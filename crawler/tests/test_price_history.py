"""Histórico de preços: uma linha por cabine a cada coleta, com o menor preço."""

import asyncio
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from worker import consumer  # noqa: E402
from worker.utils import summarize_price_history  # noqa: E402
from test_consumer_requeue import FakeMessage  # noqa: E402

D = date(2026, 12, 2)


def snap(miles, cabin="Economy", taxes=100, direct=False, provider="smiles"):
    return {"origin": "gig", "destination": "mad", "travel_date": D, "provider": provider,
            "class": cabin, "miles_price": miles, "taxes_cents": taxes, "currency": "BRL",
            "direct_only": direct}


def test_one_row_per_cabin_with_cheapest_fare():
    rows = summarize_price_history([
        snap(90000, taxes=500), snap(85000, taxes=41200), snap(120000, direct=True),
        snap(250000, cabin="Business", direct=True), snap(0),
    ])
    by_cabin = {r["class"]: r for r in rows}
    assert set(by_cabin) == {"Economy", "Business"}
    eco = by_cabin["Economy"]
    assert (eco["origin"], eco["destination"]) == ("GIG", "MAD")
    assert eco["min_miles_price"] == 85000 and eco["taxes_cents"] == 41200
    assert eco["min_miles_price_direct"] == 120000
    assert eco["flights_found"] == 4  # inclui o voo sem preço
    assert by_cabin["Business"]["min_miles_price_direct"] == 250000


def test_no_direct_flight_and_no_priced_fare():
    rows = summarize_price_history([snap(90000)])
    assert rows[0]["min_miles_price_direct"] is None
    assert summarize_price_history([snap(0), snap(None)]) == []


def _run(monkeypatch, history_insert):
    calls = []
    for name in ("mark_job_running", "mark_job_failed", "mark_job_done", "insert_fare_snapshot",
                 "mark_search_request_provider_failed", "mark_search_request_provider_done"):
        async def rec(*args, _n=name):
            calls.append(_n)
            return "UPDATE 1"
        monkeypatch.setattr(consumer, name, rec)
    async def now():
        return "T0"
    async def delete_stale(*_):
        return 0
    monkeypatch.setattr(consumer, "db_now", now)
    monkeypatch.setattr(consumer, "delete_stale_fare_snapshots", delete_stale)
    monkeypatch.setattr(consumer, "insert_fare_price_history", history_insert)

    async def crawler(*_):
        return {}, [{"origem": "GIG", "destino": "MAD", "miles_price": 85000, "taxes_cents": 100,
                     "cabin": "ECONOMIC", "escalas": 1}]
    monkeypatch.setitem(consumer.CRAWLERS, "azul", crawler)
    msg = FakeMessage({"job_id": 7, "search_id": "s", "origin": "GIG", "destination": "MAD",
                       "travel_date": "2026-12-02", "provider": "azul"})
    asyncio.run(consumer.handle_message(msg))
    return msg.calls, calls


def test_consumer_writes_history_with_crawl_time(monkeypatch):
    seen = []
    async def history(rows, crawled_at):
        seen.append((rows, crawled_at))
        return len(rows)
    msg_calls, calls = _run(monkeypatch, history)
    rows, crawled_at = seen[0]
    assert crawled_at == "T0"
    assert rows[0]["min_miles_price"] == 85000 and rows[0]["provider"] == "azul"
    assert "mark_job_done" in calls and msg_calls == [("ack",)]


def test_history_failure_does_not_fail_the_job(monkeypatch):
    async def history(rows, crawled_at):
        raise RuntimeError('relation "fare_price_history" does not exist')
    msg_calls, calls = _run(monkeypatch, history)
    assert "mark_job_done" in calls and "mark_job_failed" not in calls
    assert msg_calls == [("ack",)]


def test_unknown_tax_stays_unknown_in_history():
    # Taxa a confirmar (parceiras na Smiles) não vira 0 no histórico.
    rows = summarize_price_history([snap(85000, taxes=None)])
    assert rows[0]["taxes_cents"] is None
