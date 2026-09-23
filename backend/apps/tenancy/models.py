import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from .context import current_tenant


class Tenant(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField("Nome", max_length=180)
    slug = models.SlugField(unique=True)
    active = models.BooleanField("Ativo", default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class TenantMembership(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant", "user"], name="unique_membership")]


class ScopedManager(models.Manager):
    def get_queryset(self):
        qs = super().get_queryset()
        tenant = current_tenant.get()
        return qs.filter(tenant_id=tenant) if tenant else qs.none()


class TenantModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    objects = ScopedManager()

    class Meta:
        abstract = True
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "id"], name="%(app_label)s_%(class)s_tenant_id"
            )
        ]

    def clean(self):
        super().clean()
        if str(self.tenant_id) != current_tenant.get():
            raise ValidationError("Operação fora do cliente selecionado.")
        for field in self._meta.fields:
            if isinstance(field, models.ForeignKey) and issubclass(
                field.related_model, TenantModel
            ):
                related_id = getattr(self, field.attname)
                if related_id and not field.related_model.objects.filter(pk=related_id).exists():
                    raise ValidationError(
                        {field.name: "Relacionamento inválido para este cliente."}
                    )

    def save(self, *args, **kwargs):
        if not self.tenant_id:
            self.tenant_id = current_tenant.get()
        self.full_clean()
        return super().save(*args, **kwargs)
