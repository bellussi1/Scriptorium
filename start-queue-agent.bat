@echo off
REM ============================================
REM Scriptorium - Queue Runner Agent
REM Host-side supervisor for the Queue UI's Run buttons.
REM Keep this window open while using the Queue tab.
REM ============================================

setlocal
chcp 65001 >nul 2>&1
cd /d "%~dp0"
title Queue Runner Agent

echo Queue Runner Agent
echo ------------------
echo Watching data\literary_queue.run-request.json
echo Press Ctrl+C to stop the agent.
echo.

python scripts\queue_runner_agent.py

echo.
echo Agent stopped.
pause
