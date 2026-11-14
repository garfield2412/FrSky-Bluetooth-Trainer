"""Download and launch the pinned vJoy installer."""
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import urllib.request

INSTALLER_URL = "https://github.com/BrunnerInnovation/vJoy/releases/download/v2.2.2.0/vJoySetup_v2.2.2.0_Win10_Win11.exe"
INSTALLER_SHA256 = "ef569a3105cd301b89580f18f60c66b339e95296acf2c0dfcaf4b4bbf8ab68fe"
INSTALLER_SIZE = 5302312


def download_installer(path, cancel, progress):
    digest = hashlib.sha256()
    downloaded = 0
    with urllib.request.urlopen(INSTALLER_URL, timeout=20) as response, open(path, "wb") as output:
        while chunk := response.read(65536):
            if cancel.is_set():
                return False
            downloaded += len(chunk)
            if downloaded > INSTALLER_SIZE:
                raise ValueError("Installer size mismatch")
            digest.update(chunk)
            output.write(chunk)
            progress(downloaded / INSTALLER_SIZE * 100)
    if cancel.is_set():
        return False
    if downloaded != INSTALLER_SIZE or digest.hexdigest() != INSTALLER_SHA256:
        raise ValueError("Installer checksum mismatch")
    return True


def run_installer(path):
    # The verified file is generated in a private temporary directory.
    escaped = str(Path(path).resolve()).replace("'", "''")
    command = (
        f"$process = Start-Process -FilePath '{escaped}' -Verb RunAs -PassThru -Wait; "
        "if ($null -eq $process) { exit 1 }; exit $process.ExitCode"
    )
    result = subprocess.run(
        [str(Path(os.environ["SystemRoot"]) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"),
         "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if result.returncode not in (0, 3010):
        raise RuntimeError(result.stderr.strip() or f"Installer exit code {result.returncode}")
    return result.returncode


def install_vjoy(cancel, events):
    try:
        with tempfile.TemporaryDirectory(prefix="frsky-vjoy-") as folder:
            path = Path(folder) / "vJoySetup.exe"
            if not download_installer(path, cancel, lambda value: events.put(("setup_progress", value))):
                return
            if cancel.is_set():
                return
            events.put(("setup_installing", None))
            code = run_installer(path)
            events.put(("setup_complete", code))
    except Exception as error:
        events.put(("setup_error", str(error)))
