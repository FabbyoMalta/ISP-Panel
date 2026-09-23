from django.db import models

from apps.tenancy.models import TenantModel


class Event(TenantModel):
    title = models.CharField("Marco de evolução", max_length=200)
    description = models.TextField("Descrição", blank=True)
    occurred_on = models.DateField("Data")
    published = models.BooleanField("Visível ao cliente", default=False)
    recommendation = models.ForeignKey(
        "recommendations.Recommendation", on_delete=models.PROTECT, null=True, blank=True
    )

    class Meta(TenantModel.Meta):
        ordering = ["-occurred_on", "-created_at"]

    def __str__(self):
        return self.title
