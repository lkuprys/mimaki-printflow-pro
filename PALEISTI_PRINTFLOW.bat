@echo off
title Mimaki PrintFlow PRO (Native Desktop)
cd /d "%~dp0"

if exist "E:\Projektai\Podbase\CC\.venv\Scripts\python.exe" (
    "E:\Projektai\Podbase\CC\.venv\Scripts\python.exe" main.py
) else (
    python main.py
)

if errorlevel 1 (
    echo.
    echo Ivyko klaida paleidziant sistema.
    pause
)
