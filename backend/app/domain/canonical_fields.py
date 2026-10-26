"""Catálogo de campos canônicos para dados financeiros/contábeis.

Os campos canônicos são o "idioma comum" do produto: cada layout de origem é
mapeado para estes campos, e as regras de validação são escritas sobre eles,
o que permite reutilizar regras entre clientes com planilhas diferentes.

Campos personalizados por organização usam o prefixo ``x_`` (ex.: ``x_centro_lucro``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class CanonicalField:
    key: str
    label: str
    data_type: str  # text | decimal | integer | date | tax_id | boolean | code
    synonyms: tuple[str, ...] = field(default_factory=tuple)
    description: str = ""
    sensitive: bool = False


CANONICAL_FIELDS: tuple[CanonicalField, ...] = (
    CanonicalField("document_number", "Número do documento", "code",
                   ("documento", "num documento", "numero documento", "n documento", "nr documento", "doc",
                    "numero do titulo", "titulo", "nosso numero", "num doc", "id documento", "documento numero", "no doc",
                    "no documento", "nr doc")),
    CanonicalField("invoice_number", "Número da nota fiscal", "code",
                   ("nf", "nota fiscal", "numero nf", "num nf", "nfe", "nf e", "numero nota", "nota", "n nf")),
    CanonicalField("external_id", "Identificador externo", "code",
                   ("id", "codigo", "cod", "identificador", "chave", "id lancamento", "codigo lancamento", "id transacao")),
    CanonicalField("issue_date", "Data de emissão", "date",
                   ("emissao", "data emissao", "dt emissao", "data de emissao", "data documento", "data", "data lancamento",
                    "dt lancamento", "data movimento", "dt movimento")),
    CanonicalField("due_date", "Data de vencimento", "date",
                   ("vencimento", "data vencimento", "dt vencimento", "data de vencimento", "venc", "dt venc", "data venc")),
    CanonicalField("payment_date", "Data de pagamento", "date",
                   ("pagamento", "data pagamento", "dt pagamento", "data de pagamento", "data baixa", "dt baixa",
                    "data liquidacao", "data recebimento", "dt recebimento")),
    CanonicalField("competence", "Competência", "text",
                   ("competencia", "mes referencia", "referencia", "periodo", "mes ano", "mes competencia")),
    CanonicalField("amount", "Valor", "decimal",
                   ("valor", "vlr", "valor documento", "valor titulo", "valor original", "vl", "montante", "valor bruto",
                    "valor r", "vlr documento", "valor lancamento", "importe", "vlr titulo")),
    CanonicalField("paid_amount", "Valor pago", "decimal",
                   ("valor pago", "vlr pago", "valor recebido", "vl pago", "valor liquidado", "valor baixa")),
    CanonicalField("discount_amount", "Desconto", "decimal", ("desconto", "vlr desconto", "valor desconto")),
    CanonicalField("interest_amount", "Juros/multa", "decimal", ("juros", "multa", "juros multa", "acrescimos", "valor juros")),
    CanonicalField("net_amount", "Valor líquido", "decimal", ("valor liquido", "vlr liquido", "liquido", "vl liquido")),
    CanonicalField("total_amount", "Valor total", "decimal", ("total", "valor total", "vlr total", "total geral", "total nota")),
    CanonicalField("item_amount", "Valor do item", "decimal", ("valor item", "vlr item", "subtotal item", "valor do item")),
    CanonicalField("quantity", "Quantidade", "decimal", ("quantidade", "qtd", "qtde", "quant")),
    CanonicalField("unit_price", "Preço unitário", "decimal", ("preco unitario", "valor unitario", "vlr unitario", "preco", "vl unit")),
    CanonicalField("counterparty_name", "Nome do fornecedor/cliente", "text",
                   ("fornecedor", "cliente", "razao social", "nome", "favorecido", "sacado", "beneficiario", "nome fornecedor",
                    "nome cliente", "contraparte", "pagador", "emitente", "destinatario"), sensitive=True),
    CanonicalField("counterparty_tax_id", "CPF/CNPJ do fornecedor/cliente", "tax_id",
                   ("cnpj", "cpf", "cpf cnpj", "cnpj cpf", "documento fornecedor", "cnpj fornecedor", "cnpj cliente",
                    "cpf cnpj fornecedor", "inscricao", "cnpj emitente"), sensitive=True),
    CanonicalField("description", "Descrição/histórico", "text",
                   ("descricao", "historico", "observacao", "obs", "complemento", "memo", "detalhe")),
    CanonicalField("account_code", "Conta contábil", "code",
                   ("conta", "conta contabil", "cod conta", "codigo conta", "plano de contas", "conta debito", "conta credito")),
    CanonicalField("cost_center", "Centro de custo", "code", ("centro de custo", "centro custo", "cc", "c custo")),
    CanonicalField("category", "Categoria", "text", ("categoria", "classificacao", "natureza", "tipo despesa", "plano")),
    CanonicalField("status", "Situação", "text", ("status", "situacao", "estado", "posicao")),
    CanonicalField("entry_type", "Tipo (débito/crédito)", "text", ("tipo", "d c", "debito credito", "natureza lancamento", "tipo lancamento")),
    CanonicalField("installment", "Parcela", "text", ("parcela", "parc", "numero parcela", "n parcela")),
    CanonicalField("payment_method", "Forma de pagamento", "text", ("forma pagamento", "meio pagamento", "forma de pagamento", "modalidade")),
    CanonicalField("bank_code", "Banco", "code", ("banco", "cod banco", "codigo banco")),
    CanonicalField("bank_branch", "Agência", "code", ("agencia", "ag")),
    CanonicalField("bank_account", "Conta bancária", "code", ("conta corrente", "conta bancaria", "cc banco", "numero conta"), sensitive=True),
    CanonicalField("currency", "Moeda", "code", ("moeda", "currency")),
)

FIELDS_BY_KEY: dict[str, CanonicalField] = {f.key: f for f in CANONICAL_FIELDS}
CUSTOM_FIELD_RE = re.compile(r"^x_[a-z0-9_]{1,40}$")


def is_valid_target(key: str) -> bool:
    return key in FIELDS_BY_KEY or bool(CUSTOM_FIELD_RE.match(key))


def field_type(key: str) -> str:
    f = FIELDS_BY_KEY.get(key)
    return f.data_type if f else "text"
