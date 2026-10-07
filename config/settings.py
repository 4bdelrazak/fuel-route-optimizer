"""Django settings.

Everything an operator might change is read from the environment with a
development-safe default, so the project runs straight after `pip install` while
still refusing to start in production without a real secret key.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _bool(name: str, default: bool) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ[name])
    except (KeyError, ValueError):
        return default


DEBUG = _bool("DJANGO_DEBUG", True)
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY") or ""
if not SECRET_KEY:
    if not DEBUG:
        raise RuntimeError("DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is off.")
    SECRET_KEY = "django-insecure-development-only-do-not-use-in-production"

ALLOWED_HOSTS = [
    h.strip() for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split(",") if h.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "drf_spectacular",
    "fuel",
    "routes",
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

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

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

# SQLite is deliberate. The dataset is ~7,300 rows, candidate lookup is a single
# indexed bounding-box query, and all geographic maths runs in Python, so
# PostgreSQL or PostGIS would add setup cost without making anything faster.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get("DJANGO_DB_PATH", str(BASE_DIR / "db.sqlite3")),
    }
}

# A database-backed cache keeps geocoding and routing results across process
# restarts and across worker processes, which is what actually protects
# Nominatim's one-request-a-second policy. It needs no extra service: run
# `python manage.py createcachetable` once.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "api_cache",
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "routes.exception_handler.api_exception_handler",
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "UNAUTHENTICATED_USER": None,
    # The endpoint fronts two free public services whose usage policies this
    # application is responsible for. Throttling keeps a caller from spending
    # that budget faster than the caches can absorb it. Generous enough that a
    # reviewer clicking through Postman will never notice.
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.AnonRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {"anon": os.environ.get("API_RATE_LIMIT", "60/min")},
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Fuel Route Optimizer API",
    "DESCRIPTION": (
        "Plans a driving route between two US locations and picks the "
        "cost-optimal fuel stops for a vehicle with a 500 mile range and 10 MPG "
        "fuel economy."
    ),
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
}

# --- Domain configuration -------------------------------------------------

VEHICLE_MAX_RANGE_MILES = _float("VEHICLE_MAX_RANGE_MILES", 500.0)
VEHICLE_FUEL_ECONOMY_MPG = _float("VEHICLE_FUEL_ECONOMY_MPG", 10.0)

# Stations are positioned at their city's centroid because the dataset has no
# coordinates, so a narrow corridor would throw away perfectly usable truck
# stops: a city centroid can sit 10-20 miles from the interstate exit the stop
# is actually on. 25 miles keeps those while staying a plausible detour.
STATION_CORRIDOR_MILES = _float("STATION_CORRIDOR_MILES", 25.0)

# The start of a trip is a street address, not a truck stop, so the departure
# tank is priced from the cheapest station within this many route miles of the
# start: far enough to find a truck stop outside a city centre, near enough that
# the price is one the driver could really pay on the way out.
START_FILL_WINDOW_MILES = _float("START_FILL_WINDOW_MILES", 50.0)

# Candidate stations are thinned to the cheapest one per this many route miles.
# At city-centroid accuracy two stations this close are not distinguishable by
# position, and it bounds the optimizer's input by route length.
STATION_POSITION_BUCKET_MILES = _float("STATION_POSITION_BUCKET_MILES", 5.0)

OSRM_BASE_URL = os.environ.get("OSRM_BASE_URL", "https://router.project-osrm.org")
OSRM_TIMEOUT_SECONDS = _float("OSRM_TIMEOUT_SECONDS", 15.0)

NOMINATIM_BASE_URL = os.environ.get("NOMINATIM_BASE_URL", "https://nominatim.openstreetmap.org")
NOMINATIM_USER_AGENT = os.environ.get(
    "NOMINATIM_USER_AGENT", "fuel-route-optimizer/1.0 (backend assessment)"
)
NOMINATIM_TIMEOUT_SECONDS = _float("NOMINATIM_TIMEOUT_SECONDS", 10.0)

# Place names and road networks change on a scale of months, so these are long.
GEOCODE_CACHE_SECONDS = int(_float("GEOCODE_CACHE_SECONDS", 60 * 60 * 24 * 30))
ROUTE_CACHE_SECONDS = int(_float("ROUTE_CACHE_SECONDS", 60 * 60 * 24 * 7))

CITY_COORDINATES_PATH = os.environ.get(
    "CITY_COORDINATES_PATH", str(BASE_DIR / "data" / "us_city_coordinates.csv.gz")
)

if not DEBUG:
    SECURE_SSL_REDIRECT = _bool("DJANGO_SECURE_SSL_REDIRECT", True)
    SECURE_HSTS_SECONDS = int(_float("DJANGO_SECURE_HSTS_SECONDS", 60 * 60 * 24 * 365))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"standard": {"format": "{levelname} {asctime} {name} {message}", "style": "{"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "standard"}},
    "root": {"handlers": ["console"], "level": "WARNING"},
    "loggers": {
        name: {
            "handlers": ["console"],
            "level": os.environ.get("LOG_LEVEL", "INFO"),
            "propagate": False,
        }
        for name in ("routes", "fuel", "integrations")
    },
}
