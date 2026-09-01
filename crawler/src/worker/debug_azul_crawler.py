"""
Debug standalone do crawler TudoAzul, sem depender do worker/fila/docker.

Uso:
    # 1) Sanity check: só confirma que o Camoufox abre e renderiza
    python debug_azul_crawler.py sanity

    # 2) Diagnóstico completo do crawl da Azul, com dump de tudo
    python debug_azul_crawler.py crawl --origem CGH --destino SDU --data 2026-11-15

Flags úteis:
    --headful         roda com janela visível (precisa de X server / Xvfb / rodar fora do docker)
    --slowmo 250      desacelera as ações em ms, ajuda a ver o que tá travando
    --wait 25000      tempo extra de espera após o load (ms)

Saídas:
    ./debug_out/<timestamp>/
        responses.jsonl   -> todas as respostas de rede (url, status, content-type, corpo se JSON)
        screenshot_*.png  -> screenshots em pontos-chave
        page_final.html   -> HTML final da página
"""

import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

from camoufox.sync_api import Camoufox

# reaproveita as funções de parsing do crawler original
sys.path.insert(0, str(Path(__file__).parent))
try:
    from tudoazul_crawler import build_url, parse_tudoazul_flights, _journey_groups
except ImportError:
    print("AVISO: coloque este script na mesma pasta de tudoazul_crawler.py "
          "(ou ajuste o sys.path acima) para reaproveitar build_url/parse_tudoazul_flights.")
    raise

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("debug")


def sanity_check(headful: bool, slowmo: int, open_search: bool,
                  origem: str, destino: str, data: str, adultos: int,
                  keep_open_ms: int):
    """Confere se o Camoufox sobe e consegue navegar/renderizar.

    Por padrão só bate na home. Com --open-search, vai direto pra URL de
    busca (a mesma que o crawler usa) e tira screenshots ao longo do
    carregamento, sem se importar em capturar JSON - é só pra você OLHAR
    visualmente o que a página está mostrando (voos, captcha, tela de
    loading infinita, etc).
    """
    out_dir = Path("debug_out") / datetime.now().strftime("%Y%m%d_%H%M%S_sanity")
    out_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Abrindo Camoufox (headless=%s)...", not headful)
    with Camoufox(headless=not headful, geoip=False, humanize=True, locale="pt-BR") as browser:
        page = browser.new_page()

        if not open_search:
            # site que expõe fingerprinting - útil pra ver o que tá sendo detectado
            page.goto("https://bot.sannysoft.com", timeout=60000)
            page.wait_for_timeout(3000)
            page.screenshot(path=str(out_dir / "sannysoft.png"), full_page=True)
            logger.info("Screenshot salvo em %s", out_dir / "sannysoft.png")

            page.goto("https://www.voeazul.com.br", timeout=60000, wait_until="networkidle")
            page.wait_for_timeout(3000)
            page.screenshot(path=str(out_dir / "azul_home.png"), full_page=True)
            (out_dir / "azul_home.html").write_text(page.content(), encoding="utf-8")
            logger.info("Home da Azul carregada, title=%r", page.title())
        else:
            url = build_url(origem, destino, data, adultos)
            logger.info("Abrindo URL de busca: %s", url)

            page.goto(url, wait_until="networkidle", timeout=120000)
            page.screenshot(path=str(out_dir / "search_01_after_load.png"), full_page=True)
            logger.info("Screenshot logo após o load (networkidle) salvo.")

            # screenshots em intervalos, pra ver a página "evoluindo"
            for i in range(2, 7):
                page.wait_for_timeout(5000)
                page.screenshot(path=str(out_dir / f"search_{i:02d}_after_{(i-1)*5}s.png"), full_page=True)
                logger.info("Screenshot em +%ss salvo.", (i - 1) * 5)

            (out_dir / "search_final.html").write_text(page.content(), encoding="utf-8")
            try:
                visible = page.locator("body").inner_text()[:3000]
                (out_dir / "search_visible_text.txt").write_text(visible, encoding="utf-8")
            except Exception:
                pass
            logger.info("title final: %r", page.title())

            if keep_open_ms and headful:
                logger.info("Mantendo navegador aberto por %sms pra você olhar manualmente...", keep_open_ms)
                page.wait_for_timeout(keep_open_ms)

    logger.info("Sanity check OK. Veja os arquivos em %s", out_dir)


