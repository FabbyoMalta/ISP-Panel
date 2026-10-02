from django.contrib import admin

from apps.accounts.admin import SecurityEventAdmin
from apps.assessments.admin import CatalogAdmin

from .models import ExternalObjectMapping, IntegrationRun


@admin.register(ExternalObjectMapping)
class ExternalObjectMappingAdmin(CatalogAdmin):
    list_display = ["system", "external_id", "tenant"]
    list_filter = ["system"]


@admin.register(IntegrationRun)
class IntegrationRunAdmin(SecurityEventAdmin):
    list_display = ["started_at", "system", "status", "tenants_succeeded", "tenants_failed"]
    list_filter = ["system", "status"]
    readonly_fields = [
        "system",
        "started_at",
        "finished_at",
        "status",
        "tenants_considered",
        "tenants_matched",
        "tenants_succeeded",
        "tenants_failed",
        "error",
        "details",
    ]
