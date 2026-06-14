"""One-off audit: ProblemMaster DB + list API simulation."""
import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.contrib.auth.models import User
from rest_framework.test import APIClient

from masters.models import Crop, ProblemCategory, ProblemMaster

print("=== TABLE COUNTS ===")
print(f"crops: {Crop.objects.count()} (active={Crop.objects.filter(is_active=True).count()})")
print(f"problem_masters: {ProblemMaster.objects.count()} (active={ProblemMaster.objects.filter(is_active=True).count()}, inactive={ProblemMaster.objects.filter(is_active=False).count()})")
print(f"problem_categories: {ProblemCategory.objects.count()}")

print("\n=== CATEGORIES ===")
for row in ProblemCategory.objects.values("id", "code", "name", "is_active"):
    print(row)

print("\n=== FIRST 10 PROBLEM MASTERS ===")
for o in ProblemMaster.objects.select_related("category", "crop").order_by("id")[:10]:
    print(
        {
            "id": o.id,
            "name": o.name,
            "tamil_name_len": len(o.tamil_name or ""),
            "category_id": o.category_id,
            "category_code": o.category.code,
            "crop_id": o.crop_id,
            "crop_name": o.crop.name_en if o.crop_id else None,
            "is_active": o.is_active,
            "created_at": str(o.created_at),
        }
    )

admin = User.objects.filter(is_staff=True).first()
if not admin:
    admin = User.objects.create_user(username="audit_admin", password="x", is_staff=True, is_superuser=True)

client = APIClient()
client.force_authenticate(user=admin)

endpoints = [
    "/api/v1/masters/problem-masters/",
    "/api/v1/admin/problem-masters/",
    "/api/v1/admin/problem-items/",
    "/api/v1/problem-items/",
    "/api/v1/masters/problem-items/",
]

print("\n=== LIST API RESPONSES ===")
for url in endpoints:
    r = client.get(url)
    data = r.data
    if isinstance(data, dict):
        if "data" in data:
            payload = data["data"]
            if isinstance(payload, list):
                count = len(payload)
            elif isinstance(payload, dict) and "results" in payload:
                count = len(payload["results"])
            else:
                count = payload
        elif "results" in data:
            count = len(data["results"])
        else:
            count = data
    elif isinstance(data, list):
        count = len(data)
    else:
        count = data
    print(f"{url} -> status={r.status_code} count={count}")

# common frontend filters
for url in [
    "/api/v1/admin/problem-masters/?is_active=true",
    "/api/v1/admin/problem-items/?category=pest",
    "/api/v1/masters/problem-masters/?category_id=1",
]:
    r = client.get(url)
    print(f"{url} -> status={r.status_code} keys={list(r.data.keys()) if isinstance(r.data, dict) else type(r.data)}")

print("\n=== RESPONSE SHAPE DETAIL ===")
for url in [
    "/api/v1/admin/problem-masters/",
    "/api/v1/admin/problem-items/",
    "/api/v1/masters/problem-masters/",
]:
    r = client.get(url)
    d = r.data
    print("URL", url)
    if isinstance(d, dict):
        print("  top keys:", list(d.keys()))
        if "data" in d and isinstance(d["data"], list) and d["data"]:
            print("  data[0] keys:", list(d["data"][0].keys()))
            print("  data[0] category field:", d["data"][0].get("category"))
        if "results" in d and d["results"]:
            print("  results[0] keys:", list(d["results"][0].keys()))
            print("  results[0] category field:", d["results"][0].get("category"))
    print()
