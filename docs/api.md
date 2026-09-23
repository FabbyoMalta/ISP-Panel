# API v1

Autenticação por sessão Django, mesma origem da interface. Escritas exigem cookie
de sessão e `X-CSRFToken` válido. Não armazenar senhas/tokens no localStorage.
OpenAPI autenticado: `/api/schema/` (ou gere via comando `spectacular`).

- `/api/v1/tenants/`: empresas autorizadas ao usuário (somente leitura).
- `/api/v1/assessment-categories/`: catálogo de áreas (somente leitura).
- `/api/v1/t/{tenant_uuid}/`: recursos com escopo explícito.

| Recurso no tenant | Operações |
|---|---|
| clients, contacts | GET, POST, PATCH |
| resources, risks, external-links | GET, POST, PATCH |
| metrics | GET, POST; PATCH rejeitado para preservar histórico |
| recommendations | GET, POST, PATCH de conteúdo/editorial |
| recommendations/{id}/transition/ | POST status e reason; verifica dependências |
| dependencies | GET, POST; DELETE /{id}/ via serviço de dependências |
| roadmap, risk-links | GET, POST, PATCH |
| assessments | GET, POST, PATCH apenas enquanto rascunho |
| assessments/{id}/answer/ | POST item_key, status, comment e internal_notes opcional |
| assessments/{id}/answers/ | GET metodologia e respostas visíveis |
| assessments/{id}/publish/ | POST; valida completude e congela diagnóstico |
| events | GET, POST, PATCH |
| audit | GET; somente consultoria recebe registros |

Clientes podem apenas GET. Campos internos nunca estão em respostas de clientes.
IDs de outro tenant retornam 404 ou erro de relacionamento, sem revelar o objeto.
`tenant`, IDs, estado de execução e datas automáticas não podem ser forçados em PATCH.

Listas retornam `{count, next, previous, results}`, 50 registros por página.
Use `?page=2`. Ordenação definida pelo recurso. Erros de validação retornam 400;
acesso negado, 403; objeto inacessível/inexistente, 404. Autenticação ausente retorna
403 no modo de sessão. A escolha do tenant nunca vem de um payload confiado cegamente.

Exemplo de transição autenticada:

```http
POST /api/v1/t/{tenant}/recommendations/{id}/transition/
Content-Type: application/json
X-CSRFToken: <csrf da sessão>

{"status": "done"}
```

Gerenciamento de usuários, memberships, criação de tenants e publicação de catálogos
estão disponíveis na interface administrativa. Integrações, tokens de serviço e
chamadas externas não fazem parte desta fase.
