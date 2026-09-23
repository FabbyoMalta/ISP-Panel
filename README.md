# ISP Panel

Portal técnico e estratégico para assessoria de provedores de Internet. Cada ISP
possui diagnóstico, inventário estratégico, riscos, capacidade, avaliações,
roadmap com dependências e histórico de evolução.

## Fase 1

- Login/logout por sessão, recuperação de senha por e-mail, Argon2 e limitação de tentativas.
- Administradores, consultores e clientes; memberships e isolamento por tenant.
- PostgreSQL com RLS forçada e relacionamentos que impedem cruzamento entre tenants.
- Cadastros de empresas, contatos, recursos, riscos, métricas e links externos.
- Catálogos administráveis, metodologia versionada e avaliações publicadas imutáveis.
- Recomendações, dependências sem ciclos, bloqueios, horizontes e marcos de conclusão.
- Dashboard responsivo, maturidade por área, capacidade e evolução.
- Auditoria restrita, API paginada e especificação OpenAPI.

Não inclui conectores, coleta automática, IA, embedding, armazenamento de credenciais
de equipamentos, gestão de chamados ou ações em infraestrutura. O portal não substitui
NetBox, Zabbix, LibreNMS ou sistemas de gestão do ISP.

## Executar com Docker Compose

Requer Docker Engine e Compose >= 2.24.4. Copie `.env.example` para `.env` e preencha
`SECRET_KEY`, `DB_OWNER_PASSWORD` e `DB_APP_PASSWORD` com valores **independentes**:

```sh
python3 -c 'import secrets; print(secrets.token_hex(32))'
docker compose up --build -d --wait
docker compose exec web python backend/manage.py createsuperuser
docker compose exec web python backend/manage.py seed_catalog
```

Acesse **http://localhost:8080**. O superusuário tem permissões administrativas.
O Compose padrão é de desenvolvimento: DEBUG ligado, HTTP apenas em localhost e
e-mails no console. Produção exige o override descrito em [operação](docs/operations.md).

O serviço `migrate` executa migrations com `isp_owner`; `web` usa `isp_app`, sem
propriedade de tabelas ou BYPASSRLS. A aplicação verifica esses privilégios ao iniciar.
O PostgreSQL e a aplicação não expõem portas no host; somente o proxy é publicado.

## Dados fictícios

Em desenvolvimento, escolha uma senha forte via variável de ambiente:

```sh
read -s DEMO_PASSWORD
export DEMO_PASSWORD
docker compose exec -e DEMO_PASSWORD web python backend/manage.py seed_demo
unset DEMO_PASSWORD
```

Usuários: `consultor.demo` e `cliente.demo`. A senha é a que você definiu. O comando
não redefine senhas nem sobrescreve demonstrações existentes e recusa DEBUG=false.
Todos os dados e links de `Horizonte Fibra` são fictícios. Não use a demo em produção.

## Desenvolvimento local sem Docker

Python >= 3.13 e Node 24 para recompilar assets:

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.lock
npm ci --prefix frontend --ignore-scripts
npm run build --prefix frontend
export DEBUG=true
.venv/bin/python backend/manage.py migrate
.venv/bin/python backend/manage.py createsuperuser
.venv/bin/python backend/manage.py seed_catalog
.venv/bin/python backend/manage.py runserver
```

Sem `DATABASE_URL`, DEBUG permite SQLite. Esse modo serve para desenvolvimento
funcional; **não valida RLS**. Produção recusa SQLite. O Django não carrega `.env`
automaticamente fora do Compose: exporte as variáveis no shell.

Os assets compilados estão versionados e servidos localmente, sem CDNs. Edite
`frontend/src/app.css` e execute o build. Dependências runtime estão em
`requirements.lock`; ferramentas de desenvolvimento estão em `requirements-dev.lock`.

## Fluxo inicial

1. Crie um cliente na carteira e cadastre contatos e recursos estratégicos.
2. Cadastre um usuário cliente em **Usuários**, vinculando-o à empresa correta.
3. Registre métricas, datas, fontes e premissas das estimativas.
4. Crie uma avaliação, responda todos os critérios e publique o diagnóstico.
5. Registre riscos e recomendações; publique somente o que o cliente deve consultar.
6. Defina dependências e organize os horizontes em **Roadmap → Organizar horizontes**.
7. Atualize o andamento. Conclusões geram marcos automaticamente.

A administração em `/admin/` mantém categorias, critérios, níveis, regras, tipos de
recursos e métricas. Em critérios, selecione um item e use a ação **Publicar nova
versão completa da metodologia**. Alterações de catálogo não modificam avaliações antigas.
Não aplicável exige justificativa e não satisfaz requisitos obrigatórios de um nível.

## Verificações

```sh
TESTING=true .venv/bin/pytest -q
.venv/bin/ruff check backend tests
.venv/bin/ruff format --check backend tests
DEBUG=true .venv/bin/python backend/manage.py makemigrations --check --dry-run
DEBUG=true .venv/bin/python backend/manage.py spectacular --validate --fail-on-warn --file /tmp/isp-schema.yaml
```

Para testes reais de banco, configure `DATABASE_URL` para uma instância **descartável**
de PostgreSQL 17 com usuário capaz de criar bancos e papéis de teste:

```sh
TESTING=true DATABASE_URL=postgresql://... .venv/bin/pytest -q
```

A suíte inclui SQL direto sob papel sem BYPASSRLS, FKs compostas, imutabilidade de
histórico e concorrência entre dependências. Testes PostgreSQL são marcados como
ignorados quando executados em SQLite. Nunca use o banco de produção nos testes.

Teste de navegador, contra uma demo já inicializada:

```sh
.venv/bin/playwright install chromium
DEMO_PASSWORD='sua-senha-de-demo' .venv/bin/python tests/e2e_smoke.py
```

`PORTAL_URL` configura o endereço; `CHROME_EXECUTABLE` permite usar um Chromium já
instalado. Capturas desktop/mobile ficam em `test-results/` e não são commitadas.

## Documentação

- [Arquitetura e fronteiras](docs/architecture.md)
- [Modelo de dados](docs/data-model.md)
- [API](docs/api.md)
- [Deploy, backup e restauração](docs/operations.md)
- [Decisões arquiteturais](docs/adr/)
- [Estado de validação](docs/validation.md)
