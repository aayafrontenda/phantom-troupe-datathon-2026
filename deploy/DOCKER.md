# Docker

Два режима, одна команда.

| Где | Что запускается | Команда |
| --- | --- | --- |
| Ноутбук Аслана (Windows + RTX) | сервис + настоящая модель на GPU + Ollama (VLM) + туннель Cloudflare | `powershell -ExecutionPolicy Bypass -File deploy\docker.ps1 -Tunnel` |
| Mac / любой компьютер без NVIDIA | сервис + демо-анализатор (без модели) | `./deploy/docker.sh` |

Интерфейс: http://127.0.0.1:8000 (вход - пользователи из `SEED_USERS` в `.env`). Интерфейс собирается внутри образа (Node не нужен на машине).
Ключ жюри скрипт печатает в конце (если `API_KEY` в `.env` пустой, он генерируется один раз и хранится в volume).

## Ноутбук с GPU (Windows)

Один раз:
1. Драйвер NVIDIA свежий; Docker Desktop с WSL2 backend (Settings → General → Use WSL 2).
2. Проверка GPU в Docker: `docker run --rm --gpus all ubuntu nvidia-smi` - должна показать видеокарту.
3. `copy .env.example .env` и заполнить: `API_KEY`, `ADMIN_KEY`, `CLOUDFLARE_TUNNEL_TOKEN` (токен туннеля из Cloudflare - то, что после `--token` в команде на странице туннеля).

Запуск:
```powershell
powershell -ExecutionPolicy Bypass -File deploy\docker.ps1 -Tunnel
```
Первый запуск: сборка образа ~10–20 мин (PyTorch + веса детектора внутри образа). VLM берётся из Ollama на самой Windows,
если в `.env` задан `VLM_URL_DOCKER=http://host.docker.internal:11434` (так сейчас у Аслана: `ollama pull qwen3.5:4b` один раз).
Если `VLM_URL_DOCKER` пустой, поднимается встроенная Ollama в контейнере и сама скачивает `VLM_MODEL` в volume.
Дальше старт за минуту. Логи: `deploy\docker.ps1 -Logs`, остановка: `deploy\docker.ps1 -Down` (данные остаются).

**Туннель.** Если в `.env` есть `CLOUDFLARE_TUNNEL_TOKEN`, поднимается именованный туннель (постоянный домен).
В Cloudflare → Networking → Tunnels → туннель → Public Hostname: сервис `HTTP`, URL `app:8000`
(cloudflared работает внутри compose и видит сервис по имени `app`). Без токена - быстрый туннель, адрес
`https://*.trycloudflare.com` скрипт печатает сам (меняется при каждом перезапуске).

**Ollama уже стоит на Windows?** В `.env` `VLM_URL_DOCKER=http://host.docker.internal:11434` - контейнер Ollama тогда не запускается.

**Модель изменилась.** Код `ml/` копируется в образ, поэтому после изменений: `deploy\docker.ps1 -Tunnel` (пересоберёт только верхний слой, ~10 с).
Для быстрой итерации над моделью без Docker: `deploy\run_server.ps1` (venv + Ollama на самой Windows, те же настройки из `.env`).

**Ноутбук не должен засыпать** (PowerShell от администратора, один раз):
```powershell
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
powercfg /setacvalueindex SCHEME_CURRENT SUB_BUTTONS LIDACTION 0
powercfg /setactive SCHEME_CURRENT
```
Зарядка подключена, режим «Производительность», обновления Windows приостановлены.

## Перед сдачей

- `/ready` отвечает 200 через публичный адрес (воркер прогрет, детектор и VLM загружены).
- `API_KEY` и `ADMIN_KEY` в `.env` заданы явно; `PUBLIC_URL` - адрес интерфейса (ссылки в уведомлениях).
- Камеры и симуляторы остановлены: пока идёт проверка жюри, GPU нужна только задачам.
- Прогнано с чужой сети: `python tools/smoke_test.py --url https://<адрес> --key <ключ> --dir data/open/videos --limit 5`
  и `python tools/loadtest.py --url https://<адрес> --key <ключ> --dir data/open/videos --uploads 10 --unique` - каждое видео < 300 с, `partial 0`.
- `DEDUP=0` на время финальных правок модели (иначе повторная загрузка того же файла вернёт старый результат); перед сдачей можно вернуть `1`.

## Mac (демо без модели)

```bash
./deploy/docker.sh            # http://127.0.0.1:8000
./deploy/docker.sh --tunnel   # + публичный адрес
./deploy/docker.sh --down
```
Если порт 8000 занят dev-сервером - `PORT=8080` в `.env`.

## Что внутри

- `docker-compose.yml` - сервис `app` (демо-анализатор), профили `tunnel` (trycloudflare) и `tunnel-named` (токен).
- `docker-compose.gpu.yml` - поверх него: образ с PyTorch CUDA и весами детектора, `ANALYZER=ml`, GPU; профиль `ollama` - встроенная Ollama + загрузка `VLM_MODEL`.
- Данные (`/app/storage`: база, результаты, загрузки) - volume `storage`; видео операторов хранятся `VIDEO_RETENTION_DAYS` (0 = всегда), видео жюри - `JURY_VIDEO_TTL_SEC`.
- Анализ офлайн: веса детектора в образе, `HF_HUB_OFFLINE=1`, VLM локально в Ollama. Наружу ходит только cloudflared.
