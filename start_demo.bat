@echo off
REM ===================================================================
REM  LogGuard demo — one double-click startup.
REM
REM  Brings up the docker stack (redis, postgres, ollama) and opens
REM  four cmd windows for the API, ingestion runner, RAG explainer,
REM  and frontend dev server.
REM
REM  Demo flow is UPLOAD-DRIVEN: anomalies appear only after you
REM  upload a .log/.txt file via the /upload page in the dashboard.
REM  Nothing is auto-replayed.
REM
REM  Wait ~30 seconds after running this, then open
REM  http://localhost:5173 in your browser.
REM
REM  Optional — for a continuous-stream demo (pumps synthetic
REM  OpenStack lines through the pipeline):
REM      cd backend
REM      .venv\Scripts\activate.bat
REM      python -m tools.log_replay --rate 50 --critical-fraction 0.3
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
REM LOGGUARD_LLAMA_MODEL=llama3.2:1b — empirically the only model that
REM keeps per-explanation latency under ~30s on this CPU-only Ollama box.
REM 8b takes ~140s/call (CPU-saturated); 3b takes ~60s. 1b is the right
REM trade-off for the demo. Run `ollama pull llama3.2:1b` once on first
REM boot if the model isn't on disk yet.
start "LogGuard RAG" cmd /k "cd /d %REPO%backend && .venv\Scripts\activate.bat && set LOGGUARD_DB_URL=postgresql://postgres:postgres@localhost:5432/logguard && set LOGGUARD_REDIS_URL=redis://localhost:6379 && set LOGGUARD_LLAMA_HOST=http://localhost:11434 && set LOGGUARD_LLAMA_MODEL=llama3.2:1b && set KMP_DUPLICATE_LIB_OK=TRUE && python -m rag.explainer"

echo [start_demo] launching frontend (terminal 4)...
start "LogGuard Frontend" cmd /k "cd /d %REPO%frontend && set VITE_USE_MOCK=false && npm run dev"

echo.
echo ===================================================================
echo  All four processes started. Wait ~20 seconds for everything to
echo  initialise, then open  http://localhost:5173  in your browser.
echo.
echo  The dashboard will be EMPTY until you upload a .log/.txt file
echo  via the Upload page.
echo.
echo  To stop everything later, double-click  stop_demo.bat
echo ===================================================================
echo.
pause
