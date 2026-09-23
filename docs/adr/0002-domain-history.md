# ADR 0002 — Histórico e regras estratégicas

Metodologias são snapshots imutáveis do catálogo. Avaliações publicadas e suas
respostas ficam congeladas; nova avaliação preserva o histórico anterior.
Pontuação: atendido=1, parcial=0,5, não atendido=0; não aplicável sai do denominador.
Área sem itens aplicáveis tem score nulo. Níveis são cumulativos e exigem todos
os critérios obrigatórios atendidos; não aplicável não satisfaz requisito.

RoadmapPlacement organiza Recommendation sem duplicar estado. Dependências são
um DAG por tenant. Escritas no grafo, transições e publicação de avaliações
serializam por lock do tenant para evitar corridas. Não aplicável não desbloqueia.
Bloqueio derivado de dependências é calculado; bloqueio manual tem motivo próprio.

Conclusão gera evento na mesma transação; repetir a mesma transição não duplica.
Reabertura gera novo marco, preservando conclusão anterior, e é impedida se houver
dependentes em andamento/concluídos. Auditoria registra antes/depois, é interna
e append-only no PostgreSQL. Métricas preservam origem e data de observação.

Fase 2 terá adaptadores, identificação externa, idempotência e política de fonte
por campo. Fases 3/4 precisam de versão de regra, evidências, janela temporal e
aprovação editorial. Não há credenciais de integração na Fase 1.
