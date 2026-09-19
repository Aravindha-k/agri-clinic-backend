"""
Operational Village + EmployeeLocationAssignment Excel import service.

Used by:
- management command `import_operational_villages`
- Admin API validate / confirm endpoints

Village-only. Never creates District/Taluk/Firka.
Default planning path is read-only; writes happen only via execute_plan.
"""

from __future__ import annotations

import hashlib
import secrets
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO

from django.core.cache import cache
from django.db import transaction
from openpyxl import load_workbook

from accounts.models import EmployeeLocationAssignment, EmployeeProfile
from masters.location_utils import normalize_village_name
from masters.models import Village

# ---------------------------------------------------------------------------
# Limits / constants
# ---------------------------------------------------------------------------

MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MiB
MAX_EXCEL_ROWS = 10_000
IMPORT_TOKEN_TTL_SECONDS = 30 * 60
IMPORT_CACHE_PREFIX = "village_import_plan:v1:"
ALLOWED_EXTENSIONS = (".xlsx",)

VILLAGE_HEADERS = {
    "village",
    "village name",
    "name",
}
TAMIL_HEADERS = {
    "village tamil name",
    "tamil name",
    "tamil_name",
    "name_ta",
    "village name ta",
    "tamil",
}
EMPLOYEE_ID_HEADERS = {
    "employee id",
    "employee_id",
    "emp id",
    "emp_id",
    "staff id",
    "staff_id",
}
EMPLOYEE_NAME_HEADERS = {
    "employee name",
    "employee",
    "field staff",
    "fieldstaff",
    "field_staff",
    "staff",
    "staff name",
}
IGNORED_HEADERS = {
    "s no",
    "s.no",
    "s. no",
    "sno",
    "sl no",
    "sl.no",
    "firka",
    "taluk",
    "district",
}


class VillageImportError(ValueError):
    """Blocking import / validation failure with a stable code."""

    def __init__(self, message: str, *, code: str = "IMPORT_ERROR"):
        super().__init__(message)
        self.code = code


def _norm_header(value: object) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _cell_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def normalize_person_name(name: str) -> str:
    return " ".join((name or "").strip().split()).casefold()


def normalize_employee_id(value: str) -> str:
    return " ".join((value or "").strip().split()).upper()


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class TamilConflict:
    village_key: str
    display_name: str
    tamil_values: list[str]
    excel_rows: list[int]
    affected_employees: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "village": self.display_name,
            "village_key": self.village_key,
            "tamil_values": self.tamil_values,
            "excel_rows": self.excel_rows,
            "affected_employees": self.affected_employees,
        }


@dataclass
class RowResult:
    excel_row: int
    village: str = ""
    village_tamil_name: str = ""
    employee_id: str = ""
    employee_name: str = ""
    status: str = "ok"  # ok | warning | error | skipped
    matched_employee_pk: int | None = None
    matched_employee_id: str = ""
    messages: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "excel_row": self.excel_row,
            "village": self.village,
            "village_tamil_name": self.village_tamil_name,
            "employee_id": self.employee_id,
            "employee_name": self.employee_name,
            "status": self.status,
            "matched_employee_pk": self.matched_employee_pk,
            "matched_employee_id": self.matched_employee_id,
            "messages": self.messages,
        }


