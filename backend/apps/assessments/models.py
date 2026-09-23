from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models

from apps.tenancy.models import TenantModel


class AssessmentCategory(models.Model):
    name = models.CharField("Área", max_length=120, unique=True)
    order = models.PositiveIntegerField("Ordem", default=0)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return self.name


class AssessmentItemDefinition(models.Model):
    category = models.ForeignKey(AssessmentCategory, on_delete=models.PROTECT, verbose_name="Área")
    title = models.CharField("Critério", max_length=180)
    guidance = models.TextField("Orientação", blank=True)
    weight = models.PositiveIntegerField("Peso", default=1, validators=[MinValueValidator(1)])
    active = models.BooleanField("Ativo", default=True)

    def __str__(self):
        return self.title


class MaturityLevel(models.Model):
    name = models.CharField("Nível", max_length=100)
    order = models.PositiveIntegerField("Ordem", unique=True)
    description = models.TextField("Descrição", blank=True)

    class Meta:
        ordering = ["order"]

    def __str__(self):
        return self.name


class MaturityRule(models.Model):
    level = models.ForeignKey(MaturityLevel, on_delete=models.CASCADE, verbose_name="Nível")
    item = models.ForeignKey(
        AssessmentItemDefinition, on_delete=models.PROTECT, verbose_name="Critério obrigatório"
    )

    class Meta:
        constraints = [models.UniqueConstraint(fields=["level", "item"], name="unique_level_rule")]

    def __str__(self):
        return f"{self.level}: {self.item}"


class AssessmentTemplateVersion(models.Model):
    name = models.CharField(max_length=160)
    created_at = models.DateTimeField(auto_now_add=True)
    snapshot = models.JSONField()

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Versões são imutáveis. Publique uma nova versão do catálogo.")
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} · v{self.pk}"


class Assessment(TenantModel):
    title = models.CharField("Título", max_length=180)
    template = models.ForeignKey(
        AssessmentTemplateVersion, on_delete=models.PROTECT, verbose_name="Metodologia"
    )
    assessed_on = models.DateField("Data da avaliação")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    summary = models.TextField("Resumo para o cliente", blank=True)
    internal_notes = models.TextField("Observações internas", blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    result = models.JSONField(default=dict, blank=True)

    def clean(self):
        super().clean()
        if self.pk and Assessment.objects.filter(pk=self.pk, published_at__isnull=False).exists():
            raise ValidationError("Avaliações publicadas são imutáveis. Crie uma nova avaliação.")

    def __str__(self):
        return self.title


class AssessmentAnswer(TenantModel):
    class Status(models.TextChoices):
        MET = "met", "Atendido"
        PARTIAL = "partial", "Parcialmente atendido"
        UNMET = "unmet", "Não atendido"
        NA = "na", "Não aplicável"

    assessment = models.ForeignKey(Assessment, on_delete=models.PROTECT, related_name="answers")
    item_key = models.CharField(max_length=40)
    status = models.CharField("Situação", max_length=10, choices=Status.choices)
    comment = models.TextField("Comentário técnico / justificativa", blank=True)
    internal_notes = models.TextField("Observação interna", blank=True)

    class Meta(TenantModel.Meta):
        constraints = TenantModel.Meta.constraints + [
            models.UniqueConstraint(
                fields=["assessment", "item_key"], name="unique_assessment_answer"
            )
        ]

    def clean(self):
        super().clean()
        if self.assessment_id:
            if self.assessment.published_at:
                raise ValidationError("Respostas publicadas não podem ser alteradas.")
            if self.item_key not in {i["key"] for i in self.assessment.template.snapshot["items"]}:
                raise ValidationError("Critério não pertence à metodologia desta avaliação.")
        if self.status == self.Status.NA and not self.comment.strip():
            raise ValidationError({"comment": "Justifique o item não aplicável."})
