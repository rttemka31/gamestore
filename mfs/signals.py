import os

from django.conf import settings
from django.contrib.auth.signals import user_logged_in, user_login_failed
from django.core.cache import cache
from django.db.models.signals import pre_save, post_delete, post_save
from django.dispatch import receiver

from .models import News, Profile
from .security import record_login_failure, reset_login_failures
from .sessions import DEVICE_KEY, device_info
from .templatetags.store_extras import SITE_VERSION_CACHE_KEY


@receiver([post_save, post_delete], sender=News)
def forget_site_version(sender, **kwargs):
    """Новая новость с номером версии должна сразу появиться в подвале."""
    cache.delete(SITE_VERSION_CACHE_KEY)


@receiver(user_login_failed)
def count_failed_login(sender, credentials, request=None, **kwargs):
    """Каждая неудачная попытка входа (на сайте и в админке) приближает блокировку."""
    if request is not None:
        record_login_failure(request, credentials.get('username'))


@receiver(user_logged_in)
def forget_failed_logins(sender, request, user, **kwargs):
    if request is not None:
        reset_login_failures(request, user.get_username())


@receiver(user_logged_in)
def remember_device(sender, request, user, **kwargs):
    """Запоминаем устройство и время входа — для списка устройств в настройках."""
    if request is not None and hasattr(request, 'session'):
        request.session[DEVICE_KEY] = device_info(request)


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_profile_for_new_user(sender, instance, created, raw=False, **kwargs):
    """Профиль нужен сразу: иначе нового пользователя нельзя найти в поиске друзей."""
    if created and not raw:
        Profile.objects.get_or_create(user=instance)


def _delete_file(field_file):
    """Безопасно удаляет файл с диска, если он реально существует."""
    if field_file and field_file.name:
        try:
            if os.path.isfile(field_file.path):
                os.remove(field_file.path)
        except Exception as e:
            print(f"Не удалось удалить файл {field_file.name}: {e}")


@receiver(pre_save, sender=Profile)
def delete_old_avatar_and_banner_on_change(sender, instance, **kwargs):
    """
    Перед каждым сохранением Profile сравниваем новый avatar/banner
    со старым значением из БД. Если файл поменялся — удаляем
    старую копию с диска, чтобы они не копились (как на скриншоте
    с десятками photo_2026-..._xxx.jpg в media/banners/).
    """
    if not instance.pk:
        return  # это ещё не существующий профиль — сравнивать не с чем

    try:
        old_instance = Profile.objects.get(pk=instance.pk)
    except Profile.DoesNotExist:
        return

    for field_name in ('avatar', 'banner'):
        old_file = getattr(old_instance, field_name, None)
        new_file = getattr(instance, field_name, None)

        old_name = old_file.name if old_file else None
        new_name = new_file.name if new_file else None

        if old_name and old_name != new_name:
            _delete_file(old_file)


@receiver(post_delete, sender=Profile)
def delete_files_on_profile_delete(sender, instance, **kwargs):
    """
    Если профиль удаляют целиком (например, при удалении аккаунта
    через form=delete_account) — подчищаем оба файла за собой,
    иначе они останутся сиротами в media/.
    """
    _delete_file(instance.avatar)
    _delete_file(instance.banner)