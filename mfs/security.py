"""Защита аккаунтов от подбора паролей и массовой регистрации.

Счётчики живут в кэше Django: каждая неудачная попытка увеличивает счётчик, а через
LOCK_SECONDS после первой попытки он сбрасывается сам.
"""
from django.conf import settings
from django.contrib.auth.backends import ModelBackend
from django.core.cache import cache
from django.core.exceptions import PermissionDenied

LOCK_SECONDS = 15 * 60
MAX_FAILURES_PER_ACCOUNT = 5   # на одно имя пользователя с одного адреса
MAX_FAILURES_PER_IP = 20       # на все имена с одного адреса
MAX_REGISTRATIONS_PER_IP = 5
REGISTRATION_WINDOW = 60 * 60


def client_ip(request):
    """IP посетителя. За Cloudflare Tunnel все запросы приходят с 127.0.0.1, поэтому
    настоящий адрес берём из заголовка Cloudflare — но только когда сайт работает за прокси."""
    if getattr(settings, 'SECURE_PROXY_SSL_HEADER', None):
        forwarded = request.META.get('HTTP_CF_CONNECTING_IP')
        if forwarded:
            return forwarded.strip()
    return request.META.get('REMOTE_ADDR', '')


def _keys(request, username):
    ip = client_ip(request)
    return f'auth-fail:{(username or "").lower()}:{ip}', f'auth-fail-ip:{ip}'


def _bump(key, timeout):
    # add() задаёт срок жизни только при первой попытке, поэтому окно не продлевается бесконечно
    if not cache.add(key, 1, timeout):
        try:
            cache.incr(key)
        except ValueError:  # ключ успел истечь между add() и incr()
            cache.add(key, 1, timeout)


def login_locked(request, username):
    account_key, ip_key = _keys(request, username)
    return (cache.get(account_key, 0) >= MAX_FAILURES_PER_ACCOUNT
            or cache.get(ip_key, 0) >= MAX_FAILURES_PER_IP)


def record_login_failure(request, username):
    for key in _keys(request, username):
        _bump(key, LOCK_SECONDS)


def reset_login_failures(request, username):
    cache.delete(_keys(request, username)[0])


def password_check_locked(user):
    """Подбор текущего пароля в настройках (если сессию украли) ограничен так же, как вход."""
    return cache.get(f'password-check:{user.pk}', 0) >= MAX_FAILURES_PER_ACCOUNT


def record_password_check_failure(user):
    _bump(f'password-check:{user.pk}', LOCK_SECONDS)


def registration_limited(request):
    return cache.get(f'register:{client_ip(request)}', 0) >= MAX_REGISTRATIONS_PER_IP


def record_registration(request):
    _bump(f'register:{client_ip(request)}', REGISTRATION_WINDOW)


class RateLimitedModelBackend(ModelBackend):
    """Обычный вход по логину и паролю, но после серии неудач — отказ без проверки пароля.
    Работает и для формы входа сайта, и для админки."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        if request is not None and login_locked(request, username):
            # PermissionDenied останавливает перебор остальных бэкендов и засчитывается как неудача
            raise PermissionDenied
        return super().authenticate(request, username=username, password=password, **kwargs)
