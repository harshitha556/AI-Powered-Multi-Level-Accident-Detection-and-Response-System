#!/bin/bash
# Start the Accident Detection backend
cd backend
pip install -r requirements.txt
cp ../.env.example .env 2>/dev/null || true
uvicorn app:app --host 0.0.0.0 --port 8000 --reload
