from django.db.models import Max
from django.db import models

from .models import EmployeeProfile


def generate_employee_id():
    prefix = "KAC"

    last_id = (
        EmployeeProfile.objects.filter(employee_id__startswith=prefix)
        .annotate(
            num=models.functions.Cast(
                models.functions.Substr("employee_id", 5),
                output_field=models.IntegerField(),
            )
        )
        .aggregate(max_num=Max("num"))
        .get("max_num")
    )

    next_number = (last_id or 0) + 1
    return f"{prefix}-{next_number:04d}"
