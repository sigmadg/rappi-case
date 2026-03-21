"""Django settings — dashboard de visualización (caso_tecnico)."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
# Raíz del repo caso_tecnico (padre de django_viz/) — dataset, M1 figures, calibration.json
PROJECT_ROOT = BASE_DIR.parent

SECRET_KEY = "django-insecure-caso-tecnico-demo-only-change-in-production"
DEBUG = True
# En contenedor / acceso por IP de la red local: p. ej. DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,*
_allowed = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,testserver")
ALLOWED_HOSTS = [h.strip() for h in _allowed.split(",") if h.strip()]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "viz",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "ops_site.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "ops_site.wsgi.application"
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}
AUTH_PASSWORD_VALIDATORS = []
LANGUAGE_CODE = "es-es"
TIME_ZONE = "America/Monterrey"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Bootstrap 5: mensajes flash (error → alert-danger)
from django.contrib.messages import constants as message_constants  # noqa: E402

MESSAGE_TAGS = {
    message_constants.ERROR: "danger",
    message_constants.SUCCESS: "success",
    message_constants.WARNING: "warning",
    message_constants.INFO: "info",
}
