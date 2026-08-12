from django.urls import include, path

from users.views import CurrentUserView, ForgotPasswordView, LoginView, RegisterView

# No trailing slashes. `APPEND_SLASH = False`, so a redirect never happens and the contract's
# `/auth/login` would 404 against a route registered as `auth/login/`.
auth_urlpatterns = (
    [
        path("login", LoginView.as_view(), name="login"),
        path("register", RegisterView.as_view(), name="register"),
        path("forgot-password", ForgotPasswordView.as_view(), name="forgot-password"),
    ],
    "auth",
)

urlpatterns = [
    path("auth/", include(auth_urlpatterns)),
    # Outside `/auth/`, and outside its sub-namespace with it: this reads the account behind a
    # session rather than establishing one, and answers a failure in the project's DRF shapes
    # instead of the contract's error envelope. Registered without a trailing slash for the same
    # reason the auth routes are — `APPEND_SLASH = False` redirects nothing.
    path("users/me", CurrentUserView.as_view(), name="current-user"),
]
