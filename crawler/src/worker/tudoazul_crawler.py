"""Crawler de disponibilidade em pontos do TudoAzul."""

import asyncio
import json
import logging
import re
import time
from datetime import datetime
from typing import Optional, Tuple
from urllib.parse import urlencode

from camoufox.sync_api import Camoufox


logger = logging.getLogger(__name__)


class TodoAzulCrawlerError(RuntimeError):
    """A busca Azul não devolveu uma resposta de disponibilidade utilizável."""


def build_url(origem: str, destino: str, data: str, adultos: int) -> str:
    departure_date = datetime.strptime(data, "%Y-%m-%d").strftime("%m/%d/%Y")
    params = {
        "c[0].ds": origem,
        "c[0].std": departure_date,
        "c[0].as": destino,
        "p[0].t": "ADT",
        "p[0].c": adultos,
        "p[0].cp": "false",
        "f.dl": 3,
        "f.dr": 3,
        "cc": "PTS",
    }
    return (
        "https://www.voeazul.com.br/br/pt/home/selecao-voo?"
        f"{urlencode(params)}&{int(time.time() * 1000)}"
    )


def _first_value(*values, default=None):
    return next((value for value in values if value is not None), default)


def _airport(value) -> str:
    if isinstance(value, dict):
        return _first_value(value.get("code"), value.get("airportCode"), value.get("iata"), default="")
    return value or ""


def _duration_minutes(value) -> int:
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        match = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?", value)
        if match:
            return int(match.group(1) or 0) * 60 + int(match.group(2) or 0)
    return 0


def _as_int(value) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return 0


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


def parse_tudoazul_flights(data: dict) -> list:
    """Normaliza jornadas retornadas pela busca TudoAzul em pontos."""
    results = []
    seen = set()

    for parent, journeys in _journey_groups(data):
        for journey in journeys:
            if not isinstance(journey, dict):
                continue

            segments = journey.get("segments") or journey.get("segmentList") or []
            if not segments:
                continue
            first_segment, last_segment = segments[0], segments[-1]
            if not isinstance(first_segment, dict) or not isinstance(last_segment, dict):
                continue
            flight = first_segment.get("flight", {}) if isinstance(first_segment, dict) else {}
            last_flight = last_segment.get("flight", {}) if isinstance(last_segment, dict) else {}

            departure = _first_value(journey.get("departure"), first_segment.get("departure"))
            arrival = _first_value(journey.get("arrival"), last_segment.get("arrival"))
            origin = _airport(_first_value(journey.get("origin"), first_segment.get("origin")))
            destination = _airport(_first_value(journey.get("destination"), last_segment.get("destination")))
            carrier = _first_value(flight.get("carrierCode"), flight.get("carrier"), default="AD")
            flight_numbers = [
                str(segment.get("flight", {}).get("flightNumber", ""))
                for segment in segments
                if isinstance(segment, dict) and segment.get("flight", {}).get("flightNumber") is not None
            ]
            flight_number = "/".join(filter(None, flight_numbers))
            fare = _first_value(journey.get("cheapestFare"), journey.get("fare"), default={})
            total = fare.get("total", {}) if isinstance(fare, dict) else {}
            points = _first_value(
                total.get("points") if isinstance(total, dict) else None,
                fare.get("points") if isinstance(fare, dict) else None,
                journey.get("lowestPoints"),
                parent.get("lowestPoints"),
                default=0,
            )
            money = _first_value(
                total.get("amount") if isinstance(total, dict) else None,
                fare.get("amount") if isinstance(fare, dict) else None,
                default=0,
            )
            stops = _as_int(_first_value(journey.get("stopsCount"), journey.get("stops"), default=len(segments) - 1))
            duration = _duration_minutes(_first_value(journey.get("duration"), first_segment.get("duration")))
            key = (origin, destination, departure, arrival, carrier, flight_number)
            if not origin or not destination or key in seen:
                continue
            seen.add(key)

            results.append({
                "voo": f"{carrier}-{flight_number}",
                "companhia": _first_value(flight.get("operatedBy"), last_flight.get("operatedBy"), default="Azul"),
                "carrier_code": carrier,
                "flight_number": flight_number,
                "origem": origin,
                "destino": destination,
                "partida": departure,
                "chegada": arrival,
                "duracao_minutos": duration,
                "escalas": stops,
                "assentos": _as_int(_first_value(journey.get("availableSeats"), journey.get("seatsAvailable"), default=0)),
                "cabin": _first_value(fare.get("cabin") if isinstance(fare, dict) else None, journey.get("cabin"), default="ECONOMIC"),
                "miles_price": _as_int(points),
                "money_brl": money,
            })
    return results


