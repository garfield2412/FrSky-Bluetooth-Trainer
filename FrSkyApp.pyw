import asyncio
import ctypes
import json
import queue
import sys
import os
import threading
import tkinter as tk
import webbrowser
import winreg
import xml.etree.ElementTree as ET
from functools import partial
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from test_frsky_ble import CHARACTERISTIC, SERVICE, BleakClient, BleakError, BleakScanner, TrainerDecoder
from vjoy_output import VJoyOutput, VJoyUnavailable

SETTINGS = Path(__file__).with_name("config.xml")
LEGACY_SETTINGS = SETTINGS.with_name("transmitter-list.json")
DEFAULT = list(range(1, 9))
FRSKY_BLACK = "#222222"
FRSKY_YELLOW = "#f5c438"

sys.path.insert(0, str(Path(__file__).with_name("tray-libs")))
import pystray
from PIL import Image, ImageDraw, ImageTk


ENGLISH = {'Sprache': 'Language',
 'Systemsprache': 'System language',
 'Sender': 'Transmitter',
 'Verbinden': 'Connect',
 'Trennen': 'Disconnect',
 'Sender suchen': 'Find transmitters',
 'Kanäle zuordnen': 'Map channels',
 'Beenden': 'Exit',
 'Getrennt': 'Disconnected',
 'Bluetooth-Details': 'Bluetooth details',
 'Live-Anzeige': 'Live channels',
 'Senderprofil konnte nicht gespeichert werden': 'Could not save transmitter profile',
 'Starte Verbindung …': 'Starting connection …',
 'Trenne Bluetooth …': 'Disconnecting Bluetooth …',
 'Suche FrSky-Sender · Trainer → Bluetooth → Slave …': 'Looking for FrSky transmitters · Trainer → Bluetooth '
                                                       '→ Slave …',
 'vJoy-Achse': 'vJoy axis',
 'Senderkanal': 'Transmitter channel',
 'Mehrfach zugeordnet: {channels}': 'Assigned more than once: {channels}',
 'Standard': 'Reset to defaults',
 'Übernehmen': 'Apply',
 'Abbrechen': 'Cancel',
 'Noch keine Bluetooth-Messwerte.': 'No Bluetooth measurements yet.',
 'Getrennt. Klicke auf Verbinden, um erneut zu starten.': 'Disconnected. Click Connect to start again.',
 '{count} mögliche Sender gefunden. Auswählen und verbinden.': 'Found {count} possible transmitters. Select '
                                                               'one and click Connect.',
 'Kein FrSky-Sender gefunden. Prüfe den Schülermodus.': 'No FrSky transmitter found. Check that trainer '
                                                        'slave mode is enabled.',
 'Trenne Bluetooth und gebe vJoy frei …': 'Disconnecting Bluetooth and releasing vJoy …',
 'Fehler: {error}': 'Error: {error}',
 'Suche Sender per Bluetooth …': 'Looking for the transmitter over Bluetooth …',
 'Sender gefunden. Öffne den Trainerdienst …': 'Transmitter found. Opening the trainer service …',
 'Bluetooth verbunden. Warte auf Steuerdaten …': 'Bluetooth connected. Waiting for channel data …',
 'Bereit · Steuerdaten werden an vJoy übertragen.': 'Ready · Sending channel data to vJoy.',
 'Sender noch nicht gefunden.': 'Transmitter not found yet.',
 'Trainerdienst noch nicht erreichbar.': 'Trainer service not reachable yet.',
 'Warte auf gültige Steuerdaten.': 'Waiting for valid channel data.',
 'Bluetooth-Verbindung unterbrochen.': 'Bluetooth connection interrupted.',
 '{reason} Automatischer Versuch {attempt} in {delay} s.{hint}': '{reason} Retrying automatically in {delay} '
                                                                 's (attempt {attempt}).{hint}',
 ' Prüfe den Bluetooth-Schülermodus.': ' Check that Bluetooth trainer slave mode is enabled.',
 'Sender nach {seconds:.1f} s gefunden.': 'Transmitter found after {seconds:.1f} s.',
 'Trainerdienst nach {seconds:.1f} s geöffnet.': 'Trainer service opened after {seconds:.1f} s.',
 'Erste Steuerdaten nach {seconds:.1f} s an vJoy übergeben.': 'First channel data sent to vJoy after '
                                                              '{seconds:.1f} s.',
 '{phase}: {error}': '{phase}: {error}',
 'Sendersuche': 'Transmitter discovery',
 'Trainerdienst': 'Trainer service',
 'Steuerdaten': 'Channel data',
 'Laufende Verbindung': 'Active connection',
 'Sender nicht gefunden.': 'Transmitter not found.',
 'Keine gültigen Trainerdaten.': 'No valid trainer data.',
 'Bluetooth getrennt.': 'Bluetooth disconnected.',
 'Unbekannter Sender': 'Unknown transmitter',
 'vJoy-Gerät 1 ist möglicherweise belegt. Beende das alte Bluetooth-Skript mit Strg+X und klicke auf Verbinden.': 'vJoy '
                                                                                                                  'device '
                                                                                                                  '1 '
                                                                                                                  'may '
                                                                                                                  'be '
                                                                                                                  'in '
                                                                                                                  'use. '
                                                                                                                  'Stop '
                                                                                                                  'the '
                                                                                                                  'console '
                                                                                                                  'script '
                                                                                                                  'with '
                                                                                                                  'Ctrl+X '
                                                                                                                  'and '
                                                                                                                  'click '
                                                                                                                  'Connect.',
 'vJoy hat die Achsenposition abgelehnt.': 'vJoy rejected the axis position.'}

ENGLISH.update({
    "Startdateien": "Launch files", "Simulator": "Simulator", "Starten": "Launch", "Hinzufügen": "Add",
    "Bearbeiten": "Edit", "Entfernen": "Remove", "Simulator wählen": "Select simulator",
    "Programmdatei": "Executable", "Name": "Name", "Durchsuchen": "Browse",
    "Gib einen Namen und eine vorhandene Startdatei an (.exe, .bat, .cmd oder .lnk).": "Enter a name and select an existing launch file (.exe, .bat, .cmd or .lnk).",
    "Simulator konnte nicht gestartet werden": "Could not launch simulator",
    "Simulator entfernen?": "Remove simulator?",
    "„{name}“ aus der Liste entfernen?": "Remove “{name}” from the list?",
})

SIMULATOR_TYPES = (".exe", ".bat", ".cmd", ".lnk")

ENGLISH.update({
    "Fenster öffnen": "Open window",
    "In den Infobereich": "Hide to tray",
    "Start im Infobereich": "Start in notification area",
    "Mit Windows starten": "Start with Windows",
    "Windows-Autostart konnte nicht geändert werden": "Could not change Windows startup",
    "Bereit": "Ready",
    "Verbindung wird aufgebaut": "Connecting or reconnecting",
    "Achse wählen und einen Geber bewegen.": "Select an axis and move one control.",
    "Warte auf Daten vom ausgewählten Sender.": "Waiting for data from the selected transmitter.",
    "Erkannten Kanal übernehmen": "Use detected channel",
})

ENGLISH.update({
    "Sender entfernen": "Remove transmitter",
    "„{name}“ und seine Kanalzuordnung aus der Senderliste entfernen?":
        "Remove “{name}” and its channel mapping from the transmitter list?",
})

