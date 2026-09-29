@echo off
pip install -q -r backend\requirements.txt
python backend\seed.py
uvicorn backend.main:app --host 127.0.0.1 --port 8000
