import json
import time
import asyncio
import logging
from camoufox.sync_api import Camoufox
from typing import Tuple, Optional
from worker.utils import parse_flights


logger = logging.getLogger(__name__)


MAX_ATTEMPTS = 2  # navegadores abertos quando a resposta vem sem voos
RETRY_DELAY_S = 3
EMPTY_GRACE_S = 8  # quanto esperar por outra resposta depois de uma vazia


class SmilesCrawlerError(RuntimeError):
    """A busca Smiles não devolveu uma resposta de disponibilidade utilizável."""


def _flight_count(payload) -> int:
    if not isinstance(payload, dict):
        return 0
    segments = payload.get("requestedFlightSegmentList") or []
    if not segments or not isinstance(segments[0], dict):
        return 0
    return len(segments[0].get("flightList") or [])


def _summary(payload) -> str:
    """Resumo curto de uma resposta para o log (o JSON inteiro é grande)."""
    if not isinstance(payload, dict):
        return repr(payload)[:300]
    keys = ("resultType", "calendarStatus", "hasG3", "hasCongener", "error", "message", "errorMessage")
    info = {k: payload.get(k) for k in keys if k in payload}
    info["segmentos"] = len(payload.get("requestedFlightSegmentList") or [])
    info["chaves"] = sorted(payload)[:12]
    return json.dumps(info, ensure_ascii=False, default=str)

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

def _capture_once(url):
    """Abre um navegador novo, carrega a busca e devolve as respostas de disponibilidade."""
    captured = []
    matching_urls = []
    state = {"api_found": False, "responses": 0}
    page_title = ""
    page_text = ""

    with Camoufox(
        headless=True,
        geoip=False,
        humanize=True,
        locale="pt-BR",
    ) as browser:

        page = browser.new_page()

        def handle_response(response):
            state["responses"] += 1
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
                    state["api_found"] = True
                    logger.info("Smiles: resposta de disponibilidade capturada url=%s", response.url)
            except (json.JSONDecodeError, UnicodeDecodeError) as error:
                logger.warning("Smiles: resposta inválida em %s: %s", response.url, error)
            except Exception as error:
                logger.debug("Smiles: não foi possível processar resposta %s: %s", response.url, error)

        page.on("response", handle_response)
        try:
            page.goto(url, wait_until="networkidle", timeout=120000)
            empty_since = None
            for _ in range(120):
                if any(_flight_count(p) for p in captured):
                    break
                if state["api_found"]:
                    # Resposta sem voos: dá um tempo para a página buscar de novo sozinha.
                    empty_since = empty_since or time.monotonic()
                    if time.monotonic() - empty_since >= EMPTY_GRACE_S:
                        break
                page.wait_for_timeout(500)
        finally:
            try:
                page_title = page.title()
                page_text = page.locator("body").inner_text()[:1500]
            except Exception as error:
                logger.debug("Smiles: não foi possível ler a página final: %s", error)

    return captured, state["responses"], matching_urls, page_title, page_text


def _run_blocking_crawl(origem, destino, data, adultos):
    url = build_url(origem, destino, data, adultos)
    logger.info("Smiles: iniciando busca em %s", url)

    # A API da Smiles às vezes recusa a sessão ("Something went wrong", sem voos).
    # Recarregar a mesma página não adianta; um navegador novo costuma passar.
    for attempt in range(1, MAX_ATTEMPTS + 1):
        if attempt > 1:
            logger.info("Smiles: tentando de novo com um navegador novo (tentativa %s)", attempt)
            time.sleep(RETRY_DELAY_S)
        captured, response_count, matching_urls, page_title, page_text = _capture_once(url)
        if any(_flight_count(p) for p in captured):
            break
        if captured:
            logger.warning("Smiles: resposta sem voos: %s", _summary(captured[-1]))

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

    api_data = max(captured, key=_flight_count)

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
