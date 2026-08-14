import asyncio
import json
import aio_pika
from aio_pika import IncomingMessage, ExchangeType
from worker.config import RABBIT_URL, QUEUE_NAME, PREFETCH_COUNT
from worker.db import init_db, close_db, mark_job_done, mark_job_running, insert_fare_snapshot
from worker.smiles_crawler import crawl_smiles
from worker.utils import select_best_flight, flight_to_snapshot

async def handle_message(message: IncomingMessage):
    async with message.process(requeue=False):
        try:
            payload = json.loads(message.body)
        except Exception:
            return

        job_id = payload.get("job_id")
        origin = payload.get("origin")
        destination = payload.get("destination")
        travel_date = payload.get("travel_date")
        adultos = payload.get("adults", 1)

        await mark_job_running(job_id)

        api_data, flights = await crawl_smiles(origin, destination, travel_date, adultos)
        if not flights:
            # mark failed (simple path: set done but no results)
            await mark_job_done(job_id, "smiles")
            return

        best = select_best_flight(flights)
        if best:
            snapshot = flight_to_snapshot(best, travel_date, "smiles")
            await insert_fare_snapshot(snapshot)

        await mark_job_done(job_id, "smiles")

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
