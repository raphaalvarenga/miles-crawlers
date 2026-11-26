"""Ponte entre a fila crawl.<provider> e a extensão Chrome "Milheirinho Coletor".

O consumer continua igual: para os providers da ponte, a função de crawl em vez de
abrir um navegador headless entrega o job à extensão e espera o JSON cru que a
página da companhia recebeu. O parse e as gravações no Postgres seguem no Python.

HTTP (Bearer token em tudo, menos /health):
    GET  /health                       estado da ponte e da extensão (sem dados de quem conecta)
    GET  /consumers                    extensões que falaram com a ponte nas últimas 24 h
    GET  /jobs/next?provider=azul|latam|smiles&wait=20   long-poll: 200 com o job ou 204
    POST /jobs/{id}/result   {"url", "payload"}   JSON da API de disponibilidade
    POST /jobs/{id}/failed   {"error"}
    POST /jobs/{id}/blocked  {"url"}               verificação anti-bot na aba

Cada extensão se identifica nos cabeçalhos X-Consumer-Id (gerado na instalação),
X-Consumer-Name (nome dado nas opções, codificado como URL) e X-Extension-Version.
O IP é o de quem abriu a conexão.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import secrets
import re
import time
from dataclasses import dataclass, field
from typing import Callable, Optional
from urllib.parse import unquote

from aiohttp import web

from worker.errors import RequeueJob

from worker.tudoazul_parser import AVAILABILITY_URL_FRAGMENT, build_url as azul_build_url
from worker.tudoazul_parser import parse_tudoazul_flights
from worker.latam_parser import REDEMPTION_URL_FRAGMENT, build_url as latam_build_url
from worker.latam_parser import parse_latam_flights
from worker.smiles_parser import AVAILABILITY_URL_FRAGMENT as SMILES_URL_FRAGMENT
from worker.smiles_parser import build_url as smiles_build_url, parse_smiles_flights

logger = logging.getLogger(__name__)

MAX_BODY_BYTES = 20 * 1024 * 1024
CONSUMER_ONLINE_S = 120     # sem falar com a ponte há mais que isso: desconectada
CONSUMER_FORGET_S = 86_400  # some da lista depois de 24 h sem aparecer
_SAFE_ID = re.compile(r"[^A-Za-z0-9._-]")


@dataclass(frozen=True)
class ProviderSpec:
    build_url: Callable[..., str]
    capture: str  # trecho da URL da resposta que a extensão deve capturar
    parse: Callable[[dict], list]


PROVIDERS: dict[str, ProviderSpec] = {
    "azul": ProviderSpec(azul_build_url, AVAILABILITY_URL_FRAGMENT, parse_tudoazul_flights),
    "latam": ProviderSpec(latam_build_url, REDEMPTION_URL_FRAGMENT, parse_latam_flights),
    "smiles": ProviderSpec(smiles_build_url, SMILES_URL_FRAGMENT, parse_smiles_flights),
}


class BridgeError(RuntimeError):
    """O job não voltou da extensão com uma resposta utilizável."""


class JobNotClaimed(BridgeError, RequeueJob):
    """Nenhuma extensão pegou o job a tempo: ele volta para a fila do RabbitMQ."""


@dataclass
class BridgeJob:
    id: str
    provider: str
    url: str
    capture: str
    created_at: float
    future: asyncio.Future
    claimed_at: Optional[float] = None
    claimed_by: Optional[str] = None


@dataclass
class Consumer:
    """Uma extensão (um Chrome) que fala com a ponte."""
    id: str
    name: str
    version: str
    ip: str
    first_seen: float
    last_seen: float
    last_poll_at: dict[str, float] = field(default_factory=dict)  # provider → hora
    jobs: dict[str, int] = field(default_factory=lambda: {"claimed": 0, "done": 0, "failed": 0, "blocked": 0})
    current_job: Optional[str] = None
    last_job_at: Optional[float] = None

    def as_dict(self, now: float) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "ip": self.ip,
            "online": now - self.last_seen <= CONSUMER_ONLINE_S,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "last_poll_at": self.last_poll_at,
            "jobs": self.jobs,
            "current_job": self.current_job,
            "last_job_at": self.last_job_at,
        }


class ExtensionBridge:
    def __init__(
        self,
        token: str,
        claim_timeout_s: float = 60,
        job_timeout_s: float = 90,
        poll_wait_s: float = 20,
        requeue_unclaimed: bool = True,
    ):
        if not token:
            raise ValueError("BRIDGE_TOKEN é obrigatório")
        self.token = token
        self.claim_timeout_s = claim_timeout_s
        self.job_timeout_s = job_timeout_s
        self.poll_wait_s = poll_wait_s
        self.requeue_unclaimed = requeue_unclaimed
        self._queues: dict[str, asyncio.Queue] = {}
        self._jobs: dict[str, BridgeJob] = {}
        self._seq = itertools.count(1)
        self.last_poll_at: dict[str, float] = {}
        self.last_result_at: dict[str, float] = {}
        self.consumers: dict[str, Consumer] = {}

    # ── lado do worker ────────────────────────────────────────────────────
    def _queue(self, provider: str) -> asyncio.Queue:
        return self._queues.setdefault(provider, asyncio.Queue())

    def crawler_for(self, provider: str):
        async def crawl(origem: str, destino: str, data: str, adultos: int = 1):
            return await self.crawl(provider, origem, destino, data, adultos)
        return crawl

    async def crawl(self, provider: str, origem: str, destino: str, data: str, adultos: int = 1):
        spec = PROVIDERS[provider]
        url = spec.build_url(origem, destino, data, adultos)
        job = BridgeJob(
            id=f"{provider}-{next(self._seq)}-{secrets.token_hex(3)}",
            provider=provider,
            url=url,
            capture=spec.capture,
            created_at=time.time(),
            future=asyncio.get_running_loop().create_future(),
        )
        self._jobs[job.id] = job
        await self._queue(provider).put(job)
        logger.info("Ponte: job %s aguardando a extensão %s", job.id, url)
        try:
            payload = await self._wait(job)
        finally:
            self._jobs.pop(job.id, None)
            if not job.future.done():
                job.future.cancel()

        flights = spec.parse(payload)
        for flight in flights:
            flight["crawler_url"] = url
        logger.info("Ponte: job %s voltou com %d tarifas", job.id, len(flights))
        return payload, flights

    async def _wait(self, job: BridgeJob) -> dict:
        try:
            return await asyncio.wait_for(asyncio.shield(job.future), self.claim_timeout_s)
        except asyncio.TimeoutError:
            if job.claimed_at is None:
                message = (f"nenhuma extensão pegou o job em {self.claim_timeout_s:.0f} s "
                           "(o Chrome com a extensão está aberto?)")
                raise (JobNotClaimed if self.requeue_unclaimed else BridgeError)(message) from None
        remaining = job.claimed_at + self.job_timeout_s - time.time()
        try:
            return await asyncio.wait_for(asyncio.shield(job.future), max(remaining, 1))
        except asyncio.TimeoutError:
            raise BridgeError(f"a extensão não devolveu o job em {self.job_timeout_s:.0f} s") from None

    # ── lado HTTP (extensão) ──────────────────────────────────────────────
    def app(self) -> web.Application:
        app = web.Application(middlewares=[self._auth], client_max_size=MAX_BODY_BYTES)
        app.router.add_get("/health", self._health)
        app.router.add_get("/consumers", self._consumers)
        app.router.add_get("/jobs/next", self._next)
        app.router.add_post("/jobs/{job_id}/result", self._result)
        app.router.add_post("/jobs/{job_id}/failed", self._failed)
        app.router.add_post("/jobs/{job_id}/blocked", self._blocked)
        return app

    async def start(self, host: str, port: int) -> web.AppRunner:
        runner = web.AppRunner(self.app())
        await runner.setup()
        await web.TCPSite(runner, host, port).start()
        logger.info("Ponte da extensão ouvindo em http://%s:%s", host, port)
        return runner

    @web.middleware
    async def _auth(self, request: web.Request, handler):
        if request.path != "/health":
            expected = f"Bearer {self.token}"
            if not secrets.compare_digest(request.headers.get("Authorization", ""), expected):
                return web.json_response({"error": "token inválido"}, status=401)
        return await handler(request)

    def _consumer(self, request: web.Request) -> Consumer:
        """Registra (ou atualiza) quem fez a chamada; extensão antiga sem id vira 'ip:<ip>'."""
        now = time.time()
        ip = request.remote or "?"
        raw_id = _SAFE_ID.sub("", request.headers.get("X-Consumer-Id", ""))[:64]
        consumer_id = raw_id or f"ip:{ip}"
        name = unquote(request.headers.get("X-Consumer-Name", "")).strip()[:60]
        version = _SAFE_ID.sub("", request.headers.get("X-Extension-Version", ""))[:20]
        consumer = self.consumers.get(consumer_id)
        if consumer is None:
            consumer = self.consumers[consumer_id] = Consumer(consumer_id, name, version, ip, now, now)
            logger.info("Ponte: extensão nova %s (%s, %s, v%s)", consumer_id, name or "sem nome", ip, version or "?")
        consumer.name, consumer.version, consumer.ip, consumer.last_seen = name, version, ip, now
        for key in [k for k, c in self.consumers.items() if now - c.last_seen > CONSUMER_FORGET_S]:
            del self.consumers[key]
        return consumer

    def _finish(self, request: web.Request, job: BridgeJob, outcome: str) -> None:
        consumer = self._consumer(request)
        consumer.jobs[outcome] += 1
        consumer.last_job_at = time.time()
        if consumer.current_job == job.id:
            consumer.current_job = None

    async def _consumers(self, _request: web.Request):
        now = time.time()
        items = sorted(self.consumers.values(), key=lambda c: c.last_seen, reverse=True)
        return web.json_response({"now": now, "consumers": [c.as_dict(now) for c in items]})

    async def _health(self, _request: web.Request):
        now = time.time()
        return web.json_response({
            "ok": True,
            "providers": sorted(PROVIDERS),
            "waiting": {p: q.qsize() for p, q in self._queues.items()},
            "in_flight": sum(1 for j in self._jobs.values() if j.claimed_at is not None),
            "last_poll_at": self.last_poll_at,
            "last_result_at": self.last_result_at,
            "consumers_online": sum(1 for c in self.consumers.values() if now - c.last_seen <= CONSUMER_ONLINE_S),
        })

    async def _next(self, request: web.Request):
        provider = request.query.get("provider", "azul")
        if provider not in PROVIDERS:
            return web.json_response({"error": f"provider desconhecido: {provider}"}, status=400)
        self.last_poll_at[provider] = time.time()
        consumer = self._consumer(request)
        consumer.last_poll_at[provider] = consumer.last_seen
        try:
            wait = min(max(float(request.query.get("wait", self.poll_wait_s)), 0), 25)
        except ValueError:
            wait = self.poll_wait_s
        queue = self._queue(provider)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + wait
        while True:
            remaining = deadline - loop.time()
            try:
                job = queue.get_nowait() if remaining <= 0 else await asyncio.wait_for(queue.get(), remaining)
            except (asyncio.TimeoutError, asyncio.QueueEmpty):
                return web.Response(status=204)
            if job.future.done():  # expirou antes de alguém pegar
                continue
            job.claimed_at = time.time()
            job.claimed_by = consumer.id
            consumer.current_job = job.id
            consumer.jobs["claimed"] += 1
            logger.info("Ponte: job %s entregue à extensão %s (%s)", job.id, consumer.name or consumer.id, consumer.ip)
            return web.json_response({
                "id": job.id,
                "provider": job.provider,
                "url": job.url,
                "capture": job.capture,
                "timeout_s": self.job_timeout_s,
            })

    def _open_job(self, request: web.Request) -> Optional[BridgeJob]:
        job = self._jobs.get(request.match_info["job_id"])
        return job if job is not None and not job.future.done() else None

    async def _body(self, request: web.Request) -> dict:
        try:
            body = await request.json()
        except Exception:
            raise web.HTTPBadRequest(text="corpo não é JSON") from None
        if not isinstance(body, dict):
            raise web.HTTPBadRequest(text="corpo deve ser um objeto")
        return body

    async def _result(self, request: web.Request):
        body = await self._body(request)
        job = self._open_job(request)
        if job is None:
            return web.json_response({"error": "job inexistente ou expirado"}, status=410)
        payload = body.get("payload")
        if not isinstance(payload, dict):
            return web.json_response({"error": "payload deve ser o JSON da API"}, status=400)
        self.last_result_at[job.provider] = time.time()
        self._finish(request, job, "done")
        job.future.set_result(payload)
        return web.json_response({"ok": True})

    async def _failed(self, request: web.Request):
        body = await self._body(request)
        job = self._open_job(request)
        if job is None:
            return web.json_response({"error": "job inexistente ou expirado"}, status=410)
        error = str(body.get("error") or "erro sem detalhe")[:500]
        logger.warning("Ponte: extensão falhou o job %s: %s", job.id, error)
        self._finish(request, job, "failed")
        job.future.set_exception(BridgeError(f"extensão: {error}"))
        return web.json_response({"ok": True})

    async def _blocked(self, request: web.Request):
        body = await self._body(request)
        job = self._open_job(request)
        if job is None:
            return web.json_response({"error": "job inexistente ou expirado"}, status=410)
        url = str(body.get("url") or job.url)[:500]
        logger.warning("Ponte: verificação anti-bot no job %s (%s); extensão pausou %s", job.id, url, job.provider)
        self._finish(request, job, "blocked")
        job.future.set_exception(BridgeError(f"bloqueio anti-bot em {url}"))
        return web.json_response({"ok": True})
