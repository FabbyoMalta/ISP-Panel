"""OpenRouter-backed assistant for the initial client survey — see
docs in the approved plan (ai_assist). Four tools
(set_assessment_answer, propose_recommendation, update_resource_status,
log_metric_observation), all writing through the exact same service
functions a human consultant's own UI actions already use
(apps.assessments.services.answer_assessment,
apps.portal.services.save_record) — every write is draft-by-default and
audited under the real logged-in consultant, never a bot actor, never
auto-published. update_resource_status/log_metric_observation were
added after v1 shipped (explicit, user-requested scope extension — see
commit history) once it became clear the dashboard's capacity/ASN cards
(apps.portal.selectors.dashboard) read Resource/MetricObservation, which
the original two tools never touched.
"""

import json
from decimal import Decimal

import httpx
from django.conf import settings
from django.utils import timezone

from apps.assessments.models import Assessment, AssessmentCategory, AssessmentTemplateVersion
from apps.assessments.services import answer_assessment, start_assessment
from apps.clients.models import Client
from apps.inventory.models import Resource, ResourceType
from apps.metrics.models import MetricDefinition, MetricObservation
from apps.portal.services import save_record
from apps.recommendations.models import Recommendation

from .models import AIConversation, AIMessage

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

SYSTEM_PROMPT = (
    "Você é um assistente que ajuda um consultor técnico de provedores de "
    "Internet (ISPs) a montar o levantamento estratégico inicial de um "
    "cliente. Você vê um resumo dos dados já conhecidos sobre o cliente "
    "(alguns sincronizados automaticamente de um sistema de backup de "
    "rede, outros cadastrados manualmente). Sua tarefa: (1) para cada "
    "critério do checklist ainda sem resposta, proponha uma resposta "
    "usando `set_assessment_answer` SE E SOMENTE SE os dados already "
    "souberem disso com confiança razoável — nunca invente; (2) para o "
    "que não dá pra inferir, pergunte ao consultor, um ou poucos itens "
    "por vez, em português; (3) quando fizer sentido, proponha melhorias "
    "futuras com `propose_recommendation`; (4) quando o consultor relatar "
    "um fato operacional concreto sobre capacidade/tráfego ou sobre a "
    "situação de um recurso de infraestrutura (ASN, upstream, IPv6 "
    "etc.), registre com `log_metric_observation` ou "
    "`update_resource_status` — use qualquer tipo listado no contexto "
    'como "tipos de recurso disponíveis", mesmo que o tenant ainda não '
    "tenha esse recurso cadastrado (a ferramenta cria o registro na "
    "primeira vez); um mesmo tipo pode ter vários recursos (ex.: dois "
    "upstreams de operadoras diferentes) — use resource_name pra "
    "diferenciar cada um, nunca misture dois recursos distintos numa só "
    "descrição; sempre com o valor/situação exata que foi relatada, "
    "nunca estimando por conta própria. Todas as suas "
    "ações (respostas, recomendações, métricas, recursos) são sempre "
    "rascunho — o consultor revisa e publica depois, então pode agir "
    'livremente, mas nunca diga que algo já foi "aplicado" ou '
    '"publicado" para o cliente. Seja direto e objetivo. Nunca registre '
    "`peak-gbps` (tráfego de pico) nem nenhuma outra métrica de "
    "telemetria contínua — esse tipo de dado varia o tempo todo e só "
    "tem valor vindo de uma fonte de monitoramento real (Zabbix, "
    "NetBackup etc.), nunca de uma estimativa relatada em conversa; se "
    "o consultor perguntar sobre isso, explique essa diferença."
)

