import asyncio
import asyncpg
from typing import Optional
from .config import DATABASE_URL

pool: Optional[asyncpg.pool.Pool] = None

async def init_db():
    global pool
    if pool is None:
        pool = await asyncpg.create_pool(DATABASE_URL)

async def close_db():
    global pool
    if pool:
        await pool.close()
        pool = None

async def mark_job_running(job_id: str):
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE crawl_jobs
            SET "Status" = 'running', "StartedAt" = now()
            WHERE "Id" = $1
            """,
            job_id,
        )

async def mark_job_done(job_id: str, provider: str):
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE crawl_jobs
            SET "Status" = 'done', "FinishedAt" = now()
            WHERE "Id" = $1
            """,
            job_id,
        )

async def mark_job_failed(job_id: str, error: str):
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE crawl_jobs
            SET "Status" = 'failed', "FinishedAt" = now(), "Error" = $2
            WHERE "Id" = $1
            """,
            job_id,
            error,
        )

async def get_job_search_id(job_id: str):
    """Obtém o SearchId associado ao job quando ele não vier na mensagem."""
    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow(
                'SELECT "SearchId" FROM crawl_jobs WHERE "Id" = $1',
                job_id,
            )
        except asyncpg.UndefinedColumnError:
            return None
    return row["SearchId"] if row else None

async def mark_search_request_provider_failed(search_id: str, provider: str):
    return await mark_search_request_provider_completed(search_id, provider, "Failed")

async def mark_search_request_provider_done(search_id: str, provider: str):
    return await mark_search_request_provider_completed(search_id, provider, "Done")

async def mark_search_request_provider_completed(search_id: str, provider: str, status: str):
    async with pool.acquire() as conn:
        return await conn.execute(
            """
            UPDATE search_request_providers
            SET "Status" = $3, "CompletedAt" = now()
            WHERE "SearchId" = $1 AND "Provider" = $2
            """,
            search_id,
            provider,
            status,
        )

async def insert_fare_snapshot(snapshot: dict):
    # minimal insert for demo; adapt columns as needed
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO fare_snapshots(
                "Origin", "Destination", "TravelDate", "Class", "DirectOnly",
                "Provider", "FareOptionId", "MilesPrice", "TaxesCents", "Currency",
                "SeatsAvailable", "CrawlerUrl", "FlightDurationMinutes", "NumberOfStops",
                "DepartureTime", "ArrivalTime", "CarrierCode", "FlightNumber",
                "LastCrawledAt", "CreatedAt", "UpdatedAt"
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18, now(), now(), now())
            ON CONFLICT (
                "Origin", "Destination", "TravelDate", "Provider", "CarrierCode",
                "FlightNumber", "DepartureTime", "ArrivalTime", "Class", "DirectOnly"
            ) DO UPDATE SET
                "MilesPrice" = EXCLUDED."MilesPrice",
                "TaxesCents" = EXCLUDED."TaxesCents",
                "SeatsAvailable" = EXCLUDED."SeatsAvailable",
                "LastCrawledAt" = now(),
                "UpdatedAt" = now()
            """,
            snapshot.get("origin"),
            snapshot.get("destination"),
            snapshot.get("travel_date"),
            snapshot.get("class"),
            snapshot.get("direct_only", False),
            snapshot.get("provider"),
            snapshot.get("fare_option_id", 1),
            snapshot.get("miles_price"),
            snapshot.get("taxes_cents", 0),
            snapshot.get("currency", "BRL"),
            snapshot.get("seats_available", 0),
            snapshot.get("crawler_url"),
            snapshot.get("flight_duration_minutes", 0),
            snapshot.get("number_of_stops", 0),
            snapshot.get("departure_time"),
            snapshot.get("arrival_time"),
            snapshot.get("carrier_code", ""),
            snapshot.get("flight_number", ""),
        )
