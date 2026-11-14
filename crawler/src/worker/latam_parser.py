"""Normalização da busca em milhas da LATAM Pass (BFF air-offers v2).

Endpoint observado no navegador (chamado pela página oferta-voos):
    https://www.latamairlines.com/bff/air-offers/v2/offers/search/redemption?...

Formato: content[] com um item por itinerário. `summary` traz rota, horários
locais, duração (minutos), escalas e `brands[]` (LIGHT, STANDARD, FULL,
PREMIUM BUSINESS...), cada brand com cabine, milhas, taxas em BRL e assentos.
`itinerary[]` traz os voos de cada perna.

A busca com cabin=Economy já devolve as brands de Business, então uma busca
cobre as duas cabines. Guardamos a brand mais barata de cada cabine.
"""

from __future__ import annotations

from datetime import datetime
from urllib.parse import urlencode

SEARCH_PAGE_URL = "https://www.latamairlines.com/br/pt/oferta-voos"
REDEMPTION_URL_FRAGMENT = "/bff/air-offers/v2/offers/search/redemption"

_CABIN_BY_ID = {"Y": "ECONOMIC", "W": "PREMIUM_ECONOMY", "J": "BUSINESS", "F": "FIRST"}
_CABIN_BY_LABEL = {
    "economy": "ECONOMIC",
    "premiumeconomy": "PREMIUM_ECONOMY",
    "business": "BUSINESS",
    "first": "FIRST",
}


def build_url(origem: str, destino: str, data: str, adultos: int = 1) -> str:
    """URL da página de ofertas em milhas, no mesmo formato do site.

    Ex.: ...oferta-voos?origin=MAD&outbound=2026-12-25T00:00:00.000Z&destination=GIG&adt=1&chd=0&inf=0&trip=OW&cabin=Economy&redemption=true&sort=RECOMMENDED
    """
    outbound = datetime.strptime(data, "%Y-%m-%d").strftime("%Y-%m-%dT00:00:00.000Z")
    params = {
        "origin": origem.upper(),
        "outbound": outbound,
        "destination": destino.upper(),
        "adt": adultos,
        "chd": 0,
        "inf": 0,
        "trip": "OW",
        "cabin": "Economy",
        "redemption": "true",
        "sort": "RECOMMENDED",
    }
    return f"{SEARCH_PAGE_URL}?{urlencode(params)}"


def _as_int(value, default: int = 0) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return default


def _as_float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _cabin(brand: dict) -> str:
    cabin = brand.get("cabin") or {}
    by_id = _CABIN_BY_ID.get(str(cabin.get("id") or "").upper())
    if by_id:
        return by_id
    label = str(cabin.get("label") or "").replace(" ", "").replace("_", "").lower()
    return _CABIN_BY_LABEL.get(label, label.upper() or "ECONOMIC")


def _miles(brand: dict) -> int:
    price = brand.get("price") or {}
    if price.get("currency") not in (None, "LOYALTY_POINTS"):
        return 0
    return _as_int(price.get("amount"))


def parse_latam_flights(data: dict) -> list:
    """Uma entrada por (itinerário, cabine), com a brand mais barata da cabine."""
    results = []
    seen = set()

    for item in data.get("content") or []:
        if not isinstance(item, dict):
            continue
        summary = item.get("summary") or {}
        legs = [leg for leg in (item.get("itinerary") or []) if isinstance(leg, dict)]
        origin = (summary.get("origin") or {}).get("iataCode") or (legs[0].get("origin") if legs else None)
        destination = (summary.get("destination") or {}).get("iataCode") or (legs[-1].get("destination") if legs else None)
        if not origin or not destination:
            continue

        flights = [leg.get("flight") or {} for leg in legs]
        flight_number = "/".join(str(f["flightNumber"]) for f in flights if f.get("flightNumber"))
        carrier = (flights[0].get("airlineCode") if flights else None) or str(summary.get("flightCode") or "LA")[:2]
        if not flight_number:
            flight_number = str(summary.get("flightCode") or "")[2:]
        departure = (summary.get("origin") or {}).get("departure") or (legs[0].get("departure") if legs else None)
        arrival = (summary.get("destination") or {}).get("arrival") or (legs[-1].get("arrival") if legs else None)
        stops = _as_int(summary.get("stopOvers"), default=max(len(legs) - 1, 0))

        by_cabin: dict[str, list] = {}
        for brand in summary.get("brands") or []:
            if not isinstance(brand, dict) or _miles(brand) <= 0:
                continue
            by_cabin.setdefault(_cabin(brand), []).append(brand)

        for cabin, brands in by_cabin.items():
            brands.sort(key=_miles)
            cheapest = brands[0]
            key = (origin, destination, departure, arrival, carrier, flight_number, cabin)
            if key in seen:
                continue
            seen.add(key)

            taxes = _as_float((cheapest.get("taxes") or {}).get("amount"))
            results.append({
                "voo": f"{carrier}-{flight_number}",
                "companhia": "LATAM",
                "operado_por": ", ".join(summary.get("flightOperators") or []) or None,
                "carrier_code": carrier,
                "flight_number": flight_number,
                "origem": origin,
                "destino": destination,
                "partida": departure,
                "chegada": arrival,
                "duracao_minutos": _as_int(summary.get("duration")),
                "escalas": stops,
                "conexoes": [leg.get("destination") for leg in legs[:-1]],
                "assentos": _as_int((cheapest.get("seatsRemaining") or {}).get("count")),
                "cabin": cabin,
                "classe_tarifaria": cheapest.get("farebasis"),
                "brand": cheapest.get("brandText"),
                "miles_price": _miles(cheapest),
                "taxes_cents": _as_int(taxes * 100),
                "money_brl": taxes,
                "tarifas": [
                    {
                        "brand": b.get("brandText"),
                        "milhas": _miles(b),
                        "taxas_brl": _as_float((b.get("taxes") or {}).get("amount")),
                        "assentos": _as_int((b.get("seatsRemaining") or {}).get("count")),
                    }
                    for b in brands
                ],
            })
    return results
