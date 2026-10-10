from django.conf import settings
from django.contrib.auth import authenticate, password_validation
from django.contrib.auth.models import update_last_login
from django.contrib.auth.tokens import default_token_generator
from django.core import signing
from django.utils import translation
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.utils.translation import gettext as _
from django.utils.translation import gettext_noop as N_
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.exceptions import Throttled
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.settings import api_settings as jwt_settings
from rest_framework_simplejwt.tokens import RefreshToken

from apps.core.audit import diff, log_action, snapshot
from apps.core.email import queue_email
from apps.core.models import AuditLog
from apps.core.ws_auth import TICKET_TTL, issue_ticket

from apps.core.safe_cache import safe_cache

from . import login_guard, twofactor
from .models import User
from .serializers import (
    ChangePasswordSerializer,
    LoginSerializer,
    MeSerializer,
    OTPVerifySerializer,
    PasswordConfirmSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    TwoFactorCodeSerializer,
)

OTP_SALT = "crm.login.otp"


def _set_refresh_cookie(response, refresh: str):
    response.set_cookie(
        settings.REFRESH_COOKIE_NAME,
        refresh,
        max_age=int(jwt_settings.REFRESH_TOKEN_LIFETIME.total_seconds()),
        httponly=True,
        secure=settings.REFRESH_COOKIE_SECURE,
        samesite="Lax",
        path=settings.REFRESH_COOKIE_PATH,
    )


def _token_response(request, user, client="web"):
    """Issue tokens. Web clients get the refresh token as an httpOnly cookie; mobile clients in the body."""
    login_guard.clear(user.email)
    refresh = RefreshToken.for_user(user)
    update_last_login(None, user)
    log_action(user, AuditLog.Action.LOGIN, user, request=request, description=N_("Signed in"), changes={"client": client})
    body = {"access": str(refresh.access_token), "user": MeSerializer(user, context={"request": request}).data}
    if client == "mobile":
        body["refresh"] = str(refresh)
    response = Response(body)
    if client != "mobile":
        _set_refresh_cookie(response, str(refresh))
    return response


class PublicAuthView(APIView):
    """Unauthenticated endpoint that still answers bad credentials with 401 (not 403)."""

    authentication_classes: list = []
    permission_classes = [AllowAny]

    def get_authenticate_header(self, request):
        return "Bearer"


class SafeScopedRateThrottle(ScopedRateThrottle):
    """Per-IP limit that keeps working (per process) if Redis is down, instead of failing the request."""

    cache = safe_cache


def _check_account(email: str):
    """Same answer for every address, registered or not."""
    wait = login_guard.retry_after(email)
    if wait:
        raise Throttled(
            wait=wait,
            detail=_("Too many failed sign-in attempts for this account."),
        )


class LoginThrottleMixin:
    throttle_classes = [SafeScopedRateThrottle]
    throttle_scope = "login"


class LoginView(LoginThrottleMixin, PublicAuthView):
    @extend_schema(request=LoginSerializer, responses={200: dict})
    def post(self, request):
        ser = LoginSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        email = ser.validated_data["email"].lower()
        _check_account(email)
        user = authenticate(request, email=email, password=ser.validated_data["password"])
        if user is None:
            log_action(
                None, AuditLog.Action.LOGIN_FAILED, request=request, object_repr=email, description=N_("Failed sign-in attempt")
            )
            login_guard.record_failure(email, User.objects.filter(email__iexact=email, is_active=True).first(), request)
            raise AuthenticationFailed(_("Invalid email or password."))
        if user.two_factor_enabled:
            otp_token = signing.dumps({"uid": user.pk}, salt=OTP_SALT)
            return Response({"otp_required": True, "otp_token": otp_token})
        return _token_response(request, user, ser.validated_data["client"])


class VerifyOTPView(LoginThrottleMixin, PublicAuthView):
    @extend_schema(request=OTPVerifySerializer, responses={200: dict})
    def post(self, request):
        ser = OTPVerifySerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            payload = signing.loads(ser.validated_data["otp_token"], salt=OTP_SALT, max_age=settings.OTP_TOKEN_MAX_AGE)
            user = User.objects.get(pk=payload["uid"], is_active=True)
        except (signing.BadSignature, User.DoesNotExist, KeyError):
            raise AuthenticationFailed(_("Your sign-in session expired. Please sign in again."))
        _check_account(user.email)
        if not twofactor.verify_second_factor(user, ser.validated_data["code"]):
            log_action(user, AuditLog.Action.LOGIN_FAILED, user, request=request, description=N_("Invalid 2FA code"))
            login_guard.record_failure(user.email, user, request)
            raise AuthenticationFailed(_("Invalid verification code."))
        return _token_response(request, user, ser.validated_data["client"])


