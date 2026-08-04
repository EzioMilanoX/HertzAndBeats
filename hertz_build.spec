# -*- mode: python ; coding: utf-8 -*-
"""
hertz_build.spec -- empacotamento standalone do Hertz & Beats via PyInstaller.

FLUXO COMPLETO, um unico comando (venv de build LIMPA -- nunca a venv de
desenvolvimento com a engine em modo editavel):

    .\tools\build_exe.ps1

(o que esse script faz passo a passo, se preferir rodar na mao ou algo
falhar no meio -- ver `requirements-frozen.txt` pro motivo do
`--no-deps` no passo 4):
    1. tools\build_engine_wheel.ps1        -> wheels\ouroboros_engine-*.whl
    2. python -m venv .build_venv
    3. .build_venv\Scripts\pip install -r requirements-frozen.txt
    4. .build_venv\Scripts\pip install --no-deps wheels\ouroboros_engine-*.whl
    5. .build_venv\Scripts\pyinstaller hertz_build.spec --clean

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
        # assets/, bin/ (pasta inteira cada -- o PyInstaller copia
        # recursivamente quando a origem e' um diretorio; bin/ so' tem
        # LEIA-ME.txt hoje, sem ffmpeg real, ver bin/LEIA-ME.txt) e o
        # stages.json isolado.
        (str(PROJECT_ROOT / "assets"), "assets"),
        (str(PROJECT_ROOT / "bin"), "bin"),
        (str(PROJECT_ROOT / "data" / "stages" / "stages.json"), "data/stages"),
        (str(PROJECT_ROOT / "data" / "input_bindings" / "default_keyboard.json"), "data/input_bindings"),
        # SO' o JSON curado -- NUNCA a pasta `data/config/` inteira, que
        # tambem tem `user_settings.json`/`player_progress.json`/
        # `player_lifetime_stats.json` (save/config LOCAL desta maquina
        # de build, gitignored -- embutir eles vazaria o progresso do
        # DESENVOLVEDOR pro jogador, alem de nunca ser regravado depois).
        (str(PROJECT_ROOT / "data" / "config" / "hertz_beats.config.json"), "data/config"),
        # SO' as 4 fases curadas, uma por uma -- NUNCA `data/beatmaps/`
        # inteira, que tambem contem `data/beatmaps/user/` (beatmaps das
        # musicas importadas NESTA maquina, gravavel/pessoal, ver
        # get_writable_data_path).
        (str(PROJECT_ROOT / "data" / "beatmaps" / "stage1_pulso_leve.beatmap.json"), "data/beatmaps"),
        (str(PROJECT_ROOT / "data" / "beatmaps" / "stage2_batida_franca.beatmap.json"), "data/beatmaps"),
        (str(PROJECT_ROOT / "data" / "beatmaps" / "stage3_sobrecarga.beatmap.json"), "data/beatmaps"),
        (str(PROJECT_ROOT / "data" / "beatmaps" / "tutorial.beatmap.json"), "data/beatmaps"),
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
#
# `collect_data_files` devolve pares (dest, src) de 2 elementos, mas
# `a.datas` exige tuplas de 3 (dest, src, typecode) -- um `+=` direto
# (sem completar o typecode) faz o COLLECT() final falhar tentando
# desempacotar essas entradas (`ValueError: not enough values to
# unpack`), erro real encontrado rodando o build pela 1a vez.
a.datas += [(dest, src, "DATA") for dest, src in collect_data_files("pygame")]

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
