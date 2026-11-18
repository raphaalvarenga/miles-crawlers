# Milheirinho Coletor — extensão Chrome

Busca a disponibilidade em pontos/milhas da Smiles, da Azul e da LATAM a partir de um Chrome real, onde o anti-bot deixa passar, e devolve o JSON da API ao pipeline que já existe.

```
miles-api ──► RabbitMQ crawl.smiles ─┐
              RabbitMQ crawl.azul  ─┤
              RabbitMQ crawl.latam ─┴─► run_bridge.py (consumer + HTTP 127.0.0.1:8765)
                                           ▲  GET  /jobs/next?provider=…  (long-poll)
                                           │  POST /jobs/{id}/result      (JSON da API)
                                     extensão Milheirinho Coletor
                                           │ abre a página de busca numa aba
                                           ▼
                        hook.js lê a resposta da API de disponibilidade:
                          Azul:  .../tudoazul/reservation/availability/v6/availability
                          LATAM: .../bff/air-offers/v2/offers/search/redemption
                          Smiles: .../v1/airlines/search?
```

O parse (`tudoazul_parser.py`, `latam_parser.py`) e as gravações em `fare_snapshots`, `crawl_jobs` e `search_request_providers` continuam no Python. A API e o frontend não mudam.

## Subir

1. **Ponte**, na mesma máquina do Chrome:
   ```bash
   cd crawler
   pip install -r requirements.txt
   set BRIDGE_TOKEN=um-token-longo-qualquer
   python run_bridge.py
   ```
   Ela consome `crawl.azul` e `crawl.latam` usando `RABBIT_URL` e `DATABASE_URL` (os mesmos padrões do worker). Para ouvir só uma fila: `set BRIDGE_QUEUES=crawl.azul`. Não deixe o container `worker-azul` (Camoufox) rodando ao mesmo tempo: ele fica atrás do profile `camoufox-azul` no compose.

2. **Extensão**: abra `chrome://extensions`, ligue o *Modo do desenvolvedor*, clique em *Carregar sem compactação* e selecione esta pasta `extension/`. Nas opções, que abrem sozinhas, cole o mesmo token, marque as companhias, clique em *Salvar* e depois em *Testar ponte*. Ao atualizar a extensão, clique em *Recarregar* em `chrome://extensions` e confira as companhias marcadas (quem já tinha salvo só a Azul precisa marcar a LATAM).

## Testar sem RabbitMQ nem Postgres

```bash
python run_bridge.py --once GIG MAD 2026-12-26
python run_bridge.py --once MAD GIG 2026-12-25 --provider latam
```

Com a extensão ligada, uma aba abre a busca, fecha sozinha e o terminal mostra as tarifas.

## Como funciona

- `hook.js` (mundo da página, `document_start`): embrulha `fetch` e `XMLHttpRequest` e copia o corpo das respostas cuja URL contém `/tudoazul/reservation/availability/`. Não altera nada do que o site recebe.
- `relay.js`: repassa a captura ao background e detecta a tela de bloqueio ("comportamento incomum vindo do seu IP").
- `background.js`: um laço por programa, em paralelo: uma busca da Smiles e uma da Azul podem rodar ao mesmo tempo, cada uma na sua aba, mas cada programa faz um job por vez. Entre duas buscas do mesmo programa há um intervalo aleatório (8 a 20 s por padrão); o teto de buscas por hora vale para o Chrome todo. A espera máxima da resposta é de 60 s. Como os laços gravam o estado ao mesmo tempo, toda alteração passa por `updateRuntime`, que aplica uma de cada vez.
- **Bloqueio**: o job falha na hora (o front cai no cache), a aba fica aberta, só aquele programa pausa (os outros seguem) e aparece uma notificação. Quando a página carrega normal de novo na mesma aba, a fila volta sozinha. Também dá para usar *Retomar* nas opções.

## Limites conhecidos

- A busca expira em 25 s na API (`Search:DefaultTimeoutSeconds`), e a página da Azul leva de 10 a 30 s. Na primeira busca de uma rota o front pode mostrar o cache antigo; o dado novo aparece na próxima consulta.
- Um Chrome processa ~100 buscas/hora no máximo, somando as companhias. Mantenha o volume baixo e, se possível, use um perfil **sem** login no TudoAzul.
- Azul: `assentos` vem de `remainingSeats` por perna (lugares livres no avião), não de assentos de resgate.
- LATAM: a busca com `cabin=Economy` já traz as brands de Business, então uma busca grava as duas cabines, com a brand mais barata de cada uma (as outras ficam em `tarifas` no payload). A API pagina em 50 itinerários e só a primeira página é lida. A tela de bloqueio da LATAM ainda não foi vista; só "Access Denied" é reconhecido, e outro bloqueio vira timeout de 60 s.

## Outra companhia

1. Escreva o parser em `crawler/src/worker/<cia>_parser.py` e adicione um `ProviderSpec` em `extension_bridge.py`, com `build_url`, o trecho da URL da API e o parser.
2. Adicione o host em `manifest.json` (`host_permissions` e `content_scripts.matches`) e o trecho da URL em `FRAGMENTS` no `hook.js`.
3. Adicione uma entrada em `PROVIDERS` no `config.js`.
4. A ponte passa a ouvir `crawl.<cia>` sozinha (a fila precisa existir no RabbitMQ).
