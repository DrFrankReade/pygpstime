"""
GPS Time Sync - Attempting ~0.1s accuracy without PPS

Key Features:
- High Baud Rate selection to reduce serial latency.
- Midpoint timestamping with perf_counter for minimal jitter.
- Only error pop-ups; all other statuses shown in a scrolled text box.
- Automatic or manual connect, auto-sync, local or UTC clock setting.
- Stores config in config.json.

Disclaimers:
- True ±0.1s accuracy is challenging without PPS.
- Real-world performance depends on the GPS's NMEA transmission timing, OS scheduling, etc.
"""

import os
import json
import time
import threading
import datetime
import tkinter as tk
from tkinter import ttk, messagebox
from tkinter.scrolledtext import ScrolledText

import serial
import serial.tools.list_ports
import pynmea2

import ctypes
from ctypes import wintypes

CONFIG_FILENAME = "config.json"

# Windows-specific structure for SetSystemTime / SetLocalTime
class SYSTEMTIME(ctypes.Structure):
    _fields_ = [
        ("wYear", wintypes.WORD),
        ("wMonth", wintypes.WORD),
        ("wDayOfWeek", wintypes.WORD),
        ("wDay", wintypes.WORD),
        ("wHour", wintypes.WORD),
        ("wMinute", wintypes.WORD),
        ("wSecond", wintypes.WORD),
        ("wMilliseconds", wintypes.WORD),
    ]

def set_system_time_utc(dt_utc: datetime.datetime):
    """Set system clock in UTC (naive datetime)."""
    st = SYSTEMTIME()
    st.wYear = dt_utc.year
    st.wMonth = dt_utc.month
    st.wDay = dt_utc.day
    st.wDayOfWeek = 0
    st.wHour = dt_utc.hour
    st.wMinute = dt_utc.minute
    st.wSecond = dt_utc.second
    st.wMilliseconds = int(dt_utc.microsecond / 1000)
    try:
        ctypes.windll.kernel32.SetSystemTime(ctypes.byref(st))
    except Exception as e:
        raise OSError(f"Failed to set system time (UTC): {e}")

def set_system_time_local(dt_local: datetime.datetime):
    """Set system clock in local time (naive datetime)."""
    st = SYSTEMTIME()
    st.wYear = dt_local.year
    st.wMonth = dt_local.month
    st.wDay = dt_local.day
    st.wDayOfWeek = 0
    st.wHour = dt_local.hour
    st.wMinute = dt_local.minute
    st.wSecond = dt_local.second
    st.wMilliseconds = int(dt_local.microsecond / 1000)
    try:
        ctypes.windll.kernel32.SetLocalTime(ctypes.byref(st))
    except Exception as e:
        raise OSError(f"Failed to set system time (Local): {e}")

