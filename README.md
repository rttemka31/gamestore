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
