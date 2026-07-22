"""Sparks (Juice Visual): rajada de linhas curtas no acerto PERFECT, Zero-GC sobre um pool fixo de faiscas."""
from __future__ import annotations

import math
import random

import numpy as np

from ouroboros.core.systems.base_system import ISystem
from ouroboros.core.world import World

_TAU = 2.0 * math.pi

SPARK_DTYPE = np.dtype(
    [
        ("x", np.float32),
        ("y", np.float32),
        ("angle", np.float32),
        ("length", np.float32),
        ("expire_time_sec", np.float32),
    ]
)
"""Estado de UMA faisca (o "SparkPool" do pedido): campos primitivos,
sem nenhuma entidade do `World` por tras -- puramente cosmetico (nunca
participa de colisao/julgamento), entao nao precisa da maquina completa
de arquetipos/pools do ECS. `expire_time_sec` e um CONTADOR REGRESSIVO
(segundos restantes ate sumir -- MESMO idioma de
`judgment_display_seconds_left`/`blindness_timer_sec`, nunca um
timestamp absoluto): ao chegar a 0.0 a faisca fica invisivel (alfa 0,
ver `render_arrays`) e o slot fica livre para reaproveitamento
round-robin, sem precisar de nenhum flag "ativo" separado."""


class SparkSystem(ISystem):
    """
    Juice Visual -- Sparks: pool FIXO de `pool_size` faiscas (128 por
    padrao), pre-alocado UMA unica vez no construtor. `emit_burst` e
    chamado DIRETAMENTE pelo `JudgmentSystem` a cada acerto PERFECT
    (mesmo padrao de referencia direta entre sistemas ja usado por
    `ParryImpactSystem` <- `CollisionSystem`) e ativa `count` slots em
    ROUND-ROBIN -- reaproveita os slots mais antigos sem checar se
    ainda estao "vivos" (pool pequeno e puramente cosmetico; mesmo
    criterio ja aceito por `ShockwaveSystem`/`DistractionSystem`).

    `update()` decai `expire_time_sec` de TODAS as faiscas por
    `delta_time` de FRAME (game feel, nao evento ritmico), vetorizado
    sobre o array inteiro (128 elementos, sempre com `out=`) -- nunca
    aloca.

    NAO passa pelo `draw_batch` generico do ECS (nenhuma faisca e uma
    entidade do `World`, so um array SoA solto): `render_arrays()`
    devolve os buffers PRONTOS para o `HBPygameRenderer` desenhar via
    `pygame.draw.line` diretamente (`HertzGameLoop._sync_sparks`, mesma
    familia de sincronizacao apresentacao<-estado de
    `_sync_camera_shake`), sempre sobre buffers pre-alocados (nunca
    aloca por frame).
    """

    def __init__(
        self,
        pool_size: int = 128,
        lifetime_seconds: float = 0.22,
        max_length: float = 24.0,
    ) -> None:
        self._sparks = np.zeros(pool_size, dtype=SPARK_DTYPE)
        self._pool_size = int(pool_size)
        self._lifetime_seconds = float(lifetime_seconds)
        self._max_length = float(max_length)
        self._next_slot = 0

        # buffers de SAIDA pre-alocados (nunca recriados por frame) --
        # `render_arrays` so escreve neles via `out=`.
        self._render_length = np.zeros(pool_size, dtype=np.float32)
        self._render_alpha = np.zeros(pool_size, dtype=np.float32)
        self._fraction_buffer = np.zeros(pool_size, dtype=np.float32)

    def emit_burst(self, x: float, y: float, count: int) -> None:
        """Ativa `count` faiscas (tipicamente 4-6) partindo de `(x, y)`,
        cada uma num angulo aleatorio -- `random` aqui e puramente
        cosmetico (nunca decide um veredito de jogabilidade), mesmo
        criterio ja aceito para `random.uniform` em
        `HertzGameLoop._sync_camera_shake`. Laco escalar deliberado: 4-6
        iteracoes por rajada, tipicamente 0-1 rajada por frame."""
        sparks = self._sparks
        pool_size = self._pool_size
        for _ in range(int(count)):
            slot = self._next_slot
            self._next_slot = (self._next_slot + 1) % pool_size
            sparks["x"][slot] = x
            sparks["y"][slot] = y
            sparks["angle"][slot] = random.uniform(0.0, _TAU)
            sparks["length"][slot] = self._max_length
            sparks["expire_time_sec"][slot] = self._lifetime_seconds

    def update(self, world: World, delta_time: float) -> None:
        del world
        expire = self._sparks["expire_time_sec"]
        np.subtract(expire, delta_time, out=expire)
        np.maximum(expire, 0.0, out=expire)

    def render_arrays(self):
        """Retorna `(xs, ys, angles, lengths, alphas, pool_size)`
        prontos para o renderer -- vetorizado sobre buffers
        pre-alocados, nunca recriados. `fraction` (1.0 recem-nascida ->
        0.0 morrendo) decide as DUAS pontas do efeito ao mesmo tempo: o
        COMPRIMENTO cresce de 0 ate `length` conforme a faisca envelhece
        (o "esticam" do pedido) enquanto o ALFA cai de 255 a 0 (o
        "somem")."""
        sparks = self._sparks
        fraction = self._fraction_buffer
        np.divide(sparks["expire_time_sec"], self._lifetime_seconds, out=fraction)

        stretched_length = self._render_length
        np.subtract(1.0, fraction, out=stretched_length)
        np.multiply(stretched_length, sparks["length"], out=stretched_length)

        # a partir daqui `fraction` nao e mais necessaria -- reaproveita
        # o MESMO buffer pro alfa (nunca aloca um array novo).
        np.multiply(fraction, 255.0, out=fraction)
        np.copyto(self._render_alpha, fraction)

        return (
            sparks["x"],
            sparks["y"],
            sparks["angle"],
            stretched_length,
            self._render_alpha,
            self._pool_size,
        )