def crawl_debug(origem: str, destino: str, data: str, adultos: int,
                 headful: bool, slowmo: int, extra_wait_ms: int):
    out_dir = Path("debug_out") / datetime.now().strftime("%Y%m%d_%H%M%S_crawl")
    out_dir.mkdir(parents=True, exist_ok=True)
    responses_log = (out_dir / "responses.jsonl").open("w", encoding="utf-8")

    url = build_url(origem, destino, data, adultos)
    logger.info("URL de busca: %s", url)

    all_responses = []
    journeys_found = []

    with Camoufox(headless=not headful, geoip=False, humanize=True, locale="pt-BR") as browser:
        page = browser.new_page()

        def handle_response(response):
            entry = {
                "url": response.url,
                "status": response.status,
                "content_type": response.headers.get("content-type", ""),
            }
            try:
                body_text = response.text()
            except Exception as e:
                entry["body_error"] = str(e)
                body_text = None

            if body_text is not None:
                try:
                    payload = json.loads(body_text)
                    entry["json"] = True
                    n_groups = sum(1 for _ in _journey_groups(payload))
                    entry["journey_groups"] = n_groups
                    if n_groups:
                        journeys_found.append(payload)
                    # sempre guarda o corpo bruto se for pequeno (ex: os {"success": ...})
                    if len(body_text) < 2000:
                        entry["body"] = payload
                except json.JSONDecodeError:
                    entry["json"] = False
                    entry["body_snippet"] = body_text[:300]

            all_responses.append(entry)
            responses_log.write(json.dumps(entry, ensure_ascii=False) + "\n")
            responses_log.flush()

        page.on("response", handle_response)

        logger.info("Navegando...")
        page.goto(url, wait_until="networkidle", timeout=120000)
        page.screenshot(path=str(out_dir / "screenshot_after_load.png"), full_page=True)

        logger.info("Aguardando %sms extra...", extra_wait_ms)
        page.wait_for_timeout(extra_wait_ms)
        page.screenshot(path=str(out_dir / "screenshot_after_wait.png"), full_page=True)

        # tenta identificar bloqueios comuns (captcha / challenge / erro visível)
        body_text_visible = ""
        try:
            body_text_visible = page.locator("body").inner_text()[:3000]
        except Exception:
            pass

        (out_dir / "page_final.html").write_text(page.content(), encoding="utf-8")
        (out_dir / "visible_text.txt").write_text(body_text_visible, encoding="utf-8")

        for needle in ["captcha", "px-captcha", "are you human", "blocked", "acesso negado", "unusual traffic"]:
            if needle.lower() in body_text_visible.lower() or needle.lower() in page.content().lower():
                logger.warning("POSSÍVEL BLOQUEIO detectado: encontrado texto %r na página", needle)

    responses_log.close()

    logger.info("Total de respostas: %s", len(all_responses))
    logger.info("Respostas JSON: %s", sum(1 for r in all_responses if r.get("json")))
    logger.info("Grupos de jornadas encontrados: %s", len(journeys_found))

    # mostra os bodies pequenos que vieram sem jornadas (ex: os '{"success": ...}')
    suspects = [r for r in all_responses if r.get("json") and not r.get("journey_groups") and "body" in r]
    if suspects:
        logger.info("--- Respostas JSON pequenas sem 'journeys' (prováveis checagens anti-bot) ---")
        for s in suspects[:10]:
            logger.info("%s -> %s", s["url"], s.get("body"))

    if journeys_found:
        flights = parse_tudoazul_flights(max(journeys_found, key=lambda p: len(parse_tudoazul_flights(p))))
        logger.info("Voos normalizados: %s", len(flights))
        (out_dir / "flights.json").write_text(json.dumps(flights, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        logger.warning("Nenhuma jornada encontrada. Investigue responses.jsonl, "
                        "screenshot_after_wait.png e visible_text.txt em %s", out_dir)

    logger.info("Tudo salvo em: %s", out_dir.resolve())


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_sanity = sub.add_parser("sanity", help="Confere se o Camoufox abre e renderiza")
    p_sanity.add_argument("--headful", action="store_true")
    p_sanity.add_argument("--slowmo", type=int, default=0)
    p_sanity.add_argument("--open-search", action="store_true",
                           help="em vez da home, abre direto a URL de busca (precisa de --origem/--destino/--data)")
    p_sanity.add_argument("--origem")
    p_sanity.add_argument("--destino")
    p_sanity.add_argument("--data", help="YYYY-MM-DD")
    p_sanity.add_argument("--adultos", type=int, default=1)
    p_sanity.add_argument("--keep-open", type=int, default=0,
                           help="ms pra manter o navegador aberto no final (só funciona com --headful)")

    p_crawl = sub.add_parser("crawl", help="Roda o crawl da Azul com diagnóstico completo")
    p_crawl.add_argument("--origem", required=True)
    p_crawl.add_argument("--destino", required=True)
    p_crawl.add_argument("--data", required=True, help="YYYY-MM-DD")
    p_crawl.add_argument("--adultos", type=int, default=1)
    p_crawl.add_argument("--headful", action="store_true")
    p_crawl.add_argument("--slowmo", type=int, default=0)
    p_crawl.add_argument("--wait", type=int, default=20000, help="espera extra em ms após o load")

    args = parser.parse_args()

    if args.cmd == "sanity":
        if args.open_search and not (args.origem and args.destino and args.data):
            parser.error("--open-search precisa de --origem, --destino e --data")
        sanity_check(
            headful=args.headful,
            slowmo=args.slowmo,
            open_search=args.open_search,
            origem=args.origem,
            destino=args.destino,
            data=args.data,
            adultos=args.adultos,
            keep_open_ms=args.keep_open,
        )
    elif args.cmd == "crawl":
        crawl_debug(
            origem=args.origem,
            destino=args.destino,
            data=args.data,
            adultos=args.adultos,
            headful=args.headful,
            slowmo=args.slowmo,
            extra_wait_ms=args.wait,
        )


if __name__ == "__main__":
    main()