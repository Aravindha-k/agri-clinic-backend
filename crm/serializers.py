from rest_framework import serializers
from .models import Farmer, Visit, VisitReview


class FarmerSerializer(serializers.ModelSerializer):
    total_visits = serializers.IntegerField(read_only=True)
    last_visit_date = serializers.DateField(read_only=True)

    class Meta:
        model = Farmer
        fields = ["id", "name", "phone", "village", "total_visits", "last_visit_date"]


class VisitReviewSerializer(serializers.ModelSerializer):
    class Meta:
        model = VisitReview
        fields = ["notes", "visit_date"]


class VisitSerializer(serializers.ModelSerializer):
    reviews = VisitReviewSerializer(many=True, read_only=True)

    class Meta:
        model = Visit
        fields = ["id", "crop", "created_at", "reviews"]


class FarmerDetailSerializer(serializers.ModelSerializer):
    visits = VisitSerializer(many=True, read_only=True)

    class Meta:
        model = Farmer
        fields = ["id", "name", "phone", "village", "visits"]
