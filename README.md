# Hertz & Beats

**Bullet Hell Rítmico radial ("Defesa de Perímetro") construído sobre a [Ouroboros Engine](https://github.com/EzioMilanoX/OuroborosEngine).**

Você é o núcleo no centro da arena. Ameaças nascem na borda da tela e voam em sua direção com velocidade matematicamente calculada para tocar o seu anel **exatamente no milissegundo da batida** extraída da música pela IA offline da engine (librosa). Mire em 360º com o mouse e atire no ritmo — ou atravesse o impacto com um Dash de i-frames.

Na pegada de *Just Shapes & Beats* / *BPM: Bullets Per Minute*.

## Modos de jogo

A IA dita o **tempo** (o mesmo `beatmap.json`); o modo dita a **interpretação espacial e de input**:

| Modo | Estilo | Como se joga |
| --- | --- | --- |
| **Defensor** | BPM / Metal: Hellsinger | Núcleo fixo, ameaças radiais 360º. Cada ameaça vem com um **anel de convergência** — um anel neon que encolhe matematicamente até coincidir com a sua mira exatamente no milissegundo do hit: atire quando os círculos se beijarem. Acerto no tempo dispara um **canhão pesado que vira percussão da trilha** (Gun Sync); atirar fora do tempo é **misfire** — clique seco, arma emperra por 0.5s e o combo zera. Na fase **Polaridade**, o núcleo ganha um segundo gatilho: **Azul** (esquerdo) e **Rosa** (direito), estilo *Ikaruga* — e ameaças pesadas viram um **Parry** perfeito em vez de morrer (veja abaixo). |
| **Sobrevivência** | Just Shapes & Beats | Mova-se livre (WASD). Toda parede de som é **telegrafada**: nasce como linha-guia translúcida piscando no lugar exato, uma aproximação inteira antes — e só fica sólida e letal no instante do onset. **Não há ataque**: o Dash (Espaço) só concede i-frames se apertado **na batida** (esquiva rítmica); fora do tempo ele emperra e a parede pune. Raspar perto de uma parede letal sem tocar concede **Graze** (estilo Touhou) e carrega o medidor de **Fever**; um dash perfeito também dispara um **Pulso de Impacto** — uma onda expansiva que varre paredes fracas. Na fase **Safe Zone**, pesadas viram zonas circulares **paradas** (nunca letais) — fique dentro e segure **Ancorar** até o fim (veja abaixo). |
| **Arcade 4K** | FNF / VSRG | 4 colunas fixas (**A S W D**); notas caem até a linha de julgamento. Em beatmaps `hybrid`, a coreografia é automática: **kicks nas bordas** (A/D), **vocais no centro** (S/W) — o groove numa mão, a melodia na outra. **Ghost tapping**: batucar livre sem nota na janela não pune, só um tique suave para manter o balanço. Rajadas de picos viram **Notas de Scratch** (segure o mouse em movimento contínuo); durante um solo/glitch as colunas **balançam** (Pistas Dinâmicas); e 50 PERFECTs seguidos entram em **Flow State** — a interface some por completo até o primeiro erro. Na fase **Notas Longas**, pesadas isoladas viram Holds clássicos de tecla sustentada protegidos por um **Shield** (veja abaixo). |
| **Híbrido** | Defensor + Sobrevivência | As **seções da música alternam** os modos: atire nas batidas das seções pares, dashe pelas ondas telegrafadas das ímpares. Você move o corpo (WASD) e mira a torreta do núcleo com o mouse — o escudo móvel do núcleo. Graze e Pulso de Impacto (das seções de Sobrevivência) continuam ativos aqui. |

## Como jogar

| Ação | Controle |
| --- | --- |
| Mira 360º (Defensor) | Mouse (direção a partir do núcleo) |
| Atirar Azul / Parry (Defensor) | Botão esquerdo do mouse |
| Atirar Rosa (fase Polaridade) | Botão direito do mouse |
| Segurar Nota Longa (Defensor, fase Notas Longas) | Segure o clique **e** a mira sobre a ameaça até esgotar |
| Segurar Nota Longa (Arcade 4K, fase Notas Longas) | Segure a tecla da coluna até esgotar |
| Ancorar (Sobrevivência, fase Safe Zone) | **E** — fique dentro da zona e segure até esgotar |
| Mover (Sobrevivência) | W A S D |
| Colunas (Arcade 4K) | **A S W D** (convenção FNF: ← ↓ ↑ →) |
| Scratch alternado (Arcade 4K) | **Z/X** alternados, ou a roda do mouse — alternativas ao mouse contínuo |
| Dash (i-frames / Pulso de Impacto) | Espaço |
| Menu: escolher fase | Setas **ou W/S** · ENTER, ESPAÇO ou clique para jogar |
| Menu: Modo Treino (músicas suas) | **T** liga/desliga (densidade reduzida, sem dano de vida) |
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
| **7 · Polaridade** | Defensor (Polaridade+Parry) | **mesmo beatmap da fase 3** | Aproximação 1.8s, cone 30°, `polarity_enabled: true` |
| **8 · Notas Longas** | Defensor (Hold) | **mesmo beatmap da fase 1** | Aproximação 2.4s, 4 de vida, `holds_enabled: true` |
| **9 · Arcade: Notas Longas** | Arcade 4K (Hold+Shield) | **mesmo beatmap da fase 2** | Aproximação 1.8s, `holds_enabled: true` |
| **10 · Sobrevivência: Safe Zone** | Sobrevivência (Safe Zone+Ancora) | **mesmo beatmap da fase 1** | Aproximação 2.0s, 4 de vida, `holds_enabled: true` |

As fases 4, 5, 7, 8, 9 e 10 consomem **os mesmos `beatmap.json`** das fases 1, 2 e 3 — a demonstração literal da tese: o modo é só outra interpretação espacial do mesmo tempo extraído pela IA. Trocar o modo de uma fase é uma linha no JSON: `"overrides": { "game_mode": "survival" }`.

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

Com a música selecionada no menu, **A/D (ou ←/→) escolhem o minigame** — O Defensor, Sobrevivência, Arcade 4K, Híbrido, **Defensor: Polaridade**, **Defensor: Notas Longas**, **Arcade 4K: Notas Longas** ou **Sobrevivência: Safe Zone** — e ENTER joga. As quatro últimas variantes são os próprios modos base com `polarity_enabled`/`holds_enabled` ligados — as mesmas mecânicas das fases curadas 7, 8, 9 e 10, agora disponíveis para qualquer música sua. O mesmo beatmap serve a todas as variantes.

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

## Mecânicas novas (7 mecânicas, 3 modos)

Todas seguem a mesma disciplina Zero-GC do resto do jogo: campos extras no `RHYTHM_THREAT_DTYPE`
compartilhado, mascaramento vetorizado por `mode_tag`/flag booleano, e sistemas dedicados que só
tocam as linhas que lhes pertencem — nenhum deles aloca por frame.

**Defensor — Polaridade + Parry Perfeito** (opt-in via `polarity_enabled`, fase **Polaridade**):
o núcleo tem dois gatilhos, cada um com uma cor fixa (Azul = clique esquerdo, Rosa = clique
direito, estilo *Ikaruga*). Uma ameaça comum só morre pela cor certa — a cor é derivada de graça
do **bucket de timbre** que a IA já atribui à `lane` (metade grave dos buckets = Rosa, metade
aguda = Azul: zero análise extra). Atirar na cor errada dentro da janela de tempo+mira é um
**Deflect**: não pune, só não acerta. Ameaças **pesadas** (`threat_type` heavy) são imunes a tiro
normal — só entram como candidatas dentro da janela **PERFECT** (mais estreita que a Good comum),
e um acerto nesse instante não as destrói: `JudgmentSystem` inverte o vetor de velocidade
(`velocity *= -1`) e troca a camada de colisão para `REFLECTED_COLLISION_LAYER`, fazendo o
`CollisionSystem` genérico gerar pares entre o projétil refletido e as demais ameaças pendentes no
caminho de volta — o `ParryImpactSystem` consome esses pares e destrói a mais fraca, pontuando em
cadeia. O projétil refletido permanece deliberadamente `JUDGMENT_PENDING` (agora é uma arma, não
mais uma vítima), e a varredura genérica de MISS o ignora por completo enquanto durar.

**Sobrevivência — Graze (Touhou) + Pulso de Impacto**: um segundo raio de detecção, paralelo ao
`CollisionSystem`, mede a distância do jogador a cada parede **letal** (AABB vetorizado sobre
todas as paredes ativas); cruzar a faixa estendida (`hitbox + graze_margin`) sem tocar a hitbox
real concede pontos de **Graze** e carrega o medidor de **Fever** (0..1, decai com o tempo) — cheio,
dobra a pontuação de Graze/sobrevivência até esvaziar. Um **dash perfeito** (na batida) ativa uma
das 5 entidades de "onda de choque" pré-alocadas no início da fase (disciplina Zero-GC ainda mais
estrita: nunca criadas/destruídas, só reaproveitadas em round-robin) — o raio cresce exponencialmente
por 0.2s e varre paredes fracas no caminho; pesadas resistem, como no Parry do Defensor.

**Arcade 4K — Pistas Dinâmicas, Notas de Scratch e Flow State**: clusters de 3+ picos consecutivos
(o "solo insano" que o extrator de onsets já concentra num trecho curto) são fundidos, puramente do
lado do jogo (`lane_scratch_clustering`, sem tocar o beatmap.json), numa única **nota de Scratch**
longa — mantenha o mouse em movimento contínuo (eixo `scratch_energy`) do início ao fim do hold ou é
MISS imediato, sem esperar o fim. Os mesmos instantes de início de cluster disparam **Pistas
Dinâmicas**: as 4 colunas balançam em direções opostas (senoide amortecida causal, `compute_lane_sway`)
como reação ao impacto, nunca antecipação. E 50 PERFECTs seguidos entram em **Flow State**: o
`UIRenderSystem` apaga todo o HUD (placar, combo, vida, rótulos) para imersão total; um único Miss
"quebra o vidro" — o combo zera, um aviso dramático aparece na tela e a interface (feia) volta.
Aproximação **honesta**: `pygame.mixer` não expõe nenhum filtro de EQ em tempo real, então o "bass
boost" do enunciado é um **swell de volume real** — a faixa toca normalmente um pouco abaixo do
máximo e sobe para 1.0 exatamente na entrada do Flow (`HBPygameAudioEngine.set_track_volume`) — um
efeito genuíno e audível, sem fingir um grave que o backend não pode produzir.

## Game Feel: Notas Longas (Hold) em 3 modos, Screen Shake e Haptics

Um único campo mode-agnóstico, `duration_sec` (no `RHYTHM_THREAT_DTYPE` compartilhado), liga o Hold
em `holds_enabled` — cada modo reinterpreta a sustentação à sua maneira ("a IA dita o tempo, o modo
dita a interpretação", a mesma filosofia do resto do schema):

- **Defensor** (fase **8 · Notas Longas**): ameaças pesadas viram um Hold em duas fases. Fase 1
  (Start): um acerto na janela Good normal não destrói a ameaça — ela fica "engajada" (velocidade
  zerada, colisão com o núcleo desarmada). Fase 2 (Sustain): segure o gatilho **e** a mira sobre ela
  continuamente até `target_hit_time_sec + duration_sec` — soltar ou desmirar antes disso é MISS
  imediato (sem esperar o fim), sustentar até o fim é PERFECT.
- **Arcade 4K** (fase **9 · Arcade: Notas Longas**): pesadas que **não** viraram um cluster de Scratch
  ganham `duration_sec` e um visual ciano distinto — apertar a coluna certa engaja o Hold sem destruir
  a nota (a barra segue caindo normalmente, mesmo idioma visual do Scratch); soltar a tecla antes do
  fim quebra. Um **Shield** (`GameState.shield_charges`, 3 cargas por padrão) absorve as primeiras
  quebras — só um tremor leve; esgotado, a falha passa a custar vida de verdade, a **primeira** forma
  do Arcade 4K de chegar ao Game Over.
- **Sobrevivência** (fase **10 · Sobrevivência: Safe Zone**): pesadas viram zonas circulares
  **estacionárias** (nunca uma parede que varre) numa grade determinística derivada da `lane` — a
  hitbox nunca é armada, mesmo depois de "solidificar" visualmente no onset. Julgada por distância
  direta ao jogador (mesmo idioma do Graze): fique dentro do raio **e** segure a ação **Ancorar**
  (E) até `target_hit_time_sec + duration_sec` — sair da zona ou soltar antes é MISS imediato.

**Screen Shake**: `GameState.shake_intensity` (pixels de deslocamento) decai a cada frame via um
`CameraShakeSystem`, comum aos 3 modos; o `HertzGameLoop` traduz isso num offset aleatório real via
`IRenderer.set_camera_offset` — método que **já existia** na engine (ROADMAP próprio do usuário) mas
nunca tinha um chamador no jogo. `GameState.trigger_shake` usa `max()` (tremores sobrepostos não
somam) e hoje é acionado por qualquer impacto do jogo: quebrar um Hold/Safe Zone (nas 3 variantes),
o núcleo ou uma parede sendo atingidos, o Pulso de Impacto disparando e o Parry acertando em cadeia —
cada magnitude é sua própria constante em `HertzConfig`, afinável por fase.

**Haptics**: `IInputProvider.set_rumble(low_freq, high_freq, duration_sec)` é um método novo na
própria engine (ABC `IInputProvider`), com implementação real via `Joystick.rumble` do pygame — no-op
silencioso sem controle conectado. Toda quebra de Hold/Safe Zone (nos 3 modos) chama direto.

## Polimento e acessibilidade

**Acessibilidade a daltonismo (Polaridade)**: depender só de Azul/Rosa excluía jogadores daltônicos.
Toda ameaça comum da fase Polaridade agora tem uma **forma** fixa por cor — triângulo interno (Azul)
ou quadrado interno (Rosa), desenhada em `HBPygameRenderer.draw_batch` **independente** do tint; o
núcleo também troca de forma ao disparar cada cor. Pesadas (Parry, aceitam qualquer cor) mantêm o
visual de sempre.

**Scratch por mais de uma via**: mover o mouse continuamente esbarra no limite físico do mousepad.
`scratch_energy` agora é o **maior** entre 3 fontes independentes — o movimento relativo do mouse, o
impulso da roda do mouse, e a **alternância** entre as ações `scratch_left`/`scratch_right` (Z/X por
padrão, ou gatilhos LT/RT de um controle) — nenhuma delas é obrigatória.

**Progresso visível no Flow State**: sem HUD, o jogador perdia a noção de quanto o combo avançou além
do limiar. A linha de julgamento agora avança de cor e pulsa a cada 50 acertos extras
(`tier = combo // limiar`), sincronizado todo frame pelo `HertzGameLoop`.

**Modo Treino (músicas do jogador)**: uma música complexa recém-mapeada pode gerar uma fase brutal.
No menu, **T** liga/desliga o Modo Treino para a música selecionada — reduz a densidade de onsets
(`thin_schedule_for_practice`, função pura que mantém 1 a cada N eventos uniformemente, sem tocar o
beatmap.json versionado) e suprime o dano de vida (o MISS continua contando e quebrando o combo — só
a vida é poupada).

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

**Feedback sonoro é percussão real**: os SFX (canhão do Gun Sync, clique do misfire/dash-fora-do-tempo, tique do ghost tap, deflect, parry e a faísca sutil do graze) são sintetizados deterministicamente (como as faixas) em `data/sfx/` e pré-carregados no build — nenhum atraso de I/O na primeira vez que tocam.

Os **modos de jogo** são o `GameModeStrategy` da arquitetura, resolvido em tempo de composição: `MODE_COMPOSERS` mapeia `game_mode` → função que registra os sistemas do modo (`defender`: spawner radial + JudgmentSystem com misfire e Hold em 2 fases, mais `ParryImpactSystem` quando `polarity_enabled`; `survival`: jogador móvel + spawner de varreduras + julgamento por colisão + `GrazeSystem` + `ShockwaveSystem`, mais `SafeZoneJudgmentSystem` quando `holds_enabled`; `lanes`: spawner de notas + julgamento por tecla/coluna (Hold clássico + Shield quando `holds_enabled`) + `ScratchJudgmentSystem` + `LaneChoreographySystem`; `hybrid`: Defensor e Sobrevivência coexistindo, Graze/Shockwave inclusos). Todos os spawners **são** o `RhythmSpawnerSystem` da engine (cursor monotônico e compensação de latência intactos) e todos consomem o mesmo `RHYTHM_THREAT_DTYPE` — o modo só muda a interpretação espacial dos campos (`lane` = setor angular, eixo de varredura ou coluna). Zero branch por evento no hot-path.

No **modo Híbrido**, o beatmap é **particionado na composição** por seção musical (`mixed_section_seconds`): cada spawner consome apenas a sua partição pré-filtrada, e cada juiz filtra pelo `mode_tag` gravado na linha da ameaça — ameaças radiais e paredes de som coexistem na mesma pool sem que os juízes se contaminem (a varredura de MISS radial nunca toca uma parede, e o coletor de expiração nunca recolhe uma ameaça radial).

## Testes

Suíte headless (backends Null da engine, clock de áudio manual e determinístico):

```bash
pip install pytest
python -m pytest
```

Cobre (193 testes): spawn radial com impacto cravado na batida, janelas de julgamento e cone de mira, punição por colisão vs. janela de acerto tardio, dodge por i-frames, extração de dígitos do HUD, partida completa em autoplay perfeito, o fluxo inteiro de partida (menu → jogo ⇄ pausa → derrota → retry → vitória → próxima fase), as 7 mecânicas de Polaridade/Graze/Pulso de Impacto/Scratch/Pistas Dinâmicas/Flow State, Notas Longas (Hold) nos 3 modos (Defensor em 2 fases, Arcade 4K + Shield, Sobrevivência + Safe Zone/Ancora) + Screen Shake (agora acionado por toda colisão/impacto do jogo) + Haptics, e os 4 itens de polimento: acessibilidade de forma na Polaridade, as 3 fontes de `scratch_energy`, o tier do Flow State e o Modo Treino.

## Estrutura

```
hertzbeats/
  components/    schemas SoA (RhythmThreat, PlayerState) e ids de textura
  systems/       PlayerInput, RadialSpawner, Judgment, CoreDamage, UIRender,
                 ParryImpact, Graze, Shockwave, LaneChoreography, ScratchJudgment
  lane_scratch_clustering.py  fusao pura de picos consecutivos em notas de Scratch
  adapters/      renderer/input/audio pygame do jogo (texturas, mira, pause, Flow)
  audio/         síntese determinística das faixas das fases
  offline/       pipeline de beatmap com a IA da engine (librosa; nunca em runtime)
  bootstrap/     rhythm_composition_root (composição) + hertz_game_loop (fluxo)
  stages.py      definições de fase data-driven
data/            config, bindings, fases, beatmaps (gerados pela IA, versionados)
tools/           generate_stage_assets.py, make_beatmap.py
tests/           suíte headless
```
