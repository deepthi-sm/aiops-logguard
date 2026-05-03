@echo off
REM ===================================================================
REM  LogGuard demo — one double-click shutdown.
REM
REM  Closes all four LogGuard cmd windows by their titles, then pauses
REM  the docker containers (data is preserved — bring it back with
REM  start_demo.bat).
REM ===================================================================

set REPO=%~dp0
cd /d "%REPO%"

echo [stop_demo] closing LogGuard cmd windows...
taskkill /FI "WINDOWTITLE eq LogGuard API*" /T /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq LogGuard Runner*" /T /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq LogGuard RAG*" /T /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq LogGuard Frontend*" /T /F >nul 2>&1
REM Also kill any optional LogGuard Replay window if you started one manually:
taskkill /FI "WINDOWTITLE eq LogGuard Replay*" /T /F >nul 2>&1

echo [stop_demo] stopping docker containers (data preserved)...
docker compose stop

echo.
echo ===================================================================
echo  Demo stopped. Anomaly history in Postgres is preserved.
echo  Restart anytime by double-clicking  start_demo.bat
echo ===================================================================
echo.
pause
