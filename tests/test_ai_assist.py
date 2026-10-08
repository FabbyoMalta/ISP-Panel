"""Tests for apps.ai_assist.services — the OpenRouter-backed assistant.
`call_openrouter` is mocked directly (no real network), same approach as
test_integrations_sync.py's `fetch_netbackup_summary` mocking.
"""

from decimal import Decimal

import pytest
from apps.ai_assist import services
from apps.ai_assist.models import AIConversation, AIMessage
from apps.assessments.models import AssessmentAnswer
from apps.inventory.models import Resource, ResourceType
from apps.metrics.models import MetricDefinition, MetricObservation
from apps.recommendations.models import Recommendation
from apps.tenancy.context import tenant_context
from django.utils import timezone


def _text_response(content):
    return {"choices": [{"message": {"content": content}}]}


def _tool_response(name, arguments):
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {"id": "call_1", "function": {"name": name, "arguments": arguments}}
                    ],
                }
            }
        ]
    }


@pytest.mark.django_db
def test_build_tenant_context_includes_known_data_and_hides_internal_notes(domain):
    with tenant_context(domain.a.pk):
        definition = MetricDefinition.objects.create(
            key="netbackup-active-devices", name="Equipamentos ativos", unit="unidades"
        )
        MetricObservation.objects.create(
            tenant=domain.a,
            definition=definition,
            value=12,
            observed_at=timezone.now(),
            author=domain.admin,
        )
        resource_type = ResourceType.objects.create(name="Backbone")
        Resource.objects.create(
            tenant=domain.a,
            type=resource_type,
            name="Anel óptico principal",
            observed_at=timezone.now(),
        )
        ResourceType.objects.create(name="ASN")
        assessment = services.ensure_open_assessment(domain.admin, domain.a)
        text = services.build_tenant_context(domain.a, assessment)

    assert "Equipamentos ativos: 12" in text
    assert "Anel óptico principal" in text
    assert domain.item1.title in text
    assert domain.rec_a.title in text
    assert "CONFIDENTIAL-INTERNAL" not in text
    # update_resource_status can create a resource of a known type even
    # when the tenant has none yet — the context must list the type
    # catalog, not just already-cataloged resource instances (regression:
    # the AI once refused to touch "ASN" because it only saw resources
    # that already existed).
    assert "ASN" in text
    assert "tipos de recurso disponíveis" in text.lower()


@pytest.mark.django_db
def test_execute_tool_call_set_assessment_answer_writes_answer(domain):
    with tenant_context(domain.a.pk):
        assessment = services.ensure_open_assessment(domain.admin, domain.a)
        summary = services.execute_tool_call(
            domain.admin,
            assessment,
            "set_assessment_answer",
            {"item_key": str(domain.item1.pk), "status": "met"},
        )
        answer = AssessmentAnswer.objects.get(assessment=assessment, item_key=str(domain.item1.pk))

    assert answer.status == "met"
    assert domain.item1.title in summary


@pytest.mark.django_db
def test_execute_tool_call_propose_recommendation_creates_draft(domain):
    with tenant_context(domain.a.pk):
        assessment = services.ensure_open_assessment(domain.admin, domain.a)
        services.execute_tool_call(
            domain.admin,
            assessment,
            "propose_recommendation",
            {
                "title": "Adotar redundância de link",
                "category": domain.category.name,
                "priority": "high",
                "justification": "Reduz risco de indisponibilidade",
            },
        )
        rec = Recommendation.objects.get(title="Adotar redundância de link")

    assert rec.source == "IA (sugestão)"
    assert rec.editorial_status == "draft"


@pytest.mark.django_db
def test_execute_tool_call_update_resource_status_creates_draft_when_missing(domain):
    resource_type = ResourceType.objects.create(name="ASN")
    with tenant_context(domain.a.pk):
        assessment = services.ensure_open_assessment(domain.admin, domain.a)
        services.execute_tool_call(
            domain.admin,
            assessment,
            "update_resource_status",
            {
                "resource_type": "ASN",
                "resource_name": "ASN próprio",
                "status": "partial",
                "description": "Em processo de retirada do ASN antigo",
            },
        )
        resource = Resource.objects.get(type=resource_type)

    assert resource.status == "partial"
    assert resource.published is False