@dataclass
class ImportPlan:
    total_rows: int = 0
    valid_rows: int = 0
    unique_villages: int = 0
    villages_to_create: int = 0
    villages_existing: int = 0
    tamil_names_present: int = 0
    tamil_names_blank: int = 0
    tamil_name_conflicts: list[TamilConflict] = field(default_factory=list)
    skipped_conflicted_villages: int = 0
    skipped_conflicted_rows: int = 0
    skipped_conflicted_assignments: int = 0
    employees_matched: list[str] = field(default_factory=list)
    employees_not_found: list[str] = field(default_factory=list)
    ambiguous_employees: list[str] = field(default_factory=list)
    assignments_to_create: int = 0
    assignments_existing: int = 0
    shared_villages: dict[str, list[str]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    row_results: list[RowResult] = field(default_factory=list)
    blank_tamil_villages: list[str] = field(default_factory=list)
    # Execute payloads
    village_create: dict[str, dict[str, str]] = field(default_factory=dict)
    village_update_ta: dict[str, str] = field(default_factory=dict)
    village_reactivate: list[str] = field(default_factory=list)
    assignment_keys: list[tuple[int, str]] = field(default_factory=list)
    blocking_errors: list[str] = field(default_factory=list)
    plan_fingerprint: str = ""

    @property
    def has_blocking_errors(self) -> bool:
        return bool(self.blocking_errors)

    @property
    def eligible_villages(self) -> int:
        return self.villages_to_create + self.villages_existing

    def preview_dict(self) -> dict[str, Any]:
        return {
            "total_rows": self.total_rows,
            "valid_rows": self.valid_rows,
            "unique_villages": self.unique_villages,
            "eligible_villages": self.eligible_villages,
            "villages_to_create": self.villages_to_create,
            "villages_existing": self.villages_existing,
            "tamil_names_present": self.tamil_names_present,
            "tamil_names_blank": self.tamil_names_blank,
            "tamil_name_conflicts": [c.as_dict() for c in self.tamil_name_conflicts],
            "skipped_conflicted_villages": self.skipped_conflicted_villages,
            "skipped_conflicted_rows": self.skipped_conflicted_rows,
            "skipped_conflicted_assignments": self.skipped_conflicted_assignments,
            "employees_matched": self.employees_matched,
            "employees_not_found": self.employees_not_found,
            "ambiguous_employees": self.ambiguous_employees,
            "assignments_to_create": self.assignments_to_create,
            "assignments_existing": self.assignments_existing,
            "shared_villages": [
                {"village": name, "employees": staff}
                for name, staff in sorted(
                    self.shared_villages.items(), key=lambda x: x[0].casefold()
                )
            ],
            "warnings": self.warnings,
            "errors": self.errors,
            "blocking_errors": self.blocking_errors,
            "skippable_errors": (
                ["TAMIL_NAME_CONFLICT"] if self.tamil_name_conflicts else []
            ),
            "blank_tamil_villages": self.blank_tamil_villages,
            "row_results": [r.as_dict() for r in self.row_results],
            "can_confirm": not self.has_blocking_errors,
        }

    def skip_summary_dict(self) -> dict[str, Any]:
        return {
            "skipped_conflicted_villages": self.skipped_conflicted_villages,
            "skipped_conflicted_rows": self.skipped_conflicted_rows,
            "skipped_conflicted_assignments": self.skipped_conflicted_assignments,
            "tamil_name_conflicts": [c.as_dict() for c in self.tamil_name_conflicts],
        }

    def to_cache_payload(self) -> dict[str, Any]:
        return {
            "fingerprint": self.plan_fingerprint,
            "village_create": self.village_create,
            "village_update_ta": self.village_update_ta,
            "village_reactivate": self.village_reactivate,
            "assignment_keys": [
                [emp_pk, vkey] for emp_pk, vkey in self.assignment_keys
            ],
            "blocking_errors": list(self.blocking_errors),
            "skip_summary": self.skip_summary_dict(),
            "preview": {
                "total_rows": self.total_rows,
                "valid_rows": self.valid_rows,
                "unique_villages": self.unique_villages,
                "villages_to_create": self.villages_to_create,
                "villages_existing": self.villages_existing,
                "assignments_to_create": self.assignments_to_create,
                "assignments_existing": self.assignments_existing,
                "skipped_conflicted_villages": self.skipped_conflicted_villages,
                "skipped_conflicted_rows": self.skipped_conflicted_rows,
                "skipped_conflicted_assignments": self.skipped_conflicted_assignments,
            },
        }

    @classmethod
    def from_cache_payload(cls, payload: dict[str, Any]) -> "ImportPlan":
        plan = cls()
        plan.plan_fingerprint = payload.get("fingerprint") or ""
        plan.village_create = dict(payload.get("village_create") or {})
        plan.village_update_ta = dict(payload.get("village_update_ta") or {})
        plan.village_reactivate = list(payload.get("village_reactivate") or [])
        plan.assignment_keys = [
            (int(emp_pk), str(vkey))
            for emp_pk, vkey in (payload.get("assignment_keys") or [])
        ]
        plan.blocking_errors = list(payload.get("blocking_errors") or [])
        preview = payload.get("preview") or {}
        plan.total_rows = int(preview.get("total_rows") or 0)
        plan.valid_rows = int(preview.get("valid_rows") or 0)
        plan.unique_villages = int(preview.get("unique_villages") or 0)
        plan.villages_to_create = int(preview.get("villages_to_create") or 0)
        plan.villages_existing = int(preview.get("villages_existing") or 0)
        plan.assignments_to_create = int(preview.get("assignments_to_create") or 0)
        plan.assignments_existing = int(preview.get("assignments_existing") or 0)
        plan.skipped_conflicted_villages = int(
            preview.get("skipped_conflicted_villages") or 0
        )
        plan.skipped_conflicted_rows = int(preview.get("skipped_conflicted_rows") or 0)
        plan.skipped_conflicted_assignments = int(
            preview.get("skipped_conflicted_assignments") or 0
        )
        skip = payload.get("skip_summary") or {}
        plan.tamil_name_conflicts = [
            TamilConflict(
                village_key=item.get("village_key") or "",
                display_name=item.get("village") or "",
                tamil_values=list(item.get("tamil_values") or []),
                excel_rows=list(item.get("excel_rows") or []),
                affected_employees=list(item.get("affected_employees") or []),
            )
            for item in (skip.get("tamil_name_conflicts") or [])
        ]
        return plan


# ---------------------------------------------------------------------------
# Employee matching
# ---------------------------------------------------------------------------


def _employee_name_keys(profile: EmployeeProfile) -> set[str]:
    user = profile.user
    keys: set[str] = set()
    for raw in (
        user.first_name,
        user.last_name,
        user.get_full_name(),
        user.username,
    ):
        key = normalize_person_name(raw or "")
        if key:
            keys.add(key)
    full = normalize_person_name(user.get_full_name() or "")
    if " " in full:
        keys.add(full.split(" ", 1)[0])
    return keys


def build_employee_indexes() -> tuple[
    dict[str, EmployeeProfile], dict[str, list[EmployeeProfile]]
]:
    by_id: dict[str, EmployeeProfile] = {}
    by_name: dict[str, list[EmployeeProfile]] = defaultdict(list)
    seen_name_pk: dict[str, set[int]] = defaultdict(set)
    for profile in EmployeeProfile.objects.select_related("user").all():
        code = normalize_employee_id(profile.employee_id)
        if code:
            by_id[code] = profile
        for key in _employee_name_keys(profile):
            if profile.pk in seen_name_pk[key]:
                continue
            seen_name_pk[key].add(profile.pk)
            by_name[key].append(profile)
    return by_id, by_name


def _display_employee(profile: EmployeeProfile) -> str:
    name = (profile.user.get_full_name() or profile.user.first_name or "").strip()
    if name:
        return f"{profile.employee_id} ({name})"
    return profile.employee_id


# ---------------------------------------------------------------------------
# Workbook parsing
# ---------------------------------------------------------------------------


def _resolve_columns(
    header_row,
) -> tuple[int | None, int | None, int | None, int | None]:
    village_idx = None
    tamil_idx = None
    emp_id_idx = None
    emp_name_idx = None
    for index, header in enumerate(header_row):
        key = _norm_header(header)
        if key in IGNORED_HEADERS:
            continue
        if village_idx is None and key in VILLAGE_HEADERS:
            village_idx = index
        elif tamil_idx is None and key in TAMIL_HEADERS:
            tamil_idx = index
        elif emp_id_idx is None and key in EMPLOYEE_ID_HEADERS:
            emp_id_idx = index
        elif emp_name_idx is None and key in EMPLOYEE_NAME_HEADERS:
            emp_name_idx = index
    return village_idx, tamil_idx, emp_id_idx, emp_name_idx


def _open_workbook(source: Path | BinaryIO | str):
    if isinstance(source, (str, Path)):
        path = Path(source)
        if not path.exists():
            raise VillageImportError(f"File not found: {path}", code="FILE_NOT_FOUND")
        return load_workbook(path, read_only=True, data_only=True)
    return load_workbook(source, read_only=True, data_only=True)


def validate_upload_file(upload) -> None:
    """Validate an uploaded Django UploadedFile (or file-like with .name/.size)."""
    if upload is None:
        raise VillageImportError(
            "Excel file is required.",
            code="FILE_REQUIRED",
        )
    name = getattr(upload, "name", "") or ""
    lower = name.lower()
    if not lower.endswith(ALLOWED_EXTENSIONS):
        raise VillageImportError(
            "Invalid file type. Only .xlsx files are supported.",
            code="INVALID_EXTENSION",
        )
    size = getattr(upload, "size", None)
    if size is not None and size > MAX_UPLOAD_BYTES:
        raise VillageImportError(
            f"File too large. Maximum size is {MAX_UPLOAD_BYTES // (1024 * 1024)} MiB.",
            code="FILE_TOO_LARGE",
        )


def collect_plan(source: Path | BinaryIO | str) -> ImportPlan:
    """
    Parse workbook and build an ImportPlan. Read-only against DB for lookups.
    Wrapped in a rollback-only transaction so accidental writes cannot persist.
    """
    with transaction.atomic():
        plan = _build_plan(source)
        transaction.set_rollback(True)
        return plan


def _build_plan(source: Path | BinaryIO | str) -> ImportPlan:
    plan = ImportPlan()
    try:
        workbook = _open_workbook(source)
    except VillageImportError:
        raise
    except Exception as exc:
        raise VillageImportError(
            f"Malformed or unreadable workbook: {exc}",
            code="MALFORMED_WORKBOOK",
        ) from exc

    try:
        sheet = workbook.active
        rows_iter = sheet.iter_rows(values_only=True)
        try:
            header_row = next(rows_iter)
        except StopIteration as exc:
            raise VillageImportError("Workbook is empty.", code="EMPTY_WORKBOOK") from exc

        village_idx, tamil_idx, emp_id_idx, emp_name_idx = _resolve_columns(header_row)
        if village_idx is None:
            raise VillageImportError(
                "Required column 'Village' was not found.",
                code="MISSING_HEADERS",
            )

        village_db: dict[str, Village] = {}
        for village in Village.objects.only("id", "name", "name_ta", "is_active"):
            village_db.setdefault(normalize_village_name(village.name), village)

        existing_assignments: set[tuple[int, str]] = set()
        for row in (
            EmployeeLocationAssignment.objects.filter(
                is_operational=True, village__isnull=False
            )
            .select_related("village")
            .only("employee_id", "village__name")
        ):
            existing_assignments.add(
                (
                    row.employee_id,
                    normalize_village_name(row.village.name),
                )
            )

        by_id, by_name = build_employee_indexes()

        village_meta: dict[str, dict] = {}
        # Unique assignment pairs from valid rows: (emp_pk, vkey) -> label
        assignment_labels: dict[tuple[int, str], str] = {}
        staff_labels_by_village: dict[str, set[str]] = defaultdict(set)
        matched_labels: set[str] = set()
        not_found_labels: set[str] = set()
        ambiguous_labels: set[str] = set()

        excel_row_num = 1
        data_row_count = 0
        for row in rows_iter:
            excel_row_num += 1
            if excel_row_num - 1 > MAX_EXCEL_ROWS:
                raise VillageImportError(
                    f"Too many rows. Maximum is {MAX_EXCEL_ROWS}.",
                    code="TOO_MANY_ROWS",
                )
            if not row:
                continue

            def _col(idx: int | None) -> str:
                if idx is None or idx >= len(row):
                    return ""
                return _cell_text(row[idx])

            village_name = _col(village_idx)
            tamil = _col(tamil_idx)
            emp_id_raw = _col(emp_id_idx)
            emp_name_raw = _col(emp_name_idx)

            if not village_name and not tamil and not emp_id_raw and not emp_name_raw:
                continue

            data_row_count += 1
            result = RowResult(
                excel_row=excel_row_num,
                village=village_name,
                village_tamil_name=tamil,
                employee_id=emp_id_raw,
                employee_name=emp_name_raw,
            )

            if not village_name:
                result.status = "error"
                result.messages.append("INVALID_MISSING_VILLAGE")
                plan.errors.append(
                    f"Excel row {excel_row_num}: INVALID_MISSING_VILLAGE "
                    f"(employee_id={emp_id_raw!r}, employee_name={emp_name_raw!r})"
                )
                plan.row_results.append(result)
                continue

            plan.valid_rows += 1
            vkey = normalize_village_name(village_name)
            meta = village_meta.setdefault(
                vkey,
                {
                    "display_name": village_name,
                    "tamils": set(),
                    "tamil_rows": defaultdict(list),
                    "rows": [],
                },
            )
            meta["rows"].append(excel_row_num)
            if tamil:
                meta["tamils"].add(tamil)
                meta["tamil_rows"][tamil].append(excel_row_num)

            # ---- employee resolution ----
            profile: EmployeeProfile | None = None
            if not emp_id_raw and not emp_name_raw:
                result.status = "ok"
                result.messages.append("VILLAGE_ONLY")
                plan.row_results.append(result)
                continue

            if emp_id_raw:
                code = normalize_employee_id(emp_id_raw)
                profile = by_id.get(code)
                if profile is None:
                    result.status = "error"
                    result.messages.append("EMPLOYEE_NOT_FOUND")
                    not_found_labels.add(emp_id_raw)
                    plan.errors.append(
                        f"Excel row {excel_row_num}: EMPLOYEE_NOT_FOUND "
                        f"employee_id={emp_id_raw!r}"
                    )
                    plan.row_results.append(result)
                    continue
                if emp_name_raw:
                    name_key = normalize_person_name(emp_name_raw)
                    profile_keys = _employee_name_keys(profile)
                    if name_key and name_key not in profile_keys:
                        # Also accept exact full-name / first-name containment via
                        # normalized equality only (already checked). Mismatch.
                        result.status = "error"
                        result.messages.append("EMPLOYEE_MISMATCH")
                        plan.errors.append(
                            f"Excel row {excel_row_num}: EMPLOYEE_MISMATCH "
                            f"employee_id={emp_id_raw!r} employee_name={emp_name_raw!r} "
                            f"resolves_to={_display_employee(profile)}"
                        )
                        plan.row_results.append(result)
                        continue
            else:
                # Name-only matching
                name_key = normalize_person_name(emp_name_raw)
                candidates = by_name.get(name_key, [])
                if len(candidates) == 0:
                    result.status = "error"
                    result.messages.append("EMPLOYEE_NOT_FOUND")
                    not_found_labels.add(emp_name_raw)
                    plan.errors.append(
                        f"Excel row {excel_row_num}: EMPLOYEE_NOT_FOUND "
                        f"employee_name={emp_name_raw!r}"
                    )
                    plan.row_results.append(result)
                    continue
                if len(candidates) > 1:
                    result.status = "error"
                    result.messages.append("AMBIGUOUS_EMPLOYEE")
                    ambiguous_labels.add(emp_name_raw)
                    ids = ", ".join(c.employee_id for c in candidates)
                    plan.errors.append(
                        f"Excel row {excel_row_num}: AMBIGUOUS_EMPLOYEE "
                        f"employee_name={emp_name_raw!r} candidates=[{ids}]"
                    )
                    plan.row_results.append(result)
                    continue
                profile = candidates[0]
                warn = (
                    f"Excel row {excel_row_num}: name-based employee match used "
                    f"for {emp_name_raw!r} -> {profile.employee_id}"
                )
                plan.warnings.append(warn)
                result.status = "warning"
                result.messages.append("NAME_BASED_MATCH")

            assert profile is not None
            label = _display_employee(profile)
            matched_labels.add(label)
            result.matched_employee_pk = profile.pk
            result.matched_employee_id = profile.employee_id
            pair = (profile.pk, vkey)
            assignment_labels[pair] = label
            staff_labels_by_village[vkey].add(label)
            if result.status == "ok":
                result.status = "ok"
            plan.row_results.append(result)

        plan.total_rows = data_row_count
        plan.employees_matched = sorted(matched_labels, key=str.casefold)
        plan.employees_not_found = sorted(not_found_labels, key=str.casefold)
        plan.ambiguous_employees = sorted(ambiguous_labels, key=str.casefold)

        # Village aggregation + Tamil conflicts (conflicts skip that village only)
        conflicted_keys: set[str] = set()
        for vkey, meta in village_meta.items():
            plan.unique_villages += 1
            tamils = sorted(meta["tamils"])
            chosen_ta = ""
            conflict: TamilConflict | None = None

            if len(tamils) > 1:
                conflict_rows: list[int] = []
                for ta in tamils:
                    conflict_rows.extend(meta["tamil_rows"].get(ta, []))
                conflict = TamilConflict(
                    village_key=vkey,
                    display_name=meta["display_name"],
                    tamil_values=tamils,
                    excel_rows=sorted(set(conflict_rows)),
                )
            elif len(tamils) == 1:
                plan.tamil_names_present += 1
                chosen_ta = tamils[0]
            else:
                plan.tamil_names_blank += 1
                plan.blank_tamil_villages.append(meta["display_name"])

            existing = village_db.get(vkey)
            if (
                conflict is None
                and existing
                and chosen_ta
                and (existing.name_ta or "").strip()
                and normalize_person_name(existing.name_ta)
                != normalize_person_name(chosen_ta)
            ):
                conflict = TamilConflict(
                    village_key=vkey,
                    display_name=meta["display_name"],
                    tamil_values=sorted(
                        {
                            (existing.name_ta or "").strip(),
                            chosen_ta,
                        }
                    ),
                    excel_rows=list(meta["rows"]),
                )

            if conflict is not None:
                conflict.affected_employees = sorted(
                    staff_labels_by_village.get(vkey, set()), key=str.casefold
                )
                plan.tamil_name_conflicts.append(conflict)
                conflicted_keys.add(vkey)
                plan.warnings.append(
                    "TAMIL_NAME_CONFLICT skipped village "
                    f"{conflict.display_name!r} values={conflict.tamil_values} "
                    f"rows={conflict.excel_rows}"
                )
                continue

            if existing:
                plan.villages_existing += 1
                if not existing.is_active:
                    plan.village_reactivate.append(vkey)
                if chosen_ta and not (existing.name_ta or "").strip():
                    plan.village_update_ta[vkey] = chosen_ta
            else:
                plan.villages_to_create += 1
                plan.village_create[vkey] = {
                    "name": meta["display_name"],
                    "name_ta": chosen_ta,
                }

            labels = sorted(staff_labels_by_village.get(vkey, set()), key=str.casefold)
            if len(labels) > 1:
                plan.shared_villages[meta["display_name"]] = labels

        plan.skipped_conflicted_villages = len(conflicted_keys)
        plan.skipped_conflicted_rows = sum(
            len(village_meta[vkey]["rows"]) for vkey in conflicted_keys
        )

        conflicted_row_nums: set[int] = set()
        for vkey in conflicted_keys:
            conflicted_row_nums.update(village_meta[vkey]["rows"])
        for result in plan.row_results:
            if result.excel_row in conflicted_row_nums and result.status != "error":
                result.status = "skipped"
                if "TAMIL_NAME_CONFLICT" not in result.messages:
                    result.messages.append("TAMIL_NAME_CONFLICT")

        for pair, _label in assignment_labels.items():
            _emp_pk, vkey = pair
            if vkey in conflicted_keys:
                plan.skipped_conflicted_assignments += 1
                continue
            if pair in existing_assignments:
                plan.assignments_existing += 1
            else:
                plan.assignments_to_create += 1
                plan.assignment_keys.append(pair)

        if plan.employees_not_found:
            plan.blocking_errors.append("EMPLOYEE_NOT_FOUND")
        if plan.ambiguous_employees:
            plan.blocking_errors.append("AMBIGUOUS_EMPLOYEE")
        if any("EMPLOYEE_MISMATCH" in e for e in plan.errors):
            plan.blocking_errors.append("EMPLOYEE_MISMATCH")
        # TAMIL_NAME_CONFLICT is skippable: conflicted villages are excluded from
        # the executable plan and do not block confirm of remaining rows.

        plan.plan_fingerprint = _fingerprint_plan(plan)
        return plan
    finally:
        workbook.close()


def _fingerprint_plan(plan: ImportPlan) -> str:
    raw = repr(
        (
            sorted(plan.village_create.items()),
            sorted(plan.village_update_ta.items()),
            sorted(plan.village_reactivate),
            sorted(plan.assignment_keys),
            sorted(plan.blocking_errors),
        )
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Execute
# ---------------------------------------------------------------------------


def execute_plan(plan: ImportPlan) -> dict[str, int]:
    if plan.has_blocking_errors:
        raise VillageImportError(
            "Refusing execute due to blocking errors: "
            + ", ".join(plan.blocking_errors),
            code="BLOCKING_ERRORS",
        )

    created_villages = 0
    updated_villages = 0
    created_assignments = 0
    reused_assignments = 0

    with transaction.atomic():
        village_by_key: dict[str, Village] = {}
        for village in Village.objects.all():
            village_by_key.setdefault(normalize_village_name(village.name), village)

        existing_keys_before = set(village_by_key.keys())

        for vkey, payload in plan.village_create.items():
            if vkey in village_by_key:
                continue
            village = Village.objects.create(
                name=payload["name"],
                name_ta=payload.get("name_ta") or "",
                is_active=True,
                district=None,
                taluk=None,
            )
            village_by_key[vkey] = village
            created_villages += 1

        for vkey in plan.village_reactivate:
            village = village_by_key.get(vkey)
            if village is None:
                continue
            if not village.is_active:
                village.is_active = True
                village.save(update_fields=["is_active", "updated_at"])
                updated_villages += 1

        for vkey, tamil in plan.village_update_ta.items():
            village = village_by_key.get(vkey)
            if village is None:
                continue
            if not (village.name_ta or "").strip() and tamil:
                village.name_ta = tamil
                village.is_active = True
                village.save(update_fields=["name_ta", "is_active", "updated_at"])
                updated_villages += 1

        touched_existing = {
            vkey
            for vkey in (
                set(plan.village_update_ta)
                | set(plan.village_reactivate)
                | {k for _, k in plan.assignment_keys}
                | set(plan.village_create)
            )
            if vkey in existing_keys_before
        }
        reused_villages = len(touched_existing)

        for emp_pk, vkey in plan.assignment_keys:
            village = village_by_key.get(vkey)
            if village is None:
                raise VillageImportError(
                    f"Missing village for assignment key {vkey}",
                    code="MISSING_VILLAGE",
                )
            obj = (
                EmployeeLocationAssignment.objects.filter(
                    employee_id=emp_pk,
                    village=village,
                    is_operational=True,
                )
                .order_by("id")
                .first()
            )
            if obj is None:
                EmployeeLocationAssignment.objects.create(
                    employee_id=emp_pk,
                    village=village,
                    district=None,
                    taluk=None,
                    is_active=True,
                    is_operational=True,
                )
                created_assignments += 1
            else:
                reused_assignments += 1
                changed = False
                if obj.district_id is not None:
                    obj.district = None
                    changed = True
                if obj.taluk_id is not None:
                    obj.taluk = None
                    changed = True
                if not obj.is_active:
                    obj.is_active = True
                    changed = True
                if changed:
                    obj.save(
                        update_fields=[
                            "district",
                            "taluk",
                            "is_active",
                            "updated_at",
                        ]
                    )

    return {
        "villages_created": created_villages,
        "villages_updated": updated_villages,
        "villages_reused": reused_villages,
        "assignments_created": created_assignments,
        "assignments_reused": reused_assignments,
        "rows_processed": plan.valid_rows - plan.skipped_conflicted_rows,
        "skipped_conflicted_villages": plan.skipped_conflicted_villages,
        "skipped_conflicted_rows": plan.skipped_conflicted_rows,
        "skipped_conflicted_assignments": plan.skipped_conflicted_assignments,
        "tamil_name_conflicts": [c.as_dict() for c in plan.tamil_name_conflicts],
    }


# ---------------------------------------------------------------------------
# Import token (validate → confirm)
# ---------------------------------------------------------------------------


def store_import_plan(*, plan: ImportPlan, user_id: int) -> str:
    if plan.has_blocking_errors:
        raise VillageImportError(
            "Cannot create import token while blocking errors exist: "
            + ", ".join(plan.blocking_errors),
            code="BLOCKING_ERRORS",
        )
    token = secrets.token_urlsafe(32)
    cache.set(
        f"{IMPORT_CACHE_PREFIX}{token}",
        {
            "user_id": int(user_id),
            "consumed": False,
            "plan": plan.to_cache_payload(),
        },
        timeout=IMPORT_TOKEN_TTL_SECONDS,
    )
    return token


def load_and_consume_import_plan(*, token: str, user_id: int) -> ImportPlan:
    if not token or not str(token).strip():
        raise VillageImportError("import_token is required.", code="TOKEN_REQUIRED")
    key = f"{IMPORT_CACHE_PREFIX}{token.strip()}"
    payload = cache.get(key)
    if not payload:
        raise VillageImportError(
            "Import token is invalid or expired.",
            code="TOKEN_INVALID",
        )
    if int(payload.get("user_id") or 0) != int(user_id):
        raise VillageImportError(
            "Import token does not belong to this user.",
            code="TOKEN_FORBIDDEN",
        )
    if payload.get("consumed"):
        raise VillageImportError(
            "Import token was already used.",
            code="TOKEN_REPLAY",
        )
    # Consume before execute to prevent concurrent double-confirm.
    payload["consumed"] = True
    cache.set(key, payload, timeout=IMPORT_TOKEN_TTL_SECONDS)
    plan = ImportPlan.from_cache_payload(payload["plan"])
    if plan.has_blocking_errors:
        raise VillageImportError(
            "Stored plan has blocking errors.",
            code="BLOCKING_ERRORS",
        )
    return plan


def discard_import_token(token: str) -> None:
    if token:
        cache.delete(f"{IMPORT_CACHE_PREFIX}{token.strip()}")


# ---------------------------------------------------------------------------
# CLI report formatting
# ---------------------------------------------------------------------------


def format_plan(plan: ImportPlan, *, dry_run: bool) -> str:
    lines: list[str] = []
    if dry_run:
        lines.append("DRY RUN — no rows will be written.")
    else:
        lines.append("EXECUTE — writing villages + assignments.")
    lines.append("")
    preview = plan.preview_dict()
    for key in (
        "total_rows",
        "valid_rows",
        "unique_villages",
        "villages_to_create",
        "villages_existing",
        "tamil_names_present",
        "tamil_names_blank",
        "assignments_to_create",
        "assignments_existing",
    ):
        lines.append(f"{key}: {preview[key]}")
    lines.append(f"tamil_name_conflicts: {len(plan.tamil_name_conflicts)}")
    for c in plan.tamil_name_conflicts:
        lines.append(
            f"  TAMIL_NAME_CONFLICT (skipped): {c.display_name} | "
            f"values={c.tamil_values} | rows={c.excel_rows} | "
            f"employees={c.affected_employees}"
        )
    lines.append(f"skipped_conflicted_villages: {plan.skipped_conflicted_villages}")
    lines.append(f"skipped_conflicted_rows: {plan.skipped_conflicted_rows}")
    lines.append(
        f"skipped_conflicted_assignments: {plan.skipped_conflicted_assignments}"
    )
    lines.append(f"eligible_villages: {plan.eligible_villages}")
    lines.append(f"employees_matched: {plan.employees_matched or 'none'}")
    lines.append(f"employees_not_found: {plan.employees_not_found or 'none'}")
    lines.append(f"ambiguous_employees: {plan.ambiguous_employees or 'none'}")
    lines.append(f"shared_villages: {len(plan.shared_villages)}")
    for vname, staff in sorted(plan.shared_villages.items(), key=lambda x: x[0].casefold()):
        lines.append(f"  {vname}: {', '.join(staff)}")
    if plan.warnings:
        lines.append(f"warnings: {len(plan.warnings)}")
        for w in plan.warnings[:20]:
            lines.append(f"  - {w}")
    if plan.errors:
        lines.append(f"errors: {len(plan.errors)}")
        for e in plan.errors[:20]:
            lines.append(f"  - {e}")
    if plan.blocking_errors:
        lines.append("BLOCKING ERRORS: " + ", ".join(plan.blocking_errors))
    else:
        lines.append("BLOCKING ERRORS: none")
    if dry_run:
        lines.append("DRY RUN ZERO WRITES: YES")
    return "\n".join(lines)
