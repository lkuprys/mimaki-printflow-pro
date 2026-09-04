@echo off
title Mimaki PrintFlow PRO - Build Standalone EXE
cd /d "%~dp0"

echo =========================================================
echo   Statomas Mimaki PrintFlow PRO (Nuitka Standalone EXE)
echo =========================================================
echo.

if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" -m pip install nuitka zstandard
    "%~dp0.venv\Scripts\python.exe" -m nuitka ^
        --assume-yes-for-downloads ^
        --standalone ^
        --onefile ^
        --low-memory ^
        --windows-console-mode=disable ^
        --enable-plugin=pyside6 ^
        --include-qt-plugins=sensible,qml ^
        --include-data-dir=printflow/ui/qml=printflow/ui/qml ^
        --include-data-dir=printflow/config=printflow/config ^
        --output-filename=PrintFlow.exe ^
        main.py
) else (
    pip install nuitka zstandard
    python -m nuitka ^
        --assume-yes-for-downloads ^
        --standalone ^
        --onefile ^
        --low-memory ^
        --windows-console-mode=disable ^
        --enable-plugin=pyside6 ^
        --include-qt-plugins=sensible,qml ^
        --include-data-dir=printflow/ui/qml=printflow/ui/qml ^
        --include-data-dir=printflow/config=printflow/config ^
        --output-filename=PrintFlow.exe ^
        main.py
)

echo.
if exist "PrintFlow.exe" (
    echo [SEKME] PrintFlow.exe sukurtas sekmingai!
) else (
    echo [KLAIDA] Kompiliavimas nepavyko.
)
pause
