@echo off
chcp 65001 >nul
setlocal
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo OSHIBKA: zapustite ot imeni administratora.
    pause
    exit /b 1
)
echo Sluzhby AutoCell NE ostanavlivayu i NE zapuskayu.
echo Original podhvatitsya pri sleduyuschem starte sluzhby.
echo.
set ADDON=%~dp0
py "%ADDON%core\cli.py" remove
if %errorLevel% neq 0 (
    echo.
    echo OSHIBKA snyatiya. Sm. soobshchenie vyshe.
)
echo.
pause
endlocal
