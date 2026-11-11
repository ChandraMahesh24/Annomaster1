@echo off
REM Double-click to launch AnnoMaster-next (backend + frontend).
REM Or from a terminal:  run.bat backend   /   run.bat frontend
cd /d "%~dp0"
python run.py %*
pause
