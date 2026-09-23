from django.db import models

from apps.tenancy.models import TenantModel


class Recommendation(TenantModel):
    class Status(models.TextChoices):
        NA = "na", "Não aplicável"
        IDENTIFIED = "identified", "Identificado"
        RECOMMENDED = "recommended", "Recomendado"
        PLANNED = "planned", "Planejado"
        IN_PROGRESS = "in_progress", "Em andamento"
        DONE = "done", "Concluído"
        BLOCKED = "blocked", "Bloqueado"

    title = models.CharField("Melhoria", max_length=180)
    description = models.TextField("Descrição", blank=True)
    category = models.ForeignKey(
        "assessments.AssessmentCategory", on_delete=models.PROTECT, verbose_name="Área"
    )
    priority = models.CharField(
        "Prioridade",
        max_length=10,
        choices=[("critical", "Crítica"), ("high", "Alta"), ("medium", "Média"), ("low", "Baixa")],
        default="medium",
    )
    status = models.CharField(
        "Estado", max_length=20, choices=Status.choices, default=Status.RECOMMENDED
    )
    justification = models.TextField("Justificativa")
    impact = models.TextField("Impacto esperado", blank=True)
    effort = models.CharField("Esforço estimado", max_length=120, blank=True)
    owner = models.CharField("Responsável", max_length=160, blank=True)
    recommended_on = models.DateField("Data recomendada", null=True, blank=True)
    completed_on = models.DateField(null=True, blank=True)
    block_reason = models.TextField("Motivo do bloqueio manual", blank=True)
    client_notes = models.TextField("Observações para o cliente", blank=True)
    internal_notes = models.TextField("Observações internas", blank=True)
    editorial_status = models.CharField(
        "Publicação",
        max_length=12,
        choices=[("draft", "Rascunho"), ("review", "Em revisão"), ("published", "Publicado")],
        default="draft",
    )
    source = models.CharField("Origem", max_length=100, default="Consultor")

    def __str__(self):
        return self.title


class RecommendationDependency(TenantModel):
    recommendation = models.ForeignKey(
        Recommendation, on_delete=models.PROTECT, related_name="dependencies"
    )
    prerequisite = models.ForeignKey(
        Recommendation, on_delete=models.PROTECT, related_name="dependents"
    )

    class Meta(TenantModel.Meta):
        constraints = TenantModel.Meta.constraints + [
            models.UniqueConstraint(
                fields=["recommendation", "prerequisite"], name="unique_dependency"
            ),
            models.CheckConstraint(
                condition=~models.Q(recommendation=models.F("prerequisite")),
                name="no_self_dependency",
            ),
        ]


class RecommendationRisk(TenantModel):
    recommendation = models.ForeignKey(Recommendation, on_delete=models.PROTECT)
    risk = models.ForeignKey("risks.Risk", on_delete=models.PROTECT)

    class Meta(TenantModel.Meta):
        constraints = TenantModel.Meta.constraints + [
            models.UniqueConstraint(
                fields=["recommendation", "risk"], name="unique_recommendation_risk"
            )
        ]


class RoadmapPlacement(TenantModel):
    recommendation = models.OneToOneField(
        Recommendation, on_delete=models.PROTECT, related_name="placement"
    )
    horizon = models.CharField(
        "Horizonte",
        max_length=20,
        choices=[("now", "Agora"), ("next", "A seguir"), ("later", "Futuro")],
        default="next",
    )
    order = models.PositiveIntegerField("Ordem", default=0)
    target_date = models.DateField("Previsão", null=True, blank=True)
