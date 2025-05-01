import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE", "wall_project.settings"
)  # Updated project name
application = get_wsgi_application()
