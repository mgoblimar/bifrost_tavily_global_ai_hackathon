@echo off
rem Runs the example AI app in a visible console window for the demo recording.
rem The marker files tell record_terminal.py when the run starts and ends.
rem Pauses use ping because "timeout" can resolve to a non-Windows tool on PATH.
title CarbonDateDemo
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
mode con cols=118 lines=30
cd /d "%~dp0.."
echo.
echo ^> python -m examples.guarded_chat "Who is the CEO of Nvidia and what is their newest data centre GPU?"
echo.
ping -n 5 127.0.0.1 >nul
echo started> demo\raw\term_start.txt
.venv\Scripts\python -m examples.guarded_chat "Who is the CEO of Nvidia and what is their newest data centre GPU?"
echo ended> demo\raw\term_end.txt
echo.
ping -n 16 127.0.0.1 >nul
exit
