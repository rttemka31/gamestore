"""Устройства, на которых выполнен вход.

Данные об устройстве хранятся прямо в сессии (ключ _device): браузер и система из
User-Agent, IP, время входа и последней активности. Поэтому в настройках можно показать
список сеансов и завершить любой из них. Ключ сессии наружу не отдаётся: устройство
определяется по его хешу, иначе по странице можно было бы угнать чужой сеанс.
"""
import hashlib
import re
from datetime import datetime, timedelta, timezone as dt_timezone

from django.contrib.auth import SESSION_KEY
from django.contrib.sessions.models import Session
from django.utils import timezone

from .security import client_ip

DEVICE_KEY = '_device'
# Сеансы, начатые до появления списка устройств, о себе ничего не знают — их показываем одной строкой
LEGACY_ID = 'legacy'
# Время активности обновляем не чаще раза в 5 минут, чтобы не сохранять сессию на каждый запрос
TOUCH_EVERY = timedelta(minutes=5)

BROWSERS = [
    ('Edge', r'Edg(?:e|A|iOS)?/'),
    ('Opera', r'OPR/|Opera'),
    ('Яндекс Браузер', r'YaBrowser/'),
    ('Samsung Internet', r'SamsungBrowser/'),
    ('Firefox', r'Firefox/|FxiOS/'),
    ('Chrome', r'Chrome/|CriOS/'),
    ('Safari', r'Safari/'),
]
SYSTEMS = [
    ('Android', r'Android'),
    ('iPhone', r'iPhone'),
    ('iPad', r'iPad'),
    ('Windows', r'Windows'),
    ('macOS', r'Mac OS X|Macintosh'),
    ('Linux', r'Linux|X11'),
]
MOBILE_SYSTEMS = {'Android', 'iPhone', 'iPad'}


def _now_ts():
    return int(timezone.now().timestamp())


def device_info(request, started=True):
    """Сведения о текущем устройстве для записи в сессию."""
    now = _now_ts()
    return {
        'ua': request.META.get('HTTP_USER_AGENT', '')[:300],
        'ip': client_ip(request),
        'started': now if started else None,
        'seen': now,
    }


def describe_user_agent(user_agent):
    """Название устройства из User-Agent («Chrome · Windows») и признак телефона или планшета."""
    browser = next((name for name, pattern in BROWSERS if re.search(pattern, user_agent or '')), None)
    system = next((name for name, pattern in SYSTEMS if re.search(pattern, user_agent or '')), None)
    name = ' · '.join(part for part in (browser, system) if part) or 'Неизвестное устройство'
    return name, system in MOBILE_SYSTEMS


def device_id(session_key):
    return hashlib.sha256(session_key.encode()).hexdigest()[:16]


class DeviceTrackingMiddleware:
    """Записывает устройство в сессию вошедшего пользователя и обновляет время активности."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # До обработки запроса: если в нём будет выход, сессия очистится и мы её не тронем
        if request.user.is_authenticated:
            device = request.session.get(DEVICE_KEY)
            if not device:
                # Сеанс начат до появления списка устройств — время входа неизвестно
                request.session[DEVICE_KEY] = device_info(request, started=False)
            elif _now_ts() - device.get('seen', 0) >= TOUCH_EVERY.total_seconds():
                device.update(seen=_now_ts(), ip=client_ip(request))
                request.session.modified = True
        return self.get_response(request)


def _user_sessions(user):
    """Активные сессии пользователя: пары (ключ, данные)."""
    for session in Session.objects.filter(expire_date__gte=timezone.now()).iterator():
        data = session.get_decoded()
        if data.get(SESSION_KEY) == str(user.pk):
            yield session, data


def _to_datetime(timestamp):
    return datetime.fromtimestamp(timestamp, dt_timezone.utc) if timestamp else None


def list_devices(user, current_key):
    """Устройства пользователя для страницы настроек: текущее первым, затем по активности."""
    devices = []
    legacy = 0
    for session, data in _user_sessions(user):
        info = data.get(DEVICE_KEY)
        current = session.session_key == current_key
        if not info and not current:
            legacy += 1
            continue
        info = info or {}
        name, is_mobile = describe_user_agent(info.get('ua', ''))
        seen = _to_datetime(info.get('seen'))
        devices.append({
            'id': device_id(session.session_key),
            'name': name,
            'is_mobile': is_mobile,
            'ip': info.get('ip', ''),
            'started': _to_datetime(info.get('started')),
            'seen': seen,
            # Активность обновляется раз в 5 минут, так что «недавно» — это последние 10 минут
            'active_now': bool(seen) and timezone.now() - seen < TOUCH_EVERY * 2,
            'current': current,
        })
    devices.sort(key=lambda d: (not d['current'], -(d['seen'].timestamp() if d['seen'] else 0)))
    if legacy:
        devices.append({'id': LEGACY_ID, 'legacy_count': legacy, 'current': False})
    return devices


def end_device_session(user, target_id, current_key):
    """Завершает сеанс пользователя по id устройства (LEGACY_ID — все старые сеансы сразу).
    Текущий сеанс так не завершить."""
    ended = False
    for session, data in _user_sessions(user):
        if session.session_key == current_key:
            continue
        if target_id == LEGACY_ID:
            matches = not data.get(DEVICE_KEY)
        else:
            matches = device_id(session.session_key) == target_id
        if matches:
            session.delete()
            ended = True
    return ended


def end_other_sessions(user, current_key):
    """Завершает все сеансы пользователя, кроме текущего, и возвращает их количество."""
    ended = 0
    for session, _ in _user_sessions(user):
        if session.session_key != current_key:
            session.delete()
            ended += 1
    return ended
