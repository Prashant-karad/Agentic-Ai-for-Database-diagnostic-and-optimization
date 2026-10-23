#!/usr/bin/env bash
# Start everything for the dashboard: databases first, then the Streamlit app.
set -e
cd "$(dirname "$0")/.."

source .venv/bin/activate
bash scripts/start.sh
streamlit run src/dashboard/app.py