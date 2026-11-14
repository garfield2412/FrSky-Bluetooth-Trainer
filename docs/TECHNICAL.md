# Technical documentation

## Scope and entry points

FrSky Bluetooth Trainer is a Windows desktop application that receives FrSky ETHOS trainer data over Bluetooth LE and presents mapped inputs through vJoy. The GUI supports 8- and 16-channel frames. It drives up to eight axes and eight configured buttons on vJoy device 1.

| File | Responsibility |
| --- | --- |
| `FrSky Bluetooth Trainer.cmd` | Finds 64-bit Python 3.14 with Tkinter and starts the GUI without a console. |
| `FrSkyApp.pyw` | Tkinter GUI, BLE connection worker, sender profiles, tray menu, Windows autostart and simulator launcher. |
| `test_frsky_ble.py` | Shared frame decoder and standalone console monitor. The console accepts 8 or 16 input channels and has optional axis output via `--vjoy`. |
| `vjoy_output.py` | Loads the installed vJoy DLL through ctypes, acquires device 1 and writes axes and buttons. |
| `languages.json` | GUI text and help for German, English and French. |
| `requirements.txt` | Python dependencies. vJoy is installed separately. |

## BLE connection and decoding

The sender is configured under **Model → Trainer → Bluetooth → Slave**. The app connects with Bleak using Windows WinRT and subscribes to characteristic `FFF6` on service `FFF0`. Both use the standard Bluetooth base UUID. Windows audio pairing is separate from this trainer connection.

The decoder accepts frames delimited by `0x7E`. Byte `0x7D` escapes the following byte, which is XORed with `0x20`. The unescaped body begins with `0x80` and ends with an XOR checksum. The XOR of the full body must be zero. Eight-channel bodies are 14 bytes long and 16-channel bodies are 26 bytes long. Two channels are packed into each three-byte group. The decoder can assemble a frame across notifications. Both formats were captured from an X20 Pro AW running ETHOS 26.1. A separate 24-channel format has not been verified.

The GUI runs Bluetooth operations on a background asyncio loop. Commands are serialized when replacing a connection or scan, and worker events pass through a queue to Tkinter's main thread. The GUI reports Ready after the first successful vJoy write. It retries the trainer service once using the discovered device before scanning again. An explicit disconnect cancels automatic reconnect. After 500 ms without a valid frame, the GUI bridge centers axes and releases assigned buttons. A fresh frame restores output even if its values match the last frame. The watchdog continues to check the deadline after neutralization, so a second interruption gets its own timeout. The reset attempts to release every assigned button even if one fails. Cleanup preserves an error already being handled. After five seconds without a valid frame, the bridge reconnects. New transmitter scans are disabled during a connection or connection attempt. The status text and live notebook reserve their layout space across connection states. The window stays hidden while the app measures all supported languages and settles the initial layout. It opens at the final width or stays hidden for tray startup. Manual resizing and maximizing are disabled. Toggling the live view adjusts the window height automatically. The indeterminate progress animation runs behind the status text above the Bluetooth tools.

## vJoy mapping and timing

The localized Help dialog opens the graphical Configure vJoy utility (`vJoyConf.exe`) from standard Program Files locations. If it cannot find the utility, it points to the installer link and the Windows Start menu.

- The input frame provides up to 16 channels. Each of the eight axes can select its source channel independently.
- Axes are X, Y, Z, Rx, Ry, Rz, Slider and Dial. The mapping dialog describes each axis in plain language and retains its vJoy identifier in parentheses. The label describes the virtual axis, while the transmitter mapping determines its function. Raw values from 988 to 2012 map linearly to the driver's reported axis range. Values outside that span are clamped.
- Each assigned button selects a channel and active range. The ranges are ≤ 1300 µs, 1301–1699 µs and ≥ 1700 µs. vJoy receives a Boolean button state. The button stays pressed while the condition holds.
- Each axis row previews the live value of the channel currently selected in its dropdown. The preview is independent of guided detection and goes blank when the channel has no live data.
- Guided mapping can assign a detected channel to an axis or a button. For a button, it fills the source dropdown and keeps the chosen activation threshold. Apply saves the new mapping before closing the dialog and reconnects only when that transmitter is the connection target.
- The mapping dialog highlights each active button in yellow using the selected transmitter's live channels and the current dropdown selections. The meter beside each assigned button marks its activation range in yellow and overlays the current pulse position when available. This previews unsaved mappings. The Live Channels button tab appears after the channel tabs and lists only mapped buttons, using the connection target while connecting or connected and the selected transmitter otherwise. Without live data it shows a placeholder. When the driver receives updates, the tab shows the states written to vJoy.
- Assigned buttons require their corresponding button numbers to exist in Configure vJoy. The app releases assigned buttons and centers axes when resetting or relinquishing the device.
- Changed values are written from the BLE callback. GUI updates are coalesced on a 50 ms display timer and delivered through the Tkinter queue. The **vJoy output** tab displays axis values and button states from successful driver writes on the same display cadence. It clears the live values on neutralization or disconnect and reports driver write errors. The console monitor has its own display loop. It preserves the original error and reports a second error separately if vJoy cleanup fails.

