from django.conf import settings
from django.contrib import admin
from django.urls import include, path

# Every API app is mounted here with its own sub-namespace, so a reverse reads
# as `api:<app>:<sub>:<name>` — for example `api:users:auth:login`.
api_urls = []

urlpatterns = [
    # Django Admin, use {% url 'admin:index' %}
    path(settings.ADMIN_URL, admin.site.urls),
    # Infrastructure endpoints live off the API prefix: `common:health-check`
    path("", include(("common.urls", "common"), namespace="common")),
    # API urls
    path("api/v1/", include((api_urls, "api"), namespace="api")),
]

# Admin Site Config
# https://docs.djangoproject.com/en/5.2/ref/contrib/admin/#adminsite-attributes
admin.sites.AdminSite.site_header = settings.ADMIN_SITE_HEADER
admin.sites.AdminSite.site_title = settings.ADMIN_SITE_TITLE
