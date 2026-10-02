@echo off
setlocal
cd /d "%~dp0"
if not exist ".opencode\skills\chess-vision-analysis\SKILL.md" (
  echo Chess Vision analysis skill not found.
  exit /b 1
)
opencode .
endlocal
