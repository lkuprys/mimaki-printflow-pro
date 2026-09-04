@echo off
title Mimaki PrintFlow PRO
cd /d "%~dp0"

echo ===================================================
echo    MIMAKI PRINTFLOW PRO - Gamybinis Valdiklis
echo ===================================================
echo.
echo Paleidziama sistema... Prasome palaukti.
echo.

if exist "E:\Projektai\Podbase\CC\.venv\Scripts\python.exe" (
    "E:\Projektai\Podbase\CC\.venv\Scripts\python.exe" run_printflow.py
) else (
    python run_printflow.py
)

if errorlevel 1 (
    echo.
    echo Ivyko klaida paleidziant sistema.
    pause
)
