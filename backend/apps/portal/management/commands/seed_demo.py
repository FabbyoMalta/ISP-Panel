import os
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.assessments.models import AssessmentCategory, AssessmentTemplateVersion
from apps.assessments.services import answer_assessment, publish_assessment, start_assessment
from apps.clients.models import Client, ClientContact
from apps.external_links.models import ExternalLink
from apps.inventory.models import Resource, ResourceType
from apps.metrics.models import MetricDefinition, MetricObservation
from apps.recommendations.models import Recommendation, RoadmapPlacement
from apps.recommendations.services import add_dependency, transition
from apps.risks.models import Risk
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Tenant, TenantMembership
from apps.timeline.models import Event


class Command(BaseCommand):
    help = "Dados exclusivamente fictícios. Exige DEBUG=true e DEMO_PASSWORD forte."

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("seed_demo é permitido somente com DEBUG=true.")
        password = os.getenv("DEMO_PASSWORD")
        if not password:
            raise CommandError("Defina DEMO_PASSWORD; nenhuma senha padrão é distribuída.")
        validate_password(password)
        User = get_user_model()
        admin, created = User.objects.get_or_create(
            username="consultor.demo",
            defaults={
                "email": "consultor@example.test",
                "role": "admin",
                "is_staff": True,
                "is_superuser": True,
                "first_name": "Alex",
            },
        )
        if created:
            admin.set_password(password)
            admin.save()
        client_user, created = User.objects.get_or_create(
            username="cliente.demo",
            defaults={"email": "cliente@example.test", "first_name": "Marina"},
        )
        if created:
            client_user.set_password(password)
            client_user.save()
        call_command("seed_catalog")
        tenant, created = Tenant.objects.get_or_create(
            slug="horizonte-fibra", defaults={"name": "Horizonte Fibra"}
        )
        TenantMembership.objects.get_or_create(tenant=tenant, user=client_user)
        if not created:
            self.stdout.write("Demonstração já existe; dados e senhas não foram alterados.")
            return
        now = timezone.now()
        with tenant_context(tenant.pk):
            Client.objects.create(
                tenant=tenant,
                legal_name="Horizonte Fibra Telecomunicações Ltda. (fictícia)",
                trade_name="Horizonte Fibra",
                region="Interior de São Paulo",
                joined_on=now.date() - timedelta(days=150),
                internal_notes="Dados fictícios para demonstração. Não utilizar para decisões reais.",
            )
            ClientContact.objects.create(
                tenant=tenant,
                name="Marina Almeida (fictício)",
                position="Responsável técnica",
                email="marina@example.test",
            )
            for key, value, estimated in [
                ("active-subscribers", 1842, False),
                ("estimated-subscribers", 2500, True),
                ("peak-gbps", 4.7, False),
                ("capacity-gbps", 6, False),
            ]:
                MetricObservation.objects.create(
                    tenant=tenant,
                    definition=MetricDefinition.objects.get(key=key),
                    value=str(value),
                    observed_at=now,
                    source="Cenário fictício de demonstração",
                    estimated=estimated,
                    assumptions="Estimativa manual considerando perfil de uso, capacidade do concentrador e trânsito contratado. Revisar a cada avaliação."
                    if estimated
                    else "",
                    author=admin,
                    published=True,
                )
            for name, typ, capacity in [
                ("ASN próprio", "ASN", None),
                ("IPv6 em produção", "IPv6", None),
                ("Trânsito IP · Operadora A", "Upstream", 6),
                ("Borda principal", "Roteador de borda", None),
                ("DNS recursivo local", "DNS", None),
                ("Monitoramento de rede", "Monitoramento", None),
            ]:
                Resource.objects.create(
                    tenant=tenant,
                    name=name,
                    type=ResourceType.objects.get(name=typ),
                    capacity_gbps=capacity,
                    observed_at=now,
                    published=True,
                    source="Demonstração fictícia",
                )
            for title, severity, description in [
                (
                    "Dependência de um único upstream",
                    "high",
                    "Uma indisponibilidade na operadora de trânsito pode interromper o acesso de todos os assinantes.",
                ),
                (
                    "Servidor RADIUS sem redundância",
                    "medium",
                    "Falhas no servidor podem comprometer novas autenticações e a continuidade da operação.",
                ),
                (
                    "Retenção de logs não estruturada",
                    "medium",
                    "A ausência de histórico centralizado dificulta a investigação de incidentes e a análise técnica.",
                ),
            ]:
                Risk.objects.create(
                    tenant=tenant,
                    title=title,
                    severity=severity,
                    description=description,
                    published=True,
                )
            recs = {}
            for title, category, priority, justification in [
                (
                    "Obter ASN próprio",
                    "Internet / BGP",
                    "high",
                    "Aumentar a independência e viabilizar políticas próprias de roteamento.",
                ),
                (
                    "Contratar segundo upstream",
                    "Internet / BGP",
                    "high",
                    "Reduzir o risco de indisponibilidade e aumentar a resiliência do acesso à Internet.",
                ),
                (
                    "Implementar redundância RADIUS",
                    "Serviços de infraestrutura",
                    "high",
                    "Garantir continuidade das autenticações em caso de falha do servidor principal.",
                ),
                (
                    "Centralizar Syslog",
                    "Observabilidade",
                    "medium",
                    "Consolidar registros para reduzir o tempo de investigação de incidentes.",
                ),
                (
                    "Revisar políticas BGP de redundância",
                    "Internet / BGP",
                    "medium",
                    "Validar failover após ativar o segundo upstream.",
                ),
            ]:
                recs[title] = Recommendation.objects.create(
                    tenant=tenant,
                    title=title,
                    category=AssessmentCategory.objects.get(name=category),
                    priority=priority,
                    justification=justification,
                    editorial_status="published",
                    effort="A estimar após levantamento",
                    recommended_on=now.date() + timedelta(days=30),
                )
            transition(admin, recs["Obter ASN próprio"], "done")
            add_dependency(admin, recs["Contratar segundo upstream"], recs["Obter ASN próprio"])
            add_dependency(
                admin,
                recs["Revisar políticas BGP de redundância"],
                recs["Contratar segundo upstream"],
            )
            for order, rec in enumerate(recs.values()):
                RoadmapPlacement.objects.create(
                    tenant=tenant,
                    recommendation=rec,
                    order=order,
                    horizon="now" if rec.priority == "high" else "next",
                )
            for days, title, description in [
                (120, "Monitoramento implantado", "Visibilidade sobre equipamentos e enlaces."),
                (90, "IPv6 implantado", "Dual-stack disponível na rede de acesso."),
                (
                    30,
                    "Inventário organizado no NetBox",
                    "Documentação centralizada dos recursos estratégicos.",
                ),
            ]:
                Event.objects.create(
                    tenant=tenant,
                    title=title,
                    description=description,
                    occurred_on=now.date() - timedelta(days=days),
                    published=True,
                )
            for title, url, description in [
                ("NetBox", "https://netbox.example.test", "Inventário e documentação de rede"),
                ("Grafana", "https://grafana.example.test", "Dashboards operacionais"),
                (
                    "Monitoramento",
                    "https://monitoramento.example.test",
                    "Disponibilidade e alertas",
                ),
            ]:
                ExternalLink.objects.create(
                    tenant=tenant,
                    title=title,
                    url=url,
                    description=description + " · link fictício",
                    published=True,
                )
            assessment = start_assessment(
                admin,
                "Diagnóstico de evolução · Setembro",
                now.date(),
                AssessmentTemplateVersion.objects.first(),
                summary="Base organizada, com prioridade para redundância e observabilidade.",
            )
            met = [
                "Monitoramento de equipamentos",
                "Monitoramento de links",
                "Backups de configuração",
                "Inventário e IPAM",
                "DNS recursivo adequado",
                "Controle de acesso",
                "ASN próprio",
                "IPv6 implantado",
                "Capacidade de trânsito",
                "CGNAT dimensionado",
            ]
            for item in assessment.template.snapshot["items"]:
                status = (
                    "met"
                    if item["title"] in met
                    else (
                        "partial"
                        if item["category"] in ["Documentação", "Rede e Backbone", "Segurança"]
                        else "unmet"
                    )
                )
                answer_assessment(
                    admin,
                    assessment,
                    item["key"],
                    status,
                    "Situação fictícia registrada para demonstração.",
                )
            publish_assessment(admin, assessment)
        self.stdout.write(
            self.style.SUCCESS(
                "Demo criada: consultor.demo / cliente.demo. Use a senha definida em DEMO_PASSWORD."
            )
        )
