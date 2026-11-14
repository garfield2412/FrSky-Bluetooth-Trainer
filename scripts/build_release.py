"""Build the portable Windows x64 release from the repository root."""
import argparse
import hashlib
import platform
import runpy
import subprocess
import sys
import zipfile
from PIL import _plugins
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--version", default="0.1.0")
parser.add_argument("--output-dir", type=Path, help="Override the release output directory.")
args = parser.parse_args()
if not all(part.isdigit() for part in args.version.split(".")) or len(args.version.split(".")) != 3:
    parser.error("Use a version such as 0.1.0")
if sys.platform != "win32" or platform.architecture()[0] != "64bit":
    parser.error("Build on Windows with 64-bit Python")
root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))
output_dir = args.output_dir.resolve() if args.output_dir else root / "dist"
build = root / "build"
build.mkdir(exist_ok=True)
app = runpy.run_path(str(root / "FrSkyApp.pyw"))
app["Application"].draw_tray_icon().save(build / "app.ico")
command = [
    sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
    "--onefile", "--windowed", "--name", "FrSky Bluetooth Trainer",
    "--icon", str(build / "app.ico"), "--specpath", str(build),
    "--distpath", str(output_dir), "--workpath", str(build / "pyinstaller"),
    "--hidden-import", "pystray._win32", "--collect-submodules", "winrt",
    "--collect-all", "bleak", "--exclude-module", "numpy",
]
# The application uses PNG logos and Windows ICO/BMP icons.
required_plugins = {"PngImagePlugin", "IcoImagePlugin", "BmpImagePlugin"}
excluded_modules = [
    *(f"PIL.{plugin}" for plugin in _plugins if plugin not in required_plugins),
    "PIL._avif", "PIL._webp", "PIL._imagingcms", "PIL._imagingft",
]
for module in excluded_modules:
    command.extend(("--exclude-module", module))
for resource in ("languages.json", "frsky-logo.png", "ethos-logo.png"):
    command.extend(("--add-data", f"{root / resource}:."))
# Recent Windows Python builds ship Tcl/Tk scripts in ZIP archives.
# Extract their resources when the standard PyInstaller hook cannot find them.
for prefix, folder, destination in (
    ("libtcl", "tcl_library", "_tcl_data"),
    ("libtk", "tk_library", "_tk_data"),
):
    archives = list((Path(sys.base_prefix) / "tcl").glob(f"{prefix}*.zip"))
    if archives:
        resource_dir = build / destination
        with zipfile.ZipFile(archives[0]) as archive:
            for member in archive.infolist():
                relative = Path(member.filename).relative_to(folder)
                if ".." in relative.parts or member.is_dir():
                    continue
                target = resource_dir / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(member))
        command.extend(("--add-data", f"{resource_dir}:{destination}"))
command.append(str(root / "FrSkyApp.pyw"))
subprocess.run(command, cwd=root, check=True)
exe = output_dir / "FrSky Bluetooth Trainer.exe"
subprocess.run([str(exe), "--smoke-test"], check=True, timeout=60)
archive = output_dir / f"FrSky-Bluetooth-Trainer-v{args.version}-Windows-x64.zip"
with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as output:
    output.write(exe, exe.name)
    output.write(root / "README.md", "README.md")
digest = hashlib.sha256(archive.read_bytes()).hexdigest()
archive.with_suffix(".zip.sha256").write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
print(archive)