class GpsTimeSyncApp:
    def __init__(self, root):
        self.root = root
        self.root.title("GPS Time Sync")

        # Default / loaded config
        self.config = {
            "com_port": "",
            "auto_connect_sync": False,
            "sync_interval_minutes": 30,
            "use_local_time": True,
            "baud_rate": 9600   # New config parameter for higher accuracy
        }
        self.load_config()

        # Tkinter variables
        self.selected_port = tk.StringVar(value=self.config.get("com_port", ""))
        self.auto_connect_var = tk.BooleanVar(value=self.config.get("auto_connect_sync", False))
        self.sync_interval_var = tk.StringVar(value=str(self.config.get("sync_interval_minutes", 30)))
        self.use_local_time_var = tk.BooleanVar(value=self.config.get("use_local_time", True))
        self.selected_baud = tk.StringVar(value=str(self.config.get("baud_rate", 9600)))

        # Display variables
        self.gps_time_str = tk.StringVar(value="--:--:--")
        self.computer_time_str = tk.StringVar(value="--:--:--")
        self.delta_time_str = tk.StringVar(value="--")

        # Thread / Serial
        self.app_running = True
        self.keep_reading = False
        self.read_thread = None
        self.ser = None

        # Last GPS time in naive UTC
        self.last_gps_utc = None
        # Last delta T measurement
        self.last_delta_sec = None

        # For midpoint timing
        # We'll record a reference "perf_counter()" and "datetime.now()" at startup
        self.perf_base = time.perf_counter()
        self.time_base = datetime.datetime.now()

        self.build_gui()
        self.refresh_ports()

        if self.auto_connect_var.get():
            self.connect_to_gps()

        self.update_display_loop()
        self.schedule_auto_sync()

    # --------------------------------------------------
    # GUI Setup
    # --------------------------------------------------
    def build_gui(self):
        port_frame = ttk.LabelFrame(self.root, text="Port Selection")
        port_frame.pack(fill="x", padx=5, pady=5)

        ttk.Label(port_frame, text="GPS COM Port:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.port_combo = ttk.Combobox(port_frame, textvariable=self.selected_port, width=12)
        self.port_combo.grid(row=0, column=1, padx=5, pady=5)

        ttk.Button(port_frame, text="Refresh Ports", command=self.refresh_ports).grid(row=0, column=2, padx=5, pady=5)
        ttk.Button(port_frame, text="CONNECT", command=self.connect_to_gps).grid(row=0, column=3, padx=5, pady=5)
        ttk.Button(port_frame, text="DISCONNECT", command=self.disconnect_from_gps).grid(row=0, column=4, padx=5, pady=5)

        # Baud Rate selection
        ttk.Label(port_frame, text="Baud:").grid(row=1, column=0, padx=(5,0), pady=5, sticky="e")
        self.baud_combo = ttk.Combobox(port_frame, textvariable=self.selected_baud,
                                       values=["4800","9600","19200","38400","57600","115200"], width=8)
        self.baud_combo.grid(row=1, column=1, padx=(0,5), pady=5, sticky="w")
        self.baud_combo.bind("<<ComboboxSelected>>", lambda e: self.save_config())

        auto_connect_check = ttk.Checkbutton(
            port_frame, text="Auto-Connect & Sync at Startup",
            variable=self.auto_connect_var, command=self.save_config
        )
        auto_connect_check.grid(row=2, column=0, columnspan=5, padx=5, pady=5, sticky="w")

        local_time_check = ttk.Checkbutton(
            port_frame, text="Use Local Time (instead of UTC)",
            variable=self.use_local_time_var, command=self.save_config
        )
        local_time_check.grid(row=3, column=0, columnspan=5, padx=5, pady=5, sticky="w")

        time_frame = ttk.LabelFrame(self.root, text="Time Information")
        time_frame.pack(fill="x", padx=5, pady=5)

        ttk.Label(time_frame, text="GPS Time (UTC):").grid(row=0, column=0, padx=5, pady=5, sticky="e")
        ttk.Label(time_frame, textvariable=self.gps_time_str).grid(row=0, column=1, padx=5, pady=5, sticky="w")

        ttk.Label(time_frame, text="Computer Time (Local):").grid(row=1, column=0, padx=5, pady=5, sticky="e")
        ttk.Label(time_frame, textvariable=self.computer_time_str).grid(row=1, column=1, padx=5, pady=5, sticky="w")

        ttk.Label(time_frame, text="Delta T (s):").grid(row=2, column=0, padx=5, pady=5, sticky="e")
        ttk.Label(time_frame, textvariable=self.delta_time_str).grid(row=2, column=1, padx=5, pady=5, sticky="w")

        ttk.Button(time_frame, text="SYNC to GPS", command=self.sync_time).grid(row=3, column=0, columnspan=2, padx=5, pady=5)

        auto_sync_frame = ttk.LabelFrame(self.root, text="Automatic Sync")
        auto_sync_frame.pack(fill="x", padx=5, pady=5)

        ttk.Label(auto_sync_frame, text="Sync Interval (minutes):").grid(row=0, column=0, padx=5, pady=5, sticky="e")
        ttk.Entry(auto_sync_frame, textvariable=self.sync_interval_var, width=5).grid(row=0, column=1, padx=5, pady=5, sticky="w")
        ttk.Button(auto_sync_frame, text="Apply", command=self.apply_auto_sync_interval).grid(row=0, column=2, padx=5, pady=5)

        # Status / Log
        status_frame = ttk.LabelFrame(self.root, text="Status")
        status_frame.pack(fill="both", expand=True, padx=5, pady=5)

        self.status_box = ScrolledText(status_frame, wrap='word', height=5, state='disabled')
        self.status_box.pack(fill='both', expand=True)

    def log_status(self, message: str):
        """Append a line to the status text box without any pop-up for user actions."""
        self.status_box.configure(state='normal')
        self.status_box.insert('end', message + '\n')
        self.status_box.see('end')
        self.status_box.configure(state='disabled')

    # --------------------------------------------------
    # Refresh Ports
    # --------------------------------------------------
    def refresh_ports(self):
        ports = serial.tools.list_ports.comports()
        port_list = [p.device for p in ports]
        self.port_combo['values'] = port_list
        self.log_status("Ports refreshed.")

    # --------------------------------------------------
    # Connect / Disconnect
    # --------------------------------------------------
    def connect_to_gps(self):
        if self.read_thread and self.read_thread.is_alive():
            self.log_status("Already connected.")
            return

        selected = self.selected_port.get()
        if not selected:
            messagebox.showerror("Error", "No COM port selected!")
            return

        self.config["com_port"] = selected
        self.save_config()

        self.keep_reading = True
        self.read_thread = threading.Thread(target=self.gps_thread_loop, daemon=True)
        self.read_thread.start()

        self.log_status(f"Connecting to {selected} at baud={self.selected_baud.get()}...")

    def disconnect_from_gps(self):
        self.keep_reading = False
        if self.read_thread and self.read_thread.is_alive():
            self.read_thread.join(timeout=2.0)

        if self.ser and self.ser.is_open:
            try:
                self.ser.close()
            except:
                pass
        self.ser = None
        self.read_thread = None

        self.log_status("Disconnected from GPS.")

    # --------------------------------------------------
    # Background Thread
    # --------------------------------------------------
    def gps_thread_loop(self):
        """
        Reads lines from the GPS device and calculates Delta T
        more precisely by using perf_counter-based midpoint times.
        """
        first_valid_time_received = False

        # Convert user's string to int for baud rate
        try:
            baud = int(self.selected_baud.get())
        except ValueError:
            baud = 9600

        while self.app_running and self.keep_reading:
            if not self.ser or not self.ser.is_open:
                try:
                    self.ser = serial.Serial(
                        self.config["com_port"],
                        baudrate=baud,
                        timeout=1
                    )
                except Exception as e:
                    self.log_status(f"Error opening port: {e}")
                    time.sleep(3)
                    continue

            try:
                # We measure time before & after reading the line
                t_start = time.perf_counter()
                line = self.ser.readline().decode('ascii', errors='replace').strip()
                t_end = time.perf_counter()

                if not line:
                    continue

                # Midpoint in perf_counter domain
                t_mid = (t_start + t_end) / 2.0
                # Convert that midpoint to a datetime object
                system_time_at_mid = self.perf_to_system_time(t_mid)

                if line.startswith("$GPRMC") or line.startswith("$GNRMC"):
                    try:
                        msg = pynmea2.parse(line)
                        if msg.is_valid:
                            gps_utc = self.convert_nmea_to_datetime(msg)
                            if gps_utc:
                                self.last_gps_utc = gps_utc
                                # Show the GPS time in UTC
                                utc_str = gps_utc.strftime("%Y-%m-%d %H:%M:%S UTC")
                                self.gps_time_str.set(utc_str)

                                # Convert GPS UTC -> local offset-aware
                                gps_local_aware = gps_utc.replace(tzinfo=datetime.timezone.utc).astimezone()
                                # Convert system_time_at_mid -> local offset-aware
                                sys_local_aware = system_time_at_mid.astimezone()

                                # Compute offset in seconds
                                dt_sec = (gps_local_aware - sys_local_aware).total_seconds()
                                self.last_delta_sec = dt_sec

                                # Auto-sync on first fix if requested
                                if self.auto_connect_var.get() and not first_valid_time_received:
                                    self.sync_time(gps_utc)
                                    first_valid_time_received = True
                    except pynmea2.ParseError:
                        pass

            except Exception as e:
                # Possibly disconnected
                self.log_status(f"Read error: {e}")
                if self.ser:
                    try:
                        self.ser.close()
                    except:
                        pass
                self.ser = None
                time.sleep(3)

    def perf_to_system_time(self, pc_time: float) -> datetime.datetime:
        """
        Convert a perf_counter time to the approximate system datetime by referencing
        the initial offset at app startup. This helps reduce jitter from read times.
        """
        # The difference from startup
        delta_sec = pc_time - self.perf_base
        # Convert to a timedelta
        td = datetime.timedelta(seconds=delta_sec)
        # Add to the reference system time
        return self.time_base + td

    def convert_nmea_to_datetime(self, rmc_msg):
        """Parse RMC datestamp+timestamp into a naive UTC datetime object."""
        if rmc_msg.datestamp and rmc_msg.timestamp:
            return datetime.datetime.combine(rmc_msg.datestamp, rmc_msg.timestamp)
        return None

    # --------------------------------------------------
    # Display Update Loop
    # --------------------------------------------------
    def update_display_loop(self):
        now_local = datetime.datetime.now()
        self.computer_time_str.set(now_local.strftime("%Y-%m-%d %H:%M:%S"))

        if self.last_delta_sec is not None:
            self.delta_time_str.set(f"{self.last_delta_sec:.2f}")
        else:
            self.delta_time_str.set("--")

        self.root.after(500, self.update_display_loop)

    # --------------------------------------------------
    # Sync to GPS
    # --------------------------------------------------
    def sync_time(self, gps_utc=None):
        if gps_utc is None:
            if self.last_gps_utc is not None:
                gps_utc = self.last_gps_utc
            else:
                label_str = self.gps_time_str.get()
                if "UTC" not in label_str:
                    messagebox.showerror("Sync Error", "No valid GPS time available.")
                    return
                try:
                    dt_str = label_str.replace(" UTC", "")
                    gps_utc = datetime.datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    messagebox.showerror("Sync Error", "No valid GPS time available.")
                    return

        try:
            if self.use_local_time_var.get():
                # Convert naive UTC -> offset-aware local -> naive local
                local_aware = gps_utc.replace(tzinfo=datetime.timezone.utc).astimezone()
                local_naive = local_aware.replace(tzinfo=None)
                set_system_time_local(local_naive)
                self.log_status(f"System time set to LOCAL: {local_naive.isoformat()}")
            else:
                # gps_utc is naive UTC
                set_system_time_utc(gps_utc)
                self.log_status(f"System time set to UTC: {gps_utc.isoformat()}")
        except Exception as e:
            messagebox.showerror("Sync Error", str(e))

    # --------------------------------------------------
    # Auto-Sync
    # --------------------------------------------------
    def apply_auto_sync_interval(self):
        try:
            minutes = float(self.sync_interval_var.get())
            self.config["sync_interval_minutes"] = minutes
            self.save_config()
            self.log_status(f"Auto-sync interval set to {minutes} minute(s).")
            self.schedule_auto_sync()
        except ValueError:
            messagebox.showerror("Error", "Invalid sync interval. Please enter a numeric value.")

    def schedule_auto_sync(self):
        minutes = self.config.get("sync_interval_minutes", 30)
        interval_ms = int(minutes * 60 * 1000)
        self.root.after(interval_ms, self.auto_sync_callback)

    def auto_sync_callback(self):
        self.sync_time()
        self.schedule_auto_sync()

    # --------------------------------------------------
    # Config
    # --------------------------------------------------
    def load_config(self):
        if os.path.exists(CONFIG_FILENAME):
            try:
                with open(CONFIG_FILENAME, "r") as f:
                    self.config = json.load(f)
            except Exception as e:
                messagebox.showerror("Config Error", f"Failed to load config: {e}")

    def save_config(self):
        self.config["com_port"] = self.selected_port.get()
        self.config["auto_connect_sync"] = self.auto_connect_var.get()
        self.config["use_local_time"] = self.use_local_time_var.get()
        # Also store selected baud
        try:
            self.config["baud_rate"] = int(self.selected_baud.get())
        except ValueError:
            self.config["baud_rate"] = 9600

        try:
            with open(CONFIG_FILENAME, "w") as f:
                json.dump(self.config, f, indent=4)
        except Exception as e:
            messagebox.showerror("Config Error", f"Failed to save config: {e}")

    # --------------------------------------------------
    # Closing
    # --------------------------------------------------
    def on_close(self):
        self.app_running = False
        self.disconnect_from_gps()
        self.root.destroy()

def main():
    root = tk.Tk()
    app = GpsTimeSyncApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()

if __name__ == "__main__":
    main()
