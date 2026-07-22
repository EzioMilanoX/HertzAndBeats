"""Progresso do jogador (nao versionado): modificadores vencidos + melhor Rank por fase/musica."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, FrozenSet, Optional

from hertzbeats.game_state import RANK_ORDER

PLAYER_PROGRESS_PATH = "data/config/player_progress.json"
"""Arquivo local (gitignored, mesmo criterio de `user_settings.json`):
cada maquina guarda seu proprio progresso -- nao e um placar competitivo
versionado, so uma lembranca local de "o que voce ja venceu"."""


def _rank_is_better(candidate: str, current: Optional[str]) -> bool:
    """Meta-Jogo -- Ranks: `RANK_ORDER` (`SS` a `D`) e MELHOR->PIOR, entao
    um indice MENOR e um rank melhor. `current is None` (nunca registrado
    antes) perde sempre; um rank fora de `RANK_ORDER` (so "-", a fase sem
    nenhuma nota resolvida) e tratado como o PIOR de todos -- nunca vale
    a pena registrar um "-" por cima de um rank de verdade."""
    if current is None:
        return True
    worst = len(RANK_ORDER)
    candidate_rank = RANK_ORDER.index(candidate) if candidate in RANK_ORDER else worst
    current_rank = RANK_ORDER.index(current) if current in RANK_ORDER else worst
    return candidate_rank < current_rank


def load_progress(path: str = PLAYER_PROGRESS_PATH) -> Dict[str, dict]:
    """Progresso por `stage_id` (`StageDef.stage_id`, estavel tanto para
    fases curadas quanto para musicas do jogador -- ver
    `music_library.song_slug`): `{"modifiers": frozenset(...), "best_rank":
    str|None}`. Dict vazio se o arquivo ainda nao existir ou estiver
    corrompido -- uma medalha/rank jamais derruba o jogo."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return {
            stage_id: {
                "modifiers": frozenset(entry.get("modifiers", ())),
                "best_rank": entry.get("best_rank"),
            }
            for stage_id, entry in raw.items()
        }
    except (OSError, ValueError, AttributeError, TypeError, json.JSONDecodeError):
        return {}


def record_stage_cleared(
    stage_id: str, active_modifiers, rank: Optional[str] = None, path: str = PLAYER_PROGRESS_PATH
) -> Dict[str, dict]:
    """Registra que `stage_id` foi concluida com `active_modifiers`
    ligados e (se fornecido) o `rank` desta partida -- chamado UMA vez
    por fase concluida, na transicao pra tela de resultados, nunca no
    loop de gameplay.

    `modifiers`: UNIAO com o que ja estava salvo (nunca substitui -- uma
    medalha ganha uma vez nao some porque a fase foi rejogada com uma
    combinacao diferente). `best_rank`: so ATUALIZA se `rank` for
    estritamente MELHOR que o ja salvo (`_rank_is_better`) -- uma
    partida pior nunca rebaixa o recorde do jogador.

    Grava de volta no disco e devolve o progresso ATUALIZADO inteiro,
    para o chamador nao precisar reler o arquivo."""
    progress = load_progress(path)
    entry = progress.get(stage_id, {"modifiers": frozenset(), "best_rank": None})
    merged_modifiers = set(entry["modifiers"])
    merged_modifiers.update(active_modifiers)
    best_rank = entry["best_rank"]
    if rank is not None and _rank_is_better(rank, best_rank):
        best_rank = rank
    progress[stage_id] = {"modifiers": frozenset(merged_modifiers), "best_rank": best_rank}

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with open(destination, "w", encoding="utf-8") as f:
        json.dump(
            {
                sid: {"modifiers": sorted(e["modifiers"]), "best_rank": e["best_rank"]}
                for sid, e in progress.items()
            },
            f,
        )
    return progress


def delete_progress(path: str = PLAYER_PROGRESS_PATH) -> None:
    """Developer Tools -- Reset de Save (Wipe): apaga `player_progress.json`
    do disco, se existir. `Path.unlink(missing_ok=True)` (nao
    `os.remove`, que levantaria `FileNotFoundError` num arquivo ja
    ausente) -- cross-platform de verdade (Windows/Linux/Mac, mesmo
    `pathlib` usado no resto deste modulo) e idempotente: chamar 2x
    seguidas (ou num progresso que nunca existiu) nunca levanta. NAO
    mexe em `player_lifetime_stats.json`/`user_settings.json` -- so' o
    progresso de fases/musicas. Quem chama (`HertzGameLoop`) tambem
    precisa zerar o cache em-memoria (`self._player_progress = {}`),
    nunca feito automaticamente aqui (esta funcao so' cuida do disco)."""
    Path(path).unlink(missing_ok=True)
