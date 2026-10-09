@echo off
title PrintFlow Lite - EXE kompiliavimas
cd /d "%~dp0"

set "PY=E:\Projektai\TEST\.venv\Scripts\python.exe"
set "PYI=E:\Projektai\TEST\.venv\Scripts\pyinstaller.exe"
if not exist "%PY%" set "PY=python"
if not exist "%PYI%" set "PYI=pyinstaller"

echo [1/3] Testai...
"%PY%" tests\test_lite_e2e.py
if %ERRORLEVEL% NEQ 0 (
    echo TESTAI NEPAVYKO - kompiliavimas nutrauktas!
    pause
    exit /b 1
)

echo [2/3] PyInstaller --onefile --windowed...
"%PYI%" --noconfirm --clean --onefile --windowed --name PrintFlowLite --paths . --distpath dist --workpath build main_lite.py
if %ERRORLEVEL% NEQ 0 (
    echo KOMPILIAVIMAS NEPAVYKO!
    pause
    exit /b 1
)

echo [3/3] Kopijuojama: dist\PrintFlowLite.exe -^> PrintFlowLite.exe
copy /Y "dist\PrintFlowLite.exe" "PrintFlowLite.exe" >nul
echo.
echo PARUOSTA: %~dp0PrintFlowLite.exe
pause
