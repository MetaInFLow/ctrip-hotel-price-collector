@echo off
setlocal EnableExtensions

set "SCRIPT_DIR=%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%bootstrap_ctrip_hotel_skill.ps1" %*
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
  echo.
  echo Installation failed. Review the messages above, then press any key to close.
  pause >nul
)

exit /b %EXIT_CODE%
