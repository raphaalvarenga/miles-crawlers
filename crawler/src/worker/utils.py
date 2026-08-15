"""Utilitários para normalizar os voos retornados pela API da Smiles."""

from datetime import date, datetime


def parse_flights(data: dict) -> list:
    """Parseia com a estrutura real da API Smiles."""
    results = []
    for segment in data.get("requestedFlightSegmentList", []):
        for flight in segment.get("flightList", []):
            dep = flight.get("departure", {})
            arr = flight.get("arrival", {})
            airl = flight.get("airline", {})
            dur = flight.get("duration", {})

            # Pega todas as tarifas disponíveis.
            fares = {}
            for fare in flight.get("fareList", []):
                fares[fare.get("type")] = {
                    "milhas": fare.get("miles", 0),
                    "dinheiro": fare.get("money", 0),
                }

            results.append({
                "voo": f"{airl.get('code', '')}-{flight.get('uid', '')}",
                "companhia": airl.get("name", ""),
                "carrier_code": airl.get("code", ""),
                "flight_number": flight.get("uid", ""),
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
    miles_price = flight.get("smiles_milhas")
    if miles_price is None:
        miles_price = flight.get("smiles_club_milhas")

    if isinstance(travel_date, str):
        travel_date = date.fromisoformat(travel_date[:10])

    cabin = flight.get("cabin", "ECONOMIC")
    cabin = {
        "ECONOMIC": "Economy",
        "BUSINESS": "Business",
        "FIRST": "First",
    }.get(cabin, cabin.title())

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
        "taxes_cents": 0,
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
