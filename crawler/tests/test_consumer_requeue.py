"""Consumer: job que nenhuma extensão pegou volta para a fila (nack com requeue) e não é marcado como falha."""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from worker import consumer  # noqa: E402
from worker.extension_bridge import JobNotClaimed  # noqa: E402


class FakeMessage:
    def __init__(self, body):
        self.body = json.dumps(body).encode()
        self.processed = False
        self.redelivered = False
        self.calls = []

    def process(self, requeue=False, ignore_processed=False):
        msg = self

        class Ctx:
            async def __aenter__(self):
                return msg

            async def __aexit__(self, exc_type, exc, tb):
                if exc_type is None and not (ignore_processed and msg.processed):
                    await msg.ack()
                elif exc_type is not None and not (ignore_processed and msg.processed):
                    msg.calls.append(("reject", requeue))
        return Ctx()

    async def ack(self):
        assert not self.processed, "ack depois de já processada"
        self.processed = True
        self.calls.append(("ack",))

    async def nack(self, requeue=True):
        assert not self.processed
        self.processed = True
        self.calls.append(("nack", requeue))


def run(crawler, monkeypatch):
    db = []
    for name in ("mark_job_running", "mark_job_queued", "mark_job_failed", "mark_job_done",
                 "mark_search_request_provider_failed", "mark_search_request_provider_done"):
        async def rec(*args, _n=name):
            db.append(_n)
            return "UPDATE 1"
        monkeypatch.setattr(consumer, name, rec)
    monkeypatch.setitem(consumer.CRAWLERS, "azul", crawler)
    msg = FakeMessage({"job_id": 7, "search_id": "s", "origin": "GIG", "destination": "MAD",
                       "travel_date": "2026-12-26", "provider": "azul"})
    asyncio.run(consumer.handle_message(msg))
    return msg.calls, db


def test_unclaimed_job_is_requeued(monkeypatch):
    async def crawler(*_):
        raise JobNotClaimed("nenhuma extensão pegou o job em 60 s")
    calls, db = run(crawler, monkeypatch)
    assert calls == [("nack", True)]
    assert "mark_job_queued" in db
    assert "mark_job_failed" not in db and "mark_search_request_provider_failed" not in db


def test_other_errors_still_fail_and_ack(monkeypatch):
    async def crawler(*_):
        raise RuntimeError("bloqueio anti-bot")
    calls, db = run(crawler, monkeypatch)
    assert calls == [("ack",)]
    assert "mark_job_failed" in db and "mark_search_request_provider_failed" in db