Bluetooth details samples decoded trainer-frame arrival on the worker’s monotonic clock, including repeated values. It publishes the latest, mean and largest completed interval on a 250 ms display cadence, with immediate updates for the first two frames and after neutralization. It resets the statistics when a BLE session is opened. The diagnostics dialog shows frame age and neutralization state. Its clipboard report includes a source build ID, status, frame metrics and an error category. It excludes raw errors, addresses and paths. Frames decoded from one notification can arrive very close together in the app.

## Configuration and Windows integration

The header uses local FrSky and [ETHOS logo assets](https://ethos.frsky-rc.com/wp-content/uploads/2020/07/ETHOS-logo.png). The ETHOS logo has a dark background so its white lettering stays visible. Each logo opens its respective official site.

The source GUI reads and writes `config.xml` next to the script. The frozen EXE uses `%LOCALAPPDATA%/FrSky Bluetooth Trainer/config.xml` and imports a config.xml or legacy transmitter-list.json beside the EXE on first use. Bundled logos and translations resolve relative to __file__. Each transmitter entry stores its BLE address, name, axis order and button assignments. The mapping dialog requires a valid channel selection for every axis before saving. When loading config.xml, an invalid mapping falls back to CH1–CH8 and no button assignments for the affected transmitter. Other profiles and preferences are retained. A positive button channel selects the upper threshold, a negative one selects the lower threshold a channel with an `m` suffix selects the middle range, and zero leaves that slot unassigned. **Map channels** can copy another transmitter’s mapping or import and export versioned `frsky-mapping` XML with only axis channels and button assignments. Import and copy load a draft. Apply persists it to the selected transmitter. Simulator entries store a display name and a local path to an EXE, BAT, CMD or LNK. The application also stores language, startup view and simulator auto-launch preferences. The GUI retains a fallback reader for older `transmitter-list.json` files.

Windows autostart is opt-in and uses the current user's Run registry key. The autostart command marks a Windows sign-in launch so the simulator auto-launch preference for sign-in can be applied separately. A session-local mutex prevents duplicate GUI instances. The ⋯ menus beside the transmitter and simulator selectors contain their management actions. The main window shows why simulator launch is unavailable. Simulator launches from the window or tray require the Ready state and a connected transmitter. The shared launcher enforces this condition for queued tray commands and optional automatic launches. If a queued simulator has been edited or removed, its old entry is discarded. Closing the main window hides it to the tray. The tray icon shows Disconnected (cross), Connecting (three dots), or Connected (check mark). Connected requires a successful vJoy write. Standalone transmitter discovery keeps the tray disconnected. Connection controls refresh the native tray menu when the selection or connection state changes. After a manual disconnect, Connect becomes available again for the selected transmitter. **Exit** closes the BLE session and releases vJoy.

## Localization

`languages.json` is loaded from the app directory. Each locale defines its display name, Windows primary language ID, message translations and five help paragraphs. German message strings in the GUI serve as lookup keys. Keep named placeholders and format specifiers intact. To add a language, add its entry to the catalog and include translations for the English catalog's keys. Missing translations fall back to English and then the original text. System mode uses the primary language of the Windows display language and falls back to English. An explicit selection overrides it and is stored in `config.xml`.

## Verification

From a Windows checkout with the Python dependencies installed:

```powershell
py -3.14 -m py_compile FrSkyApp.pyw test_frsky_ble.py vjoy_output.py
py -3.14 test_frsky_ble.py --help
git diff --check
```

For decoder changes, exercise both frame sizes, fragmented notifications and invalid checksums. For GUI changes, check all supported languages, an empty sender list and disconnected, connecting and ready states. Simulated packets can verify mappings and status indicators without acquiring vJoy.

For hardware verification, fully exit the GUI before running the console against the same sender. Check live channel motion in both trainer modes, then check axis motion and assigned buttons in vJoy Monitor or the Windows Game Controllers panel (`joy.cpl`), opened from the **Windows game controllers** button in the main window or in the channel mapping dialog. The shortcut is available independently of the BLE and vJoy connection states. Confirm buttons release on disconnect and verify the final bindings in the simulator. Record which stages were exercised with actual hardware.

## Release build

Install requirements-build.txt on Windows x64 with Python 3.14. Run `python scripts/build_release.py --version 0.1.0`. PyInstaller creates a windowed single-file EXE with logos and translations, runs the EXE resource/Tk smoke test, then packages it with the README and creates a SHA-256 checksum. User settings are excluded.

The Windows release workflow runs on version tags or manual dispatch for an existing tag. It builds the archive and checksum on Windows and creates a draft prerelease. Review docs/RELEASE_NOTES.md and complete hardware and clean-Windows verification before publishing. The frozen autostart command uses sys.executable. The single-instance mutex is shared with source launches.
