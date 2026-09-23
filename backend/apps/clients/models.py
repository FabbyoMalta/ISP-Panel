from django.db import models

from apps.tenancy.models import TenantModel


class Client(TenantModel):
    legal_name = models.CharField("Razão social", max_length=200)
    trade_name = models.CharField("Nome fantasia", max_length=160)
    region = models.CharField("Região de operação", max_length=200, blank=True)
    joined_on = models.DateField("Início da assessoria")
    internal_notes = models.TextField("Observações internas", blank=True)

    class Meta(TenantModel.Meta):
        constraints = TenantModel.Meta.constraints + [
            models.UniqueConstraint(fields=["tenant"], name="one_client_per_tenant")
        ]

    def __str__(self):
        return self.trade_name


class ClientContact(TenantModel):
    name = models.CharField("Nome", max_length=160)
    position = models.CharField("Função", max_length=120, blank=True)
    email = models.EmailField("E-mail", blank=True)
    phone = models.CharField("Telefone", max_length=40, blank=True)

    def __str__(self):
        return self.name
