@echo off
REM Launch the 4 demo windows without the final `pause` from restart_demo.bat,
REM so a calling shell doesn't hang. Used during automated smoke tests.
set REPO=%~dp0
start "LogGuard API" cmd /k "cd /d %REPO%backend && .venv\Scripts\activate.bat && set LOGGUARD_DB_URL=postgresql://postgres:postgres@localhost:5432/logguard && set LOGGUARD_REDIS_URL=redis://localhost:6379 && set KMP_DUPLICATE_LIB_OK=TRUE && uvicorn api.main:app --host 0.0.0.0 --port 8000"
start "LogGuard Runner" cmd /k "cd /d %REPO%backend && .venv\Scripts\activate.bat && set LOGGUARD_DB_URL=postgresql://postgres:postgres@localhost:5432/logguard && set LOGGUARD_REDIS_URL=redis://localhost:6379 && set KMP_DUPLICATE_LIB_OK=TRUE && python -m ingestion.runner"
start "LogGuard RAG" cmd /k "cd /d %REPO%backend && .venv\Scripts\activate.bat && set LOGGUARD_DB_URL=postgresql://postgres:postgres@localhost:5432/logguard && set LOGGUARD_REDIS_URL=redis://localhost:6379 && set LOGGUARD_LLAMA_HOST=http://localhost:11434 && set LOGGUARD_LLAMA_MODEL=llama3.2:1b && set KMP_DUPLICATE_LIB_OK=TRUE && python -m rag.explainer"
start "LogGuard Frontend" cmd /k "cd /d %REPO%frontend && set VITE_USE_MOCK=false && npm run dev"
