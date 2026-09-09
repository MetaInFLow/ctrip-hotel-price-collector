@echo off
setlocal EnableExtensions

set "SKILL_DIR=%~dp0"
set "RUNNER=%SKILL_DIR%bin\ctrip-agent.exe"
set "BROWSER=%SKILL_DIR%browser\chrome.exe"

if not exist "%RUNNER%" (
  echo Installation failed: this package does not match Windows or is incomplete.
  exit /b 1
)
if not exist "%BROWSER%" (
  echo Installation failed: the bundled browser component is missing. Extract the complete package and retry.
  exit /b 1
)

"%RUNNER%" setup
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
  echo.
  echo Installation failed. Review the message above and run install.cmd again.
  pause
  exit /b %EXIT_CODE%
)

echo.
echo Deployment complete. Enable the FDE Ctrip price comparison skill in Codex.
pause
exit /b 0
