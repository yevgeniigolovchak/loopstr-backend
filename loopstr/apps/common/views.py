from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView


# The response is built by hand, so the generator has no serializer to read and would fall back to
# an empty, warning-producing body. Declaring it keeps the published document honest.
@extend_schema(
    summary="Liveness probe",
    description="Answers 200 while the process can serve a request. Unauthenticated, and outside the "
    "API version prefix, so a probe does not have to track either.",
    responses={
        status.HTTP_200_OK: inline_serializer(
            name="HealthCheck",
            fields={"status": serializers.CharField()},
        ),
    },
)
class HealthCheckView(APIView):
    """Liveness probe — answers 200 while the process can serve a request."""

    authentication_classes = ()
    permission_classes = (AllowAny,)

    def get(self, request, *args, **kwargs):
        return Response({"status": "ok"}, status=status.HTTP_200_OK)
