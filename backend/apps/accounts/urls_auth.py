from django.urls import path

from . import views_auth as v

urlpatterns = [
    path("login/", v.LoginView.as_view(), name="auth-login"),
    path("login/verify-otp/", v.VerifyOTPView.as_view(), name="auth-verify-otp"),
    path("refresh/", v.RefreshView.as_view(), name="auth-refresh"),
    path("logout/", v.LogoutView.as_view(), name="auth-logout"),
    path("me/", v.MeView.as_view(), name="auth-me"),
    path("password/change/", v.ChangePasswordView.as_view(), name="auth-password-change"),
    path("password/reset/", v.PasswordResetRequestView.as_view(), name="auth-password-reset"),
    path("password/reset/confirm/", v.PasswordResetConfirmView.as_view(), name="auth-password-reset-confirm"),
    path("2fa/setup/", v.TwoFactorSetupView.as_view(), name="auth-2fa-setup"),
    path("2fa/enable/", v.TwoFactorEnableView.as_view(), name="auth-2fa-enable"),
    path("2fa/disable/", v.TwoFactorDisableView.as_view(), name="auth-2fa-disable"),
    path("2fa/backup-codes/", v.BackupCodesRegenerateView.as_view(), name="auth-2fa-backup-codes"),
]
