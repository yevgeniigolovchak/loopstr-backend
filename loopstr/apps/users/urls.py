from django.urls import include, path

from users.views import ForgotPasswordView, LoginView

# No trailing slashes. `APPEND_SLASH = False`, so a redirect never happens and the contract's
# `/auth/login` would 404 against a route registered as `auth/login/`.
auth_urlpatterns = (
    [
        path("login", LoginView.as_view(), name="login"),
        path("forgot-password", ForgotPasswordView.as_view(), name="forgot-password"),
    ],
    "auth",
)

urlpatterns = [
    path("auth/", include(auth_urlpatterns)),
]
