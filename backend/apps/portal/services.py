import json

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.forms.models import model_to_dict

from apps.audit.services import record
from apps.tenancy.context import current_tenant
from apps.tenancy.models import Tenant


def require_consultant(actor):
    if not actor.is_consultant:
        raise PermissionDenied("Somente a consultoria pode alterar dados.")


def lock_tenant():
    return Tenant.objects.select_for_update().get(pk=current_tenant.get(), active=True)


@transaction.atomic
def save_record(actor, obj):
    require_consultant(actor)
    lock_tenant()
    previous = type(obj).objects.filter(pk=obj.pk).first()
    before = model_to_dict(previous) if previous else {}
    obj.save()
    after = model_to_dict(obj)
    changes = {
        key: {"before": before.get(key), "after": value}
        for key, value in after.items()
        if before.get(key) != value
    }
    record(
        actor,
        "updated" if previous else "created",
        obj,
        json.loads(json.dumps(changes, default=str)),
    )
    return obj


def visible(queryset, user):
    if user.is_consultant:
        return queryset
    model = queryset.model
    names = {field.name for field in model._meta.fields}
    if "published" in names:
        return queryset.filter(published=True)
    if "published_at" in names:
        return queryset.filter(published_at__isnull=False)
    if "editorial_status" in names:
        return queryset.filter(editorial_status="published")
    if model._meta.model_name == "assessmentanswer":
        return queryset.filter(assessment__published_at__isnull=False)
    if model._meta.model_name == "recommendationdependency":
        return queryset.filter(
            recommendation__editorial_status="published", prerequisite__editorial_status="published"
        )
    if model._meta.model_name == "roadmapplacement":
        return queryset.filter(recommendation__editorial_status="published")
    if model._meta.model_name == "recommendationrisk":
        return queryset.filter(recommendation__editorial_status="published", risk__published=True)
    if model._meta.model_name == "auditentry":
        return queryset.none()
    return queryset


def check_metric(obj):
    if obj.estimated and not obj.assumptions.strip():
        raise ValidationError({"assumptions": "Documente as premissas da estimativa."})