@pytest.mark.django_db
def test_execute_tool_call_update_resource_status_keeps_same_type_resources_separate(domain):
    resource_type = ResourceType.objects.create(name="Upstream")
    with tenant_context(domain.a.pk):
        assessment = services.ensure_open_assessment(domain.admin, domain.a)
        services.execute_tool_call(
            domain.admin,
            assessment,
            "update_resource_status",
            {
                "resource_type": "Upstream",
                "resource_name": "Plena",
                "status": "active",
                "description": "Upstream principal, 3 Gbps",
                "capacity_gbps": 3,
            },
        )
        services.execute_tool_call(
            domain.admin,
            assessment,
            "update_resource_status",
            {
                "resource_type": "Upstream",
                "resource_name": "Dinâmica",
                "status": "partial",
                "description": "Upstream redundante, failover manual",
                "capacity_gbps": 2,
            },
        )
        resources = {r.name: r for r in Resource.objects.filter(type=resource_type)}

    assert set(resources) == {"Plena", "Dinâmica"}
    assert resources["Plena"].capacity_gbps == Decimal("3")
    assert resources["Dinâmica"].status == "partial"


@pytest.mark.django_db
def test_execute_tool_call_update_resource_status_sets_asn_only_when_allowed(domain):
    allowed_type = ResourceType.objects.create(name="Upstream", attribute_keys=["asn"])
    restricted_type = ResourceType.objects.create(name="Servidor", attribute_keys=["funcao"])
    with tenant_context(domain.a.pk):
        assessment = services.ensure_open_assessment(domain.admin, domain.a)
        services.execute_tool_call(
            domain.admin,
            assessment,
            "update_resource_status",
            {
                "resource_type": "Upstream",
                "resource_name": "Plena",
                "status": "active",
                "description": "Anuncia pelo AS12345",
                "asn": "12345",
            },
        )
        services.execute_tool_call(
            domain.admin,
            assessment,
            "update_resource_status",
            {
                "resource_type": "Servidor",
                "resource_name": "DNS-01",
                "status": "active",
                "description": "Servidor de DNS",
                "asn": "12345",
            },
        )
        allowed = Resource.objects.get(type=allowed_type)
        restricted = Resource.objects.get(type=restricted_type)

    assert allowed.attributes.get("asn") == "12345"
    assert "asn" not in restricted.attributes


@pytest.mark.django_db
def test_execute_tool_call_update_resource_status_forces_unpublished_on_existing(domain):
    resource_type = ResourceType.objects.create(name="ASN")
    with tenant_context(domain.a.pk):
        Resource.objects.create(
            tenant=domain.a,
            type=resource_type,
            name="ASN 12345",
            status="active",
            observed_at=timezone.now(),
            published=True,
        )
        assessment = services.ensure_open_assessment(domain.admin, domain.a)
        services.execute_tool_call(
            domain.admin,
            assessment,
            "update_resource_status",
            {
                "resource_type": "ASN",
                "resource_name": "ASN 12345",
                "status": "partial",
                "description": "Em processo de retirada",
            },
        )
        resource = Resource.objects.get(type=resource_type)

    assert resource.status == "partial"
    assert resource.published is False


@pytest.mark.django_db
def test_execute_tool_call_log_metric_observation_creates_draft(domain):
    definition = MetricDefinition.objects.create(
        key="capacity-gbps", name="Capacidade", unit="Gbps"
    )
    with tenant_context(domain.a.pk):
        assessment = services.ensure_open_assessment(domain.admin, domain.a)
        services.execute_tool_call(
            domain.admin,
            assessment,
            "log_metric_observation",
            {"metric_key": "capacity-gbps", "value": 6.5},
        )
        observation = MetricObservation.objects.get(definition=definition)

    assert observation.value == Decimal("6.5")
    assert observation.published is False
    assert observation.source == "IA (sugestão, a partir da conversa)"


