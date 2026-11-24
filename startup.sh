#!/bin/bash
# Start command for Azure App Service (Linux, Python). Set it in
# Configuration > General settings > Startup Command as:  bash startup.sh
python -m streamlit run app.py \
  --server.port "${PORT:-8000}" \
  --server.address 0.0.0.0 \
  --server.headless true \
  --browser.gatherUsageStats false
