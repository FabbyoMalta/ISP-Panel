from django.core.exceptions import ValidationError
from django.db import models

from apps.tenancy.models import TenantModel


class ResourceType(models.Model):
    name = models.CharField("Nome", max_length=100, unique=True)
    attribute_keys = models.JSONField("Atributos permitidos", default=list, blank=True)

    def __str__(self):
        return self.name


class Resource(TenantModel):
    class Status(models.TextChoices):
        ACTIVE = "active", "Ativo"
        PARTIAL = "partial", "Parcial"
        INACTIVE = "inactive", "Inativo"

    type = models.ForeignKey(ResourceType, verbose_name="Tipo", on_delete=models.PROTECT)
    name = models.CharField("Recurso", max_length=180)
    status = models.CharField(
        "Situação", max_length=16, choices=Status.choices, default=Status.ACTIVE
    )
    description = models.TextField("Descrição técnica", blank=True)
    capacity_gbps = models.DecimalField(
        "Capacidade (Gbps)", max_digits=12, decimal_places=3, null=True, blank=True
    )
    attributes = models.JSONField("Atributos específicos (JSON)", default=dict, blank=True)
    source = models.CharField("Fonte", max_length=150, default="Consultoria — registro manual")
    observed_at = models.DateTimeField("Data da verificação")
    published = models.BooleanField("Visível ao cliente", default=False)
    internal_notes = models.TextField("Observações internas", blank=True)

    def clean(self):
        super().clean()
        if self.capacity_gbps is not None and self.capacity_gbps < 0:
            raise ValidationError({"capacity_gbps": "Informe uma capacidade não negativa."})
        if not isinstance(self.attributes, dict):
            raise ValidationError({"attributes": "Informe um objeto JSON."})
        if self.type_id:
            unknown = set(self.attributes) - set(self.type.attribute_keys)
            if unknown:
                raise ValidationError(
                    {"attributes": "Atributos não permitidos: " + ", ".join(sorted(unknown))}
                )
        forbidden = ("password", "senha", "secret", "token", "credential")
        if any(word in key.lower() for key in self.attributes for word in forbidden):
            raise ValidationError({"attributes": "Não armazene credenciais de equipamentos."})

    def __str__(self):
        return self.name
