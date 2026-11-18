"""Busca da Smiles pela extensão Chrome: URL da página, resposta a capturar e parse.

A página https://www.smiles.com.br/mfe/emissao-passagem chama a API
https://api-air-flightsearch-blue.smiles.com.br/v1/airlines/search?... e o JSON
dela é o mesmo que o crawler Camoufox já lia (requestedFlightSegmentList[].flightList[]).

Sem dependência do Camoufox: a ponte da extensão roda sem ele instalado.
"""

from __future__ import annotations

from datetime import datetime

from worker.utils import parse_flights

# Trecho da URL da resposta de disponibilidade (o "?" evita outros caminhos de /search).
AVAILABILITY_URL_FRAGMENT = "/v1/airlines/search?"

SEARCH_PAGE_URL = "https://www.smiles.com.br/mfe/emissao-passagem"


class SmilesRejectedError(RuntimeError):
    """A API respondeu sem voos e com mensagem de erro (ex.: "Something went wrong")."""


def build_url(origem: str, destino: str, data: str, adultos: int = 1) -> str:
    # A página recebe a data como epoch em ms da meia-noite local.
    ts = int(datetime.strptime(data, "%Y-%m-%d").timestamp()) * 1000
    return (
        f"{SEARCH_PAGE_URL}"
        f"?tripType=2&originAirport={origem}"
        f"&destinationAirport={destino}"
        f"&departureDate={ts}"
        f"&adults={adultos}"
        f"&children=0"
        f"&infants=0"
        f"&searchType=g3"
        f"&segments=1"
        f"&cabin=ALL"
    )


def parse_smiles_flights(payload: dict) -> list:
    """Voos da resposta; levanta SmilesRejectedError quando a API recusou a busca.

    Sem isso, uma recusa viraria "0 voos" e o job seria marcado como concluído.
    """
    if not isinstance(payload, dict):
        raise SmilesRejectedError(f"resposta inesperada: {type(payload).__name__}")
    if "requestedFlightSegmentList" not in payload:
        message = payload.get("message") or payload.get("errorMessage") or payload.get("error")
        raise SmilesRejectedError(f"a Smiles recusou a busca: {message or sorted(payload)[:8]}")
    return parse_flights(payload)
