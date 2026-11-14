Portable Windows x64 preview v0.1.3.

Changes
- Added guided vJoy setup with Install vJoy, Open download page and Later actions.
- The pinned vJoy 2.2.2.0 download is checked against its size and SHA-256 before requesting administrator permission.
- Added download progress and driver availability checks after setup.
- Fixed the disabled install button after an unsuccessful automatic connection attempt.
- Setup and help are available in German, English and French.

Download the Windows-x64 ZIP, extract it, and run FrSky Bluetooth Trainer.exe. Python and its dependencies are included.

vJoy is required. Install it from the setup dialog or get it from the BRUNNER release page.
https://github.com/BrunnerInnovation/vJoy/releases/tag/v2.2.2.0

Configure device 1 with the required axes and buttons after installation. Windows may require a restart.

Settings are stored in %LOCALAPPDATA%/FrSky Bluetooth Trainer/config.xml. An existing config.xml beside the EXE is imported on first use.

This preview is unsigned. Windows SmartScreen may display a prompt.

Verification includes the actual installer download and checksum, simulated failure cases and localized UI states, plus the packaged EXE resource/icon smoke test. Full installer execution and a clean Windows installation remain to be verified.
