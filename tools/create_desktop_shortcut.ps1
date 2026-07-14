# Cria/atualiza o atalho "Hertz & Beats" na area de trabalho do usuario.
# O atalho roda o jogo via pythonw.exe (sem janela de console), com o
# diretorio de trabalho na raiz do repositorio e o icone do jogo.
#
# Uso (da raiz do repositorio):
#   powershell -ExecutionPolicy Bypass -File tools\create_desktop_shortcut.ps1

$root = Split-Path -Parent $PSScriptRoot

$python = (Get-Command python).Source
$pythonw = Join-Path (Split-Path -Parent $python) 'pythonw.exe'
if (-not (Test-Path $pythonw)) { $pythonw = $python }

$desktop = [Environment]::GetFolderPath('Desktop')
$shortcutPath = Join-Path $desktop 'Hertz & Beats.lnk'

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $pythonw
$shortcut.Arguments = '-m hertzbeats'
$shortcut.WorkingDirectory = $root
$shortcut.Description = 'Hertz & Beats - Bullet Hell Ritmico sobre a Ouroboros Engine'

$icon = Join-Path $root 'assets\hertz_beats.ico'
if (Test-Path $icon) { $shortcut.IconLocation = "$icon,0" }

$shortcut.Save()
Write-Host "Atalho criado: $shortcutPath"
Write-Host "  alvo: $pythonw -m hertzbeats"
Write-Host "  pasta de trabalho: $root"
