# Развёртывание на ROG и публичный адрес

Сервер — ноутбук ASUS ROG (единственная NVIDIA GPU). Он должен быть включён и в сети всё время,
пока жюри проверяет решения.

## 1. Настройки Windows (один раз, PowerShell от администратора)

```powershell
powercfg /change standby-timeout-ac 0       # не засыпать от сети
powercfg /change hibernate-timeout-ac 0     # не уходить в гибернацию
powercfg /setacvalueindex SCHEME_CURRENT SUB_BUTTONS LIDACTION 0   # закрытие крышки — ничего не делать
powercfg /setactive SCHEME_CURRENT
```

Ещё: зарядка подключена, режим питания «Производительность» (Armoury Crate → Turbo/Performance),
обновления Windows приостановлены (Параметры → Центр обновления → Приостановить).

## 2. Запуск сервиса

```powershell
copy .env.example .env      # ANALYZER=ml, API_KEY=<ключ для жюри>, VLM_*
powershell -ExecutionPolicy Bypass -File deploy\run_server.ps1
```

Проверка: http://127.0.0.1:8000 (интерфейс), http://127.0.0.1:8000/health.

## 3. Публичный адрес (Cloudflare Tunnel)

```powershell
winget install --id Cloudflare.cloudflared
cloudflared tunnel --url http://localhost:8000
```

В выводе будет адрес `https://<случайные-слова>.trycloudflare.com` — это URL для жюри.
Адрес быстрого туннеля меняется при перезапуске `cloudflared`: после сдачи его не трогаем.
Если есть свой домен в Cloudflare — сделайте именованный туннель, тогда адрес постоянный.

Проверить с телефона через мобильный интернет (не Wi-Fi ноутбука) и с чужого компьютера:

```bash
curl -X POST https://<адрес>/api/v1/analyze -H "X-API-Key: <ключ>" -F "file=@X-1.mov"
python tools/smoke_test.py --url https://<адрес> --key <ключ> --dir data/open/videos --limit 5
```

## 4. Перед сдачей

- `API_KEY` в `.env` задан явно (иначе ключ лежит в `storage/api_key.txt`).
- `HF_HUB_OFFLINE=1` в `.env` — сервис не ходит в интернет за весами.
- Прогнаны все 40 видео и 5 видео одновременно через публичный адрес; каждое < 300 с.
- Терминалы с `run_server.ps1` и `cloudflared` открыты, ноутбук на зарядке.
