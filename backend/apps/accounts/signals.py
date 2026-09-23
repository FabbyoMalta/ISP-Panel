from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver

from .models import SecurityEvent


@receiver(user_logged_in)
def logged_in(sender, user, **kwargs):
    SecurityEvent.objects.create(actor=user, action="login")


@receiver(user_logged_out)
def logged_out(sender, user, **kwargs):
    if user:
        SecurityEvent.objects.create(actor=user, action="logout")


@receiver(user_login_failed)
def failed_login(sender, **kwargs):
    # Do not persist the credentials supplied to this signal.
    SecurityEvent.objects.create(action="login_failed")
