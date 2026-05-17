"""
Keep Visit rows and Farmer master records aligned after mobile/admin field work.
"""

from __future__ import annotations

from masters.models import Farmer, FarmerField
from visits.models import Visit


def sync_visit_farmer_master(visit: Visit) -> Visit:
    """
    - Ensure visit.farmer_id is set when name/phone match or a new master row is needed.
    - Copy snapshot fields between visit and Farmer so list/detail APIs agree.
    - Link or create FarmerField when visit has land_name but no field FK.
    """
    if not visit.pk:
        return visit

    employee = visit.employee
    phone = (visit.farmer_phone or "").strip()
    name = (visit.farmer_name or "").strip()
    farmer = visit.farmer

    if not farmer and phone:
        farmer = Farmer.objects.filter(phone=phone, is_active=True).order_by("id").first()
    if not farmer and name:
        farmer = (
            Farmer.objects.filter(name__iexact=name, is_active=True).order_by("id").first()
        )

    if not farmer and (phone or name):
        farmer = Farmer.objects.create(
            name=name or "Unknown",
            phone=phone or f"V{visit.pk}",
            district=visit.district,
            village=visit.village,
            created_by_employee=employee,
            assigned_employee=employee,
        )

    if not farmer:
        return visit

    visit_updates = {}
    master_updates = {}

    if visit.farmer_id != farmer.id:
        visit_updates["farmer_id"] = farmer.id

    if not visit.farmer_name and farmer.name:
        visit_updates["farmer_name"] = farmer.name
    elif name and visit.farmer_name != name:
        visit_updates["farmer_name"] = name
        if farmer.name != name:
            master_updates["name"] = name

    if not visit.farmer_phone and farmer.phone:
        visit_updates["farmer_phone"] = farmer.phone
    elif phone and visit.farmer_phone != phone:
        visit_updates["farmer_phone"] = phone
        if (
            farmer.phone != phone
            and not Farmer.objects.filter(phone=phone)
            .exclude(pk=farmer.pk)
            .exists()
        ):
            master_updates["phone"] = phone

    if visit.district_id and farmer.district_id != visit.district_id:
        master_updates["district_id"] = visit.district_id
    elif farmer.district_id and not visit.district_id:
        visit_updates["district_id"] = farmer.district_id

    if visit.village_id and farmer.village_id != visit.village_id:
        master_updates["village_id"] = visit.village_id
    elif farmer.village_id and not visit.village_id:
        visit_updates["village_id"] = farmer.village_id

    if master_updates:
        Farmer.objects.filter(pk=farmer.pk).update(**master_updates)

    field = visit.field
    land_name = (visit.land_name or "").strip()
    if field and field.farmer_id == farmer.id:
        if not visit.land_name and field.land_name:
            visit_updates["land_name"] = field.land_name
    elif land_name:
        matched_field = (
            FarmerField.objects.filter(
                farmer=farmer, land_name__iexact=land_name, is_active=True
            )
            .order_by("id")
            .first()
        )
        if matched_field:
            visit_updates["field_id"] = matched_field.id
            if visit.land_area is None and matched_field.land_size is not None:
                visit_updates["land_area"] = float(matched_field.land_size)
        elif not visit.field_id:
            new_field = FarmerField.objects.create(
                farmer=farmer,
                land_name=land_name,
                land_size=visit.land_area,
                created_by_employee=employee,
            )
            visit_updates["field_id"] = new_field.id

    if visit_updates:
        Visit.objects.filter(pk=visit.pk).update(**visit_updates)
        visit.refresh_from_db()

    return visit
