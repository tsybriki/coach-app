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

Результат (с версией в имени — Chrome по URL обновляет иконку
установленного приложения, а по содержимому файла — нет):
    client/icons/icon-192-v2.png
    client/icons/icon-512-v2.png
    client/icons/icon-maskable-512-v2.png
    client/icons/icon-v2.svg

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

import base64
import io
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "client" / "icons"
SOURCE = OUT / "icon-source.png"

# Фон иконки — цвет темы приложения (`--bg` в `client/style.css`).
# Тёмный: иначе маска Android показала бы серый прямоугольник.
BG = (15, 17, 21)

# Версия иконки — в имени файла.
#
# Chrome обновляет иконку установленного PWA, только если изменился URL
# иконки: новый файл под старым URL он не подхватит, и значок останется
# прежним, пока приложение не удалят и не поставят заново. Поэтому при
# смене картинки версия поднимается: icon-v2.png вместо icon-v1.png.
#
# Меняешь знак — поднимай версию здесь.
VERSION = 2
SUFFIX = f"-v{VERSION}"

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


def write_svg(master: Image.Image, path: Path) -> None:
    """SVG-версия — знак, встроенный в SVG как data URI.

    **Растр внутри, а не ссылка на файл.** SVG, загруженный как `<img>`,
    по правилам безопасности не грузит внешние ресурсы: обёртка со
    `<image href="icon-source.png">` показывала пустой фон. Поэтому растр
    встраивается прямо в SVG.

    Свой SVG рисовать вручную нельзя: знак пришёл картинкой.
    """
    embedded = master.resize((256, 256), Image.LANCZOS)
    embedded = embedded.quantize(colors=256, method=Image.FASTOCTREE)
    buffer = io.BytesIO()
    embedded.save(buffer, "PNG", optimize=True)
    data = base64.b64encode(buffer.getvalue()).decode("ascii")

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 256 256">
  <rect width="256" height="256" fill="rgb({BG[0]},{BG[1]},{BG[2]})"/>
  <image width="256" height="256" xlink:href="data:image/png;base64,{data}"/>
</svg>
"""
    path.write_text(svg, encoding="utf-8")
    print(f"written: {path.relative_to(ROOT)} ({path.stat().st_size} B)")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    master = load_master()

    for size, name in ((192, "icon-192.png"), (512, "icon-512.png")):
        path = OUT / f"icon-{size}{SUFFIX}.png"
        render(size, master).save(path, "PNG", optimize=True)
        print(f"written: {path.relative_to(ROOT)} ({path.stat().st_size} B)")

    path = OUT / f"icon-maskable-512{SUFFIX}.png"
    render(512, master, maskable=True).save(path, "PNG", optimize=True)
    print(f"written: {path.relative_to(ROOT)} ({path.stat().st_size} B)")

    path = OUT / f"icon{SUFFIX}.svg"
    write_svg(master, path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
