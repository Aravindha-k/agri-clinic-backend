from django.contrib.auth.models import User
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from drf_spectacular.utils import extend_schema_field
from drf_spectacular.openapi import OpenApiTypes
from rest_framework import serializers
from .models import EmployeeProfile
from utils.serializer_mixins import ProfilePhotoUrlMixin
from .password_policy import validate_strong_password


def _validate_password_field(value):
    try:
        validate_strong_password(value)
    except DjangoValidationError as exc:
        raise serializers.ValidationError(list(exc.messages))
    return value


def employee_create_success_payload(profile: EmployeeProfile) -> dict:
    """Canonical admin create/list success fields for mobile-capable accounts."""
    return {
        "id": profile.id,
        "user_id": profile.user_id,
        "username": profile.user.username,
        "employee_id": profile.employee_id,
        "role": profile.role,
        "is_active_employee": profile.is_active_employee,
        "can_login": profile.can_login,
        "mobile_login_enabled": bool(
            profile.can_login
            and profile.is_active_employee
            and profile.user.is_active
            and not profile.user.is_staff
        ),
        "account_active": bool(profile.user.is_active and profile.is_active_employee),
    }


# =========================
# EMPLOYEE CREATE (ADMIN)
# =========================
class EmployeeCreateSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)

    def validate_password(self, value):
        return _validate_password_field(value)

    phone = serializers.CharField()

    def validate_username(self, value):
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("Username is required")
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError("Username already exists")
        return value

    def validate_phone(self, value):
        if not value.isdigit():
            raise serializers.ValidationError("Phone must contain only digits")
        if len(value) != 10:
            raise serializers.ValidationError("Phone must be exactly 10 digits")
        return value

    @transaction.atomic
    def create(self, validated_data):
        from .utils import generate_employee_id

        user = User.objects.create_user(
            username=validated_data["username"],
            password=validated_data["password"],
            is_staff=False,
            is_active=True,
        )

        profile = EmployeeProfile.objects.create(
            user=user,
            employee_id=generate_employee_id(),
            phone=validated_data["phone"],
            is_active_employee=True,
            can_login=True,
            role="FieldAgent",
        )
        # Return profile so API can expose the real employee_id string.
        return profile


# =========================
# CURRENT USER CONTEXT
# =========================
class MeSerializer(serializers.ModelSerializer):
    role = serializers.SerializerMethodField()
    employee_id = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "username", "role", "employee_id"]

    @extend_schema_field(OpenApiTypes.STR)
    def get_role(self, obj):
        return "ADMIN" if obj.is_staff else "EMPLOYEE"

    @extend_schema_field(OpenApiTypes.STR)
    def get_employee_id(self, obj):
        if hasattr(obj, "employee_profile"):
            return obj.employee_profile.employee_id
        return None


# =========================
# ADMIN PASSWORD RESET
# =========================
class AdminResetPasswordSerializer(serializers.Serializer):
    employee_id = serializers.CharField()
    new_password = serializers.CharField(write_only=True)

    def validate_new_password(self, value):
        return _validate_password_field(value)

    def save(self):
        employee_id = self.validated_data["employee_id"]
        new_password = self.validated_data["new_password"]

        try:
            profile = EmployeeProfile.objects.select_related("user").get(
                employee_id=employee_id
            )
        except EmployeeProfile.DoesNotExist:
            raise serializers.ValidationError({"employee_id": "Employee not found"})

        profile.user.set_password(new_password)
        profile.user.save(update_fields=["password"])

        return profile.user


