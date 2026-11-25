#!/usr/bin/env python3
"""Иконки приложения — для установки на телефон.

Chrome просит иконки в манифесте: 192×192 и 512×512 для обычных, плюс
512×512 maskable (с безопасной зоной) для Android. Без них пункт
«Установить приложение» не появляется.

Иконка — **готовая картинка**, а не рисунок из палитры: Кирилл прислал
знак «Чёрный тренер» (25.11.2026), и рисовать его кодом бессмысленно.
Мастер-файл — `client/icons/icon-source.png`, он и есть источник правды.

Запуск:
    python3 tools/render_icons.py

Результат:
    client/icons/icon-192.png
    client/icons/icon-512.png
    client/icons/icon-maskable-512.png
    client/icons/icon.svg

**Maskable-версия — с запасом.** Android обрезает иконку по своей маске
(круг, скруглённый квадрат): рисунок в полный размер срезался бы по
краям, и обрезалась бы именно надпись. Поэтому maskable-иконка — тот же
знак, уменьшенный до 80 % и с фоном в цвет темы.

**Почему SVG — обёртка, а не векторная иконка.** Мастер — растр, и
перерисовывать его в SVG вручную значит рисовать знак заново. SVG
делается как `<image>` поверх цветного фона: браузеры, которые просят
SVG-иконку, получают тот же знак.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "client" / "icons"
SOURCE = OUT / "icon-source.png"

# Фон иконки — цвет темы приложения (`--bg` в `client/style.css`).
# Тёмный: иначе маска Android показала бы серый прямоугольник.
BG = (15, 17, 21)

# Мастер — 1140×1150. Держим его в PNG с альфа-каналом.
MASTER_SIZE = 1024


def load_master() -> Image.Image:
    """Мастер-файл знака — RGBA с прозрачными углами."""
    if not SOURCE.exists():
        raise SystemExit(
            f"нет мастер-файла иконки: {SOURCE.relative_to(ROOT)}\n"
            "Положить знак в client/icons/icon-source.png и запустить снова."
        )
    image = Image.open(SOURCE).convert("RGBA")
    # Квадрат по большей стороне, знак по центру.
    side = max(image.size)
    square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    square.paste(image, ((side - image.size[0]) // 2,
                         (side - image.size[1]) // 2), image)
    return square


def render(size: int, master: Image.Image, *, maskable: bool = False) -> Image.Image:
    """Иконка заданного размера.

    Обычная: знак во весь размер — она и есть витрина.

    Maskable: безопасная зона Android — центральные 80 % (по спецификации
    круг маски захватывает 80 % ширины). Знак уменьшается, а фон
    заливается цветом темы: иначе по краям маски оставалась бы
    прозрачность, а система подставила бы своё.
    """
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))

    if maskable:
        canvas = Image.new("RGBA", (size, size), BG + (255,))
        inner = int(size * 0.8)
        scaled = master.resize((inner, inner), Image.LANCZOS)
        offset = (size - inner) // 2
        canvas.paste(scaled, (offset, offset), scaled)
        return canvas

    scaled = master.resize((size, size), Image.LANCZOS)
    canvas.paste(scaled, (0, 0), scaled)
    return canvas


def write_svg(master: Image.Image) -> None:
    """SVG-версия — обёртка с растра.

    Браузеры, просящие SVG-иконку, получают тот же знак. Свой SVG
    рисовать вручную нельзя: знак пришёл картинкой.
    """
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 {MASTER_SIZE} {MASTER_SIZE}">
  <rect width="{MASTER_SIZE}" height="{MASTER_SIZE}" fill="rgb({BG[0]},{BG[1]},{BG[2]})"/>
  <image width="{MASTER_SIZE}" height="{MASTER_SIZE}" xlink:href="icon-source.png"/>
</svg>
"""
    path = OUT / "icon.svg"
    path.write_text(svg, encoding="utf-8")
    print(f"written: {path.relative_to(ROOT)} ({path.stat().st_size} B)")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    master = load_master()

    for size, name in ((192, "icon-192.png"), (512, "icon-512.png")):
        path = OUT / name
        render(size, master).save(path, "PNG", optimize=True)
        print(f"written: {path.relative_to(ROOT)} ({path.stat().st_size} B)")

    path = OUT / "icon-maskable-512.png"
    render(512, master, maskable=True).save(path, "PNG", optimize=True)
    print(f"written: {path.relative_to(ROOT)} ({path.stat().st_size} B)")

    write_svg(master)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
