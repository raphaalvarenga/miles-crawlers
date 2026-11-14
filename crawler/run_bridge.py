"""Worker das filas crawl.azul e crawl.latam que delega a busca à extensão Chrome (Miles Fetcher).

Rode na mesma máquina do Chrome com a extensão:

    set BRIDGE_TOKEN=<o mesmo token configurado na extensão>
    python run_bridge.py                    # consome crawl.azul e crawl.latam e grava no Postgres

Teste sem RabbitMQ nem Postgres (só ponte + extensão):

    python run_bridge.py --once GIG MAD 2026-12-26
    python run_bridge.py --once MAD GIG 2026-12-25 --provider latam

Variáveis: BRIDGE_TOKEN (obrigatória), BRIDGE_HOST (127.0.0.1), BRIDGE_PORT (8765),
BRIDGE_CLAIM_TIMEOUT_S (60), BRIDGE_JOB_TIMEOUT_S (90), BRIDGE_QUEUES (padrão
crawl.<provider> para cada provider da ponte, separadas por vírgula), além de
RABBIT_URL e DATABASE_URL do worker normal.
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from worker.extension_bridge import PROVIDERS, ExtensionBridge  # noqa: E402


def build_bridge() -> ExtensionBridge:
    token = os.getenv("BRIDGE_TOKEN", "")
    if not token:
        sys.exit("Defina BRIDGE_TOKEN (o mesmo token das opções da extensão).")
    return ExtensionBridge(
        token=token,
        claim_timeout_s=float(os.getenv("BRIDGE_CLAIM_TIMEOUT_S", "60")),
        job_timeout_s=float(os.getenv("BRIDGE_JOB_TIMEOUT_S", "90")),
    )


async def run_once(bridge: ExtensionBridge, host: str, port: int, args) -> None:
    runner = await bridge.start(host, port)
    try:
        print(f"Aguardando a extensão pegar o job {args.origem}-{args.destino} {args.data}...")
        _payload, flights = await bridge.crawl(args.provider, args.origem, args.destino, args.data, args.adultos)
        print(f"{len(flights)} tarifas:")
        for f in flights:
            print(json.dumps({k: f[k] for k in (
                "voo", "cabin", "partida", "chegada", "escalas", "miles_price", "money_brl", "assentos",
            )}, ensure_ascii=False))
    finally:
        await runner.cleanup()


async def run_worker(bridge: ExtensionBridge, host: str, port: int) -> None:
    from worker import consumer

    for provider in PROVIDERS:
        consumer.CRAWLERS[provider] = bridge.crawler_for(provider)
    queues = [q.strip() for q in os.getenv("BRIDGE_QUEUES", "").split(",") if q.strip()]
    queues = queues or [f"crawl.{p}" for p in PROVIDERS]
    runner = await bridge.start(host, port)
    try:
        await consumer.main(queues)
    finally:
        await runner.cleanup()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--once", nargs=3, metavar=("ORIGEM", "DESTINO", "DATA"),
                        help="faz uma busca só pela extensão e imprime o resultado")
    parser.add_argument("--provider", default="azul", choices=sorted(PROVIDERS))
    parser.add_argument("--adultos", type=int, default=1)
    args = parser.parse_args()

    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    host = os.getenv("BRIDGE_HOST", "127.0.0.1")
    port = int(os.getenv("BRIDGE_PORT", "8765"))
    bridge = build_bridge()
    try:
        if args.once:
            args.origem, args.destino, args.data = args.once[0].upper(), args.once[1].upper(), args.once[2]
            asyncio.run(run_once(bridge, host, port, args))
        else:
            asyncio.run(run_worker(bridge, host, port))
    except KeyboardInterrupt:
        print("Interrompido")


if __name__ == "__main__":
    main()
