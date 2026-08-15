import asyncio
import json
import logging
import aio_pika
from aio_pika import IncomingMessage, ExchangeType
from worker.config import RABBIT_URL, QUEUE_NAME, PREFETCH_COUNT
from worker.db import (
    init_db,
    close_db,
    mark_job_done,
    mark_job_failed,
    mark_search_request_provider_done,
    mark_job_running,
    mark_search_request_provider_failed,
    insert_fare_snapshot,
)
from worker.smiles_crawler import crawl_smiles
from worker.utils import flight_to_snapshot

logger = logging.getLogger(__name__)


async def handle_message(message: IncomingMessage):
    job_id = None
    search_id = None
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

            await mark_job_running(job_id)

            api_data, flights = await crawl_smiles(origin, destination, travel_date, adultos)
            if not flights:
                if search_id is not None:
                    await mark_search_request_provider_done(search_id, "smiles")
                await mark_job_done(job_id, "smiles")
                return

            for flight in flights:
                snapshot = flight_to_snapshot(flight, travel_date, "smiles")
                await insert_fare_snapshot(snapshot)

            if search_id is not None:
                await mark_search_request_provider_done(search_id, "smiles")
            await mark_job_done(job_id, "smiles")
        except Exception as error:
            logger.exception("Erro ao processar job Smiles %s", job_id)

            if job_id is not None:
                try:
                    await mark_job_failed(job_id, str(error))
                except Exception:
                    logger.exception("Não foi possível marcar o crawl job %s como failed", job_id)

            if search_id is not None:
                try:
                    await mark_search_request_provider_failed(search_id, "smiles")
                except Exception:
                    logger.exception(
                        "Não foi possível marcar o search request provider %s como Failed",
                        search_id,
                    )

async def main():
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
