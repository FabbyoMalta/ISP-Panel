# ADR 0001 — Monólito modular e isolamento

Status: aprovado pelo usuário em 23/09/2026.

Django 5.2 LTS, PostgreSQL 17, templates/HTMX/Tailwind, DRF e Caddy.
Módulos compartilham serviços transacionais entre HTML e API. Não há chamadas
HTTP internas nem workers na Fase 1.

Cada ISP é um tenant, com Client 1:1. Usuários são globais; memberships autorizam
clientes. Consultores acessam um tenant explícito por requisição. Catálogos e
listagem de tenants são globais, protegidos por permissões próprias.

Tabelas de negócio têm tenant_id, manager com negação sem contexto, RLS forçada
e FKs compostas no PostgreSQL. SET LOCAL é limitado à transação. Contexto Python
usa ContextVar e é restaurado inclusive em exceções. O papel runtime não pode
ser proprietário/superusuário/BYPASSRLS; migrations usam identidade separada.

SQLite é permitido somente para desenvolvimento/testes funcionais; não comprova
RLS. CI PostgreSQL e comando check_runtime_db verificam isolamento real.

Notas internas nunca são incluídas no serializer de cliente. Publicação e estado
de execução são conceitos distintos. IDs UUID não são mecanismos de autorização.
