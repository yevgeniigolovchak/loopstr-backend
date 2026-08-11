import importlib

from django.urls import clear_url_caches

import pytest

import common.urls
import config.urls


def _reload_urlconf():
    """Rebuild the URLconf so a changed `API_DOCS_ENABLED` takes effect.

    The docs routes are decided at import time and Django imports a URLconf once per process, so
    flipping the setting on its own changes nothing. `config.urls` is reloaded as well: its
    `include()` holds a resolver that has already cached the patterns it read from `common.urls`.
    """
    importlib.reload(common.urls)
    importlib.reload(config.urls)
    clear_url_caches()


@pytest.fixture
def api_docs_disabled(settings):
    """Serve the project as a deployment with `DJANGO_API_DOCS_ENABLED` turned off would."""
    original = settings.API_DOCS_ENABLED

    settings.API_DOCS_ENABLED = False
    _reload_urlconf()

    yield

    settings.API_DOCS_ENABLED = original
    _reload_urlconf()
