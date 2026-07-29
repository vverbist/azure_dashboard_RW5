@echo off
setlocal

cd /d "%~dp0"

echo Starting SCADA update...
uv run python pipeline\run_scada_update.py %*
set "SCADA_EXIT_CODE=%ERRORLEVEL%"

if not "%SCADA_EXIT_CODE%"=="0" (
    echo.
    echo SCADA update failed with exit code %SCADA_EXIT_CODE%.
) else (
    echo.
    echo SCADA update completed successfully.
)

exit /b %SCADA_EXIT_CODE%
