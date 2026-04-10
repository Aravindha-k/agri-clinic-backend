from django.contrib import admin
from .models import (
    District,
    Village,
    Crop,
    Farmer,
    FarmerField,
    FarmerActivity,
)


@admin.register(District)
class DistrictAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "is_active")
    search_fields = ("name",)
    list_filter = ("is_active",)


@admin.register(Village)
class VillageAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "district", "is_active")
    search_fields = ("name", "district__name")
    list_filter = ("district", "is_active")


@admin.register(Crop)
class CropAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name_en",
        "name_ta",
        "scientific_name",
        "crop_category",
        "typical_season",
        "is_active",
    )
    search_fields = ("name_en", "name_ta", "scientific_name")
    list_filter = ("is_active", "crop_category", "typical_season")


class FarmerFieldInline(admin.TabularInline):
    model = FarmerField
    extra = 0
    show_change_link = True


@admin.register(Farmer)
class FarmerAdmin(admin.ModelAdmin):
    list_display = (
        "farmer_code",
        "name",
        "phone",
        "district",
        "village",
        "assigned_employee",
        "is_active",
    )
    search_fields = ("name", "phone", "farmer_code")
    list_filter = ("is_active", "district", "irrigation_type", "soil_type")
    inlines = [FarmerFieldInline]
