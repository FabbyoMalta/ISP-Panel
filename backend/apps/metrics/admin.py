from django.contrib import admin

from apps.assessments.admin import CatalogAdmin

from .models import MetricDefinition

admin.site.register(MetricDefinition, CatalogAdmin)
