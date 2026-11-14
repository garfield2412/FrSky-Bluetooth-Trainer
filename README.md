# FrSky Bluetooth Trainer

[Deutsch](#deutsch) · [English](#english)

## Deutsch

Windows-App für Flugsimulatoren wie HELI-X. Sie empfängt bis zu acht FrSky-ETHOS-Trainerkanäle direkt per Bluetooth LE und gibt sie als virtuellen Joystick über vJoy aus. Getestet mit X20 Pro AW und ETHOS 26.1. Unabhängiges Community-Projekt.

1. Installiere Python 3.14 x64 mit Tkinter und führe im Projektordner `py -3.14 -m pip install -r requirements.txt` aus.
2. Lade den Windows-Installer unter **Assets** herunter. Aktiviere in **Configure vJoy** für Gerät 1 die Achsen X, Y, Z, Rx, Ry, Rz, Slider und Dial. [vJoy-Release](https://github.com/BrunnerInnovation/vJoy/releases/tag/v2.2.2.0)
3. Öffne am Sender **Modell → Trainer**, füge über **+** einen Bluetooth-Link hinzu und aktiviere ihn mit **Slave** und **CH1–CH8**. [ETHOS-Handbuch](https://ethos-doc.frsky-rc.com/model-setup/trainer/#bluetooth)
4. Starte `FrSky Bluetooth Trainer.cmd`. Wähle **Sender suchen**, deinen Sender und **Verbinden**. Sobald **Bereit** erscheint, wähle und kalibriere **vJoy Device** im Simulator.

Senderprofile, Sprache und Simulatorpfade werden lokal in `config.xml` gespeichert. Die App bietet eine Live-Kanalanzeige, Kanalzuordnung pro Sender und ein Menü im Windows-Infobereich. Die Konsolenvariante lässt sich mit `py -3.14 -u test_frsky_ble.py --address AA:BB:CC:DD:EE:FF` starten. Ohne `--address` verwendet sie den zuletzt verbundenen Sender aus der Konfiguration.

## English

Windows app for flight simulators such as HELI-X. It receives up to eight FrSky ETHOS trainer channels directly over Bluetooth LE and forwards them to vJoy. Tested with an X20 Pro AW running ETHOS 26.1. Independent community project.

1. Install 64-bit Python 3.14 with Tkinter. In the project directory, run `py -3.14 -m pip install -r requirements.txt`.
2. Download the Windows installer under **Assets**. In **Configure vJoy**, enable X, Y, Z, Rx, Ry, Rz, Slider and Dial for device 1. [vJoy release](https://github.com/BrunnerInnovation/vJoy/releases/tag/v2.2.2.0)
3. On the radio, open **Model → Trainer**, add a Bluetooth link with **+**, enable it and select **Slave** and **CH1–CH8**. [ETHOS manual](https://ethos-doc.frsky-rc.com/model-setup/trainer/#bluetooth)
4. Open `FrSky Bluetooth Trainer.cmd`. Click **Find transmitters**, select the radio and click **Connect**. Once it shows **Ready**, select and calibrate **vJoy Device** in your simulator.

Transmitter profiles, language and simulator paths are stored locally in `config.xml`. The app includes live channel meters, per-transmitter channel mapping and a Windows notification-area menu. To use the console, run `py -3.14 -u test_frsky_ble.py --address AA:BB:CC:DD:EE:FF`. Omit `--address` to use the last connected transmitter from the configuration.

## Acknowledgments

[BTWifiSerial](https://github.com/Amigache/BTWifiSerial) served as a reference for the FrSky BLE trainer frame format. The app uses [Bleak](https://github.com/hbldh/bleak), [vJoy](https://github.com/BrunnerInnovation/vJoy), [Pillow](https://github.com/python-pillow/Pillow) and [pystray](https://github.com/moses-palmer/pystray).
