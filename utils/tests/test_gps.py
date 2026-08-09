from django.test import SimpleTestCase
from rest_framework import serializers

from utils.gps import (
    validate_gps_location_string,
    validate_latitude,
    validate_latitude_longitude,
    validate_longitude,
)


class GpsValidationTests(SimpleTestCase):
    def test_valid_coordinates(self):
        lat, lng = validate_latitude_longitude(12.97, 77.59)
        self.assertEqual(lat, 12.97)
        self.assertEqual(lng, 77.59)

    def test_null_island_rejected(self):
        with self.assertRaises(serializers.ValidationError) as ctx:
            validate_latitude_longitude(0, 0)
        self.assertIn("0,0", str(ctx.exception.detail))

    def test_null_island_string_pair_rejected(self):
        with self.assertRaises(serializers.ValidationError):
            validate_latitude_longitude("0", "0.0")

    def test_near_zero_latitude_accepted(self):
        lat, lng = validate_latitude_longitude(0, 0.0001)
        self.assertEqual(lat, 0.0)
        self.assertEqual(lng, 0.0001)

    def test_near_zero_longitude_accepted(self):
        lat, lng = validate_latitude_longitude(0.0001, 0)
        self.assertEqual(lat, 0.0001)
        self.assertEqual(lng, 0.0)

    def test_invalid_latitude(self):
        with self.assertRaises(serializers.ValidationError):
            validate_latitude(95)

    def test_invalid_longitude(self):
        with self.assertRaises(serializers.ValidationError):
            validate_longitude(200)

    def test_gps_location_string(self):
        normalized = validate_gps_location_string("12.5, 78.5")
        self.assertEqual(normalized, "12.5,78.5")

    def test_gps_location_string_null_island_rejected(self):
        with self.assertRaises(serializers.ValidationError):
            validate_gps_location_string("0,0")

    def test_gps_location_string_invalid(self):
        with self.assertRaises(serializers.ValidationError):
            validate_gps_location_string("not-gps")
