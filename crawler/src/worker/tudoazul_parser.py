"""Normalização da resposta de disponibilidade em pontos do TudoAzul (API v6).

Endpoint observado no navegador:
    https://b2c-api.voeazul.com.br/tudoAzulReservationAvailability/api/tudoazul/reservation/availability/v6/availability

Formato: data.trips[].journeys[], cada jornada com `identifier` (rota, horários,
duração, conexões), `segments[]` (voos e assentos por perna) e `fares[]` (uma por
cabine). Em cada tarifa, `paxPoints[]` traz os níveis de pagamento: o
`amountLevel` 1 é só pontos (+ taxas); os níveis seguintes são pontos + dinheiro.

Este módulo não depende do navegador: é usado tanto pelo crawler Camoufox quanto
pela ponte com a extensão Chrome.
"""

from __future__ import annotations

from datetime import datetime
from urllib.parse import urlencode

SEARCH_PAGE_URL = "https://www.voeazul.com.br/br/pt/home/selecao-voo"
AVAILABILITY_URL_FRAGMENT = "/tudoazul/reservation/availability/"



def build_url(origem: str, destino: str, data: str, adultos: int = 1) -> str:
    """URL da página de seleção de voo em pontos, no mesmo formato do site.

    Ex.: ...selecao-voo?c[0].ds=GIG&c[0].std=12/26/2026&c[0].as=MAD&p[0].t=ADT&p[0].c=1&p[0].cp=false&f.dl=3&f.dr=3&cc=PTS
    """
    departure_date = datetime.strptime(data, "%Y-%m-%d").strftime("%m/%d/%Y")
    params = {
        "c[0].ds": origem.upper(),
        "c[0].std": departure_date,
        "c[0].as": destino.upper(),
        "p[0].t": "ADT",
        "p[0].c": adultos,
        "p[0].cp": "false",
        "f.dl": 3,
        "f.dr": 3,
        "cc": "PTS",
    }
    return f"{SEARCH_PAGE_URL}?{urlencode(params, safe='[]/')}"


_CABIN_BY_CATEGORY = {
    "economy": "ECONOMIC",
    "premiumeconomy": "PREMIUM_ECONOMY",
    "business": "BUSINESS",
    "first": "FIRST",
}


def _journey_groups(value):
    """Encontra listas de jornadas na resposta, mesmo quando envelopada pela API."""
    if isinstance(value, dict):
        journeys = value.get("journeys")
        if isinstance(journeys, list) and journeys:
            yield value, journeys
        for child in value.values():
            yield from _journey_groups(child)
    elif isinstance(value, list):
        for child in value:
            yield from _journey_groups(child)


def _as_int(value, default: int = 0) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return default


def _duration_minutes(duration) -> int:
    if not isinstance(duration, dict):
        return 0
    return (
        _as_int(duration.get("days")) * 1440
        + _as_int(duration.get("hours")) * 60
        + _as_int(duration.get("minutes"))
    )


def _cabin(fare: dict) -> str:
    category = (fare.get("productClass") or {}).get("category") or ""
    key = category.replace(" ", "").replace("_", "").lower()
    return _CABIN_BY_CATEGORY.get(key, category.upper() or "ECONOMIC")


def _adult_level(pax_points: dict) -> dict | None:
    levels = pax_points.get("levels") or []
    return next((lv for lv in levels if lv.get("paxType") == "ADT"), levels[0] if levels else None)


def _points(level: dict) -> int:
    points = level.get("points") or {}
    return _as_int(points.get("discountedAmount") or points.get("amount"))


def _min_remaining_seats(segments: list) -> int:
    seats = [
        leg.get("legInfo", {}).get("remainingSeats")
        for segment in segments
        for leg in (segment.get("legs") or [])
        if isinstance(leg.get("legInfo"), dict)
    ]
    seats = [s for s in seats if isinstance(s, (int, float))]
    return int(min(seats)) if seats else 0


def parse_tudoazul_flights(data: dict) -> list:
    """Uma entrada por (jornada, cabine) com tarifa disponível."""
    results = []
    seen = set()

    for _parent, journeys in _journey_groups(data):
        for journey in journeys:
            if not isinstance(journey, dict):
                continue
            if not (journey.get("status") or {}).get("available", True):
                continue
            ident = journey.get("identifier") or {}
            origin = ident.get("departureStation")
            destination = ident.get("arrivalStation")
            if not origin or not destination:
                continue

            segments = [s for s in (journey.get("segments") or []) if isinstance(s, dict)]
            seg_idents = [s.get("identifier") or {} for s in segments]
            flight_number = "/".join(
                str(si["flightNumber"]) for si in seg_idents if si.get("flightNumber")
            ) or str(ident.get("flightNumber") or "")
            carrier = ident.get("carrierCode") or "AD"
            connections = ident.get("connections") or {}
            stops = _as_int(connections.get("count"), default=max(len(segments) - 1, 0))

            for fare in journey.get("fares") or []:
                if not isinstance(fare, dict) or not fare.get("available", True):
                    continue
                pax_points = sorted(
                    (p for p in (fare.get("paxPoints") or []) if isinstance(p, dict)),
                    key=lambda p: _as_int(p.get("amountLevel"), default=99),
                )
                if not pax_points:
                    continue
                base = _adult_level(pax_points[0])
                if not base:
                    continue
                miles_price = _points(base)
                if miles_price <= 0:
                    continue

                cabin = _cabin(fare)
                key = (origin, destination, ident.get("std"), ident.get("sta"), carrier, flight_number, cabin)
                if key in seen:
                    continue
                seen.add(key)

                combos = []
                for p in pax_points[1:]:
                    lv = _adult_level(p)
                    if lv:
                        combos.append({
                            "nivel": _as_int(p.get("amountLevel")),
                            "pontos": _points(lv),
                            "dinheiro_brl": lv.get("totalMoney"),
                        })

                results.append({
                    "voo": f"{carrier}-{flight_number}",
                    "companhia": "Azul",
                    "operado_por": ident.get("operatedBy"),
                    "carrier_code": carrier,
                    "flight_number": flight_number,
                    "origem": origin,
                    "destino": destination,
                    "partida": ident.get("std"),
                    "chegada": ident.get("sta"),
                    "duracao_minutos": _duration_minutes(ident.get("duration")),
                    "escalas": stops,
                    "conexoes": [c.get("code") for c in (connections.get("stationsInformation") or [])],
                    # remainingSeats é a sobra do avião por perna, não assentos de resgate.
                    "assentos": _min_remaining_seats(segments),
                    "cabin": cabin,
                    "classe_tarifaria": fare.get("classOfService"),
                    "miles_price": miles_price,
                    # Nível 1: só pontos; totalMoney = taxas de embarque + taxa de conveniência.
                    "taxes_cents": _as_int(_as_float(base.get("totalMoney")) * 100),
                    "money_brl": base.get("totalMoney"),
                    "pontos_mais_dinheiro": combos,
                })
    return results


def _as_float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
