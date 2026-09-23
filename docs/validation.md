# Validação da implementação

Verificado localmente em 23/09/2026:

- Django 5.2.17; Python 3.14.7 no ambiente de desenvolvimento.
- PostgreSQL 17.11 compilado em /tmp para testes, sem instalação de serviço no host.
- **54 testes aprovados** com PostgreSQL, incluindo backup/restore via pg_dump/pg_restore.
- Login administrativo sem sessão e perfil correto no bootstrap do superusuário.
- RLS com papel sem superusuário/BYPASSRLS: leitura sem contexto negada; dados de outro
  tenant inacessíveis por SQL direto; inserção em tenant diferente rejeitada.
- Integridade composta entre tenants, histórico publicado imutável e auditoria append-only.
- Corrida entre dependências opostas produz uma inclusão e uma rejeição, sem ciclo.
- Migrações executadas com isp_owner; check_runtime_db e seed_demo com isp_app restrito.
- Navegador Chromium: login cliente, dashboard, roadmap, gráfico, logout e ausência
  de overflow horizontal em desktop 1440px e mobile 390px; sem erros JavaScript.
- Configurações de produção (DEBUG=false), manifesto estático e requisições autenticadas
  de cliente/consultor validadas com o papel restrito isp_app.
- Build Tailwind, assets locais e collectstatic com manifesto de produção.
- OpenAPI validado sem erros/advertências; lint, formatação e estado das migrations verificados.

## Limites da validação

Docker Engine/Compose não estão instalados neste ambiente. O build da imagem e o
startup conjunto do Compose foram configurados na CI, **mas não executados localmente**.
A CI ainda precisa rodar após o repositório ser enviado ao serviço Git remoto.
A CI usa Python 3.13 e PostgreSQL 17, conforme o alvo de deployment.

Não houve deploy público. Emissão real de certificado, entrega SMTP, agendamento de
backup, criptografia age e envio a armazenamento externo precisam ser verificados
no servidor escolhido. O exercício de restauração local validou dados, policies e
triggers do dump PostgreSQL; não simulou a perda do host ou restauração de chaves.

SQLite é somente uma opção de desenvolvimento: os testes específicos de PostgreSQL
são ignorados nesse modo e não constituem validação de segurança de produção.
