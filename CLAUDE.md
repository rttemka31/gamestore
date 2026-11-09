# GameStore

Интернет-магазин и цифровая платформа видеоигр на Django: каталог, корзина и покупка, библиотека с запуском игр и учётом времени, профили, друзья, отзывы, новости, вход через Google/Discord.

Репозиторий: https://github.com/rttemka31/gamestore (основная ветка `main`, работа идёт в feature-ветках).

## Стек
- Python 3.12, Django 6.1, django-allauth (Google, Discord), Pillow, python-dotenv
- SQLite (`db.sqlite3` в корне, в git не попадает)
- Фронтенд — шаблоны Django + чистые CSS/JS, без сборщика и без npm

## Команды
Запускать через venv проекта (`venv\Scripts\python.exe`):
- Сервер: `python manage.py runserver`
- Тесты: `python manage.py test mfs` (~100 тестов, около 2 минут)
- Миграции: `python manage.py makemigrations mfs` → `python manage.py migrate`

Настройки берутся из `.env` (образец — `example.env`). Для разработки `DJANGO_DEBUG=1`, `DJANGO_HTTPS=0`. Для публичного запуска через Cloudflare Tunnel — `DJANGO_DEBUG=0`, `DJANGO_HTTPS=1` и `runserver --insecure` (подробно в README).

## Структура
- `config/` — настройки, корневые URL, WSGI/ASGI
- `mfs/` — единственное приложение магазина
  - `models.py` — Game/Dlc (общий `BaseMediaProduct`), Genre, Collection, Screenshot, Profile, Friendship, Review, Wishlist, FavoriteGame, Cart, News, UserLibrary и др.
  - `urls.py` — все адреса сайта (namespace `mfs`)
  - `views/` — по разделам: `store`, `cart`, `library`, `accounts`, `social`, общие помощники в `common`; всё реэкспортируется через `views/__init__.py`
  - `security.py` — ограничение попыток входа и регистраций (через кэш, учитывает `CF-Connecting-IP` за прокси)
  - `signals.py` — создание профиля, удаление старых аватаров и баннеров
  - `templatetags/store_extras.py` — фильтры шаблонов
  - `tests/` — тесты разложены так же, как `views/`; общая база в `tests/base.py`
- `djang/templates/` — `base.html`, `base_mini.html`, `store/`, `users/`, `admin/`; частичные шаблоны начинаются с `_`
- `djang/static/` — `css/style.css` (общие стили и токены в `:root`), отдельные CSS для страниц, `js/`, сезонные темы в `css/event/` и `js/event/`
- `djang/media/` — загруженные файлы (в git не попадают)
- `backups/` — копии базы перед миграциями (`db.backup-before-00NN.sqlite3`)

## Правила проекта
- Комментарии в коде, docstring'и и сообщения коммитов — **на русском** (так принято в проекте).
- Сообщения коммитов: короткое описание сути изменений, без префиксов (`Каталог игр, исправление ошибок и усиление безопасности`).
- Views — функции, не классы. Новые адреса добавлять в `mfs/urls.py`, саму функцию — в подходящий модуль `views/` и экспортировать в `views/__init__.py`.
- Стили: использовать CSS-переменные из `:root` в `style.css` (`--accent`, `--bg-*`, `--text-*` и т.д.), не хардкодить цвета. Следить за контрастом текста (не ниже 4.5:1).
- Перед миграцией, меняющей данные, делать копию базы в `backups/db.backup-before-00NN.sqlite3`.
- На новую функциональность — тесты в соответствующем `mfs/tests/test_*.py`.
- После изменений прогонять `python manage.py test mfs`.

## На что обратить внимание
- `requirements.txt` сохранён в UTF-16 — при правке сохранить кодировку или согласовать перевод в UTF-8.
- `.env` содержит секреты — не читать и не выводить его содержимое без необходимости, не коммитить.
