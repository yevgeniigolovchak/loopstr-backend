from django.conf import settings
from django.urls import path

from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.permissions import AllowAny

from common.views import HealthCheckView

urlpatterns = [
    path("health-check/", HealthCheckView.as_view(), name="health-check"),
]

# The pages describe `/api/v1/`, so mounting them inside it would version the documentation along
# with the API it documents. They are registered only when the flag is on: a deployment that turns
# it off gets a 404 rather than a page it has to protect.
#
# `AllowAny` and the empty authentication are spelled out because DRF defaults to
# `IsAuthenticated` here — left implicit, the documentation would ask for credentials that the auth
# story has not shipped yet.
if settings.API_DOCS_ENABLED:
    urlpatterns += [
        path(
            "schema/",
            SpectacularAPIView.as_view(authentication_classes=(), permission_classes=(AllowAny,)),
            name="schema",
        ),
        path(
            "docs/",
            SpectacularSwaggerView.as_view(
                url_name="common:schema",
                authentication_classes=(),
                permission_classes=(AllowAny,),
            ),
            name="docs",
        ),
    ]
