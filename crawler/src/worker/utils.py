"""Utilitários para normalizar os voos retornados pela API da Smiles."""

from __future__ import annotations

import logging
from datetime import date, datetime

logger = logging.getLogger(__name__)

# Valores aceitos pelo enum FlightClass da API.
_CLASS_BY_CABIN = {
    "ECONOMIC": "Economy",
    "ECONOMY": "Economy",
    "PREMIUM_ECONOMY": "PremiumEconomy",
    "BUSINESS": "Business",
    "FIRST": "First",
}


def _flight_number(flight: dict) -> str:
    """Obtém o número comercial estável, sem usar o uid efêmero da busca."""
    sources = [
        flight,
        flight.get("flight", {}),
        flight.get("operatingFlight", {}),
        flight.get("marketingFlight", {}),
    ]
    for field in ("segments", "segmentList", "flightSegments"):
        segments = flight.get(field, [])
        if isinstance(segments, list):
            sources.extend(segments)
    for source in sources:
        if not isinstance(source, dict):
            continue
        for field in ("flightNumber", "flight_number", "number", "flightCode"):
            value = source.get(field)
            if value is not None and str(value).strip():
                return str(value).strip()
    return ""


def parse_flights(data: dict) -> list:
    """Parseia com a estrutura real da API Smiles."""
    results = []
    for segment in data.get("requestedFlightSegmentList", []):
        for flight in segment.get("flightList", []):
            dep = flight.get("departure", {})
            arr = flight.get("arrival", {})
            airl = flight.get("airline", {})
            dur = flight.get("duration", {})
            flight_number = _flight_number(flight)

            # Pega todas as tarifas disponíveis.
            fares = {}
            for fare in flight.get("fareList", []):
                fares[fare.get("type")] = {
                    "milhas": fare.get("miles", 0),
                    "dinheiro": fare.get("money", 0),
                }

            results.append({
                "voo": f"{airl.get('code', '')}-{flight_number}",
                "companhia": airl.get("name", ""),
                "carrier_code": airl.get("code", ""),
                "flight_number": flight_number,
                "origem": dep.get("airport", {}).get("code", ""),
                "destino": arr.get("airport", {}).get("code", ""),
                "partida": dep.get("date", ""),
                "chegada": arr.get("date", ""),
                "duracao": f"{dur.get('hours', 0)}h{dur.get('minutes', 0):02d}",
                "duracao_minutos": dur.get("hours", 0) * 60 + dur.get("minutes", 0),
                "escalas": flight.get("stops", 0),
                "assentos": flight.get("availableSeats", 0),
                "tarifas": fares,
                "cabin": flight.get("cabin", "ECONOMIC"),
                # Atalhos para as tarifas mais comuns.
                "smiles_milhas": fares.get("SMILES", {}).get("milhas"),
                "smiles_club_milhas": fares.get("SMILES_CLUB", {}).get("milhas"),
                "money_brl": fares.get("MONEY", {}).get("dinheiro"),
            })
    return results


def select_best_flight(flights: list) -> dict | None:
    """Retorna o voo com a menor tarifa Smiles ou Smiles Club disponível."""
    priced_flights = [
        flight
        for flight in flights
        if flight.get("smiles_milhas") is not None
        or flight.get("smiles_club_milhas") is not None
    ]
    if not priced_flights:
        return None

    return min(
        priced_flights,
        key=lambda flight: min(
            price
            for price in (
                flight.get("smiles_milhas"),
                flight.get("smiles_club_milhas"),
            )
            if price is not None
        ),
    )


def flight_to_snapshot(flight: dict, travel_date: str, provider: str) -> dict:
    """Converte um voo normalizado no formato esperado pelo repositório."""
    miles_price = flight.get("miles_price")
    if miles_price is None:
        miles_price = flight.get("smiles_milhas")
    if miles_price is None:
        miles_price = flight.get("smiles_club_milhas")
    if miles_price is None:
        miles_price = 0

    if isinstance(travel_date, str):
        travel_date = date.fromisoformat(travel_date[:10])

    raw_cabin = flight.get("cabin") or "ECONOMIC"
    cabin = _CLASS_BY_CABIN.get(str(raw_cabin).upper())
    if cabin is None:
        # A API só aceita estas quatro classes; um valor desconhecido no banco quebra a busca.
        logger.warning("Cabine desconhecida %r; gravando como Economy", raw_cabin)
        cabin = "Economy"

    def to_time(value):
        if not value:
            return None
        try:
            return datetime.fromisoformat(
                value.replace("Z", "+00:00")
            ).time().replace(tzinfo=None)
        except (AttributeError, ValueError):
            return None

    return {
        "origin": flight.get("origem"),
        "destination": flight.get("destino"),
        "travel_date": travel_date,
        "class": cabin,
        "direct_only": flight.get("escalas", 0) == 0,
        "provider": provider,
        "fare_option_id": flight.get("fare_option_id", 1),
        "miles_price": miles_price,
        "taxes_cents": flight.get("taxes_cents", 0),
        "currency": "BRL",
        "seats_available": flight.get("assentos", 0),
        "crawler_url": flight.get("crawler_url"),
        "flight_duration_minutes": flight.get("duracao_minutos", 0),
        "number_of_stops": flight.get("escalas", 0),
        "departure_time": to_time(flight.get("partida")),
        "arrival_time": to_time(flight.get("chegada")),
        "carrier_code": flight.get("carrier_code", ""),
        "flight_number": flight.get("flight_number", ""),
    }


def summarize_price_history(snapshots: list[dict]) -> list[dict]:
    """Uma linha de histórico por rota/data/programa/cabine: o menor preço da coleta.

    Recebe os snapshots já normalizados (flight_to_snapshot). Preço zero ou ausente
    significa que a tarifa não veio e fica de fora do mínimo.
    """
    groups: dict[tuple, list[dict]] = {}
    for s in snapshots:
        key = (
            str(s.get("origin") or "").upper(),
            str(s.get("destination") or "").upper(),
            s.get("travel_date"),
            s.get("provider"),
            s.get("class"),
        )
        groups.setdefault(key, []).append(s)

    rows = []
    for (origin, destination, travel_date, provider, cabin), items in groups.items():
        priced = [s for s in items if (s.get("miles_price") or 0) > 0]
        if not priced:
            continue
        cheapest = min(priced, key=lambda s: (s["miles_price"], s.get("taxes_cents") or 0))
        direct = [s["miles_price"] for s in priced if s.get("direct_only")]
        rows.append({
            "origin": origin,
            "destination": destination,
            "travel_date": travel_date,
            "provider": provider,
            "class": cabin,
            "min_miles_price": cheapest["miles_price"],
            "taxes_cents": cheapest.get("taxes_cents") or 0,
            "currency": cheapest.get("currency") or "BRL",
            "min_miles_price_direct": min(direct) if direct else None,
            "flights_found": len(items),
        })
    return rows
