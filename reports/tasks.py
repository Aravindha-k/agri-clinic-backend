"""
reports/tasks.py
─────────────────
Celery tasks for background report generation and PDF building.
"""

from __future__ import annotations

import io
import logging
from datetime import date, timedelta
from typing import Any, Dict, Optional

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# Public task: request a report
# ──────────────────────────────────────────────────────────────


@shared_task(bind=True, max_retries=2, default_retry_delay=30)
def generate_report(self, report_id: int) -> None:
    """
    Entry-point task.  Looks up the Report record, routes to the
    correct builder, saves the file, and marks the report done.
    """
    from reports.models import Report

    try:
        report = Report.objects.get(pk=report_id)
    except Report.DoesNotExist:
        logger.error("generate_report: Report %s not found", report_id)
        return

    report.status = Report.STATUS_PROCESSING
    report.save(update_fields=["status"])

    try:
        buffer = _build_pdf(report)
        _save_report_file(report, buffer)
        report.status = Report.STATUS_DONE
        report.completed_at = timezone.now()
        report.save(update_fields=["status", "completed_at", "file", "file_url"])
        logger.info("Report %s generated successfully", report_id)
    except Exception as exc:
        report.status = Report.STATUS_FAILED
        report.error_message = str(exc)
        report.save(update_fields=["status", "error_message"])
        logger.exception("Report %s generation failed", report_id)
        raise self.retry(exc=exc)


# ──────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────


def _build_pdf(report) -> io.BytesIO:
    """
    Build a PDF using reportlab and return a BytesIO buffer.
    Falls back to a plain text stub if reportlab is not installed.
    """
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.platypus import (
            SimpleDocTemplate,
            Paragraph,
            Spacer,
            Table,
            TableStyle,
        )
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib import colors
    except ImportError:
        logger.warning("reportlab not installed – generating stub PDF")
        buf = io.BytesIO(b"%PDF-1.4 stub")
        buf.seek(0)
        return buf

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    styles = getSampleStyleSheet()
    story = []

    # Title
    story.append(
        Paragraph(f"Agri Clinic – {report.get_report_type_display()}", styles["Title"])
    )
    story.append(Spacer(1, 12))
    story.append(
        Paragraph(f"Generated: {timezone.now():%Y-%m-%d %H:%M}", styles["Normal"])
    )
    story.append(Spacer(1, 12))

    # Route to content builder
    rows = _get_report_rows(report)
    if rows:
        table = Table(rows)
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2d7a3a")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    (
                        "ROWBACKGROUNDS",
                        (0, 1),
                        (-1, -1),
                        [colors.white, colors.HexColor("#f0f7f0")],
                    ),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                ]
            )
        )
        story.append(table)

    doc.build(story)
    buffer.seek(0)
    return buffer


def _get_report_rows(report) -> list:
    """Route to the correct data fetcher based on report_type."""
    params = report.parameters or {}

    if report.report_type == "employee_performance":
        from visits.selectors import get_employee_performance

        date_from = _parse_date(
            params.get("date_from"), date.today() - timedelta(days=30)
        )
        date_to = _parse_date(params.get("date_to"), date.today())
        qs = get_employee_performance(date_from=date_from, date_to=date_to)
        headers = ["Employee", "Employee ID", "Visits"]
        rows = [headers] + [
            [
                r["employee__username"],
                r.get("employee__employee_profile__employee_id", ""),
                r["visit_count"],
            ]
            for r in qs
        ]
        return rows

    elif report.report_type in ("daily_summary", "visit_summary", "monthly_summary"):
        from visits.selectors import get_visit_trends

        date_from = _parse_date(
            params.get("date_from"), date.today() - timedelta(days=30)
        )
        date_to = _parse_date(params.get("date_to"), date.today())
        qs = get_visit_trends(date_from=date_from, date_to=date_to)
        headers = ["Date", "Total Visits"]
        rows = [headers] + [[str(r["visit_date"]), r["count"]] for r in qs]
        return rows

    elif report.report_type == "village_summary":
        from dashboard.selectors import get_village_heatmap

        data = get_village_heatmap(top_n=50)
        headers = ["Village", "Total Visits"]
        rows = [headers] + [[r["village__name"], r["count"]] for r in data]
        return rows

    return []


def _save_report_file(report, buffer: io.BytesIO) -> None:
    """Save the PDF buffer as a Django FileField (works with S3 and local)."""
    from django.core.files.base import ContentFile

    filename = (
        f"report_{report.pk}_{report.report_type}_{timezone.now():%Y%m%d_%H%M%S}.pdf"
    )
    report.file.save(filename, ContentFile(buffer.read()), save=False)

    # Derive a public URL
    try:
        report.file_url = report.file.url
    except Exception:
        report.file_url = ""


def _parse_date(value: Optional[str], default: date) -> date:
    if not value:
        return default
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        return default


# ──────────────────────────────────────────────────────────────
# Utility callable (used by visits/tasks.py)
# ──────────────────────────────────────────────────────────────


def build_and_store_pdf(
    *, report_type: str, object_id: int, requested_by_user_id: int
) -> None:
    """
    Create a Report record and enqueue a generation task.
    Called from other task modules to avoid circular imports.
    """
    from reports.models import Report

    report = Report.objects.create(
        report_type=report_type,
        requested_by_id=requested_by_user_id,
        parameters={"object_id": object_id},
        status=Report.STATUS_PENDING,
    )
    generate_report.delay(report.pk)
