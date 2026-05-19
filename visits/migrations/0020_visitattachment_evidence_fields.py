from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def forwards_map_legacy_file_type(apps, schema_editor):
    VisitAttachment = apps.get_model("visits", "VisitAttachment")
    mapping = {
        "CROP": "image",
        "SOIL": "image",
        "BILL": "other",
        "VOICE": "audio",
        "PDF": "pdf",
        "OTHER": "other",
    }
    for row in VisitAttachment.objects.select_related("visit").all().iterator():
        legacy = (getattr(row, "file_type", None) or "OTHER").upper()
        row.attachment_type = mapping.get(legacy, "other")
        if row.visit_id:
            row.employee_id = row.visit.employee_id
            row.uploaded_by_id = row.visit.employee_id
        if row.file:
            if not row.original_filename:
                row.original_filename = row.file.name.split("/")[-1]
            try:
                row.file_size = row.file.size or 0
            except Exception:
                row.file_size = 0
        row.save()


class Migration(migrations.Migration):

    dependencies = [
        ("visits", "0019_visit_local_sync_id"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="visitattachment",
            name="attachment_type",
            field=models.CharField(
                choices=[
                    ("image", "Image"),
                    ("pdf", "PDF"),
                    ("audio", "Audio"),
                    ("text", "Text note"),
                    ("other", "Other"),
                ],
                db_index=True,
                max_length=20,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="visitattachment",
            name="employee",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="visit_attachments",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="visitattachment",
            name="text_content",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="visitattachment",
            name="original_filename",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="visitattachment",
            name="mime_type",
            field=models.CharField(blank=True, default="", max_length=128),
        ),
        migrations.AddField(
            model_name="visitattachment",
            name="file_size",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="visitattachment",
            name="uploaded_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="uploaded_visit_attachments",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.RunPython(forwards_map_legacy_file_type, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="visitattachment",
            name="attachment_type",
            field=models.CharField(
                choices=[
                    ("image", "Image"),
                    ("pdf", "PDF"),
                    ("audio", "Audio"),
                    ("text", "Text note"),
                    ("other", "Other"),
                ],
                db_index=True,
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="visitattachment",
            name="employee",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="visit_attachments",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name="visitattachment",
            name="file",
            field=models.FileField(
                blank=True, null=True, upload_to="visit_attachments/%Y/%m/"
            ),
        ),
        migrations.RemoveField(
            model_name="visitattachment",
            name="file_type",
        ),
    ]
