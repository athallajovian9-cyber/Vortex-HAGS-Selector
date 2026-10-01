@echo off
setlocal
cd /d "%~dp0"
if not exist "Vortex_HAGS_Selector.exe" goto MISSING
echo   starting Vortex HAGS Selector ...
start "" "%~dp0Vortex_HAGS_Selector.exe"
exit /b 0

:MISSING
echo.
echo   Vortex_HAGS_Selector.exe was not found next to this .bat file.
echo   Unzip the whole release folder, then run this again.
echo.
pause
exit /b 1
