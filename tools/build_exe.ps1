<#
.SYNOPSIS
    Constroi o executavel standalone de Hertz & Beats do zero, numa venv
    de build LIMPA e descartavel -- um unico comando.

.DESCRIPTION
    Orquestra o fluxo completo:
        1. tools/build_engine_wheel.ps1  -- gera wheels/ouroboros_engine-*.whl
        2. Recria .build_venv do zero (nunca reaproveita uma venv velha,
           pra nunca misturar um build anterior com dependencias novas)
        3. pip install -r requirements-frozen.txt (numpy, pygame-ce, pyinstaller)
        4. pip install --no-deps o wheel da engine (ver comentario em
           requirements-frozen.txt sobre por que --no-deps e' necessario)
        5. pyinstaller hertz_build.spec --clean

    Resultado: dist\HertzAndBeats\HertzAndBeats.exe, pronto pra copiar pro
    PC de qualquer jogador -- nenhum Python necessario la.

.EXAMPLE
    .\tools\build_exe.ps1
#>
$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

Write-Host "==> 1/5: construindo o wheel da OuroborosEngine..." -ForegroundColor Cyan
& "$PSScriptRoot\build_engine_wheel.ps1"

$EngineWheel = Get-ChildItem -Path (Join-Path $ProjectRoot "wheels") -Filter "ouroboros_engine-*.whl" | Select-Object -First 1
if (-not $EngineWheel) {
    throw "Nenhum wheel da engine encontrado em wheels\ apos build_engine_wheel.ps1 -- confira a saida acima."
}

$VenvDir = Join-Path $ProjectRoot ".build_venv"
Write-Host "`n==> 2/5: recriando a venv de build limpa em '$VenvDir'..." -ForegroundColor Cyan
if (Test-Path $VenvDir) {
    Remove-Item -Recurse -Force $VenvDir
}
python -m venv $VenvDir

$VenvPython = Join-Path $VenvDir "Scripts\python.exe"

Write-Host "`n==> 3/5: instalando dependencias base (numpy, pygame-ce, pyinstaller)..." -ForegroundColor Cyan
& $VenvPython -m pip install --upgrade pip --quiet
& $VenvPython -m pip install -r (Join-Path $ProjectRoot "requirements-frozen.txt")

Write-Host "`n==> 4/5: instalando o wheel da engine (--no-deps -- ver requirements-frozen.txt)..." -ForegroundColor Cyan
& $VenvPython -m pip install --no-deps $EngineWheel.FullName

Write-Host "`n==> 5/5: rodando o PyInstaller..." -ForegroundColor Cyan
& $VenvPython -m PyInstaller (Join-Path $ProjectRoot "hertz_build.spec") --clean --noconfirm

$ExePath = Join-Path $ProjectRoot "dist\HertzAndBeats\HertzAndBeats.exe"
if (Test-Path $ExePath) {
    Write-Host "`nBuild concluido: $ExePath" -ForegroundColor Green
    Write-Host "Copie a pasta INTEIRA 'dist\HertzAndBeats\' pro PC do jogador."
} else {
    throw "PyInstaller terminou mas '$ExePath' nao existe -- confira a saida acima."
}
