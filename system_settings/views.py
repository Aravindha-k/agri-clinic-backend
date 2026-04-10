from rest_framework.views import APIView
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework import status, serializers

from drf_spectacular.utils import extend_schema, inline_serializer

from utils.schema import SIMPLE_SUCCESS, error_schema

from .models import SystemSetting, SystemConfig


@extend_schema(
    tags=["System"],
    summary="List or update system settings",
    description="GET: returns all system settings (key/value pairs). PATCH: update a setting value by key.",
    request=inline_serializer(
        name="SystemSettingPatchRequest",
        fields={
            "key": serializers.CharField(),
            "value": serializers.CharField(required=False, allow_blank=True),
        },
    ),
    responses={200: SIMPLE_SUCCESS, 400: error_schema("SettingError")},
)
class SystemSettingsAPI(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        settings = SystemSetting.objects.all()
        data = [
            {
                "key": s.key,
                "value": s.value,
                "description": s.description,
                "is_active": s.is_active,
            }
            for s in settings
        ]
        return Response(data)

    def patch(self, request):
        key = request.data.get("key")
        value = request.data.get("value")

        if not key:
            return Response({"error": "key required"}, status=400)

        setting = SystemSetting.objects.filter(key=key).first()
        if not setting:
            return Response({"error": "Setting not found"}, status=404)

        setting.value = value
        setting.save(update_fields=["value", "updated_at"])

        return Response({"message": "Setting updated"}, status=status.HTTP_200_OK)


# ─────────────────────────────────────────────
# SYSTEM CONFIG (singleton – tracking thresholds)
# GET  /api/system/config/
# PUT  /api/system/config/
# ─────────────────────────────────────────────
class SystemConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = SystemConfig
        fields = [
            "heartbeat_timeout_minutes",
            "gps_accuracy_limit",
            "gps_jump_limit_km",
            "tracking_stale_minutes",
            "updated_at",
        ]
        read_only_fields = ("updated_at",)


@extend_schema(
    tags=["System"],
    summary="Get or update system config",
    description="GET: returns tracking threshold config. PUT: updates heartbeat timeout, GPS accuracy limits, etc.",
    request=SystemConfigSerializer,
    responses={200: SystemConfigSerializer, 400: error_schema("SystemConfigError")},
)
class SystemConfigAPI(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        config = SystemConfig.load()
        return Response(SystemConfigSerializer(config).data)

    def put(self, request):
        config = SystemConfig.load()
        serializer = SystemConfigSerializer(config, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(
            {"message": "Config updated", "config": serializer.data},
            status=status.HTTP_200_OK,
        )
