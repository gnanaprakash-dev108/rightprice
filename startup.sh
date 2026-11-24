#!/bin/bash
# Start command for Azure App Service (Linux, Python). Set it in
# Configuration > General settings > Startup Command as:  bash startup.sh
#
# server.py serves the new front end and starts the earlier Streamlit screens beside itself,
# reachable under /classic. To go back to the Streamlit screens alone, set the app setting
# RIGHTPRICE_UI=classic and restart.
if [ "$RIGHTPRICE_UI" = "classic" ]; then
  exec python -m streamlit run app.py \
    --server.port "${PORT:-8000}" \
    --server.address 0.0.0.0 \
    --server.headless true \
    --browser.gatherUsageStats false
fi
exec python -m uvicorn server:app --host 0.0.0.0 --port "${PORT:-8000}"
