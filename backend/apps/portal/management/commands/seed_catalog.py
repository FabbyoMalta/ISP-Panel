from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.assessments.models import (
    AssessmentCategory,
    AssessmentItemDefinition,
    AssessmentTemplateVersion,
    MaturityLevel,
    MaturityRule,
)
from apps.assessments.services import publish_catalog
from apps.inventory.models import ResourceType
from apps.metrics.models import MetricDefinition

CATEGORIES = {
    "Rede e Backbone": [
        "Capacidade de trânsito",
        "Monitoramento da utilização de links",
        "Capacidade de interfaces",
        "Redundância física de backbone",
    ],
    "Internet / BGP": [
        "ASN próprio",
        "IPv6 implantado",
        "BGP próprio",
        "Segundo upstream",
        "RPKI e políticas de roteamento",
        "Engenharia de tráfego",
    ],
    "Serviços de infraestrutura": [
        "DNS recursivo adequado",
        "DNS autoritativo e reverso",
        "NTP",
        "RADIUS redundante",
        "CGNAT dimensionado",
    ],
    "Monitoramento": [
        "Monitoramento de equipamentos",
        "Monitoramento de links",
        "Alertas acionáveis",
    ],
    "Observabilidade": [
        "Syslog centralizado",
        "NetFlow / NetStream",
        "Retenção de logs e métricas",
        "Telemetria",
    ],
    "Segurança": [
        "Backups de configuração",
        "Controle de acesso",
        "Proteção da infraestrutura",
        "Plano de recuperação de desastre",
    ],
    "Documentação": [
        "Inventário e IPAM",
        "Documentação de POPs e enlaces",
        "VLANs e diagramas",
        "Procedimentos documentados",
    ],
    "Operação": [
        "Gestão de incidentes",
        "Gestão de mudanças",
        "Capacity planning",
        "Automações",
        "Provisionamento automatizado",
    ],
}
LEVELS = {
    "Essencial": [
        "Monitoramento de equipamentos",
        "Backups de configuração",
        "Inventário e IPAM",
        "DNS recursivo adequado",
        "Controle de acesso",
    ],
    "Resiliência": [
        "ASN próprio",
        "IPv6 implantado",
        "BGP próprio",
        "Segundo upstream",
        "Redundância física de backbone",
        "CGNAT dimensionado",
    ],
    "Operação": [
        "Syslog centralizado",
        "NetFlow / NetStream",
        "Alertas acionáveis",
        "Capacity planning",
        "Gestão de incidentes",
    ],
    "Escala": [
        "Automações",
        "Telemetria",
        "Engenharia de tráfego",
        "Plano de recuperação de desastre",
        "Provisionamento automatizado",
    ],
}


class Command(BaseCommand):
    help = "Cria catálogos iniciais sem sobrescrever alterações administrativas."

    @transaction.atomic
    def handle(self, *args, **options):
        actor = get_user_model().objects.filter(is_superuser=True, is_active=True).first()
        if not actor:
            raise CommandError("Crie um superusuário antes de inicializar os catálogos.")
        definitions = {}
        for order, (category_name, titles) in enumerate(CATEGORIES.items()):
            category, _ = AssessmentCategory.objects.get_or_create(
                name=category_name, defaults={"order": order}
            )
            for title in titles:
                item, _ = AssessmentItemDefinition.objects.get_or_create(
                    category=category, title=title
                )
                definitions[title] = item
        for order, (name, requirements) in enumerate(LEVELS.items(), 1):
            level, created = MaturityLevel.objects.get_or_create(
                order=order, defaults={"name": name}
            )
            if created:
                for title in requirements:
                    MaturityRule.objects.create(level=level, item=definitions[title])
        for name, keys in {
            "Upstream": ["operadora", "circuito"],
            "ASN": ["numero"],
            "IPv4": ["prefixo"],
            "IPv6": ["prefixo"],
            "Roteador de borda": ["fabricante", "modelo"],
            "Servidor": ["funcao"],
            "CGNAT": ["plataforma"],
            "DNS": ["funcao"],
            "RADIUS": ["plataforma"],
            "Monitoramento": ["plataforma"],
            "Documentação": ["plataforma"],
        }.items():
            ResourceType.objects.get_or_create(name=name, defaults={"attribute_keys": keys})
        for key, name, unit in [
            ("active-subscribers", "Clientes ativos", "clientes"),
            ("estimated-subscribers", "Capacidade estimada de clientes", "clientes"),
            ("peak-gbps", "Tráfego de pico", "Gbps"),
            ("capacity-gbps", "Capacidade de trânsito IP", "Gbps"),
        ]:
            MetricDefinition.objects.get_or_create(key=key, defaults={"name": name, "unit": unit})
        if not AssessmentTemplateVersion.objects.exists():
            publish_catalog(actor)
        self.stdout.write(self.style.SUCCESS("Catálogos inicializados."))
