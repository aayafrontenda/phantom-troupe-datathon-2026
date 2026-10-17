# frontend

Web UI of PhantomGuard: React 19 + Vite + TypeScript + Tailwind v4, shadcn-style primitives in `src/components/ui`, lucide icons.
Design tokens (forte.kz look, light/dark) live in `src/styles/app.css` and are exposed to Tailwind in `src/styles/index.css`.

```bash
npm ci
npm run dev        # http://127.0.0.1:5173, proxies the API to http://127.0.0.1:8000 (VITE_BACKEND to change)
npm run build      # frontend/dist - served by the backend
npm run typecheck
```

`deploy/run_server.sh` builds `dist` automatically when it is missing or stale; the Docker image builds it in a Node stage.
Everything the UI needs is in `docs/api_contract.md`.

Screens: `/checks` (upload, progress, verdict, findings with frames / timecode / rule, operator decision, report) - the landing page;
`/findings/:id` (one moment: clip or video, AI description, operator wording, decision, supervisor check, history);
`/review` (supervisor: all operator decisions, filters, CSV); `/quality` (AI accuracy by type, adaptive thresholds, dataset export);
`/live` (cameras over WebSocket, event feed); `/rules` (violation types and regulations); `/admin` (users and roles).

Conventions: every string goes through `t()` (`src/i18n/strings.ts`, keys must exist in ru, kk and en - a backend test checks it);
styling with Tailwind utilities and `src/components/ui`, no inline styles for static looks; API shapes in `src/types.ts`.