@pytest.mark.django_db
def test_execute_tool_call_log_metric_observation_requires_assumptions_when_estimated(domain):
    MetricDefinition.objects.create(key="capacity-gbps", name="Capacidade", unit="Gbps")
    with tenant_context(domain.a.pk):
        assessment = services.ensure_open_assessment(domain.admin, domain.a)
        summary = services.execute_tool_call(
            domain.admin,
            assessment,
            "log_metric_observation",
            {"metric_key": "capacity-gbps", "value": 6.5, "estimated": True},
        )

    assert "premissa" in summary.lower()
    assert not MetricObservation.objects.filter(definition__key="capacity-gbps").exists()


@pytest.mark.django_db
def test_execute_tool_call_log_metric_observation_rejects_peak_gbps(domain):
    # peak-gbps is continuous telemetry — it must come from a real
    # monitoring source, never from a chat-reported value (regression:
    # the AI once logged a stale "7.2 Gbps" that the user never actually
    # stated as current, and metrics are permanently immutable once
    # written — a database trigger blocks even deleting a draft row —
    # so a wrong value here can never be cleaned up, only superseded).
    # The allow-list must be enforced server-side, not just hinted to
    # the model via the tool schema's enum.
    MetricDefinition.objects.create(key="peak-gbps", name="Pico", unit="Gbps")
    with tenant_context(domain.a.pk):
        assessment = services.ensure_open_assessment(domain.admin, domain.a)
        summary = services.execute_tool_call(
            domain.admin,
            assessment,
            "log_metric_observation",
            {"metric_key": "peak-gbps", "value": 7.2},
        )

    assert "não pode ser registrada" in summary
    assert not MetricObservation.objects.filter(definition__key="peak-gbps").exists()


@pytest.mark.django_db
def test_send_message_records_user_and_assistant_text(domain, monkeypatch):
    monkeypatch.setattr(
        services, "call_openrouter", lambda messages, tools: _text_response("Olá, consultor.")
    )
    with tenant_context(domain.a.pk):
        conversation = AIConversation.objects.create(tenant=domain.a)
        created = services.send_message(domain.admin, conversation, "Bom dia")

    assert [m.role for m in created] == [AIMessage.Role.USER, AIMessage.Role.ASSISTANT]
    assert created[-1].content == "Olá, consultor."


@pytest.mark.django_db
def test_send_message_executes_tool_then_final_reply(domain, monkeypatch):
    calls = []

    seen_messages = []

    def fake_call(messages, tools):
        calls.append(1)
        seen_messages.append(messages)
        if len(calls) == 1:
            return _tool_response(
                "set_assessment_answer", '{"item_key": "%s", "status": "met"}' % domain.item1.pk
            )
        return _text_response("Pronto, já registrei.")

    monkeypatch.setattr(services, "call_openrouter", fake_call)
    with tenant_context(domain.a.pk):
        conversation = AIConversation.objects.create(tenant=domain.a)
        created = services.send_message(domain.admin, conversation, "")
        answer = AssessmentAnswer.objects.get(item_key=str(domain.item1.pk))

    assert answer.status == "met"
    assert [m.role for m in created] == [AIMessage.Role.TOOL, AIMessage.Role.ASSISTANT]
    # Regression: Claude (via OpenRouter) refuses a conversation whose
    # last message is assistant-authored ("assistant message prefill").
    # The second call must be handed a message list ending in role=tool.
    assert seen_messages[1][-1]["role"] == "tool"


@pytest.mark.django_db
def test_send_message_stops_at_iteration_cap(domain, monkeypatch):
    monkeypatch.setattr(
        services,
        "call_openrouter",
        lambda messages, tools: _tool_response(
            "set_assessment_answer", '{"item_key": "%s", "status": "met"}' % domain.item1.pk
        ),
    )
    with tenant_context(domain.a.pk):
        conversation = AIConversation.objects.create(tenant=domain.a)
        created = services.send_message(domain.admin, conversation, "")

    assert len(created) == services.MAX_TOOL_ITERATIONS
    assert all(m.role == AIMessage.Role.TOOL for m in created)
