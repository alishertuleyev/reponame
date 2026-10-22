@echo off
REM Vernut shtatnye main.py/app.py i zapustit sluzhby, esli oni lezhat.
REM Uzhe zapushchennuyu sluzhbu ne ostanavlivaet.
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo OSHIBKA: zapustite ot imeni administratora.
    pause
    exit /b 1
)
set ADDON=%~dp0
py "%ADDON%core\cli.py" remove
if %errorLevel% neq 0 (
    echo OSHIBKA: puti ne vosstanovleny. Sluzhby ne zapuskayu.
    pause
    exit /b 1
)
set NSSM=C:\AutoCell\bin\nssm.exe
echo Start AutoCellBackend...
"%NSSM%" start AutoCellBackend
echo Start AutoCellFrontend...
"%NSSM%" start AutoCellFrontend
echo.
sc query AutoCellBackend
echo.
sc query AutoCellFrontend
echo.
echo Esli sluzhba STOP_PENDING:
echo   sc queryex AutoCellBackend
echo   taskkill /F /PID  (nomer iz PID)
echo   "%NSSM%" start AutoCellBackend
pause
