# Deploy no homelab (registry local + swarm no Portainer)

Tudo roda em `192.168.1.40`:

| Serviço | Endereço |
|---|---|
| Registry de imagens | `192.168.1.40:5050` |
| Site (frontend) | http://192.168.1.40:3080 (público: https://milheirinho.com) |
| API | http://192.168.1.40:5000 (público: https://api.milheirinho.com) |
| Worker da Smiles (Camoufox) | desligado (0 réplicas); veja abaixo |

Postgres e RabbitMQ continuam onde já estão. A ponte da extensão (`bridge`) roda na
stack, na porta 8765, e atende Smiles, Azul e LATAM; a extensão no seu Chrome aponta
para `http://192.168.1.40:8765`. Defina `BRIDGE_TOKEN` nas variáveis de ambiente da
stack no Portainer (o mesmo token das opções da extensão).
O worker Camoufox da Smiles fica na stack com 0 réplicas: a Smiles passou a pedir
uma validação de segurança a ele. Para religá-lo, veja o comentário na stack.

## 1. Liberar o registry sem HTTPS (uma vez)

O registry não tem certificado, então o Docker de cada máquina precisa
aceitá-lo explicitamente. Adicione ao `daemon.json`:

```json
{
  "insecure-registries": ["192.168.1.40:5050"]
}
```

- **Seu PC (Docker Desktop):** Settings > Docker Engine, inclua a linha e clique em Apply & restart.
- **Cada nó do swarm (Linux):** edite `/etc/docker/daemon.json` e rode `sudo systemctl restart docker`.

## 2. Subir o registry (uma vez)

No Portainer: **Stacks > Add stack**, nome `registry`, cole
[`registry-stack.yml`](registry-stack.yml) e clique em **Deploy the stack**.

Teste no navegador: http://192.168.1.40:5050/v2/_catalog deve responder `{"repositories":[]}`.

## 3. Gerar e enviar as imagens

No PowerShell, na pasta `miles-crawlers`:

```powershell
.\deploy\build-push.ps1
```

Gera `miles-api`, `milheirinho-frontend`, `miles-smiles-worker` e `miles-bridge`, cada uma com
a tag da versão (data e hora) e `latest`. Para gerar só algumas:
`.\deploy\build-push.ps1 -Only api,frontend`.

O endereço da API fica gravado na imagem do frontend no build
(`-ApiUrl`, padrão `https://api.milheirinho.com`). Quem chama a API é o navegador do
visitante, então use sempre o endereço público: com `http://192.168.1.40:5000` o site
só funciona dentro da sua rede. Se a API mudar de endereço, gere o frontend de novo.

## 4. Subir o Milheirinho

1. No Portainer: **Registries > Add registry > Custom registry**, URL `192.168.1.40:5050`, sem autenticação.
2. **Stacks > Add stack**, nome `milheirinho`, cole [`milheirinho-stack.yml`](milheirinho-stack.yml).
3. Em **Environment variables**, adicione `BRIDGE_TOKEN` com o token da extensão e, se tiver
   mais de uma extensão ligada (outro Chrome, Brave ou perfil), `PREFETCH_COUNT` com o número
   delas (padrão 1). Faça o deploy.

## Atualizar depois de mudar o código

1. `.\deploy\build-push.ps1` (ou `-Only` com o que mudou).
2. No Portainer, abra a stack `milheirinho` > **Update the stack**, com **Re-pull image** marcado.

Para voltar a uma versão anterior, troque `:latest` pela tag da versão no stack.

## Observações

- Só uma ponte: com a do homelab no ar, não rode `run_bridge.py` no PC (as duas
  dividiriam as filas e metade dos jobs iria para a ponte sem extensão).
- Só um consumidor por fila: a ponte e o worker Camoufox não devem ouvir
  `crawl.smiles` ao mesmo tempo, nem dois workers (cuidado com container antigo
  de um deploy que falhou).
- A imagem do worker baixa o navegador do Camoufox no build (~1,3 GB).
- As imagens são `linux/amd64`. Se algum nó do swarm for ARM, é preciso gerar
  com `docker buildx` para as duas arquiteturas.
