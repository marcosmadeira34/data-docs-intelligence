# API

- Base: `/api/v1`. Especificação OpenAPI interativa em `/api/docs` (Swagger) e `/api/redoc`; JSON em `/api/openapi.json`.
- Autenticação:
  - **Navegador**: `POST /auth/login` define o cookie httpOnly `ddi_access` e o cookie `ddi_csrf`. Requisições que
    alteram estado precisam do cabeçalho `X-CSRF-Token` com o valor de `ddi_csrf`.
  - **Integrações**: use `Authorization: Bearer <access_token>` (retornado no login). CSRF não se aplica.
- A organização ativa vem do token; troque com `POST /auth/switch-organization`.
- Papéis (mínimo exigido): leitura (`viewer`) para consultas e downloads; `analyst` para cadastrar, enviar,
  mapear, configurar regras, executar e revisar; `admin` para membros, auditoria e exclusão de arquivos;
  `owner` para conceder/alterar o papel de proprietário.

## Erros

Formato único:

```json
{"error": {"code": "structure_review_required", "message": "…", "details": {…}, "request_id": "…"}}
```

| HTTP | Códigos comuns |
|---|---|
| 401 | `unauthorized`, `invalid_credentials`, `too_many_attempts` |
| 403 | `forbidden`, `csrf_failed` |
| 404 | `not_found` (também para recursos de outra organização) |
| 409 | `conflict`, `structure_review_required` (detalhes: diferenças estruturais) |
| 413 | `payload_too_large` |
| 422 | `validation_failed` (detalhes por campo, sem ecoar valores), `file_rejected`, `empty_file`, `content_mismatch`, `corrupted_file`, `macro_rejected`, `decompression_limit`, `unsupported_extension`, `unsupported_format` |
| 429 | `limit_exceeded` (cota do plano; detalhes com métrica/uso/limite), `concurrency_limit` |
| 500 | `internal_error` (mensagem genérica + `request_id`) |

## Convenções

- Paginação: `limit` (1–200, padrão 50) e `offset`; respostas com `items` e `total`.
- `X-Request-ID`: aceito na requisição e devolvido em toda resposta; aparece nos logs.
- `Idempotency-Key` em `POST /jobs` e `POST /comparisons`: repetir a chave devolve a execução existente.
- `rule_ids` em `POST /jobs`: omitido = regras ativas no escopo da empresa/perfil; `[]` = apenas regras derivadas
  do mapeamento (obrigatórios e tipos).
- Datas em ISO 8601 (UTC). Valores monetários nas regras/evidências como string decimal.

## Endpoints

### Autenticação

| Método | Caminho | Descrição |
|---|---|---|
| POST | `/api/v1/auth/signup` | Criar organização e usuário proprietário |
| POST | `/api/v1/auth/login` | Autenticar |
| POST | `/api/v1/auth/logout` | Encerrar sessão |
| POST | `/api/v1/auth/switch-organization` | Trocar organização ativa |

### Organização

| Método | Caminho | Descrição |
|---|---|---|
| GET | `/api/v1/me` | Usuário autenticado |
| POST | `/api/v1/me/password` | Alterar a própria senha |
| GET | `/api/v1/organizations/current` | Organização corrente |
| PATCH | `/api/v1/organizations/current` | Atualizar organização |
| GET | `/api/v1/organizations/current/usage` | Plano, limites e consumo do mês |
| GET | `/api/v1/organizations/current/members` | Listar membros |
| POST | `/api/v1/organizations/current/members` | Adicionar membro |
| PATCH | `/api/v1/organizations/current/members/{membership_id}` | Alterar papel ou status |
| POST | `/api/v1/organizations/current/members/{membership_id}/reset-password` | Gerar senha temporária para um membro |

### Empresas atendidas

| Método | Caminho | Descrição |
|---|---|---|
| GET | `/api/v1/clients` | Listar empresas atendidas |
| POST | `/api/v1/clients` | Cadastrar empresa atendida |
| GET | `/api/v1/clients/{client_id}` | Consultar empresa atendida |
| PATCH | `/api/v1/clients/{client_id}` | Editar ou desativar empresa atendida |

### Arquivos

