@echo off
REM Launcher for the Grim Dawn Build Assistant (Windows).
REM Double-click this file to run, or execute it from a command prompt.
cd /d "%~dp0"

if not exist ".venv" (
    echo First run: setting up the environment ^(this can take a minute^)...
    python -m venv .venv
    .venv\Scripts\pip install --quiet --upgrade pip
    .venv\Scripts\pip install --quiet -e .
)

REM Ensure GUI deps exist even if the venv predates them.
.venv\Scripts\python -c "import PySide6" 2>NUL || .venv\Scripts\pip install --quiet PySide6 platformdirs

set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
.venv\Scripts\python -m gd_assistant %*
