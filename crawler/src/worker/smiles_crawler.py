import json
import asyncio
from camoufox.sync_api import Camoufox
from typing import Tuple, Optional
from worker.utils import parse_flights

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

    with Camoufox(
        headless=True,
        geoip=False,
        humanize=True,
        locale="pt-BR",
    ) as browser:

        page = browser.new_page()

        def handle_response(response):
            nonlocal api_found
            try:
                if (
                    response.url and
                    "flightsearch" in response.url
                    and "/search" in response.url
                ):
                    body = response.text()
                    data = json.loads(body)
                    captured.append(data)
                    api_found = True
            except Exception:
                pass

        page.on("response", handle_response)
        page.goto(url, wait_until="networkidle", timeout=120000)
        for _ in range(120):
            if api_found:
                break
            page.wait_for_timeout(500)

    if not captured:
        return None, []

    api_data = max(
        captured,
        key=lambda x: len(
            x.get("requestedFlightSegmentList", [{}])[0]
             .get("flightList", [])
        ) if x.get("requestedFlightSegmentList") else 0
    )

    flights = parse_flights(api_data)
    return api_data, flights

async def crawl_smiles(origem: str, destino: str, data: str, adultos: int = 1) -> Tuple[Optional[dict], list]:
    # Run blocking Camoufox in thread
    loop = asyncio.get_running_loop()
    api_data, flights = await loop.run_in_executor(None, _run_blocking_crawl, origem, destino, data, adultos)
    return api_data, flights
