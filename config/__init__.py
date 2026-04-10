# Make Celery app available when Django starts (only if celery is installed)
try:
    from .celery import app as celery_app

    __all__ = ("celery_app",)
except ImportError:
    pass
