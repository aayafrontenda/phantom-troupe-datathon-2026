# frontend

Web UI of CashGuard: React 19 + Vite + TypeScript, no UI libraries, design system in `src/styles/app.css` (forte.kz look).

```bash
npm ci
npm run dev        # http://127.0.0.1:5173, proxies the API to http://127.0.0.1:8000 (VITE_BACKEND to change)
npm run build      # frontend/dist — served by the backend
npm run typecheck
```

`deploy/run_server.sh` builds `dist` automatically when it is missing or stale; the Docker image builds it in a Node stage.
Everything the UI needs is in `docs/api_contract.md`; screens and conventions are in `docs/tasks/FRONTEND.md`.
