from .models import SystemSetting


def get_setting(key, default=None):
    try:
        setting = SystemSetting.objects.get(key=key, is_active=True)
        return setting.value
    except SystemSetting.DoesNotExist:
        return default
