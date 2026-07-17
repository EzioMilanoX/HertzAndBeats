"""
Gera a documentacao HTML completa do Hertz & Beats em docs/index.html.

Fonte unica de verdade: o proprio repositorio. As secoes de referencia
sao extraidas dos DOCSTRINGS reais (via ast, sem importar pygame) e dos
DADOS versionados (config, fases, beatmaps) -- regenerar depois de
qualquer mudanca mantem a documentacao correta por construcao.

Uso (a partir da raiz do repositorio):
    python tools/build_docs.py
"""
from __future__ import annotations

import ast
import html
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

OUTPUT_PATH = Path("docs/index.html")
PACKAGE_ROOT = Path("hertzbeats")
TESTS_ROOT = Path("tests")


# ---------------------------------------------------------------- extracao

def _first_line(doc: str) -> str:
    return doc.strip().splitlines()[0] if doc else ""


def parse_module(path: Path) -> dict:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    module = {
        "path": str(path).replace("\\", "/"),
        "doc": ast.get_docstring(tree) or "",
        "classes": [],
        "functions": [],
        "constants": [],
    }
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            methods = [
                {"name": item.name, "doc": ast.get_docstring(item) or ""}
                for item in node.body
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                and not item.name.startswith("__")
            ]
            module["classes"].append(
                {"name": node.name, "doc": ast.get_docstring(node) or "", "methods": methods}
            )
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            module["functions"].append({"name": node.name, "doc": ast.get_docstring(node) or ""})
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name.isupper():
                module["constants"].append(name)
    return module


def collect_modules() -> list:
    return [parse_module(p) for p in sorted(PACKAGE_ROOT.rglob("*.py")) if p.name != "__init__.py"]


