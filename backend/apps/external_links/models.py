from django.core.validators import URLValidator
from django.db import models

from apps.tenancy.models import TenantModel


class ExternalLink(TenantModel):
    title = models.CharField("Ferramenta", max_length=120)
    url = models.URLField("URL", validators=[URLValidator(schemes=["https", "http"])])
    description = models.CharField("Descrição", max_length=240, blank=True)
    published = models.BooleanField("Visível ao cliente", default=False)

    def __str__(self):
        return self.title
