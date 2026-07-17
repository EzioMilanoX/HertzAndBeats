# Hertz & Beats

**Bullet Hell Rítmico radial ("Defesa de Perímetro") construído sobre a [Ouroboros Engine](https://github.com/EzioMilanoX/OuroborosEngine).**

Você é o núcleo no centro da arena. Ameaças nascem na borda da tela e voam em sua direção com velocidade matematicamente calculada para tocar o seu anel **exatamente no milissegundo da batida** extraída da música pela IA offline da engine (librosa). Mire em 360º com o mouse e atire no ritmo — ou atravesse o impacto com um Dash de i-frames.

Na pegada de *Just Shapes & Beats* / *BPM: Bullets Per Minute*.

## Modos de jogo

A IA dita o **tempo** (o mesmo `beatmap.json`); o modo dita a **interpretação espacial e de input**:

| Modo | Estilo | Como se joga |
| --- | --- | --- |
| **Defensor** | BPM / Metal: Hellsinger | Núcleo fixo, ameaças radiais 360º. Cada ameaça vem com um **anel de convergência** — um anel neon que encolhe matematicamente até coincidir com a sua mira exatamente no milissegundo do hit: atire quando os círculos se beijarem. Acerto no tempo dispara um **canhão pesado que vira percussão da trilha** (Gun Sync); atirar fora do tempo é **misfire** — clique seco, arma emperra por 0.5s e o combo zera. |
| **Sobrevivência** | Just Shapes & Beats | Mova-se livre (WASD). Toda parede de som é **telegrafada**: nasce como linha-guia translúcida piscando no lugar exato, uma aproximação inteira antes — e só fica sólida e letal no instante do onset. **Não há ataque**: o Dash (Espaço) só concede i-frames se apertado **na batida** (esquiva rítmica); fora do tempo ele emperra e a parede pune. |
| **Arcade 4K** | FNF / VSRG | 4 colunas fixas (**A S W D**); notas caem até a linha de julgamento. Em beatmaps `hybrid`, a coreografia é automática: **kicks nas bordas** (A/D), **vocais no centro** (S/W) — o groove numa mão, a melodia na outra. **Ghost tapping**: batucar livre sem nota na janela não pune, só um tique suave para manter o balanço. |
| **Híbrido** | Defensor + Sobrevivência | As **seções da música alternam** os modos: atire nas batidas das seções pares, dashe pelas ondas telegrafadas das ímpares. Você move o corpo (WASD) e mira a torreta do núcleo com o mouse — o escudo móvel do núcleo. |

## Como jogar

| Ação | Controle |
| --- | --- |
| Mira 360º (Defensor) | Mouse (direção a partir do núcleo) |
| Atirar / Parry (Defensor) | Botão esquerdo do mouse |
| Mover (Sobrevivência) | W A S D |
| Colunas (Arcade 4K) | **A S W D** (convenção FNF: ← ↓ ↑ →) |
| Dash (i-frames) | Espaço |
| Menu: escolher fase | Setas **ou W/S** · ENTER, ESPAÇO ou clique para jogar |
| Pausar / retomar | ESC |
| Após derrota/vitória | R repete a fase, ENTER vai à próxima, M (ou BACKSPACE) volta ao menu |
| **Calibrar áudio** | **+ / −** durante o jogo (passos de 10 ms, salvo entre sessões) |

**Sente o ritmo dessincronizado?** É a latência de áudio da sua máquina (driver + fones/caixas + monitor). Durante qualquer fase, aperte **+** se as ameaças parecem chegar *antes* do som, **−** se chegam *depois* — o valor aparece na tela, vale na hora e fica salvo em `data/config/user_settings.json` (local, por máquina).

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

## Use a sua própria música (arraste e jogue)

**Jogue qualquer `.mp3`, `.ogg`, `.wav` ou `.flac` na pasta [`musicas/`](musicas/) e abra o jogo.** Na primeira abertura a IA analisa a faixa (alguns segundos, com aviso na tela) e ela aparece no fim do menu; o beatmap fica cacheado em `data/beatmaps/user/` — as próximas aberturas são instantâneas. Substituiu o arquivo? A análise refaz sozinha.

Com a música selecionada no menu, **A/D (ou ←/→) escolhem o minigame** — O Defensor, Sobrevivência, Arcade 4K ou Híbrido — e ENTER joga. O mesmo beatmap serve aos quatro modos.

A análise requer `librosa` (`pip install librosa`); sem ele, músicas já analisadas continuam jogáveis e as novas são puladas com aviso no console. Para controle fino (densidade, espaçamento, lanes), o CLI continua disponível:

```bash
python tools/make_beatmap.py --audio minha_musica.mp3 \
    --output data/beatmaps/minha.beatmap.json --track-id minha
```

com o resultado apontável por uma entrada manual em `data/stages/stages.json` (aí com `overrides` de dificuldade próprios).

**Como o mapeador funciona (v4)** — a matemática de áudio vive na engine ([`extraction_profiles`](https://github.com/EzioMilanoX/OuroborosEngine)); o jogo interpreta. Três **Perfis de Extração**:

- **`groove`** — HPSS isola o percussivo, envelope em mel grave (fmax 250 Hz: bumbo/caixa, sem chimbal), **PLP** dá o pulso dominante e toda nota é **quantizada nessa grade** (batidas + colcheias; os onsets apenas votam). Para faixas guiadas por bateria — imune a mascaramento por pads/vocais.
- **`vocal_shred`** — separação suave (harmônico + percussivo atenuado, preservando os ataques da melodia), envelope em mel médio/agudo (300–8000 Hz), `onset_detect` agressivo **sem** quantização — abraça síncopa e metralhadoras de notas estilo FNF.
- **`hybrid`** *(padrão das suas músicas)* — as duas camadas fundidas com prioridade do kick, cada nota com a tag `layer`. No Arcade 4K, **kicks vão para as colunas das bordas e vocais para o centro** — o groove numa mão, a melodia na outra.

A **lane vem do timbre** (centroide espectral em quantis: grave → esquerda, agudo → direita, com anti-jack), **pesadas** são o topo ~8% dos acentos da própria música, e melhorias no mapeador re-analisam sua biblioteca automaticamente (`mapper_version`). Escolha o perfil por música com `tools/make_beatmap.py --profile groove|vocal_shred|hybrid`.

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

**Feedback sonoro é percussão real**: os três SFX (canhão do Gun Sync, clique do misfire/dash-fora-do-tempo, tique do ghost tap) são sintetizados deterministicamente (como as faixas) em `data/sfx/` e pré-carregados no build — nenhum atraso de I/O na primeira vez que tocam.

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
