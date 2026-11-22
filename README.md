# Chess Vision

Веб-приложение для анализа шахматных позиций и партий в формате PGN, игры против программы и турниров между её игровыми профилями. Интерфейс написан на React, API — на FastAPI, данные хранятся в SQLite.

## Локальный запуск

Из корня проекта, с установленными Docker и Docker Compose v2:

```sh
docker build -t chess-vision:local .
docker compose up -d --wait
curl -fsS http://127.0.0.1:8080/api/v1/health
```

Интерфейс: http://127.0.0.1:8080. Проверка API должна вернуть `{"status":"ok"}`.

## Автодеплой

После пуша в `main` [GitHub Actions](.github/workflows/deploy.yml) собирает образ на self-hosted раннере, передаёт его на `storage.netbird.cloud` по SSH и запускает Compose в `/data/chess`. Первый запуск можно сделать вручную: **Actions → Deploy Chess Vision → Run workflow → main**.

1. Зарегистрируйте Linux-раннер с меткой `chess-deploy`. Ему нужны Docker, SSH-клиент, `gzip` и доступ к серверу через NetBird. Архитектуры раннера и сервера должны совпадать. Не запускайте на этом раннере недоверенные workflow.
2. На сервере установите Docker и Compose v2. Создайте `/data/chess` и дайте SSH-пользователю право записи в этот каталог и возможность запускать Docker без `sudo`. Добавьте публичный ключ деплоя в `authorized_keys` этого пользователя.
3. В **Settings → Secrets and variables → Actions** добавьте переменную `CHESS_SSH_USER` (имя SSH-пользователя) и два секрета: `CHESS_SSH_KEY` (приватный ключ деплоя без парольной фразы) и `CHESS_SSH_KNOWN_HOSTS` (строка `known_hosts` для `storage.netbird.cloud` с проверенным ключом сервера).
4. По умолчанию приложение слушает `127.0.0.1:8080`. Чтобы открыть его в VPN, задайте `CHESS_BIND_IP=<NetBird-IP сервера>` в `/data/chess/.env`. Переменная `CHESS_PORT` меняет порт. Не публикуйте порт в интернете: в приложении нет аутентификации.

База сохраняется в `/data/chess/data/chess_vision.db` между деплоями. Если нужно перенести существующую базу, скопируйте её туда до первого запуска. Статус и логи на сервере: `cd /data/chess && docker compose ps && docker compose logs --tail=50 chess`.
