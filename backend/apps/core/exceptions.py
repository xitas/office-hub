from django.utils.translation import gettext as _
from rest_framework.views import exception_handler


def api_exception_handler(exc, context):
    """Uniform error body: {"detail": str, "code": str, "errors": {field: [messages]}}."""
    response = exception_handler(exc, context)
    if response is None:
        return None

    data = response.data
    code = getattr(exc, "default_code", "error")
    if isinstance(data, dict) and set(data.keys()) <= {"detail", "code"}:
        body = {"detail": str(data.get("detail", "")), "code": str(data.get("code", code)), "errors": {}}
    elif isinstance(data, dict):
        non_field = data.get("non_field_errors")
        detail = str(non_field[0]) if non_field else _("Please correct the errors below.")
        body = {"detail": detail, "code": "invalid", "errors": data}
    else:
        body = {"detail": str(data[0]) if data else "Error", "code": code, "errors": {}}
    response.data = body
    return response
