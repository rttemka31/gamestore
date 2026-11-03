# GameStore

Цифровая платформа и интернет-магазин видеоигр с личным профилем и каталогом.

## Запуск

Нужен Python 3.12 или новее (его требует Django 6).

```
git clone https://github.com/rttemka31/gamestore.git
cd gamestore
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy example.env .env
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Перед запуском заполни `.env` своими значениями (смотри `example.env`).
Сайт будет доступен на http://127.0.0.1:8000/

## Публичный запуск через туннель

Когда сайт открыт для других людей (например, через Cloudflare Tunnel), укажи в `.env`:

```
DJANGO_DEBUG=0
DJANGO_HTTPS=1
```

и запускай сервер так (без `--insecure` при выключенном `DEBUG` не загрузятся стили и скрипты):

```
python manage.py runserver --insecure
```

С `DJANGO_HTTPS=1` сайт не открывается по http://127.0.0.1:8000/, поэтому для обычной разработки верни `DJANGO_DEBUG=1` и `DJANGO_HTTPS=0`.
