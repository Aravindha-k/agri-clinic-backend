#!/usr/bin/env python
"""
Setup database with admin user, employee user, and master data
"""
import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.contrib.auth.models import User
from accounts.models import EmployeeProfile
from masters.models import District, Village, Crop, ProblemCategory

# 1. Create Admin User (admin/admin)
admin_user, created = User.objects.get_or_create(
    username="admin",
    defaults={"is_staff": True, "is_superuser": True, "email": "admin@agri.com"},
)
admin_user.set_password("admin")
admin_user.save()
print(f"✓ Admin user: {admin_user.username} / admin")

# 2. Create Test Employee User (apitest/testpass123)
employee_user, created = User.objects.get_or_create(
    username="apitest", defaults={"email": "apitest@agri.com"}
)
employee_user.set_password("testpass123")
employee_user.save()
print(f"✓ Employee user: {employee_user.username} / testpass123")

# 3. Create Employee Profile for apitest
try:
    emp_profile = EmployeeProfile.objects.get(user=employee_user)
except EmployeeProfile.DoesNotExist:
    emp_profile = EmployeeProfile.objects.create(
        user=employee_user,
        phone="9876543210",
        is_active_employee=True,
        employee_id="EMP003",
    )
print(f"✓ Employee profile: {emp_profile.employee_id}")

# 4. Create another employee
employee_user2, created = User.objects.get_or_create(
    username="employee1", defaults={"email": "employee1@agri.com"}
)
employee_user2.set_password("password")
employee_user2.save()
print(f"✓ Employee user: {employee_user2.username} / password")

# 5. Create Employee Profile for employee1
try:
    emp_profile2 = EmployeeProfile.objects.get(user=employee_user2)
except EmployeeProfile.DoesNotExist:
    emp_profile2 = EmployeeProfile.objects.create(
        user=employee_user2,
        phone="9876543211",
        is_active_employee=True,
        employee_id="EMP004",
    )
print(f"✓ Employee profile: {emp_profile2.employee_id}")

# 6. Create Masters - Viluppuram Data
district, created = District.objects.get_or_create(
    name="Viluppuram", defaults={"is_active": True}
)
print(f"✓ District: {district.name} (ID: {district.id})")

village, created = Village.objects.get_or_create(
    name="Viluppuram Village 1",
    district=district,
    defaults={"is_active": True},
)
print(f"✓ Village: {village.name} (ID: {village.id})")

crop, created = Crop.objects.get_or_create(
    name_en="Paddy",
    defaults={"name_ta": "Nel", "is_active": True},
)
print(f"✓ Crop: {crop.name_en} (ID: {crop.id})")

problem, created = ProblemCategory.objects.get_or_create(
    name="Pest", defaults={"is_active": True}
)
print(f"✓ Problem: {problem.name} (ID: {problem.id})")

print("\n" + "=" * 60)
print("✅ DATABASE SETUP COMPLETE")
print("=" * 60)
print("\n📝 LOGIN CREDENTIALS:")
print(f"  Admin:     admin / admin")
print(f"  Employee:  apitest / testpass123")
print(f"  Employee2: employee1 / password")
print("\n🗂️ MASTER DATA IDs:")
print(f"  District ID: {district.id}")
print(f"  Village ID: {village.id}")
print(f"  Crop ID: {crop.id}")
print(f"  Problem ID: {problem.id}")
print("\n🚀 NEXT STEPS:")
print("  1. Start server: python manage.py runserver 0.0.0.0:8000")
print("  2. Run E2E test: python tools/e2e_viluppuram_test.py")
print("  3. Import Postman: docs/agri-clinic-collection.json")
