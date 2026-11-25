# Instalar o Milheirinho Coletor (extensão + ponte)

Guia para colocar uma máquina Windows para coletar os preços da **Smiles**, da **Azul** e da **LATAM**
para o Milheirinho. São duas peças, que rodam juntas na mesma máquina:

| Peça | O que faz |
|---|---|
| **Ponte** (`crawler/run_bridge.py`) | Pega os jobs das filas `crawl.smiles`, `crawl.azul` e `crawl.latam` no RabbitMQ, entrega à extensão e grava o resultado no Postgres. |
| **Extensão** (pasta `extension/`) | Abre a busca da companhia numa aba do Chrome, lê a resposta do site e devolve à ponte. |

A ponte pode rodar em dois lugares:

- **No homelab (recomendado):** ela já vem na stack do Portainer (serviço `bridge`,
  porta 8765). Na extensão, use `http://192.168.1.40:8765` e pule o passo 3.
- **No seu PC:** `python run_bridge.py` (passo 3). Na extensão, use `http://127.0.0.1:8765`.

Use um lugar só: duas pontes dividiriam as filas. Em `http`, a extensão só aceita
`127.0.0.1`, `localhost` ou um IP de rede local (10.x, 172.16–31.x, 192.168.x); um
endereço público precisa de `https`. Quem fala com o RabbitMQ e o Postgres é a ponte.

```
API ─► RabbitMQ (crawl.smiles / azul / latam) ─► ponte ◄──► extensão no Chrome ─► site do programa
                                                │
                                                └─► Postgres (fare_snapshots)
```

## Antes de começar

- Windows com **Google Chrome** (versão 116 ou mais nova).
- **Python 3.9 ou mais novo** (`python --version`).
- **Git**, para baixar o repositório.
- A máquina precisa enxergar o homelab: RabbitMQ em `192.168.1.40:5672` e Postgres
  em `192.168.1.40:5432`. Fora da rede de casa, isso exige VPN (Tailscale, por exemplo).

## 1. Baixar o código e instalar as dependências

No PowerShell:

```powershell
git clone https://github.com/raphaalvarenga/miles-crawlers.git
cd miles-crawlers\crawler
python -m pip install -r requirements.txt
```

## 2. Escolher um token

O token é a senha entre a ponte e a extensão. Pode ser qualquer texto, mas use um
aleatório e guarde-o, porque ele vai nos dois lados:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(24))"
```

Copie o valor sem aspas e sem espaços.

## 3. Rodar a ponte (só se ela não estiver no homelab)

Ainda na pasta `crawler`:

```powershell
$env:BRIDGE_TOKEN = "cole-o-token-aqui"; python run_bridge.py
```

Deixe essa janela aberta: a ponte roda enquanto ela estiver aberta. Ela já vem
apontando para o RabbitMQ e o Postgres do homelab; para outro endereço, defina
`RABBIT_URL` e `DATABASE_URL` antes de rodar.

Para não digitar o token toda vez, salve-o nas variáveis do usuário (uma vez só) e
abra um PowerShell novo:

```powershell
[Environment]::SetEnvironmentVariable("BRIDGE_TOKEN", "cole-o-token-aqui", "User")
```

Rode **uma ponte só** por fila. Duas pontes dividem os jobs entre si, o que dificulta
achar problemas.

## 4. Instalar a extensão

1. Abra `chrome://extensions`.
2. Ligue o **Modo do desenvolvedor** (canto superior direito).
3. Clique em **Carregar sem compactação** e escolha a pasta `miles-crawlers\extension`.
4. A página de opções abre sozinha. Se não abrir: no card do **Milheirinho Coletor**,
   clique em **Detalhes > Opções da extensão**.

Dica: fixe o ícone da arara na barra do Chrome (ícone de quebra-cabeça > alfinete).

## 5. Configurar a extensão

Na página de opções:

| Campo | Valor |
|---|---|
| **Ligado** | marcado |
| **URL da ponte** | `http://192.168.1.40:8765` (homelab) ou `http://127.0.0.1:8765` (PC). Num endereço que não seja `127.0.0.1`/`localhost`, o Chrome pede para liberar o acesso ao clicar em **Salvar**: aceite. |
| **Token** | o mesmo do passo 2 |
| **Companhias** | Smiles, Azul e/ou LATAM |
| **Intervalo mín./máx.** | 8 e 20 s (padrão): espera aleatória entre buscas da mesma companhia |
| **Teto por hora** (ao lado de cada companhia) | Smiles 60, Azul 40, LATAM 40 (padrão) |
| **Abrir a aba em primeiro plano** | desmarcado, para as abas não roubarem o foco |

