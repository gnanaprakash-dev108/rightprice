@echo off
cd /d "%~dp0"
echo Starting RightPrice, the fabric should-cost tool. Your browser will open at http://localhost:8502
python -m streamlit run app.py --server.port 8502
pause
