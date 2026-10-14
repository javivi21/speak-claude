@echo off
title Dictado por voz
cd /d "%~dp0"
".venv\Scripts\python.exe" dictado.py %*
pause
