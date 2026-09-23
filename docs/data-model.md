# Modelo de dados

| Grupo | Relações |
|---|---|
| Identidade | User N:N Tenant via TenantMembership; papel global admin/consultant/client |
| Empresa | Tenant 1:1 Client; Tenant 1:N ClientContact |
| Catálogos | AssessmentCategory 1:N AssessmentItemDefinition; MaturityLevel N:N critérios via MaturityRule |
| Metodologia | AssessmentTemplateVersion preserva snapshot completo e imutável de critérios, pesos e requisitos |
| Avaliação | Tenant 1:N Assessment; Assessment 1:N AssessmentAnswer; resposta única por item da versão |
| Inventário | ResourceType 1:N Resource; atributos JSON limitados às chaves permitidas |
| Capacidade | MetricDefinition 1:N MetricObservation; observação tem data, fonte, autor e premissas |
| Evolução | Tenant 1:N Recommendation; relação dirigida RecommendationDependency; RoadmapPlacement 0..1 por recomendação |
| Riscos | Tenant 1:N Risk; Recommendation N:N Risk via RecommendationRisk |
| Marcos | Tenant 1:N Event; referência opcional à recomendação concluída |
| Acesso externo | Tenant 1:N ExternalLink; somente HTTP(S), sem embedding |
| Auditoria | AuditEntry por tenant; SecurityEvent global; ambos internos e append-only em PostgreSQL |

Todas as tabelas de negócio têm UUID, tenant_id, created_at e updated_at. Catálogos
usam identificadores globais. FKs entre tabelas de negócio são verificadas por
(tenant_id, id) no banco. Deleções destrutivas não são oferecidas na API de cadastros;
usuários/tenants podem ser desativados, recursos inativados e riscos mitigados.

## Cálculos

Atendido=1, parcial=0,5, não atendido=0. A pontuação por área é a média ponderada
multiplicada por 100, arredondada para inteiro. Não aplicável é excluído; se não
houver itens aplicáveis, score=null. Não há publicação de avaliação incompleta.
Níveis são cumulativos; cada requisito obrigatório deve estar atendido. O resultado
inclui os critérios pendentes do próximo nível.

Métricas não são editadas: uma nova observação atualiza o histórico. A escolha de
publicação é feita no registro. Capacidade estimada exige premissas. Uso percentual
é uma comparação dos últimos valores publicados de pico e capacidade; suas datas
são mostradas separadamente e o resultado não é previsão automática de capacidade.

Metodologias e avaliações publicadas são imutáveis. Mudanças administrativas geram
novas versões. Eventos preservam marcos; reabrir uma melhoria gera novo evento e
não remove a conclusão histórica. Edições manuais de eventos são auditadas.
