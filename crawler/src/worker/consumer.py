import asyncio
import json
import logging
import os
import aio_pika
from aio_pika import IncomingMessage, ExchangeType
from worker.config import RABBIT_URL, QUEUE_NAME, PREFETCH_COUNT
from worker.db import (
    init_db,
    close_db,
    mark_job_done,
    mark_job_failed,
    get_job_search_id,
    mark_search_request_provider_done,
    mark_job_running,
    mark_search_request_provider_failed,
    insert_fare_snapshot,
)
from worker.smiles_crawler import crawl_smiles
from worker.tudoazul_crawler import crawl_tudoazul
from worker.utils import flight_to_snapshot

logger = logging.getLogger(__name__)


async def _mark_provider_done(search_id, provider):
    result = await mark_search_request_provider_done(search_id, provider)
    if result == "UPDATE 0":
        logger.warning(
            "Nenhum search_request_provider encontrado para search_id=%s provider=%s",
            search_id,
            provider,
        )
    else:
        logger.info(
            "search_request_provider atualizado para Done: search_id=%s provider=%s",
            search_id,
            provider,
        )


async def handle_message(message: IncomingMessage):
    job_id = None
    search_id = None
    provider = "smiles"
    async with message.process(requeue=False):
        try:
            payload = json.loads(message.body)
            job_id = payload.get("job_id")
            search_id = (
                payload.get("search_id")
                or payload.get("searchId")
                or payload.get("SearchId")
            )
            origin = payload.get("origin")
            destination = payload.get("destination")
            travel_date = payload.get("travel_date")
            adultos = payload.get("adults", 1)
            provider = payload.get("provider", "smiles").lower()
            logger.info("Job recebido: id=%s provider=%s search_id=%s", job_id, provider, search_id)

            await mark_job_running(job_id)
            if search_id is None and job_id is not None:
                search_id = await get_job_search_id(job_id)
                logger.info("SearchId recuperado do crawl job: id=%s search_id=%s", job_id, search_id)

            crawlers = {
                "smiles": crawl_smiles,
                "azul": crawl_tudoazul,
            }
            crawler = crawlers.get(provider)
            if crawler is None:
                raise ValueError(f"Provider não suportado: {provider}")

            logger.info("Iniciando crawler: id=%s provider=%s rota=%s-%s data=%s", job_id, provider, origin, destination, travel_date)
            api_data, flights = await crawler(origin, destination, travel_date, adultos)
            logger.info("Crawler concluído: id=%s provider=%s voos=%d", job_id, provider, len(flights))
            if not flights:
                if search_id is not None:
                    await _mark_provider_done(search_id, provider)
                else:
                    logger.warning("Job %s concluído sem SearchId; provider permanecerá sem atualização", job_id)
                await mark_job_done(job_id, provider)
                return

            for flight in flights:
                snapshot = flight_to_snapshot(flight, travel_date, provider)
                await insert_fare_snapshot(snapshot)

            if search_id is not None:
                await _mark_provider_done(search_id, provider)
            else:
                logger.warning("Job %s concluído sem SearchId; provider permanecerá sem atualização", job_id)
            await mark_job_done(job_id, provider)
        except Exception as error:
            logger.exception("Erro ao processar job %s", job_id)

            if job_id is not None:
                try:
                    await mark_job_failed(job_id, str(error))
                except Exception:
                    logger.exception("Não foi possível marcar o crawl job %s como failed", job_id)

            if search_id is not None:
                try:
                    await mark_search_request_provider_failed(search_id, provider)
                except Exception:
                    logger.exception(
                        "Não foi possível marcar o search request provider %s como Failed",
                        search_id,
                    )

async def main():
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    await init_db()
    connection = await aio_pika.connect_robust(RABBIT_URL)
    channel = await connection.channel()
    await channel.set_qos(prefetch_count=PREFETCH_COUNT)

    queue = await channel.declare_queue(
        QUEUE_NAME,
        passive=True,
    )
    await queue.consume(handle_message)

    print(f"Listening on {QUEUE_NAME}...")
    try:
        await asyncio.Future()
    finally:
        await connection.close()
        await close_db()

if __name__ == "__main__":
    asyncio.run(main())
