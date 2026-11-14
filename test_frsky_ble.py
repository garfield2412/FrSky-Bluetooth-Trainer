import argparse
import asyncio
import msvcrt
import signal
import sys
from functools import reduce
from operator import xor
from pathlib import Path
from xml.etree import ElementTree

sys.path.insert(0, str(Path(__file__).with_name("ble-libs")))
from bleak import BleakClient, BleakScanner
from bleak.exc import BleakError

SERVICE = "0000fff0-0000-1000-8000-00805f9b34fb"
CHARACTERISTIC = "0000fff6-0000-1000-8000-00805f9b34fb"
FRAME_SIZE = 14


class TrainerDecoder:
    def __init__(self):
        self.frame = None
        self.escaped = False

    def feed(self, data):
        for byte in data:
            if byte == 0x7E:
                frame = self.frame
                valid_length = frame is not None and len(frame) == FRAME_SIZE
                complete = valid_length and not self.escaped
                self.frame = bytearray()
                self.escaped = False
                if complete and frame[0] == 0x80 and reduce(xor, frame, 0) == 0:
                    yield decode_channels(frame)
            elif self.frame is not None:
                if self.escaped:
                    self.frame.append(byte ^ 0x20)
                    self.escaped = False
                elif byte == 0x7D:
                    self.escaped = True
                else:
                    self.frame.append(byte)
                if len(self.frame) > FRAME_SIZE:
                    self.frame = None


def decode_channels(frame):
    channels = []
    for offset in range(1, 13, 3):
        first, middle, last = frame[offset:offset + 3]
        channels.append(first | ((middle & 0xF0) << 4))
        channels.append(((middle & 0x0F) << 4) | (last >> 4) | ((last & 0x0F) << 8))
    return channels


async def show_channels(client, disconnected, joystick):
    decoder = TrainerDecoder()
    loop = asyncio.get_running_loop()
    latest = None
    last_packet = loop.time()

    def on_packet(_, data):
        nonlocal latest, last_packet
        for channels in decoder.feed(data):
            latest = channels
            last_packet = loop.time()

    print("BLE verbunden. Warte auf Trainerdaten ...")
    await client.start_notify(CHARACTERISTIC, on_packet)
    previous = None
    try:
        while not disconnected.is_set():
            if loop.time() - last_packet > 5:
                raise TimeoutError("Seit 5 Sekunden keine gültigen Trainerdaten.")
            if latest is not None and latest != previous:
                if joystick is not None:
                    joystick.write(latest)
                line = "  ".join(f"CH{i}: {value:4d}" for i, value in enumerate(latest, 1))
                print(f"\r{line}", end="", flush=True)
                previous = latest
            try:
                await asyncio.wait_for(disconnected.wait(), timeout=0.1)
            except TimeoutError:
                pass
    finally:
        if previous is not None:
            print()
        if client.is_connected:
            try:
                await client.stop_notify(CHARACTERISTIC)
            except (BleakError, OSError):
                pass


async def run_trainer(joystick, address):
    print("FrSky | Live-Anzeige | Strg+X zum Beenden")
    failures = 0
    while True:
        try:
            print(f"Suche Sender {address} per BLE ...")
            device = await BleakScanner.find_device_by_address(address, timeout=12)
            if device is None:
                raise RuntimeError("Sender im BLE-Scan nicht gefunden.")
            disconnected = asyncio.Event()
            async with BleakClient(
                device,
                services=[SERVICE],
                winrt={"use_cached_services": bool(failures % 2)},
                disconnected_callback=lambda _: disconnected.set(),
                timeout=12,
            ) as client:
                await show_channels(client, disconnected, joystick)
            failures = 0
            print("Bluetooth getrennt.")
        except (BleakError, OSError, TimeoutError, RuntimeError) as error:
            failures += 1
            print(f"Trainerlink: {error or type(error).__name__}")
        if joystick is not None:
            joystick.center()
        delay = min(2 * max(1, failures), 6)
        print(f"Neuer Verbindungsversuch in {delay} s.")
        await asyncio.sleep(delay)


async def wait_for_exit_key():
    while True:
        while msvcrt.kbhit():
            key = msvcrt.getwch()
            if key == "\x18":
                return
            if key in ("\x00", "\xe0"):
                msvcrt.getwch()
        await asyncio.sleep(0.05)


async def main(joystick, address):
    tasks = [asyncio.create_task(run_trainer(joystick, address))]
    if sys.stdin.isatty():
        tasks.append(asyncio.create_task(wait_for_exit_key()))
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FrSky BLE live monitor and optional vJoy output.")
    parser.add_argument("--address", help="BLE address (defaults to the last transmitter saved in config.xml).")
    parser.add_argument("--vjoy", action="store_true", help="Enable vJoy device 1.")
    parser.add_argument("--channels", nargs="+", type=int, choices=range(1, 9),
                        default=list(range(1, 9)), metavar="CH",
                        help="Four or eight channels in vJoy axis order (default: 1 through 8).")
    parser.add_argument("--vjoy-dll", help="Path to the 64-bit vJoyInterface.dll.")
    args = parser.parse_args()
    if len(args.channels) not in (4, 8):
        parser.error("--channels erwartet vier oder acht Kanalnummern.")

    address = args.address
    if not address:
        try:
            address = ElementTree.parse(Path(__file__).with_name("config.xml")).getroot().get("last-transmitter")
        except (OSError, ElementTree.ParseError):
            pass
    if not address:
        parser.error("Select a transmitter in the app first or specify --address.")

    signal.signal(signal.SIGINT, signal.SIG_IGN)
    joystick = None
    try:
        if args.vjoy:
            from vjoy_output import VJoyOutput
            joystick = VJoyOutput(args.channels, args.vjoy_dll)
            joystick.center()
            mapping = ", ".join(f"{axis}=CH{channel}" for axis, channel in zip(joystick.axis_names, args.channels))
            print(f"vJoy 1 | {mapping}")
        asyncio.run(main(joystick, address))
    except (OSError, RuntimeError) as error:
        sys.exit(str(error))
    finally:
        if joystick is not None:
            joystick.close()
    print("\nLive-Anzeige beendet.")
