#!/bin/sh
# API container entry: dev uses --reload; set API_RELOAD=0 for production-like runs.
set -e
if [ "${API_RELOAD:-1}" = "1" ] || [ "${API_RELOAD:-1}" = "true" ]; then
  exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
else
  exec uvicorn app.main:app --host 0.0.0.0 --port 8000
fi