def _check_cookie_request(request):
    """CSRF defence for endpoints authenticated by the refresh *cookie* (an ambient credential).

    SameSite=Lax already stops other sites, but not sibling subdomains or old browsers. A custom
    header can't be sent by a plain form and, cross-origin, needs a CORS preflight that only our
    own origins pass; a present Origin header must also be one of ours. Body-token (mobile) calls
    carry no ambient credential and skip this.
    """
    if request.headers.get("X-Requested-With") != "XMLHttpRequest":
        raise PermissionDenied(_("Missing X-Requested-With header."))
    origin = request.headers.get("Origin")
    if origin and origin not in _trusted_origins(request):
        raise PermissionDenied(_("Request origin is not allowed."))


def _trusted_origins(request) -> set[str]:
    return {
        *settings.CORS_ALLOWED_ORIGINS,
        *getattr(settings, "CSRF_TRUSTED_ORIGINS", []),
        f"{request.scheme}://{request.get_host()}",
    }


class RefreshView(PublicAuthView):
    @extend_schema(request=None, responses={200: dict})
    def post(self, request):
        from_cookie = "refresh" not in request.data
        raw = request.data.get("refresh") or request.COOKIES.get(settings.REFRESH_COOKIE_NAME)
        if from_cookie and raw:
            _check_cookie_request(request)
        if not raw:
            # No session at all is a normal state (e.g. first visit), not an error.
            return Response(status=status.HTTP_204_NO_CONTENT)
        ser = TokenRefreshSerializer(data={"refresh": raw})
        try:
            ser.is_valid(raise_exception=True)
        except (TokenError, AuthenticationFailed) as exc:
            raise AuthenticationFailed(_("Session expired. Please sign in again.")) from exc
        data = dict(ser.validated_data)
        new_refresh = data.pop("refresh", None)
        if new_refresh and not from_cookie:
            data["refresh"] = new_refresh
        response = Response(data)
        if new_refresh and from_cookie:
            _set_refresh_cookie(response, new_refresh)
        return response


class LogoutView(PublicAuthView):
    @extend_schema(request=None, responses={204: None})
    def post(self, request):
        raw = request.data.get("refresh") or request.COOKIES.get(settings.REFRESH_COOKIE_NAME)
        if raw and "refresh" not in request.data:
            _check_cookie_request(request)
        if raw:
            try:
                token = RefreshToken(raw)
                user = User.objects.filter(pk=token.get("user_id")).first()
                token.blacklist()
                if user:
                    log_action(user, AuditLog.Action.LOGOUT, user, request=request, description=N_("Signed out"))
            except TokenError:
                pass
        response = Response(status=status.HTTP_204_NO_CONTENT)
        response.delete_cookie(settings.REFRESH_COOKIE_NAME, path=settings.REFRESH_COOKIE_PATH)
        return response