VJOY_DOWNLOAD = "https://github.com/BrunnerInnovation/vJoy/releases/tag/v2.2.2.0"
VJOY_TITLE = "vJoy fehlt oder ist nicht aktiv"
VJOY_PROMPT = ("Lade vJoy herunter und installiere es. Wenn es bereits installiert ist, "
               "aktiviere oder repariere den Treiber. Klicke danach erneut auf Verbinden.\n\nDownloadseite öffnen?")
ENGLISH.update({
    VJOY_TITLE: "vJoy is missing or inactive",
    VJOY_PROMPT: "Download and install vJoy. If it is already installed, enable or repair the driver. "
                 "Then click Connect again.\n\nOpen the download page?",
})

ENGLISH.update({
    "Sender wechseln": "Switch transmitter",
    "Simulator starten": "Launch simulator",
    "Simulator starten, sobald die Steuerung bereit ist": "Launch simulator when controls are ready",
    "Auch bei Windows-Anmeldung": "Also at Windows sign-in",
    "Trainerdienst erneut öffnen …": "Retrying the trainer service …",
})

PROJECT_URL = "https://github.com/garfield2412/FrSky-Bluetooth-Trainer"
TRAINER_MANUAL = "https://ethos-doc.frsky-rc.com/model-setup/trainer/#bluetooth"

ENGLISH.update({
    "Hilfe": "Help",
    "Projekt auf GitHub": "Project on GitHub",
    "Unabhängiges Community-Projekt. Quellcode und Fehlermeldungen findest du auf GitHub.":
        "Independent community project. Find the source code and report issues on GitHub.",
    "So funktioniert es": "How it works",
    "vJoy installieren": "Install vJoy",
    "vJoy auf GitHub": "vJoy on GitHub",
    "Sender vorbereiten": "Set up the transmitter",
    "Am PC verbinden": "Connect on your PC",
    "Simulator einrichten": "Set up the simulator",
    "ETHOS-Handbuch: Bluetooth-Trainer": "ETHOS manual: Bluetooth trainer",
    "Schließen": "Close",
})

HELP_STEPS = {
    "de": (
        "Mit dieser App steuerst du deinen Flugsimulator kabellos mit deiner FrSky-Funke. vJoy stellt dafür in Windows einen virtuellen Joystick bereit.",
        "Öffne „vJoy auf GitHub“. Lade unter „Assets“ den Windows-Installer herunter und führe ihn aus. Öffne danach „Configure vJoy“, wähle Gerät 1 und aktiviere X, Y, Z, Rx, Ry, Rz, Slider und Dial. Klicke auf „Apply“. Mit Win+R → joy.cpl kannst du prüfen, ob „vJoy Device“ erscheint.",
        "1. Öffne auf der Funke Modell → Trainer und tippe auf +.\n"
        "2. Wähle Bluetooth und aktiviere die Verbindung.\n"
        "3. Wähle als Trainer-Modus Slave (Schüler) und als Kanalbereich CH1–CH8.",
        "Schalte Bluetooth in Windows ein. Klicke in der App auf „Sender suchen“, wähle deine Funke und klicke auf „Verbinden“. Sobald „Bereit“ erscheint, kannst du loslegen.",
        "Öffne die „Live-Anzeige“ und bewege einen Knüppel. Bewegt sich ein Balken mit, kommen die Daten an. Wähle im Simulator „vJoy Device“ als Steuerung und folge der Kalibrierung im Simulator.",
    ),
    "en": (
        "This app lets you fly your simulator wirelessly with your FrSky radio. vJoy provides a virtual joystick in Windows for the simulator to use.",
        "Click “vJoy on GitHub”. Under “Assets”, download and run the Windows installer. Open “Configure vJoy”, select device 1, and enable X, Y, Z, Rx, Ry, Rz, Slider and Dial. Click “Apply”. Press Win+R and enter joy.cpl to check that “vJoy Device” appears.",
        "1. On your radio, open Model → Trainer and tap +.\n"
        "2. Select Bluetooth and enable the link.\n"
        "3. Set Trainer mode to Slave (student) and Channel range to CH1–CH8.",
        "Turn on Bluetooth in Windows. In the app, click “Find transmitters”, select your radio and click “Connect”. Wait for “Ready”.",
        "Open “Live channels” and move a stick. If a bar moves with it, the app is receiving data. Select “vJoy Device” as your controller and follow the calibration steps in your simulator.",
    ),
}

LANGUAGES = ("system", "de", "en")


AUTOSTART_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
AUTOSTART_NAME = "FrSky Bluetooth Trainer"


def autostart_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_KEY) as key:
            value, _ = winreg.QueryValueEx(key, AUTOSTART_NAME)
            return bool(value)
    except OSError:
        return False


def set_autostart(enabled):
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, AUTOSTART_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            executable = Path(sys.executable).resolve()
            command = f'"{executable}"'
            if not getattr(sys, "frozen", False):
                executable = executable.with_name("pythonw.exe")
                if not executable.is_file():
                    raise FileNotFoundError(executable)
                command = f'"{executable}" "{Path(__file__).resolve()}"'
            winreg.SetValueEx(key, AUTOSTART_NAME, 0, winreg.REG_SZ, command + " --windows-autostart")
        else:
            try:
                winreg.DeleteValue(key, AUTOSTART_NAME)
            except FileNotFoundError:
                pass


def message(text, **fields):
    return text, fields


def translate(value, language):
    text, fields = value if isinstance(value, tuple) else (value, {})
    if language == "en":
        text = ENGLISH.get(text, text)
    return text.format(**{key: translate(item, language) if isinstance(item, tuple) else item
                          for key, item in fields.items()}) if fields else text


def load_settings(path):
    root = ET.parse(path).getroot()
    if root.tag != "config":
        raise ValueError("Invalid configuration root")
    return {
        "language": root.get("language", "system"),
        "last": root.get("last-transmitter", ""),
        "last_simulator": int(root.get("last-simulator", "0")),
        "start_in_tray": root.get("start-in-tray", "false") == "true",
        "auto_launch": root.get("auto-launch", "false") == "true",
        "auto_launch_at_login": root.get("auto-launch-at-login", "false") == "true",
        "senders": {
            node.attrib["address"]: {
                "name": node.attrib["name"],
                "channels": [int(channel) for channel in node.attrib["channels"].split()],
            }
            for node in root.findall("./transmitters/transmitter")
        },
        "simulators": [dict(node.attrib) for node in root.findall("./simulators/simulator")],
    }


def save_settings(path, settings):
    root = ET.Element("config", {
        "language": settings.get("language", "system"),
        "last-transmitter": settings.get("last", ""),
        "last-simulator": str(settings.get("last_simulator", 0)),
        "start-in-tray": "true" if settings.get("start_in_tray", False) else "false",
        "auto-launch": "true" if settings.get("auto_launch") else "false",
        "auto-launch-at-login": "true" if settings.get("auto_launch_at_login") else "false",
    })
    transmitters = ET.SubElement(root, "transmitters")
    for address, profile in settings["senders"].items():
        ET.SubElement(transmitters, "transmitter", {
            "address": address,
            "name": profile["name"],
            "channels": " ".join(map(str, profile["channels"])),
        })
    simulators = ET.SubElement(root, "simulators")
    for entry in settings.get("simulators", []):
        ET.SubElement(simulators, "simulator", {"name": entry["name"], "path": entry["path"]})
    staged = path.with_suffix(".tmp")
    ET.indent(root)
    ET.ElementTree(root).write(staged, encoding="utf-8", xml_declaration=True)
    staged.replace(path)


