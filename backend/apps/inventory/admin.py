from django.contrib import admin

from apps.assessments.admin import CatalogAdmin

from .models import ResourceType

admin.site.register(ResourceType, CatalogAdmin)
