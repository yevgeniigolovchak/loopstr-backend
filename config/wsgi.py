"""
WSGI config for the loopstr project.

It exposes the WSGI callable as a module-level variable named ``application``.
"""

import os
import sys

from django.core.wsgi import get_wsgi_application

# Local apps are imported by bare module name, so the apps directory is on sys.path.
app_path = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir))
sys.path.append(os.path.join(app_path, "loopstr", "apps"))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

application = get_wsgi_application()