class BluetoothWorker:
    def __init__(self, events):
        self.events = events
        self.loop = asyncio.new_event_loop()
        self.task = None
        self.command_lock = asyncio.Lock()
        self.thread = threading.Thread(target=self.loop.run_forever)
        self.thread.start()

    def submit(self, operation, *args):
        self.loop.call_soon_threadsafe(lambda: self.loop.create_task(self.replace(operation, args)))

    async def replace(self, operation, args):
        async with self.command_lock:
            previous = self.task
            self.task = None
            if previous:
                previous.cancel()
                await asyncio.gather(previous, return_exceptions=True)
            if operation is None:
                self.loop.stop()
                return
            task = asyncio.create_task(operation(*args))
            self.task = task
        try:
            await task
        except asyncio.CancelledError:
            pass
        except VJoyUnavailable:
            if self.task is task:
                self.events.put(("vjoy_unavailable", None))
        except Exception as error:
            if self.task is task:
                self.events.put(("status", message("Fehler: {error}", error=message(str(error) or type(error).__name__))))
        finally:
            if self.task is task:
                self.task = None
                self.events.put(("finished", operation.__name__))

    async def disconnect(self):
        self.events.put(("disconnected", None))

    async def scan(self):
        devices = await BleakScanner.discover(timeout=6, return_adv=True)
        candidates = {}
        for device, advert in devices.values():
            name = advert.local_name or device.name or "Unbekannter Sender"
            if SERVICE in advert.service_uuids or name.upper().startswith(("X20", "X18", "X14", "FRSKY", "TWIN", "XE")):
                candidates[device.address] = {"name": name, "channels": DEFAULT.copy()}
        self.events.put(("devices", candidates))

    async def connect(self, address, channels):
        try:
            output = VJoyOutput(channels)
        except RuntimeError as error:
            if "konnte nicht geöffnet werden" in str(error):
                raise RuntimeError("vJoy-Gerät 1 ist möglicherweise belegt. Beende das alte Bluetooth-Skript mit Strg+X und klicke auf Verbinden.") from error
            raise
        failures = 0
        service_retry = False
        device = None
        try:
            while True:
                output.center()
                self.events.put(("values", None))
                self.events.put(("connection", None))
                try:
                    phase = "Sendersuche"
                    if device is None:
                        self.events.put(("progress", "Suche Sender per Bluetooth …"))
                        started = self.loop.time()
                        device = await BleakScanner.find_device_by_address(address, timeout=10)
                        if device is None:
                            raise TimeoutError("Sender nicht gefunden.")
                        self.events.put(("diagnostic", message("Sender nach {seconds:.1f} s gefunden.", seconds=self.loop.time() - started)))
                    self.events.put(("progress", "Trainerdienst erneut öffnen …" if service_retry else
                                     "Sender gefunden. Öffne den Trainerdienst …"))
                    phase = "Trainerdienst"
                    started = self.loop.time()
                    disconnected = asyncio.Event()
                    async with BleakClient(
                        device, services=[SERVICE], timeout=12,
                        winrt={"use_cached_services": bool(failures % 2)},
                        disconnected_callback=lambda _: disconnected.set(),
                    ) as client:
                        self.events.put(("connection", address))
                        self.events.put(("diagnostic", message("Trainerdienst nach {seconds:.1f} s geöffnet.", seconds=self.loop.time() - started)))
                        self.events.put(("progress", "Bluetooth verbunden. Warte auf Steuerdaten …"))
                        phase = "Steuerdaten"
                        started = self.loop.time()
                        decoder = TrainerDecoder()
                        latest = None
                        last_packet = self.loop.time()
                        display_timer = None
                        write_error = None

                        def refresh_display():
                            nonlocal display_timer
                            display_timer = None
                            if not disconnected.is_set():
                                self.events.put(("raw_channels", (address, latest)))
                                self.events.put(("values", [latest[i - 1] for i in channels]))

                        def on_packet(_, data):
                            nonlocal latest, last_packet, display_timer, write_error, failures, phase
                            if disconnected.is_set():
                                return
                            for values in decoder.feed(data):
                                last_packet = self.loop.time()
                                if values == latest:
                                    continue
                                try:
                                    output.write(values)
                                except (OSError, RuntimeError) as error:
                                    write_error = error
                                    disconnected.set()
                                    return
                                if latest is None:
                                    self.events.put(("diagnostic", message("Erste Steuerdaten nach {seconds:.1f} s an vJoy übergeben.", seconds=self.loop.time() - started)))
                                    self.events.put(("status", "Bereit · Steuerdaten werden an vJoy übertragen."))
                                    self.events.put(("ready", address))
                                    phase = "Laufende Verbindung"
                                    failures = 0
                                latest = values
                                if display_timer is None:
                                    display_timer = self.loop.call_later(0.05, refresh_display)

                        try:
                            await client.start_notify(CHARACTERISTIC, on_packet)
                            while not disconnected.is_set():
                                remaining = 5 - (self.loop.time() - last_packet)
                                if remaining <= 0:
                                    raise TimeoutError("Keine gültigen Trainerdaten.")
                                try:
                                    await asyncio.wait_for(disconnected.wait(), timeout=remaining)
                                except TimeoutError:
                                    pass
                            if write_error is not None:
                                raise write_error
                        finally:
                            disconnected.set()
                            if display_timer is not None:
                                display_timer.cancel()
                        raise ConnectionError("Bluetooth getrennt.")
                except (ConnectionError, TimeoutError, OSError, BleakError) as error:
                    self.events.put(("connection", None))
                    output.center()
                    self.events.put(("values", None))
                    failures += 1
                    # Try the discovered device once more before starting another scan.
                    service_retry = phase == "Trainerdienst" and not service_retry and device is not None
                    if not service_retry:
                        device = None
                    delay = 1 if service_retry else min(failures * 2, 6)
                    self.events.put(("diagnostic", message("{phase}: {error}", phase=message(phase), error=message(str(error) or type(error).__name__))))
                    reason = {
                        "Sendersuche": "Sender noch nicht gefunden.",
                        "Trainerdienst": "Trainerdienst noch nicht erreichbar.",
                        "Steuerdaten": "Warte auf gültige Steuerdaten.",
                        "Laufende Verbindung": "Bluetooth-Verbindung unterbrochen.",
                    }[phase]
                    hint = " Prüfe den Bluetooth-Schülermodus." if failures >= 3 else ""
                    self.events.put(("progress", message("{reason} Automatischer Versuch {attempt} in {delay} s.{hint}",
                                                               reason=message(reason), attempt=failures + 1, delay=delay, hint=message(hint))))
                    await asyncio.sleep(delay)
        finally:
            self.events.put(("connection", None))
            output.close()


