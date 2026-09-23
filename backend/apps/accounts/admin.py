from django.contrib import admin

from apps.assessments.admin import CatalogAdmin

from .models import SecurityEvent


@admin.register(SecurityEvent)
class SecurityEventAdmin(CatalogAdmin):
    list_display = ["created_at", "actor", "action", "object_id"]
    readonly_fields = ["created_at", "actor", "action", "object_id", "details"]

    def has_add_permission(self, request):
        return False
