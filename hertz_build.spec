# -*- mode: python ; coding: utf-8 -*-
"""
hertz_build.spec -- empacotamento standalone do Hertz & Beats via PyInstaller.

    pip install -e ".[build]"
    pyinstaller hertz_build.spec --clean

Gera `dist/HertzAndBeats/` (modo --onedir, NAO --onefile de proposito --
ver nota abaixo) com `HertzAndBeats.exe`/`HertzAndBeats` + tudo que ele
precisa ao lado.

POR QUE --onedir E NAO --onefile: um `--onefile` extrai o bundle inteiro
pra uma pasta temporaria (`sys._MEIPASS`) TODA VEZ que o jogo abre, e
apaga ao fechar -- com o `ffmpeg` embutido (a dezenas de MB) dentro de
`datas`, isso vira alguns segundos de espera ANTES da Tela de Titulo
aparecer, em TODA execucao. `--onedir` paga esse custo de extracao so
UMA vez (na instalacao/no build) e abre quase instantaneo depois --
melhor experiencia pra um jogo que o jogador abre repetidas vezes.

RESOLUCAO DE CAMINHOS EM RUNTIME: todo caminho relativo consumido pelo
jogo passa por `utils.path_resolver.get_resource_path` (recurso
SOMENTE LEITURA -- `assets/`, `data/stages/stages.json`,
`data/input_bindings/default_keyboard.json`, `bin/ffmpeg*`) ou
`get_writable_data_path` (dado GRAVAVEL -- SFX/faixas sintetizadas,
saves, `musicas/`) -- ver o modulo pra a distincao completa. Isso e'
resolvido NA CARGA/COMPOSICAO (`RhythmCompositionRoot.build`, Tela de
Titulo/Loading), nunca em `ISystem.update()` -- este `.spec` so'
precisa GARANTIR que os arquivos certos existam ao lado do executavel
gerado, a logica de runtime ja esta pronta no codigo.
"""
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

block_cipher = None

# `SPECPATH` e' injetado pelo PyInstaller no namespace de execucao do
# .spec (caminho absoluto da PASTA deste arquivo) -- nunca `__file__`
# (um .spec nao e' importado como modulo comum).
PROJECT_ROOT = Path(SPECPATH)

a = Analysis(
    ["hertzbeats/__main__.py"],
    pathex=[str(PROJECT_ROOT)],  # garante que `utils.path_resolver`/`hertzbeats` sejam encontrados na analise
    binaries=[],
    datas=[
        # Pilar 3 do pedido: assets/, bin/ (pasta inteira cada -- o
        # PyInstaller copia recursivamente quando a origem e' um
        # diretorio) e o stages.json isolado.
        (str(PROJECT_ROOT / "assets"), "assets"),
        (str(PROJECT_ROOT / "bin"), "bin"),
        (str(PROJECT_ROOT / "data" / "stages" / "stages.json"), "data/stages"),
        # Mesma categoria (recurso curado/SOMENTE LEITURA) do stages.json
        # acima, so' nao foi pedido explicitamente no briefing -- sem
        # isso o 1o `input_provider.load_bindings(...)`/
        # `HertzConfig.from_json(...)` real do build vai falhar com
        # FileNotFoundError. Descomentar antes de gerar um build real:
        # (str(PROJECT_ROOT / "data" / "input_bindings" / "default_keyboard.json"), "data/input_bindings"),
        # (str(PROJECT_ROOT / "data" / "config" / "hertz_beats.config.json"), "data/config"),
        # (str(PROJECT_ROOT / "data" / "beatmaps"), "data/beatmaps"),  # so as 4 fases curadas -- NUNCA a subpasta data/beatmaps/user/ (gravavel, ver get_writable_data_path)
    ],
    hiddenimports=[
        # pygame-ce/numpy tem hooks proprios que o PyInstaller ja
        # descobre sozinho na maioria dos casos. Se o .exe gerado
        # fechar sozinho ao abrir (sem stacktrace com console=False),
        # rode com console=True abaixo pra ver o ModuleNotFoundError
        # exato e adicionar o modulo faltante aqui.
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Dieta: librosa/scipy carregam esse ecossistema de VISUALIZACAO
        # (plot/notebook) so' como dependencia OPCIONAL de submodulos
        # que este jogo nunca importa (so' HPSS/onset/beat-tracking
        # puros, numpy/scipy) -- cada um tira dezenas de MB do build.
        "matplotlib",
        "IPython",
        "jupyter",
        "notebook",
        "pandas",
        "PyQt5",
        # NAO EXCLUA "tkinter": `youtube_import.read_system_clipboard`
        # usa `import tkinter` DE VERDADE pra ler o clipboard no Ctrl+V
        # da Importacao Direta -- excluir quebraria essa feature em
        # silencio (ImportError so' na hora de colar uma URL, nao no
        # build). Unico ajuste real sobre a lista pedida no briefing.
    ],
    noarchive=False,
    cipher=block_cipher,
)

# Dados de runtime do proprio pygame-ce (fonte padrao interna, etc.) --
# normalmente ja cobertos pelo hook oficial, mas incluido explicitamente
# aqui como salvaguarda pra um build --onedir nunca ficar sem eles.
a.datas += collect_data_files("pygame")

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="HertzAndBeats",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # trocar pra True temporariamente se o .exe fechar sozinho sem explicar por que
    icon=str(PROJECT_ROOT / "assets" / "hertz_beats.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="HertzAndBeats",
)
