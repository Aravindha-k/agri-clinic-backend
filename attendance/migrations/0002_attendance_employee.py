"""Introduce AttendanceEmployee and migrate attendance identity off EmployeeProfile.

Strategy (non-destructive):
1. Create AttendanceEmployee.
2. Add a nullable `attendance_employee` FK on the three affected models and
   add the optional `shift` FK on EmployeeShopAssignment.
3. Backfill: for every EmployeeProfile referenced by existing attendance rows,
   create (or reuse) an AttendanceEmployee carrying the profile's employee_id
   as employee_code, then point the new FK at it. Rows referencing a missing
   profile get a LEGACY-EMP-<pk> identity — nothing is deleted or remapped
   silently.
4. Drop the old `employee` column, rename `attendance_employee` to `employee`,
   enforce NOT NULL, and restore the unique constraints on the new column.
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def backfill_attendance_employees(apps, schema_editor):
    EmployeeProfile = apps.get_model("accounts", "EmployeeProfile")
    AttendanceEmployee = apps.get_model("attendance", "AttendanceEmployee")

    cache = {}

    def identity_for(profile_pk):
        if profile_pk in cache:
            return cache[profile_pk]
        profile = (
            EmployeeProfile.objects.select_related("user")
            .filter(pk=profile_pk)
            .first()
        )
        if profile is not None:
            user = profile.user
            full_name = (user.get_full_name() or user.username)[:160]
            defaults = {
                "full_name": full_name,
                "phone": (profile.phone or "")[:20],
                "is_active": profile.is_active_employee,
                "linked_profile_id": profile.pk,
            }
            ae, _ = AttendanceEmployee.objects.get_or_create(
                employee_code=profile.employee_id, defaults=defaults
            )
            if ae.linked_profile_id is None:
                ae.linked_profile_id = profile.pk
                ae.save(update_fields=["linked_profile_id"])
        else:
            ae, _ = AttendanceEmployee.objects.get_or_create(
                employee_code=f"LEGACY-EMP-{profile_pk}",
                defaults={
                    "full_name": f"Legacy employee {profile_pk}",
                    "is_active": False,
                },
            )
        cache[profile_pk] = ae
        return ae

    for model_name in (
        "EmployeeShopAssignment",
        "AttendanceEvent",
        "AttendanceDailySummary",
    ):
        Model = apps.get_model("attendance", model_name)
        profile_ids = (
            Model.objects.exclude(employee__isnull=True)
            .values_list("employee_id", flat=True)
            .distinct()
        )
        for pid in profile_ids:
            ae = identity_for(pid)
            Model.objects.filter(employee_id=pid).update(attendance_employee=ae)


class Migration(migrations.Migration):

    dependencies = [
        ("attendance", "0001_initial"),
        ("accounts", "0014_assignment_district_nullable"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AttendanceEmployee",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("employee_code", models.CharField(db_index=True, help_text="Unique human code shown on the selection screen/reports.", max_length=32, unique=True)),
                ("full_name", models.CharField(max_length=160)),
                ("phone", models.CharField(blank=True, default="", max_length=20)),
                ("is_active", models.BooleanField(db_index=True, default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="created_attendance_employees", to=settings.AUTH_USER_MODEL)),
                ("updated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="updated_attendance_employees", to=settings.AUTH_USER_MODEL)),
                ("linked_profile", models.ForeignKey(blank=True, help_text="Optional informational link to a Field Officer profile. Does NOT grant login or mobile access.", null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="attendance_identities", to="accounts.employeeprofile")),
            ],
            options={"ordering": ["employee_code"]},
        ),
        migrations.AddField(
            model_name="employeeshopassignment",
            name="attendance_employee",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name="+", to="attendance.attendanceemployee"),
        ),
        migrations.AddField(
            model_name="attendanceevent",
            name="attendance_employee",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name="+", to="attendance.attendanceemployee"),
        ),
        migrations.AddField(
            model_name="attendancedailysummary",
            name="attendance_employee",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name="+", to="attendance.attendanceemployee"),
        ),
        migrations.AddField(
            model_name="employeeshopassignment",
            name="shift",
            field=models.ForeignKey(blank=True, help_text="Optional default shift for this employee at this shop.", null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="assignments", to="attendance.shift"),
        ),
        migrations.RunPython(
            backfill_attendance_employees,
            reverse_code=migrations.RunPython.noop,
        ),
        # ── EmployeeShopAssignment: swap FK ───────────────────────
        migrations.RemoveConstraint(
            model_name="employeeshopassignment",
            name="uniq_employee_shop_assignment",
        ),
        migrations.RemoveField(model_name="employeeshopassignment", name="employee"),
        migrations.RenameField(
            model_name="employeeshopassignment",
            old_name="attendance_employee",
            new_name="employee",
        ),
        migrations.AlterField(
            model_name="employeeshopassignment",
            name="employee",
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="shop_assignments", to="attendance.attendanceemployee"),
        ),
        migrations.AddConstraint(
            model_name="employeeshopassignment",
            constraint=models.UniqueConstraint(fields=("employee", "shop"), name="uniq_employee_shop_assignment"),
        ),
        # ── AttendanceEvent: swap FK ──────────────────────────────
        migrations.RemoveField(model_name="attendanceevent", name="employee"),
        migrations.RenameField(
            model_name="attendanceevent",
            old_name="attendance_employee",
            new_name="employee",
        ),
        migrations.AlterField(
            model_name="attendanceevent",
            name="employee",
            field=models.ForeignKey(db_index=True, on_delete=django.db.models.deletion.PROTECT, related_name="attendance_events", to="attendance.attendanceemployee"),
        ),
        # ── AttendanceDailySummary: swap FK ───────────────────────
        migrations.RemoveConstraint(
            model_name="attendancedailysummary",
            name="uniq_attendance_summary_emp_shop_date",
        ),
        migrations.RemoveField(model_name="attendancedailysummary", name="employee"),
        migrations.RenameField(
            model_name="attendancedailysummary",
            old_name="attendance_employee",
            new_name="employee",
        ),
        migrations.AlterField(
            model_name="attendancedailysummary",
            name="employee",
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="attendance_daily_summaries", to="attendance.attendanceemployee"),
        ),
        migrations.AddConstraint(
            model_name="attendancedailysummary",
            constraint=models.UniqueConstraint(fields=("employee", "shop", "date"), name="uniq_attendance_summary_emp_shop_date"),
        ),
    ]
