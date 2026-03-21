from django.apps import AppConfig


class EvictedFrontendConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'evicted'
    verbose_name = 'Evicted'
