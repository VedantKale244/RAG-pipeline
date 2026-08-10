@echo off
setlocal
title Neuro-Adaptive GraphRAG Backend
echo Starting Neuro-Adaptive GraphRAG FastAPI Backend...
set "ROOT=%~dp0"
set "PYTHON_EXE=%ROOT%.venv\Scripts\python.exe"

rem A moved or upgraded system Python leaves virtual environments with a dead
rem launcher. Repair it automatically so the API cannot silently stay offline.
if exist "%PYTHON_EXE%" (
  "%PYTHON_EXE%" -c "import fastapi, uvicorn, slowapi, cohere, numpy" >nul 2>&1
  if not errorlevel 1 goto :start
)

echo Repairing the backend Python environment. This happens only when it is missing or invalid...
where py >nul 2>nul
if errorlevel 1 (
  echo Python 3.11 or newer is required. Install Python, then run this file again.
  pause
  exit /b 1
)

rem IMPORTANT: the pinned deps (langchain-pinecone==0.2.13, langchain-cohere==0.4.4,
rem torch, ragas) do NOT support Python 3.14. Pick the newest INSTALLED release in the
rem 3.11-3.13 range. Fall back to 3.13, 3.12, then 3.11.
set "PYVER="
py -3.13 -c "pass" >nul 2>nul && set "PYVER=3.13"
if not defined PYVER py -3.12 -c "pass" >nul 2>nul && set "PYVER=3.12"
if not defined PYVER py -3.11 -c "pass" >nul 2>nul && set "PYVER=3.11"
if not defined PYVER (
  echo No compatible Python (3.11/3.12/3.13) found. Install Python 3.11, 3.12 or 3.13, then run this file again.
  pause
  exit /b 1
)
echo Using Python %PYVER% to (re)build the virtual environment...
py -%PYVER% -m venv --clear "%ROOT%.venv"
if errorlevel 1 goto :repair_failed
"%PYTHON_EXE%" -m pip install --upgrade pip
if errorlevel 1 goto :repair_failed
"%PYTHON_EXE%" -m pip install -r "%ROOT%backend\requirements.txt"
if errorlevel 1 goto :repair_failed

echo Backend environment repaired successfully.

:start
cd /d "%ROOT%backend"
"%PYTHON_EXE%" -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload --reload-dir app --timeout-keep-alive 65
echo.
echo Backend process exited. Restarting in 3 seconds...
timeout /t 3 /nobreak >nul
goto start

:repair_failed
echo Backend environment repair failed. Check your internet connection and the errors above, then run this file again.
pause
exit /b 1
