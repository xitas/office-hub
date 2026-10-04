from django.contrib.auth import password_validation
from django.utils.translation import gettext as _
from rest_framework import serializers

from apps.core.permissions import permissions_for

from .models import Department, User


class DepartmentSerializer(serializers.ModelSerializer):
    manager_name = serializers.CharField(source="manager.full_name", default=None, read_only=True)
    member_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Department
        fields = ["id", "name", "description", "manager", "manager_name", "member_count", "created_at"]
        read_only_fields = ["created_at"]


class UserSummarySerializer(serializers.ModelSerializer):
    """Compact user shape for embedding in other resources."""

    class Meta:
        model = User
        fields = ["id", "full_name", "email", "avatar", "role"]


class MeSerializer(serializers.ModelSerializer):
    department_name = serializers.CharField(source="department.name", default=None, read_only=True)
    permissions = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id", "email", "full_name", "phone", "job_title", "role", "department", "department_name",
            "avatar", "language", "theme", "two_factor_enabled", "permissions", "date_joined", "last_login",
        ]
        read_only_fields = [
            "id", "email", "role", "department", "two_factor_enabled", "permissions", "date_joined", "last_login",
        ]

    def get_permissions(self, obj) -> list[str]:
        return permissions_for(obj)


class UserSerializer(serializers.ModelSerializer):
    """Admin user management. Password is write-only and optional on update."""

    department_name = serializers.CharField(source="department.name", default=None, read_only=True)
    password = serializers.CharField(write_only=True, required=False, style={"input_type": "password"})

    class Meta:
        model = User
        fields = [
            "id", "email", "full_name", "phone", "job_title", "role", "department", "department_name",
            "avatar", "is_active", "two_factor_enabled", "last_login", "date_joined", "password",
        ]
        read_only_fields = ["two_factor_enabled", "last_login", "date_joined"]

    def validate_email(self, value):
        value = value.lower()
        qs = User.objects.filter(email__iexact=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(_("A user with this email already exists."))
        return value

    def validate(self, attrs):
        password = attrs.get("password")
        if not self.instance and not password:
            raise serializers.ValidationError({"password": _("Password is required for new users.")})
        if password:
            candidate = self.instance or User(**{k: v for k, v in attrs.items() if k != "password"})
            password_validation.validate_password(password, candidate)

        request = self.context.get("request")
        if self.instance and request and self.instance.pk == request.user.pk:
            if attrs.get("role", self.instance.role) != self.instance.role:
                raise serializers.ValidationError({"role": _("You cannot change your own role.")})
            if attrs.get("is_active", True) is False:
                raise serializers.ValidationError({"is_active": _("You cannot deactivate your own account.")})
        return attrs

    def create(self, validated_data):
        password = validated_data.pop("password")
        return User.objects.create_user(password=password, **validated_data)

    def update(self, instance, validated_data):
        password = validated_data.pop("password", None)
        for key, value in validated_data.items():
            setattr(instance, key, value)
        if password:
            instance.set_password(password)
        instance.save()
        return instance


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(style={"input_type": "password"})
    client = serializers.ChoiceField(choices=["web", "mobile"], default="web")


class OTPVerifySerializer(serializers.Serializer):
    otp_token = serializers.CharField()
    code = serializers.CharField(max_length=20)
    client = serializers.ChoiceField(choices=["web", "mobile"], default="web")


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField()
    new_password = serializers.CharField()

    def validate_current_password(self, value):
        if not self.context["request"].user.check_password(value):
            raise serializers.ValidationError(_("Current password is incorrect."))
        return value

    def validate_new_password(self, value):
        password_validation.validate_password(value, self.context["request"].user)
        return value


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()


class PasswordResetConfirmSerializer(serializers.Serializer):
    uid = serializers.CharField()
    token = serializers.CharField()
    new_password = serializers.CharField()


class TwoFactorCodeSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=20)


class PasswordConfirmSerializer(serializers.Serializer):
    password = serializers.CharField()
