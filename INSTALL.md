# Instalando e jogando Hertz & Beats

## Pra quem só quer jogar (nenhum Python necessário)

1. Peça pro desenvolvedor a pasta inteira **`HertzAndBeats`** (a que sai
   de `dist/HertzAndBeats/` depois do build — **não** só o `.exe`
   sozinho: ele depende dos arquivos ao lado, dentro de `_internal/`).
2. Copie essa pasta pra qualquer lugar do seu PC — Área de Trabalho,
   Documentos, um pendrive. Não precisa "instalar" nada, não precisa de
   admin, não mexe no registro do Windows.
3. Dê duplo-clique em **`HertzAndBeats.exe`** dentro da pasta.
4. Se o Windows mostrar a tela azul **"O Windows protegeu o computador"**
   (SmartScreen) — normal pra qualquer `.exe` novo sem assinatura digital
   paga, não é um vírus: clique em **"Mais informações"** e depois em
   **"Executar assim mesmo"**. Só aparece na primeira vez.
5. Na primeira abertura, o jogo sintetiza os SFX/faixas das fases (alguns
   segundos) e grava em `data/sfx/`/`data/tracks/` ao lado do `.exe` —
   próximas aberturas são instantâneas.

**Requisitos:** Windows 10/11 de 64 bits. Nada mais.

Quer importar suas próprias músicas? Solte os arquivos de áudio na pasta
`musicas/` (criada ao lado do `.exe` na primeira execução) ou use o Ctrl+V
de importação direta do YouTube — ambos funcionam sem Python, exatamente
como no jogo rodando do código-fonte.

---

## Para quem vai gerar o executável (desenvolvedor)

Pré-requisito: **Python 3.11+** e os repositórios `Hertz & Beats`/
`OuroborosEngine` lado a lado.

```powershell
cd "Hertz & Beats"
.\tools\build_exe.ps1
```

Termina imprimindo `dist\HertzAndBeats\HertzAndBeats.exe`. Copie a pasta
`dist\HertzAndBeats\` inteira — é isso que você entrega, seguindo a seção
acima. Rode de novo sempre que o código do jogo **ou** da engine mudar.

### O que o script faz

1. `tools\build_engine_wheel.ps1` — constrói um `.whl` de verdade da
   OuroborosEngine a partir de `../OuroborosEngine`, em `wheels/`.
2. Recria `.build_venv\` do zero (venv de build descartável, separada da
   venv de desenvolvimento com a engine em modo editável).
3. `pip install -r requirements-frozen.txt` — `numpy`, `pygame-ce`, `pyinstaller`.
4. Instala o `.whl` da engine com `--no-deps` (ver achado abaixo).
5. `pyinstaller hertz_build.spec --clean` — gera o executável em `dist/`.

### 3 achados reais ao gerar o primeiro build de verdade

Nenhum destes apareceu só lendo o código — só rodando o build e o
executável até o fim, verificando de fato:

1. **`ouroboros-engine` não instala com `pip install` normal.** O
   `pyproject.toml` da engine declara `pygame>=2.5` (o pacote *original*
   do PyPI), mas o código roda sobre `pygame-ce`. Como o `pygame`
   original não tem wheel pronto pras versões recentes de Python nesta
   plataforma, o `pip` tenta compilá-lo do zero e falha (o instalador
   dele chama `pacman`, que só existe no Linux). Resolvido instalando o
   wheel da engine com `--no-deps` e listando `pygame-ce` manualmente —
   `tools/build_exe.ps1` já faz isso.
2. **`collect_data_files("pygame")` quebrava o `COLLECT` final.** Devolve
   pares `(destino, origem)` de 2 elementos nesta versão do PyInstaller,
   mas `a.datas` exige tuplas de 3 (`(destino, origem, tipo)`) — um
   `a.datas += collect_data_files(...)` direto (sem completar o tipo)
   derrubava o build com `ValueError: not enough values to unpack`.
   Corrigido em `hertz_build.spec`.
3. **`config.beatmap_path` nunca passava por `get_resource_path`.** O
   `.exe` abria, sintetizava os SFX/faixas — e travava com
   `FileNotFoundError` ao tentar carregar o beatmap de uma fase curada
   (`BeatmapLoader.load`, na engine). `load_stages` resolve
   `stages_path` (o `stages.json` em si), mas nunca os campos *dentro*
   dele (`beatmap_path`/`track_path` de cada fase) — corrigido nos 2
   pontos reais de consumo (`rhythm_composition_root.py`,
   `stages.py::read_stage_bpm_and_duration`).

Cada um só apareceu rodando o `.exe` gerado de ponta a ponta — nenhum
teste automatizado headless cobria o bundle real do PyInstaller.

### Diagnosticando um build que fecha sozinho

Em `hertz_build.spec`, troque `console=False` por `console=True` na
seção `EXE(...)` e rode `.\tools\build_exe.ps1` de novo — abre uma janela
de console junto do jogo, mostrando o traceback exato.

### "Dieta" do executável

`~100 MB` (incluindo os SFX/faixas já sintetizados no build de teste).
`librosa`/`scipy`/`numba`/`matplotlib`/`pandas`/`PyQt5` são excluídos
explicitamente em `hertz_build.spec` — usados só pela IA offline de
beatmap (`hertzbeats/offline/`), nunca no caminho de execução do jogo
empacotado. `tkinter` é mantido de propósito: `youtube_import.py` usa
`import tkinter` de verdade pra ler o clipboard no Ctrl+V da Importação
Direta.
