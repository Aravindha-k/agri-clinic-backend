from django.db import models
from django.contrib.auth.models import User
from django.conf import settings


class EmployeeProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)

    employee_id = models.CharField(max_length=20, unique=True)

    phone = models.CharField(max_length=15)

    is_active_employee = models.BooleanField(default=True)  # ✅ ADD THIS

    def __str__(self):
        return f"{self.employee_id} - {self.user.username}"
