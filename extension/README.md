# Miles Fetcher — extensão Chrome

Busca a disponibilidade em pontos da Azul a partir de um Chrome real, onde o anti-bot (Akamai) deixa passar, e devolve o JSON da API ao pipeline que já existe.

```
miles-api ──► RabbitMQ crawl.azul ──► run_bridge.py (consumer + HTTP 127.0.0.1:8765)
                                           ▲  GET  /jobs/next      (long-poll)
                                           │  POST /jobs/{id}/result  (JSON da API)
                                     extensão Miles Fetcher
                                           │ abre selecao-voo?...cc=PTS numa aba
                                           ▼
                        hook.js lê a resposta de .../tudoazul/reservation/availability/v6/availability
```

O parse (`tudoazul_parser.py`) e as gravações em `fare_snapshots`, `crawl_jobs` e `search_request_providers` continuam no Python. A API e o frontend não mudam.

## Subir

1. **Ponte**, na mesma máquina do Chrome:
   ```bash
   cd crawler
   pip install -r requirements.txt
   set BRIDGE_TOKEN=um-token-longo-qualquer
   python run_bridge.py
   ```
   Ela consome `crawl.azul` usando `RABBIT_URL` e `DATABASE_URL` (os mesmos padrões do worker). Não deixe o container `worker-azul` (Camoufox) rodando ao mesmo tempo: ele fica atrás do profile `camoufox-azul` no compose.

2. **Extensão**: abra `chrome://extensions`, ligue o *Modo do desenvolvedor*, clique em *Carregar sem compactação* e selecione esta pasta `extension/`. Nas opções, que abrem sozinhas, cole o mesmo token, clique em *Salvar* e depois em *Testar ponte*.

## Testar sem RabbitMQ nem Postgres

```bash
python run_bridge.py --once GIG MAD 2026-12-26
```

Com a extensão ligada, uma aba abre a busca, fecha sozinha e o terminal mostra as tarifas.

## Como funciona

- `hook.js` (mundo da página, `document_start`): embrulha `fetch` e `XMLHttpRequest` e copia o corpo das respostas cuja URL contém `/tudoazul/reservation/availability/`. Não altera nada do que o site recebe.
- `relay.js`: repassa a captura ao background e detecta a tela de bloqueio ("comportamento incomum vindo do seu IP").
- `background.js`: processa um job por vez, com intervalo aleatório (8 a 20 s por padrão) e teto de buscas por hora. A espera máxima da resposta é de 60 s.
- **Bloqueio**: o job falha na hora (o front cai no cache), a aba fica aberta, o provider pausa e aparece uma notificação. Quando a página carrega normal de novo na mesma aba, a fila volta sozinha. Também dá para usar *Retomar* nas opções.

## Limites conhecidos

- A busca expira em 25 s na API (`Search:DefaultTimeoutSeconds`), e a página da Azul leva de 10 a 30 s. Na primeira busca de uma rota o front pode mostrar o cache antigo; o dado novo aparece na próxima consulta.
- Um Chrome processa ~100 buscas/hora no máximo. Mantenha o volume baixo e, se possível, use um perfil **sem** login no TudoAzul.
- `assentos` vem de `remainingSeats` por perna (lugares livres no avião), não de assentos de resgate.

## LATAM depois

1. Adicione um `ProviderSpec("latam", ...)` em `extension_bridge.py`, com `build_url`, o trecho da URL da API e o parser.
2. Adicione o host em `manifest.json` (`host_permissions` e `content_scripts.matches`) e o trecho da URL em `FRAGMENTS` no `hook.js`.
3. Adicione uma entrada em `PROVIDERS` no `config.js`.
4. Rode uma segunda ponte com `QUEUE_NAME=crawl.latam`, ou estenda o consumer para ouvir as duas filas.
