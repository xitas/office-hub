from drf_spectacular.utils import extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import module_permission

from . import registry


class DashboardView(APIView):
    permission_classes = [module_permission("dashboard", "view")]

    @extend_schema(responses={200: dict})
    def get(self, request):
        return Response(registry.build(request.user))
