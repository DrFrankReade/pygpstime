# GPS Time Sync with Midpoint Timestamping (High-Accuracy NMEA Reader)

This program uses Python, Tkinter, and pySerial/pynmea2 to connect to a GPS device over a serial port, parse NMEA sentences for time, and then synchronize the computer’s clock to the GPS time. It aims to achieve roughly **±0.1s** accuracy in typical scenarios **without** needing a Pulse-Per-Second (PPS) signal. All non-error notifications are written to a status/log text box, allowing for near “hands-off” operation.

---

## Features

- **High Baud Rate Support**  
  Supports selecting a baud rate up to **115200** to reduce data transmission delays, which can improve synchronization accuracy.

- **Midpoint Timestamping**  
  Uses Python’s high-resolution `time.perf_counter()` to estimate the exact arrival time of each NMEA sentence, reducing jitter from read overhead.

- **Auto-Connect & Auto-Sync**  
  Can be configured to automatically connect and synchronize on program startup, with periodic re-synchronization (in minutes).

- **Local or UTC System Time**  
  Allows the user to set the Windows system clock in either local time or UTC.

- **Minimal Popup Dialogs**  
  Only critical errors produce a pop-up (`messagebox.showerror`). Informational messages (e.g., “Connecting…”, “Sync completed.”) are written to a scrollable status box.

- **Persistent Configuration**  
  Remembers user-selected COM port, baud rate, sync interval, and other preferences in a local JSON file (`config.json`).

---

## Requirements

1. **Python 3.6+** (recommended for `time.perf_counter()`, though earlier versions might still work).  
2. **Administrator Privileges on Windows**  
   - Setting the system time requires elevated (admin) privileges.  
3. **pySerial** and **pynmea2**  
   - Installed via [pip](https://pypi.org/project/pip/).

---

## Installation

1. **Install Python** (version 3.6 or higher).  
2. **Install Dependencies**:

   ```bash
   pip install pyserial
   pip install pynmea2
   ```

3. **Obtain the Script**  
   - Place the `.py` file (the program) in a convenient folder.  

4. **Run the Program**:

   ```bash
   python your_program_name.py
   ```
   or open it in an IDE (VSCode, PyCharm, etc.) with Python installed.  

> **Important**: On **Windows**, to actually **set the system clock**, you **must** run the script as Administrator. For instance:
>
> ```bash
> runas /user:Administrator python your_program_name.py
> ```

---

## Usage

1. **Start the Program**  
   - The main window will appear with a compact layout (adjustable via `root.geometry(...)` in code).

2. **Select the COM Port**  
   - Click “Refresh Ports” to scan for available COM ports.
   - Choose the COM port connected to your GPS device (e.g., `COM3`, `COM4`, etc.).

3. **Choose a Baud Rate**  
   - Default is **9600**. Many GPS units allow higher speeds (4800, 19200, 38400, 115200).
   - Faster baud rates can improve time accuracy by reducing transmission delays.

4. **Auto-Connect & Sync at Startup** (optional)  
   - Checking this box means next time you launch the program, it automatically connects and syncs without user clicks (unless there’s an error).

5. **Use Local Time (instead of UTC)**  
   - If checked, the system clock is set in local time.
   - Otherwise, it sets the system clock in UTC. (Requires the system to be configured for a UTC-based hardware clock.)

6. **CONNECT**  
   - Click “CONNECT” to open the port. The program reads `$GPRMC` / `$GNRMC` lines, parsing GPS time.
   - **GPS Time (UTC)** is displayed, along with your **Computer Time (Local)** and **Delta T (s)**.

7. **SYNC to GPS**  
   - Click this button to set your system clock (either local or UTC).
   - If auto-connect is enabled, the system clock is automatically synced after the first valid GPS fix.

8. **Auto-Sync Interval**  
   - Enter a value in minutes and click “Apply.”  
   - The program re-syncs periodically at that interval.  
   - Status messages appear in the scrolling text box at the bottom.

9. **Disconnect**  
   - Click “DISCONNECT” to stop reading from the GPS.  

10. **Exit**  
    - Close the window to exit. Your settings (port, baud, auto-connect, etc.) are saved to `config.json`.

---

## How it Works

1. **Serial Reading & Midpoint Timestamp**  
   - A background thread opens the COM port and reads lines.
   - Each line read is timestamped with a “midpoint time” in `time.perf_counter()` (the average of read start/end times).
   - This helps reduce Python/serial overhead from distorting the actual arrival time.

2. **Parsing & Delta T**  
   - On detecting `$GPRMC` or `$GNRMC`, the code uses `pynmea2` to parse the date and UTC time.
   - The naive UTC time from GPS is converted to local offset-aware time if needed, and the local system time (at the read midpoint) is also offset-aware. Subtracting them yields a **Delta T** in seconds.

3. **Synchronizing the Clock**  
   - On sync, Windows’ `SetSystemTime` (UTC) or `SetLocalTime` is called via `ctypes`.
   - Ensure you have **admin privileges** on Windows for this operation.

4. **Configuration**  
   - All settings are stored in `config.json`, including the selected COM port, baud rate, auto-connect, local/UTC preference, and sync interval.

---

## Accuracy Considerations

- **NMEA Delay**: Many GPS devices may output their NMEA data up to 0.3–0.5 seconds after the actual “top of second.”  
- **Higher Baud**: Minimizes serial transmission time; typically can shave off tens of milliseconds.  
- **Windows Latency**: OS scheduling can introduce small inaccuracies.  
- **No PPS**: Without a PPS line or kernel-level time sync, ±0.1–0.3s is typical. For beyond ±0.1s, a PPS-based approach is recommended.

---

## Troubleshooting

1. **Clock Not Changing**: Confirm the script is run as Administrator.  
2. **No COM Ports**: Check GPS driver installation, or re-plug the USB/serial adapter. Click “Refresh Ports.”  
3. **Garbled GPS Data**: Ensure the GPS baud rate matches the selected baud in the program.  
4. **Large Delta T**: Wait for the GPS to get a stable fix, or confirm system clock was not far off initially.  
5. **Config Errors**: If `config.json` becomes corrupted, delete it and re-configure.

---

## License

This project is licensed under the [MIT License](https://opensource.org/licenses/MIT). Please see the full text below:

```
MIT License

Copyright (c) 2023

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell  
copies of the Software, and to permit persons to whom the Software is  
furnished to do so, subject to the following conditions:  

The above copyright notice and this permission notice shall be included in  
all copies or substantial portions of the Software.  

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR  
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,  
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE  
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER  
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,  
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE  
SOFTWARE.
```
