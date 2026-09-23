from collections import defaultdict

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.services import record
from apps.portal.services import lock_tenant, require_consultant, save_record
from apps.timeline.models import Event

from .models import (
    Assessment,
    AssessmentAnswer,
    AssessmentItemDefinition,
    AssessmentTemplateVersion,
    MaturityLevel,
)


def publish_catalog(actor, name="Avaliação estratégica"):
    if not actor.is_administrator:
        raise PermissionDenied
    items = list(AssessmentItemDefinition.objects.filter(active=True).select_related("category"))
    if not items:
        raise ValidationError("Cadastre critérios antes de publicar uma metodologia.")
    keys = {str(item.pk) for item in items}
    levels = []
    for level in MaturityLevel.objects.all():
        requirements = [
            str(key) for key in level.maturityrule_set.values_list("item_id", flat=True)
        ]
        if not requirements or not set(requirements) <= keys:
            raise ValidationError(f"O nível {level.name} precisa de critérios obrigatórios ativos.")
        levels.append({"name": level.name, "order": level.order, "requirements": requirements})
    snapshot = {
        "method": "weighted-v1",
        "levels": levels,
        "items": [
            {
                "key": str(item.pk),
                "title": item.title,
                "guidance": item.guidance,
                "category": item.category.name,
                "weight": item.weight,
            }
            for item in items
        ],
    }
    return AssessmentTemplateVersion.objects.create(name=name, snapshot=snapshot)


@transaction.atomic
def start_assessment(actor, title, assessed_on, template, summary="", internal_notes=""):
    require_consultant(actor)
    tenant = lock_tenant()
    return save_record(
        actor,
        Assessment(
            tenant=tenant,
            title=title,
            assessed_on=assessed_on,
            template=template,
            summary=summary,
            internal_notes=internal_notes,
            author=actor,
        ),
    )


@transaction.atomic
def answer_assessment(actor, assessment, item_key, status, comment="", internal_notes=""):
    require_consultant(actor)
    lock_tenant()
    assessment = Assessment.objects.get(pk=assessment.pk)
    if assessment.published_at:
        raise ValidationError("Avaliação publicada não pode ser alterada.")
    answer = AssessmentAnswer.objects.filter(assessment=assessment, item_key=item_key).first()
    if not answer:
        answer = AssessmentAnswer(
            tenant=assessment.tenant, assessment=assessment, item_key=item_key
        )
    answer.status, answer.comment, answer.internal_notes = status, comment, internal_notes
    return save_record(actor, answer)


def calculate(assessment):
    answers = {a.item_key: a for a in assessment.answers.all()}
    items = assessment.template.snapshot["items"]
    if not items or set(answers) != {item["key"] for item in items}:
        raise ValidationError("Responda todos os critérios antes de publicar.")
    areas = defaultdict(lambda: {"points": 0, "weight": 0, "applicable": 0, "total": 0})
    values = {"met": 1, "partial": 0.5, "unmet": 0}
    for item in items:
        answer = answers[item["key"]]
        area = areas[item["category"]]
        area["total"] += 1
        if answer.status != "na":
            area["points"] += values[answer.status] * item["weight"]
            area["weight"] += item["weight"]
            area["applicable"] += 1
    result = {"areas": [], "level": "Em desenvolvimento", "pending": []}
    for name, area in areas.items():
        result["areas"].append(
            {
                "name": name,
                "score": round(100 * area["points"] / area["weight"]) if area["weight"] else None,
                "applicable": area["applicable"],
                "total": area["total"],
            }
        )
    by_key = {item["key"]: item["title"] for item in items}
    for level in assessment.template.snapshot["levels"]:
        missing = [key for key in level["requirements"] if answers[key].status != "met"]
        if missing:
            result["pending"] = [by_key[key] for key in missing]
            break
        result["level"] = level["name"]
    return result


@transaction.atomic
def publish_assessment(actor, assessment):
    require_consultant(actor)
    lock_tenant()
    assessment = Assessment.objects.get(pk=assessment.pk)
    if assessment.published_at:
        raise ValidationError("Avaliação já publicada.")
    assessment.result = calculate(assessment)
    assessment.published_at = timezone.now()
    assessment.save()
    Event.objects.create(
        tenant=assessment.tenant,
        title=f"Avaliação publicada: {assessment.title}",
        occurred_on=timezone.localdate(),
        published=True,
    )
    record(actor, "assessment_published", assessment, assessment.result)
    return assessment
