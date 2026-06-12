@echo off
REM Double-click this to install the ClassifyHub agent with a setup window.
REM It locates a working Python, then launches the graphical installer.

setlocal
cd /d "%~dp0"

REM Prefer the py launcher, then python/python3. Skip the Microsoft Store stub.
set "PYEXE="
for %%P in (py.exe python.exe python3.exe) do (
    if not defined PYEXE (
        for /f "delims=" %%I in ('where %%P 2^>nul') do (
            echo %%I | find /i "WindowsApps" >nul || (
                if not defined PYEXE set "PYEXE=%%I"
            )
        )
    )
)

if not defined PYEXE (
    echo.
    echo Python 3 was not found on this PC.
    echo Please install it from https://www.python.org/downloads/
    echo During setup, TICK "Add python.exe to PATH", then run this installer again.
    echo.
    pause
    exit /b 1
)

"%PYEXE%" "%~dp0install_gui.py"
if errorlevel 1 (
    echo.
    echo The installer reported a problem. See the message above.
    pause
)
endlocal
