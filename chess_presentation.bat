@echo off
rem opencode topic session: optimize/queries (continues last session in this directory)
rem usage: oc-optimize.bat        - continue topic session
rem        oc-optimize.bat new    - start fresh topic session
title opencode - optimize
cd /d "%~dp0optimize"
if /i "%~1"=="new" (opencode) else (opencode -c %*)
