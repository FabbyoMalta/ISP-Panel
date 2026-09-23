# Arquitetura

Monólito modular: Python/Django 5.2, PostgreSQL 17, DRF, templates, HTMX, Tailwind e
Chart.js. Caddy termina HTTPS, Gunicorn executa a aplicação. Assets são locais.

```
Navegador → Caddy → Django (HTML/HTMX e API)
                         ↓ serviços transacionais
                      PostgreSQL
```

`portal` compõe formulários, consultas de dashboard e adaptadores HTTP. Os serviços
nos módulos de negócio são a autoridade para publicação, dependências e transições.
`portal.services.save_record` centraliza autorização de edição e auditoria dos
cadastros. Não há signals para regras de negócio; signals de autenticação apenas
registram eventos de segurança.

## Isolamento

A rota contém um tenant explícito. O middleware verifica login, tenant ativo e
membership ou papel de consultoria antes de abrir `tenant_context`. O contexto
instala `SET LOCAL app.tenant_id` dentro de uma transação, restaura o contexto em
exceções e mantém o filtro Python via ContextVar. Sem contexto, consultas de negócio
retornam zero linhas. RLS e FKs compostas reforçam esse contrato no PostgreSQL.

Tabelas globais: usuários, memberships, tenants, catálogos, versões de metodologia,
contadores de autenticação e eventos de segurança. Suas interfaces têm permissões
próprias. A carteira lista apenas identidade dos clientes autorizados; não agrega
SQL irrestrito das tabelas técnicas.

O cliente é somente leitura. Visibilidade editorial é filtrada antes da serialização
ou renderização. Notas internas são removidas do serializer e nunca renderizadas
para clientes. Pré-requisitos internos aparecem apenas como indicação genérica de
bloqueio. Sessões exigem CSRF para escrita; não há JWT no armazenamento do navegador.

## Evolução

- Fase 2: módulo de adaptadores e workers; Integration/IntegrationRun/ExternalObjectMapping;
  timeouts, retentativas, idempotência, proteção de destinos e credenciais externas protegidas.
- Fase 3: observações agregadas, janelas temporais, cobertura e versões das regras de análise;
  sem replicar toda a telemetria operacional.
- Fase 4: recomendações com evidências, origem e aprovação editorial do consultor.
  Nenhuma alteração autônoma de infraestrutura.

Os modelos futuros não têm tabelas vazias antecipadas no MVP. Categorias, níveis,
requisitos e pesos já são administráveis. O banco compartilhado simplifica a
operação inicial; grandes volumes ou exigências contratuais podem justificar
mover um tenant para banco dedicado posteriormente.
