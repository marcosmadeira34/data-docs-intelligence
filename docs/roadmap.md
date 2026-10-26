# Estado do produto e próximos passos

## Implementado (MVP)

- Organizações, usuários, papéis (owner/admin/analyst/viewer), cadastro, login, troca de organização, gestão de membros com senha temporária, troca de senha.
- Empresas atendidas: cadastro, busca, edição, desativação, histórico de arquivos e execuções.
- Upload CSV/TXT/TSV/XLSX com validação do formato real, hash, deduplicação sinalizada, retenção, download auditado, exclusão lógica.
- Inspeção estrutural: codificação, delimitador, abas, mesclas, linhas de título, cabeçalho, tipos, formatos BR/US, vazios, linhas malformadas, prévia mascarada, ambiguidades explícitas; confirmação pelo usuário.
- Mapeamento: sugestões heurísticas (sinônimos, termos, similaridade, compatibilidade de tipo, conflitos), campos personalizados `x_`, transformações autorizadas, obrigatoriedade, aprovação explícita.
- Perfis versionados (estrutura + mapeamento), reaproveitamento por compatibilidade estrutural e bloqueio com pedido de revisão quando o layout muda.
- Motor de regras declarativo com 14 tipos, condições de aplicação, severidades, versionamento, catálogo global somente leitura e duplicação.
- Execuções síncronas/assíncronas com fila no PostgreSQL, retentativas, classificação de falhas, idempotência, cancelamento, reprocessamento, snapshot de evidências.
- Resultados com filtros e facetas, revisão de achados, exportação CSV segura, relatório de evidências.
- Comparação por chave explícita (composta e normalizada), tolerâncias absolutas/percentuais, tratamento de nulos, classificação completa, sugestão de configuração, exportação.
- Planos, cotas mensais aplicadas no backend, registro de consumo, abstração de pagamentos (sem cobrança real).
- Painel com métricas reais, auditoria, logs estruturados, health checks, Docker Compose, dados sintéticos, 152 testes.
- IA opcional (Anthropic) com contrato validado, minimização de dados e fallback heurístico.

## Limitações conhecidas

- Inspeção roda na requisição de upload: arquivos XLSX grandes (dezenas de MB) podem levar dezenas de segundos.
- Comparação mantém em memória as chaves e campos comparados dos dois arquivos (adequado para centenas de milhares de linhas, não para dezenas de milhões).
- Duplicidade/chave única guardam um hash por registro em memória durante a execução.
- Detecção de células mescladas só em XLSX até 5 MB; fórmulas sem valor calculado em cache são lidas como vazias.
- `.xls` (Excel 97-2003), PDF, OCR e XML fiscal não são suportados.
- Bloqueio de força bruta em memória (por processo); verificação de cota não é atômica sob concorrência alta.
- Recuperação de senha por e-mail não existe (administrador gera senha temporária).
- Sem testes automatizados de frontend (validação feita por build, typecheck e roteiro com navegador headless).
- Correspondência aproximada (fuzzy) na comparação não implementada (intencional no MVP).

## Pendências priorizadas e estimativas (1 desenvolvedor sênior)

| Prioridade | Item | Estimativa |
|---|---|---|
| Alta | Inspeção assíncrona para arquivos grandes (job de inspeção + progresso) | 3–4 dias |
| Alta | E-mail transacional (convite, recuperação de senha) e MFA opcional | 4–6 dias |
| Alta | Integração de pagamentos (Stripe/Pagar.me/Iugu) sobre `PaymentProvider`, webhooks e trocas de plano | 6–8 dias |
| Alta | Atendimento a titulares LGPD (busca/eliminação por documento), política de retenção por organização | 4–5 dias |
| Alta | Testes de frontend (Playwright) no CI + pipeline CI/CD com Postgres | 3–4 dias |
| Média | Relatório executivo em PDF/XLSX e envio agendado | 4–5 dias |
| Média | Regras com escopo por perfil na UI, simulação de regra sobre um arquivo antes de salvar | 3 dias |
| Média | Comparação com correspondência aproximada explícita ("prováveis correspondências") | 5–7 dias |
| Média | Comparação em streaming/ordenada externamente para arquivos muito grandes | 5 dias |
| Média | Rate limiting distribuído e cotas atômicas (Redis ou `SELECT … FOR UPDATE` por organização) | 2–3 dias |
| Média | Explicação de inconsistências por IA (texto auxiliar, nunca decisória) | 3 dias |
| Baixa | XML de NF-e/NFS-e, OFX/extratos bancários, integrações com ERPs contábeis | 2–4 semanas por integração |
| Baixa | PDF/OCR de documentos | 3–5 semanas |

Estimativa para uma versão comercial inicial (itens de prioridade alta): **4 a 6 semanas**.
