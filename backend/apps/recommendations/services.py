from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.services import record
from apps.portal.services import lock_tenant, require_consultant
from apps.timeline.models import Event

from .models import Recommendation, RecommendationDependency


def pending_dependencies(recommendation):
    return recommendation.dependencies.exclude(prerequisite__status="done")


@transaction.atomic
def add_dependency(actor, recommendation, prerequisite):
    require_consultant(actor)
    lock_tenant()
    recommendation = Recommendation.objects.get(pk=recommendation.pk)
    prerequisite = Recommendation.objects.get(pk=prerequisite.pk)
    if recommendation.pk == prerequisite.pk:
        raise ValidationError("Uma melhoria não pode depender de si mesma.")
    if recommendation.status in ("in_progress", "done"):
        raise ValidationError("Replaneje a melhoria antes de alterar seus pré-requisitos.")
    graph = {}
    for left, right in RecommendationDependency.objects.values_list(
        "recommendation_id", "prerequisite_id"
    ):
        graph.setdefault(left, []).append(right)
    queue, visited = [prerequisite.pk], set()
    while queue:
        node = queue.pop()
        if node == recommendation.pk:
            raise ValidationError("Esta dependência criaria um ciclo no roadmap.")
        if node not in visited:
            visited.add(node)
            queue.extend(graph.get(node, []))
    edge, created = RecommendationDependency.objects.get_or_create(
        tenant_id=recommendation.tenant_id,
        recommendation=recommendation,
        prerequisite=prerequisite,
    )
    if created:
        record(actor, "dependency_added", edge, {"prerequisite": str(prerequisite.pk)})
    return edge


@transaction.atomic
def remove_dependency(actor, dependency):
    require_consultant(actor)
    lock_tenant()
    dependency = RecommendationDependency.objects.get(pk=dependency.pk)
    if dependency.recommendation.status in ("in_progress", "done"):
        raise ValidationError("Replaneje a melhoria antes de remover dependências.")
    record(actor, "dependency_removed", dependency)
    dependency.delete()


@transaction.atomic
def transition(actor, recommendation, status, reason=""):
    require_consultant(actor)
    lock_tenant()
    recommendation = Recommendation.objects.get(pk=recommendation.pk)
    if status not in Recommendation.Status.values:
        raise ValidationError("Estado inválido.")
    before = recommendation.status
    if status == before:
        return recommendation
    if (
        before == "done"
        and recommendation.dependents.filter(
            recommendation__status__in=["in_progress", "done"]
        ).exists()
    ):
        raise ValidationError(
            "Replaneje primeiro as melhorias dependentes em andamento ou concluídas."
        )
    if status in ("in_progress", "done") and pending_dependencies(recommendation).exists():
        raise ValidationError(
            "Conclua os pré-requisitos antes de iniciar ou concluir esta melhoria."
        )
    if status in ("blocked", "na") and not reason.strip():
        raise ValidationError("Informe o motivo do bloqueio ou da não aplicabilidade.")
    if before == "blocked" and status in ("in_progress", "done"):
        raise ValidationError("Remova o bloqueio manual retornando a melhoria para planejado.")
    recommendation.status = status
    recommendation.block_reason = reason if status in ("blocked", "na") else ""
    recommendation.completed_on = timezone.localdate() if status == "done" else None
    recommendation.save()
    if status == "done":
        Event.objects.create(
            tenant=recommendation.tenant,
            title=recommendation.title,
            description="Melhoria concluída pela consultoria.",
            occurred_on=recommendation.completed_on,
            published=recommendation.editorial_status == "published",
            recommendation=recommendation,
        )
    elif before == "done":
        Event.objects.create(
            tenant=recommendation.tenant,
            title=f"Replanejamento: {recommendation.title}",
            occurred_on=timezone.localdate(),
            published=recommendation.editorial_status == "published",
            recommendation=recommendation,
        )
    record(
        actor,
        "status_changed",
        recommendation,
        {"before": before, "after": status, "reason": reason},
    )
    return recommendation
