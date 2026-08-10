@echo off
title Admin Command Center
cd /d "%~dp0"
echo Starting Private Admin Dashboard...
echo (Opens in your browser automatically)
python "%~dp0admin-dashboard\server.py"
echo.
echo The admin dashboard server has stopped.
pause