from django.contrib import admin, messages
from django.core.exceptions import ValidationError

from .models import (
    AssessmentCategory,
    AssessmentItemDefinition,
    AssessmentTemplateVersion,
    MaturityLevel,
    MaturityRule,
)
from .services import publish_catalog


class CatalogAdmin(admin.ModelAdmin):
    def has_module_permission(self, request):
        return request.user.is_administrator

    def has_view_permission(self, request, obj=None):
        return request.user.is_administrator

    def has_add_permission(self, request):
        return request.user.is_administrator

    def has_change_permission(self, request, obj=None):
        return request.user.is_administrator

    def has_delete_permission(self, request, obj=None):
        return False


@admin.action(description="Publicar nova versão completa da metodologia")
def publish(modeladmin, request, queryset):
    try:
        version = publish_catalog(request.user)
        modeladmin.message_user(request, f"Metodologia publicada: {version}", messages.SUCCESS)
    except ValidationError as error:
        modeladmin.message_user(request, " ".join(error.messages), messages.ERROR)


@admin.register(AssessmentItemDefinition)
class ItemAdmin(CatalogAdmin):
    list_display = ["title", "category", "weight", "active"]
    list_filter = ["category", "active"]
    actions = [publish]


@admin.register(AssessmentTemplateVersion)
class VersionAdmin(CatalogAdmin):
    list_display = ["name", "created_at"]
    readonly_fields = ["name", "snapshot", "created_at"]

    def has_add_permission(self, request):
        return False


for model in [AssessmentCategory, MaturityLevel, MaturityRule]:
    admin.site.register(model, CatalogAdmin)
admin.site.site_header = "ISP Panel · Administração de catálogos"
admin.site.site_title = "ISP Panel"
