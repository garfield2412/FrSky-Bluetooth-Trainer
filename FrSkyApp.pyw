import asyncio
import ctypes
import hashlib
import time
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
from tkinter import filedialog, font, messagebox, ttk

from test_frsky_ble import CHARACTERISTIC, SERVICE, BleakClient, BleakError, BleakScanner, TrainerDecoder
from vjoy_output import BUTTON_HIGH, BUTTON_LOW, BUTTON_MODES, VJoyOutput, VJoyUnavailable, button_pressed

FROZEN = getattr(sys, "frozen", False)
APP_DIRECTORY = Path(sys.executable).parent if FROZEN else Path(__file__).parent
SETTINGS = (Path(os.environ["LOCALAPPDATA"]) / "FrSky Bluetooth Trainer" / "config.xml"
            if FROZEN else APP_DIRECTORY / "config.xml")
LEGACY_SETTINGS = SETTINGS.with_name("transmitter-list.json")
DEFAULT = list(range(1, 9))
FRSKY_BLACK = "#222222"
FRSKY_YELLOW = "#f5c438"
LIVE_SURFACE = "#fffefa"
LIVE_BORDER = "#d0cbc0"
LIVE_VALUE = "#674d08"

sys.path.insert(0, str(Path(__file__).with_name("tray-libs")))
import pystray
from PIL import Image, ImageDraw, ImageTk


SIMULATOR_TYPES = (".exe", ".bat", ".cmd", ".lnk")


LANGUAGE_CATALOG = json.loads(Path(__file__).with_name("languages.json").read_text(encoding="utf-8"))
LANGUAGES = ("system", *LANGUAGE_CATALOG)
AXIS_DESCRIPTIONS = {'X': 'X-Achse', 'Y': 'Y-Achse', 'Z': 'Z-Achse', 'Rx': 'Drehung um X', 'Ry': 'Drehung um Y', 'Rz': 'Drehung um Z', 'Slider': 'Schieberegler', 'Dial': 'Drehregler'}

VJOY_DOWNLOAD = "https://github.com/BrunnerInnovation/vJoy/releases/tag/v2.2.2.0"
VJOY_TITLE = "vJoy fehlt oder ist nicht aktiv"
VJOY_PROMPT = ("Lade vJoy herunter und installiere es. Wenn es bereits installiert ist, "
               "aktiviere oder repariere den Treiber. Klicke danach erneut auf Verbinden.\n\nDownloadseite öffnen?")


PROJECT_URL = "https://github.com/garfield2412/FrSky-Bluetooth-Trainer"
TRAINER_MANUAL = "https://ethos-doc.frsky-rc.com/model-setup/trainer/#bluetooth"


CONTROLS_TIMEOUT = 0.5
RECONNECT_TIMEOUT = 5
READY_STATUS = "Bereit · Steuerdaten werden an vJoy übertragen."


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
    translations = LANGUAGE_CATALOG.get(language, LANGUAGE_CATALOG["en"])["messages"]
    text = translations.get(text, LANGUAGE_CATALOG["en"]["messages"].get(text, text) if language != "de" else text)
    return text.format(**{key: translate(item, language) if isinstance(item, tuple) else item
                          for key, item in fields.items()}) if fields else text


def decode_button(token):
    if token.endswith("m"):
        return int(token[:-1]), "middle"
    value = int(token)
    return (abs(value), value >= 0)


def encode_button(channel, mode):
    if not channel:
        return "0"
    if mode == "middle":
        return f"{channel}m"
    return str(channel if mode else -channel)


def read_mapping(node):
    channels = [int(channel) for channel in node.attrib["channels"].split()]
    buttons = [decode_button(token) for token in node.get("buttons", "").split()]
    if (len(channels) != 8 or len(set(channels)) != 8 or any(not 1 <= channel <= 16 for channel in channels)
            or len(buttons) > 8 or any(not 0 <= channel <= 16 for channel, _ in buttons)):
        raise ValueError("Invalid channel or button assignment")
    return channels, buttons


def import_mapping(path):
    node = ET.parse(path).getroot()
    if node.tag != "frsky-mapping" or node.get("version") != "1":
        raise ValueError("Invalid mapping format")
    return read_mapping(node)


def mapping_attributes(channels, buttons):
    return {
        "channels": " ".join(map(str, channels)),
        "buttons": " ".join(encode_button(channel, mode) for channel, mode in buttons),
    }


