@echo off
title Mimaki PrintFlow PRO - Build Standalone EXE
cd /d "%~dp0"

echo =========================================================
echo   Statomas Mimaki PrintFlow PRO (Standalone EXE)
echo =========================================================
echo.

if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" -m pip install pyinstaller
    "%~dp0.venv\Scripts\pyinstaller.exe" --noconfirm --clean --onefile --windowed --name "PrintFlow" --hidden-import="pywinauto" --hidden-import="comtypes" --hidden-import="win32service" --hidden-import="win32gui" --hidden-import="win32con" --hidden-import="win32process" --add-data "printflow/ui/qml;printflow/ui/qml" --add-data "printflow/config;printflow/config" main.py
) else (
    pip install pyinstaller
    pyinstaller --noconfirm --clean --onefile --windowed --name "PrintFlow" --hidden-import="pywinauto" --hidden-import="comtypes" --hidden-import="win32service" --hidden-import="win32gui" --hidden-import="win32con" --hidden-import="win32process" --add-data "printflow/ui/qml;printflow/ui/qml" --add-data "printflow/config;printflow/config" main.py
)

if exist "dist\PrintFlow.exe" (
    copy /y "dist\PrintFlow.exe" "PrintFlow.exe"
    echo.
    echo [SEKME] PrintFlow.exe sukurtas sekmingai!
) else (
    echo.
    echo [KLAIDA] Kompiliavimas nepavyko.
)
pause
