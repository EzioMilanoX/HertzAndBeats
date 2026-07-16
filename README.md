# Hertz & Beats

**Bullet Hell Rítmico radial ("Defesa de Perímetro") construído sobre a [Ouroboros Engine](https://github.com/EzioMilanoX/OuroborosEngine).**

Você é o núcleo no centro da arena. Ameaças nascem na borda da tela e voam em sua direção com velocidade matematicamente calculada para tocar o seu anel **exatamente no milissegundo da batida** extraída da música pela IA offline da engine (librosa). Mire em 360º com o mouse e atire no ritmo — ou atravesse o impacto com um Dash de i-frames.

Na pegada de *Just Shapes & Beats* / *BPM: Bullets Per Minute*.

## Modos de jogo

A IA dita o **tempo** (o mesmo `beatmap.json`); o modo dita a **interpretação espacial e de input**:

| Modo | Estilo | Como se joga |
| --- | --- | --- |
| **Defensor** | BPM / Metal: Hellsinger | Núcleo fixo, ameaças radiais 360º; mire com o mouse e atire quando a ameaça tocar sua mira. Atirar **fora do tempo é misfire** e zera o combo. |
| **Sobrevivência** | Just Shapes & Beats | Mova-se livre (WASD); paredes de som varrem a arena cruzando o centro na batida. **Não há ataque**: o Dash (Espaço, i-frames) atravessa as paredes no ritmo — atravessar ou esquivar pontua. |
| **Arcade 4K** | FNF / VSRG | 4 colunas fixas; notas caem até a linha de julgamento. Aperte **D F J K** na coluna certa, na janela certa. Ghost taps não punem. |
| **Híbrido** | Defensor + Sobrevivência | As **seções da música alternam** os modos: atire nas batidas das seções pares, dashe pelas ondas das ímpares. Você move o corpo (WASD) e mira a torreta do núcleo com o mouse — o escudo móvel do núcleo. |

## Como jogar

| Ação | Controle |
| --- | --- |
| Mira 360º (Defensor) | Mouse (direção a partir do núcleo) |
| Atirar / Parry (Defensor) | Botão esquerdo do mouse |
| Mover (Sobrevivência) | W A S D |
| Colunas (Arcade 4K) | D F J K |
| Dash (i-frames) | Espaço |
| Menu: escolher fase | Setas ↑/↓, ENTER (ou clique) para jogar |
| Pausar / retomar | ESC |
| Após derrota/vitória | R repete a fase, ENTER vai à próxima, M volta ao menu |

O fluxo da partida: **menu de fases → jogando ⇄ pausado → GAME OVER** (vida zerada) ou **FASE CONCLUÍDA** (todas as ameaças resolvidas). Pausar congela a música — e como todo o gameplay rítmico lê exclusivamente o relógio de áudio, o jogo inteiro congela em sincronia e retoma do ponto exato, sem drift.

## Fases

Um tutorial e três fases padrões, definidos em [data/stages/stages.json](data/stages/stages.json) (data-driven — adicione as suas):

| Fase | Modo | Faixa | Dificuldade |
| --- | --- | --- | --- |
| **Tutorial** | Defensor | 80 BPM, `calm` | Guiado por instruções na tela; 6 de vida, sem misfire |
| **1 · Pulso Leve** | Defensor | 100 BPM, `calm` | Aproximação 2.4s, 4 de vida, cone de mira 40° |
| **2 · Batida Franca** | Defensor | 128 BPM, `standard` | Afinação padrão (2.0s, 3 de vida, 35°) |
| **3 · Sobrecarga** | Defensor | 150 BPM, `intense`, drops a cada 4 compassos | Aproximação 1.6s, cone 30° |
| **4 · Ondas de Choque** | Sobrevivência | **mesmo beatmap da fase 1** | 4 de vida, varreduras a cada batida forte |
| **5 · Arcade 4K** | Arcade | **mesmo beatmap da fase 2** | Notas D/F/J/K, queda em 1.8s |
| **6 · Híbrido** | Defensor+Sobrevivência | **mesmo beatmap da fase 3** | Seções de 9.6s alternando tiro e dash |

As fases 4 e 5 consomem **os mesmos `beatmap.json`** das fases 1 e 2 — a demonstração literal da tese: o modo é só outra interpretação espacial do mesmo tempo extraído pela IA. Trocar o modo de uma fase é uma linha no JSON: `"overrides": { "game_mode": "survival" }`.

O **tutorial** ensina jogando: faixas de instrução aparecem no topo da tela em sincronia com a música (mova a mira → atire quando a ameaça tocar o anel → janelas PERFECT/GOOD → uma onda de 3 ameaças simultâneas para aprender o Dash → sequência final). O beatmap do tutorial é **autoral** (timing didático, em [data/beatmaps/tutorial.beatmap.json](data/beatmaps/tutorial.beatmap.json)) — o `generate_stage_assets.py` preserva ele e só regenera os das fases via IA. Por baixo, é o mesmo motor: um `TutorialSystem` zero-GC avança um cursor de passos contra o `IAudioClock` (a mesma base de tempo do spawner) e troca a textura de um sprite-banner pré-renderizado; os passos vêm do JSON da fase (`tutorial_steps`), então qualquer fase pode virar um tutorial.

Cada fase tem sua faixa sintetizada deterministicamente (o `.wav` não é versionado; é reconstruído bit a bit no primeiro uso) e seu beatmap extraído pela IA offline da engine — 107, 180 e 168 ameaças respectivamente. Para regenerar tudo: `python tools/generate_stage_assets.py --force` (requer `librosa`).

- **PERFECT** — tiro com \|delta\| ≤ 50 ms da batida (300 pts)
- **GOOD** — \|delta\| ≤ 100 ms (100 pts)
- **MISS** — a ameaça passou 150 ms do tempo, ou atingiu o núcleo (quebra o combo e custa vida)
- **Dash no tempo certo** — a ameaça atravessa você sem dano e sem quebrar o combo

O visual e a mecânica coincidem: a borda da ameaça toca o anel de julgamento do núcleo no instante exato da batida — atire quando encostar.

## Rodando

Requisitos: Python ≥ 3.11, `numpy`, `pygame-ce` e a Ouroboros Engine.

```bash
# com o repositório da engine clonado ao lado (recomendado para dev):
pip install -e ../OuroborosEngine --no-deps
pip install numpy pygame-ce

# ou direto do GitHub:
pip install "ouroboros-engine @ git+https://github.com/EzioMilanoX/OuroborosEngine.git"

# na raiz deste repositório:
python -m hertzbeats
```

Alternativas práticas no Windows:

- **`jogar.bat`** (na raiz) — duplo clique roda o jogo com console (mostra o placar final e eventuais erros);
- **Atalho na área de trabalho** — rode uma vez `powershell -ExecutionPolicy Bypass -File tools\create_desktop_shortcut.ps1` e um atalho "Hertz & Beats" (com ícone, sem janela de console) aparece na sua área de trabalho.

As faixas das fases são **re-sintetizadas deterministicamente** (numpy puro) quando necessário — os `.wav` não são versionados, mas os `beatmap.json` extraídos deles pela IA são, então o jogo abre pronto para jogar.

Se o áudio parecer adiantado/atrasado, calibre a latência de saída: `python -m hertzbeats --latency 0.10`.

## Use a sua própria música

O pipeline offline de IA da engine (BPM + onsets via librosa) gera o beatmap de qualquer faixa:

```bash
pip install librosa  # só para a etapa offline, nunca no jogo
python tools/make_beatmap.py --audio minha_musica.mp3 \
    --output data/beatmaps/minha.beatmap.json --track-id minha
```

Depois adicione uma entrada em `data/stages/stages.json` apontando `track_path`/`beatmap_path` para os novos arquivos (sem o bloco `synth` — a faixa é sua) e ela aparece no menu de fases. A curadoria pós-IA do jogo descarta onsets a menos de 200 ms do anterior (janelas de julgamento nunca se sobrepõem) e converte picos de energia (strength ≥ 0.8) em **ameaças pesadas**.

## Arquitetura

Tudo é SoA (Structure of Arrays) sobre as `ComponentPool` da engine — nenhum objeto "HitEvent"/"Threat" Python é instanciado no loop de gameplay (Zero-GC).

Ordem exata de execução registrada por `hertzbeats/bootstrap/rhythm_composition_root.py` (o "cimento" entre engine e jogo):

1. **PlayerInputSystem** — lê teclado/mouse: mira 360º, Dash e i-frames
2. **RadialRhythmSpawnerSystem** — *é* o `RhythmSpawnerSystem` da engine (cursor monotônico + compensação de latência intactos), estendido para materializar a ameaça na borda com velocidade calculada para o impacto cravar na batida
3. **JudgmentSystem** — varre o RhythmThreatPool com `|target_hit_time_sec − IAudioClock.now|` vetorizado em buffers pré-alocados; janelas Perfect/Good/Miss; marca `is_hit` e atualiza `score`/`combo_count`
4. **PhysicsSystem** (engine) — integra as ameaças não destruídas
5. **CollisionSystem** (engine) + **CoreDamageSystem** — detecta a ameaça que passou do ponto e pune (dano, combo quebrado), respeitando i-frames de Dash
6. **UIRenderSystem** — decompõe o placar em dígitos por aritmética (`(valor // 10^i) % 10`) e escreve `texture_id`/`tint_a` em sprites de HUD pré-criados; os glifos 0-9 e as palavras PERFECT/GOOD/MISS foram pré-renderizados **uma única vez** no carregamento — nenhum `font.render` por frame

O HUD é desenhado pela mesma pipeline `IRenderer.draw_batch()` ultra-rápida do jogo base: dígitos são entidades `transform+sprite` comuns.

A única fonte de verdade temporal é o `IAudioClock` (posição real de reprodução, compensada de latência) — nunca delta-time acumulado, então áudio e gameplay não sofrem drift.

O **fluxo de partida** (menu/pausa/derrota/resultados) vive no `HertzGameLoop` — não em um `ISystem`: sistemas julgam uma fase em andamento; trocar ou reiniciar fase é *recomposição* (`compose_world` de novo: pools novas, placar zerado, cursor do spawner em 0, música do zero), na fase de carregamento, onde alocar é permitido. Os overlays (menu, PAUSADO, GAME OVER, FASE CONCLUÍDA) usam superfícies pré-renderizadas na composição — nenhum `font.render` por frame.

Os **modos de jogo** são o `GameModeStrategy` da arquitetura, resolvido em tempo de composição: `MODE_COMPOSERS` mapeia `game_mode` → função que registra os sistemas do modo (`defender`: spawner radial + JudgmentSystem com misfire; `survival`: jogador móvel + spawner de varreduras + julgamento 100% por colisão; `lanes`: spawner de notas + julgamento por tecla/coluna; `hybrid`: os dois primeiros coexistindo). Todos os spawners **são** o `RhythmSpawnerSystem` da engine (cursor monotônico e compensação de latência intactos) e todos consomem o mesmo `RHYTHM_THREAT_DTYPE` — o modo só muda a interpretação espacial dos campos (`lane` = setor angular, eixo de varredura ou coluna). Zero branch por evento no hot-path.

No **modo Híbrido**, o beatmap é **particionado na composição** por seção musical (`mixed_section_seconds`): cada spawner consome apenas a sua partição pré-filtrada, e cada juiz filtra pelo `mode_tag` gravado na linha da ameaça — ameaças radiais e paredes de som coexistem na mesma pool sem que os juízes se contaminem (a varredura de MISS radial nunca toca uma parede, e o coletor de expiração nunca recolhe uma ameaça radial).

## Testes

Suíte headless (backends Null da engine, clock de áudio manual e determinístico):

```bash
pip install pytest
python -m pytest
```

Cobre: spawn radial com impacto cravado na batida, janelas de julgamento e cone de mira, punição por colisão vs. janela de acerto tardio, dodge por i-frames, extração de dígitos do HUD, partida completa em autoplay perfeito e o fluxo inteiro de partida (menu → jogo ⇄ pausa → derrota → retry → vitória → próxima fase).

## Estrutura

```
hertzbeats/
  components/    schemas SoA (RhythmThreat, PlayerState) e ids de textura
  systems/       PlayerInput, RadialSpawner, Judgment, CoreDamage, UIRender
  adapters/      renderer/input/audio pygame do jogo (texturas, mira, pause)
  audio/         síntese determinística das faixas das fases
  offline/       pipeline de beatmap com a IA da engine (librosa; nunca em runtime)
  bootstrap/     rhythm_composition_root (composição) + hertz_game_loop (fluxo)
  stages.py      definições de fase data-driven
data/            config, bindings, fases, beatmaps (gerados pela IA, versionados)
tools/           generate_stage_assets.py, make_beatmap.py
tests/           suíte headless
```
