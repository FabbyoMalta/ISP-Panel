import hashlib
from datetime import timedelta

from django.db import transaction
from django.http import HttpResponse
from django.utils import timezone

from .models import AuthAttempt


class AuthRateLimitMiddleware:
    """DB backed counters, shared by workers. Never stores usernames, IPs or passwords."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method == "POST" and request.path in (
            "/accounts/login/",
            "/accounts/password_reset/",
            "/admin/login/",
        ):
            # Caddy overwrites X-Real-IP; the application port is private in production.
            from django.conf import settings

            ip = request.META.get("REMOTE_ADDR", "unknown")
            if not (settings.DEBUG or settings.TESTING):
                ip = request.META.get("HTTP_X_REAL_IP", ip)
            identity = request.POST.get("username", request.POST.get("email", "")).strip().lower()
            for subject, limit in (("ip:" + ip, 30), ("account:" + identity, 8)):
                key = hashlib.sha256((request.path + subject).encode()).hexdigest()
                with transaction.atomic():
                    attempt, _ = AuthAttempt.objects.get_or_create(
                        key=key, defaults={"window_start": timezone.now()}
                    )
                    attempt = AuthAttempt.objects.select_for_update().get(pk=attempt.pk)
                    if timezone.now() - attempt.window_start > timedelta(minutes=15):
                        attempt.count, attempt.window_start = 0, timezone.now()
                    attempt.count += 1
                    attempt.save()
                    if attempt.count > limit:
                        response = HttpResponse(
                            "Muitas tentativas. Aguarde 15 minutos.", status=429
                        )
                        response["Retry-After"] = "900"
                        return response
        return self.get_response(request)