# =========================
# SELF-SERVICE PASSWORD CHANGE
# =========================
class ChangePasswordSerializer(serializers.Serializer):
    # Optional for backward compatibility with mobile/admin clients; ignored for
    # identity — password always changes for request.user only.
    employee_id = serializers.CharField(required=False, allow_blank=True)
    current_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True)

    def validate_new_password(self, value):
        return _validate_password_field(value)

    def validate(self, data):
        request = self.context.get("request")
        user = getattr(request, "user", None) if request is not None else None
        if user is None or not getattr(user, "is_authenticated", False):
            raise serializers.ValidationError(
                {"detail": "Authentication required."}
            )

        employee_id = (data.get("employee_id") or "").strip()
        if employee_id:
            profile = (
                EmployeeProfile.objects.filter(user=user)
                .only("employee_id")
                .first()
            )
            own_id = getattr(profile, "employee_id", None) or ""
            if employee_id.casefold() != str(own_id).casefold():
                raise serializers.ValidationError(
                    {
                        "employee_id": (
                            "You can only change your own password."
                        )
                    }
                )

        current_password = data.get("current_password")
        if not user.check_password(current_password):
            raise serializers.ValidationError(
                {"current_password": "Current password is incorrect"}
            )

        self._user = user
        return data

    def save(self):
        self._user.set_password(self.validated_data["new_password"])
        self._user.save(update_fields=["password"])
        return self._user


class AdminCreateSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)
    phone = serializers.CharField()

    def validate_password(self, value):
        return _validate_password_field(value)

    def validate_username(self, value):
        if User.objects.filter(username=value).exists():
            raise serializers.ValidationError("Username already exists")
        return value

    def validate_phone(self, value):
        if not value.isdigit():
            raise serializers.ValidationError("Phone must contain only digits")
        if len(value) != 10:
            raise serializers.ValidationError("Phone must be exactly 10 digits")
        return value

    def create(self, validated_data):
        admin = User.objects.create_user(
            username=validated_data["username"],
            password=validated_data["password"],
            is_staff=True,
            is_superuser=False,
            is_active=True,
        )

        # ✅ OPTIONAL: reuse EmployeeProfile for admin contact info
        EmployeeProfile.objects.create(
            user=admin,
            employee_id=f"ADMIN-{admin.id}",
            phone=validated_data["phone"],
            is_active_employee=True,
        )

        return admin


# =========================
# ADMIN EMPLOYEE LIST / DETAIL
# =========================
class AdminEmployeeListSerializer(ProfilePhotoUrlMixin, serializers.ModelSerializer):
    user_id = serializers.IntegerField(source="user.id", read_only=True)
    username = serializers.CharField(source="user.username", read_only=True)
    first_name = serializers.CharField(source="user.first_name", read_only=True)
    last_name = serializers.CharField(source="user.last_name", read_only=True)
    can_login = serializers.BooleanField(read_only=True)
    mobile_login_enabled = serializers.SerializerMethodField()
    device_status = serializers.SerializerMethodField()
    district_id = serializers.IntegerField(
        source="district.id", read_only=True, allow_null=True
    )
    district_name = serializers.CharField(
        source="district.name", read_only=True, allow_null=True
    )

    class Meta:
        model = EmployeeProfile
        fields = [
            "id",
            "user_id",
            "employee_id",
            "username",
            "first_name",
            "last_name",
            "phone",
            "role",
            "district_id",
            "district_name",
            "is_active_employee",
            "can_login",
            "mobile_login_enabled",
            "profile_photo_url",
            "profile_photo_updated_at",
            "device_status",
            "created_at",
        ]
        read_only_fields = (
            "id",
            "employee_id",
            "created_at",
            "profile_photo_url",
            "profile_photo_updated_at",
            "can_login",
            "mobile_login_enabled",
        )

    def get_mobile_login_enabled(self, obj):
        return bool(
            obj.can_login
            and obj.is_active_employee
            and obj.user.is_active
            and not obj.user.is_staff
        )

    def get_device_status(self, obj):
        from accounts.device_sessions import device_status_payload

        return device_status_payload(obj.user)