def load_settings(path):
    root = ET.parse(path).getroot()
    if root.tag != "config":
        raise ValueError("Invalid configuration root")
    senders = {}
    for node in root.findall("./transmitters/transmitter"):
        try:
            channels, buttons = read_mapping(node)
        except (KeyError, ValueError):
            channels, buttons = DEFAULT.copy(), []
        senders[node.attrib["address"]] = {"name": node.attrib["name"], "channels": channels, "buttons": buttons}
    return {
        "language": root.get("language", "system"),
        "last": root.get("last-transmitter", ""),
        "last_simulator": int(root.get("last-simulator", "0")),
        "start_in_tray": root.get("start-in-tray", "false") == "true",
        "auto_launch": root.get("auto-launch", "false") == "true",
        "auto_launch_at_login": root.get("auto-launch-at-login", "false") == "true",
        "senders": senders,
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
            **mapping_attributes(profile["channels"], profile.get("buttons", [])),
        })
    simulators = ET.SubElement(root, "simulators")
    for entry in settings.get("simulators", []):
        ET.SubElement(simulators, "simulator", {"name": entry["name"], "path": entry["path"]})
    path.parent.mkdir(parents=True, exist_ok=True)
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

    async def connect(self, address, channels, buttons=()):
        try:
            output = VJoyOutput(channels, buttons=buttons)
        except RuntimeError as error:
            if "konnte nicht geöffnet werden" in str(error):
                raise RuntimeError("vJoy-Gerät 1 ist möglicherweise belegt. Beende das alte Bluetooth-Skript mit Strg+X und klicke auf Verbinden.") from error
            raise
        highest_channel = max(*channels, *(channel for channel, _ in buttons))
        def clean_output(action):
            active_error = sys.exception()
            try:
                action()
            except (OSError, RuntimeError) as error:
                if active_error is None:
                    raise
                active_error.add_note(str(error))

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
                        decoder = TrainerDecoder(extended=True)
                        latest = None
                        positions = button_states = []
                        packet_count = 0
                        first_packet = previous_packet = None
                        latest_interval = longest_interval = 0.0
                        next_quality_update = 0.0
                        last_packet = self.loop.time()
                        self.events.put(("quality", None))
                        self.events.put(("neutralized", False))
                        display_timer = None
                        write_error = None
                        neutralized = False

                        def refresh_display():
                            nonlocal display_timer
                            display_timer = None
                            if not disconnected.is_set():
                                self.events.put(("raw_channels", (address, latest)))
                                self.events.put(("values", latest))
                                self.events.put(("button_states", button_states))
                                self.events.put(("vjoy_output", positions))

                        def on_packet(_, data):
                            nonlocal latest, last_packet, display_timer, write_error, failures, phase, positions, button_states, neutralized
                            nonlocal packet_count, first_packet, previous_packet, latest_interval, longest_interval, next_quality_update
                            if disconnected.is_set():
                                return
                            for values in decoder.feed(data):
                                last_packet = self.loop.time()
                                packet_count += 1
                                if previous_packet is None:
                                    first_packet = last_packet
                                else:
                                    latest_interval = last_packet - previous_packet
                                    longest_interval = max(longest_interval, latest_interval)
                                previous_packet = last_packet
                                if last_packet >= next_quality_update or neutralized or packet_count == 2:
                                    mean = (last_packet - first_packet) / max(1, packet_count - 1)
                                    self.events.put(("quality", (packet_count, latest_interval, mean, longest_interval,
                                                                 time.monotonic())))
                                    next_quality_update = last_packet + 0.25
                                if values == latest:
                                    continue
                                try:
                                    if highest_channel > len(values):
                                        raise RuntimeError("Die Kanalzuordnung benötigt einen Sender mit 16 Trainerkanälen.")
                                    positions, button_states = output.write(values)
                                except (OSError, RuntimeError) as error:
                                    write_error = error
                                    self.events.put(("vjoy_error", str(error)))
                                    disconnected.set()
                                    return
                                if latest is None:
                                    self.events.put(("diagnostic", message("Erste Steuerdaten nach {seconds:.1f} s an vJoy übergeben.", seconds=self.loop.time() - started)))
                                    self.events.put(("status", READY_STATUS))
                                    neutralized = False
                                    self.events.put(("neutralized", False))
                                    self.events.put(("ready", address))
                                    phase = "Laufende Verbindung"
                                    failures = 0
                                latest = values
                                if display_timer is None:
                                    display_timer = self.loop.call_later(0.05, refresh_display)

                        try:
                            await client.start_notify(CHARACTERISTIC, on_packet)
                            while not disconnected.is_set():
                                elapsed = self.loop.time() - last_packet
                                remaining = RECONNECT_TIMEOUT - elapsed
                                if remaining <= 0:
                                    raise TimeoutError("Keine gültigen Trainerdaten.")
                                if latest is not None and not neutralized:
                                    until_reset = CONTROLS_TIMEOUT - elapsed
                                    if until_reset <= 0:
                                        try:
                                            output.center()
                                        except (OSError, RuntimeError) as error:
                                            self.events.put(("vjoy_error", str(error)))
                                            raise RuntimeError("vJoy konnte nicht zurückgesetzt werden") from error
                                        self.events.put(("neutralized", True))
                                        latest = None
                                        neutralized = True
                                        if display_timer is not None:
                                            display_timer.cancel()
                                            display_timer = None
                                        self.events.put(("values", None))
                                        self.events.put(("progress", "Keine Steuerdaten. vJoy ist neutralisiert. Warte auf den Sender …"))
                                    else:
                                        remaining = min(remaining, until_reset)
                                # A resumed stream can arm a new deadline while this coroutine waits.
                                remaining = min(remaining, CONTROLS_TIMEOUT)
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
                            try:
                                clean_output(output.center)
                            finally:
                                self.events.put(("values", None))
                        raise ConnectionError("Bluetooth getrennt.")
                except (ConnectionError, TimeoutError, OSError, BleakError) as error:
                    self.events.put(("connection", None))
                    self.events.put(("failure", (phase, type(error).__name__)))
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
            clean_output(output.close)


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
            if FROZEN and not SETTINGS.exists():
                previous = APP_DIRECTORY / "config.xml"
                if previous.is_file():
                    save_settings(SETTINGS, load_settings(previous))
                else:
                    legacy = APP_DIRECTORY / "transmitter-list.json"
                    if legacy.is_file():
                        save_settings(SETTINGS, json.loads(legacy.read_text(encoding="utf-8")))
            if SETTINGS.exists():
                self.settings.update(load_settings(SETTINGS))
            elif LEGACY_SETTINGS.exists():
                self.settings.update(json.loads(LEGACY_SETTINGS.read_text(encoding="utf-8")))
        except (OSError, ValueError, KeyError, ET.ParseError):
            pass

        self.localized_widgets = []
        self.localized_menu_entries = []
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
        style.configure("Ethos.TLabel", background=FRSKY_BLACK, padding=(5, 1))
        body = ttk.Frame(root, padding=(16, 10))
        body.pack(fill="both", expand=True)
        header = ttk.Frame(body, style="Brand.TFrame", padding=(9, 4))
        header.pack(fill="x")
        tk.Frame(body, background=FRSKY_YELLOW, height=3).pack(fill="x")
        self.brand_logos = []
        for filename, size, url, spacing, logo_style in (
            ("frsky-logo.png", (168, 36), "https://www.frsky-rc.com/", 0, "Brand.TLabel"),
            ("ethos-logo.png", (82, 32), "https://ethos.frsky-rc.com/", 12, "Ethos.TLabel"),
        ):
            try:
                with Image.open(Path(__file__).with_name(filename)) as logo:
                    logo.thumbnail(size, Image.Resampling.LANCZOS)
                    photo = ImageTk.PhotoImage(logo, master=root)
            except OSError:
                continue
            self.brand_logos.append(photo)
            logo_link = ttk.Label(header, image=photo, style=logo_style, cursor="hand2", takefocus=True)
            logo_link.pack(side="left", padx=(spacing, 0))
            for event in ("<Button-1>", "<Return>", "<space>"):
                logo_link.bind(event, lambda _, target=url: webbrowser.open(target))
        self.language_picker = ttk.Combobox(header, width=22, state="readonly")
        self.widget(ttk.Button, header, "Hilfe", command=self.show_help).pack(side="right", padx=(8, 0))
        self.widget(ttk.Button, header, "GitHub", command=self.open_project).pack(side="right", padx=(8, 0))
        self.language_picker.pack(side="right")
        self.widget(ttk.Label, header, "Sprache", style="Brand.TLabel").pack(side="right", padx=(0, 6))
        self.language_picker.bind("<<ComboboxSelected>>", self.change_language)
        self.update_language_picker()
        bluetooth = self.widget(ttk.LabelFrame, body, "Bluetooth", padding=(10, 6))
        bluetooth.pack(fill="x", pady=(8, 6))
        self.widget(ttk.Label, bluetooth, "Sender").pack(anchor="w")
        sender_bar = ttk.Frame(bluetooth)
        sender_bar.pack(fill="x", pady=(3, 6))
        self.sender = ttk.Combobox(sender_bar, state="readonly")
        self.sender.pack(side="left", fill="x", expand=True)
        self.sender_menu = self.management_menu(sender_bar, [("Sender entfernen", self.remove_sender)])
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
        self.search_hint = tk.StringVar()
        tk.Label(bluetooth, textvariable=self.search_hint, wraplength=540, width=1, height=1,
                 background=surface, foreground=ink, anchor="w", justify="left").pack(fill="x")
        self.sender.bind("<<ComboboxSelected>>", self.sender_selected)
        self.update_connect_button()
        self.simulators = self.settings.setdefault("simulators", [])
        simulator = self.widget(ttk.LabelFrame, body, "Simulator", padding=(10, 6))
        simulator.pack(fill="x", pady=(0, 6))
        simulator_bar = ttk.Frame(simulator)
        simulator_bar.pack(fill="x")
        self.simulator_picker = ttk.Combobox(simulator_bar, state="readonly", width=17)
        self.simulator_picker.pack(side="left", fill="x", expand=True)
        self.simulator_picker.bind("<<ComboboxSelected>>", self.select_simulator)
        self.simulator_menu = self.management_menu(simulator_bar, [
            ("Hinzufügen", lambda: self.edit_simulator()),
            ("Bearbeiten", lambda: self.edit_simulator(self.simulator_picker.current())),
            ("Entfernen", self.remove_simulator),
        ])
        self.simulator_start_button = self.widget(ttk.Button, simulator_bar, "Starten",
                                                  command=self.request_simulator_launch, style="Launch.TButton")
        self.simulator_start_button.pack(side="left", padx=(12, 0))
        self.simulator_hint = tk.StringVar()
        tk.Label(simulator, textvariable=self.simulator_hint, width=1, height=1, anchor="w",
                 background=surface, foreground=ink).pack(fill="x", pady=(3, 0))
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
        self.quality = None
        self.neutralized = False
        self.last_failure = None
        self.output_values = []
        self.output_error = None
        self.status = tk.StringVar(value=self.tr(self.status_message))
        line_height = font.nametofont("TkDefaultFont", root=root).metrics("linespace")
        self.status_canvas = tk.Canvas(bluetooth, width=1, height=3 * line_height + 4,
                                       background=surface, highlightthickness=0)
        self.status_canvas.pack(fill="x", pady=(6, 4))
        self.progress_band = self.status_canvas.create_rectangle(0, 0, 0, 0, fill="#fae7a5",
                                                                outline="", state="hidden")
        self.status_text = self.status_canvas.create_text(5, 2, anchor="nw", fill=ink, font="TkDefaultFont")
        self.progress_job = None
        self.progress_step = 0
        self.status.trace_add("write", self.update_status_text)
        self.status_canvas.bind("<Configure>", self.update_status_text)
        self.update_status_text()
        connection_tools = ttk.Frame(bluetooth)
        connection_tools.pack(fill="x")
        self.widget(ttk.Button, connection_tools, "Bluetooth-Details",
                    command=self.show_diagnostics).pack(side="left")
        self.widget(ttk.Button, connection_tools, "Windows-Gamecontroller",
                    command=self.open_game_controllers).pack(side="left", padx=(8, 0))

        self.live = tk.BooleanVar()
        self.widget(ttk.Checkbutton, body, "Live-Anzeige", variable=self.live, command=self.toggle).pack(anchor="w")
        self.details = ttk.Notebook(body)
        self.channel_pages = [ttk.Frame(self.details), ttk.Frame(self.details)]
        for page in self.channel_pages:
            page.columnconfigure((0, 1, 2, 3), weight=1, uniform="channel")
        self.details.add(self.channel_pages[0], text="CH1–CH8")
        self.button_page = ttk.Frame(self.details)
        self.output_page = ttk.Frame(self.details, padding=(8, 4))
        self.details.add(self.output_page, text=self.tr("vJoy-Ausgabe"))
        self.output_status = ttk.Label(self.output_page, wraplength=510)
        self.output_status.pack(anchor="w")
        self.output_axes = ttk.Label(self.output_page, justify="left")
        self.output_axes.pack(anchor="w")
        self.output_buttons = ttk.Label(self.output_page, wraplength=510, justify="left")
        self.output_buttons.pack(anchor="w")
        self.render_output()
        self.button_status = []
        self.button_states = []
        for index in range(8):
            label = ttk.Label(self.button_page, padding=(10, 5))
            self.button_status.append(label)
        self.meters = []
        for index in range(16):
            card = tk.Frame(self.channel_pages[index // 8], background=LIVE_SURFACE, highlightthickness=1,
                            highlightbackground=LIVE_BORDER, padx=7, pady=3)
            card.grid(row=(index % 8) // 4, column=index % 4, sticky="ew", padx=3, pady=2)
            card.columnconfigure(0, weight=1)
            tk.Label(card, text=f"CH{index + 1}", bg=LIVE_SURFACE, fg=FRSKY_BLACK,
                     font=("Segoe UI", 10, "bold")).grid(row=0, column=0, sticky="w")
            number = tk.StringVar(value="—")
            tk.Label(card, textvariable=number, bg=LIVE_SURFACE, fg=LIVE_VALUE,
                     font=("Consolas", 10)).grid(row=0, column=1, sticky="e")
            meter = tk.Canvas(card, width=100, height=22, background=LIVE_SURFACE,
                              highlightthickness=0)
            meter.grid(row=1, column=0, columnspan=2, sticky="ew")
            self.meters.append((meter, number))
            meter.bind("<Configure>", lambda event, i=index: self.draw_meter(
                event.widget,
                self.channel_values[i] if self.channel_values is not None and i < len(self.channel_values) else None,
                light=True,
            ))
        self.channel_values = None
        self.details.update_idletasks()
        self.details.configure(width=self.channel_pages[0].winfo_reqwidth(),
                               height=max(self.channel_pages[0].winfo_reqheight(),
                                          4 * (self.button_status[0].winfo_reqheight() + 4)))
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
        # Reserve room for all supported languages before showing the window.
        widths = [640]
        for language in LANGUAGE_CATALOG:
            for widget, label in self.localized_widgets:
                widget.configure(text=translate(label, language))
            root.update_idletasks()
            widths.append(root.winfo_reqwidth())
        for widget, label in self.localized_widgets:
            widget.configure(text=self.tr(label))
        root.minsize(max(widths), 1)
        self.render_buttons([])
        root.after(60, self.poll)
        if self.selected() is not None:
            root.after(150, lambda: self.connect(at_start=True))

    @staticmethod
    def language_for_windows(language_id):
        primary = language_id & 0x3FF
        return next((code for code, entry in LANGUAGE_CATALOG.items()
                     if entry["windows_primary"] == primary), "en")

    def effective_language(self):
        if self.language_preference != "system":
            return self.language_preference
        language_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        return self.language_for_windows(language_id)

    def tr(self, value):
        return translate(value, self.language)

    def widget(self, cls, parent, label, **options):
        widget = cls(parent, text=self.tr(label), **options)
        self.localized_widgets.append((widget, label))
        return widget

    def management_menu(self, parent, commands):
        button = ttk.Menubutton(parent, text="⋯", width=3)
        button.pack(side="left", padx=(6, 0))
        menu = tk.Menu(button, tearoff=False)
        for index, (label, command) in enumerate(commands):
            menu.add_command(label=self.tr(label), command=command)
            self.localized_menu_entries.append((menu, index, label))
        button.configure(menu=menu)
        return menu

    def update_language_picker(self):
        system = self.language_for_windows(ctypes.windll.kernel32.GetUserDefaultUILanguage())
        self.language_picker["values"] = (f'{self.tr("Systemsprache")} ({LANGUAGE_CATALOG[system]["name"]})',
                                          *(entry["name"] for entry in LANGUAGE_CATALOG.values()))
        self.language_picker.current(LANGUAGES.index(self.language_preference))

    def change_language(self, _=None):
        self.language_preference = LANGUAGES[self.language_picker.current()]
        self.language = self.effective_language()
        self.settings["language"] = self.language_preference
        for widget, label in self.localized_widgets:
            widget.configure(text=self.tr(label))
        self.update_language_picker()
        for menu, index, label in self.localized_menu_entries:
            menu.entryconfigure(index, label=self.tr(label))
        self.details.tab(self.output_page, text=self.tr("vJoy-Ausgabe"))
        self.render_output()
        if self.button_states:
            states, self.button_states = self.button_states, []
            self.details.tab(self.button_page, text=self.tr("vJoy-Tasten"))
            self.render_buttons(states)
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
        for index in (1, 2):
            self.simulator_menu.entryconfigure(index, state="normal" if self.simulators else "disabled")
        self.update_simulator_start()
        if hasattr(self, "tray"):
            self.tray.update_menu()

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

    def update_simulator_start(self):
        self.simulator_start_enabled = bool(
            self.simulators and self.status_message == READY_STATUS
            and self.connected_address is not None
            and not (self.disconnecting or self.scanning or self.closing)
        )
        self.simulator_start_button.state(["!disabled" if self.simulator_start_enabled else "disabled"])
        hint = ("Simulator über ⋯ hinzufügen" if not self.simulators else
                "" if self.simulator_start_enabled else "Zuerst Sender verbinden")
        self.simulator_hint.set(self.tr(hint))

    def request_simulator_launch(self, entry=None):
        if entry is None:
            index = self.simulator_picker.current()
            if index < 0:
                return
            entry = self.simulators[index]
        self.launch_simulator(entry)

    def launch_simulator(self, entry):
        if not self.simulator_start_enabled or entry not in self.simulators:
            return
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
        if not self.connecting:
            self.render_buttons([])
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

    def save(self, settings=None, *, parent=None):
        try:
            save_settings(SETTINGS, self.settings if settings is None else settings)
        except OSError as error:
            messagebox.showerror(self.tr("Konfiguration konnte nicht gespeichert werden"),
                                 str(error), parent=parent or self.root)
            return False
        return True

    def sender_selected(self, _event):
        self.update_connect_button()
        if not self.connecting:
            self.render_buttons([])

    def update_connect_button(self):
        address = self.selected()
        same_sender = address == self.connected_address or (self.connecting and address == self.connection_target)
        disabled = self.scanning or self.disconnecting or address is None or same_sender
        self.buttons[2].state(["disabled" if self.scanning or self.disconnecting or address is None else "!disabled"])
        self.sender_menu.entryconfigure(0, state="normal" if self.can_remove_sender(address) else "disabled")
        self.buttons[0].state(["disabled" if disabled else "!disabled"])
        active = self.connecting or self.connected_address is not None
        self.buttons[1].state(["disabled" if active or self.scanning or self.disconnecting else "!disabled"])
        self.search_hint.set(self.tr("Sender zuerst trennen, um nach weiteren Sendern zu suchen.") if active else "")
        can_disconnect = self.connecting and not self.disconnecting and not self.scanning
        self.disconnect_button.state(["!disabled" if can_disconnect else "disabled"])
        self.tray_connect_enabled = self.can_connect_from_tray()
        if hasattr(self, "simulator_start_button"):
            self.update_simulator_start()
        if hasattr(self, "tray"):
            self.tray.update_menu()

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
        self.quality = None
        self.neutralized = False
        self.last_failure = None
        self.output_error = None
        self.render_output()
        self.set_status("Starte Verbindung …", busy=True)
        profile = self.settings["senders"][address]
        self.worker.submit(self.worker.connect, address, profile["channels"], profile.get("buttons", []))

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
        if self.connecting or self.connected_address is not None or self.scanning or self.disconnecting:
            return
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
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 12)
        )
        ttk.Label(panel, text=self.tr("vJoy-Achse")).grid(row=1, column=0, sticky="w")
        ttk.Label(panel, text=self.tr("Senderkanal")).grid(row=1, column=1, sticky="w", padx=(30, 0))

        choices = [f"CH{channel}" for channel in range(1, 17)]
        axis_labels = tuple(f"{self.tr(AXIS_DESCRIPTIONS[axis])} ({axis})"
                            for axis in VJoyOutput.axis_names)
        selectors = []
        axis_meters = []
        panel_background = ttk.Style(panel).lookup("TFrame", "background")
        for row, (axis, channel) in enumerate(zip(axis_labels, profile["channels"]), 2):
            ttk.Label(panel, text=axis).grid(row=row, column=0, sticky="w", pady=3)
            selector = ttk.Combobox(panel, values=choices, state="readonly", width=13)
            selector.current(channel - 1)
            selector.bind("<FocusIn>", lambda event: event.widget.selection_clear())
            selector.bind("<<ComboboxSelected>>", lambda event: event.widget.selection_clear())
            selector.grid(row=row, column=1, sticky="w", padx=(30, 0), pady=3)
            selectors.append(selector)
            meter = tk.Canvas(panel, width=88, height=22, background=panel_background, highlightthickness=0)
            meter.grid(row=row, column=2, padx=(8, 0), sticky="e")
            axis_meters.append(meter)

        guide = ttk.Frame(panel)
        guide.grid(row=10, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        button_labels = tuple(self.tr(message("Taste {number}", number=i)) for i in range(1, 9))
        target_picker = ttk.Combobox(guide, state="readonly", width=21, values=axis_labels + button_labels)
        target_picker.current(0)
        target_picker.pack(side="left")
        detected = None
        baseline = None
        hint = tk.StringVar()

        def use_detected():
            target = target_picker.current()
            if detected is None or target < 0:
                return
            if target >= len(axis_labels):
                source, _, _, _ = button_fields[target - len(axis_labels)]
                source.current(detected + 1)
                return
            other = next((i for i, item in enumerate(selectors) if item.current() == detected), None)
            if other is not None:
                selectors[other].current(selectors[target].current())
            selectors[target].current(detected)

        use = ttk.Button(guide, text=self.tr("Erkannten Kanal übernehmen"), command=use_detected, state="disabled")
        use.pack(side="left", padx=6)
        ttk.Label(panel, textvariable=hint, foreground=FRSKY_BLACK, font=("Segoe UI", 10, "bold")).grid(row=11, column=0, columnspan=3, sticky="w")

        detected_meter = tk.Canvas(panel, width=260, height=28, background=FRSKY_BLACK, highlightthickness=0)
        detected_meter.grid(row=12, column=0, columnspan=3, sticky="ew", pady=3)

        timer = None

        def detect():
            nonlocal baseline, detected, timer
            current = None
            if self.raw_channels is None or self.raw_channels[0] != address:
                baseline = detected = None
                hint.set(self.tr("Warte auf Daten vom ausgewählten Sender."))
            else:
                current = self.raw_channels[1]
                if baseline is None or len(baseline) != len(current):
                    baseline = current
                    detected = None
                else:
                    changes = [abs(old - new) for old, new in zip(baseline, current)]
                    index = max(range(len(changes)), key=changes.__getitem__)
                    if changes[index] >= 35 and changes.count(changes[index]) == 1:
                        detected = index
                        baseline = current
                hint.set(self.tr("Achse oder Taste wählen und einen Geber bewegen.") if detected is None
                         else f"CH{detected + 1} · {current[detected]} µs")
            self.draw_meter(detected_meter, None if detected is None else current[detected])
            use.state(["disabled" if detected is None else "!disabled"])
            for selector, meter in zip(selectors, axis_meters):
                index = selector.current()
                raw = current[index] if current is not None and 0 <= index < len(current) else None
                self.draw_meter(meter, raw)
            for source, position, label, meter in button_fields:
                channel = source.current()
                mode = BUTTON_MODES[position.current()]
                raw = current[channel - 1] if current is not None and 0 < channel <= len(current) else None
                self.draw_button_meter(meter, raw, mode, assigned=channel > 0)
                active = raw is not None and button_pressed(raw, mode)
                label.configure(background=FRSKY_YELLOW if active else "", foreground=FRSKY_BLACK if active else "")
            timer = dialog.after(100, detect)

        dialog.bind("<Destroy>", lambda event: dialog.after_cancel(timer)
                    if event.widget is dialog and timer is not None else None)
        error = tk.StringVar()
        ttk.Label(panel, textvariable=error, foreground="#a61b1b", wraplength=350).grid(
            row=13, column=0, columnspan=3, sticky="w", pady=(8, 0)
        )

        def reset():
            for index, selector in enumerate(selectors):
                selector.current(index)
            error.set("")

        button_panel = ttk.LabelFrame(panel, text=self.tr("vJoy-Tasten"), padding=6)
        button_panel.grid(row=14, column=0, columnspan=3, sticky="ew", pady=(6, 0))
        button_fields = []
        saved_buttons = (profile.get("buttons") or []) + [(0, True)] * 8
        for index in range(8):
            channel, high = saved_buttons[index]
            row, group = index % 4 + 1, (index // 4) * 4
            if row == 1:
                ttk.Label(button_panel, text=self.tr("Gedrückt bei")).grid(row=0, column=group + 2)
            label = ttk.Label(button_panel, text=self.tr(message("Taste {number}", number=index + 1)), padding=(3, 1))
            label.grid(row=row, column=group, sticky="ew")
            source = ttk.Combobox(button_panel, values=[self.tr("Aus"), *choices], state="readonly", width=8)
            source.current(channel)
            source.grid(row=row, column=group + 1, padx=6, pady=2)
            position = ttk.Combobox(button_panel, values=(f"≥ {BUTTON_HIGH} µs", f'{self.tr("Mitte")} ({BUTTON_LOW + 1}–{BUTTON_HIGH - 1} µs)',
                                                           f"≤ {BUTTON_LOW} µs"), state="readonly", width=21)
            position.current(BUTTON_MODES.index(high))
            position.grid(row=row, column=group + 2)
            meter = tk.Canvas(button_panel, width=62, height=16, background=panel_background, highlightthickness=0)
            meter.grid(row=row, column=group + 3, padx=(5, 6))
            button_fields.append((source, position, label, meter))
        detect()

        def draft_mapping():
            channels = [selector.current() + 1 for selector in selectors]
            if 0 in channels:
                error.set(self.tr("Wähle für jede Achse einen Senderkanal aus."))
                return
            duplicates = [f"CH{channel}" for channel in sorted(set(channels)) if channels.count(channel) > 1]
            if duplicates:
                error.set(self.tr(message("Mehrfach zugeordnet: {channels}", channels=", ".join(duplicates))))
                return
            buttons = [(source.current(), BUTTON_MODES[position.current()] if source.current() else True)
                       for source, position, _, _ in button_fields]
            while buttons and not buttons[-1][0]:
                buttons.pop()
            return channels, buttons

        def load_draft(channels, buttons):
            for selector, channel in zip(selectors, channels):
                selector.current(channel - 1)
            for (source, position, _, _), (channel, mode) in zip(button_fields, buttons + [(0, True)] * 8):
                source.current(channel)
                position.current(BUTTON_MODES.index(mode))
            error.set("")
            transfer_status.set(self.tr("Zuordnung geladen. Mit Übernehmen speichern."))

        def load_file():
            filename = filedialog.askopenfilename(parent=dialog, filetypes=[("XML", "*.xml")])
            if not filename:
                return
            try:
                load_draft(*import_mapping(filename))
            except (OSError, ET.ParseError, KeyError, ValueError):
                messagebox.showerror(self.tr("Zuordnung importieren …"), self.tr("Ungültige Zuordnungsdatei."),
                                     parent=dialog)

        def export_file():
            draft = draft_mapping()
            if draft is None:
                return
            filename = filedialog.asksaveasfilename(parent=dialog, defaultextension=".xml",
                                                     initialfile="frsky-mapping.xml", filetypes=[("XML", "*.xml")])
            if not filename:
                return
            node = ET.Element("frsky-mapping", {"version": "1", **mapping_attributes(*draft)})
            try:
                ET.ElementTree(node).write(filename, encoding="utf-8", xml_declaration=True)
            except OSError as exc:
                messagebox.showerror(self.tr("Zuordnung konnte nicht exportiert werden"), str(exc), parent=dialog)

        def apply_mapping():
            draft = draft_mapping()
            if draft is None:
                return
            channels, buttons = draft
            changed = channels != profile["channels"] or buttons != profile.get("buttons", [])
            if changed:
                updated_profile = {**profile, "channels": channels, "buttons": buttons}
                updated_senders = {**self.settings["senders"], address: updated_profile}
                if not self.save({**self.settings, "senders": updated_senders}, parent=dialog):
                    return
                self.settings["senders"][address] = updated_profile
            dialog.destroy()
            if changed and self.connecting and self.connection_target == address:
                self.connect(launch=False)

        actions = ttk.Frame(panel)
        actions.grid(row=16, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        transfer = ttk.Frame(panel)
        transfer.grid(row=15, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        picker = ttk.Menubutton(transfer, text=self.tr("Zuordnung kopieren von …"))
        copy_menu = tk.Menu(picker, tearoff=False)
        for key, source_profile in self.settings["senders"].items():
            if key != address:
                copy_menu.add_command(label=f'{source_profile["name"]} · {key}',
                                      command=partial(load_draft, source_profile["channels"],
                                                      source_profile.get("buttons", [])))
        if copy_menu.index("end") is None:
            copy_menu.add_command(label=self.tr("Keine weiteren Senderprofile"), state="disabled")
        picker.configure(menu=copy_menu)
        picker.pack(side="left", padx=(0, 6))
        ttk.Button(transfer, text=self.tr("Zuordnung importieren …"), command=load_file).pack(side="left", padx=(0, 6))
        ttk.Button(transfer, text=self.tr("Zuordnung exportieren …"), command=export_file).pack(side="left")
        transfer_status = tk.StringVar()
        ttk.Label(panel, textvariable=transfer_status).grid(row=17, column=0, columnspan=3, sticky="w")
        ttk.Button(actions, text=self.tr("Standard"), command=reset).pack(side="left", padx=(0, 12))
        ttk.Button(actions, text=self.tr("Windows-Gamecontroller"),
                   command=partial(self.open_game_controllers, dialog)).pack(side="left", padx=(0, 6))
        ttk.Button(actions, text=self.tr("Übernehmen"), command=apply_mapping, style="Launch.TButton").pack(side="right")
        ttk.Button(actions, text=self.tr("Abbrechen"), command=dialog.destroy).pack(side="right", padx=(0, 6))
        dialog.bind("<Escape>", lambda _: dialog.destroy())
        dialog.grab_set()
        dialog.focus_set()


    def toggle(self):
        if self.live.get():
            self.details.pack(fill="x", pady=(4, 0), before=self.footer)
        else:
            self.details.pack_forget()

    def render_buttons(self, states):
        if not states:
            address = self.connection_target if self.connecting else self.selected()
            profile = self.settings["senders"].get(address, {})
            states = [(index, channel, None)
                      for index, (channel, _) in enumerate(profile.get("buttons", []), 1) if channel]
        if states == self.button_states:
            return
        self.button_states = states
        visible = str(self.button_page) in self.details.tabs()
        if not states:
            if visible:
                self.details.forget(self.button_page)
            return
        if not visible:
            self.details.insert(self.details.index(self.output_page), self.button_page, text=self.tr("vJoy-Tasten"))
        for label in self.button_status:
            label.grid_remove()
        for cell, (index, channel, pressed) in enumerate(states):
            label = self.button_status[index - 1]
            title = self.tr(message("Taste {number}", number=index))
            state = self.tr("Keine Live-Daten" if pressed is None else "Gedrückt" if pressed else "Losgelassen")
            label.configure(text=f"{title} · CH{channel} · {state}",
                            background=FRSKY_YELLOW if pressed else "#ebe8df",
                            foreground=FRSKY_BLACK)
            label.grid(row=cell // 2, column=cell % 2, sticky="ew", padx=4, pady=2)

    def render_output(self):
        status = ("Letzter vJoy-Schreibvorgang erfolgreich" if self.output_values
                  else "Keine gültige vJoy-Ausgabe")
        if self.output_error:
            status = message("vJoy-Schreibfehler: {error}", error=self.tr(message(self.output_error)))
        self.output_status.configure(text=self.tr(status))
        axes = [f"{axis} ← CH{channel}  {value}" for axis, (channel, value)
                in zip(VJoyOutput.axis_names, self.output_values)]
        self.output_axes.configure(text="\n".join("    ".join(axes[i:i + 4]) for i in range(0, len(axes), 4)))
        buttons = []
        if self.output_values:
            for index, channel, pressed in self.button_states:
                state = self.tr("Gedrückt" if pressed else "Losgelassen")
                buttons.append(f'{self.tr(message("Taste {number}", number=index))} · CH{channel} · {state}')
        self.output_buttons.configure(text="  ·  ".join(buttons))

    def render_channels(self, values):
        self.channel_values = values
        if values is None:
            self.output_values = []
            self.render_buttons([])
            self.render_output()
        extra = self.channel_pages[1]
        if values is not None and len(values) > 8:
            if str(extra) not in self.details.tabs():
                self.details.insert(1, extra, text="CH9–CH16")
        elif str(extra) in self.details.tabs():
            self.details.forget(extra)
        for index, (meter, number) in enumerate(self.meters):
            raw = values[index] if values is not None and index < len(values) else None
            self.draw_meter(meter, raw, light=True)
            number.set("—" if raw is None else f"{raw} µs")

    @staticmethod
    def draw_meter(meter, raw, *, light=False):
        left, right = 8, max(18, meter.winfo_width() - 8)
        center = (left + right) / 2
        meter.delete("all")
        meter.create_line(left, 10, right, 10, fill="#ded9cf" if light else "#484848", width=10, capstyle="round")
        for x in (left, center, right):
            meter.create_line(x, 16, x, 20, fill="#81796a" if light else "#bbbbbb", width=2 if x == center else 1)
        if raw is not None:
            ratio = (max(988, min(2012, raw)) - 988) / 1024
            position = left + (right - left) * ratio
            meter.create_line(center, 10, position, 10, fill=FRSKY_YELLOW, width=8, capstyle="round")
            meter.create_oval(position - 5, 5, position + 5, 15, fill=FRSKY_YELLOW,
                               outline="#83651a" if light else "#ffffff", width=1)

    @staticmethod
    def draw_button_meter(meter, raw, mode, *, assigned):
        meter.delete("all")
        if not assigned:
            return
        left, right = 3, max(4, meter.winfo_width() - 3)

        def pixel(value):
            return left + (right - left) * (max(988, min(2012, value)) - 988) / 1024

        low, high = {True: (BUTTON_HIGH, 2012), "middle": (BUTTON_LOW + 1, BUTTON_HIGH - 1),
                     False: (988, BUTTON_LOW)}[mode]
        meter.create_rectangle(left, 5, right, 11, fill="#ded9cf", outline="")
        meter.create_rectangle(pixel(low), 5, pixel(high), 11, fill=FRSKY_YELLOW, outline="")
        if raw is not None:
            x = pixel(raw)
            meter.create_line(x, 2, x, 14, fill=FRSKY_BLACK, width=2, tags=("position",))

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

        color = {"Verbunden": "#177845", "Verbindung wird hergestellt": "#754019",
                 "Getrennt": "#454545"}[state]
        draw.ellipse((64, 64, 126, 126), fill=color, outline="#f3f7fb", width=5)
        if state == "Verbunden":
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
                             enabled=lambda _: self.tray_connect_enabled),
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
                             enabled=lambda _: self.simulator_start_enabled),
            pystray.MenuItem(self.tr("Beenden"), lambda *_: self.events.put(("tray_exit", None))),
        )

    def set_status(self, text, *, busy=False):
        self.status_message = text
        self.status.set(self.tr(text))
        self.update_simulator_start()
        state = ("Verbindung wird hergestellt" if busy and not self.scanning else
                 "Verbunden" if text == READY_STATUS else "Getrennt")
        self.update_tray(state)
        if busy:
            if self.progress_job is None:
                self.animate_progress()
        else:
            self.stop_progress()

    def update_status_text(self, *_):
        self.status_canvas.itemconfigure(self.status_text, text=self.status.get(),
                                         width=max(1, self.status_canvas.winfo_width() - 10))

    def animate_progress(self):
        canvas = self.status_canvas
        width = canvas.winfo_width()
        band = width * 0.35
        phase = self.progress_step / 60
        left = (width - band) * (1 - abs(2 * phase - 1))
        canvas.coords(self.progress_band, left, 0, left + band, canvas.winfo_height())
        canvas.itemconfigure(self.progress_band, state="normal")
        self.progress_step = (self.progress_step + 1) % 60
        self.progress_job = self.root.after(30, self.animate_progress)

    def stop_progress(self):
        if self.progress_job is not None:
            self.root.after_cancel(self.progress_job)
            self.progress_job = None
        self.progress_step = 0
        self.status_canvas.itemconfigure(self.progress_band, state="hidden")

    def open_project(self):
        webbrowser.open(PROJECT_URL)

    def open_game_controllers(self, parent=None):
        try:
            os.startfile(str(Path(os.environ["SystemRoot"]) / "System32" / "joy.cpl"))
        except OSError as error:
            messagebox.showerror(self.tr("Windows-Gamecontroller konnten nicht geöffnet werden"),
                                 str(error), parent=parent or self.root)

    def open_vjoy_config(self, parent):
        candidates = (
            Path(root) / "vJoy" / folder / "vJoyConf.exe"
            for variable in ("ProgramFiles", "ProgramFiles(x86)")
            if (root := os.environ.get(variable))
            for folder in ("x64", "", "x86")
        )
        executable = next((path for path in candidates if path.is_file()), None)
        if executable is None:
            messagebox.showinfo(
                self.tr("vJoy-Konfiguration nicht gefunden"),
                self.tr("Installiere vJoy über den Download-Link in der Hilfe. Falls vJoy bereits installiert ist, öffne „Configure vJoy“ über das Windows-Startmenü."),
                parent=parent,
            )
            return
        try:
            os.startfile(str(executable), cwd=str(executable.parent))
        except OSError as error:
            messagebox.showerror(self.tr("vJoy-Konfiguration konnte nicht geöffnet werden"),
                                 str(error), parent=parent)

    def show_help(self):
        dialog = tk.Toplevel(self.root)
        dialog.title(self.tr("Hilfe"))
        dialog.transient(self.root)
        panel = ttk.Frame(dialog, padding=16)
        panel.pack(fill="both", expand=True)
        headings = ("So funktioniert es", "vJoy installieren", "Sender vorbereiten", "Am PC verbinden", "Simulator einrichten")
        for heading, step in zip(headings, LANGUAGE_CATALOG[self.language]["help"]):
            ttk.Label(panel, text=self.tr(heading), font=("Segoe UI", 10, "bold")).pack(anchor="w")
            ttk.Label(panel, text=step, wraplength=430, justify="left").pack(anchor="w", pady=(2, 8))

            if heading == "vJoy installieren":
                actions = ttk.Frame(panel)
                actions.pack(anchor="w", pady=(0, 8))
                ttk.Button(actions, text=self.tr("vJoy auf GitHub"),
                           command=lambda: webbrowser.open(VJOY_DOWNLOAD)).pack(side="left", padx=(0, 6))
                ttk.Button(actions, text=self.tr("vJoy konfigurieren"),
                           command=partial(self.open_vjoy_config, dialog)).pack(side="left")
            elif heading == "Sender vorbereiten":
                ttk.Button(panel, text=self.tr("ETHOS-Handbuch: Bluetooth-Trainer"),
                           command=lambda: webbrowser.open(TRAINER_MANUAL)).pack(anchor="w", pady=(0, 8))
        ttk.Label(panel, text=self.tr("Unabhängiges Community-Projekt. Quellcode und Fehlermeldungen findest du auf GitHub."),
                  wraplength=430, justify="left").pack(anchor="w", pady=(8, 4))
        project = ttk.Frame(panel)
        project.pack(fill="x")
        ttk.Button(project, text=self.tr("Projekt auf GitHub"), command=self.open_project).pack(side="left")
        ttk.Button(project, text=self.tr("Schließen"), command=dialog.destroy).pack(side="right")
        dialog.bind("<Escape>", lambda _: dialog.destroy())
        dialog.grab_set()
        dialog.focus_set()

    def diagnostic_lines(self):
        lines = []
        if self.quality is None:
            lines.append(self.tr("Warte auf mindestens zwei gültige Trainerframes."))
        else:
            count, last, mean, longest, received_at = self.quality
            lines.append(self.tr(message("Trainerframes seit BLE-Verbindung: {count}", count=count)))
            lines.append(self.tr(message("Letzter gültiger Frame vor {seconds:.2f} s",
                                         seconds=max(0, time.monotonic() - received_at))))
            if count > 1:
                lines.append(self.tr(message(
                    "Frameabstand · zuletzt {last:.1f} ms · Mittel {mean:.1f} ms · längste Pause {longest:.1f} ms",
                    last=last * 1000, mean=mean * 1000, longest=longest * 1000)))
        if self.neutralized:
            lines.append(self.tr("vJoy neutralisiert"))
        return lines

    def copy_diagnostics(self, dialog):
        with open(sys.executable if FROZEN else __file__, "rb") as source:
            build = hashlib.file_digest(source, "sha256").hexdigest()[:12]
        phase = ("Bereit" if self.status_message == READY_STATUS else
                 "Verbindung wird aufgebaut" if self.progress_job is not None else "Getrennt")
        error = self.tr("Kein Fehler erfasst")
        if self.last_failure:
            stage, code = self.last_failure
            error = f"{self.tr(stage)} ({code})" if code else self.tr(stage)
        lines = [f"FrSky Bluetooth Trainer · build {build}", self.tr(message("Status: {status}", status=self.tr(phase))),
                 *self.diagnostic_lines(), self.tr(message("Letzter Fehler: {error}", error=error))]
        dialog.clipboard_clear()
        dialog.clipboard_append("\n".join(lines))

    def show_diagnostics(self):
        dialog = tk.Toplevel(self.root)
        dialog.title(self.tr("Bluetooth-Details"))
        dialog.transient(self.root)
        panel = ttk.Frame(dialog, padding=14)
        panel.pack(fill="both", expand=True)
        ttk.Label(panel, text=self.tr("Ab Empfang in der App gemessen. Keine Ende-zu-Ende-Latenz."),
                  wraplength=450).pack(anchor="w", pady=(0, 8))
        summary = tk.StringVar()
        ttk.Label(panel, textvariable=summary, wraplength=450, justify="left").pack(anchor="w")
        actions = ttk.Frame(panel)
        actions.pack(fill="x", pady=(8, 0))
        copy_button = ttk.Button(actions, text=self.tr("Diagnose kopieren"))
        copy_button.pack(side="left")
        ttk.Button(actions, text=self.tr("Schließen"), command=dialog.destroy).pack(side="right")

        def copy():
            self.copy_diagnostics(dialog)
            copy_button.configure(text=self.tr("Diagnose kopiert"))

        copy_button.configure(command=copy)

        def refresh():
            nonlocal timer
            lines = self.diagnostic_lines()
            summary.set("\n".join(lines + [""] + list(map(self.tr, self.diagnostics))))
            timer = dialog.after(250, refresh)

        timer = None
        refresh()
        dialog.bind("<Destroy>", lambda event: dialog.after_cancel(timer) if event.widget is dialog else None)
        dialog.bind("<Escape>", lambda _: dialog.destroy())

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
                    self.request_simulator_launch(value)
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
                self.quality = None
                self.neutralized = False
                self.output_error = None
                self.render_channels(None)
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
            elif kind == "neutralized":
                self.neutralized = value
            elif kind == "failure":
                self.last_failure = value
            elif kind == "quality":
                self.quality = value
            elif kind == "vjoy_output":
                self.output_values = value
                self.output_error = None
                self.render_output()
            elif kind == "vjoy_error":
                self.last_failure = ("vJoy-Ausgabe fehlgeschlagen", None)
                self.output_error = value
                self.output_values = []
                self.render_output()
            elif kind == "diagnostic":
                self.diagnostics.append(value)
                del self.diagnostics[:-12]
            elif kind == "connection":
                self.connected_address = value
                self.update_connect_button()
            elif kind == "button_states":
                self.render_buttons(value)
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
                self.stop_progress()
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
    root.withdraw()
    root.resizable(False, False)
    app = Application(root)
    root.update_idletasks()
    if not app.start_in_tray.get():
        root.deiconify()
    root.mainloop()


if __name__ == "__main__":
    if "--smoke-test" in sys.argv:
        root = tk.Tk()
        root.withdraw()
        for filename in ("frsky-logo.png", "ethos-logo.png"):
            with Image.open(Path(__file__).with_name(filename)) as image:
                ImageTk.PhotoImage(image, master=root)
        from io import BytesIO

        for state in ("Getrennt", "Verbindung wird hergestellt", "Verbunden"):
            icon = Application.draw_tray_icon(state)
            ImageTk.PhotoImage(icon, master=root)
            for image_format in ("ICO", "BMP"):
                stream = BytesIO()
                icon.save(stream, format=image_format)
                stream.seek(0)
                with Image.open(stream) as decoded:
                    decoded.load()
        assert {"de", "en", "fr"} <= LANGUAGE_CATALOG.keys()
        root.destroy()
        sys.exit(0)
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