class Application:
    def __init__(self, root):
        self.root = root
        self.events = queue.SimpleQueue()
        self.worker = BluetoothWorker(self.events)
        self.closing = False
        self.pending_simulator = None
        self.raw_channels = None
        self.tray_state = None
        self.settings = {"last": "", "senders": {}}
        try:
            if SETTINGS.exists():
                self.settings.update(load_settings(SETTINGS))
            elif LEGACY_SETTINGS.exists():
                self.settings.update(json.loads(LEGACY_SETTINGS.read_text(encoding="utf-8")))
        except (OSError, ValueError, KeyError, ET.ParseError):
            pass

        self.localized_widgets = []
        self.status_message = "Getrennt"
        self.language_preference = self.settings.get("language", "system")
        if self.language_preference not in LANGUAGES:
            self.language_preference = "system"
        self.language = self.effective_language()
        root.title("FrSky Bluetooth Trainer")
        self.window_icon = ImageTk.PhotoImage(self.draw_tray_icon("Getrennt"), master=root)
        root.iconphoto(True, self.window_icon)
        root.minsize(640, 1)
        style = ttk.Style(root)
        style.theme_use("clam")
        surface, panel, border, ink = "#f2f1ee", "#fffefa", "#d0cbc0", FRSKY_BLACK
        root.configure(background=surface)
        style.configure(".", background=surface, foreground=ink, font=("Segoe UI", 9))
        for name in ("TFrame", "TLabel", "TCheckbutton", "TLabelframe"):
            style.configure(name, background=surface)
        style.configure("TLabelframe", bordercolor=border, lightcolor=border, darkcolor=border)
        style.configure("TLabelframe.Label", background=surface, foreground=ink, font=("Segoe UI", 10, "bold"))
        style.configure("TButton", background=panel, bordercolor=border, lightcolor=panel, darkcolor=border)
        style.map("TButton", background=[("disabled", "#e4e1da"), ("pressed", "#edcf70"), ("active", "#fff0b7")])
        style.configure("Action.TButton", padding=(12, 4))
        style.configure("Launch.TButton", background=FRSKY_YELLOW, bordercolor="#997616",
                        lightcolor=FRSKY_YELLOW, darkcolor="#997616", font=("Segoe UI", 10, "bold"), padding=(18, 5))
        style.map("Launch.TButton", background=[("disabled", "#e4e1da"), ("pressed", "#d6a81d"), ("active", "#ffda62")])
        style.configure("TCombobox", fieldbackground=panel, background=panel, bordercolor=border)
        style.map("TCombobox", fieldbackground=[("readonly", panel)], selectbackground=[("readonly", "#fff0b7")],
                  selectforeground=[("readonly", ink)])
        style.configure("TEntry", fieldbackground=panel, bordercolor=border)
        style.configure("Horizontal.TProgressbar", background=FRSKY_YELLOW, troughcolor="#dfdbd1",
                        bordercolor=border, lightcolor=FRSKY_YELLOW, darkcolor=FRSKY_YELLOW)
        style.configure("Brand.TFrame", background="#ffffff")
        style.configure("Brand.TLabel", background="#ffffff", foreground=ink)
        body = ttk.Frame(root, padding=(16, 10))
        body.pack(fill="both", expand=True)
        header = ttk.Frame(body, style="Brand.TFrame", padding=(9, 4))
        header.pack(fill="x")
        tk.Frame(body, background=FRSKY_YELLOW, height=3).pack(fill="x")
        logo_path = Path(__file__).with_name("frsky-logo.png")
        try:
            with Image.open(logo_path) as logo:
                logo.thumbnail((168, 36), Image.Resampling.LANCZOS)
                self.brand_logo = ImageTk.PhotoImage(logo, master=root)
        except OSError:
            pass
        else:
            logo_link = ttk.Label(header, image=self.brand_logo, style="Brand.TLabel",
                                  cursor="hand2", takefocus=True)
            logo_link.pack(side="left")
            for event in ("<Button-1>", "<Return>", "<space>"):
                logo_link.bind(event, lambda _: webbrowser.open("https://www.frsky-rc.com/"))
        self.language_picker = ttk.Combobox(header, width=17, state="readonly")
        self.widget(ttk.Button, header, "Hilfe", command=self.show_help).pack(side="right", padx=(8, 0))
        self.widget(ttk.Button, header, "GitHub", command=self.open_project).pack(side="right", padx=(8, 0))
        self.language_picker.pack(side="right")
        self.widget(ttk.Label, header, "Sprache", style="Brand.TLabel").pack(side="right", padx=(0, 6))
        self.language_picker.bind("<<ComboboxSelected>>", self.change_language)
        self.update_language_picker()
        bluetooth = self.widget(ttk.LabelFrame, body, "Bluetooth", padding=(10, 6))
        bluetooth.pack(fill="x", pady=(8, 6))
        self.widget(ttk.Label, bluetooth, "Sender").pack(anchor="w")
        self.sender = ttk.Combobox(bluetooth, state="readonly")
        self.sender.pack(fill="x", pady=(3, 6))
        self.refresh(self.settings["last"])
        bar = ttk.Frame(bluetooth)
        bar.pack(fill="x")
        self.connected_address = None
        self.scanning = False
        self.connecting = False
        self.connection_target = None
        self.disconnecting = False
        self.buttons = []
        for title, command in (("Verbinden", self.connect), ("Sender suchen", self.scan), ("Kanäle zuordnen", self.mapping)):
            button = self.widget(ttk.Button, bar, title, command=command, style="Launch.TButton" if command == self.connect else "Action.TButton")
            button.pack(side="left", padx=(0, 10))
            self.buttons.append(button)
            if command == self.connect:
                self.disconnect_button = self.widget(ttk.Button, bar, "Trennen", command=self.disconnect,
                                                     state="disabled", style="Action.TButton")
                self.disconnect_button.pack(side="left", padx=(0, 16))
        self.remove_sender_button = self.widget(ttk.Button, bluetooth, "Sender entfernen",
                                                command=self.remove_sender, style="Action.TButton")
        self.remove_sender_button.pack(anchor="w", pady=(5, 0))
        self.sender.bind("<<ComboboxSelected>>", lambda _: self.update_connect_button())
        self.update_connect_button()
        self.simulators = self.settings.setdefault("simulators", [])
        simulator = self.widget(ttk.LabelFrame, body, "Simulator", padding=(10, 6))
        simulator.pack(fill="x", pady=(0, 6))
        simulator_bar = ttk.Frame(simulator)
        simulator_bar.pack(fill="x")
        simulator_tools = ttk.Frame(simulator)
        simulator_tools.pack(fill="x", pady=(5, 0))
        self.simulator_picker = ttk.Combobox(simulator_bar, state="readonly", width=17)
        self.simulator_picker.pack(side="left", fill="x", expand=True)
        self.simulator_picker.bind("<<ComboboxSelected>>", self.select_simulator)
        self.simulator_buttons = []
        for label, command in (
            ("Starten", self.launch_simulator),
            ("Hinzufügen", lambda: self.edit_simulator()),
            ("Bearbeiten", lambda: self.edit_simulator(self.simulator_picker.current())),
            ("Entfernen", self.remove_simulator),
        ):
            primary = label == "Starten"
            button = self.widget(ttk.Button, simulator_bar if primary else simulator_tools,
                                 label, command=command, style="Launch.TButton" if primary else "Action.TButton")
            button.pack(side="left", padx=(12, 0) if primary else (0, 10))
            if label != "Hinzufügen":
                self.simulator_buttons.append(button)
        self.auto_launch = tk.BooleanVar(value=self.settings.get("auto_launch", False))
        self.auto_launch_at_login = tk.BooleanVar(value=self.settings.get("auto_launch_at_login", False))
        self.widget(ttk.Checkbutton, simulator, "Simulator starten, sobald die Steuerung bereit ist",
                    variable=self.auto_launch, command=self.save_auto_launch).pack(anchor="w", pady=(6, 0))
        self.login_launch_button = self.widget(ttk.Checkbutton, simulator, "Auch bei Windows-Anmeldung",
                                               variable=self.auto_launch_at_login, command=self.save_auto_launch)
        self.login_launch_button.pack(anchor="w", padx=(18, 0))
        self.refresh_simulators(self.settings.get("last_simulator", 0))
        self.update_login_launch_button()

        self.diagnostics = []
        self.status = tk.StringVar(value=self.tr(self.status_message))
        ttk.Label(bluetooth, textvariable=self.status, wraplength=540).pack(anchor="w", pady=(6, 4))
        self.progress = ttk.Progressbar(bluetooth, mode="indeterminate")
        self.details_button = self.widget(ttk.Button, bluetooth, "Bluetooth-Details", command=self.show_diagnostics)
        self.details_button.pack(anchor="w")

        self.live = tk.BooleanVar()
        self.widget(ttk.Checkbutton, body, "Live-Anzeige", variable=self.live, command=self.toggle).pack(anchor="w")
        self.details = ttk.Frame(body)
        self.details.columnconfigure((0, 1, 2, 3), weight=1, uniform="channel")
        self.meters = []
        for index in range(8):
            card = tk.Frame(self.details, background=FRSKY_BLACK, highlightthickness=1,
                            highlightbackground="#555555", padx=7, pady=3)
            card.grid(row=index // 4, column=index % 4, sticky="ew", padx=3, pady=2)
            card.columnconfigure(0, weight=1)
            tk.Label(card, text=f"CH{index + 1}", bg=FRSKY_BLACK, fg="#ffffff",
                     font=("Segoe UI", 10, "bold")).grid(row=0, column=0, sticky="w")
            number = tk.StringVar(value="—")
            tk.Label(card, textvariable=number, bg=FRSKY_BLACK, fg=FRSKY_YELLOW,
                     font=("Consolas", 10)).grid(row=0, column=1, sticky="e")
            meter = tk.Canvas(card, width=100, height=22, background=FRSKY_BLACK,
                              highlightthickness=0)
            meter.grid(row=1, column=0, columnspan=2, sticky="ew")
            self.meters.append((meter, number))
            meter.bind("<Configure>", lambda event, i=index: self.draw_meter(
                event.widget, self.channel_values[i] if self.channel_values is not None else None
            ))
        self.channel_values = None
        self.footer = ttk.Frame(body)
        self.footer.pack(fill="x", pady=(7, 0))
        self.start_in_tray = tk.BooleanVar(value=self.settings.get("start_in_tray", False))
        self.widget(ttk.Checkbutton, self.footer, "Start im Infobereich",
                    variable=self.start_in_tray, command=self.save_start_mode).pack(side="left")
        self.start_with_windows = tk.BooleanVar(value=autostart_enabled())
        self.widget(ttk.Checkbutton, self.footer, "Mit Windows starten",
                    variable=self.start_with_windows, command=self.save_autostart).pack(side="left", padx=(8, 0))
        self.widget(ttk.Button, self.footer, "Beenden", command=self.close,
                    style="Action.TButton").pack(side="right")
        self.widget(ttk.Button, self.footer, "In den Infobereich", command=root.withdraw,
                    style="Action.TButton").pack(side="right", padx=(0, 10))
        self.tray = pystray.Icon("frsky-bluetooth-trainer")
        self.update_tray("Getrennt")
        self.tray.run_detached()
        root.protocol("WM_DELETE_WINDOW", root.withdraw)
        root.bind("<Control-x>", lambda _: self.close())
        if self.start_with_windows.get() and "--windows-autostart" not in sys.argv[1:]:
            try:
                set_autostart(True)
            except OSError:
                pass
        if self.start_in_tray.get():
            root.withdraw()
        root.after(60, self.poll)
        if self.selected() is not None:
            root.after(150, lambda: self.connect(at_start=True))

    def effective_language(self):
        if self.language_preference != "system":
            return self.language_preference
        language_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        return "de" if language_id & 0x3FF == 7 else "en"

    def tr(self, value):
        return translate(value, self.language)

    def widget(self, cls, parent, label, **options):
        widget = cls(parent, text=self.tr(label), **options)
        self.localized_widgets.append((widget, label))
        return widget

    def update_language_picker(self):
        self.language_picker["values"] = (self.tr("Systemsprache"), "Deutsch", "English")
        self.language_picker.current(LANGUAGES.index(self.language_preference))

    def change_language(self, _=None):
        self.language_preference = LANGUAGES[self.language_picker.current()]
        self.language = self.effective_language()
        self.settings["language"] = self.language_preference
        for widget, label in self.localized_widgets:
            widget.configure(text=self.tr(label))
        self.update_language_picker()
        self.refresh(self.selected())
        self.update_connect_button()
        self.status.set(self.tr(self.status_message))
        self.update_tray(self.tray_state, force=True)
        self.save()

    def refresh_simulators(self, index):
        self.simulator_picker["values"] = [item["name"] for item in self.simulators]
        if self.simulators:
            self.simulator_picker.current(max(0, min(index, len(self.simulators) - 1)))
        else:
            self.simulator_picker.set("")
        for button in self.simulator_buttons:
            button.state(["!disabled" if self.simulators else "disabled"])

    def select_simulator(self, _=None):
        self.settings["last_simulator"] = max(0, self.simulator_picker.current())
        self.save()

    def edit_simulator(self, index=None):
        existing = self.simulators[index] if index is not None else {"name": "", "path": ""}
        dialog = tk.Toplevel(self.root)
        dialog.title(self.tr("Bearbeiten" if index is not None else "Hinzufügen"))
        dialog.transient(self.root)
        panel = ttk.Frame(dialog, padding=16)
        panel.pack(fill="both", expand=True)
        panel.columnconfigure(1, weight=1)
        name = tk.StringVar(value=existing["name"])
        path = tk.StringVar(value=existing["path"])
        ttk.Label(panel, text=self.tr("Name")).grid(row=0, column=0, sticky="w", padx=(0, 10))
        name_field = ttk.Entry(panel, textvariable=name)
        name_field.grid(row=0, column=1, columnspan=2, sticky="ew", pady=4)
        ttk.Label(panel, text=self.tr("Programmdatei")).grid(row=1, column=0, sticky="w", padx=(0, 10))
        ttk.Entry(panel, textvariable=path, width=44).grid(row=1, column=1, sticky="ew", pady=4)

        def browse():
            selected = filedialog.askopenfilename(parent=dialog, title=self.tr("Simulator wählen"),
                                                  filetypes=[(self.tr("Startdateien"), " ".join(f"*{ext}" for ext in SIMULATOR_TYPES))])
            if selected:
                path.set(selected)
                if not name.get().strip():
                    name.set(Path(selected).stem)

        ttk.Button(panel, text=self.tr("Durchsuchen"), command=browse).grid(row=1, column=2, padx=(6, 0))
        error = tk.StringVar()
        ttk.Label(panel, textvariable=error, foreground="#a61b1b", wraplength=450).grid(
            row=2, column=0, columnspan=3, sticky="w"
        )

        def apply():
            executable = Path(path.get().strip().strip('"'))
            title = name.get().strip()
            if not title or executable.suffix.lower() not in SIMULATOR_TYPES or not executable.is_file():
                error.set(self.tr("Gib einen Namen und eine vorhandene Startdatei an (.exe, .bat, .cmd oder .lnk)."))
                return
            entry = {"name": title, "path": str(executable.resolve())}
            if index is None:
                self.simulators.append(entry)
            else:
                self.simulators[index] = entry
            self.refresh_simulators(len(self.simulators) - 1 if index is None else index)
            self.select_simulator()
            dialog.destroy()

        actions = ttk.Frame(panel)
        actions.grid(row=3, column=0, columnspan=3, sticky="e", pady=(12, 0))
        ttk.Button(actions, text=self.tr("Abbrechen"), command=dialog.destroy).pack(side="left", padx=6)
        ttk.Button(actions, text=self.tr("Übernehmen"), command=apply, style="Launch.TButton").pack(side="left")
        dialog.bind("<Escape>", lambda _: dialog.destroy())
        dialog.grab_set()
        name_field.focus_set()

    def remove_simulator(self):
        index = self.simulator_picker.current()
        name = self.simulators[index]["name"]
        if messagebox.askyesno(self.tr("Simulator entfernen?"),
                               self.tr(message("„{name}“ aus der Liste entfernen?", name=name)),
                               parent=self.root):
            del self.simulators[index]
            self.refresh_simulators(index)
            self.select_simulator()

    def update_login_launch_button(self):
        self.login_launch_button.state(["!disabled" if self.auto_launch.get() else "disabled"])

    def save_auto_launch(self):
        self.settings["auto_launch"] = self.auto_launch.get()
        self.settings["auto_launch_at_login"] = self.auto_launch_at_login.get()
        if not self.auto_launch.get():
            self.pending_simulator = None
        self.update_login_launch_button()
        self.save()

    def launch_simulator(self, entry=None):
        if entry is None:
            index = self.simulator_picker.current()
            if index < 0:
                return
            entry = self.simulators[index]
            self.pending_simulator = None
        executable = Path(entry["path"])
        try:
            os.startfile(str(executable), cwd=str(executable.parent))
        except OSError as error:
            messagebox.showerror(self.tr("Simulator konnte nicht gestartet werden"),
                                 f"{entry['name']}\n{error}", parent=self.root)

    def refresh(self, address):
        self.addresses = list(self.settings["senders"])
        self.sender["values"] = [
            f"{self.tr(self.settings['senders'][key]['name']) if self.settings['senders'][key]['name'] == 'Unbekannter Sender' else self.settings['senders'][key]['name']}  ({key})" for key in self.addresses
        ]
        if self.addresses:
            self.sender.current(self.addresses.index(address) if address in self.addresses else 0)
        else:
            self.sender.set("")

    def selected(self):
        index = self.sender.current()
        return self.addresses[index] if index >= 0 else None

    def can_remove_sender(self, address):
        return (address is not None and address in self.settings["senders"]
                and address != self.connected_address
                and not (self.connecting and address == self.connection_target)
                and not (self.scanning or self.disconnecting or self.closing))

    def remove_sender(self):
        address = self.selected()
        if not self.can_remove_sender(address):
            return
        name = self.settings["senders"][address]["name"]
        prompt = message("„{name}“ und seine Kanalzuordnung aus der Senderliste entfernen?", name=name)
        if not messagebox.askyesno(self.tr("Sender entfernen"), self.tr(prompt), parent=self.root):
            return
        if not self.can_remove_sender(address):
            return
        del self.settings["senders"][address]
        if self.settings["last"] == address:
            self.settings["last"] = next(iter(self.settings["senders"]), "")
        self.refresh(self.connection_target if self.connecting else self.settings["last"])
        self.update_connect_button()
        self.save()

    def save_autostart(self):
        try:
            set_autostart(self.start_with_windows.get())
        except OSError as error:
            self.start_with_windows.set(autostart_enabled())
            messagebox.showerror(self.tr("Windows-Autostart konnte nicht geändert werden"),
                                 str(error), parent=self.root)

    def save_start_mode(self):
        self.settings["start_in_tray"] = self.start_in_tray.get()
        self.save()

    def save(self):
        try:
            save_settings(SETTINGS, self.settings)
        except OSError as error:
            messagebox.showerror(self.tr("Senderprofil konnte nicht gespeichert werden"), str(error), parent=self.root)

    def update_connect_button(self):
        address = self.selected()
        same_sender = address == self.connected_address or (self.connecting and address == self.connection_target)
        disabled = self.scanning or self.disconnecting or address is None or same_sender
        self.buttons[2].state(["disabled" if self.scanning or self.disconnecting or address is None else "!disabled"])
        self.remove_sender_button.state(["!disabled" if self.can_remove_sender(address) else "disabled"])
        self.buttons[0].state(["disabled" if disabled else "!disabled"])
        can_disconnect = self.connecting and not self.disconnecting and not self.scanning
        self.disconnect_button.state(["!disabled" if can_disconnect else "disabled"])

    def connect(self, *, at_start=False, launch=True):
        address = self.selected()
        if address is None:
            return
        self.pending_simulator = None
        index = self.simulator_picker.current()
        at_login = at_start and "--windows-autostart" in sys.argv[1:]
        if launch and index >= 0 and self.auto_launch.get() and (not at_login or self.auto_launch_at_login.get()):
            self.pending_simulator = self.simulators[index].copy()
        self.connection_target = address
        self.connecting = True
        self.update_connect_button()
        self.settings["last"] = address
        self.save()
        self.raw_channels = None
        self.render_channels(None)
        self.diagnostics.clear()
        self.set_status("Starte Verbindung …", busy=True)
        self.worker.submit(self.worker.connect, address, self.settings["senders"][address]["channels"])

    def disconnect(self):
        self.pending_simulator = None
        self.disconnecting = True
        for button in self.buttons:
            button.state(["disabled"])
        self.update_connect_button()
        self.raw_channels = None
        self.render_channels(None)
        self.set_status("Trenne Bluetooth …")
        self.worker.submit(self.worker.disconnect)

    def scan(self):
        self.pending_simulator = None
        self.scanning = True
        self.connecting = False
        self.update_connect_button()
        for button in self.buttons:
            button.state(["disabled"])
        self.raw_channels = None
        self.render_channels(None)
        self.set_status("Suche FrSky-Sender · Trainer → Bluetooth → Slave …", busy=True)
        self.worker.submit(self.worker.scan)

    def mapping(self):
        address = self.selected()
        profile = self.settings["senders"][address]
        dialog = tk.Toplevel(self.root)
        dialog.title(self.tr("Kanäle zuordnen"))
        dialog.transient(self.root)
        dialog.resizable(False, False)
        panel = ttk.Frame(dialog, padding=18)
        panel.pack(fill="both", expand=True)

        ttk.Label(panel, text=profile["name"], font=("Segoe UI", 12, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 12)
        )
        ttk.Label(panel, text=self.tr("vJoy-Achse")).grid(row=1, column=0, sticky="w")
        ttk.Label(panel, text=self.tr("Senderkanal")).grid(row=1, column=1, sticky="w", padx=(30, 0))

        choices = [f"CH{channel}" for channel in DEFAULT]
        selectors = []
        for row, (axis, channel) in enumerate(zip(VJoyOutput.axis_names, profile["channels"]), 2):
            ttk.Label(panel, text=axis).grid(row=row, column=0, sticky="w", pady=3)
            selector = ttk.Combobox(panel, values=choices, state="readonly", width=13)
            selector.current(channel - 1)
            selector.grid(row=row, column=1, sticky="w", padx=(30, 0), pady=3)
            selectors.append(selector)

        guide = ttk.Frame(panel)
        guide.grid(row=10, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        axis_picker = ttk.Combobox(guide, state="readonly", width=9, values=VJoyOutput.axis_names)
        axis_picker.current(0)
        axis_picker.pack(side="left")
        detected = None
        baseline = None
        hint = tk.StringVar()

        def use_detected():
            target = axis_picker.current()
            other = next((i for i, item in enumerate(selectors) if item.current() == detected), None)
            if other is not None:
                selectors[other].current(selectors[target].current())
            selectors[target].current(detected)

        use = ttk.Button(guide, text=self.tr("Erkannten Kanal übernehmen"), command=use_detected, state="disabled")
        use.pack(side="left", padx=6)
        ttk.Label(panel, textvariable=hint, foreground=FRSKY_BLACK, font=("Segoe UI", 10, "bold")).grid(row=11, column=0, columnspan=2, sticky="w")

        detected_meter = tk.Canvas(panel, width=260, height=28, background=FRSKY_BLACK, highlightthickness=0)
        detected_meter.grid(row=12, column=0, columnspan=2, sticky="ew", pady=3)

        timer = None

        def detect():
            nonlocal baseline, detected, timer
            if self.raw_channels is None or self.raw_channels[0] != address:
                baseline = detected = None
                hint.set(self.tr("Warte auf Daten vom ausgewählten Sender."))
            else:
                current = self.raw_channels[1]
                if baseline is None:
                    baseline = current
                else:
                    changes = [abs(old - new) for old, new in zip(baseline, current)]
                    index = max(range(8), key=changes.__getitem__)
                    if changes[index] >= 35 and changes.count(changes[index]) == 1:
                        detected = index
                        baseline = current
                hint.set(self.tr("Achse wählen und einen Geber bewegen.") if detected is None
                         else f"CH{detected + 1} · {current[detected]} µs")
            self.draw_meter(detected_meter, None if detected is None else current[detected])
            use.state(["disabled" if detected is None else "!disabled"])
            timer = dialog.after(100, detect)

        dialog.bind("<Destroy>", lambda event: dialog.after_cancel(timer)
                    if event.widget is dialog and timer is not None else None)
        detect()
        error = tk.StringVar()
        ttk.Label(panel, textvariable=error, foreground="#a61b1b", wraplength=350).grid(
            row=13, column=0, columnspan=2, sticky="w", pady=(8, 0)
        )

        def reset():
            for index, selector in enumerate(selectors):
                selector.current(index)
            error.set("")

        def apply_mapping():
            channels = [selector.current() + 1 for selector in selectors]
            duplicates = [f"CH{channel}" for channel in DEFAULT if channels.count(channel) > 1]
            if duplicates:
                error.set(self.tr(message("Mehrfach zugeordnet: {channels}", channels=", ".join(duplicates))))
                return
            dialog.destroy()
            if channels != profile["channels"]:
                profile["channels"] = channels
                self.connect(launch=False)

        actions = ttk.Frame(panel)
        actions.grid(row=14, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        ttk.Button(actions, text=self.tr("Standard"), command=reset).pack(side="left", padx=(0, 12))
        ttk.Button(actions, text=self.tr("Übernehmen"), command=apply_mapping, style="Launch.TButton").pack(side="right")
        ttk.Button(actions, text=self.tr("Abbrechen"), command=dialog.destroy).pack(side="right", padx=(0, 6))
        dialog.bind("<Escape>", lambda _: dialog.destroy())
        dialog.grab_set()
        selectors[0].focus_set()


    def toggle(self):
        if self.live.get():
            self.details.pack(fill="x", pady=(4, 0), before=self.footer)
        else:
            self.details.pack_forget()

    def render_channels(self, values):
        self.channel_values = values
        for index, (meter, number) in enumerate(self.meters):
            raw = values[index] if values is not None else None
            self.draw_meter(meter, raw)
            number.set("—" if raw is None else f"{raw} µs")

    @staticmethod
    def draw_meter(meter, raw):
        left, right = 8, max(18, meter.winfo_width() - 8)
        center = (left + right) / 2
        meter.delete("all")
        meter.create_line(left, 10, right, 10, fill="#484848", width=10, capstyle="round")
        for x in (left, center, right):
            meter.create_line(x, 16, x, 20, fill="#bbbbbb", width=2 if x == center else 1)
        if raw is not None:
            ratio = (max(988, min(2012, raw)) - 988) / 1024
            position = left + (right - left) * ratio
            meter.create_line(center, 10, position, 10, fill=FRSKY_YELLOW, width=8, capstyle="round")
            meter.create_oval(position - 5, 5, position + 5, 15, fill=FRSKY_YELLOW, outline="#ffffff", width=1)

    def tray_simulators(self):
        return (
            pystray.MenuItem(entry["name"], partial(self.queue_tray_simulator, entry))
            for entry in self.simulators[:]
        )

    def queue_tray_simulator(self, entry, _icon, _item):
        self.events.put(("tray_simulator", entry))

    def queue_tray_switch(self, address, _icon, _item):
        self.events.put(("tray_switch", address))

    def can_switch_from_tray(self, address):
        return (address in self.settings["senders"] and not (self.scanning or self.disconnecting or self.closing)
                and not (self.connecting and address == self.connection_target))

    def can_connect_from_tray(self):
        return self.selected() is not None and not (self.connecting or self.connected_address or self.disconnecting or self.scanning or self.closing)

    @staticmethod
    def draw_tray_icon(state=None):
        image = Image.new("RGBA", (128, 128))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((5, 5, 105, 105), radius=23, fill=FRSKY_YELLOW,
                               outline=FRSKY_BLACK, width=6)
        # Bluetooth mark, separated from the status badge at small sizes.
        draw.line((53, 24, 74, 43, 33, 78), fill=FRSKY_BLACK, width=9, joint="curve")
        draw.line((33, 37, 74, 73, 53, 91, 53, 24), fill=FRSKY_BLACK, width=9, joint="curve")

        if state is None:
            return image.crop((0, 0, 111, 111)).resize((64, 64), Image.Resampling.LANCZOS)

        color = {"Bereit": "#177845", "Verbindung wird aufgebaut": "#754019",
                 "Getrennt": "#454545"}[state]
        draw.ellipse((64, 64, 126, 126), fill=color, outline="#f3f7fb", width=5)
        if state == "Bereit":
            draw.line((79, 95, 91, 106, 111, 84), fill="white", width=7, joint="curve")
        elif state == "Getrennt":
            draw.line((82, 82, 108, 108), fill="white", width=7)
            draw.line((108, 82, 82, 108), fill="white", width=7)
        else:
            for center in (81, 95, 109):
                draw.ellipse((center - 4, 91, center + 4, 99), fill="white")
        return image.resize((64, 64), Image.Resampling.LANCZOS)

    def update_tray(self, state, *, force=False):
        if state == self.tray_state and not force:
            return
        self.tray_state = state
        icon = self.draw_tray_icon(state)
        self.tray.icon = icon
        self.window_icon = ImageTk.PhotoImage(icon, master=self.root)
        self.root.iconphoto(True, self.window_icon)
        self.tray.title = f"FrSky Bluetooth Trainer · {self.tr(state)}"
        self.tray.menu = pystray.Menu(
            pystray.MenuItem(self.tr("Fenster öffnen"), lambda *_: self.events.put(("tray_open", None)), default=True),
            pystray.MenuItem(self.tr("Verbinden"), lambda *_: self.events.put(("tray_connect", None)),
                             enabled=lambda _: self.can_connect_from_tray()),
            pystray.MenuItem(self.tr("Trennen"), lambda *_: self.events.put(("tray_disconnect", None)),
                             enabled=lambda _: self.connecting and not self.disconnecting and not self.scanning),
            pystray.MenuItem(self.tr("Sender wechseln"), pystray.Menu(lambda: (
                pystray.MenuItem(
                    profile["name"], partial(self.queue_tray_switch, address),
                    checked=lambda item, address=address: address == self.connection_target and self.connecting,
                    enabled=lambda item, address=address: self.can_switch_from_tray(address),
                )
                for address, profile in self.settings["senders"].copy().items()
            ))),
            pystray.MenuItem(self.tr("Simulator starten"), pystray.Menu(self.tray_simulators),
                             enabled=lambda _: bool(self.simulators)),
            pystray.MenuItem(self.tr("Beenden"), lambda *_: self.events.put(("tray_exit", None))),
        )

    def set_status(self, text, *, busy=False):
        self.status_message = text
        self.status.set(self.tr(text))
        state = ("Verbindung wird aufgebaut" if busy else
                 "Bereit" if text == "Bereit · Steuerdaten werden an vJoy übertragen." else "Getrennt")
        self.update_tray(state)
        if busy:
            self.progress.pack(fill="x", pady=(0, 6), before=self.details_button)
            self.progress.start(60)
        else:
            self.progress.stop()
            self.progress.pack_forget()

    def open_project(self):
        webbrowser.open(PROJECT_URL)

    def show_help(self):
        dialog = tk.Toplevel(self.root)
        dialog.title(self.tr("Hilfe"))
        dialog.transient(self.root)
        panel = ttk.Frame(dialog, padding=16)
        panel.pack(fill="both", expand=True)
        headings = ("So funktioniert es", "vJoy installieren", "Sender vorbereiten", "Am PC verbinden", "Simulator einrichten")
        for heading, step in zip(headings, HELP_STEPS[self.language]):
            ttk.Label(panel, text=self.tr(heading), font=("Segoe UI", 10, "bold")).pack(anchor="w")
            ttk.Label(panel, text=step, wraplength=430, justify="left").pack(anchor="w", pady=(2, 8))

        actions = ttk.Frame(panel)
        actions.pack(fill="x", pady=(4, 0))
        ttk.Button(actions, text=self.tr("vJoy auf GitHub"),
                   command=lambda: webbrowser.open(VJOY_DOWNLOAD)).pack(side="left", padx=(0, 6))
        ttk.Button(actions, text=self.tr("ETHOS-Handbuch: Bluetooth-Trainer"),
                   command=lambda: webbrowser.open(TRAINER_MANUAL)).pack(side="left")
        ttk.Label(panel, text=self.tr("Unabhängiges Community-Projekt. Quellcode und Fehlermeldungen findest du auf GitHub."),
                  wraplength=430, justify="left").pack(anchor="w", pady=(8, 4))
        project = ttk.Frame(panel)
        project.pack(fill="x")
        ttk.Button(project, text=self.tr("Projekt auf GitHub"), command=self.open_project).pack(side="left")
        ttk.Button(project, text=self.tr("Schließen"), command=dialog.destroy).pack(side="right")
        dialog.bind("<Escape>", lambda _: dialog.destroy())
        dialog.grab_set()
        dialog.focus_set()

    def show_diagnostics(self):
        messagebox.showinfo(
            self.tr("Bluetooth-Details"),
            "\n".join(map(self.tr, self.diagnostics)) or self.tr("Noch keine Bluetooth-Messwerte."),
            parent=self.root,
        )

    def poll(self):
        while not self.events.empty():
            kind, value = self.events.get_nowait()
            if self.closing:
                continue
            if kind == "tray_open":
                self.root.deiconify()
                self.root.lift()
            elif kind == "tray_exit":
                self.close()
            elif kind == "tray_connect":
                if self.can_connect_from_tray():
                    self.connect()
            elif kind == "tray_simulator":
                if value in self.simulators:
                    self.pending_simulator = None
                    self.launch_simulator(value)
            elif kind == "tray_switch":
                if self.can_switch_from_tray(value):
                    self.refresh(value)
                    self.connect()
            elif kind == "tray_disconnect":
                if self.connecting and not self.disconnecting and not self.scanning:
                    self.disconnect()
            elif kind == "raw_channels":
                if not self.disconnecting:
                    self.raw_channels = value
            elif kind == "disconnected":
                self.connected_address = None
                self.connecting = False
                self.disconnecting = False
                for button in self.buttons:
                    button.state(["!disabled"])
                self.update_connect_button()
                self.set_status("Getrennt. Klicke auf Verbinden, um erneut zu starten.")
            elif self.disconnecting:
                continue
            elif kind == "vjoy_unavailable":
                self.set_status(VJOY_TITLE)
                if self.root.state() == "withdrawn":
                    self.root.deiconify()
                if messagebox.askyesno(self.tr(VJOY_TITLE), self.tr(VJOY_PROMPT), parent=self.root):
                    webbrowser.open(VJOY_DOWNLOAD)
            elif kind == "ready":
                if value == self.connection_target == self.connected_address and self.pending_simulator:
                    entry, self.pending_simulator = self.pending_simulator, None
                    self.launch_simulator(entry)
            elif kind == "status":
                self.set_status(value)
            elif kind == "progress":
                self.set_status(value, busy=True)
            elif kind == "diagnostic":
                self.diagnostics.append(value)
                del self.diagnostics[:-12]
            elif kind == "connection":
                self.connected_address = value
                self.update_connect_button()
            elif kind == "values":
                if value is None:
                    self.raw_channels = None
                self.render_channels(value)
            elif kind == "devices":
                for key, profile in value.items():
                    self.settings["senders"].setdefault(key, profile)
                self.refresh(self.selected())
                self.set_status(message("{count} mögliche Sender gefunden. Auswählen und verbinden.", count=len(value))
                                if value else "Kein FrSky-Sender gefunden. Prüfe den Schülermodus.")
            elif kind == "finished" and value == "connect":
                self.pending_simulator = None
                self.connecting = False
                self.update_connect_button()
            elif kind == "finished" and value == "scan":
                self.scanning = False
                self.progress.stop()
                self.progress.pack_forget()
                for button in self.buttons:
                    button.state(["!disabled"])
                self.update_connect_button()
        if self.closing and not self.worker.thread.is_alive():
            self.tray.stop()
            self.worker.loop.close()
            self.root.destroy()
        else:
            self.root.after(60, self.poll)

    def close(self):
        if not self.closing:
            self.closing = True
            self.set_status("Trenne Bluetooth und gebe vJoy frei …")
            self.worker.submit(None)


def run_once(start):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateMutexW
    create.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p)
    create.restype = ctypes.c_void_p
    close = kernel.CloseHandle
    close.argtypes = (ctypes.c_void_p,)
    close.restype = ctypes.c_int
    name = r"Local\FrSkyBluetoothTrainer"
    handle = create(None, False, name)
    error = ctypes.get_last_error()
    if not handle:
        raise ctypes.WinError(error)
    try:
        if error == 183:  # ERROR_ALREADY_EXISTS
            return False
        start()
        return True
    finally:
        close(handle)


def start_app():
    set_app_id = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
    set_app_id.argtypes = (ctypes.c_wchar_p,)
    set_app_id.restype = ctypes.c_long
    set_app_id("FrSkyBluetoothTrainer.Desktop")
    root = tk.Tk()
    Application(root)
    root.mainloop()


if __name__ == "__main__":
    if not run_once(start_app):
        root = tk.Tk()
        root.withdraw()
        german = ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF == 7
        messagebox.showinfo(
            "FrSky Bluetooth Trainer",
            "Die App läuft bereits. Du findest sie im Windows-Infobereich neben der Uhr."
            if german else "The app is already running. Look in the Windows notification area near the clock.",
            parent=root,
        )
        root.destroy()
