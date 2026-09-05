@echo off
title Podbase Mimaki PrintFlow Lite
cd /d "%~dp0"

if exist "PrintFlowLite.exe" (
    start "" "PrintFlowLite.exe"
    exit
)

if exist "..\.venv\Scripts\python.exe" (
    start "" "..\.venv\Scripts\python.exe" "main_lite.py"
    exit
)

python main_lite.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Klaida paleidziant PrintFlow Lite!
    pause
)
