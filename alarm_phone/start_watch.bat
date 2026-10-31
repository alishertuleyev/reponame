@echo off
chcp 65001 >nul
cd /d "%~dp0"
py -3 watch.py
if %errorLevel% neq 0 (
    echo.
    echo OSHIBKA zapuska. Nuzhen Python 3 na etom PK.
)
echo.
pause
