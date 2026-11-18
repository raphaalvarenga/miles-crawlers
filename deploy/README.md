# Deploy no homelab (registry local + swarm no Portainer)

Tudo roda em `192.168.1.40`:

| Serviço | Endereço |
|---|---|
| Registry de imagens | `192.168.1.40:5050` |
| Site (frontend) | http://192.168.1.40:3000 |
| API | http://192.168.1.40:5000 |
| Worker da Smiles | sem porta (consome `crawl.smiles`) |

Postgres e RabbitMQ continuam onde já estão. A ponte da Azul/LATAM
(`crawler/run_bridge.py`) continua no seu PC, junto com o Chrome e a extensão.

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

Gera `miles-api`, `milheirinho-frontend` e `miles-smiles-worker`, cada uma com
a tag da versão (data e hora) e `latest`. Para gerar só algumas:
`.\deploy\build-push.ps1 -Only api,frontend`.

O endereço da API fica gravado na imagem do frontend no build
(`-ApiUrl`, padrão `http://192.168.1.40:5000`). Se a API mudar de endereço,
gere o frontend de novo.

## 4. Subir o Milheirinho

1. No Portainer: **Registries > Add registry > Custom registry**, URL `192.168.1.40:5050`, sem autenticação.
2. **Stacks > Add stack**, nome `milheirinho`, cole [`milheirinho-stack.yml`](milheirinho-stack.yml) e faça o deploy.

## Atualizar depois de mudar o código

1. `.\deploy\build-push.ps1` (ou `-Only` com o que mudou).
2. No Portainer, abra a stack `milheirinho` > **Update the stack**, com **Re-pull image** marcado.

Para voltar a uma versão anterior, troque `:latest` pela tag da versão no stack.

## Observações

- Quando o worker da Smiles estiver no swarm, pare o que roda no seu PC
  (`python run_worker.py`); os dois podem coexistir, mas dividem a fila.
- A imagem do worker baixa o navegador do Camoufox no build (~1,3 GB).
- As imagens são `linux/amd64`. Se algum nó do swarm for ARM, é preciso gerar
  com `docker buildx` para as duas arquiteturas.
