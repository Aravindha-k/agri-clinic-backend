from rest_framework import serializers
from .models import AuditLog


class AuditLogSerializer(serializers.ModelSerializer):
    actor = serializers.CharField(source="actor.username", default=None)
    actor_id = serializers.IntegerField(source="actor.id", default=None)
    entity_id = serializers.CharField(source="object_id", default=None)
    timestamp = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = AuditLog
        fields = [
            "id",
            "actor",
            "actor_id",
            "module",
            "action",
            "entity_id",
            "description",
            "metadata",
            "ip_address",
            "timestamp",
        ]
