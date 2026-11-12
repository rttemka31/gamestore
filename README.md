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

## Структура проекта

```
config/                 настройки Django, корневые URL, WSGI/ASGI
mfs/                    приложение магазина
    models.py           игры, новости, профили, библиотека, друзья, отзывы
    urls.py             все адреса сайта
    admin.py            админка
    signals.py          создание профиля, удаление старых аватаров и баннеров
    views/              представления по разделам сайта
        common.py       общие помощники (корзина, избранное, безопасные ссылки)
        store.py        главная, каталог, страница игры, новости, поиск, 404
        cart.py         корзина и покупка
        library.py      библиотека, запуск и остановка игр, избранное, желаемое
        accounts.py     вход, регистрация, свой профиль, настройки, экспорт данных
        social.py       друзья, чужие профили, отзывы
    templatetags/       фильтры шаблонов (store_extras)
    tests/              тесты, разложенные так же, как views/
    migrations/         миграции базы данных
djang/
    templates/          шаблоны: base*.html, store/ — магазин, users/ — аккаунт, admin/
    static/
        css/            стили (style.css — общий, остальные — для отдельных страниц)
        css/event/      сезонные темы (Хэллоуин)
        js/             скрипты, js/event/ — для сезонных тем
        img/icons/      иконки интерфейса и логотипы
        fonts/          шрифты
    media/              загруженные файлы (в git не попадают)
backups/                копии базы перед миграциями (в git не попадают)
```

Тесты запускаются командой `python manage.py test mfs`.

## Публичный запуск через туннель

Когда сайт открыт для других людей (например, через Cloudflare Tunnel), укажи в `.env`:

```
DJANGO_DEBUG=0
DJANGO_HTTPS=1
```

И запускай сервер так (без `--insecure` при выключенном `DEBUG` не загрузятся стили и скрипты):

```
python manage.py runserver --insecure
```

С `DJANGO_HTTPS=1` сайт не открывается по http://127.0.0.1:8000/, поэтому для обычной разработки верни `DJANGO_DEBUG=1` и `DJANGO_HTTPS=0`.
