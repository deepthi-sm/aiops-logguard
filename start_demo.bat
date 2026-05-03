@echo off
REM ===================================================================
REM  LogGuard demo — one double-click startup.
REM
REM  Brings up the docker stack (redis, postgres, ollama) and opens
REM  five cmd windows for the API, ingestion runner, RAG explainer,
REM  log replay, and frontend dev server.
REM
REM  Wait ~30 seconds after running this, then open
REM  http://localhost:5173 in your browser.
REM ===================================================================

set REPO=%~dp0
cd /d "%REPO%"

echo [start_demo] starting docker containers...
docker compose start
if errorlevel 1 (
    echo [start_demo] containers not yet created, doing first-boot up...
    docker compose up -d redis postgres ollama
)

REM Give Postgres a moment to accept connections.
timeout /t 5 /nobreak >nul

echo [start_demo] launching API (terminal 1)...
start "LogGuard API" cmd /k "cd /d %REPO%backend && .venv\Scripts\activate.bat && set LOGGUARD_DB_URL=postgresql://postgres:postgres@localhost:5432/logguard && set LOGGUARD_REDIS_URL=redis://localhost:6379 && uvicorn api.main:app --host 0.0.0.0 --port 8000"

echo [start_demo] launching ingestion runner (terminal 2)...
start "LogGuard Runner" cmd /k "cd /d %REPO%backend && .venv\Scripts\activate.bat && set LOGGUARD_DB_URL=postgresql://postgres:postgres@localhost:5432/logguard && set LOGGUARD_REDIS_URL=redis://localhost:6379 && set KMP_DUPLICATE_LIB_OK=TRUE && python -m ingestion.runner"

echo [start_demo] launching RAG explainer (terminal 3)...
start "LogGuard RAG" cmd /k "cd /d %REPO%backend && .venv\Scripts\activate.bat && set LOGGUARD_DB_URL=postgresql://postgres:postgres@localhost:5432/logguard && set LOGGUARD_REDIS_URL=redis://localhost:6379 && set LOGGUARD_LLAMA_HOST=http://localhost:11434 && set KMP_DUPLICATE_LIB_OK=TRUE && python -m rag.explainer"

echo [start_demo] launching log replay (terminal 4)...
start "LogGuard Replay" cmd /k "cd /d %REPO%backend && .venv\Scripts\activate.bat && set LOGGUARD_REDIS_URL=redis://localhost:6379 && python -m tools.log_replay --rate 50 --critical-fraction 0.3"

echo [start_demo] launching frontend (terminal 5)...
start "LogGuard Frontend" cmd /k "cd /d %REPO%frontend && set VITE_USE_MOCK=false && npm run dev"

echo.
echo ===================================================================
echo  All five processes started. Wait ~20 seconds for everything to
echo  initialise, then open  http://localhost:5173  in your browser.
echo.
echo  To stop everything later, double-click  stop_demo.bat
echo ===================================================================
echo.
pause
