@echo off
cd /d "%~dp0"
uv run python pipeline\run_daily_update.py