Cada programa marcado roda em paralelo, na sua própria aba: uma busca da Smiles
não espera a da Azul terminar, e cada um tem o seu teto por hora.

Clique em **Salvar** e depois em **Testar ponte**. A resposta deve começar com
"Ponte ok". Esse teste só confirma que a ponte está no ar, não o token: o token é
conferido no primeiro job (veja o 401 em [Problemas comuns](#problemas-comuns)).
O quadro **Estado** mostra o que a extensão está fazendo.

## 6. Testar

Com a ponte e a extensão ligadas, faça uma busca no site do Milheirinho. Uma aba de
cada programa abre, busca e fecha sozinha em 10 a 30 segundos. No terminal da ponte aparecem
`GET /jobs/next ... 200` e, depois, as tarifas gravadas.

Para testar só a extensão, sem RabbitMQ nem Postgres (pare a ponte antes):

```powershell
python run_bridge.py --once GIG MAD 2026-12-26
python run_bridge.py --once MAD GIG 2026-12-25 --provider latam
python run_bridge.py --once SDU CGH 2026-12-01 --provider smiles
```

O terminal imprime as tarifas encontradas.

Para ouvir só algumas filas, defina antes `$env:BRIDGE_QUEUES = "crawl.azul,crawl.latam"`.
Rode **um consumidor só** por fila: se o worker Camoufox da Smiles estiver ligado
no homelab, tire a Smiles da ponte assim.

## No dia a dia

- O Chrome precisa ficar aberto com a extensão ligada, e a janela da ponte também.
  Pode minimizar.
- **Bloqueio do site:** se a Azul ou a LATAM mostrarem a tela de "comportamento
  incomum", ou a Smiles a de "Validação de segurança" ("Eu sou humano"), a extensão pausa só esse programa, deixa a aba aberta e mostra uma
  notificação. Resolva a verificação na própria aba: a fila volta sozinha. Também dá
  para clicar em **Retomar (tirar pausa)** nas opções.
- **Atualizar a extensão:** depois de `git pull`, abra `chrome://extensions` e clique
  em **Recarregar** (↻) no card. Token e configurações continuam salvos.
  Quando a extensão ganhar um programa novo (como a Smiles na 0.4.0), marque-o nas
  opções e clique em **Salvar**: quem já tinha salvo continua só com os antigos.
- **Atualizar a ponte:** depois de `git pull`, feche a janela e rode a ponte de novo.
- Use um perfil do Chrome **sem login** na Smiles, no TudoAzul ou no LATAM Pass, e mantenha o
  volume baixo. O limite prático é de ~100 buscas por hora por Chrome.

## Problemas comuns

| Sintoma | Causa provável | O que fazer |
|---|---|---|
| Terminal da ponte mostra `GET /jobs/next ... 401` | Token diferente nos dois lados | Rode `"[$env:BRIDGE_TOKEN]"` no terminal da ponte: aspas ou espaços aparecem entre os colchetes. Acerte, reinicie a ponte e salve o mesmo valor na extensão. |
| `Defina BRIDGE_TOKEN` ao iniciar a ponte | Variável não definida neste terminal | Defina o token (passo 3) no mesmo PowerShell em que roda a ponte. |
| **Testar ponte** falha | Ponte parada, URL errada ou acesso negado | No homelab, veja se o serviço `bridge` está rodando no Portainer; no PC, se a janela da ponte está aberta. Se você recusou o acesso ao endereço, clique em **Salvar** de novo e aceite. |
| "URL da ponte recusada" | `http` num endereço público | Em `http` a extensão só aceita `127.0.0.1`, `localhost` ou IP de rede local; outro endereço precisa de `https`. |
| Ponte com `O computador remoto recusou a conexão` | Sem acesso ao RabbitMQ do homelab | Confira a rede (ou a VPN) e se o RabbitMQ está no ar em `192.168.1.40`. |
| Busca fica em "buscando" e nenhuma aba abre | Extensão desligada, companhia desmarcada ou pausada | Veja o quadro **Estado** nas opções; marque **Ligado** e a companhia, ou clique em **Retomar**. |
| A aba abre e fecha, mas nada aparece no site | Página demorou mais que 60 s ou mudou | Veja o erro no terminal da ponte e o job em `crawl_jobs` (coluna `Error`). |

Detalhes de funcionamento e de como adicionar outra companhia estão no
[README da extensão](README.md).
