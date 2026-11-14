import ctypes as c
import os
from pathlib import Path


BUTTON_HIGH = 1700
BUTTON_LOW = 1300


BUTTON_MODES = (True, "middle", False)


def button_pressed(value, mode):
    if mode == "middle":
        return BUTTON_LOW < value < BUTTON_HIGH
    return value >= BUTTON_HIGH if mode else value <= BUTTON_LOW


class VJoyUnavailable(RuntimeError):
    pass


def load_vjoy_api(dll_path=None):
    candidates = [Path(dll_path)] if dll_path else [
        Path(root) / "vJoy" / folder / "vJoyInterface.dll"
        for root in (os.environ["ProgramFiles"], os.environ.get("ProgramFiles(x86)", os.environ["ProgramFiles"]))
        for folder in ("x64", "")
    ]
    path = next((path for path in candidates if path.is_file()), None)
    if path is None:
        raise VJoyUnavailable("vJoyInterface.dll fehlt. Installiere vJoy oder gib --vjoy-dll an.")
    try:
        with os.add_dll_directory(str(path.resolve().parent)):
            api = c.CDLL(str(path.resolve()))
        enabled = api.vJoyEnabled
    except (OSError, AttributeError) as error:
        raise VJoyUnavailable("Die vJoy-Schnittstelle konnte nicht geladen werden.") from error
    enabled.argtypes = ()
    enabled.restype = c.c_int
    if not enabled():
        raise VJoyUnavailable("Der vJoy-Treiber ist nicht aktiv.")
    return api


class VJoyOutput:
    axis_names = ("X", "Y", "Z", "Rx", "Ry", "Rz", "Slider", "Dial")

    def __init__(self, channels, dll_path=None, *, buttons=()):
        self.channels = channels
        self.buttons = [(index, channel, high) for index, (channel, high) in enumerate(buttons, 1) if channel]
        self.axes = range(0x30, 0x30 + len(channels))
        self.device = 1
        self.api = load_vjoy_api(dll_path)
        for name, args, result in (
            ("AcquireVJD", [c.c_uint], c.c_int),
            ("RelinquishVJD", [c.c_uint], None),
            ("GetVJDAxisMin", [c.c_uint, c.c_uint, c.POINTER(c.c_long)], c.c_int),
            ("GetVJDAxisMax", [c.c_uint, c.c_uint, c.POINTER(c.c_long)], c.c_int),
            ("GetVJDButtonNumber", [c.c_uint], c.c_int),
            ("SetBtn", [c.c_int, c.c_uint, c.c_ubyte], c.c_int),
            ("SetAxis", [c.c_long, c.c_uint, c.c_uint], c.c_int),
        ):
            function = getattr(self.api, name)
            function.argtypes = args
            function.restype = result
        self.ranges = []
        for axis in self.axes:
            low, high = c.c_long(), c.c_long()
            if not (self.api.GetVJDAxisMin(self.device, axis, c.byref(low))
                    and self.api.GetVJDAxisMax(self.device, axis, c.byref(high))):
                name = self.axis_names[axis - 0x30]
                raise RuntimeError(f"Aktiviere die Achse {name} für vJoy-Gerät 1.")
            self.ranges.append((low.value, high.value))
        if self.buttons and self.buttons[-1][0] > self.api.GetVJDButtonNumber(self.device):
            raise RuntimeError("Aktiviere in Configure vJoy die belegten Tasten für Gerät 1.")
        if not self.api.AcquireVJD(self.device):
            raise RuntimeError("vJoy-Gerät 1 konnte nicht geöffnet werden. Prüfe die Konfiguration und andere Programme.")

    def write(self, values):
        positions = self.write_axes(values)
        states = []
        for index, channel, high in self.buttons:
            pressed = button_pressed(values[channel - 1], high)
            self.set_button(index, pressed)
            states.append((index, channel, pressed))
        return positions, states

    def set_button(self, index, pressed):
        if not self.api.SetBtn(pressed, self.device, index):
            raise RuntimeError("vJoy hat den Tastenzustand abgelehnt.")

    def write_axes(self, values):
        positions = []
        for axis, (low, high), channel in zip(self.axes, self.ranges, self.channels):
            value = max(988, min(2012, values[channel - 1]))
            position = low + round((value - 988) * (high - low) / 1024)
            if not self.api.SetAxis(position, self.device, axis):
                raise RuntimeError("vJoy hat die Achsenposition abgelehnt.")
            positions.append((channel, position))
        return positions

    def center(self):
        first_error = None
        for index, _, _ in self.buttons:
            try:
                self.set_button(index, False)
            except (OSError, RuntimeError) as error:
                if first_error is None:
                    first_error = error
        try:
            self.write_axes([1500] * max(self.channels))
        except (OSError, RuntimeError):
            if first_error is None:
                raise
        if first_error is not None:
            raise first_error

    def close(self):
        try:
            self.center()
        finally:
            self.api.RelinquishVJD(self.device)
