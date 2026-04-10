from django.contrib import admin
from masters.models import (
    Farmer,
    FarmerField,
    FieldCrop,
    CropIssue,
    Recommendation,
    FarmerActivity,
)


class FarmerFieldInline(admin.TabularInline):
    model = FarmerField
    extra = 0
    show_change_link = True


class FieldCropInline(admin.TabularInline):
    model = FieldCrop
    extra = 0


class RecommendationInline(admin.TabularInline):
    model = Recommendation
    extra = 0


@admin.register(FarmerField)
class FarmerFieldAdmin(admin.ModelAdmin):
    list_display = ("id", "farmer", "land_name", "land_size", "soil_type")
    list_filter = ("soil_type", "irrigation_type")
    search_fields = ("land_name", "farmer__name")
    inlines = [FieldCropInline]


@admin.register(FieldCrop)
class FieldCropAdmin(admin.ModelAdmin):
    list_display = ("id", "land", "crop_name", "crop_stage", "sowing_date")
    search_fields = ("land__land_name", "crop_name")


@admin.register(CropIssue)
class CropIssueAdmin(admin.ModelAdmin):
    list_display = ("id", "visit", "crop", "severity", "created_at")
    list_filter = ("severity",)
    search_fields = ("description",)
    inlines = [RecommendationInline]


@admin.register(Recommendation)
class RecommendationAdmin(admin.ModelAdmin):
    list_display = ("id", "issue", "fertilizer", "pesticide", "dosage")
    search_fields = ("fertilizer", "pesticide")


@admin.register(FarmerActivity)
class FarmerActivityAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "farmer",
        "activity_type",
        "reference_id",
        "created_by",
        "created_at",
    )
    list_filter = ("activity_type",)
    search_fields = ("farmer__name", "farmer__farmer_code", "notes")
    raw_id_fields = ("farmer", "created_by")
