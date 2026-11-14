"""Build the portable Windows x64 release from the repository root."""
import argparse
import hashlib
import platform
import runpy
import subprocess
import sys
import zipfile
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--version", default="0.1.0")
args = parser.parse_args()
if not all(part.isdigit() for part in args.version.split(".")) or len(args.version.split(".")) != 3:
    parser.error("Use a version such as 0.1.0")
if sys.platform != "win32" or platform.architecture()[0] != "64bit":
    parser.error("Build on Windows with 64-bit Python")
root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))
build = root / "build"
build.mkdir(exist_ok=True)
app = runpy.run_path(str(root / "FrSkyApp.pyw"))
app["Application"].draw_tray_icon().save(build / "app.ico")
command = [
    sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
    "--onefile", "--windowed", "--name", "FrSky Bluetooth Trainer",
    "--icon", str(build / "app.ico"), "--specpath", str(build),
    "--distpath", str(root / "dist"), "--workpath", str(build / "pyinstaller"),
    "--hidden-import", "pystray._win32", "--collect-submodules", "winrt",
    "--collect-all", "bleak", "--exclude-module", "numpy",
]
for resource in ("languages.json", "frsky-logo.png", "ethos-logo.png"):
    command.extend(("--add-data", f"{root / resource}:."))
command.append(str(root / "FrSkyApp.pyw"))
subprocess.run(command, cwd=root, check=True)
exe = root / "dist" / "FrSky Bluetooth Trainer.exe"
subprocess.run([str(exe), "--smoke-test"], check=True, timeout=60)
archive = root / "dist" / f"FrSky-Bluetooth-Trainer-v{args.version}-Windows-x64.zip"
with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as output:
    output.write(exe, exe.name)
    output.write(root / "README.md", "README.md")
digest = hashlib.sha256(archive.read_bytes()).hexdigest()
archive.with_suffix(".zip.sha256").write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
print(archive)
