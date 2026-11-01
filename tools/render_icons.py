#!/usr/bin/env python3
"""Иконки приложения — для установки на телефон.

Chrome просит иконки в манифесте: 192×192 и 512×512 для обычных, плюс
512×512 maskable (с безопасной зоной) для Android. Без них пункт
«Установить приложение» не появляется.

Иконка рисуется здесь, а не хранится готовой: палитра живёт в
`client/style.css`, и иконка обязана быть из неё же. Размеры — аргумент,
поэтому один и тот же рисунок годится и для 192, и для 512.

Запуск:
    python3 tools/render_icons.py

Результат:
    client/icons/icon-192.png
    client/icons/icon-512.png
    client/icons/icon-maskable-512.png
    client/icons/icon.svg
"""
from __future__ import annotations

import re
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
CSS = ROOT / "client" / "style.css"
OUT = ROOT / "client" / "icons"

# Палитра — из :root в style.css. Читаем оттуда, чтобы иконка и интерфейс
# были из одного источника.
PALETTE_RE = re.compile(r"(--[\w-]+):\s*(#[0-9a-fA-F]{3,8});")


def palette() -> dict[str, str]:
    """Переменные из `:root` в style.css."""
    css = CSS.read_text(encoding="utf-8")
    root = css[css.find(":root"):css.find("}", css.find(":root"))]
    return {name: value for name, value in PALETTE_RE.findall(root)}


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def draw_icon(size: int, colors: dict[str, str], *, maskable: bool = False) -> Image.Image:
    """Рисунок иконки.

    Что на ней: тёмный квадрат с кругом-«диском» и полосой беговой дорожки.
    Смысл — приложение про тренировки, а не абстрактный значок.

    Maskable-версия: рисунок занимает меньше места и сдвинут в центр —
    Android обрезает иконку по своей маске (круг, скруглённый квадрат),
    и полноразмерный рисунок срезался бы по краям.
    """
    bg = hex_to_rgb(colors["--bg"])
    accent = hex_to_rgb(colors["--accent"])
    accent2 = hex_to_rgb(colors["--accent2"])
    text = hex_to_rgb(colors["--text"])

    image = Image.new("RGB", (size, size), bg)
    draw = ImageDraw.Draw(image)

    # Маскаable: безопасная зона — центральные 80 % (по спецификации Android
    # круг маски захватывает 80 % ширины).
    scale = 0.8 if maskable else 0.92
    center = size / 2
    radius = size * scale / 2

    # Диск-подложка.
    draw.ellipse(
        [center - radius, center - radius, center + radius, center + radius],
        fill=hex_to_rgb(colors["--panel"]),
    )

    # Дорожка: три полосы разной длины, как у беговых тренировок.
    bar_h = size * 0.075
    gap = size * 0.045
    widths = [0.46, 0.34, 0.22]
    top = center - (3 * bar_h + 2 * gap) / 2
    for index, ratio in enumerate(widths):
        width = size * ratio
        y0 = top + index * (bar_h + gap)
        color = accent if index == 0 else (accent2 if index == 1 else text)
        draw.rounded_rectangle(
            [center - width / 2, y0, center + width / 2, y0 + bar_h],
            radius=bar_h / 2,
            fill=color,
        )

    return image


def main() -> int:
    colors = palette()
    OUT.mkdir(parents=True, exist_ok=True)

    for size, name in ((192, "icon-192.png"), (512, "icon-512.png")):
        path = OUT / name
        draw_icon(size, colors).save(path, "PNG", optimize=True)
        print(f"written: {path.relative_to(ROOT)} ({path.stat().st_size} B)")

    path = OUT / "icon-maskable-512.png"
    draw_icon(512, colors, maskable=True).save(path, "PNG", optimize=True)
    print(f"written: {path.relative_to(ROOT)} ({path.stat().st_size} B)")

    # SVG — векторная версия для favicon и для браузеров, которые просят SVG.
    svg = _svg(colors)
    path = OUT / "icon.svg"
    path.write_text(svg, encoding="utf-8")
    print(f"written: {path.relative_to(ROOT)} ({path.stat().st_size} B)")

    return 0


def _svg(colors: dict[str, str]) -> str:
    """SVG-версия иконки — те же формы, что и в PNG."""
    bg = colors["--bg"]
    panel = colors["--panel"]
    accent = colors["--accent"]
    accent2 = colors["--accent2"]
    text = colors["--text"]
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
  <rect width="512" height="512" fill="{bg}"/>
  <circle cx="256" cy="256" r="235" fill="{panel}"/>
  <rect x="138" y="200" width="236" height="38" rx="19" fill="{accent}"/>
  <rect x="171" y="252" width="170" height="38" rx="19" fill="{accent2}"/>
  <rect x="200" y="304" width="112" height="38" rx="19" fill="{text}"/>
</svg>
"""


if __name__ == "__main__":
    raise SystemExit(main())
