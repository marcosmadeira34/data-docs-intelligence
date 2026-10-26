"""Abstração de provedores de IA para sugestões de mapeamento.

Princípios:
- O produto funciona sem IA (provedor heurístico determinístico).
- A IA recebe apenas metadados de colunas (nome, tipo inferido, % de vazios);
  amostras de valores só são enviadas se ``DDI_AI_SEND_SAMPLE_VALUES=true``, e mascaradas.
- Toda resposta é validada contra o catálogo de campos; destinos desconhecidos são descartados.
- Nenhuma sugestão da IA é aprovada automaticamente.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from app.core.config import Settings, get_settings
from app.domain.mapping.suggest import MappingSuggestion, suggest_mappings

log = logging.getLogger(__name__)


class MappingSuggester(Protocol):
    name: str

    def suggest(self, columns: list[dict[str, Any]], threshold: float) -> list[MappingSuggestion]: ...


class HeuristicSuggester:
    name = "heuristic"

    def suggest(self, columns: list[dict[str, Any]], threshold: float) -> list[MappingSuggestion]:
        return suggest_mappings(columns, threshold=threshold)


class AssistedSuggester:
    """Heurística primeiro; a IA complementa apenas colunas sem sugestão confiável."""

    name = "ai"

    def __init__(self, provider: Any, settings: Settings):
        self.provider = provider
        self.settings = settings

    def suggest(self, columns: list[dict[str, Any]], threshold: float) -> list[MappingSuggestion]:
        base = suggest_mappings(columns, threshold=threshold)
        pending = [c for c, s in zip(columns, base, strict=True) if s.target_field is None or s.requires_confirmation]
        if not pending:
            return base
        try:
            ai = {s.source_column: s for s in self.provider.suggest(pending, self.settings)}
        except Exception as exc:  # falha do provedor externo nunca bloqueia o fluxo
            log.warning("ai.suggest_failed", extra={"error_type": type(exc).__name__})
            for s in base:
                if s.target_field is None:
                    s.warnings.append("sugestão por IA indisponível no momento")
            return base
        taken = {s.target_field for s in base if s.target_field and not s.requires_confirmation}
        out = []
        for s in base:
            a = ai.get(s.source_column)
            if a and a.target_field and a.target_field not in taken and (s.target_field is None or a.confidence > s.confidence):
                a.requires_confirmation = True  # sugestões da IA sempre exigem confirmação humana
                taken.add(a.target_field)
                out.append(a)
            else:
                out.append(s)
        return out


def get_suggester() -> MappingSuggester:
    s = get_settings()
    if s.ai_provider == "anthropic" and s.anthropic_api_key:
        from app.infrastructure.ai.anthropic_provider import AnthropicMappingProvider

        return AssistedSuggester(AnthropicMappingProvider(s), s)
    return HeuristicSuggester()
