<#
.SYNOPSIS
    Constroi um wheel NAO-editavel da OuroborosEngine (repo irmao,
    "../OuroborosEngine") e o deixa em wheels/.

.DESCRIPTION
    Hertz & Beats consome a engine via `pip install -e ../OuroborosEngine`
    em desenvolvimento (mesmo com `pyproject.toml` declarando um
    `ouroboros-engine @ git+https://...` -- na pratica, a instalacao
    local editavel sobrescreve isso) -- pratico pra editar os dois repos
    junto, mas ruim pra empacotar: um install editavel vira um
    redirecionamento (arquivo .pth) pra pasta de codigo-fonte, nao
    arquivos de pacote de verdade, e o PyInstaller (que anda o grafo de
    imports sobre o que esta em site-packages) pode nao seguir esse
    redirecionamento -- ou pior, embutir um caminho absoluto da SUA
    maquina dentro do executavel.

    Este script gera um wheel de verdade (arquivos reais, sem
    redirecionamento) a partir do estado ATUAL do codigo da engine, para
    ser instalado (nao-editavel) numa venv de build limpa antes de rodar
    o PyInstaller -- ver `requirements-frozen.txt` e `hertz_build.spec`.

.EXAMPLE
    .\tools\build_engine_wheel.ps1
    # gera wheels\ouroboros_engine-<versao>-py3-none-any.whl

.NOTES
    Rode de novo sempre que o codigo da engine mudar E voce for gerar um
    build novo do executavel -- o wheel gerado e um SNAPSHOT do estado
    local da engine no instante em que este script roda, nunca
    atualizado sozinho depois.
#>
$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$EngineSource = Join-Path $ProjectRoot "..\OuroborosEngine"
$WheelsDir = Join-Path $ProjectRoot "wheels"

if (-not (Test-Path $EngineSource)) {
    throw "Repo irmao da engine nao encontrado em '$EngineSource' -- este script assume o mesmo layout de pastas do README (Hertz & Beats e OuroborosEngine lado a lado)."
}

New-Item -ItemType Directory -Force -Path $WheelsDir | Out-Null

Get-ChildItem -Path $WheelsDir -Filter "ouroboros_engine-*.whl" -ErrorAction SilentlyContinue | Remove-Item -Force

Write-Host "Construindo wheel da OuroborosEngine a partir de '$EngineSource'..."
python -m pip wheel $EngineSource -w $WheelsDir --no-deps

$Built = Get-ChildItem -Path $WheelsDir -Filter "ouroboros_engine-*.whl" | Select-Object -First 1
if (-not $Built) {
    throw "`pip wheel` terminou sem erro mas nenhum .whl da engine apareceu em '$WheelsDir' -- confira a saida acima."
}

Write-Host ""
Write-Host "Wheel gerado: $($Built.FullName)" -ForegroundColor Green
Write-Host "Normalmente voce nao chama este script direto -- rode .\tools\build_exe.ps1"
Write-Host "pra fazer o build completo do executavel (ele chama este script sozinho)."
