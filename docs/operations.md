# Operação self-hosted

## Produção com HTTPS

Pré-requisitos: servidor com Docker Engine/Compose >= 2.24.4, domínio apontado para
o servidor, portas 80/443 disponíveis e serviço SMTP configurado. Defina no `.env`:

- SECRET_KEY e senhas independentes, aleatórias e fortes; arquivo com permissão 0600.
- DOMAIN e ALLOWED_HOSTS com o domínio real; CSRF_TRUSTED_ORIGINS=https://seu.dominio.
- EMAIL_HOST, EMAIL_PORT, EMAIL_HOST_USER, EMAIL_HOST_PASSWORD e DEFAULT_FROM_EMAIL.
- EMAIL_USE_TLS=true para SMTP com STARTTLS. Não utilize backend de console em produção.

```sh
chmod 600 .env
docker compose -f compose.yaml -f compose.production.yaml up --build -d --wait
docker compose exec web python backend/manage.py createsuperuser
docker compose exec web python backend/manage.py seed_catalog
docker compose exec web python backend/manage.py check --deploy
docker compose exec web python backend/manage.py check_runtime_db
```

Caddy solicita/renova certificados; preserve seus volumes. Não exponha `web:8000`
ou PostgreSQL diretamente. O proxy sobrescreve X-Real-IP e Django confia no protocolo
encaminhado somente porque a aplicação está em rede privada. Se houver outro proxy
na frente, configure conscientemente a cadeia de proxies confiáveis.

O serviço web usa filesystem somente leitura e /tmp temporário. Secrets ficam nas
variáveis do ambiente Docker (visíveis a administradores do host). Não há senhas
de roteadores/servidores ou tokens de integração armazenados no modelo do MVP.
Não cole credenciais em campos de texto livre ou observações.

O papel `isp_owner` é exclusivo das migrations. `isp_app` não pode ser proprietário,
superusuário ou BYPASSRLS. O script de inicialização é executado somente no primeiro
uso de um volume vazio: mudar a senha em `.env` não altera usuários de um volume
existente. Para rotação, altere a senha no PostgreSQL e atualize o ambiente em uma
janela controlada. A aplicação recusa iniciar com papel privilegiado.

## Cadastro e publicação

Clientes visualizam apenas registros publicados. Rascunhos de avaliações não são
compartilhados. Métricas são append-only: escolha a visibilidade ao registrá-las;
um novo valor preserva os anteriores. Campos internos ficam restritos à consultoria.
Superusuários têm acesso administrativo; use contas individuais e privilégios de
consultor para a operação diária. Desative usuários desligados e revise memberships.

Não existe inscrição pública. Um administrador pode criar usuários com senha inicial
ou enviar link de definição por SMTP. Teste login, recuperação e envio de convite
com uma conta de teste antes de disponibilizar o portal aos clientes.

## Backup

Faça backups diários e antes de qualquer upgrade. O script usa pg_dump consistente,
um arquivo temporário com permissão restrita e criptografia age. Instale `age` no
host e forneça **somente a chave pública** ao processo de backup:

```sh
BACKUP_DIR=/caminho/protegido AGE_RECIPIENT=age1... ./deploy/backup/backup.sh
```

A chave privada deve ficar fora do servidor. O dump temporário é removido por trap;
o script aborta se pg_dump ou criptografia falhar. Mantenha o diretório em volume
criptografado, especialmente para proteger um dump interrompido por falha do host.
Transfira os `.dump.age` para armazenamento externo com permissões restritas e
retenção definida. O agendamento, destino e credenciais do backup dependem do
ambiente real e não são configurados automaticamente pelo portal.

Guarde separadamente `.env`, chaves e documentação de recuperação. Volume Docker,
RAID e snapshot no mesmo host não substituem cópia externa. Proposta inicial de
operação: backup diário, retenção de 30 dias e exercício de restauração mensal;
RPO/RTO devem ser validados com o responsável pelo serviço.

## Restauração em ambiente isolado

Nunca teste restauração sobre o banco ativo. Em uma instalação isolada, inicialize
PostgreSQL e seus papéis, mas não execute migrations antes de restaurar o dump:

```sh
# Em um diretório/projeto de recuperação, com .env próprio:
docker compose up -d db
umask 077
age -d -i /caminho/fora-do-servidor/chave.agekey -o /tmp/isp-restore.dump backup.dump.age
docker compose exec -T db pg_restore -U isp_owner -d isp_panel --no-owner --no-privileges --exit-on-error < /tmp/isp-restore.dump
```

O banco deve estar vazio. O pg_restore recria tabelas, índices, constraints, RLS e
triggers. Os default privileges definidos no init concedem acesso a isp_app para
as tabelas restauradas. Depois da restauração, execute migrations da versão de
código correspondente, `check_runtime_db`, login e testes com dois tenants.
Compare contagens, últimas avaliações, recomendações e eventos. Remova o dump
descriptografado após a validação. Só planeje a troca do ambiente ativo depois de
confirmar integridade e acessos; preservar o banco anterior permite retorno.

## Atualização

1. Leia migrations/ADRs e faça backup validado.
2. Teste a atualização numa cópia isolada.
3. Interrompa tráfego durante migrations que afetem compatibilidade.
4. Reconstrua a imagem e execute o serviço migrate antes de subir web.
5. Execute check_runtime_db, verifique /health/ e os fluxos de cliente/consultoria.

`/health/` testa a conexão ao banco sem expor dados. Logs de acesso do Gunicorn
registram status e duração, evitando URLs com tokens de recuperação de senha.
Auditoria do domínio é consultada por tenant; eventos de segurança ficam no admin.
Configure rotação dos logs Docker no host e monitore disco, certificados, falhas
HTTP, SMTP e sucesso dos backups.

Agende `python backend/manage.py clearsessions` diariamente. Contadores de
rate-limit são persistentes e compartilhados; execute `prune_auth_attempts` diariamente
para remover janelas antigas. Não remova auditoria automaticamente sem definir
uma política explícita de retenção.

## Limites conhecidos

- Instância única; sem alta disponibilidade e sem fila de envio de e-mail.
- As consultas estratégicas foram projetadas para os primeiros clientes e volumes
  manuais. Revise índices/consultas antes de introduzir coleta volumosa.
- Testes de RLS pressupõem PostgreSQL 17, não SQLite.
- Deploy real, entrega SMTP, emissão de certificado e armazenamento externo de
  backups dependem das configurações e credenciais do ambiente escolhido.

HSTS está habilitado por um ano no portal em produção. `check --deploy` pode emitir
W005/W021 porque `includeSubDomains` e preload ficam desativados por padrão.
São escolhas de domínio: só configure HSTS_INCLUDE_SUBDOMAINS=true e HSTS_PRELOAD=true
quando todos os subdomínios estiverem preparados e a política de preload for desejada.
Não é necessário habilitá-los para que o portal use HTTPS e cookies seguros.
