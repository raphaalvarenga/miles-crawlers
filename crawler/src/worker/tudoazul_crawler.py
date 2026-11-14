"""Crawler de disponibilidade em pontos do TudoAzul."""

import asyncio
import json
import logging
from typing import Optional, Tuple

from camoufox.sync_api import Camoufox

try:
    from worker.tudoazul_parser import _journey_groups, build_url, parse_tudoazul_flights  # noqa: F401 (reexportado p/ debug)
except ImportError:  # debug_azul_crawler.py roda direto da pasta worker/
    from tudoazul_parser import _journey_groups, build_url, parse_tudoazul_flights  # noqa: F401


logger = logging.getLogger(__name__)


class TodoAzulCrawlerError(RuntimeError):
    """A busca Azul não devolveu uma resposta de disponibilidade utilizável."""


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
