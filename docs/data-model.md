# Modelo de dados

Migration inicial: [backend/migrations/versions/0001_initial_schema.py](../backend/migrations/versions/0001_initial_schema.py).
Todos os recursos de clientes carregam `organization_id` e toda consulta da API filtra por ele.

```
Organization 1─* Membership *─1 User
Organization 1─* ClientAccount 1─* FileAsset
Organization 1─* DatasetProfile 1─* DatasetProfileVersion 1─1 MappingProfile
                 DatasetProfile.current_version_id ─► DatasetProfileVersion (FK circular, SET NULL)
Organization 1─* ValidationRule (organization_id NULL = regra global)
FileAsset + DatasetProfileVersion ─► ProcessingJob 1─* ValidationFinding
FileAsset (A, B) ─► ComparisonJob 1─* ComparisonResult
Organization 1─1 Subscription ─► Plan ; Organization 1─* UsageRecord ; Organization 1─* AuditEvent
```

## Entidades

| Tabela | Finalidade | Pontos importantes |
|---|---|---|
| `organizations` | Escritório/BPO assinante | `status` active/suspended; exclusão em cascata de tudo que é da organização |
| `users` | Pessoa autenticada | e-mail único; hash Argon2id; pode pertencer a várias organizações |
| `memberships` | Usuário × organização + papel | `owner/admin/analyst/viewer`; `status` desativa o acesso imediatamente; único por (org, user) |
| `client_accounts` | Empresa atendida | nome único por organização; desativação lógica (`inactive`) |
| `file_assets` | Metadados do arquivo | `content_hash` SHA-256, `storage_key` interno (nunca exposto), `read_options` confirmadas, `inspection` (prévia mascarada), `retention_until`; exclusão **lógica** remove conteúdo e prévia e mantém metadados |
| `dataset_profiles` | Perfil lógico de layout | escopo por empresa ou organização (`client_account_id` nulo); `current_version_id` |
| `dataset_profile_versions` | Estrutura esperada (imutável) | colunas + tipos, aba, cabeçalho, delimitador, `structure_signature`, `approval_status` draft/approved/superseded, arquivo de referência |
| `mapping_profiles` | Mapeamento da versão | `entries` (coluna, destino, status, confiança, transformações, obrigatório, formato numérico/data), origem das sugestões, aprovador |
| `validation_rules` | Versão de regra | `rule_key` estável + `version` (único), `is_current`, tipo, parâmetros validados, severidade, `applies_when`, escopo por empresa/perfil |
| `processing_jobs` | Execução de validação | estado, tentativas, `error_kind`, `rules_snapshot`, `input_snapshot` (hash, opções de leitura, versão e mapeamento do perfil), contagens, `idempotency_key` único por organização |
| `validation_findings` | Inconsistência | regra/versão, linha, chave do registro, campo, valor observado **mascarado/truncado**, mensagem, evidência, revisão |
| `comparison_jobs` | Comparação | arquivos A/B, configuração (chaves, campos, tolerâncias, normalização), resumo por categoria |
| `comparison_results` | Item divergente/ambíguo | categoria, chave, linhas A/B, diferenças; correspondências exatas são apenas contadas |
| `audit_events` | Trilha de auditoria | ação, entidade, ator, detalhes sem conteúdo de arquivo, `request_id` |
| `plans` / `subscriptions` / `usage_records` | Monetização | limites mensais por plano, política de excedente, consumo por métrica e período `AAAA-MM` |

## Índices relevantes

- `file_assets (organization_id, client_account_id, created_at)` e `(organization_id, content_hash)` — listagens e duplicidade.
- `processing_jobs (organization_id, created_at)`, `(status)` — histórico e fila.
- `validation_findings (job_id, severity)`, `(job_id, rule_key)`, `(job_id, field)` — filtros de resultados.
- `comparison_results (comparison_id, category)`.
- `validation_rules (organization_id, is_current)`; único `(rule_key, version)`.
- `usage_records (organization_id, metric, period)` — verificação de cotas.
- `audit_events (organization_id, created_at)`.

## Estratégias de exclusão

| Objeto | Estratégia |
|---|---|
| Organização | `ON DELETE CASCADE` em todas as tabelas da organização (operação administrativa, sem endpoint público) |
| Arquivo | Exclusão lógica: conteúdo e prévia removidos, metadados e hash mantidos; jobs referenciam com `RESTRICT` |
| Empresa atendida | Desativação; arquivos e histórico preservados |
| Perfil | Arquivamento; versões nunca são apagadas (jobs referenciam com `RESTRICT`) |
| Regra | Novas versões; versões antigas permanecem (`is_current = false`) |
| Usuário | Desativação da participação; `SET NULL` nas referências de autoria |
