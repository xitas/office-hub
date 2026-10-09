from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils.translation import gettext
from rest_framework.settings import api_settings

from .models import AuditLog

# Never written into the audit trail, even as "changed".
SENSITIVE_FIELDS = {"password", "totp_secret", "backup_codes"}


def get_client_ip(request):
    """Client address, trusting X-Forwarded-For only for the configured number of proxies
    (same rule as DRF's throttling, so audit IPs and rate limits agree)."""
    if request is None:
        return None
    num_proxies = api_settings.NUM_PROXIES or 0
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if num_proxies and forwarded:
        addrs = [a.strip() for a in forwarded.split(",")]
        return addrs[-min(num_proxies, len(addrs))]
    return request.META.get("REMOTE_ADDR")


def _serialize(value):
    if isinstance(value, models.Model):
        return str(value)
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


def snapshot(instance) -> dict:
    """Current values of concrete, non-sensitive fields. Foreign keys are recorded by name, not id,
    so the audit trail stays readable ("department: Sales → Operations")."""
    data = {}
    for field in instance._meta.concrete_fields:
        if field.name in SENSITIVE_FIELDS:
            continue
        if field.is_relation:
            related = getattr(instance, field.name) if getattr(instance, field.attname) is not None else None
            data[field.name] = str(related) if related is not None else None
        else:
            data[field.name] = _serialize(getattr(instance, field.attname))
    return data


def diff(before: dict, after: dict) -> dict:
    """{field: [old, new]} for fields whose value changed (snapshots already exclude sensitive fields)."""
    return {k: [before.get(k), v] for k, v in after.items() if before.get(k) != v and k not in ("updated_at", "updated_by")}


def model_label(content_type) -> str | None:
    """Human, translated name of an entry's record type (e.g. "user" / "صارف")."""
    if content_type is None:
        return None
    model = content_type.model_class()
    return str(model._meta.verbose_name) if model else content_type.model


def translated_description(entry) -> str:
    return gettext(entry.description) if entry.description else ""


def log_action(actor, action, obj=None, *, changes=None, description="", request=None, object_repr=None):
    """`description` should be an untranslated message id (wrap literals in gettext_noop)."""
    if actor is not None and not getattr(actor, "is_authenticated", False):
        actor = None
    return AuditLog.objects.create(
        actor=actor,
        action=action,
        content_type=ContentType.objects.get_for_model(obj) if obj is not None else None,
        object_id=str(obj.pk) if obj is not None else "",
        object_repr=(object_repr if object_repr is not None else str(obj) if obj is not None else "")[:255],
        changes=changes or {},
        description=description[:255],
        ip=get_client_ip(request),
    )


class AuditedViewSetMixin:
    """Writes an AuditLog row on create, update and delete; sets `created_by` / `updated_by` when the model has them."""

    def _user_fields(self, serializer, *names):
        fields = {f.name for f in serializer.Meta.model._meta.concrete_fields}
        return {name: self.request.user for name in names if name in fields}

    def audit_snapshot(self, instance) -> dict:
        """Values compared for the audit diff. Override to add e.g. many-to-many fields."""
        return snapshot(instance)

    def perform_create(self, serializer):
        instance = serializer.save(**self._user_fields(serializer, "created_by", "updated_by"))
        log_action(
            self.request.user, AuditLog.Action.CREATE, instance, changes=self.audit_snapshot(instance), request=self.request
        )

    def perform_update(self, serializer):
        before = self.audit_snapshot(serializer.instance)
        sensitive_before = {f: getattr(serializer.instance, f, None) for f in SENSITIVE_FIELDS}
        instance = serializer.save(**self._user_fields(serializer, "updated_by"))
        changes = diff(before, self.audit_snapshot(instance))
        for field, old in sensitive_before.items():
            if old != getattr(instance, field, None):
                changes[field] = ["***", "***"]
        if changes:
            log_action(self.request.user, AuditLog.Action.UPDATE, instance, changes=changes, request=self.request)

    def perform_destroy(self, instance):
        log_action(
            self.request.user, AuditLog.Action.DELETE, instance, changes=self.audit_snapshot(instance), request=self.request
        )
        instance.delete()
