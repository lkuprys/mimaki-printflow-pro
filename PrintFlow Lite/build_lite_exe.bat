@echo off
title PrintFlow Lite - vietinis kompiliavimas (bandymams, neisleidzia)
cd /d "%~dp0"

set "PY=E:\Projektai\TEST\.venv\Scripts\python.exe"
set "PYI=E:\Projektai\TEST\.venv\Scripts\pyinstaller.exe"
if not exist "%PY%" set "PY=python"
if not exist "%PYI%" set "PYI=pyinstaller"
set PRINTFLOW_NO_AUTO_UPDATE=1

echo [1/3] Testai...
"%PY%" tests\test_lite_e2e.py
if %ERRORLEVEL% NEQ 0 (
    echo TESTAI NEPAVYKO - kompiliavimas nutrauktas!
    pause
    exit /b 1
)

echo [2/3] PyInstaller --onedir --windowed (kaip GitHub isleidime)...
"%PYI%" --noconfirm --clean --onedir --windowed --name PrintFlowLite --icon assets\podbase.ico --paths . --add-data "fonts;fonts" --add-data "assets;assets" --distpath dist --workpath build main_lite.py
if %ERRORLEVEL% NEQ 0 (
    echo KOMPILIAVIMAS NEPAVYKO!
    pause
    exit /b 1
)

echo [3/3] Paruosta: %~dp0dist\PrintFlowLite\PrintFlowLite.exe
echo Pastaba: oficialus isleidimas daromas tik per GitHub Actions "Isleisti PrintFlow Lite atnaujinima".
pause
