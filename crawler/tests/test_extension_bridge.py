"""Ponte ↔ "extensão" simulada por HTTP, sem RabbitMQ nem Postgres."""

import asyncio
import json
import socket
import sys
from pathlib import Path

import aiohttp
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from worker.errors import RequeueJob  # noqa: E402
from worker.extension_bridge import BridgeError, ExtensionBridge, JobNotClaimed  # noqa: E402

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "azul_availability_v6_GIG_MAD.json").read_text(encoding="utf-8")
)
TOKEN = "teste-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def with_bridge(scenario, **kwargs):
    bridge = ExtensionBridge(TOKEN, **kwargs)
    port = free_port()
    runner = await bridge.start("127.0.0.1", port)
    try:
        async with aiohttp.ClientSession(f"http://127.0.0.1:{port}") as http:
            return await scenario(bridge, http)
    finally:
        await runner.cleanup()


def test_job_round_trip_returns_parsed_flights():
    async def scenario(bridge, http):
        crawl = asyncio.create_task(bridge.crawl("azul", "GIG", "MAD", "2026-12-26"))
        async with http.get("/jobs/next?provider=azul&wait=2", headers=AUTH) as r:
            assert r.status == 200
            job = await r.json()
        assert job["url"].endswith("c[0].ds=GIG&c[0].std=12/26/2026&c[0].as=MAD&p[0].t=ADT&p[0].c=1"
                                   "&p[0].cp=false&f.dl=3&f.dr=3&cc=PTS")
        assert job["capture"] == "/tudoazul/reservation/availability/"
        async with http.post(f"/jobs/{job['id']}/result", headers=AUTH,
                             json={"url": "https://b2c-api.voeazul.com.br/x/v6/availability", "payload": FIXTURE}) as r:
            assert r.status == 200
        _payload, flights = await crawl
        assert [(f["flight_number"], f["cabin"], f["miles_price"]) for f in flights] == [
            ("2849/8754", "ECONOMIC", 402000),
            ("2849/8754", "BUSINESS", 813000),
            ("4205/4046/8754", "ECONOMIC", 402000),
        ]
        assert all(f["crawler_url"] == job["url"] for f in flights)
        # job encerrado: novo resultado é recusado
        async with http.post(f"/jobs/{job['id']}/result", headers=AUTH, json={"payload": FIXTURE}) as r:
            assert r.status == 410

    asyncio.run(with_bridge(scenario))


def test_blocked_fails_the_crawl():
    async def scenario(bridge, http):
        crawl = asyncio.create_task(bridge.crawl("azul", "GIG", "MAD", "2026-12-26"))
        async with http.get("/jobs/next?provider=azul&wait=2", headers=AUTH) as r:
            job = await r.json()
        async with http.post(f"/jobs/{job['id']}/blocked", headers=AUTH, json={"url": job["url"]}) as r:
            assert r.status == 200
        with pytest.raises(BridgeError, match="anti-bot"):
            await crawl

    asyncio.run(with_bridge(scenario))


def test_unclaimed_job_times_out_and_is_not_handed_out_later():
    async def scenario(bridge, http):
        with pytest.raises(BridgeError, match="nenhuma extensão"):
            await bridge.crawl("azul", "GIG", "MAD", "2026-12-26")
        async with http.get("/jobs/next?provider=azul&wait=0", headers=AUTH) as r:
            assert r.status == 204

    asyncio.run(with_bridge(scenario, claim_timeout_s=0.2))


def test_unclaimed_job_asks_to_go_back_to_the_queue():
    async def scenario(bridge, http):
        with pytest.raises(RequeueJob):
            await bridge.crawl("azul", "GIG", "MAD", "2026-12-26")

    asyncio.run(with_bridge(scenario, claim_timeout_s=0.2))


def test_unclaimed_job_fails_when_requeue_is_off():
    async def scenario(bridge, http):
        with pytest.raises(BridgeError) as info:
            await bridge.crawl("azul", "GIG", "MAD", "2026-12-26")
        assert not isinstance(info.value, RequeueJob)

    asyncio.run(with_bridge(scenario, claim_timeout_s=0.2, requeue_unclaimed=False))


def test_claimed_job_that_times_out_is_a_failure_not_a_requeue():
    async def scenario(bridge, http):
        crawl = asyncio.create_task(bridge.crawl("azul", "GIG", "MAD", "2026-12-26"))
        async with http.get("/jobs/next?provider=azul&wait=2", headers=AUTH) as r:
            assert r.status == 200
        with pytest.raises(BridgeError) as info:
            await crawl
        assert not isinstance(info.value, JobNotClaimed)

    asyncio.run(with_bridge(scenario, claim_timeout_s=0.3, job_timeout_s=0.3))


def test_requires_token_and_health_is_public():
    async def scenario(bridge, http):
        async with http.get("/jobs/next?provider=azul&wait=0") as r:
            assert r.status == 401
        async with http.get("/jobs/next?provider=azul&wait=0", headers={"Authorization": "Bearer errado"}) as r:
            assert r.status == 401
        async with http.get("/health") as r:
            assert r.status == 200 and (await r.json())["providers"] == ["azul", "latam", "smiles"]

    asyncio.run(with_bridge(scenario))


def test_consumers_lists_who_polls_with_id_name_version_and_ip():
    headers = {**AUTH, "X-Consumer-Id": "abc-123", "X-Consumer-Name": "PC%20do%20escrit%C3%B3rio",
               "X-Extension-Version": "0.8.0"}

    async def scenario(bridge, http):
        crawl = asyncio.create_task(bridge.crawl("azul", "GIG", "MAD", "2026-12-26"))
        async with http.get("/jobs/next?provider=azul&wait=2", headers=headers) as r:
            job = await r.json()
        async with http.get("/consumers", headers=AUTH) as r:
            (c,) = (await r.json())["consumers"]
        assert (c["id"], c["name"], c["version"], c["ip"], c["online"]) == (
            "abc-123", "PC do escritório", "0.8.0", "127.0.0.1", True)
        assert c["current_job"] == job["id"] and c["jobs"]["claimed"] == 1 and "azul" in c["last_poll_at"]
        async with http.post(f"/jobs/{job['id']}/result", headers=headers, json={"payload": FIXTURE}) as r:
            assert r.status == 200
        await crawl
        async with http.get("/consumers", headers=AUTH) as r:
            (c,) = (await r.json())["consumers"]
        assert c["jobs"]["done"] == 1 and c["current_job"] is None
        # /health é público: só a contagem, sem id nem IP.
        async with http.get("/health") as r:
            health = await r.json()
        assert health["consumers_online"] == 1 and "consumers" not in health
        async with http.get("/consumers") as r:
            assert r.status == 401

    asyncio.run(with_bridge(scenario))


def test_old_extension_without_id_is_listed_by_ip():
    async def scenario(bridge, http):
        async with http.get("/jobs/next?provider=smiles&wait=0", headers=AUTH) as r:
            assert r.status == 204
        async with http.get("/consumers", headers=AUTH) as r:
            (c,) = (await r.json())["consumers"]
        assert c["id"] == "ip:127.0.0.1" and c["name"] == "" and "smiles" in c["last_poll_at"]

    asyncio.run(with_bridge(scenario))