# Chaves que a IA pode gravar via log_metric_observation — única fonte
# de verdade (usada no schema do tool E na validação em
# execute_tool_call, pra isso nunca depender só do que o modelo decide
# respeitar). Deliberadamente SEM peak-gbps: é telemetria contínua, só
# tem sentido vindo de uma fonte de monitoramento real — nunca de um
# relato em conversa. MetricObservation é histórico e imutável (trigger
# de banco — nem rascunho pode ser apagado), então um valor errado
# aqui fica pra sempre; mais um motivo pra manter essa lista apertada.
ALLOWED_METRIC_KEYS = ("active-subscribers", "estimated-subscribers", "capacity-gbps")

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "set_assessment_answer",
            "description": (
                "Responde (ou corrige) um critério do checklist de avaliação em andamento."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "item_key": {"type": "string", "description": "Chave do critério"},
                    "status": {
                        "type": "string",
                        "enum": ["met", "partial", "unmet", "na"],
                        "description": "met=atendido, partial=parcial, unmet=não atendido, na=não aplicável",
                    },
                    "comment": {
                        "type": "string",
                        "description": "Justificativa curta (obrigatória se status=na)",
                    },
                },
                "required": ["item_key", "status"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_recommendation",
            "description": "Cria uma recomendação (melhoria futura) como rascunho.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "category": {
                        "type": "string",
                        "description": "Nome exato de uma das áreas já listadas no contexto",
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["critical", "high", "medium", "low"],
                    },
                    "justification": {"type": "string"},
                    "impact": {"type": "string"},
                },
                "required": ["title", "category", "priority", "justification"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_resource_status",
            "description": (
                "Cria ou atualiza UM recurso de infraestrutura (ex.: um upstream "
                "específico, o ASN, um IPv6) com base no que o consultor relatou. "
                "Um tipo pode ter vários recursos (ex.: dois upstreams diferentes) — "
                "use resource_name pra identificar qual. Sempre fica como "
                "rascunho, mesmo que o recurso já estivesse publicado para o "
                "cliente — a publicação da mudança é manual."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "resource_type": {
                        "type": "string",
                        "description": "Nome exato de um tipo já listado no contexto (ex.: ASN, Upstream, IPv6)",
                    },
                    "resource_name": {
                        "type": "string",
                        "description": (
                            "Nome que identifica esse recurso específico entre outros do "
                            'mesmo tipo (ex.: nome do operador do upstream — "Plena", '
                            '"Dinâmica"; para um recurso único do tenant, como o ASN '
                            "próprio, repita o nome do tipo ou use o identificador real, "
                            'ex.: "ASN 12345")'
                        ),
                    },
                    "status": {
                        "type": "string",
                        "enum": ["active", "partial", "inactive"],
                        "description": "active=ativo, partial=parcial/em transição, inactive=inativo",
                    },
                    "description": {
                        "type": "string",
                        "description": "Situação atual em texto, com o contexto relatado (ex.: em processo de retirada do ASN antigo)",
                    },
                    "capacity_gbps": {
                        "type": "number",
                        "description": "Capacidade em Gbps, se fizer sentido para esse recurso (ex.: um link de upstream)",
                    },
                    "asn": {
                        "type": "string",
                        "description": (
                            "Número do ASN desse recurso, se for relevante e tiver sido "
                            "relatado (ex.: um upstream que anuncia pelo AS12345 — "
                            "habilita a consulta RDAP manual na tela de Infraestrutura)"
                        ),
                    },
                },
                "required": ["resource_type", "resource_name", "status", "description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "log_metric_observation",
            "description": (
                "Registra uma nova observação de capacidade/base de clientes relatada "
                "na conversa. Sempre fica como rascunho. NÃO serve para métricas que "
                "variam continuamente (ex.: tráfego de pico) — essas só devem vir de "
                "uma fonte de monitoramento real, nunca de um relato em conversa."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "metric_key": {
                        "type": "string",
                        "enum": list(ALLOWED_METRIC_KEYS),
                        "description": (
                            "active-subscribers=clientes ativos, "
                            "estimated-subscribers=capacidade estimada de clientes, "
                            "capacity-gbps=capacidade de trânsito IP contratada"
                        ),
                    },
                    "value": {"type": "number"},
                    "estimated": {
                        "type": "boolean",
                        "description": "true se o próprio cliente deu um valor aproximado, não uma medição exata",
                    },
                    "assumptions": {
                        "type": "string",
                        "description": "Premissas da estimativa (obrigatório se estimated=true)",
                    },
                },
                "required": ["metric_key", "value"],
            },
        },
    },
]

MAX_TOOL_ITERATIONS = 5


def call_openrouter(messages: list[dict], tools: list[dict]) -> dict:
    response = httpx.post(
        OPENROUTER_URL,
        headers={"Authorization": f"Bearer {settings.OPENROUTER_API_KEY}"},
        json={"model": settings.OPENROUTER_MODEL, "messages": messages, "tools": tools},
        timeout=60,
    )
    response.raise_for_status()
    return response.json()


def ensure_open_assessment(actor, tenant) -> Assessment:
    """Finds the tenant's most recent draft (unpublished) Assessment, or
    starts a new one against the latest published catalog — same inputs
    `apps.portal.views.assessment_create` already requires.
    """
    draft = Assessment.objects.filter(published_at__isnull=True).order_by("-assessed_on").first()
    if draft is not None:
        return draft
    template = AssessmentTemplateVersion.objects.order_by("-pk").first()
    if template is None:
        raise ValueError("Nenhuma metodologia publicada ainda — publique um catálogo primeiro.")
    return start_assessment(
        actor,
        title=f"Levantamento inicial — {tenant.name}",
        assessed_on=timezone.localdate(),
        template=template,
    )


