from django.db.models import Q

from apps.core.audit import model_label, translated_description
from apps.core.models import AuditLog
from apps.notifications.models import Notification

# Security events stay in the audit log; they are not "team activity".
HIDDEN_ACTIONS = [AuditLog.Action.LOGIN, AuditLog.Action.LOGIN_FAILED, AuditLog.Action.LOGOUT, AuditLog.Action.SECURITY]
HIDDEN_MODELS = ["organizationsettings", "notification", "notificationpreference"]


def activity(user, limit=15):
    """Recent changes: admins see the whole office, everyone else sees their department."""
    qs = (
        AuditLog.objects.exclude(action__in=HIDDEN_ACTIONS)
        .exclude(content_type__model__in=HIDDEN_MODELS)
        .select_related("actor", "content_type")
    )
    if not user.is_admin:
        if user.department_id:
            qs = qs.filter(Q(actor__department_id=user.department_id) | Q(actor=user))
        else:
            qs = qs.filter(actor=user)
    return [
        {
            "id": e.pk,
            "actor_name": e.actor.full_name if e.actor else None,
            "action": e.action,
            "model": e.content_type.model if e.content_type else None,
            "model_label": model_label(e.content_type),
            "object_repr": e.object_repr,
            "description": translated_description(e),
            "timestamp": e.timestamp.isoformat(),
        }
        for e in qs[:limit]
    ]


def unread_notifications(user):
    return Notification.objects.filter(recipient=user, is_read=False).count()
