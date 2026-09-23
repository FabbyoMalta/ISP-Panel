from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = "admin", "Administrador"
        CONSULTANT = "consultant", "Consultor"
        CLIENT = "client", "Cliente"

    email = models.EmailField(unique=True)
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.CLIENT)

    @property
    def is_consultant(self):
        return self.is_active and (self.is_superuser or self.role in ("admin", "consultant"))

    @property
    def is_administrator(self):
        return self.is_active and (self.is_superuser or self.role == "admin")


class AuthAttempt(models.Model):
    key = models.CharField(max_length=64, unique=True)
    count = models.PositiveIntegerField(default=0)
    window_start = models.DateTimeField()


class SecurityEvent(models.Model):
    actor = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True)
    action = models.CharField(max_length=80)
    object_id = models.CharField(max_length=64, blank=True)
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