def collect_tests() -> list:
    tests = []
    for path in sorted(TESTS_ROOT.glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        cases = [
            node.name
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
        ]
        tests.append({"file": path.name, "doc": _first_line(ast.get_docstring(tree) or ""), "cases": cases})
    return tests


def beatmap_stats(beatmap_path: str) -> dict:
    with open(beatmap_path, encoding="utf-8") as f:
        beatmap = json.load(f)
    timestamps = [t["timestamp_seconds"] for t in beatmap["threats"]]
    gaps = [b - a for a, b in zip(timestamps, timestamps[1:]) if b > a]
    span = timestamps[-1] - timestamps[0] if len(timestamps) > 1 else 0.0
    return {
        "count": len(timestamps),
        "heavy": sum(1 for t in beatmap["threats"] if t["threat_type"] == "rhythm_threat_heavy"),
        "density": len(timestamps) / span if span else 0.0,
        "min_gap": min(gaps) if gaps else 0.0,
        "first": timestamps[0],
        "last": timestamps[-1],
        "bpm": beatmap["bpm"],
    }


# ---------------------------------------------------------------- renderizacao

def e(text: str) -> str:
    return html.escape(text)


def doc_block(doc: str) -> str:
    if not doc:
        return ""
    return f'<pre class="doc">{e(doc.strip())}</pre>'


def render_api(modules: list) -> str:
    parts = []
    for module in modules:
        anchor = module["path"].replace("/", "-").replace(".py", "")
        parts.append(f'<details class="module" id="{anchor}"><summary><code>{e(module["path"])}</code>'
                     f' — {e(_first_line(module["doc"]))}</summary>')
        parts.append(doc_block(module["doc"]))
        if module["constants"]:
            parts.append("<p class='constants'>Constantes: " + ", ".join(f"<code>{e(c)}</code>" for c in module["constants"]) + "</p>")
        for func in module["functions"]:
            parts.append(f'<h4><code>{e(func["name"])}()</code></h4>{doc_block(func["doc"])}')
        for cls in module["classes"]:
            parts.append(f'<h3>classe <code>{e(cls["name"])}</code></h3>{doc_block(cls["doc"])}')
            for method in cls["methods"]:
                if method["doc"]:
                    parts.append(f'<h4><code>.{e(method["name"])}()</code></h4>{doc_block(method["doc"])}')
        parts.append("</details>")
    return "\n".join(parts)


def render_stage_rows(stages, base_config) -> str:
    rows = []
    for stage in stages:
        stats = beatmap_stats(stage.beatmap_path)
        overrides = ", ".join(f"{k}={v}" for k, v in stage.overrides.items()) or "—"
        synth = f'{stage.synth["bpm"]:.0f} BPM · {stage.synth["bars"]} compassos · {stage.synth.get("style", "standard")}' if stage.synth else "faixa externa"
        tutorial = f'{len(stage.tutorial_steps)} passos' if stage.tutorial_steps else "—"
        rows.append(
            f"<tr><td><strong>{e(stage.name)}</strong><br><small>{e(stage.subtitle)}</small></td>"
            f"<td>{e(synth)}</td>"
            f"<td>{stats['count']} ({stats['heavy']} pesadas)</td>"
            f"<td>{stats['density']:.2f}/s</td>"
            f"<td>{stats['min_gap']:.2f}s</td>"
            f"<td>{e(overrides)}</td>"
            f"<td>{tutorial}</td></tr>"
        )
    return "\n".join(rows)


def render_tests(tests) -> str:
    parts = []
    total = 0
    for test in tests:
        total += len(test["cases"])
        cases = "".join(f"<li><code>{e(c)}</code></li>" for c in test["cases"])
        parts.append(f'<details><summary><code>{e(test["file"])}</code> — {e(test["doc"])} '
                     f'({len(test["cases"])} testes)</summary><ul>{cases}</ul></details>')
    return f"<p>Total: <strong>{total} testes</strong> headless (backends Null da engine, clock manual).</p>" + "\n".join(parts)


def main() -> int:
    from hertzbeats.config import HertzConfig
    from hertzbeats.stages import load_stages

    base_config = HertzConfig.from_json("data/config/hertz_beats.config.json")
    stages = load_stages(base_config.stages_path)
    modules = collect_modules()
    tests = collect_tests()

    config_raw = json.loads(Path("data/config/hertz_beats.config.json").read_text(encoding="utf-8"))
    config_rows = "\n".join(
        f"<tr><td><code>{e(str(k))}</code></td><td><code>{e(json.dumps(v, ensure_ascii=False))}</code></td></tr>"
        for k, v in config_raw.items()
    )

    tutorial_stage = stages[0]
    tutorial_rows = "\n".join(
        f"<tr><td>ate {step['until_seconds']:.0f}s</td><td>{e(step['text'])}</td></tr>"
        for step in tutorial_stage.tutorial_steps
    )

    page = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Hertz &amp; Beats — Documentação</title>
<style>
:root {{ --bg:#faf9ff; --fg:#1d1a2e; --muted:#5f5a78; --card:#efedf8; --accent:#6b4fd8; --gold:#a07800; --line:#d8d4ea; }}
@media (prefers-color-scheme: dark) {{
  :root {{ --bg:#0c0a18; --fg:#e8e6f4; --muted:#a09ac0; --card:#171430; --accent:#a78bfa; --gold:#ffd640; --line:#2c2750; }}
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; font:16px/1.6 system-ui,'Segoe UI',sans-serif; background:var(--bg); color:var(--fg); }}
main {{ max-width:980px; margin:0 auto; padding:2rem 1.2rem 6rem; }}
h1 {{ font-size:2.4rem; margin:.2em 0; }} h1 span {{ color:var(--accent); }}
h2 {{ margin-top:2.6em; border-bottom:2px solid var(--line); padding-bottom:.25em; }}
h3 {{ margin-top:1.6em; }} h4 {{ margin:.9em 0 .2em; color:var(--muted); }}
code {{ background:var(--card); padding:.12em .38em; border-radius:5px; font-size:.92em; }}
pre {{ background:var(--card); padding:.9em 1.1em; border-radius:10px; overflow-x:auto; }}
pre.doc {{ white-space:pre-wrap; color:var(--muted); font-size:.88em; margin:.3em 0 .9em; }}
table {{ border-collapse:collapse; width:100%; margin:1em 0; font-size:.93em; }}
th,td {{ border:1px solid var(--line); padding:.5em .7em; text-align:left; vertical-align:top; }}
th {{ background:var(--card); }}
details {{ border:1px solid var(--line); border-radius:10px; padding:.55em .9em; margin:.55em 0; }}
summary {{ cursor:pointer; font-weight:600; }}
details.module > summary {{ font-weight:500; }}
.pill {{ display:inline-block; background:var(--card); border:1px solid var(--line); border-radius:999px; padding:.1em .8em; margin:.15em; font-size:.9em; }}
.flow {{ background:var(--card); border-radius:10px; padding:1em 1.2em; overflow-x:auto; }}
nav {{ position:sticky; top:0; background:var(--bg); border-bottom:1px solid var(--line); padding:.6em 1.2em; z-index:2; }}
nav a {{ color:var(--accent); text-decoration:none; margin-right:1.1em; font-size:.92em; }}
.gold {{ color:var(--gold); font-weight:600; }}
small, .muted {{ color:var(--muted); }}
</style>
</head>
<body>
<nav>
  <a href="#visao">Visão geral</a><a href="#rodar">Rodar</a><a href="#jogar">Como jogar</a>
  <a href="#fluxo">Fluxo</a><a href="#fases">Fases</a><a href="#mecanicas">Mecânicas novas</a>
  <a href="#arquitetura">Arquitetura</a>
  <a href="#config">Config</a><a href="#ferramentas">Ferramentas</a><a href="#testes">Testes</a><a href="#api">API</a>
</nav>
<main>
<h1>Hertz <span>&amp;</span> Beats</h1>
<p class="muted">Bullet Hell Rítmico radial ("Defesa de Perímetro") sobre a
<a href="https://github.com/EzioMilanoX/OuroborosEngine">Ouroboros Engine</a> ·
<a href="https://github.com/EzioMilanoX/HertzAndBeats">github.com/EzioMilanoX/HertzAndBeats</a></p>

<h2 id="visao">Visão geral</h2>
<p>Você é o <strong>núcleo</strong> no centro da arena. Ameaças nascem na borda da tela e voam
em sua direção com velocidade matematicamente calculada para a borda delas tocar o
<span class="gold">anel de julgamento</span> exatamente no milissegundo da batida — batidas extraídas
da música pela IA offline da engine (BPM + onsets via librosa). Mire em 360° com o mouse,
atire no ritmo, ou atravesse o impacto com um Dash de invencibilidade.</p>
<p>Princípios herdados da engine e mantidos em todo o jogo:</p>
<ul>
<li><strong>Zero-GC no gameplay</strong>: tudo é SoA (Structure of Arrays) sobre <code>ComponentPool</code>;
nenhum objeto Python ("HitEvent", "Threat", string) é instanciado por frame — vereditos são inteiros
gravados na própria linha do array, dígitos do HUD são aritmética sobre buffers pré-alocados.</li>
<li><strong>Relógio de áudio como única verdade temporal</strong>: spawner, julgamento e tutorial leem
o <code>IAudioClock</code> (posição real de reprodução, compensada de latência) — nunca delta-time
acumulado. Sem drift; pausar a música congela o jogo inteiro em sincronia.</li>
<li><strong>Data-driven</strong>: fases, beatmaps, bindings e toda a afinação vivem em JSON, nunca
hardcoded em sistema.</li>
</ul>

<h2 id="rodar">Como rodar</h2>
<pre>pip install -e ../OuroborosEngine --no-deps   # engine clonada ao lado
pip install numpy pygame-ce
python -m hertzbeats</pre>
<ul>
<li><strong>jogar.bat</strong> — duplo clique, roda com console (mostra placar final e erros).</li>
<li><strong>Atalho na área de trabalho</strong> — <code>powershell -ExecutionPolicy Bypass -File tools\\create_desktop_shortcut.ps1</code>
cria o atalho "Hertz &amp; Beats" (pythonw, sem console, com ícone).</li>
<li>Áudio adiantado/atrasado? Calibre: <code>python -m hertzbeats --latency 0.10</code>.</li>
<li>As faixas <code>.wav</code> são re-sintetizadas deterministicamente no primeiro build (não são versionadas);
os <code>beatmap.json</code> extraídos pela IA são versionados.</li>
<li>Se o monitor for menor que a janela configurada, a janela <em>e toda a geometria da arena</em>
encolhem na mesma proporção (<code>fit_config_to_display</code>) — a física e o julgamento continuam
cravados na batida em qualquer escala.</li>
</ul>

<h2 id="jogar">Como jogar</h2>
<table>
<tr><th>Ação</th><th>Controle</th></tr>
<tr><td>Mira 360°</td><td>Mouse (direção a partir do núcleo; o marcador orbita <em>sobre</em> o anel de julgamento)</td></tr>
<tr><td>Atirar Azul / Parry</td><td>Botão esquerdo do mouse</td></tr>
<tr><td>Atirar Rosa (fase Polaridade)</td><td>Botão direito do mouse</td></tr>
<tr><td>Dash (i-frames / Pulso de Impacto)</td><td>Espaço</td></tr>
<tr><td>Menu: escolher fase</td><td>Setas ↑/↓ · ENTER ou clique para jogar · ESC sai</td></tr>
<tr><td>Pausar / retomar</td><td>ESC</td></tr>
<tr><td>Derrota / vitória</td><td>R repete · ENTER próxima fase · M menu</td></tr>
</table>
<table>
<tr><th>Veredito</th><th>Condição</th><th>Efeito</th></tr>
<tr><td class="gold">PERFECT</td><td>|delta| ≤ {base_config.perfect_window_seconds*1000:.0f} ms da batida, mira dentro do cone de ±{base_config.aim_tolerance_degrees:.0f}°</td><td>+{base_config.score_perfect} pts, combo +1</td></tr>
<tr><td>GOOD</td><td>|delta| ≤ {base_config.good_window_seconds*1000:.0f} ms</td><td>+{base_config.score_good} pts, combo +1</td></tr>
<tr><td>MISS</td><td>batida passou {base_config.miss_window_seconds*1000:.0f} ms, ou a ameaça atingiu o núcleo</td><td>combo zera; impacto custa 1 de vida</td></tr>
<tr><td>DODGED</td><td>impacto durante os i-frames do Dash ({base_config.dash_duration_seconds:.2f}s; cooldown {base_config.dash_cooldown_seconds:.1f}s)</td><td>sem dano, combo preservado, sem pontos</td></tr>
</table>
<p class="muted">O visual e a mecânica coincidem: a ameaça deve ser atingida quando a borda dela
toca o anel — que é exatamente onde a sua mira orbita.</p>

<h2 id="fluxo">Fluxo de partida</h2>
<div class="flow"><pre>
MENU ──ENTER/clique──▶ PLAYING ◀──ESC──▶ PAUSED ──M──▶ MENU
                          │
        vida zerada ──────┤────── beatmap completo E (ameaças resolvidas OU música acabou)
                          ▼                              ▼ (carência de 1s)
                      GAME OVER                       RESULTS
                      R: repete                       ENTER: próxima fase
                      M: menu                         R: repete · M: menu
</pre></div>
<ul>
<li>Trocar/reiniciar fase = <strong>recomposição total</strong> do <code>World</code> (pools novas, placar
zerado, cursor do spawner em 0, música do zero) — nenhum estado vaza entre partidas.</li>
<li>Pausa congela <code>pygame.mixer.music.get_pos()</code> → o <code>IAudioClock</code> congela → todo o
gameplay rítmico para em sincronia e retoma do ponto exato.</li>
<li>Guard anti-softlock: se a música termina com ameaças ainda vivas (o relógio congela no fim da faixa),
a fase encerra pela carência em tempo real — e a curadoria de beatmap garante margem de fim ≥ 1s
para isso não acontecer em condições normais.</li>
</ul>

<h2 id="fases">Fases</h2>
<table>
<tr><th>Fase</th><th>Faixa (síntese)</th><th>Ameaças</th><th>Densidade</th><th>Gap mín.</th><th>Overrides</th><th>Tutorial</th></tr>
{render_stage_rows(stages, base_config)}
</table>
<p>Definidas em <code>data/stages/stages.json</code>. A curadoria pós-IA (<code>select_onsets</code>) escolhe
os onsets <strong>mais fortes</strong> da música até a densidade-alvo da fase, com espaçamento mínimo e
janela temporal jogável (nada antes da pista completa de aproximação, nada depois de
<code>duração − 1.2s</code>). Picos com strength ≥ 0.8 viram <strong>ameaças pesadas</strong>.</p>
<h3>Passos do tutorial</h3>
<table><tr><th>Janela</th><th>Instrução</th></tr>{tutorial_rows}</table>
<h3>Use a sua própria música</h3>
<pre>pip install librosa
python tools/make_beatmap.py --audio minha.mp3 --output data/beatmaps/minha.beatmap.json --track-id minha</pre>
<p>Depois adicione uma entrada em <code>stages.json</code> (sem o bloco <code>synth</code>) e ela aparece no menu.</p>

<h2 id="mecanicas">Mecânicas novas (7 mecânicas, 3 modos)</h2>
<p>Todas seguem a mesma disciplina Zero-GC do resto do jogo: campos extras no
<code>RHYTHM_THREAT_DTYPE</code> compartilhado, mascaramento vetorizado por <code>mode_tag</code>/flag
booleano, e sistemas dedicados que só tocam as linhas que lhes pertencem.</p>
<h3>Defensor — Polaridade + Parry Perfeito</h3>
<p>Opt-in via <code>polarity_enabled</code> (fase <span class="gold">Polaridade</span>): dois gatilhos
com cor fixa (Azul = clique esquerdo, Rosa = clique direito, estilo <em>Ikaruga</em>). A cor de uma
ameaça comum vem de graça do <strong>bucket de timbre</strong> que a IA já atribui à <code>lane</code>
(metade grave = Rosa, metade aguda = Azul — zero análise extra). Cor errada no tempo/mira certos é um
<strong>Deflect</strong> (não pune, só não acerta). Ameaças <strong>pesadas</strong> só entram como
candidatas dentro da janela PERFECT (mais estreita); um acerto nesse instante as <strong>reflete</strong>
em vez de destruir — <code>JudgmentSystem</code> inverte a velocidade e troca a camada de colisão para
<code>REFLECTED_COLLISION_LAYER</code>, e o <code>ParryImpactSystem</code> consome os pares que o
<code>CollisionSystem</code> genérico passa a gerar entre o projétil e as demais ameaças no caminho de
volta, destruindo a mais fraca em cadeia. O refletido permanece <code>JUDGMENT_PENDING</code> de
propósito — agora é uma arma, não mais uma vítima — e a varredura de MISS o ignora.</p>
<h3>Sobrevivência — Graze + Fever, Pulso de Impacto</h3>
<p>Um segundo raio de detecção (AABB vetorizado, paralelo ao <code>CollisionSystem</code>) mede a
distância a cada parede letal; cruzar a faixa estendida (<code>hitbox + graze_margin</code>) sem tocar
a hitbox real concede <strong>Graze</strong> e carrega o medidor de <strong>Fever</strong> (decai com o
tempo; cheio, dobra a pontuação). Um dash perfeito ativa uma de 5 entidades de onda de choque
<strong>pré-alocadas</strong> (nunca criadas/destruídas — round-robin), cujo raio cresce
exponencialmente por 0.2s e varre paredes fracas; pesadas resistem, como no Parry.</p>
<h3>Arcade 4K — Pistas Dinâmicas, Scratch, Flow State</h3>
<p>Clusters de 3+ picos consecutivos são fundidos <strong>puramente do lado do jogo</strong>
(<code>lane_scratch_clustering</code>, sem tocar o beatmap.json) numa nota de <strong>Scratch</strong> —
mova o mouse continuamente (eixo <code>scratch_energy</code>) do início ao fim do hold ou é MISS
imediato. Os mesmos instantes de início de cluster disparam <strong>Pistas Dinâmicas</strong>: as 4
colunas balançam em direções opostas via uma senoide amortecida <em>causal</em>
(<code>compute_lane_sway</code>) — reação ao impacto, nunca antecipação. 50 PERFECTs seguidos entram em
<strong>Flow State</strong>: o <code>UIRenderSystem</code> apaga todo o HUD; um Miss "quebra o vidro" e
restaura a interface. Aproximação honesta: <code>pygame.mixer</code> não tem EQ em tempo real, então o
"bass boost" é um <strong>swell de volume real</strong> (a faixa sobe para 1.0 exatamente na entrada do
Flow via <code>HBPygameAudioEngine.set_track_volume</code>) — sem fingir um grave que o backend não pode
produzir.</p>

<h2 id="arquitetura">Arquitetura</h2>
<p>Ordem <strong>exata</strong> de execução por frame, registrada em
<code>hertzbeats/bootstrap/rhythm_composition_root.py</code>:</p>
<ol>
<li><code>PlayerInputSystem</code> — mira 360° (eixos abstratos <code>aim_x/aim_y</code>), Dash, i-frames, crosshair;</li>
<li><code>RadialRhythmSpawnerSystem</code> — <em>é</em> o <code>RhythmSpawnerSystem</code> da engine (cursor
monotônico + compensação de latência intactos), estendido para materializar cada ameaça na borda com
<code>velocidade = (raio_spawn − contato) / tempo_restante</code> — o impacto crava na batida mesmo que o
spawn atrase um frame;</li>
<li><code>JudgmentSystem</code> — varre o RhythmThreatPool com <code>|target_hit_time − relógio|</code>
vetorizado em buffers <code>out=</code>; janelas Perfect/Good/Miss + cone de mira; vence a candidata de menor
|delta|; marca <code>is_hit</code>, enfileira destruição diferida, atualiza placar por aritmética;</li>
<li><code>PhysicsSystem</code> (engine) — integra posições;</li>
<li><code>CollisionSystem</code> (engine) + <code>CoreDamageSystem</code> — pares AABB núcleo×ameaça;
punição só quando a ameaça está vencida além da janela GOOD (senão roubaria o acerto tardio) e fora de
i-frames; cada ameaça recebe exatamente <strong>um</strong> veredito (campo <code>judgment</code> guarda contra dupla contagem);</li>
<li><code>TutorialSystem</code> (só em fases com <code>tutorial_steps</code>) — banner de instruções por cursor de tempo;</li>
<li><code>UIRenderSystem</code> — dígitos por <code>(valor // 10^i) % 10</code> vetorizado sobre sprites de HUD
pré-criados; glifos e palavras pré-renderizados uma única vez no carregamento.</li>
</ol>
<p>O HUD e os overlays (menu/PAUSADO/GAME OVER/FASE CONCLUÍDA) usam superfícies pré-renderizadas na
composição — nenhum <code>font.render</code> por frame. A destruição de entidades dentro de sistemas usa o
padrão da engine: o <code>PackedEntityId</code> (uint64) fica gravado na própria linha SoA da ameaça.</p>

<h2 id="config">Referência de configuração (<code>data/config/hertz_beats.config.json</code>)</h2>
<table><tr><th>Campo</th><th>Valor atual</th></tr>{config_rows}</table>
<p class="muted">Fases sobrescrevem campos via <code>overrides</code> (aplicados com
<code>dataclasses.replace</code>; campo desconhecido = erro, nunca ignorado).</p>

<h2 id="ferramentas">Ferramentas</h2>
<ul>
<li><code>tools/generate_stage_assets.py [--force]</code> — sintetiza as faixas e regenera os beatmaps
de todas as fases via IA (preserva beatmaps autorais de tutorial);</li>
<li><code>tools/make_beatmap.py</code> — gera beatmap de qualquer música sua;</li>
<li><code>tools/make_icon.py</code> — regenera o ícone (PNG + ICO);</li>
<li><code>tools/create_desktop_shortcut.ps1</code> — cria o atalho na área de trabalho;</li>
<li><code>tools/build_docs.py</code> — regenera esta documentação a partir do código/dados reais.</li>
</ul>

<h2 id="testes">Testes automatizados</h2>
{render_tests(tests)}
<p>Rodar: <code>python -m pytest</code> (na raiz). A suíte inclui <strong>invariantes de jogabilidade</strong>
sobre os beatmaps versionados: densidade média/pico dentro do humanamente jogável, espaçamento mínimo entre
janelas de julgamento, margem de fim de faixa (anti-softlock) e pista completa para a primeira ameaça.</p>

<h2 id="api">Referência de API (docstrings do código)</h2>
{render_api(modules)}

<p class="muted" style="margin-top:4rem">Gerado por <code>tools/build_docs.py</code> a partir do código e
dos dados reais do repositório.</p>
</main>
</body>
</html>
"""
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(page, encoding="utf-8")
    print(
        f"documentacao gerada: {OUTPUT_PATH} "
        f"({len(modules)} modulos, {sum(len(t['cases']) for t in tests)} testes documentados)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
