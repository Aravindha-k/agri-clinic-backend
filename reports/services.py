from django.db.models import Count
from visits.models import Visit


def employee_wise_visits(start_date=None, end_date=None):
    qs = Visit.objects.select_related("employee")

    if start_date:
        qs = qs.filter(visit_date__gte=start_date)
    if end_date:
        qs = qs.filter(visit_date__lte=end_date)

    return (
        qs.values("employee__username")
        .annotate(total_visits=Count("id"))
        .order_by("-total_visits")
    )


def village_wise_visits(start_date=None, end_date=None):
    qs = Visit.objects.select_related("village")

    if start_date:
        qs = qs.filter(visit_date__gte=start_date)
    if end_date:
        qs = qs.filter(visit_date__lte=end_date)

    return (
        qs.values("village__name")
        .annotate(total_visits=Count("id"))
        .order_by("-total_visits")
    )


def crop_problem_report(start_date=None, end_date=None):
    qs = Visit.objects.select_related("employee", "district", "village", "crop")

    if start_date:
        qs = qs.filter(visit_date__gte=start_date)
    if end_date:
        qs = qs.filter(visit_date__lte=end_date)

    return (
        qs.filter(pest_issue=True)
        .values("crop__name_en")
        .annotate(count=Count("id"))
        .order_by("-count")
    )
