# frontend

Интерфейс сейчас живёт в `backend/static/` (index.html, app.css, app.js, i18n.js) — обычный JS без сборки,
сервис отдаёт его сам, поэтому он работает и через туннель, и в Docker без Node.

Эта папка — место под React-сборку, если когда-нибудь понадобится: если есть `frontend/dist/index.html`,
backend отдаёт его вместо `backend/static/`.
