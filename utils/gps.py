"""Latitude/longitude validation for visits, tracking, and GPS strings."""

from __future__ import annotations

from typing import Any, Optional, Tuple

from rest_framework import serializers


def validate_latitude(value: Any) -> float:
    try:
        lat = float(value)
    except (TypeError, ValueError):
        raise serializers.ValidationError("Latitude must be a number.")
    if not -90.0 <= lat <= 90.0:
        raise serializers.ValidationError("Latitude must be between -90 and 90.")
    return lat


def validate_longitude(value: Any) -> float:
    try:
        lng = float(value)
    except (TypeError, ValueError):
        raise serializers.ValidationError("Longitude must be a number.")
    if not -180.0 <= lng <= 180.0:
        raise serializers.ValidationError("Longitude must be between -180 and 180.")
    return lng


def validate_latitude_longitude(latitude: Any, longitude: Any) -> Tuple[float, float]:
    lat = validate_latitude(latitude)
    lng = validate_longitude(longitude)
    # Reject null-island only — individual lat=0 or lng=0 remains valid.
    if lat == 0.0 and lng == 0.0:
        raise serializers.ValidationError(
            "Invalid coordinates (0,0). Provide a real GPS fix."
        )
    return lat, lng


def validate_gps_location_string(
    gps_location: Optional[str], *, required: bool = False
) -> Optional[str]:
    """
    Validate Farmer/FarmerField gps_location \"lat,lng\" format.
    Returns normalized \"lat,lng\" string or None when empty and not required.
    """
    raw = (gps_location or "").strip()
    if not raw:
        if required:
            raise serializers.ValidationError("GPS location is required.")
        return None
    parts = raw.split(",")
    if len(parts) != 2:
        raise serializers.ValidationError(
            'GPS location must be "latitude,longitude" (two comma-separated numbers).'
        )
    lat, lng = validate_latitude_longitude(parts[0].strip(), parts[1].strip())
    return f"{lat},{lng}"
