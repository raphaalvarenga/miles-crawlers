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

async def insert_fare_snapshot(snapshot: dict):
    # minimal insert for demo; adapt columns as needed
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO fare_snapshots(
                "Origin", "Destination", "TravelDate", "Class", "DirectOnly",
                "Provider", "FareOptionId", "MilesPrice", "TaxesCents", "Currency",
                "SeatsAvailable", "LastCrawledAt", "CreatedAt", "UpdatedAt"
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11, now(), now(), now())
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
        )
