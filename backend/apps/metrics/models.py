from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models

from apps.tenancy.models import TenantModel


class MetricDefinition(models.Model):
    key = models.SlugField(unique=True)
    name = models.CharField("Métrica", max_length=150)
    unit = models.CharField("Unidade", max_length=40)

    def __str__(self):
        return f"{self.name} ({self.unit})"


class MetricObservation(TenantModel):
    definition = models.ForeignKey(
        MetricDefinition, on_delete=models.PROTECT, verbose_name="Métrica"
    )
    value = models.DecimalField(
        "Valor", max_digits=16, decimal_places=3, validators=[MinValueValidator(0)]
    )
    observed_at = models.DateTimeField("Data da observação")
    source = models.CharField("Fonte", max_length=180, default="Registro manual")
    assumptions = models.TextField("Premissas e contexto", blank=True)
    estimated = models.BooleanField("Estimativa", default=False)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    published = models.BooleanField("Visível ao cliente", default=False)

    class Meta(TenantModel.Meta):
        ordering = ["-observed_at", "-created_at"]
        indexes = [models.Index(fields=["tenant", "definition", "observed_at"])]

    def __str__(self):
        return f"{self.definition}: {self.value}"

    def clean(self):
        super().clean()
        if self.estimated and not self.assumptions.strip():
            raise ValidationError({"assumptions": "Documente as premissas da estimativa."})
        if self.pk and MetricObservation.objects.filter(pk=self.pk).exists():
            raise ValidationError("Métricas são históricas. Registre uma nova observação.")
