@echo off
setlocal
set "app=%~dp0FrSkyApp.pyw"
set "check=import sys, sysconfig, tkinter; sys.exit(not (sys.version_info[:2] == (3, 14) and sysconfig.get_platform() == 'win-amd64'))"

py -3.14 -c "%check%" >nul 2>&1
if not errorlevel 1 (
    for /f "delims=" %%P in ('py -3.14 -c "import sys; print(sys.executable)"') do if exist "%%~dpPpythonw.exe" (
        set "pythonw=%%~dpPpythonw.exe"
        goto launch
    )
)

for /f "delims=" %%P in ('where.exe python.exe 2^>nul') do if exist "%%~dpPpythonw.exe" (
    "%%P" -c "%check%" >nul 2>&1
    if not errorlevel 1 (
        set "pythonw=%%~dpPpythonw.exe"
        goto launch
    )
)

echo Python 3.14 ^(Windows x64^) mit Tkinter wurde nicht gefunden.
echo Installiere es mit dem Python-Launcher oder fuege Python zum PATH hinzu.
pause
exit /b 1

:launch
start "" "%pythonw%" "%app%"
