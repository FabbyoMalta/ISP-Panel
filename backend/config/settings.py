import os
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
DEBUG = os.getenv("DEBUG", "false").lower() == "true"
TESTING = os.getenv("TESTING", "false").lower() == "true"
SECRET_KEY = os.getenv("SECRET_KEY", "")
if not SECRET_KEY:
    if DEBUG or TESTING:
        SECRET_KEY = "development-only-not-for-production-isp-panel"
    else:
        raise ImproperlyConfigured("SECRET_KEY deve ser definida fora do código.")
ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1,testserver").split(",")
CSRF_TRUSTED_ORIGINS = [x for x in os.getenv("CSRF_TRUSTED_ORIGINS", "").split(",") if x]
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "drf_spectacular",
    *[
        f"apps.{app}"
        for app in (
            "accounts",
            "tenancy",
            "clients",
            "inventory",
            "assessments",
            "recommendations",
            "risks",
            "metrics",
            "timeline",
            "external_links",
            "audit",
            "portal",
            "integrations",
            "ai_assist",
        )
    ],
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.accounts.middleware.AuthRateLimitMiddleware",
    "apps.tenancy.middleware.TenantMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.portal.middleware.SecurityHeadersMiddleware",
]
ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.portal.context.navigation",
            ]
        },
    }
]
database_url = os.getenv("DATABASE_URL")
if not database_url and not (DEBUG or TESTING):
    raise ImproperlyConfigured("DATABASE_URL PostgreSQL é obrigatória em produção.")
DATABASES = {
    "default": dj_database_url.parse(
        database_url or f"sqlite:///{BASE_DIR / 'dev.sqlite3'}",
        conn_max_age=0,
    )
}
if DATABASES["default"]["ENGINE"] == "django.db.backends.postgresql":
    DATABASES["default"]["TEST"] = {"CHARSET": "UTF8", "TEMPLATE": "template0"}
if not (DEBUG or TESTING) and DATABASES["default"]["ENGINE"] != "django.db.backends.postgresql":
    raise ImproperlyConfigured("Produção exige PostgreSQL e RLS.")
AUTH_USER_MODEL = "accounts.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 12},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]
LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_TZ = True
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
if DEBUG or TESTING:
    STORAGES["staticfiles"]["BACKEND"] = "django.contrib.staticfiles.storage.StaticFilesStorage"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = LOGIN_URL
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = 60 * 60 * 8
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_COOKIE_SECURE = not (DEBUG or TESTING)
CSRF_COOKIE_SECURE = not (DEBUG or TESTING)
SECURE_SSL_REDIRECT = not (DEBUG or TESTING)
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_HSTS_SECONDS = 31536000 if not (DEBUG or TESTING) else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = os.getenv("HSTS_INCLUDE_SUBDOMAINS", "false").lower() == "true"
SECURE_HSTS_PRELOAD = os.getenv("HSTS_PRELOAD", "false").lower() == "true"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
PASSWORD_RESET_TIMEOUT = 3600
EMAIL_BACKEND = os.getenv("EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend")
EMAIL_HOST = os.getenv("EMAIL_HOST", "localhost")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.getenv("EMAIL_USE_TLS", "true").lower() == "true"
# Implicit TLS (port 465, e.g. Titan/GoDaddy) instead of STARTTLS (587).
# Django refuses both at once, so enabling SSL turns STARTTLS off.
EMAIL_USE_SSL = os.getenv("EMAIL_USE_SSL", "false").lower() == "true"
if EMAIL_USE_SSL:
    EMAIL_USE_TLS = False
EMAIL_TIMEOUT = int(os.getenv("EMAIL_TIMEOUT", "15"))
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "portal@localhost")
# apps.integrations.management.commands.sync_netbackup — read-only summary
# pull from NetBackup. Empty by default: the command no-ops (logs a warning,
# writes no IntegrationRun) until both are set, same fail-closed convention
# as the rest of this file's optional integrations.
NETBACKUP_API_URL = os.getenv("NETBACKUP_API_URL", "")
NETBACKUP_API_TOKEN = os.getenv("NETBACKUP_API_TOKEN", "")
# apps.ai_assist.services — OpenRouter chat-completions call for the
# consultant-facing AI assistant. Empty by default: the assistant view
# shows "não configurado" and never calls out until both are set, same
# fail-closed convention as NETBACKUP_API_URL/TOKEN above.
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "")
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
    "EXCEPTION_HANDLER": "apps.portal.api.exception_handler",
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
}
SPECTACULAR_SETTINGS = {
    "TITLE": "ISP Panel API",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "ENUM_NAME_OVERRIDES": {
        "RecommendationStatusEnum": "apps.recommendations.models.Recommendation.Status",
        "ResourceStatusEnum": "apps.inventory.models.Resource.Status",
        "RiskStatusEnum": [("open", "Aberto"), ("mitigated", "Mitigado"), ("accepted", "Aceito")],
        "PriorityEnum": [
            ("critical", "Crítica"),
            ("high", "Alta"),
            ("medium", "Média"),
            ("low", "Baixa"),
        ],
    },
}
