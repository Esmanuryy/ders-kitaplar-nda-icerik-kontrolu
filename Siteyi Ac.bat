@echo off
rem Ders Kitabi Denetleyici: cift tiklayinca siteyi baslatir ve tarayicida acar.
if "%~1"=="tarayici" goto tarayici

chcp 65001 >nul
title Ders Kitabi Denetleyici
cd /d "%~dp0"
set PYTHONUTF8=1
set ADRES=http://127.0.0.1:5000

rem Site zaten aciksa ikinci kez baslatma, sadece tarayicida ac.
curl.exe -s -m 2 -o nul %ADRES%
if not errorlevel 1 (
    start "" %ADRES%
    exit /b 0
)

py -3.12 --version >nul 2>&1
if errorlevel 1 (
    echo Python 3.12 bulunamadi. Lutfen Python 3.12 kurun.
    pause
    exit /b 1
)

echo Site baslatiliyor, tarayici birazdan kendiliginden acilacak.
echo Siteyi kapatmak icin bu pencereyi kapatin.
echo.
start "" /b cmd /c ""%~f0" tarayici"
py -3.12 app.py
echo.
echo Site kapandi. Yukarida hata mesaji varsa kurulum icin README dosyasina bakin.
pause
exit /b 0

:tarayici
rem Site hazir olunca tarayiciyi acar (en fazla yaklasik 2 dakika bekler).
for /l %%i in (1,1,120) do (
    curl.exe -s -m 2 -o nul http://127.0.0.1:5000
    if not errorlevel 1 (
        start "" http://127.0.0.1:5000
        exit /b 0
    )
    ping -n 2 127.0.0.1 >nul
)
exit /b 1
