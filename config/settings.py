import sys

from django.core.exceptions import ImproperlyConfigured

import environ

# loopstr/config/settings.py - 2 = loopstr/
ROOT_DIR = environ.Path(__file__) - 2
APPS_DIR = ROOT_DIR.path("loopstr")

# Local apps are imported by bare module name: `from users.models import User`
sys.path.append("loopstr/apps")

# Environment
# https://django-environ.readthedocs.io/en/latest/#how-to-use
# ------------------------------------------------------------------------------
# Default values and casting
env = environ.Env(
    DJANGO_DEBUG=(bool, False),
    DJANGO_SECRET_KEY=(str, ""),
    DJANGO_ALLOWED_HOSTS=(list, []),
    # Static
    DJANGO_STATIC_ROOT=(str, str(APPS_DIR("staticfiles"))),
    # Database
    POSTGRES_HOST=(str, "db"),
    POSTGRES_PORT=(int, 5432),
    POSTGRES_DB=(str, ""),
    POSTGRES_USER=(str, ""),
    POSTGRES_PASSWORD=(str, ""),
    # Django REST Framework
    DRF_ENABLE_BROWSABLE_API_RENDERER=(bool, False),
    DRF_PAGE_SIZE=(int, 20),
    # API documentation
    DJANGO_API_DOCS_ENABLED=(bool, True),
    # Sessions
    DJANGO_SESSION_COOKIE_SECURE=(bool, True),
    DJANGO_SESSION_COOKIE_AGE=(int, 60 * 60 * 24 * 30),
    # Cross-origin requests
    DJANGO_CORS_ALLOWED_ORIGINS=(list, []),
    DJANGO_CSRF_TRUSTED_ORIGINS=(list, []),
    # Authentication
    DJANGO_AUTH_LOCKOUT_MAX_ATTEMPTS=(int, 5),
    DJANGO_AUTH_LOCKOUT_MINUTES=(int, 15),
)

# Django Core
# https://docs.djangoproject.com/en/5.2/ref/settings/#core-settings
# ------------------------------------------------------------------------------
DEBUG = env.bool("DJANGO_DEBUG")
SECRET_KEY = env("DJANGO_SECRET_KEY")
ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS")
ADMIN_URL = "admin/"
ADMIN_SITE_TITLE = "loopstr"
ADMIN_SITE_HEADER = "loopstr"
TIME_ZONE = "UTC"
USE_TZ = True
LANGUAGE_CODE = "en-us"
USE_I18N = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
APPEND_SLASH = False
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Django Database
# https://docs.djangoproject.com/en/5.2/ref/settings/#databases
# ------------------------------------------------------------------------------
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB"),
        "USER": env("POSTGRES_USER"),
        "PASSWORD": env("POSTGRES_PASSWORD"),
        "HOST": env("POSTGRES_HOST"),
        "PORT": env("POSTGRES_PORT"),
    },
}

