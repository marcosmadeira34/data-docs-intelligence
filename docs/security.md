# Segurança, privacidade e implantação

## Controles implementados

| Área | Controle | Onde |
|---|---|---|
| Senhas | Argon2id; política mínima (10+ caracteres, não só letras/números); tempo constante para e-mail inexistente | `core/security.py`, `organizations/schemas.py` |
| Força bruta | Bloqueio temporário por e-mail+IP após falhas (`DDI_LOGIN_MAX_ATTEMPTS`, `DDI_LOGIN_LOCKOUT_SECONDS`); mensagem genérica | `core/security.py` |
| Sessão | JWT HS256 com expiração, em cookie httpOnly `SameSite=Strict` (+ `Secure` com `DDI_COOKIE_SECURE`); Bearer para integrações | `organizations/router.py` |
| CSRF | Double-submit (`ddi_csrf` + `X-CSRF-Token`) para requisições autenticadas por cookie | `api/deps.py` |
| Autorização | Papel verificado no backend por rota; participação e status reverificados no banco a cada requisição (desativação tem efeito imediato) | `api/deps.py` |
| Isolamento multiempresa | Toda consulta filtra `organization_id`; `get_owned` devolve 404 para recursos de outra organização (anti-IDOR/enumeração) | todos os routers |
| Upload | Limite por `Content-Length` e em streaming; formato real por conteúdo; rejeita binários disfarçados, `.xls` OLE, macros (`vbaProject.bin`), ZIP com descompressão excessiva; XML lido com `defusedxml`; nomes internos aleatórios; armazenamento privado com permissão 0600 | `domain/ingestion/detect.py`, `files/service.py`, `infrastructure/storage` |
| Download | Somente pela API autenticada, com auditoria, `Content-Disposition: attachment`, `nosniff`, `no-store` | `files/router.py` |
| Exportações | Mesmas permissões dos arquivos; células iniciadas por `= + - @ \t \r | %` são neutralizadas | `reports/export.py` |
| Execução de código | Nenhuma: regras são declarativas; regex restrita (sem backreferences, lookarounds, quantificadores aninhados, repetições > 999; entrada truncada) | `domain/validation/rules.py` |
| Prompt injection | Conteúdo de arquivos tratado como dado; IA recebe só metadados por padrão; saída restrita a destinos enumerados e revalidada; nada é aprovado automaticamente | `infrastructure/ai` |
| Dados em logs | Logs JSON apenas com ids, hashes e contagens; teste automatizado garante que valores de células não aparecem | `core/logging.py`, `tests/test_security.py` |
| Dados em respostas | Prévias e valores observados mascarados (CPF/CNPJ, e-mail, conta); erros de validação não ecoam a entrada; chaves de armazenamento nunca expostas | `domain/values.py`, `main.py` |
| Cabeçalhos | `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store` na API | `main.py`, `next.config.mjs` |
| Retenção | `retention_until` por arquivo; worker expurga o conteúdo vencido e audita | `files/service.py`, `worker.py` |
| Auditoria | Login, upload/rejeição/download/exclusão, perfis, aprovação de mapeamento, regras, execuções, exportações, membros e senhas | `audit` |
| Segredos | Somente variáveis de ambiente; aplicação recusa iniciar em produção com a chave de desenvolvimento | `core/config.py` |

Testes que demonstram os controles: [backend/tests/test_security.py](../backend/tests/test_security.py) (acesso cruzado de leitura,
alteração, download, exclusão e listagens; papéis; CSRF; tokens forjados/expirados; vazamento em logs e erros; cotas)
e [backend/tests/test_ingestion.py](../backend/tests/test_ingestion.py) (uploads maliciosos).

## LGPD — preparação (sem afirmação de conformidade)

O sistema oferece meios técnicos; a conformidade depende das bases legais, contratos e processos de cada escritório.

- **Minimização**: prévias limitadas a 20 linhas e mascaradas; achados guardam no máximo 120 caracteres mascarados
  do valor; IA não recebe valores por padrão.
- **Retenção e eliminação**: prazo configurável (`DDI_FILE_RETENTION_DAYS`), exclusão manual por administrador,
  expurgo automático. Metadados (nome, hash, datas) permanecem para trilha de auditoria.
- **Rastreabilidade**: trilha de auditoria por organização.
- **Pendências** para operação comercial: atendimento a titulares (exportação/eliminação por titular), registro
  de operações de tratamento, DPA com clientes e com o provedor de IA (se habilitado), política de privacidade,
  criptografia de backups e definição de região de armazenamento.

## Backup e restauração (procedimento recomendado)

- **PostgreSQL**: `pg_dump -Fc` diário + WAL contínuo (PITR) no serviço gerenciado; retenção de 30 dias;
  restauração testada mensalmente em ambiente isolado (`pg_restore -d <novo_banco>` e `alembic current`).
- **Objetos**: versionamento e criptografia do bucket (SSE), replicação entre regiões se exigido; política de
  ciclo de vida coerente com `DDI_FILE_RETENTION_DAYS` (objetos expurgados não devem ser restaurados por backup).
- **Ordem de restauração**: banco → objetos → `alembic upgrade head` → `python -m app.cli bootstrap` → subir api/worker.
- Ambiente Docker local: `docker compose exec db pg_dump -U ddi -Fc ddi > backup.dump` e o volume `storage`.

## Checklist de implantação

- [ ] `DDI_ENVIRONMENT=production`, `DDI_SECRET_KEY` aleatório (≥ 32 bytes) em gerenciador de segredos
- [ ] HTTPS terminado em proxy/balanceador; `DDI_COOKIE_SECURE=true`; HSTS no proxy
- [ ] Limite de corpo no proxy coerente com `DDI_MAX_UPLOAD_BYTES`; timeouts de upload
- [ ] PostgreSQL gerenciado com backups/PITR, TLS e usuário de aplicação sem superusuário
- [ ] `DDI_STORAGE_BACKEND=s3`, bucket privado, bloqueio de acesso público, SSE, credenciais de escopo mínimo
- [ ] `DDI_ALLOW_SIGNUP=false` se as organizações forem provisionadas manualmente
- [ ] Pelo menos 1 réplica do worker; alertas para jobs `failed` e fila crescente
- [ ] Coleta dos logs JSON (stdout) com retenção definida; sem logging de corpo de requisição no proxy
- [ ] Health checks `/health/live` (liveness) e `/health/ready` (readiness) configurados
- [ ] `alembic upgrade head` e `python -m app.cli bootstrap` no pipeline de deploy (serviço `migrate`)
- [ ] Se usar IA: `DDI_AI_PROVIDER=anthropic`, chave em segredo, avaliação contratual/DPA, `DDI_AI_SEND_SAMPLE_VALUES=false` salvo decisão explícita
- [ ] Bloqueio de login distribuído (Redis/banco) se houver várias réplicas da API
- [ ] Revisão de dependências (`pip-audit`, `npm audit`) e atualização de imagens base