| Método | Caminho | Descrição |
|---|---|---|
| POST | `/api/v1/files` | Enviar arquivo CSV/XLSX |
| GET | `/api/v1/files` | Listar arquivos |
| GET | `/api/v1/files/{file_id}` | Consultar arquivo e inspeção estrutural |
| DELETE | `/api/v1/files/{file_id}` | Excluir conteúdo do arquivo (mantém histórico) |
| GET | `/api/v1/files/{file_id}/profile` | Inspecionar estrutura com outras opções (sem salvar) |
| POST | `/api/v1/files/{file_id}/structure` | Confirmar aba, cabeçalho e delimitador |
| POST | `/api/v1/files/{file_id}/mapping` | Sugerir mapeamento e perfis compatíveis |
| GET | `/api/v1/files/{file_id}/download` | Baixar arquivo original (autorizado) |

### Perfis

| Método | Caminho | Descrição |
|---|---|---|
| GET | `/api/v1/profiles` | Listar perfis |
| POST | `/api/v1/profiles` | Criar perfil a partir de um arquivo e mapeamento |
| GET | `/api/v1/profiles/{profile_id}` | Consultar perfil e versões |
| PATCH | `/api/v1/profiles/{profile_id}` | Renomear ou arquivar perfil |
| POST | `/api/v1/profiles/{profile_id}/versions` | Criar nova versão do perfil |
| POST | `/api/v1/profiles/{profile_id}/versions/{version_id}/approve` | Aprovar versão em rascunho |
| GET | `/api/v1/profiles/{profile_id}/compatibility` | Verificar compatibilidade de um arquivo com a versão atual |

### Regras de validação

| Método | Caminho | Descrição |
|---|---|---|
| GET | `/api/v1/validation-rules/catalog` | Catálogo de tipos de regra e campos canônicos |
| POST | `/api/v1/validation-rules/check` | Validar parâmetros de uma regra sem salvar |
| GET | `/api/v1/validation-rules` | Listar regras (versões atuais) |
| POST | `/api/v1/validation-rules` | Criar regra |
| GET | `/api/v1/validation-rules/{rule_id}` | Consultar regra e histórico de versões |
| PATCH | `/api/v1/validation-rules/{rule_id}` | Alterar regra (cria nova versão) |
| POST | `/api/v1/validation-rules/{rule_id}/clone` | Duplicar regra (ex.: global) para a organização |

### Execuções

| Método | Caminho | Descrição |
|---|---|---|
| POST | `/api/v1/jobs` | Executar validação de um arquivo com um perfil |
| GET | `/api/v1/jobs` | Histórico de execuções |
| GET | `/api/v1/jobs/{job_id}` | Consultar execução |
| GET | `/api/v1/jobs/{job_id}/findings` | Inconsistências da execução (com filtros) |
| PATCH | `/api/v1/jobs/{job_id}/findings/{finding_id}` | Registrar revisão de uma inconsistência |
| GET | `/api/v1/jobs/{job_id}/findings/export.csv` | Exportar inconsistências em CSV |
| GET | `/api/v1/jobs/{job_id}/report` | Relatório da execução com evidências de reprodutibilidade |
| POST | `/api/v1/jobs/{job_id}/reprocess` | Reprocessar com o mesmo arquivo e perfil |
| POST | `/api/v1/jobs/{job_id}/cancel` | Cancelar execução enfileirada |

### Comparações

| Método | Caminho | Descrição |
|---|---|---|
| POST | `/api/v1/comparisons/suggest` | Sugerir chave e campos a comparar |
| POST | `/api/v1/comparisons` | Comparar dois arquivos |
| GET | `/api/v1/comparisons` | Listar comparações |
| GET | `/api/v1/comparisons/{comparison_id}` | Consultar comparação |
| GET | `/api/v1/comparisons/{comparison_id}/results` | Divergências e classificações |
| GET | `/api/v1/comparisons/{comparison_id}/export.csv` | Exportar relatório de divergências em CSV |

### Painel e auditoria

| Método | Caminho | Descrição |
|---|---|---|
| GET | `/api/v1/dashboard` | Indicadores da organização |
| GET | `/api/v1/audit-events` | Trilha de auditoria (administradores) |

### Saúde

| Método | Caminho | Descrição |
|---|---|---|
| GET | `/health/live` | Liveness (processo ativo) |
| GET | `/health/ready` | Readiness (banco e armazenamento) |

