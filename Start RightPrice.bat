@echo off
cd /d "%~dp0"
echo Starting RightPrice, the fabric should-cost tool. Open http://localhost:8502 in your browser.
python -m uvicorn server:app --port 8502
pause
