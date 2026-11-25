# Changelog

Mudanças notáveis do Hertz & Beats. O histórico anterior a este arquivo está no `git log` e nas seções do [README](README.md).

## [0.1.0] — 2026-11-25 (pré-lançamento)

Primeira release, com o `.exe` (pasta `HertzAndBeats/` num `.zip`). Os charts das 3 trilhas originais foram revisados à mão, mas ainda não ajustados jogando.

### Mudado
- Dependência da OuroborosEngine fixada na tag `v0.4.0` (antes seguia o `main`).


### Adicionado
- **Campanha `trilhas_originais`**: 3 fases com músicas **originais** sintetizadas, de estilos diferentes, e charts autorais revisados à mão.
  - **1 · Maré Lenta** — 76 BPM, downtempo/lo-fi (piano elétrico FM, sino, boom-bap). 57 notas, ~1.1/s.
  - **2 · Contratempo** — 112 BPM, funk em tresillo (palmas, slap, metais no contratempo). 105 notas, ~1.6/s. Stems vocais (`karaoke_sync`).
  - **3 · Hiperpulso** — 170 BPM, drum'n'bass (two-step, reese, arpejo, supersaw). 131 notas, ~2.0/s.
- `hertzbeats/audio/original_songs.py`: compositor das músicas (instrumentos, partitura por parte, stems, verdade fundamental pela mesma partitura sem renderizar). Ruído determinístico por hash inteiro.
- Forma nova de `synth` em `stages.json`: `{"bpm", "song", "sections": [{"name", "bars", "part", "lead"}]}`. `demo_track_synth.synthesize_from_spec` despacha as 3 formas; re-síntese, stems, Escala de Tempo e Treino por Seção funcionam sem nada específico.
- **Geração assistida de beatmap** — `tools/rascunho_beatmap.py` + `hertzbeats/offline/beatmap_assist.py`: áudio → rascunhos na DSL em `facil`/`normal`/`dificil` (aninhados, com piso de gap e teto de pico), BPM/onsets por librosa ou por um detector em numpy (só WAV), ataque refinado no sinal bruto (viés −0.7 ms), `--bpm`/`--offset` para corrigir a detecção.
- `tools/compor_faixas.py`: lista/renderiza as músicas originais (com stems e escala de tempo).
- DSL: diretiva `offset <segundos>` (onde cai o `1:1` no áudio).
- `tools/generate_stage_assets.py`: fases com `"beatmap": {"authored_source": "charts/x.hbm"}` são **compiladas** (linter + digital da faixa) em vez de passar pela IA; `--apenas-autorais` dispensa librosa.
- Testes: `tests/test_original_stages.py` e `tests/test_beatmap_assist.py` (63 novos; suíte em 1006).
- `[tool.ruff]` no `pyproject.toml` (seleção da engine: E4, E7, E9, F) — `ruff check .` verde pela primeira vez.
- `CLAUDE.md` do projeto.

### Corrigido
- **Tela de Calibração levantava `NameError` no primeiro toque**: `_CALIBRATION_ONTIME_THRESHOLD_SECONDS` tinha sido apagada por engano no commit do gate de dev (`b422ba3`). Achado pelo ruff (F821).
- Lint: imports mortos, variável não usada em `parry_impact_system`, nomes ambíguos/`;` em testes.