def build_tenant_context(tenant, assessment: Assessment) -> str:
    """Pure-ish (one tenant's already-scoped querysets, no network) —
    text the model reads as part of the system context each turn. Never
    includes internal_notes (Client/Assessment/Recommendation) — see the
    plan's decision 7.
    """
    lines = [f"Cliente: {tenant.name}"]
    client = Client.objects.filter(tenant=tenant).first()
    if client is not None:
        lines.append(f"Razão social: {client.legal_name}")
        lines.append(f"Região de atuação: {client.region or 'não informado'}")

    lines.append("\nMétricas e indicadores conhecidos (valor mais recente de cada):")
    latest_by_key: dict[str, MetricObservation] = {}
    for obs in MetricObservation.objects.select_related("definition").order_by("-observed_at"):
        latest_by_key.setdefault(obs.definition.key, obs)
    if latest_by_key:
        for obs in latest_by_key.values():
            tag = " (estimativa)" if obs.estimated else ""
            lines.append(f"- {obs.definition.name}: {obs.value} {obs.definition.unit}{tag}")
    else:
        lines.append("- (nenhuma métrica registrada ainda)")

    lines.append("\nRecursos de infraestrutura cadastrados:")
    resources = list(Resource.objects.select_related("type"))
    if resources:
        for resource in resources:
            lines.append(
                f"- {resource.type.name}: {resource.name} ({resource.get_status_display()})"
            )
    else:
        lines.append("- (nenhum recurso cadastrado ainda)")
    # Tipos válidos para update_resource_status mesmo quando o tenant
    # ainda não tem nenhum recurso desse tipo cadastrado — a ferramenta
    # cria o recurso (como rascunho) na primeira vez.
    type_names = sorted(ResourceType.objects.values_list("name", flat=True))
    if type_names:
        lines.append(
            "\nTipos de recurso disponíveis para update_resource_status "
            "(cria o recurso se ainda não existir): " + ", ".join(type_names)
        )

    items = assessment.template.snapshot["items"]
    answered = {a.item_key: a for a in assessment.answers.all()}
    lines.append(
        f"\nChecklist da avaliação em andamento ({len(answered)}/{len(items)} respondidos):"
    )
    for item in items:
        answer = answered.get(item["key"])
        if answer is not None:
            lines.append(f"- [{item['key']}] {item['title']} — já respondido: {answer.status}")
        else:
            guidance = f" — {item['guidance']}" if item.get("guidance") else ""
            lines.append(f"- [{item['key']}] {item['title']} (área: {item['category']}){guidance}")

    published_recs = list(
        Recommendation.objects.filter(editorial_status="published").values_list("title", flat=True)
    )
    if published_recs:
        lines.append("\nRecomendações já publicadas (não sugerir de novo):")
        for title in published_recs:
            lines.append(f"- {title}")

    return "\n".join(lines)


def execute_tool_call(actor, assessment: Assessment, tool_name: str, args: dict) -> str:
    """Dispatches one tool call to the real domain service, returns a
    short human-readable summary used both for the `tool` message sent
    back to the model and for the action card rendered in the chat UI.
    """
    if tool_name == "set_assessment_answer":
        answer_assessment(
            actor,
            assessment,
            item_key=args["item_key"],
            status=args["status"],
            comment=args.get("comment", ""),
        )
        items_by_key = {i["key"]: i["title"] for i in assessment.template.snapshot["items"]}
        title = items_by_key.get(args["item_key"], args["item_key"])
        return f"Respondido: {title} → {args['status']}"

    if tool_name == "propose_recommendation":
        category = AssessmentCategory.objects.filter(name=args["category"]).first()
        if category is None:
            return f'Categoria "{args["category"]}" não encontrada — recomendação não criada.'
        save_record(
            actor,
            Recommendation(
                tenant=assessment.tenant,
                title=args["title"],
                description=args.get("description", ""),
                category=category,
                priority=args["priority"],
                justification=args["justification"],
                impact=args.get("impact", ""),
                source="IA (sugestão)",
            ),
        )
        return f"Recomendação criada (rascunho): {args['title']}"

    if tool_name == "update_resource_status":
        resource_type = ResourceType.objects.filter(name=args["resource_type"]).first()
        if resource_type is None:
            return f'Tipo de recurso "{args["resource_type"]}" não encontrado — nada alterado.'
        # Matched by (type, name): a type can have several resources (two
        # different upstreams, for example) — name is what tells them
        # apart, same as the consultant's own manual form does.
        resource = Resource.objects.filter(type=resource_type, name=args["resource_name"]).first()
        if resource is None:
            resource = Resource(
                tenant=assessment.tenant,
                type=resource_type,
                name=args["resource_name"],
                observed_at=timezone.now(),
            )
        resource.status = args["status"]
        resource.description = args["description"]
        if args.get("capacity_gbps") is not None:
            resource.capacity_gbps = Decimal(str(args["capacity_gbps"]))
        if args.get("asn") and "asn" in resource_type.attribute_keys:
            resource.attributes = {**resource.attributes, "asn": args["asn"]}
        resource.observed_at = timezone.now()
        resource.source = "IA (sugestão, a partir da conversa)"
        # Mesmo que o recurso já estivesse publicado pro cliente, uma
        # edição da IA sempre volta a exigir revisão manual — nunca troca
        # o que o cliente vê sem o consultor decidir de novo.
        resource.published = False
        save_record(actor, resource)
        return (
            f'Recurso atualizado (rascunho): {resource_type.name} "{resource.name}" → '
            f"{resource.get_status_display()}"
        )

    if tool_name == "log_metric_observation":
        if args["metric_key"] not in ALLOWED_METRIC_KEYS:
            return (
                f'Métrica "{args["metric_key"]}" não pode ser registrada pela IA — '
                "esse tipo de dado precisa vir de uma fonte de monitoramento real."
            )
        definition = MetricDefinition.objects.filter(key=args["metric_key"]).first()
        if definition is None:
            return f'Métrica "{args["metric_key"]}" não encontrada — nada registrado.'
        estimated = bool(args.get("estimated"))
        assumptions = args.get("assumptions", "")
        if estimated and not assumptions.strip():
            return "Estimativa precisa de uma premissa (assumptions) — nada registrado."
        save_record(
            actor,
            MetricObservation(
                tenant=assessment.tenant,
                definition=definition,
                value=Decimal(str(args["value"])),
                observed_at=timezone.now(),
                source="IA (sugestão, a partir da conversa)",
                assumptions=assumptions,
                estimated=estimated,
                author=actor,
                published=False,
            ),
        )
        return (
            f"Métrica registrada (rascunho): {definition.name} = {args['value']} {definition.unit}"
        )

    return f"Ferramenta desconhecida: {tool_name}"