# =========================
# ADMIN EMPLOYEE CREATE (full)
# =========================
class AdminEmployeeFullCreateSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)
    phone = serializers.CharField(required=False, allow_blank=True, default="")
    employee_id = serializers.CharField(required=False, allow_blank=True)
    role = serializers.ChoiceField(
        choices=EmployeeProfile.ROLE_CHOICES,
    )
    district = serializers.IntegerField(required=False, allow_null=True)
    village = serializers.IntegerField(required=False, allow_null=True)

    def validate_password(self, value):
        return _validate_password_field(value)

    def validate_username(self, value):
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("Username is required")
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError("Username already exists")
        return value

    def validate_phone(self, value):
        value = (value or "").strip()
        if not value:
            return ""
        if not value.isdigit():
            raise serializers.ValidationError("Phone must contain only digits")
        if len(value) != 10:
            raise serializers.ValidationError("Phone must be exactly 10 digits")
        return value

    def validate_employee_id(self, value):
        value = (value or "").strip()
        if not value:
            return value
        if EmployeeProfile.objects.filter(employee_id__iexact=value).exists():
            raise serializers.ValidationError("Employee ID already exists")
        return value

    @transaction.atomic
    def create(self, validated_data):
        from .utils import generate_employee_id

        emp_id = (validated_data.get("employee_id") or "").strip() or generate_employee_id()
        if EmployeeProfile.objects.filter(employee_id__iexact=emp_id).exists():
            raise serializers.ValidationError(
                {"employee_id": "Employee ID already exists"}
            )

        user = User.objects.create_user(
            username=validated_data["username"],
            password=validated_data["password"],
            is_staff=False,
            is_active=True,
        )
        profile = EmployeeProfile.objects.create(
            user=user,
            employee_id=emp_id,
            phone=validated_data.get("phone") or "",
            role=validated_data.get("role", "FieldAgent"),
            district_id=validated_data.get("district"),
            village_id=validated_data.get("village"),
            is_active_employee=True,
            can_login=True,
        )
        return profile


# =========================
# ADMIN EMPLOYEE UPDATE (full)
# =========================
class AdminEmployeeUpdateSerializer(serializers.Serializer):
    username = serializers.CharField(required=False)
    first_name = serializers.CharField(required=False, allow_blank=True)
    last_name = serializers.CharField(required=False, allow_blank=True)
    phone = serializers.CharField(required=False)
    role = serializers.ChoiceField(choices=EmployeeProfile.ROLE_CHOICES, required=False)
    district = serializers.IntegerField(required=False, allow_null=True)
    is_active_employee = serializers.BooleanField(required=False)
    can_login = serializers.BooleanField(required=False)

    def validate_phone(self, value):
        if value and (not value.isdigit() or len(value) != 10):
            raise serializers.ValidationError("Phone must be exactly 10 digits")
        return value

    @transaction.atomic
    def update(self, instance, validated_data):
        user = instance.user
        user_fields_to_save = []

        username = validated_data.get("username")
        if username and username != user.username:
            if User.objects.exclude(id=user.id).filter(username__iexact=username).exists():
                raise serializers.ValidationError(
                    {"username": "Username already exists"}
                )
            user.username = username
            user_fields_to_save.append("username")

        if "first_name" in validated_data:
            user.first_name = validated_data["first_name"]
            user_fields_to_save.append("first_name")
        if "last_name" in validated_data:
            user.last_name = validated_data["last_name"]
            user_fields_to_save.append("last_name")

        if "is_active_employee" in validated_data:
            instance.is_active_employee = validated_data["is_active_employee"]
            user.is_active = validated_data["is_active_employee"]
            user_fields_to_save.append("is_active")
            # Keep mobile login flag aligned unless can_login is set explicitly.
            if "can_login" not in validated_data:
                instance.can_login = validated_data["is_active_employee"]

        if "can_login" in validated_data:
            instance.can_login = validated_data["can_login"]

        if user_fields_to_save:
            user.save(update_fields=list(dict.fromkeys(user_fields_to_save)))

        if "phone" in validated_data:
            instance.phone = validated_data["phone"]
        if "role" in validated_data:
            instance.role = validated_data["role"]
        if "district" in validated_data:
            instance.district_id = validated_data["district"]

        instance.save()
        return instance
