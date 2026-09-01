import json
import asyncio
import logging
from camoufox.sync_api import Camoufox
from typing import Tuple, Optional
from worker.utils import parse_flights


logger = logging.getLogger(__name__)


class SmilesCrawlerError(RuntimeError):
    """A busca Smiles não devolveu uma resposta de disponibilidade utilizável."""

def build_url(origem, destino, data, adultos):
    from datetime import datetime

    dt = datetime.strptime(data, "%Y-%m-%d")
    ts = int(dt.timestamp()) * 1000

    return (
        f"https://www.smiles.com.br/mfe/emissao-passagem"
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

def _run_blocking_crawl(origem, destino, data, adultos):
    url = build_url(origem, destino, data, adultos)

    captured = []
    api_found = False
    response_count = 0
    matching_urls = []
    page_title = ""
    page_text = ""

    logger.info("Smiles: iniciando busca em %s", url)

    with Camoufox(
        headless=True,
        geoip=False,
        humanize=True,
        locale="pt-BR",
    ) as browser:

        page = browser.new_page()

        def handle_response(response):
            nonlocal api_found, response_count
            response_count += 1
            try:
                if (
                    response.url and
                    "flightsearch" in response.url
                    and "/search" in response.url
                ):
                    body = response.text()
                    payload = json.loads(body)
                    captured.append(payload)
                    matching_urls.append(response.url)
                    api_found = True
                    logger.info("Smiles: resposta de disponibilidade capturada url=%s", response.url)
            except (json.JSONDecodeError, UnicodeDecodeError) as error:
                logger.warning("Smiles: resposta inválida em %s: %s", response.url, error)
            except Exception as error:
                logger.debug("Smiles: não foi possível processar resposta %s: %s", response.url, error)

        page.on("response", handle_response)
        try:
            page.goto(url, wait_until="networkidle", timeout=120000)
            for _ in range(120):
                if api_found:
                    break
                page.wait_for_timeout(500)
        finally:
            try:
                page_title = page.title()
                page_text = page.locator("body").inner_text()[:1500]
            except Exception as error:
                logger.debug("Smiles: não foi possível ler a página final: %s", error)

    logger.info(
        "Smiles: busca finalizada respostas=%s capturas=%s",
        response_count,
        len(captured),
    )
    if matching_urls:
        logger.info("Smiles: URLs de disponibilidade observadas: %s", matching_urls[:10])

    if not captured:
        logger.warning("Smiles: nenhuma resposta encontrada. title=%r pagina=%r", page_title, page_text)
        raise SmilesCrawlerError(
            f"Nenhuma resposta de disponibilidade Smiles encontrada (respostas={response_count})"
        )

    api_data = max(
        captured,
        key=lambda x: len(
            x.get("requestedFlightSegmentList", [{}])[0]
             .get("flightList", [])
        ) if x.get("requestedFlightSegmentList") else 0
    )

    flights = parse_flights(api_data)
    logger.info("Smiles: voos normalizados=%s", len(flights))
    if not flights:
        raise SmilesCrawlerError("A resposta Smiles não continha voos normalizáveis")
    for flight in flights:
        flight["crawler_url"] = url
    return api_data, flights

async def crawl_smiles(origem: str, destino: str, data: str, adultos: int = 1) -> Tuple[Optional[dict], list]:
    # Run blocking Camoufox in thread
    loop = asyncio.get_running_loop()
    api_data, flights = await loop.run_in_executor(None, _run_blocking_crawl, origem, destino, data, adultos)
    return api_data, flights
