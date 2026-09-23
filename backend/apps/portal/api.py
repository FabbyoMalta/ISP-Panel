from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from rest_framework import mixins, permissions, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from apps.assessments.models import Assessment, AssessmentAnswer, AssessmentCategory
from apps.assessments.services import answer_assessment, publish_assessment, start_assessment
from apps.audit.models import AuditEntry
from apps.clients.models import Client, ClientContact
from apps.external_links.models import ExternalLink
from apps.inventory.models import Resource
from apps.metrics.models import MetricObservation
from apps.recommendations.models import (
    Recommendation,
    RecommendationDependency,
    RecommendationRisk,
    RoadmapPlacement,
)
from apps.recommendations.services import add_dependency, remove_dependency, transition
from apps.risks.models import Risk
from apps.tenancy.models import Tenant
from apps.timeline.models import Event

from .services import check_metric, save_record, visible


def exception_handler(exc, context):
    if isinstance(exc, DjangoValidationError):
        exc = ValidationError(exc.message_dict if hasattr(exc, "message_dict") else exc.messages)
    if isinstance(exc, IntegrityError):
        exc = ValidationError("Registro duplicado ou relacionamento inválido.")
    return drf_exception_handler(exc, context)


class ConsultantWrite(permissions.BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and (
            request.method in permissions.SAFE_METHODS or request.user.is_consultant
        )


class ScopedSerializer(serializers.ModelSerializer):
    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get("request")
        if not request or not request.user.is_authenticated or not request.user.is_consultant:
            fields.pop("internal_notes", None)
        # Manager.none() outside tenant context must not be frozen at import time.
        for field in fields.values():
            if isinstance(field, serializers.PrimaryKeyRelatedField) and field.queryset is not None:
                field.queryset = field.queryset.model.objects.all()
        return fields

    def to_internal_value(self, data):
        unknown = set(data) - set(self.fields)
        readonly = {key for key in data if key in self.fields and self.fields[key].read_only}
        if unknown or readonly:
            raise ValidationError(
                {key: "Campo não permitido para escrita." for key in unknown | readonly}
            )
        return super().to_internal_value(data)

    def create(self, validated_data):
        request = self.context["request"]
        obj = self.Meta.model(tenant=request.tenant, **validated_data)
        if isinstance(obj, MetricObservation):
            obj.author = request.user
            check_metric(obj)
        return save_record(request.user, obj)

    def update(self, instance, validated_data):
        if isinstance(instance, MetricObservation):
            raise ValidationError("Registre uma nova observação para preservar o histórico.")
        for key, value in validated_data.items():
            setattr(instance, key, value)
        return save_record(self.context["request"].user, instance)


def serializer_for(model, fields, readonly=()):
    meta = type(
        "Meta",
        (),
        {
            "model": model,
            "fields": ["id", "created_at", *fields],
            "read_only_fields": ["id", "created_at", *readonly],
        },
    )
    return type(f"{model.__name__}Serializer", (ScopedSerializer,), {"Meta": meta})


class ScopedViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [ConsultantWrite]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return self.serializer_class.Meta.model.objects.none()
        return visible(self.serializer_class.Meta.model.objects.all(), self.request.user).order_by(
            "-created_at"
        )


RESOURCE_SERIALIZERS = {
    "clients": serializer_for(
        Client, ["legal_name", "trade_name", "region", "joined_on", "internal_notes"]
    ),
    "contacts": serializer_for(ClientContact, ["name", "position", "email", "phone"]),
    "resources": serializer_for(
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
    "risks": serializer_for(
        Risk, ["title", "severity", "description", "status", "owner", "published", "internal_notes"]
    ),
    "metrics": serializer_for(
        MetricObservation,
        ["definition", "value", "observed_at", "source", "assumptions", "estimated", "published"],
    ),
    "events": serializer_for(Event, ["title", "description", "occurred_on", "published"]),
    "external-links": serializer_for(ExternalLink, ["title", "url", "description", "published"]),
    "roadmap": serializer_for(
        RoadmapPlacement, ["recommendation", "horizon", "order", "target_date"]
    ),
    "risk-links": serializer_for(RecommendationRisk, ["recommendation", "risk"]),
}


class RecommendationSerializer(ScopedSerializer):
    blocked = serializers.SerializerMethodField()

    class Meta:
        model = Recommendation
        fields = [
            "id",
            "created_at",
            "title",
            "description",
            "category",
            "priority",
            "status",
            "justification",
            "impact",
            "effort",
            "owner",
            "recommended_on",
            "completed_on",
            "block_reason",
            "client_notes",
            "internal_notes",
            "editorial_status",
            "source",
            "blocked",
        ]
        read_only_fields = ["id", "created_at", "status", "completed_on", "block_reason", "source"]

    def get_blocked(self, obj) -> bool:
        return (
            obj.status == "blocked"
            or obj.dependencies.exclude(prerequisite__status="done").exists()
        )


class TransitionSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=Recommendation.Status.choices)
    reason = serializers.CharField(required=False, allow_blank=True)


class RecommendationViewSet(ScopedViewSet):
    serializer_class = RecommendationSerializer

    @action(detail=True, methods=["post"], serializer_class=TransitionSerializer)
    def transition(self, request, **kwargs):
        serializer = TransitionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        # The action serializer differs; use the explicitly scoped domain queryset.
        obj = self.get_object()
        obj = transition(request.user, obj, **serializer.validated_data)
        return Response(RecommendationSerializer(obj, context={"request": request}).data)

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Recommendation.objects.none()
        return visible(Recommendation.objects.all(), self.request.user).order_by("-created_at")


class AssessmentSerializer(ScopedSerializer):
    class Meta:
        model = Assessment
        fields = [
            "id",
            "created_at",
            "title",
            "template",
            "assessed_on",
            "summary",
            "internal_notes",
            "published_at",
            "result",
        ]
        read_only_fields = ["id", "created_at", "published_at", "result"]

    def create(self, validated_data):
        return start_assessment(self.context["request"].user, **validated_data)

    def update(self, instance, validated_data):
        if "template" in validated_data:
            raise ValidationError("A metodologia não pode mudar após a criação.")
        return super().update(instance, validated_data)


class AnswerInputSerializer(serializers.Serializer):
    item_key = serializers.CharField()
    status = serializers.ChoiceField(choices=AssessmentAnswer.Status.choices)
    comment = serializers.CharField(required=False, allow_blank=True)
    internal_notes = serializers.CharField(required=False, allow_blank=True)


class AssessmentViewSet(ScopedViewSet):
    serializer_class = AssessmentSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Assessment.objects.none()
        return visible(Assessment.objects.all(), self.request.user).order_by("-created_at")

    @action(detail=True, methods=["post"])
    def publish(self, request, **kwargs):
        obj = publish_assessment(request.user, self.get_object())
        return Response(AssessmentSerializer(obj, context={"request": request}).data)

    @action(detail=True, methods=["post"], serializer_class=AnswerInputSerializer)
    def answer(self, request, **kwargs):
        serializer = AnswerInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        obj = answer_assessment(request.user, self.get_object(), **serializer.validated_data)
        return Response({"id": str(obj.pk), "status": obj.status})

    @action(detail=True, methods=["get"])
    def answers(self, request, **kwargs):
        obj = self.get_object()
        fields = ["item_key", "status", "comment"]
        if request.user.is_consultant:
            fields.append("internal_notes")
        return Response(
            {"methodology": obj.template.snapshot, "answers": list(obj.answers.values(*fields))}
        )


class DependencySerializer(ScopedSerializer):
    class Meta:
        model = RecommendationDependency
        fields = ["id", "recommendation", "prerequisite"]
        read_only_fields = ["id"]
        validators = []

    def create(self, validated_data):
        return add_dependency(self.context["request"].user, **validated_data)


class DependencyViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = DependencySerializer
    permission_classes = [ConsultantWrite]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return RecommendationDependency.objects.none()
        return visible(RecommendationDependency.objects.all(), self.request.user).order_by("id")

    def perform_destroy(self, instance):
        remove_dependency(self.request.user, instance)


class AuditSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditEntry
        fields = ["id", "actor", "action", "object_type", "object_id", "changes", "created_at"]


class AuditViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AuditSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return AuditEntry.objects.none()
        return visible(AuditEntry.objects.all(), self.request.user)


class TenantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tenant
        fields = ["id", "name", "slug"]


class TenantViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = TenantSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Tenant.objects.none()
        qs = Tenant.objects.filter(active=True).order_by("name")
        if not self.request.user.is_consultant:
            qs = qs.filter(tenantmembership__user=self.request.user)
        return qs


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = AssessmentCategory
        fields = ["id", "name", "order"]


class CategoryViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = CategorySerializer
    queryset = AssessmentCategory.objects.all()
