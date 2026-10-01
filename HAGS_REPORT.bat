@echo off
setlocal
cd /d "%~dp0"
set "SYS=%SystemRoot%\System32"
if not exist "Vortex_HAGS_Selector.exe" goto MISSING

echo   asking Windows for the HAGS verdict on this machine ...
echo   a permission prompt may appear.
echo.

"%SYS%\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -Command "Start-Process -FilePath '%~dp0Vortex_HAGS_Selector.exe' -ArgumentList '--report' -Verb RunAs -Wait" 2>nul

if not exist "%~dp0hags_report.txt" goto NOWRITE
type "%~dp0hags_report.txt"
echo.
pause
exit /b 0

:MISSING
echo   Vortex_HAGS_Selector.exe was not found next to this .bat file.
echo.
pause
exit /b 1

:NOWRITE
echo   hags_report.txt was not written.
echo   If a permission prompt appeared, approve it and run this again.
echo.
pause
exit /b 1
