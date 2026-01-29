from django.contrib.auth.models import User
from rest_framework import serializers
from .models import EmployeeProfile


class EmployeeCreateSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)
    phone = serializers.CharField()

    def validate_phone(self, value):
        if not value.isdigit():
            raise serializers.ValidationError("Phone must contain only digits")
        if len(value) != 10:
            raise serializers.ValidationError("Phone must be exactly 10 digits")
        return value

    def create(self, validated_data):
        # ✅ Auto Employee ID Generate
        last_emp = EmployeeProfile.objects.order_by("-id").first()

        if last_emp and last_emp.employee_id.startswith("KAC-"):
            last_number = int(last_emp.employee_id.split("-")[1])
        else:
            last_number = 0

        new_employee_id = f"KAC-{last_number+1:04d}"

        # ✅ Create User
        user = User.objects.create_user(
            username=validated_data["username"],
            password=validated_data["password"],
            is_staff=False,
        )

        # ✅ Create Employee Profile
        EmployeeProfile.objects.create(
            user=user,
            employee_id=new_employee_id,
            phone=validated_data["phone"],
            is_active_employee=True,
        )

        return user


# ✅ Who am I (role detection)
class MeSerializer(serializers.ModelSerializer):
    role = serializers.SerializerMethodField()
    employee_id = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "username", "role", "employee_id"]

    def get_role(self, obj):
        return "ADMIN" if obj.is_staff else "EMPLOYEE"

    def get_employee_id(self, obj):
        try:
            return obj.employeeprofile.employee_id
        except EmployeeProfile.DoesNotExist:
            return None


# ✅ Admin Reset Password
class AdminResetPasswordSerializer(serializers.Serializer):
    user_id = serializers.IntegerField()
    new_password = serializers.CharField(write_only=True)

    def save(self):
        user_id = self.validated_data["user_id"]
        new_password = self.validated_data["new_password"]

        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            raise serializers.ValidationError("User not found")

        user.set_password(new_password)
        user.save()

        return user
