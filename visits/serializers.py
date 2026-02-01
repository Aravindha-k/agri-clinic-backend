from rest_framework import serializers
from django.utils import timezone

from .models import Visit
from tracking.models import WorkDay, AvailabilityEvent
from .models import Visit, VisitAttachment


class VisitCreateSerializer(serializers.Serializer):
    farmer_name = serializers.CharField()
    farmer_phone = serializers.CharField()
    village = serializers.CharField()
    crop_type = serializers.CharField()
    problem_category = serializers.CharField()

    latitude = serializers.DecimalField(max_digits=9, decimal_places=6)
    longitude = serializers.DecimalField(max_digits=9, decimal_places=6)

    def save(self, **kwargs):
        user = self.context["request"].user

        # Admin cannot create visits
        if user.is_staff:
            raise serializers.ValidationError("Admin cannot create visits")

        # Active workday required
        try:
            workday = WorkDay.objects.get(user=user, is_active=True)
        except WorkDay.DoesNotExist:
            raise serializers.ValidationError("No active workday")

        # GPS OFF check
        if AvailabilityEvent.objects.filter(
            user=user,
            workday=workday,
            event_type="GPS_OFF",
            end_time__isnull=True,
        ).exists():
            raise serializers.ValidationError("GPS is OFF")

        # OFFLINE check
        if AvailabilityEvent.objects.filter(
            user=user,
            workday=workday,
            event_type="OFFLINE",
            end_time__isnull=True,
        ).exists():
            raise serializers.ValidationError("User is OFFLINE")

        visit = Visit.objects.create(
            user=user,
            farmer_name=self.validated_data["farmer_name"],
            farmer_phone=self.validated_data["farmer_phone"],
            village=self.validated_data["village"],
            crop_type=self.validated_data["crop_type"],
            problem_category=self.validated_data["problem_category"],
            latitude=self.validated_data["latitude"],
            longitude=self.validated_data["longitude"],
            is_verified=True,
        )

        return visit


# class VisitAttachmentSerializer(serializers.ModelSerializer):
#     class Meta:
#         model = VisitAttachment
#         fields = ["id", "file_type", "file", "uploaded_at"]


class VisitAttachmentSerializer(serializers.ModelSerializer):
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = VisitAttachment
        fields = ["id", "file_type", "file", "file_url", "uploaded_at"]

    def get_file_url(self, obj):
        request = self.context.get("request")
        if request:
            return request.build_absolute_uri(obj.file.url)
        return obj.file.url


class VisitSerializer(serializers.ModelSerializer):
    employee = serializers.CharField(source="user.username", read_only=True)
    attachments = VisitAttachmentSerializer(many=True, read_only=True)

    class Meta:
        model = Visit
        fields = [
            "id",
            "farmer_name",
            "farmer_phone",
            "village",
            "crop_type",
            "problem_category",
            "latitude",
            "longitude",
            "visit_time",
            "is_verified",
            "employee",
            "attachments",
        ]


class VisitListSerializer(serializers.ModelSerializer):
    attachments = VisitAttachmentSerializer(many=True, read_only=True)

    class Meta:
        model = Visit
        fields = [
            "id",
            "farmer_name",
            "village",
            "visit_time",
            "attachments",
        ]