# Django Applications
# https://docs.djangoproject.com/en/5.2/ref/settings/#installed-apps
# ------------------------------------------------------------------------------
DJANGO_APPS = (
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.admin",
)
THIRD_PARTY_APPS = (
    "corsheaders",
    "rest_framework",
    "drf_spectacular",
    # Ships the Swagger UI assets as static files, so the docs page loads nothing from a CDN.
    "drf_spectacular_sidecar",
)
LOCAL_APPS = (
    "common.apps.CommonConfig",
    "users.apps.UsersAppConfig",
)
INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# Django Middlewares
# https://docs.djangoproject.com/en/5.2/ref/settings/#middleware
# ------------------------------------------------------------------------------
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # Above CommonMiddleware on purpose: that one answers some requests itself, and a response
    # generated before this middleware runs would go out without the CORS headers.
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# Django Templates
# https://docs.djangoproject.com/en/5.2/ref/settings/#templates
# ------------------------------------------------------------------------------
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [
            str(APPS_DIR.path("templates")),
        ],
        "OPTIONS": {
            "debug": DEBUG,
            "loaders": [
                "django.template.loaders.filesystem.Loader",
                "django.template.loaders.app_directories.Loader",
            ],
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.template.context_processors.i18n",
                "django.template.context_processors.static",
                "django.template.context_processors.tz",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# Django Password Management
# https://docs.djangoproject.com/en/5.2/topics/auth/passwords/#enabling-password-validation
# ------------------------------------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Django Static Files
# https://docs.djangoproject.com/en/5.2/ref/settings/#static-files
# ------------------------------------------------------------------------------
STATIC_URL = "/static/"
STATIC_ROOT = env("DJANGO_STATIC_ROOT")
STATICFILES_DIRS = (str(APPS_DIR.path("static")),)
STATICFILES_FINDERS = (
    "django.contrib.staticfiles.finders.FileSystemFinder",
    "django.contrib.staticfiles.finders.AppDirectoriesFinder",
)

# Django Auth
# https://docs.djangoproject.com/en/5.2/ref/settings/#auth
# ------------------------------------------------------------------------------
AUTH_USER_MODEL = "users.User"

# docs/auth-api.md fixes the cookie flags, so only `SECURE` is a variable: hardcoding it True
# breaks local development, which speaks HTTP and would never get the cookie back, and hardcoding
# it False ships a session readable off the wire. It defaults to True so an environment that
# forgets the variable fails closed.
SESSION_COOKIE_SECURE = env.bool("DJANGO_SESSION_COOKIE_SECURE")
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
# What "remember me" sets the session expiry to (ACC-01 #7). Without it the login view leaves the
# session at browser-close, which is the unchecked case.
SESSION_COOKIE_AGE = env.int("DJANGO_SESSION_COOKIE_AGE")

# ACC-01 #6: five consecutive failures lock the account for fifteen minutes. This is state on the
# user row, not a DRF throttle — a throttle counts requests per client and cannot express "this
# account", and there is no Redis here to hold a shared counter.


# Neither value has a meaningful reading below 1, and a wrong one is invisible until somebody fails
# a login: `MAX_ATTEMPTS = 0` is compared against an already-incremented counter, so one typo locks
# the account, and `MINUTES = 0` sets the lock to a moment that has already passed — the policy
# reads as configured and does nothing. A plausible way to reach either is guessing that 0 turns
# the feature off. This fails the process instead, at startup, naming the variable.
def positive_int(name, value):
    if value < 1:
        raise ImproperlyConfigured(f"{name} must be 1 or greater; got {value}.")

    return value


AUTH_LOCKOUT_MAX_ATTEMPTS = positive_int(
    "DJANGO_AUTH_LOCKOUT_MAX_ATTEMPTS",
    env.int("DJANGO_AUTH_LOCKOUT_MAX_ATTEMPTS"),
)
AUTH_LOCKOUT_MINUTES = positive_int(
    "DJANGO_AUTH_LOCKOUT_MINUTES",
    env.int("DJANGO_AUTH_LOCKOUT_MINUTES"),
)

# Cross-Origin Requests
# https://github.com/adamchainz/django-cors-headers
# ------------------------------------------------------------------------------
# The frontend runs on its own origin and sends `credentials: "include"`, so the session cookie
# only survives the round trip while the response carries `Access-Control-Allow-Credentials`.
# That header is incompatible with a wildcard origin, which is why this is an explicit list and
# not `CORS_ALLOW_ALL_ORIGINS`.
CORS_ALLOWED_ORIGINS = env.list("DJANGO_CORS_ALLOWED_ORIGINS")
CORS_ALLOW_CREDENTIALS = True

# The `/auth/*` endpoints declare no authenticator, so CSRF never runs on them. Everything
# reachable after login keeps `SessionAuthentication` and therefore keeps CSRF, and Django matches
# the `Origin` header of those requests against this list.
CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS")

# Django REST Framework
# https://www.django-rest-framework.org/api-guide/settings/
# ------------------------------------------------------------------------------
PAGE_SIZE = env.int("DRF_PAGE_SIZE")
REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "PAGE_SIZE": PAGE_SIZE,
    "TEST_REQUEST_DEFAULT_FORMAT": "json",
}
if env.bool("DRF_ENABLE_BROWSABLE_API_RENDERER"):
    REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"].append("rest_framework.renderers.BrowsableAPIRenderer")

# API Documentation
# https://drf-spectacular.readthedocs.io/en/latest/settings.html
# ------------------------------------------------------------------------------
# The frontend team reads `/docs/` and `/schema/` in this PoC, so they are on by default; the
# flag exists so a deployment can take them down without a code change.
API_DOCS_ENABLED = env.bool("DJANGO_API_DOCS_ENABLED")
SPECTACULAR_SETTINGS = {
    "TITLE": "loopstr API",
    "VERSION": "v1",
    # The schema endpoint documents the API, not itself.
    "SERVE_INCLUDE_SCHEMA": False,
    # Serve the Swagger UI from `drf_spectacular_sidecar` inside our own image; the default
    # points at a CDN, which a deployment behind a firewall cannot reach.
    "SWAGGER_UI_DIST": "SIDECAR",
    "SWAGGER_UI_FAVICON_HREF": "SIDECAR",
    # This setting replaces the package default rather than extending it, so the enum hook is
    # re-listed here — dropping it would inline every enum instead of naming it as a component.
    "POSTPROCESSING_HOOKS": [
        "drf_spectacular.hooks.postprocess_schema_enums",
        "common.schema.add_contract_components",
    ],
}

# Django Logging
# https://docs.djangoproject.com/en/5.2/ref/settings/#logging
# ------------------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "%(levelname)s %(asctime)s %(module)s %(process)d %(thread)d %(message)s",
        },
    },
    "handlers": {
        "console": {
            "level": "DEBUG",
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "propagate": True,
            "level": "INFO",
        },
        # The authentication audit trail is logged at INFO. Without an entry here the lines would
        # reach a root logger that has no handler and go nowhere.
        "users": {
            "handlers": ["console"],
            "propagate": True,
            "level": "INFO",
        },
    },
}