class WebSocketTicketView(APIView):
    """Single-use, 30-second ticket for opening the notifications WebSocket (see apps.core.ws_auth)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses={200: dict})
    def post(self, request):
        return Response({"ticket": issue_ticket(request.user), "expires_in": TICKET_TTL})


class MeView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    @extend_schema(responses=MeSerializer)
    def get(self, request):
        return Response(MeSerializer(request.user, context={"request": request}).data)

    @extend_schema(request=MeSerializer, responses=MeSerializer)
    def patch(self, request):
        before = snapshot(request.user)
        ser = MeSerializer(request.user, data=request.data, partial=True, context={"request": request})
        ser.is_valid(raise_exception=True)
        user = ser.save()
        changes = diff(before, snapshot(user))
        if changes:
            log_action(user, AuditLog.Action.UPDATE, user, changes=changes, request=request, description=N_("Updated own profile"))
        return Response(ser.data)


class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=ChangePasswordSerializer, responses={204: None})
    def post(self, request):
        ser = ChangePasswordSerializer(data=request.data, context={"request": request})
        ser.is_valid(raise_exception=True)
        request.user.set_password(ser.validated_data["new_password"])
        request.user.save(update_fields=["password"])
        log_action(request.user, AuditLog.Action.SECURITY, request.user, request=request, description=N_("Changed password"))
        return Response(status=status.HTTP_204_NO_CONTENT)


class PasswordResetRequestView(PublicAuthView):
    throttle_classes = [SafeScopedRateThrottle]
    throttle_scope = "password_reset"

    @extend_schema(request=PasswordResetRequestSerializer, responses={204: None})
    def post(self, request):
        ser = PasswordResetRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        user = User.objects.filter(email__iexact=ser.validated_data["email"], is_active=True).first()
        if user:
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = default_token_generator.make_token(user)
            link = f"{settings.FRONTEND_URL}/reset-password?uid={uid}&token={token}"
            with translation.override(user.language):
                queue_email(
                    _("Reset your Office CRM password"),
                    _(
                        "Hello %(name)s,\n\nUse this link to set a new password:\n%(link)s\n\n"
                        "If you did not request this, you can ignore this email."
                    )
                    % {"name": user.full_name, "link": link},
                    [user.email],
                )
        # Same response either way so the endpoint cannot be used to discover accounts.
        return Response(status=status.HTTP_204_NO_CONTENT)


class PasswordResetConfirmView(PublicAuthView):

    @extend_schema(request=PasswordResetConfirmSerializer, responses={204: None})
    def post(self, request):
        ser = PasswordResetConfirmSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            user = User.objects.get(pk=force_str(urlsafe_base64_decode(ser.validated_data["uid"])), is_active=True)
        except (User.DoesNotExist, ValueError, TypeError):
            user = None
        if user is None or not default_token_generator.check_token(user, ser.validated_data["token"]):
            raise ValidationError({"token": [_("This reset link is invalid or has expired.")]})
        try:
            password_validation.validate_password(ser.validated_data["new_password"], user)
        except Exception as exc:
            raise ValidationError({"new_password": list(getattr(exc, "messages", [str(exc)]))})
        user.set_password(ser.validated_data["new_password"])
        user.save(update_fields=["password"])
        login_guard.clear(user.email)
        log_action(user, AuditLog.Action.SECURITY, user, request=request, description=N_("Reset password via email"))
        return Response(status=status.HTTP_204_NO_CONTENT)


class TwoFactorSetupView(APIView):
    """Generates a new (not yet active) TOTP secret and returns its QR code."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses={200: dict})
    def post(self, request):
        user = request.user
        if user.two_factor_enabled:
            raise ValidationError({"detail": _("Two-factor authentication is already enabled.")})
        user.totp_secret = twofactor.new_secret()
        user.save(update_fields=["totp_secret"])
        uri, qr = twofactor.provisioning_qr(user)
        return Response({"secret": user.totp_secret, "otpauth_uri": uri, "qr_code": qr})


class TwoFactorEnableView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=TwoFactorCodeSerializer, responses={200: dict})
    def post(self, request):
        ser = TwoFactorCodeSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        user = request.user
        if user.two_factor_enabled:
            raise ValidationError({"detail": _("Two-factor authentication is already enabled.")})
        if not twofactor.verify_totp(user, ser.validated_data["code"]):
            raise ValidationError({"code": [_("Invalid code. Check your authenticator app and try again.")]})
        codes = twofactor.generate_backup_codes(user)
        user.two_factor_enabled = True
        user.save(update_fields=["two_factor_enabled", "backup_codes"])
        log_action(user, AuditLog.Action.SECURITY, user, request=request, description=N_("Enabled two-factor authentication"))
        return Response({"backup_codes": codes})


class TwoFactorDisableView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=PasswordConfirmSerializer, responses={204: None})
    def post(self, request):
        ser = PasswordConfirmSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        user = request.user
        if not user.check_password(ser.validated_data["password"]):
            raise ValidationError({"password": [_("Password is incorrect.")]})
        user.two_factor_enabled = False
        user.totp_secret = ""
        user.backup_codes = []
        user.save(update_fields=["two_factor_enabled", "totp_secret", "backup_codes"])
        log_action(user, AuditLog.Action.SECURITY, user, request=request, description=N_("Disabled two-factor authentication"))
        return Response(status=status.HTTP_204_NO_CONTENT)


class BackupCodesRegenerateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=PasswordConfirmSerializer, responses={200: dict})
    def post(self, request):
        ser = PasswordConfirmSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        user = request.user
        if not user.two_factor_enabled:
            raise ValidationError({"detail": _("Two-factor authentication is not enabled.")})
        if not user.check_password(ser.validated_data["password"]):
            raise ValidationError({"password": [_("Password is incorrect.")]})
        codes = twofactor.generate_backup_codes(user)
        user.save(update_fields=["backup_codes"])
        log_action(user, AuditLog.Action.SECURITY, user, request=request, description=N_("Regenerated 2FA backup codes"))
        return Response({"backup_codes": codes})
