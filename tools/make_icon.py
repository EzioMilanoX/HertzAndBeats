"""
Gera o icone do jogo (assets/icon.png + assets/hertz_beats.ico) com o
motivo radial da arena: nucleo no centro, anel de julgamento dourado e
ameacas chegando pela borda. O .ico embute o PNG 256x256 (formato
suportado pelo Windows Vista+), montado com stdlib struct -- sem PIL.

Uso (a partir da raiz do repositorio):
    python tools/make_icon.py
"""
from __future__ import annotations

import math
import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pygame

SIZE = 256
PNG_PATH = Path("assets/icon.png")
ICO_PATH = Path("assets/hertz_beats.ico")


def draw_icon() -> "pygame.Surface":
    pygame.init()
    surface = pygame.Surface((SIZE, SIZE), pygame.SRCALPHA)
    center = SIZE // 2

    pygame.draw.circle(surface, (8, 6, 20, 255), (center, center), 126)
    pygame.draw.circle(surface, (90, 70, 160, 255), (center, center), 120, 8)
    pygame.draw.circle(surface, (36, 28, 70, 255), (center, center), 96, 3)

    # ameacas convergindo pela borda (mesma paleta do jogo)
    for angle_deg in (90, 210, 330):
        angle = math.radians(angle_deg)
        x = center + int(math.cos(angle) * 84)
        y = center - int(math.sin(angle) * 84)
        pygame.draw.circle(surface, (255, 80, 96, 255), (x, y), 15)

    pygame.draw.circle(surface, (255, 214, 64, 255), (center, center), 48, 7)  # anel de julgamento
    pygame.draw.circle(surface, (240, 240, 255, 255), (center, center), 30)  # nucleo

    return surface


def write_ico(png_path: Path, ico_path: Path) -> None:
    png_bytes = png_path.read_bytes()
    icondir = struct.pack("<HHH", 0, 1, 1)
    # largura/altura 0 = 256; 1 plano; 32 bpp; PNG embutido no offset 22
    entry = struct.pack("<BBBBHHII", 0, 0, 0, 0, 1, 32, len(png_bytes), 22)
    ico_path.write_bytes(icondir + entry + png_bytes)


def main() -> int:
    PNG_PATH.parent.mkdir(parents=True, exist_ok=True)
    surface = draw_icon()
    pygame.image.save(surface, str(PNG_PATH))
    write_ico(PNG_PATH, ICO_PATH)
    print(f"icone gerado: {PNG_PATH} + {ICO_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
