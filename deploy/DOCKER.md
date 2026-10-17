# Docker

Два режима, одна команда.

| Где | Что запускается | Команда |
| --- | --- | --- |
| Ноутбук Аслана (Windows + RTX) | сервис + настоящая модель на GPU + Ollama (VLM) + туннель Cloudflare | `powershell -ExecutionPolicy Bypass -File deploy\docker.ps1 -Tunnel` |
| Mac / любой компьютер без NVIDIA | сервис + демо-анализатор (без модели) | `./deploy/docker.sh` |

Интерфейс: http://127.0.0.1:8000. Ключ жюри скрипт печатает в конце (если `API_KEY` в `.env` пустой, он генерируется один раз и хранится в volume).

## Ноутбук с GPU (Windows)

Один раз:
1. Драйвер NVIDIA свежий; Docker Desktop с WSL2 backend (Settings → General → Use WSL 2).
2. Проверка GPU в Docker: `docker run --rm --gpus all ubuntu nvidia-smi` — должна показать видеокарту.
3. `copy .env.example .env` и заполнить: `API_KEY`, `ADMIN_KEY`, `CLOUDFLARE_TUNNEL_TOKEN` (токен туннеля из Cloudflare — то, что после `--token` в команде на странице туннеля).

Запуск:
```powershell
powershell -ExecutionPolicy Bypass -File deploy\docker.ps1 -Tunnel
```
Первый запуск: сборка образа ~10–20 мин (PyTorch + веса детектора внутри образа) и скачивание VLM (~6 ГБ, один раз, хранится в volume `ollama`).
Дальше старт за минуту. Логи: `deploy\docker.ps1 -Logs`, остановка: `deploy\docker.ps1 -Down` (данные остаются).

**Туннель.** Если в `.env` есть `CLOUDFLARE_TUNNEL_TOKEN`, поднимается именованный туннель (постоянный домен).
В Cloudflare → Networking → Tunnels → туннель → Public Hostname: сервис `HTTP`, URL `app:8000`
(cloudflared работает внутри compose и видит сервис по имени `app`). Без токена — быстрый туннель, адрес
`https://*.trycloudflare.com` скрипт печатает сам (меняется при каждом перезапуске).

**Ollama уже стоит на Windows?** Можно не тянуть модель второй раз: в `.env` `VLM_URL_DOCKER=http://host.docker.internal:11434`
(тогда контейнер `ollama` всё равно стартует, но не используется).

**Аслан поменял модель.** Код `ml/` копируется в образ, поэтому после изменений: `deploy\docker.ps1 -Tunnel` (пересоберёт только верхний слой, ~10 с).
Для быстрой итерации над моделью удобнее без Docker: `deploy\run_server.ps1` (см. `deploy/README.md`).

## Mac (демо без модели)

```bash
./deploy/docker.sh            # http://127.0.0.1:8000
./deploy/docker.sh --tunnel   # + публичный адрес
./deploy/docker.sh --down
```
Если порт 8000 занят dev-сервером — `PORT=8080` в `.env`.

## Что внутри

- `docker-compose.yml` — сервис `app` (демо-анализатор), профили `tunnel` (trycloudflare) и `tunnel-named` (токен).
- `docker-compose.gpu.yml` — поверх него: образ с PyTorch CUDA и весами детектора, `ANALYZER=ml`, GPU, `ollama` + `ollama-pull`.
- Данные (`/app/storage`: база, результаты, загрузки) — volume `storage`; видео удаляются через `VIDEO_TTL_SEC`.
- Анализ офлайн: веса детектора в образе, `HF_HUB_OFFLINE=1`, VLM локально в Ollama. Наружу ходит только cloudflared.
