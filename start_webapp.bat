@echo off
cd /d "%~dp0"
echo Starting RW5 dashboard - http://127.0.0.1:8000/
uv run uvicorn api.main:app --reload
