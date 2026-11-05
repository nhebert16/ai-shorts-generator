@echo off
REM Launched by Windows Task Scheduler ("Shorts" task).
REM Makes and uploads 1 Short per run; output appended to logs\pipeline.log
cd /d "%~dp0"
if not exist logs mkdir logs
set PYTHONIOENCODING=utf-8
venv\Scripts\python.exe main.py --max-posts 1 >> logs\pipeline.log 2>&1
