from django.apps import AppConfig


class MfsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'mfs'

    def ready(self):
        import mfs.signals  # noqa — регистрирует @receiver из signals.py
