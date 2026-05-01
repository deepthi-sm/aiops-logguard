# AIOps-LogGuard frontend

React + TypeScript + Vite + Tailwind dashboard. Reads from the FastAPI
backend at `http://localhost:8000` (Vite proxies `/api` and `/ws` for you).

## Dev

```cmd
cd frontend
npm install
npm run dev
```

Then open `http://localhost:5173`.

The backend's CORS is already permissive for this origin (see
`backend/api/main.py`), and Vite proxies `/api` + `/ws` so you don't need
any other configuration.

## Build

```cmd
npm run build
```

Produces a static `dist/` you can serve with any static-file host (nginx,
Vercel, Netlify, GitHub Pages).

## Stack

- **React 18** + **TypeScript 5** strict mode
- **Vite 5** (dev server + build)
- **TanStack Query 5** for HTTP fetching, caching, auto-refresh
- **Native WebSocket** with reconnect-with-exponential-backoff
- **Tailwind 3** for styling
- **Recharts** for the timeline chart

## Contract sync

`src/api/types.ts` mirrors the Pydantic models in `backend/api/schemas.py`.
When the backend contract changes, update both files together. CLAUDE.md
"How Claude Code should work in this repo" requires this.

A future PR can replace the hand-written types file with codegen from the
deployed `/openapi.json` (e.g. `openapi-typescript`) so drift is impossible.