def _run_blocking_crawl(origem: str, destino: str, data: str, adultos: int):
    url = build_url(origem, destino, data, adultos)
    captured = []
    response_count = 0
    json_count = 0
    json_without_journeys = []
    relevant_responses = []
    page_title = ""
    page_text = ""

    logger.info("Azul: iniciando busca em %s", url)

    with Camoufox(headless=True, geoip=True, humanize=True, locale="pt-BR") as browser:
        page = browser.new_page()

        def handle_response(response):
            nonlocal response_count, json_count
            response_count += 1
            try:
                body = response.text()
                payload = json.loads(body)
                json_count += 1
                journey_group_count = sum(1 for _ in _journey_groups(payload))
                response_url = response.url
                if any(token in response_url.lower() for token in ("flight", "search", "availability", "booking", "offer")):
                    relevant_responses.append(response_url)
                if journey_group_count:
                    captured.append(payload)
                    logger.info(
                        "Azul: resposta com jornadas capturada url=%s grupos=%s",
                        response_url,
                        journey_group_count,
                    )
                elif len(json_without_journeys) < 5:
                    keys = list(payload)[:20] if isinstance(payload, dict) else [type(payload).__name__]
                    json_without_journeys.append((response_url, keys))
            except (json.JSONDecodeError, UnicodeDecodeError):
                return
            except Exception as error:
                logger.debug("Azul: não foi possível ler resposta %s: %s", response.url, error)

        page.on("response", handle_response)
        try:
            page.goto(url, wait_until="networkidle", timeout=120000)
            page.wait_for_timeout(15000)
        finally:
            try:
                page_title = page.title()
                page_text = page.locator("body").inner_text()[:1500]
            except Exception as error:
                logger.debug("Azul: não foi possível ler a página final: %s", error)

    logger.info(
        "Azul: busca finalizada respostas=%s json=%s capturas=%s",
        response_count,
        json_count,
        len(captured),
    )
    if relevant_responses:
        logger.info("Azul: URLs relevantes observadas: %s", relevant_responses[:10])
    if json_without_journeys:
        logger.info("Azul: JSON sem jornadas: %s", json_without_journeys)

    if not captured:
        logger.warning(
            "Azul: nenhuma jornada encontrada. title=%r pagina=%r",
            page_title,
            page_text,
        )
        raise TodoAzulCrawlerError(
            f"Nenhuma resposta de disponibilidade Azul encontrada (json={json_count}, respostas={response_count})"
        )

    api_data = max(captured, key=lambda payload: len(parse_tudoazul_flights(payload)))
    flights = parse_tudoazul_flights(api_data)
    logger.info("Azul: jornadas normalizadas=%s", len(flights))
    if not flights:
        raise TodoAzulCrawlerError("A resposta Azul tinha jornadas, mas nenhuma pôde ser normalizada")
    for flight in flights:
        flight["crawler_url"] = url
    return api_data, flights


async def crawl_tudoazul(origem: str, destino: str, data: str, adultos: int = 1) -> Tuple[Optional[dict], list]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _run_blocking_crawl, origem, destino, data, adultos)
