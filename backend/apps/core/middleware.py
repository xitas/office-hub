from django.conf import settings


class SecurityHeadersMiddleware:
    """Adds Content-Security-Policy and Permissions-Policy when configured (production).

    Django's SecurityMiddleware already handles HSTS, X-Content-Type-Options,
    Referrer-Policy and Cross-Origin-Opener-Policy; XFrameOptionsMiddleware adds X-Frame-Options.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        csp = getattr(settings, "CONTENT_SECURITY_POLICY", "")
        if csp and "Content-Security-Policy" not in response:
            response["Content-Security-Policy"] = csp
        permissions = getattr(settings, "PERMISSIONS_POLICY", "")
        if permissions and "Permissions-Policy" not in response:
            response["Permissions-Policy"] = permissions
        return response
