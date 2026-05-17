from django.apps import AppConfig


class VisitsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'visits'

    def ready(self):
        import visits.signals  # noqa: F401
