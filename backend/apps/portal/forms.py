from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.db import models
from django.utils import timezone

from apps.assessments.models import Assessment, AssessmentAnswer, AssessmentTemplateVersion
from apps.clients.models import Client, ClientContact
from apps.external_links.models import ExternalLink
from apps.inventory.models import Resource
from apps.metrics.models import MetricObservation
from apps.recommendations.models import Recommendation, RecommendationRisk, RoadmapPlacement
from apps.risks.models import Risk
from apps.tenancy.models import Tenant
from apps.timeline.models import Event


class StyledFormMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field, forms.URLField):
                field.assume_scheme = "https"
            if isinstance(field, forms.ModelChoiceField):
                field.queryset = field.queryset.model.objects.all()
            if isinstance(field, forms.DateTimeField):
                field.widget = forms.DateTimeInput(
                    attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
                )
                field.initial = field.initial or timezone.now
            elif isinstance(field, forms.DateField):
                field.widget = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
            elif isinstance(field.widget, forms.Textarea):
                field.widget.attrs["rows"] = 3


def model_form(model, fields):
    def formfield(field, **kwargs):
        if isinstance(field, models.URLField):
            kwargs["assume_scheme"] = "https"
        return field.formfield(**kwargs)

    meta = type(
        "Meta",
        (),
        {"model": model, "fields": fields, "formfield_callback": staticmethod(formfield)},
    )
    return type(f"{model.__name__}Form", (StyledFormMixin, forms.ModelForm), {"Meta": meta})


FORMS = {
    "client": model_form(
        Client, ["legal_name", "trade_name", "region", "joined_on", "internal_notes"]
    ),
    "contacts": model_form(ClientContact, ["name", "position", "email", "phone"]),
    "resources": model_form(
        Resource,
        [
            "type",
            "name",
            "status",
            "description",
            "capacity_gbps",
            "attributes",
            "source",
            "observed_at",
            "published",
            "internal_notes",
        ],
    ),
    "risks": model_form(
        Risk, ["title", "severity", "description", "status", "owner", "published", "internal_notes"]
    ),
    "recommendations": model_form(
        Recommendation,
        [
            "title",
            "category",
            "priority",
            "description",
            "justification",
            "impact",
            "effort",
            "owner",
            "recommended_on",
            "client_notes",
            "internal_notes",
            "editorial_status",
        ],
    ),
    "metrics": model_form(
        MetricObservation,
        ["definition", "value", "observed_at", "source", "assumptions", "estimated", "published"],
    ),
    "events": model_form(Event, ["title", "description", "occurred_on", "published"]),
    "links": model_form(ExternalLink, ["title", "url", "description", "published"]),
    "roadmap": model_form(RoadmapPlacement, ["recommendation", "horizon", "order", "target_date"]),
    "risk-links": model_form(RecommendationRisk, ["recommendation", "risk"]),
}


class TenantForm(StyledFormMixin, forms.Form):
    name = forms.CharField(label="Nome fantasia", max_length=160)
    slug = forms.SlugField(label="Identificador", max_length=50)
    legal_name = forms.CharField(label="Razão social", max_length=200)
    region = forms.CharField(label="Região de operação", required=False)
    joined_on = forms.DateField(label="Início da assessoria", initial=timezone.localdate)

    def clean_slug(self):
        slug = self.cleaned_data["slug"]
        if Tenant.objects.filter(slug=slug).exists():
            raise forms.ValidationError("Este identificador já está em uso.")
        return slug


class UserForm(StyledFormMixin, forms.ModelForm):
    password = forms.CharField(
        label="Senha inicial",
        widget=forms.PasswordInput,
        required=False,
        help_text="Na criação, informe uma senha forte ou deixe em branco para enviar um link de definição por e-mail.",
    )
    tenants = forms.ModelMultipleChoiceField(
        label="Empresas autorizadas (perfil cliente)",
        queryset=Tenant.objects.filter(active=True),
        required=False,
    )

    class Meta:
        model = get_user_model()
        fields = ["username", "email", "first_name", "last_name", "role", "is_active"]

    def clean(self):
        data = super().clean()
        if data.get("password"):
            validate_password(data["password"], self.instance)
        if data.get("role") == "client" and not data.get("tenants"):
            raise forms.ValidationError("Vincule o usuário cliente a pelo menos uma empresa.")
        return data


class AssessmentForm(StyledFormMixin, forms.Form):
    title = forms.CharField(label="Título", max_length=180)
    template = forms.ModelChoiceField(
        label="Metodologia", queryset=AssessmentTemplateVersion.objects.order_by("-id")
    )
    assessed_on = forms.DateField(label="Data da avaliação", initial=timezone.localdate)
    summary = forms.CharField(label="Resumo para o cliente", widget=forms.Textarea, required=False)
    internal_notes = forms.CharField(
        label="Observações internas", widget=forms.Textarea, required=False
    )


class AnswerForm(StyledFormMixin, forms.Form):
    status = forms.ChoiceField(label="Situação", choices=AssessmentAnswer.Status.choices)
    comment = forms.CharField(label="Comentário técnico", widget=forms.Textarea, required=False)
    internal_notes = forms.CharField(
        label="Observação interna", widget=forms.Textarea, required=False
    )


class TransitionForm(forms.Form):
    status = forms.ChoiceField(label="Novo estado", choices=Recommendation.Status.choices)
    reason = forms.CharField(
        label="Motivo (obrigatório para bloqueio ou não aplicável)", required=False
    )


class DependencyForm(forms.Form):
    prerequisite = forms.ModelChoiceField(
        label="Depende de", queryset=Recommendation.objects.none()
    )

    def __init__(self, *args, recommendation, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["prerequisite"].queryset = Recommendation.objects.exclude(pk=recommendation.pk)


AssessmentEditForm = model_form(Assessment, ["title", "assessed_on", "summary", "internal_notes"])
