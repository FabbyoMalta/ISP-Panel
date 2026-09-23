from django.db import models

from apps.tenancy.models import TenantModel


class Risk(TenantModel):
    title = models.CharField("Risco", max_length=180)
    severity = models.CharField(
        "Severidade",
        max_length=12,
        choices=[("critical", "Crítica"), ("high", "Alta"), ("medium", "Média"), ("low", "Baixa")],
        default="medium",
    )
    description = models.TextField("Consequência e justificativa")
    status = models.CharField(
        "Situação",
        max_length=12,
        choices=[("open", "Aberto"), ("mitigated", "Mitigado"), ("accepted", "Aceito")],
        default="open",
    )
    owner = models.CharField("Responsável", max_length=160, blank=True)
    published = models.BooleanField("Visível ao cliente", default=False)
    internal_notes = models.TextField("Observações internas", blank=True)

    def __str__(self):
        return self.title
