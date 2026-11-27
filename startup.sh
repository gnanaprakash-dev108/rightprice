#!/bin/bash
# Start command for Azure App Service (Linux, Python). Set it in
# Configuration > General settings > Startup Command as:  bash startup.sh
#
# server.py serves the whole app: one front end (the shell, web/rightcost.html and web/pages/) and the API.
# The earlier Streamlit screens, and the app setting RIGHTPRICE_UI=classic that started them alone, are retired
# (stage 4, 27 Nov 2026).
exec python -m uvicorn server:app --host 0.0.0.0 --port "${PORT:-8000}"
