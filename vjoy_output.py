import ctypes as c
import os
from pathlib import Path


class VJoyUnavailable(RuntimeError):
    pass


class VJoyOutput:
    axis_names = ("X", "Y", "Z", "Rx", "Ry", "Rz", "Slider", "Dial")

    def __init__(self, channels, dll_path=None):
        self.channels = channels
        self.axes = range(0x30, 0x30 + len(channels))
        self.device = 1
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
                self.api = c.CDLL(str(path.resolve()))
            enabled = self.api.vJoyEnabled
        except (OSError, AttributeError) as error:
            raise VJoyUnavailable("Die vJoy-Schnittstelle konnte nicht geladen werden.") from error
        enabled.argtypes = ()
        enabled.restype = c.c_int
        if not enabled():
            raise VJoyUnavailable("Der vJoy-Treiber ist nicht aktiv.")
        for name, args, result in (
            ("AcquireVJD", [c.c_uint], c.c_int),
            ("RelinquishVJD", [c.c_uint], None),
            ("GetVJDAxisMin", [c.c_uint, c.c_uint, c.POINTER(c.c_long)], c.c_int),
            ("GetVJDAxisMax", [c.c_uint, c.c_uint, c.POINTER(c.c_long)], c.c_int),
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
        if not self.api.AcquireVJD(self.device):
            raise RuntimeError("vJoy-Gerät 1 konnte nicht geöffnet werden. Prüfe die Konfiguration und andere Programme.")

    def write(self, values):
        for axis, (low, high), channel in zip(self.axes, self.ranges, self.channels):
            value = max(988, min(2012, values[channel - 1]))
            position = low + round((value - 988) * (high - low) / 1024)
            if not self.api.SetAxis(position, self.device, axis):
                raise RuntimeError("vJoy hat die Achsenposition abgelehnt.")

    def center(self):
        self.write([1500] * 8)

    def close(self):
        try:
            self.center()
        finally:
            self.api.RelinquishVJD(self.device)
