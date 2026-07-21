# Hertz & Beats

**Bullet Hell Rítmico radial ("Defesa de Perímetro") construído sobre a [Ouroboros Engine](https://github.com/EzioMilanoX/OuroborosEngine).**

Você é o núcleo no centro da arena. Ameaças nascem na borda da tela e voam em sua direção com velocidade matematicamente calculada para tocar o seu anel **exatamente no milissegundo da batida** extraída da música pela IA offline da engine (librosa). Mire em 360º com o mouse e atire no ritmo — ou atravesse o impacto com um Dash de i-frames.

Na pegada de *Just Shapes & Beats* / *BPM: Bullets Per Minute*.

## Modos de jogo

A IA dita o **tempo** (o mesmo `beatmap.json`); o modo dita a **interpretação espacial e de input**:

| Modo | Estilo | Como se joga |
| --- | --- | --- |
| **Defensor** | BPM / Metal: Hellsinger | Núcleo fixo, ameaças radiais 360º. Acerto no tempo dispara um **canhão pesado que vira percussão da trilha** (Gun Sync); atirar fora do tempo é **misfire** — clique seco, arma emperra por 0.5s e o combo zera. Todo o resto (anéis-aviso, Polaridade/Parry, Escudos Rotativos, Gêmeos, Eclipses, Overload, Colapso do Anel) é **modular** — ver [Arquitetura de Mecânicas Modulares](#modificadores) abaixo. |
| **Arcade 4K** | FNF / VSRG | 4 colunas fixas (**A S W D**); notas caem até a linha de julgamento. Em beatmaps `hybrid`, a coreografia é automática: **kicks nas bordas** (A/D), **vocais no centro** (S/W) — o groove numa mão, a melodia na outra. **Ghost tapping**: batucar livre sem nota na janela não pune, só um tique suave para manter o balanço. Rajadas de picos viram **Notas de Scratch** (segure o mouse em movimento contínuo); durante um solo/glitch as colunas **balançam** (Pistas Dinâmicas); e 50 PERFECTs seguidos entram em **Flow State** — a interface some por completo até o primeiro erro. Notas Longas/Shield, Bombas e Cura também são modulares (veja abaixo). |

## Como jogar

| Ação | Controle |
| --- | --- |
| Mira 360º (Defensor) | Mouse (direção a partir do núcleo) |
| Atirar Azul / Parry (Defensor) | Botão esquerdo do mouse |
| Atirar Rosa (fase Polaridade) | Botão direito do mouse |
| Segurar Nota Longa (Defensor, fase Notas Longas) | Segure o clique **e** a mira sobre a ameaça até esgotar |
| Segurar Nota Longa (Arcade 4K, fase Notas Longas) | Segure a tecla da coluna até esgotar |
| Colunas (Arcade 4K) | **A S W D** (convenção FNF: ← ↓ ↑ →) |
| Scratch alternado (Arcade 4K) | **Z/X** alternados, ou a roda do mouse — alternativas ao mouse contínuo |
| Dash (i-frames, Defensor) | Espaço |
| Menu: escolher fase | Setas **ou W/S** · ENTER/ESPAÇO/clique numa fase curada joga; numa música sua, entra no menu de opções |
| Menu de opções (músicas suas) | **W/S** navegam as linhas · **A/D** alteram a linha de múltipla escolha em foco · **ENTER/ESPAÇO** liga/desliga um modifier OU inicia a fase (só na linha `>>> INICIAR FASE <<<`) · **ESC** volta pra lista de fases |
| Menu: Modo Treino (músicas suas) | **T** liga/desliga (densidade reduzida, sem dano de vida) |
| Pausar / retomar | ESC |
| Após derrota/vitória | R repete a fase, ENTER vai à próxima, M (ou BACKSPACE) volta ao menu |
| **Calibrar áudio** | **+ / −** durante o jogo (passos de 10 ms, salvo entre sessões) |

**Sente o ritmo dessincronizado?** É a latência de áudio da sua máquina (driver + fones/caixas + monitor). Durante qualquer fase, aperte **+** se as ameaças parecem chegar *antes* do som, **−** se chegam *depois* — o valor aparece na tela, vale na hora e fica salvo em `data/config/user_settings.json` (local, por máquina).

O fluxo da partida: **menu de fases → jogando ⇄ pausado → GAME OVER** (vida zerada) ou **FASE CONCLUÍDA** (todas as ameaças resolvidas). Pausar congela a música — e como todo o gameplay rítmico lê exclusivamente o relógio de áudio, o jogo inteiro congela em sincronia e retoma do ponto exato, sem drift.

## Fases

Um tutorial + a **campanha do Defensor** (5 fases de dificuldade progressiva) + Arcade 4K, definidos em [data/stages/stages.json](data/stages/stages.json) (data-driven — adicione as suas):

| Fase | Modo | Faixa | Dificuldade | `active_modifiers` |
| --- | --- | --- | --- | --- |
| **Tutorial** | Defensor | 80 BPM, `calm` | Guiado por instruções na tela; 6 de vida, sem misfire | `[]` |
| **1 · Iniciação** | Defensor | 100 BPM, `calm` | Aproximação 2.8s, cone 45°, janelas bem largas (70/150/220 ms) | `[]` |
| **2 · Despertar** | Defensor | 128 BPM, `standard` | Aproximação 2.0s, cone 38°, janelas 60/120/180 ms | `["telegraph_rings"]` |
| **3 · Ikaruga** | Defensor | 150 BPM, `intense` (beatmap da fase 3) | Aproximação 1.8s, cone 32°, janelas 50/100/150 ms | `["telegraph_rings", "polarity"]` |
| **4 · Clausura** | Defensor | 150 BPM (mesmo beatmap) | Aproximação 1.5s, cone 25°, janelas 45/90/130 ms | `[..., "orbital_shields"]` |
| **5 · Pesadelo** | Defensor | 150 BPM (mesmo beatmap) | Aproximação 1.2s, cone 20°, janelas 35/70/100 ms (no limite humano) | `[..., "twin_threats", "orbital_eclipses", "overload", "radius_collapse"]` |
| **6 · Arcade 4K** | Arcade | **mesmo beatmap da fase 2** | Notas D/F/J/K, queda em 1.8s | `[]` |
| **7 · Notas Longas** | Defensor (Hold) | **mesmo beatmap da fase 1** | Aproximação 2.4s, 4 de vida | `["holds"]` |
| **8 · Arcade: Notas Longas** | Arcade 4K (Hold+Shield) | **mesmo beatmap da fase 2** | Aproximação 1.8s | `["holds"]` |

As fases 3-8 consomem **os mesmos 3 `beatmap.json`** das fases 1-3 (a IA nunca vê o modificador nem o modo — a demonstração literal da tese: o mesmo tempo extraído vira jogos diferentes só por dados de composição). A campanha do Defensor escala matematicamente (`approach_seconds`/`aim_tolerance_degrees`/janelas de julgamento cada vez mais apertadas) **e** mecanicamente (mais entradas em `active_modifiers` a cada fase, nunca menos) — ver [Arquitetura de Mecânicas Modulares](#modificadores) abaixo para o catálogo completo e como cada modifier liga sistemas extras na composição.

O **tutorial** ensina jogando: faixas de instrução aparecem no topo da tela em sincronia com a música (mova a mira → atire quando a ameaça tocar o anel → janelas PERFECT/GOOD → uma onda de 3 ameaças simultâneas para aprender o Dash → sequência final). O beatmap do tutorial é **autoral** (timing didático, em [data/beatmaps/tutorial.beatmap.json](data/beatmaps/tutorial.beatmap.json)) — o `generate_stage_assets.py` preserva ele e só regenera os das fases via IA. Por baixo, é o mesmo motor: um `TutorialSystem` zero-GC avança um cursor de passos contra o `IAudioClock` (a mesma base de tempo do spawner) e troca a textura de um sprite-banner pré-renderizado; os passos vêm do JSON da fase (`tutorial_steps`), então qualquer fase pode virar um tutorial.

Cada fase tem sua faixa sintetizada deterministicamente (o `.wav` não é versionado; é reconstruído bit a bit no primeiro uso) e seu beatmap extraído pela IA offline da engine — 107, 180 e 168 ameaças respectivamente (fases 1-3; as demais reusam esses 3 arquivos). Para regenerar tudo: `python tools/generate_stage_assets.py --force` (requer `librosa`).

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

Com a música selecionada no menu, **ENTER/ESPAÇO/clique entram no menu de opções** — um padrão universal de Arcade/RPG que deixa montar sua própria combinação de mecânicas, uma música por vez:

- **W/S** navegam as linhas do menu (eixo vertical, sempre).
- **A/D** alteram o VALOR da linha de múltipla escolha em foco — as 2 primeiras linhas são sempre `< DEFENSOR >`/`< ARCADE 4K >` (o modo base) e `< Nenhuma >`/`< Polaridade >`/`< Holds >` (a **Mecânica Pesada** — Polaridade e Holds nunca coexistem porque disputam o mesmo `threat_type` "pesada", então viraram uma escolha de 3 valores em vez de 2 checkboxes com lógica de exclusão escondida).
- **ENTER/ESPAÇO** é o botão de Ação da linha em foco — liga/desliga um checkbox de modifier, ou **só na última linha, `>>> INICIAR FASE <<<`**, inicia a fase com a combinação atual (em qualquer outra linha, nunca inicia nada).
- **ESC** sai do menu de opções de volta pra lista de fases, sem iniciar nada nem encerrar o jogo; **T** liga/desliga o Modo Treino, como sempre.

O Defensor mostra `telegraph_rings`, `orbital_shields`, `twin_threats`, `orbital_eclipses` e `overload` como checkboxes (a Mecânica Pesada cobre `polarity`/`holds` à parte); o Arcade 4K não tem nenhum checkbox hoje, só as 2 linhas de múltipla escolha + `INICIAR FASE`. `"radius_collapse"`/`"bombs"`/`"heal"` **não** entram no menu: só fazem algo visível em cima de dado específico de fase curada (eventos `modchart_events`/ameaças desses tipos no beatmap) que uma música do jogador nunca tem — um checkbox que não muda nada na tela é pior que não oferecer a opção. Toda música começa fora do menu de opções, no Defensor, Mecânica Pesada "Nenhuma" e sem nenhum checkbox marcado; a combinação escolhida vira `HertzConfig.active_modifiers` direto na hora de iniciar (ver [Modificadores](#modificadores)).

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

## Mecânicas novas

Todas seguem a mesma disciplina Zero-GC do resto do jogo: campos extras no `RHYTHM_THREAT_DTYPE`
compartilhado, mascaramento vetorizado por `mode_tag`/flag booleano, e sistemas dedicados que só
tocam as linhas que lhes pertencem — nenhum deles aloca por frame.

**Defensor — Polaridade + Parry Perfeito** (opt-in via `"polarity"` em `active_modifiers`, fase **Ikaruga**):
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

## Game Feel: Notas Longas (Hold) nos 2 modos, Screen Shake e Haptics

Um único campo mode-agnóstico, `duration_sec` (no `RHYTHM_THREAT_DTYPE` compartilhado), liga o Hold
em `"holds"` (`active_modifiers`) — cada modo reinterpreta a sustentação à sua maneira ("a IA dita o tempo, o modo
dita a interpretação", a mesma filosofia do resto do schema):

- **Defensor** (fase **7 · Notas Longas**): ameaças pesadas viram um Hold em duas fases. Fase 1
  (Start): um acerto na janela Good normal não destrói a ameaça — ela fica "engajada" (velocidade
  zerada, colisão com o núcleo desarmada). Fase 2 (Sustain): segure o gatilho **e** a mira sobre ela
  continuamente até `target_hit_time_sec + duration_sec` — soltar ou desmirar antes disso é MISS
  imediato (sem esperar o fim), sustentar até o fim é PERFECT.
- **Arcade 4K** (fase **8 · Arcade: Notas Longas**): pesadas que **não** viraram um cluster de Scratch
  ganham `duration_sec` e um visual ciano distinto — apertar a coluna certa engaja o Hold sem destruir
  a nota (a barra segue caindo normalmente, mesmo idioma visual do Scratch); soltar a tecla antes do
  fim quebra. Um **Shield** (`GameState.shield_charges`, 3 cargas por padrão) absorve as primeiras
  quebras — só um tremor leve; esgotado, a falha passa a custar vida de verdade, a **primeira** forma
  do Arcade 4K de chegar ao Game Over.

**Screen Shake**: `GameState.shake_intensity` (pixels de deslocamento) decai a cada frame via um
`CameraShakeSystem`, comum aos 2 modos; o `HertzGameLoop` traduz isso num offset aleatório real via
`IRenderer.set_camera_offset` — método que **já existia** na engine (ROADMAP próprio do usuário) mas
nunca tinha um chamador no jogo. `GameState.trigger_shake` usa `max()` (tremores sobrepostos não
somam) e hoje é acionado por qualquer impacto do jogo: quebrar um Hold (nas 2 variantes), o núcleo
sendo atingido, e o Parry acertando em cadeia — cada magnitude é sua própria constante em
`HertzConfig`, afinável por fase.

**Haptics**: `IInputProvider.set_rumble(low_freq, high_freq, duration_sec)` é um método novo na
própria engine (ABC `IInputProvider`), com implementação real via `Joystick.rumble` do pygame — no-op
silencioso sem controle conectado. Toda quebra de Hold (nos 2 modos) chama direto.

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

## Modcharts e efeitos avançados (Arcade 4K)

Oito mecânicas, todas **opt-in por dados** (nenhuma exige tocar em `LaneJudgmentSystem`/`LaneNoteSpawnerSystem` de fora do jeito data-driven já estabelecido) e todas seguindo a mesma disciplina Zero-GC do resto do jogo:

- **Notas Tóxicas (Bombas)** — o beatmap ganha um `threat_type` a mais, `rhythm_threat_bomb` (basta existir em `threat_type_ids`, o mesmo critério de opt-in de `rhythm_threat_heavy`). Uma Bomba é candidata a acerto como qualquer nota (mesma seleção por tempo+coluna), mas **acertá-la nunca pontua**: zera o combo, custa vida, treme a câmera e aciona o Vignette Flash. O jogo **correto** é não tocar — uma Bomba que passa da linha sem ser pressionada é destruída silenciosamente (SURVIVED), sem punição nenhuma, excluída da varredura genérica de MISS pela mesma lição de exclusão já usada para Scratch/Hold.
- **Notas de Cura** — outro `threat_type` opt-in, `rhythm_threat_heal`. Pontua PERFECT/GOOD normalmente; só um **PERFECT** também recupera 1 de vida (`heal_amount`, respeitando o teto de `max_health`) — GOOD pontua mas não cura, e deixar passar é um MISS comum do Arcade (sem dano de vida, como qualquer nota ignorada nesse modo).
- **Notas Fantasmas (Hidden)** — `hidden_notes_enabled` interpola `sprite.tint_a` linearmente de 255 até 0 nos últimos `hidden_fade_seconds` antes do julgamento (`VisualModifierSystem`) — a nota fica invisível pouco antes de chegar, mas a hitbox temporal (100% baseada no relógio, nunca em posição/alpha) não muda em **nada**.
- **Modcharts (Swap com Lerp)** — `StageDef.modchart_events` (100% game-side, não existe no `beatmap.json` da engine) define eventos `{"type": "swap", "time_seconds", "duration_seconds", "lane_a", "lane_b"}`: duas colunas trocam de lugar suavemente (interpolação linear) ao longo de N segundos. O `LaneChoreographySystem` (já responsável pelas Pistas Dinâmicas) ganhou essa segunda responsabilidade: `lane_center_xs` deixou de ser um array estático — agora é um buffer **mutável**, reescrito por inteiro todo frame e compartilhado por identidade com o `LaneNoteSpawnerSystem`, então uma nota **já caindo** acompanha a curva do swap em tempo real, não só as recém-criadas. A decoração de fundo das colunas também é sincronizada a cada frame (`HertzGameLoop._sync_lane_playfield`).
- **Inversão de Gravidade (Reverse Scroll)** — evento `{"type": "reverse_scroll", "time_seconds", "duration_seconds", "reversed"}` espelha `spawn_y`/linha de julgamento em torno do centro vertical da janela. O `ReverseScrollSystem` (novo) recalcula `velocity.linear_y` de **toda** nota pendente a cada frame — a mesma fórmula usada no spawn (`(linha_julgamento − posição_atual) / tempo_restante`), reaplicada continuamente a partir da posição corrente. Sem nenhum evento ativo essa fórmula é matematicamente **idêntica** a manter a velocidade original; um cuidado sutil (e corrigido só ao escrever o teste real de física sem deriva) é medir o tempo restante a partir do instante que a posição *ainda não integrada* de fato representa (`agora − delta_time`), não do relógio já avançado — senão o primeiro recálculo introduz um viés de velocidade permanente. O `LaneJudgmentSystem` é 100% temporal, então o julgamento nunca é afetado pela inversão.
- **Obstruções Visuais (jumpscares)** — evento `{"type": "distraction", "time_seconds", "duration_seconds", "x_fraction", "y_fraction"}` ativa um slot de um pool fixo de 5 entidades pré-alocadas (`DistractionSystem`: nunca cria/destrói, só liga/desliga em round-robin), cobrindo a tela com uma mancha de tinta procedural (`layer_z` acima do HUD) por um instante.
- **Stutter Scroll** — ruído visual senoidal em Y (`sin(now_seconds * frequência) * amplitude`, `VisualModifierSystem`) que confunde a leitura da queda das notas. A "gagueira" nunca toca `transform.position_y` (a física real que o `PhysicsSystem` integra e o julgamento por tempo nem olha): o `HertzGameLoop` sobrescreve `_render_frame` para somar o ruído só no array **temporário** de posições que vai para `draw_batch`, e descartado a seguir — sem deriva acumulada frame a frame.
- **Vignette Flash ("Cegueira Rítmica")** — acionado ao acertar uma Bomba: `GameState.blindness_timer_sec` (decaído pelo `CameraShakeSystem`, mesmo padrão de `shake_intensity`) liga um overlay pré-renderizado **uma única vez** no carregamento (`texture_bank.build_and_register_vignette_surface`) — uma Surface do tamanho da janela, opaca, com um buraco circular **transparente de verdade** (`pygame.draw.circle` com alfa 0 sobre `SRCALPHA` escreve os pixels, não mescla) focado na linha de julgamento. O jogador só lê as notas dentro do círculo iluminado enquanto durar.

Habilitar num `stages.json`: `"holds"`/`"bombs"`/`"heal"` em `active_modifiers` (`"stutter_scroll_enabled"`/`"hidden_notes_enabled": true` continuam campos separados em `overrides` -- não migrados para a lista, ver [Modificadores](#modificadores)) e/ou `"modchart_events": [...]` (swap, reverse_scroll, distraction) na definição da fase.

## Defensor hardcore: Captura Orbital, Ressonância de Polaridade e Hitlag de Parry

Quatro mecânicas que aprofundam o combate do Defensor **em cima** da Polaridade + Parry Perfeito já existente (tudo opt-in via `"polarity"` em `active_modifiers`, sem tocar nos outros dois modos):

- **Captura Orbital (Escudos Rotativos)** — um `threat_type` a mais, `rhythm_threat_orbit` (mesmo critério de opt-in de Bombas/Cura/pesadas). Um Parry Perfeito nesse tipo **não** reflete: `JudgmentSystem._register_orbital_capture` zera a velocidade, troca a camada de colisão para `SHIELD_COLLISION_LAYER` (arma contra ameaças comuns, nunca contra o núcleo — mesma técnica do Parry clássico) e grava `phase = PHASE_ORBITING` (reaproveita o campo `phase` já existente, sem precisar de um campo novo). O novo `OrbitalCaptureSystem` sobrescreve `position_x/y` diretamente todo frame via seno/cosseno em torno do núcleo — `spawn_angle_rad` (só telemetria até a captura) vira o offset angular fixo da órbita, então escudos capturados em momentos diferentes giram **juntos** preservando o espaçamento relativo. O `ParryImpactSystem` (já existente) passa a tratar `is_reflected` **ou** `phase == PHASE_ORBITING` como "atacante" — um escudo destrói qualquer ameaça comum que cruzar seu caminho, para sempre (nunca expira, ao contrário de um projétil refletido).
- **Ressonância de Polaridade (Combos Monocromáticos)** — `GameState.resonance_color/resonance_chain` seguem a sequência de ameaças comuns destruídas: mesma cor estende a corrente, cor diferente reinicia em 1. Ao atingir `resonance_chain_threshold` (10 por padrão) o jogador entra em **Overdrive** daquela cor (`GameState.in_overdrive`) — reinterpretação honesta do "tiro perfurante" pedido para um modelo hitscan sem projétil físico (o Defensor não tem bala viajando): um único disparo em Overdrive abate **todas** as candidatas válidas da cor quente presentes no frame de uma vez (`_register_piercing_kill`), não só a melhor — pesadas/orbitais e Holds engajáveis ficam de fora, seguem suas próprias rotas mesmo durante o Overdrive.
- **Ameaças de Hold Radial** — o Hold do Defensor (fase 6 · Notas Longas, já existente) ganhou o único gap real da revisão: soltar o gatilho ou desmirar antes do fim agora causa **dano instantâneo** no núcleo (mesmo guarda `practice_mode`/`health > 0` do `CoreDamageSystem`), além do MISS/Camera Shake/Haptics que já existiam.
- **Juice Extremo de Parry (Hitlag Visual Simulado)** — todo Parry Perfeito (clássico ou Captura Orbital) arma `GameState.trigger_hitlag`: `visual_freeze_frames` (decaído por quadro, não por segundo, no `CameraShakeSystem`) suspende `begin_frame`/`draw_batch` no `HBPygameRenderer` — a Surface simplesmente não é tocada, repetindo o último frame desenhado — e `invert_colors` arma um flash de cor invertida (`branco − frame atual` via `BLEND_RGB_SUB`, depois copiado de volta — a ordem inversa do que se poderia supor) publicado por **exatamente 1 frame**, no instante em que o congelamento termina. O `IAudioClock`/`world.step` nunca param — só a apresentação congela, a garantia central da tarefa.

## Defensor hardcore II: Gêmeos de Polaridade, Eclipses Orbitais, Overload do Núcleo e Colapso do Anel de Julgamento

O 3º e último pacote hardcore do Defensor, todo em cima da Polaridade já existente e sem alocar memória em runtime:

- **Gêmeos de Polaridade (Spawn Simultâneo e Flick)** — um `threat_type` a mais, `rhythm_threat_twin`. Quando o `RadialRhythmSpawnerSystem` processa um evento desse tipo, ele materializa **duas** entidades no mesmo frame, mesmo `target_hit_time_sec`, em lanes diametralmente opostas (`lane` e `lane + lane_count/2`, ou seja, ângulos `angle` e `angle + π`). Como a polaridade de uma ameaça comum é derivada da metade do bucket de timbre da sua `lane` (metade inferior = Rosa, superior = Azul), a lane espelhada cai **sempre** no bucket oposto — as duas nascem em cores opostas automaticamente, sem nenhuma lógica extra de cor. `_create_threat_entity` cria a segunda entidade fora do cursor monotônico da engine (o evento do beatmap continua contando como um disparo só); `_materialize_threat` foi extraído para ser chamado duas vezes, uma por entidade.
- **Eclipses Orbitais (Barreiras Dinâmicas)** — novo arquétipo `orbital_eclipse` (`orbital_eclipse_count` obstáculos, opt-in por fase), com `collision_layer = SHIELD_COLLISION_LAYER`/`collision_mask = REFLECTED_COLLISION_LAYER`: bloqueiam o único "tiro" que de fato viaja pelo espaço no Defensor hitscan — o projétil refletido do Parry — sem afetar ameaças comuns. Cada Eclipse nasce com `velocity.angular` constante e `velocity.linear = 0`; o `PhysicsSystem` **genérico** da engine já integra `rotation_rad += angular * delta_time` sozinho (movimento circular "de graça"). O novo `OrbitalEclipseSystem`, registrado **depois** do `PhysicsSystem` na composição, só converte esse ângulo já avançado em posição cartesiana (`center + cos/sin(rotation_rad) * orbit_radius`) — a ponte que o motor genérico não sabe fazer sozinho (ele só gira, nunca orbita). O `ParryImpactSystem` ganhou uma checagem `frozenset` (montada uma vez no construtor, sem alocação por frame): um par Eclipse×refletido destrói o projétil sem pontuar, o Eclipse (obstáculo permanente) segue orbitando.
- **Overload do Núcleo (reaproveitamento do `ShockwaveSystem`)** — o `ShockwaveSystem` original (Pulso de Impacto da extinta Sobrevivência) foi restaurado e incorporado à composição do Defensor: mesmo pool fixo round-robin, mesmo crescimento exponencial de raio, mesma técnica de camada de colisão própria sobre o `CollisionSystem` genérico — só o **gatilho** muda. O `JudgmentSystem` detecta Dash (Espaço) acionado sobre uma batida viva (candidata comum dentro da janela Good) com a Ressonância de Polaridade **cheia** (`GameState.in_overdrive`) e chama `GameState.consume_overdrive_for_overload()` — arma `overload_requested` (pedido de um frame, pull-based, mesmo padrão de `invert_colors`) **e** zera a corrente de Ressonância na mesma chamada, o "custo" de ativar o Overload. O `ShockwaveSystem` consome o pedido no seu próprio `update()` e ativa o próximo slot do pool, centrado no núcleo; o `CollisionSystem` já varre as ameaças fracas que a onda tocar (pesadas/orbitais/refletidos/escudos resistem, como ao Parry).
- **Colapso do Anel de Julgamento (Dynamic Radius)** — `judgment_radius` deixou de ser uma constante capturada no construtor: agora é `GameState.current_judgment_radius`, mutável. Um evento `{"type": "radius_collapse", "time_seconds", "duration_seconds", "target_radius"}` no `modchart_events` da fase dispara uma interpolação linear encadeada (`compute_collapsed_radius`, mesmo idioma de Lerp acumulado do `compute_scroll_flip_fraction` do Arcade 4K — cada evento parte de onde o anterior parou, permitindo sequências de colapso/expansão ao longo da música), calculada todo frame pelo novo `JudgmentRadiusSystem`. Três leitores consomem o mesmo valor mutável: o `RadialRhythmSpawnerSystem` (velocidade de ameaças **novas** — só as recém-nascidas sentem a mudança, as em voo mantêm sua velocidade original), o `PlayerInputSystem` (raio de órbita da mira) e o `HertzGameLoop._sync_defender_playfield` (o anel desenhado pelo `HBPygameRenderer`, publicado de novo a cada frame). Sem nenhum evento `radius_collapse` no beatmap da fase, o raio simplesmente permanece no valor base para sempre — mesma filosofia "sempre registrado, inofensivo por padrão" do `ReverseScrollSystem`.

A fase **5 · Pesadelo** liga os 4 modifiers acima de uma vez (3 Eclipses Orbitais + um colapso do anel de julgamento de 26→14px e de volta, em torno dos 20s de música) como demonstração curada — ver a tabela de fases e a seção [Modificadores](#modificadores) a seguir para como cada mecânica virou uma entrada de lista em vez de um flag fixo do `HertzConfig`.

## Modificadores

A partir desta revisão o jogo abandonou o conceito de "modos engessados" com um flag dedicado por mecânica (`polarity_enabled`, `holds_enabled`, ...). Em seu lugar, `HertzConfig.active_modifiers: Tuple[str, ...]` é uma lista aberta de strings — **qualquer** fase (curada ou música do jogador) pode combinar livremente as mecânicas do Defensor e do Arcade 4K, e `rhythm_composition_root.py` decide dinamicamente quais sistemas extras entram na composição.

**De onde vem a lista.** `StageDef.active_modifiers` é um campo dedicado da fase (irmão de `overrides`, não um campo dentro dele — como `modchart_events`), lido direto do JSON:

```json
{ "stage_id": "...", "overrides": { "aim_tolerance_degrees": 25.0 }, "active_modifiers": ["polarity", "orbital_shields"] }
```

`resolve_stage_config` copia essa lista para `HertzConfig.active_modifiers` **substituindo por completo** o valor anterior — nunca mesclada com nenhum default residual, então uma fase que não lista um modifier simplesmente não o tem, mesmo que a fase anterior o tivesse (`stage_config` é reconstruída do zero a cada troca).

**Como a composição lê a lista.** `_compose_defender_mode`/`_compose_lanes_mode` resolvem um único `frozenset(config.active_modifiers)` no topo da função e derivam booleanos locais — o resto do corpo só testa esses booleanos, exatamente como testava os antigos `config.polarity_enabled`/`config.holds_enabled`, só que agora a fonte de verdade é a presença na lista:

```python
modifiers = frozenset(config.active_modifiers)
polarity_enabled = "polarity" in modifiers
telegraph_rings_enabled = "telegraph_rings" in modifiers
orbital_shields_enabled = "orbital_shields" in modifiers and polarity_enabled   # dependencia tecnica
...
if telegraph_rings_enabled:
    ctx.world.register_system(ConvergenceRingSystem(...))
if polarity_enabled:
    ctx.world.register_system(ParryImpactSystem(...))
if overload_enabled:                      # Overload exige Polaridade (a Ressonancia so existe com ela)
    ctx.world.register_system(ShockwaveSystem(...))
```

Cada `if` registra um sistema **a mais** — a ORDEM de registro (PlayerInput → Spawner → Judgment → Physics → Collision → CoreDamage) nunca muda entre fases, só quantos sistemas extras entram nela. Zero-GC preservado: a resolução do `frozenset` e dos booleanos roda uma única vez na composição/carregamento da fase, nunca por frame — o hot-path (`update()` de cada sistema) nunca consulta `active_modifiers`.

**Dependências técnicas degradam, nunca quebram.** Alguns modifiers pressupõem outro ativo (`orbital_shields`/`twin_threats`/`overload` exigem `polarity`, já que reusam sua cor/Ressonância/máquina de Parry). Uma fase mal curada que ligue `orbital_shields` sem `polarity` não lança erro — o booleano derivado (`orbital_shields_enabled = "orbital_shields" in modifiers and polarity_enabled`) simplesmente fica `False`, e nenhum sistema extra entra (testado em `test_active_modifiers.py::test_orbital_shields_without_polarity_degrades_to_no_op`).

**Catálogo atual:**

| Modifier | Sistema(s) ligado(s) | Depende de |
| --- | --- | --- |
| `telegraph_rings` | `ConvergenceRingSystem` (anéis-aviso) | — |
| `polarity` | Disparo azul/rosa, Parry Perfeito, Ressonância/Overdrive, Hitlag | — |
| `orbital_shields` | `OrbitalCaptureSystem` (Escudos Rotativos) | `polarity` |
| `twin_threats` | Gêmeos de Polaridade (spawn duplo em `RadialRhythmSpawnerSystem`) | `polarity` |
| `orbital_eclipses` | `OrbitalEclipseSystem` + `orbital_eclipse_count` obstáculos | — |
| `overload` | `ShockwaveSystem` (reaproveitado) | `polarity` |
| `radius_collapse` | `JudgmentRadiusSystem` (raio dinâmico) | — |
| `holds` | Notas Longas (Defensor: fire+mira; Arcade: tecla+Shield) | mutuamente exclusivo com `polarity` (mesmo `threat_type`) |
| `bombs` / `heal` | Notas Tóxicas / Notas de Cura (Arcade 4K) | — |

**Gêmeos/Escudos Rotativos num beatmap real da IA.** O mapeador offline só conhece `basic`/`heavy` — nunca emite `rhythm_threat_twin`/`rhythm_threat_orbit`. Para que `twin_threats`/`orbital_shields` produzam algo visível em cima de um beatmap gerado pela IA (não só em testes com beatmap escrito à mão), `_reinterpret_scheduled_for_modifiers` (nova função pura em `rhythm_composition_root.py`) reescreve uma fração **determinística** (nunca por sorteio — a cada 5ª comum vira Gêmeos, a cada 3ª pesada vira Escudo) do array já agendado, sempre devolvendo uma cópia nova — o `beatmap.json` em disco nunca muda, mesma filosofia 100% game-side de Bombas/Cura/Scratch.

**Nos menus.** O seletor de minigame das músicas do jogador passou por 3 desenhos: um ciclo de 10 combinações FIXAS (`MODE_CYCLE`), depois um painel de checkboxes navegado por A/D+C, e por fim o **padrão universal de Arcade/RPG** atual (ver [Use a sua própria música](#use-a-sua-própria-música-arraste-e-jogue)) — a demonstração mais literal da tese de "combinar mecânicas livremente", com o eixo de navegação correto (W/S sempre vertical, A/D sempre multipla escolha) e sem tecla dedicada nenhuma (ENTER/ESPAÇO já bastam). `HertzGameLoop` guarda, por fase `selectable_mode`: `game_mode` ("defender"/"lanes"), `heavy_mechanic` ("none"/"polarity"/"holds" — substitui os antigos checkboxes independentes de Polaridade/Holds por uma multipla escolha, tornando a exclusão mútua ESTRUTURAL em vez de uma regra escondida), um `frozenset` dos demais modifiers booleanos, um `menu_cursor_index`, e um flag `options_focused` (foco ANINHADO: W/S navegam a lista de fases enquanto `options_focused` é falso, e as linhas do menu de opções assim que o jogador confirma sobre uma música — ESC volta ao estado anterior sem iniciar nada). `modifier_rows_for_game_mode(game_mode)` sempre retorna `(GAME_MODE_ROW, HEAVY_MECHANIC_ROW, <checkboxes do modo>, START_ROW)` — a fase só inicia com ENTER/ESPAÇO EXATAMENTE em `START_ROW`, nunca em outra linha (evita o erro comum de "toda tecla de confirmar já inicia a fase" que existia nos 2 desenhos anteriores).

O menu de fases curadas (`stages.json`) já resolvia a dica de controles a partir de `stage.active_modifiers` desde a introdução da arquitetura; essa resolução tem uma cadeia de prioridade (`overload` > `orbital_shields` > `twin_threats` > `orbital_eclipses` > `polarity` > `holds` > genérico do modo) para que uma fase com vários modifiers ligados ao mesmo tempo (ex.: "5 - Pesadelo") mostre a dica mais relevante, nunca uma lista de 7 linhas. **Achado real ao construir isso**: `HBPygameRenderer._blit_centered`/`_draw_modifier_row` só centralizam uma `Surface` já pronta — nunca quebram linha nem escalam — então um texto de dica, um rótulo de fase (`stage.name` + `stage.subtitle`) ou um rótulo de checkbox comprido demais estoura as bordas da janela em vez de aparecer cortado educadamente; 3 rótulos/dicas estouravam (2 novos, 1 pré-existente em "8 - Arcade: Notas Longas") até serem encurtados, e 2 testes de regressão (`test_render_visuals.py`, medem a largura renderizada de verdade com `pygame.font.Font(...).size(...)` contra `config.window_width`) passaram a cobrir isso. **Outro achado**: o rótulo pedido pra `START_ROW` usava os glifos Unicode de "play" (▶/◀) — a fonte PADRÃO do pygame (`pygame.font.Font(None, ...)`, sem arquivo de fonte customizado) não tem esses glifos e renderiza um quadrado vazio ("tofu") no lugar; trocado por ASCII puro (`">>>  INICIAR FASE  <<<"`), verificado empiricamente antes de decidir.

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

**Feedback sonoro é percussão real**: os SFX (canhão do Gun Sync, clique do misfire/dash-fora-do-tempo, tique do ghost tap, deflect e parry) são sintetizados deterministicamente (como as faixas) em `data/sfx/` e pré-carregados no build — nenhum atraso de I/O na primeira vez que tocam.

Os **modos de jogo** são o `GameModeStrategy` da arquitetura, resolvido em tempo de composição: `MODE_COMPOSERS` mapeia `game_mode` → função que registra os sistemas BASE do modo (`defender`: spawner radial + JudgmentSystem com misfire e Hold em 2 fases; `lanes`: spawner de notas + julgamento por tecla/coluna + `ScratchJudgmentSystem` + `LaneChoreographySystem`). Todos os spawners **são** o `RhythmSpawnerSystem` da engine (cursor monotônico e compensação de latência intactos) e todos consomem o mesmo `RHYTHM_THREAT_DTYPE` — o modo só muda a interpretação espacial dos campos (`lane` = setor angular ou coluna). Zero branch por evento no hot-path. Por cima do modo, `active_modifiers` (ver [Modificadores](#modificadores)) decide QUAIS sistemas extras entram — `ParryImpactSystem`/`OrbitalCaptureSystem`/`ShockwaveSystem`/etc no Defensor, Hold+Shield/Bombas/Cura no Arcade 4K.

## Testes

Suíte headless (backends Null da engine, clock de áudio manual e determinístico):

```bash
pip install pytest
python -m pytest
```

Cobre (259 testes): spawn radial com impacto cravado na batida, janelas de julgamento e cone de mira, punição por colisão vs. janela de acerto tardio, dodge por i-frames, extração de dígitos do HUD, partida completa em autoplay perfeito, o fluxo inteiro de partida (menu → jogo ⇄ pausa → derrota → retry → vitória → próxima fase), Polaridade + Parry Perfeito, Pistas Dinâmicas/Scratch/Flow State, Notas Longas (Hold) nos 2 modos (Defensor, Arcade 4K + Shield) + Screen Shake (agora acionado por toda colisão/impacto do jogo) + Haptics, os 4 itens de polimento (acessibilidade de forma na Polaridade, as 3 fontes de `scratch_energy`, o tier do Flow State e o Modo Treino), as 8 mecânicas/Modcharts avançados do Arcade 4K (Notas Tóxicas, Notas de Cura, Notas Fantasmas, Swap com Lerp, Inversão de Gravidade, Obstruções Visuais, Stutter Scroll, Vignette Flash), as 4 mecânicas hardcore do Defensor (Captura Orbital, Ressonância de Polaridade/Overdrive perfurante, dano instantâneo no Hold Radial e Hitlag Visual de Parry — renderer real com driver `dummy`, não só GameState), o 3º pacote hardcore do Defensor (Gêmeos de Polaridade, Eclipses Orbitais bloqueando o refletido do Parry, Overload do Núcleo/Shockwave reaproveitado e Colapso do Anel de Julgamento, também validado com renderer real), a Arquitetura de Mecânicas Modulares (`test_active_modifiers.py`: cada modifier liga/não liga o sistema certo, dependências técnicas degradam sem erro, `active_modifiers` nunca vaza entre fases, `_reinterpret_scheduled_for_modifiers` reatribui exatamente a fração determinística esperada), e o menu de opções padrão Arcade/RPG do seletor de minigame (`test_match_flow.py`: confirmar entra no menu sem iniciar nada, W/S percorrem todas as linhas sem pular/repetir e enrolam nas duas pontas, A/D fora do menu não fazem nada, A/D dentro alteram `GAME_MODE_ROW`/`HEAVY_MECHANIC_ROW` corretamente — incluindo o reset automático da Mecânica Pesada ao trocar pra um modo onde ela não existe —, ENTER/ESPAÇO liga/desliga um checkbox mas não faz nada nas linhas de múltipla escolha, a fase só inicia com o cursor EXATAMENTE em `START_ROW`, ESC sai do menu sem iniciar nem encerrar o jogo, e toda linha possível tem uma textura de rótulo registrada; `test_render_visuals.py`: nenhum hint/nome/rótulo de fase ou de linha do menu estoura a largura real da janela).

## Estrutura

```
hertzbeats/
  components/    schemas SoA (RhythmThreat, PlayerState) e ids de textura
  systems/       PlayerInput, RadialSpawner, Judgment, CoreDamage, UIRender,
                 ParryImpact, OrbitalCapture, LaneChoreography, ScratchJudgment,
                 OrbitalEclipse, Shockwave (Overload), JudgmentRadius (Colapso)
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
