@echo off
setlocal
cd /d "%~dp0frontend"
if not exist "node_modules" (
  echo Frontend dependencies not found. Installing...
  call "%ProgramFiles%\nodejs\npm.cmd" install
  if errorlevel 1 exit /b 1
)
call "%ProgramFiles%\nodejs\npm.cmd" run dev
