<#
.SYNOPSIS
  Gera as imagens do Milheirinho e envia ao registry do homelab.

.DESCRIPTION
  Espera os três repositórios lado a lado:
    Projects\miles-api, Projects\miles-frontend, Projects\miles-crawlers

  Cada imagem recebe duas tags: a versão (padrão: data e hora) e "latest".
  O stack do Portainer usa "latest"; a tag de versão serve para voltar atrás.

.EXAMPLE
  .\deploy\build-push.ps1
  .\deploy\build-push.ps1 -Only api,frontend
  .\deploy\build-push.ps1 -NoPush        # só gera as imagens
#>
param(
    [string]$Registry = "192.168.1.40:5050",
    [string]$ApiUrl = "http://192.168.1.40:5000",
    [string]$Tag = (Get-Date -Format "yyyyMMdd-HHmm"),
    [ValidateSet("api", "frontend", "smiles-worker", "bridge")]
    [string[]]$Only = @("api", "frontend", "smiles-worker", "bridge"),
    [switch]$NoPush
)

$ErrorActionPreference = "Stop"
$crawlers = Split-Path $PSScriptRoot -Parent
$projects = Split-Path $crawlers -Parent

$images = @(
    @{ Key = "api"; Name = "miles-api"; Context = Join-Path $projects "miles-api\Miles.Api"; Args = @() },
    @{ Key = "frontend"; Name = "milheirinho-frontend"; Context = Join-Path $projects "miles-frontend";
       Args = @("--build-arg", "NEXT_PUBLIC_API_BASE_URL=$ApiUrl") },
    @{ Key = "smiles-worker"; Name = "miles-smiles-worker"; Context = $crawlers;
       Args = @("-f", (Join-Path $crawlers "crawler\Dockerfile")) },
    @{ Key = "bridge"; Name = "miles-bridge"; Context = $crawlers;
       Args = @("-f", (Join-Path $crawlers "crawler\Dockerfile.bridge")) }
)

function Invoke-Docker {
    param([string[]]$Arguments)
    Write-Host "> docker $($Arguments -join ' ')" -ForegroundColor DarkGray
    # O docker escreve o progresso no stderr; no PowerShell 5.1 isso vira erro quando a
    # saída é redirecionada. Vale só o código de saída.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & docker @Arguments 2>&1 | ForEach-Object { "$_" }
    } finally {
        $ErrorActionPreference = $previous
    }
    if ($LASTEXITCODE -ne 0) { throw "docker $($Arguments[0]) falhou (código $LASTEXITCODE)" }
}

foreach ($image in $images | Where-Object { $Only -contains $_.Key }) {
    if (-not (Test-Path $image.Context)) { throw "Pasta não encontrada: $($image.Context)" }
    $versioned = "$Registry/$($image.Name):$Tag"
    $latest = "$Registry/$($image.Name):latest"

    Write-Host "`n== $($image.Name) ==" -ForegroundColor Cyan
    Invoke-Docker (@("build", "--pull", "-t", $versioned, "-t", $latest) + $image.Args + @($image.Context))

    if (-not $NoPush) {
        Invoke-Docker @("push", $versioned)
        Invoke-Docker @("push", $latest)
    }
}

Write-Host "`nPronto. Tag desta versão: $Tag" -ForegroundColor Green
if (-not $NoPush) {
    Write-Host "No Portainer: Stacks > milheirinho > Update the stack (marque 'Re-pull image')."
}
