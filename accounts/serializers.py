from django.contrib.auth.models import User
from django.core.exceptions import ValidationError as DjangoValidationError
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


# =========================
# EMPLOYEE CREATE (ADMIN)
# =========================
class EmployeeCreateSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)

    def validate_password(self, value):
        return _validate_password_field(value)

    phone = serializers.CharField()

    def validate_phone(self, value):
        if not value.isdigit():
            raise serializers.ValidationError("Phone must contain only digits")
        if len(value) != 10:
            raise serializers.ValidationError("Phone must be exactly 10 digits")
        return value

    def create(self, validated_data):
        # Check if user already exists
        if User.objects.filter(username=validated_data["username"]).exists():
            raise serializers.ValidationError({"username": "User already created"})

        last_emp = EmployeeProfile.objects.order_by("-id").first()
        if last_emp and last_emp.employee_id.startswith("KAC-"):
            last_number = int(last_emp.employee_id.split("-")[1])
        else:
            last_number = 0

        new_employee_id = f"KAC-{last_number + 1:04d}"

        user = User.objects.create_user(
            username=validated_data["username"],
            password=validated_data["password"],
            is_staff=False,
            is_active=True,
        )

        EmployeeProfile.objects.create(
            user=user,
            employee_id=new_employee_id,
            phone=validated_data["phone"],
            is_active_employee=True,
            role="FieldAgent",  # Always set to FieldAgent
        )

        return user


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
    employee_id = serializers.CharField()
    current_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True)

    def validate_new_password(self, value):
        return _validate_password_field(value)

    def validate(self, data):
        employee_id = data.get("employee_id")
        current_password = data.get("current_password")

        try:
            profile = EmployeeProfile.objects.select_related("user").get(
                employee_id=employee_id
            )
        except EmployeeProfile.DoesNotExist:
            raise serializers.ValidationError({"employee_id": "Employee not found"})

        if not profile.user.check_password(current_password):
            raise serializers.ValidationError(
                {"current_password": "Current password is incorrect"}
            )

        self._user = profile.user
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
    can_login = serializers.BooleanField(source="user.is_active", read_only=True)
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
    employee_id = serializers.CharField()
    role = serializers.ChoiceField(
        choices=EmployeeProfile.ROLE_CHOICES,
    )
    district = serializers.IntegerField(required=False, allow_null=True)
    village = serializers.IntegerField(required=False, allow_null=True)

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

    def validate_employee_id(self, value):
        if value and EmployeeProfile.objects.filter(employee_id=value).exists():
            raise serializers.ValidationError("Employee ID already exists")
        return value

    def create(self, validated_data):
        from .utils import generate_employee_id

        emp_id = validated_data.get("employee_id") or generate_employee_id()

        user = User.objects.create_user(
            username=validated_data["username"],
            password=validated_data["password"],
            is_staff=False,
            is_active=True,
        )
        profile = EmployeeProfile.objects.create(
            user=user,
            employee_id=emp_id,
            phone=validated_data["phone"],
            role=validated_data.get("role", "FieldAgent"),
            district_id=validated_data.get("district"),
            village_id=validated_data.get("village"),
            is_active_employee=True,
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

    def validate_phone(self, value):
        if value and (not value.isdigit() or len(value) != 10):
            raise serializers.ValidationError("Phone must be exactly 10 digits")
        return value

    def update(self, instance, validated_data):
        user = instance.user
        user_fields_to_save = []

        username = validated_data.get("username")
        if username and username != user.username:
            if User.objects.exclude(id=user.id).filter(username=username).exists():
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

        if user_fields_to_save:
            user.save(update_fields=user_fields_to_save)

        if "phone" in validated_data:
            instance.phone = validated_data["phone"]
        if "role" in validated_data:
            instance.role = validated_data["role"]
        if "district" in validated_data:
            instance.district_id = validated_data["district"]
        if "is_active_employee" in validated_data:
            instance.is_active_employee = validated_data["is_active_employee"]
            user.is_active = validated_data["is_active_employee"]
            user.save(update_fields=["is_active"])

        instance.save()
        return instance
