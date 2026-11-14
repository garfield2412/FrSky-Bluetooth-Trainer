# FrSky Bluetooth Trainer

Windows app for flight simulators such as HELI-X. It receives 8 or 16 FrSky ETHOS trainer channels over Bluetooth LE and maps them to up to eight vJoy axes and eight configurable buttons. Tested with an X20 Pro AW running ETHOS 26.1. Independent community project.

## Download and releases

Get the portable Windows x64 application from [GitHub Releases](https://github.com/garfield2412/FrSky-Bluetooth-Trainer/releases). Preview builds are marked as prereleases. Download the Windows-x64 ZIP, extract it and run **FrSky Bluetooth Trainer.exe**. Python is included in the EXE.

Install [vJoy](https://github.com/BrunnerInnovation/vJoy/releases/tag/v2.2.2.0) separately and configure device 1 as described below. The preview is unsigned, so Windows SmartScreen may display a prompt.

The EXE saves settings in `%LOCALAPPDATA%/FrSky Bluetooth Trainer/config.xml`. On first use it imports an existing `config.xml` beside the EXE. Place your existing configuration beside the EXE before the first start to migrate it.

## Install from source

You need Windows 10 or 11 on an x64 PC with Bluetooth LE, a FrSky radio with Bluetooth trainer mode, and vJoy.

1. In the GitHub repository, choose **Code → Download ZIP** and extract the ZIP to a folder you can write to. Open the extracted folder containing `requirements.txt`. You can also clone the repository with Git.
2. Install **Python 3.14** using the **Windows installer (64-bit)**. Include pip, Tcl/Tk and the Python launcher. Open a new PowerShell window after installation. [Python for Windows](https://www.python.org/downloads/windows/)
3. Open PowerShell in the extracted folder and run:

   ```powershell
   py -3.14 --version
   py -3.14 -m pip install -r requirements.txt
   ```

4. In the vJoy release's **Assets** section, download and run `vJoySetup_v2.2.2.0_Win10_Win11.exe`. Open **Configure vJoy** from the Windows Start menu or from the app under **Help → Install vJoy**. Select device 1 and enable **X, Y, Z, Rx, Ry, Rz, Slider and Dial**. If you plan to map buttons, enable at least as many as the highest button number you want to use. Click **Apply**. To verify the installation before starting the app, press **Win+R** and enter `joy.cpl`. From the app, click **Windows game controllers** next to **Bluetooth details** or in the channel mapping dialog. Select **vJoy Device** and open **Properties** to test axes and buttons. [vJoy release](https://github.com/BrunnerInnovation/vJoy/releases/tag/v2.2.2.0)

## First connection

1. Enable Bluetooth in Windows. On your radio, open **Model → Trainer**, add a **Bluetooth** link with **+**, enable it and select **Slave**. Choose **CH1–CH8** or **CH1–CH16**, if available. [ETHOS Bluetooth trainer manual](https://ethos-doc.frsky-rc.com/model-setup/trainer/#bluetooth)
2. Double-click `FrSky Bluetooth Trainer.cmd`. Click **Find transmitters**, select your radio and click **Connect**. The app connects directly through Bluetooth LE. Windows audio pairing is unnecessary.
3. Wait for **Ready**, then open **Live channels** and move a stick to verify the input. In your simulator, select and calibrate **vJoy Device**. To use switches as buttons, assign them under **Map channels → vJoy buttons** and bind the corresponding buttons in the simulator.

- **Live channels → vJoy output** shows the source channel and driver value for each axis, the mapped button states and the last write status.
- **Map channels → vJoy buttons** supports low (≤ 1300 µs), middle (1301–1699 µs) and high (≥ 1700 µs) positions.
- In **Map channels**, use **Copy mapping from**, **Import mapping** or **Export mapping** to reuse assignments. The XML export contains only the draft axis and button mapping. Click **Apply** to save a copied or imported draft.
- **Bluetooth details** shows the latest, mean and longest interval between valid trainer frames received by the app. It also shows how long ago the latest frame arrived and whether vJoy was neutralized after a gap. **Copy diagnostics** copies the build ID, status, frame statistics and last error category without transmitter addresses or local paths. The frame statistics describe data arrival, not end-to-end latency.

If the launcher closes without opening a window, run `py -3.14 FrSkyApp.pyw` from PowerShell to see the startup error. If it reports a missing Python package, rerun the dependency installation command above.

The GUI and help are available in German, English and French. **System language** follows the Windows display language and falls back to English. You can also select a language manually.

Transmitter profiles, language and simulator paths are stored locally in `config.xml`. The app includes live channel meters, per-transmitter channel mapping and a Windows notification-area menu. To use the console, run `py -3.14 -u test_frsky_ble.py --address AA:BB:CC:DD:EE:FF`. Omit `--address` to use the last connected transmitter from the configuration.

Disconnect before searching for another transmitter. Simulator launch from the window or tray is available once the controls are ready. Use ⋯ beside the transmitter or simulator list to manage its entries. The channel mapping dialog shows each assigned button’s activation range in yellow and marks the live input when available. A brief interruption resets vJoy inputs after 500 ms. Bluetooth reconnects after five seconds without a valid frame.

For implementation and testing details, see the [technical documentation](docs/TECHNICAL.md).

## Latency

The Bluetooth path includes transmission from the radio, Windows BLE notification delivery, the bridge, vJoy, and the simulator's input and rendering loop. A wired USB joystick uses the radio's USB HID reporting path. The total latency and the difference between these paths depend on the radio, PC and simulator. Connection setup and reconnect times are separate from the delay of an input during normal operation.

The bridge now sends changed channel values to vJoy as soon as it decodes a valid BLE notification. The live display is limited to about 20 updates per second. The previous implementation checked for changes every 50 ms and forwarded only the latest values at each check.

## Acknowledgments

[BTWifiSerial](https://github.com/Amigache/BTWifiSerial) served as a reference for the FrSky BLE trainer frame format. The app uses [Bleak](https://github.com/hbldh/bleak), [vJoy](https://github.com/BrunnerInnovation/vJoy), [Pillow](https://github.com/python-pillow/Pillow) and [pystray](https://github.com/moses-palmer/pystray).