def _history_messages(conversation: AIConversation, tenant, assessment: Assessment) -> list[dict]:
    """Builds the system+context+past-turns prefix for a new call to
    send_message. Past turns are reconstructed as plain user/assistant
    text (every prior turn always finished on a role=assistant message —
    see send_message's loop — so this never ends on a tool/assistant
    prefill-style message); tool_call_id correlation is only needed
    *within* the live loop below, not across turns.
    """
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": build_tenant_context(tenant, assessment)},
    ]
    for message in conversation.messages.all():
        if message.role == AIMessage.Role.TOOL:
            continue
        messages.append({"role": message.role, "content": message.content})
    return messages


def send_message(actor, conversation: AIConversation, user_text: str) -> list[AIMessage]:
    """Orchestrator — records `user_text` (skipped when blank, for the
    very first automatic turn), calls OpenRouter with the full context,
    executes any tool calls in a loop (capped at MAX_TOOL_ITERATIONS so a
    model that won't stop calling tools can't hang the request forever),
    and returns every AIMessage created this call (for the view to
    render without a second query).

    Tool calls/results are kept in-memory in OpenAI's own
    assistant-with-tool_calls + role=tool protocol for the live back-and
    -forth below — Claude (via OpenRouter) refuses to continue a
    conversation whose last message is assistant-authored ("assistant
    message prefill"), so the loop must never hand back a message list
    ending in anything but tool/user.
    """
    tenant = conversation.tenant
    assessment = conversation.assessment or ensure_open_assessment(actor, tenant)
    if conversation.assessment_id != assessment.id:
        conversation.assessment = assessment
        conversation.save(update_fields=["assessment"])
    created: list[AIMessage] = []

    messages = _history_messages(conversation, tenant, assessment)
    if user_text.strip():
        created.append(
            AIMessage.objects.create(
                tenant=tenant,
                conversation=conversation,
                role=AIMessage.Role.USER,
                content=user_text,
            )
        )
        messages.append({"role": "user", "content": user_text})

    for _ in range(MAX_TOOL_ITERATIONS):
        response = call_openrouter(messages, TOOLS)
        choice = response["choices"][0]["message"]
        tool_calls = choice.get("tool_calls") or []

        if not tool_calls:
            created.append(
                AIMessage.objects.create(
                    tenant=tenant,
                    conversation=conversation,
                    role=AIMessage.Role.ASSISTANT,
                    content=choice.get("content") or "",
                )
            )
            break

        messages.append(choice)
        for call in tool_calls:
            name = call["function"]["name"]
            args = json.loads(call["function"]["arguments"] or "{}")
            summary = execute_tool_call(actor, assessment, name, args)
            created.append(
                AIMessage.objects.create(
                    tenant=tenant,
                    conversation=conversation,
                    role=AIMessage.Role.TOOL,
                    content=summary,
                    tool_name=name,
                    tool_args=args,
                )
            )
            messages.append(
                {"role": "tool", "tool_call_id": call.get("id", name), "content": summary}
            )
    return created
