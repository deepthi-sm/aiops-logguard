@echo off
REM ===================================================================
REM  LogGuard demo — full restart (nuclear option).
REM
REM  Use this when:
REM   - Something is stuck and `curl -X DELETE` won't clear it
REM   - The frontend or API is unresponsive
REM   - You want a 100%% fresh start before a demo run
REM
REM  Sequence:
REM   1. Kill all 4 LogGuard cmd windows (API, runner, RAG, frontend)
REM   2. Restart docker containers (redis, postgres, ollama)
REM   3. Wipe Postgres data (anomalies, drift_events) + Redis streams
REM   4. Re-launch all 4 cmd windows fresh
REM
REM  Total time: ~30 seconds.
REM ===================================================================

set REPO=%~dp0
cd /d "%REPO%"

echo [restart] step 1/4: closing existing LogGuard windows...
taskkill /FI "WINDOWTITLE eq LogGuard API*"      /T /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq LogGuard Runner*"   /T /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq LogGuard RAG*"      /T /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq LogGuard Frontend*" /T /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq LogGuard Replay*"   /T /F >nul 2>&1

echo [restart] step 2/4: restarting docker containers...
docker compose restart redis postgres ollama
timeout /t 4 /nobreak >nul

echo [restart] step 3/4: wiping Postgres + Redis state...
docker exec aiops-logguard-postgres-1 psql -U postgres -d logguard -c "TRUNCATE anomalies, drift_events RESTART IDENTITY CASCADE;" >nul 2>&1
docker exec aiops-logguard-redis-1 redis-cli FLUSHALL >nul 2>&1

echo [restart] step 4/4: launching fresh windows...
timeout /t 2 /nobreak >nul

start "LogGuard API" cmd /k "cd /d %REPO%backend && .venv\Scripts\activate.bat && set LOGGUARD_DB_URL=postgresql://postgres:postgres@localhost:5432/logguard && set LOGGUARD_REDIS_URL=redis://localhost:6379 && uvicorn api.main:app --host 0.0.0.0 --port 8000"
start "LogGuard Runner" cmd /k "cd /d %REPO%backend && .venv\Scripts\activate.bat && set LOGGUARD_DB_URL=postgresql://postgres:postgres@localhost:5432/logguard && set LOGGUARD_REDIS_URL=redis://localhost:6379 && set KMP_DUPLICATE_LIB_OK=TRUE && python -m ingestion.runner"
start "LogGuard RAG" cmd /k "cd /d %REPO%backend && .venv\Scripts\activate.bat && set LOGGUARD_DB_URL=postgresql://postgres:postgres@localhost:5432/logguard && set LOGGUARD_REDIS_URL=redis://localhost:6379 && set LOGGUARD_LLAMA_HOST=http://localhost:11434 && set LOGGUARD_LLAMA_MODEL=llama3.2:1b && set KMP_DUPLICATE_LIB_OK=TRUE && python -m rag.explainer"
start "LogGuard Frontend" cmd /k "cd /d %REPO%frontend && set VITE_USE_MOCK=false && npm run dev"

echo.
echo ===================================================================
echo  Full restart complete. Wait ~20 seconds for everything to come up,
echo  then open http://localhost:5173 in your browser.
echo  The dashboard will be EMPTY. Upload a file or paste the demo URL.
echo ===================================================================
echo.
pause
