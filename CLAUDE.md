# CLAUDE.md — Hertz & Beats

Bullet hell rítmico radial (Defensor) + Arcade 4K, sobre a **OuroborosEngine** (repositório irmão `../OuroborosEngine`, **não vendorizada**). Idioma: PT-BR (código e comentários sem acento, como o resto do repo).

## Comandos

```bash
python -m hertzbeats                      # jogo (ou jogar.bat)
python -m hertzbeats --stage 11           # direto numa fase (índice em data/stages/stages.json)
python -m hertzbeats --stage 4 --section climax --rate 0.75
python -m pytest                          # ~1000 testes headless, ~90 s
python -m ruff check .                    # seleção da engine: E4, E7, E9, F
```

Ferramentas (`tools/`, rodar da raiz):

| Script | Para quê |
| --- | --- |
| `rascunho_beatmap.py` | áudio → rascunhos na DSL (facil/normal/dificil) para revisar à mão |
| `compile_beatmap.py` | `.hbm` (DSL) → `beatmap.json`, com linter de jogabilidade |
| `compor_faixas.py` | renderiza as músicas originais (`--listar`, `--todas`, `--stems`) |
| `generate_stage_assets.py` | re-sintetiza faixas, roda a IA (librosa) ou compila o chart autoral, carimba `track_fingerprint`; `--apenas-autorais` |
| `check_beat_alignment.py` | audita se os charts curados caem na batida |
| `make_beatmap.py` | IA da engine sobre qualquer música (JSON direto) |

## Regras que os testes cobram (e por quê)

- **`.wav` não é versionado; `beatmap.json` é.** Toda faixa de fase vem de uma spec `synth` e é re-sintetizada bit a bit. Mudou a síntese (`demo_track_synth.py`/`original_songs.py`) ou a spec? Rode `python tools/generate_stage_assets.py --force` (ou `--apenas-autorais`) — senão `test_every_versioned_beatmap_matches_the_audio_it_came_from` falha (e o jogo fica fora do tempo sem nenhum outro sintoma).
- **Nada de `np.random` na síntese** (o algoritmo não é contrato entre versões do numpy): ruído vem de `original_songs._hash_noise` ou do seno caótico histórico.
- **Forma plana da spec é bit a bit idêntica à histórica** (tutorial tem chart autoral casado à faixa) — não mexer em `_render_unnormalized` sem regenerar e conferir os hashes.
- **Piso de jogabilidade: 0.30 s entre notas**, pico ≤ 3.2 notas/s em 5 s, média ≤ 2.6/s, primeira nota ≥ `approach_seconds` + 0.3, última ≥ 1 s antes do fim (`test_playability_invariants.py`).
- **Notas na batida**: viés mediano ≤ 3 ms, ≥ 85 % casando com golpe de bateria real (`test_beat_alignment.py`, contra `percussive_onset_times`).
- **Chart autoral nunca é podado nem regerado pela IA** (tutorial, `charts/*.hbm` das trilhas originais). O `.hbm` é a fonte; o JSON é compilado.
- Fases que compartilham `track_path` têm de declarar a **mesma** spec `synth`.

## Onde mexer

- Fase nova: `data/stages/stages.json` (data-driven; campanha nova ganha cabeçalho sozinha).
- Música original nova: parte(s) em `hertzbeats/audio/original_songs.py` (`SONGS`), seções em `stages.json` com `"song"`, rascunho com `rascunho_beatmap.py`, revisão em `charts/`, `"beatmap": {"authored_source": ...}`, depois `generate_stage_assets.py --apenas-autorais`.
- Comportamento compartilhado (ECS, áudio, extratores da IA) começa na **engine**, não aqui. Este repo não modifica a OuroborosEngine.
- `hertzbeats/offline/` nunca é importado pelo runtime (librosa fica fora do processo do jogo).

## Git

Só commit/push quando o Enzo pedir. Changelog em [CHANGELOG.md](CHANGELOG.md).
