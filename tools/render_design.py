#!/usr/bin/env python3
"""
render_design.py — собрать документы дизайна Coach App в один HTML.

Запуск:
    python3 tools/render_design.py

На входе:  design/*.md  (девять файлов)
На выходе: DESIGN.html (self-contained, читается с телефона офлайн)
"""
from __future__ import annotations

import html
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DESIGN = os.path.join(ROOT, "specs", "design")
OUT = os.path.join(ROOT, "DESIGN.html")

C = {
    "bg": "#fdf6ed", "card": "#fffefb", "ink": "#1a1a1a", "muted": "#6a6056",
    "faint": "#9a9085", "border": "#e6dac4", "code": "#f4ede0",
    "planner": "#c2410c", "state": "#0284c7", "fact": "#0b7d71",
    "delivery": "#a17405", "narrator": "#7c3aed", "entry": "#d4a017",
}

FILES = [
    ("00-index.md", "Карта", "что уже есть и что предложено"),
    ("01-контракты.md", "Контракты", "как подсистемы общаются"),
    ("02-хранилище.md", "Хранилище", "где состояние и как пишется"),
    ("03-BFF.md", "BFF", "HTTP-слой"),
    ("04-хостинг.md", "Хостинг", "доступ дома и снаружи"),
    ("05-клиент.md", "Клиент", "PWA, офлайн, очередь команд"),
    ("06-адаптеры.md", "Адаптеры", "Garmin, Stryd, календарь, нарратор"),
    ("07-реализация.md", "Реализация", "этапы и что не входит в базу"),
    ("08-развилки.md", "Развилки", "вопросы, на которые нужен ответ"),
]


def esc(s: str) -> str:
    return html.escape(s, quote=False)


def inline(s: str) -> str:
    """Мини-разметка: `код`, **жирный**."""
    s = esc(s)
    s = re.sub(r"`([^`]+)`", r'<code>\1</code>', s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", s)
    return s


def md_to_html(md: str) -> str:
    """Markdown → HTML. Поддерживает: h1-h4, таблицы, код-блоки, списки, blockquote, абзацы."""
    out: list[str] = []
    lines = md.split("\n")
    i = 0
    in_list = False
    in_ol = False

    def close_lists():
        nonlocal in_list, in_ol
        if in_list:
            out.append("</ul>")
            in_list = False
        if in_ol:
            out.append("</ol>")
            in_ol = False

    while i < len(lines):
        ln = lines[i]
        s = ln.strip()

        if not s:
            close_lists()
            i += 1
            continue

        # код-блок
        if s.startswith("```"):
            close_lists()
            i += 1
            buf = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1
            out.append("<pre><code>" + esc("\n".join(buf)) + "</code></pre>")
            continue

        # таблица: строка с | и следующая разделитель
        if "|" in s and i + 1 < len(lines) and re.match(r"^\|[\s:|-]+\|$", lines[i + 1].strip()):
            close_lists()
            head = [c.strip() for c in s.strip("|").split("|")]
            i += 2
            rows = []
            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            out.append('<div class="tw"><table><tr>')
            out += [f"<th>{inline(h)}</th>" for h in head]
            out.append("</tr>")
            for r in rows:
                out.append("<tr>")
                out += [f"<td>{inline(c)}</td>" for c in r]
                out.append("</tr>")
            out.append("</table></div>")
            continue

        # заголовки
        m = re.match(r"^(#{1,4})\s+(.*)$", s)
        if m:
            close_lists()
            lvl = len(m.group(1))
            out.append(f"<h{lvl}>{inline(m.group(2))}</h{lvl}>")
            i += 1
            continue

        # цитата
        if s.startswith("> "):
            close_lists()
            out.append(f'<blockquote>{inline(s[2:])}</blockquote>')
            i += 1
            continue

        # горизонтальная линия
        if set(s) <= {"-", " "} and len(s) >= 3:
            close_lists()
            out.append("<hr>")
            i += 1
            continue

        # нумерованный список
        m = re.match(r"^(\d+)\.\s+(.*)$", s)
        if m:
            if in_list:
                out.append("</ul>")
                in_list = False
            if not in_ol:
                out.append("<ol>")
                in_ol = True
            out.append(f"<li>{inline(m.group(2))}</li>")
            i += 1
            continue

        # маркированный список
        m = re.match(r"^[-*]\s+(.*)$", s)
        if m:
            if in_ol:
                out.append("</ol>")
                in_ol = False
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{inline(m.group(1))}</li>")
            i += 1
            continue

        close_lists()
        out.append(f"<p>{inline(s)}</p>")
        i += 1

    close_lists()
    return "\n".join(out)


def main() -> int:
    sections: list[tuple[str, str, str, str]] = []
    for fname, short, sub in FILES:
        p = os.path.join(DESIGN, fname)
        if not os.path.exists(p):
            print(f"MISSING: {p}", file=sys.stderr)
            return 1
        with open(p, encoding="utf-8") as f:
            md = f.read()
        body = md_to_html(md)
        # первый h1 — заголовок файла, выносим в шапку секции
        body = re.sub(r"^<h1>.*?</h1>\s*", "", body, count=1, flags=re.S)
        sections.append((fname, short, sub, body))

    o: list[str] = []
    A = o.append
    A("<!DOCTYPE html>")
    A('<html lang="ru"><head><meta charset="UTF-8">')
    A('<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">')
    A("<title>Coach App — дизайн</title>")
    A(f"""<style>
  :root {{
    --bg:{C['bg']}; --card-bg:{C['card']}; --ink:{C['ink']}; --muted:{C['muted']};
    --faint:{C['faint']}; --border:{C['border']}; --code-bg:{C['code']};
    --planner:{C['planner']}; --state:{C['state']}; --fact:{C['fact']};
    --delivery:{C['delivery']}; --narrator:{C['narrator']}; --entry:{C['entry']};
  }}
  * {{ box-sizing:border-box; margin:0; padding:0; }}
  html {{ -webkit-text-size-adjust:100%; }}
  body {{ font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
    background:var(--bg); color:var(--ink); line-height:1.5; font-size:16px; padding-bottom:48px; }}
  code {{ font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; font-size:.92em; }}

  header {{ padding:16px 14px 12px; border-bottom:1px solid var(--border); background:var(--card-bg); }}
  header h1 {{ font-size:19px; font-weight:700; }}
  header .sub {{ font-size:12.5px; color:var(--muted); margin-top:4px; }}
  header .meta {{ font-size:11px; color:var(--faint); margin-top:6px; }}

  nav {{ position:sticky; top:0; z-index:10; background:rgba(253,246,237,.96); backdrop-filter:blur(8px);
    border-bottom:1px solid var(--border); overflow-x:auto; white-space:nowrap; padding:7px 12px; scrollbar-width:none; }}
  nav::-webkit-scrollbar {{ display:none; }}
  nav a {{ display:inline-block; font-size:12px; color:var(--muted); text-decoration:none;
    padding:4px 9px; margin-right:4px; border:1px solid var(--border); border-radius:999px; background:var(--card-bg); }}

  main {{ padding:0 12px; max-width:780px; margin:0 auto; }}
  section {{ margin-top:26px; }}
  .h2 {{ font-size:16px; font-weight:700; padding-bottom:6px; border-bottom:2px solid var(--ink);
    margin-bottom:10px; display:flex; align-items:baseline; gap:8px; flex-wrap:wrap; }}
  .h2 .fn {{ font-size:10.5px; font-weight:400; color:var(--faint); font-family:ui-monospace,monospace; }}
  h1 {{ font-size:19px; font-weight:700; margin:4px 0 12px; }}
  h2 {{ font-size:16px; font-weight:700; margin:18px 0 7px; padding-bottom:5px; border-bottom:1px solid var(--border); }}
  h3 {{ font-size:14px; font-weight:700; margin:14px 0 5px; }}
  h4 {{ font-size:13px; font-weight:700; margin:12px 0 4px; color:var(--muted); }}
  p {{ font-size:14.5px; margin-bottom:8px; }}
  ul,ol {{ margin:0 0 9px; padding-left:22px; font-size:14px; }}
  li {{ margin-bottom:4px; }}
  blockquote {{ border-left:3px solid var(--border); padding:2px 0 2px 10px; margin:0 0 9px;
    color:var(--muted); font-size:13.5px; }}
  pre {{ background:var(--code-bg); border:1px solid var(--border); border-radius:8px; padding:9px 11px;
    overflow-x:auto; margin:0 0 10px; font-size:12px; line-height:1.45; }}
  pre code {{ font-size:12px; }}
  hr {{ border:none; border-top:1px solid var(--border); margin:18px 0; }}
  b {{ font-weight:700; }}

  .tw {{ overflow-x:auto; -webkit-overflow-scrolling:touch; margin:6px 0 12px; position:relative; }}
  table {{ border-collapse:collapse; width:100%; min-width:440px; font-size:12.5px; }}
  th,td {{ text-align:left; padding:6px 7px; border-bottom:1px solid var(--border); vertical-align:top; }}
  th {{ font-size:10.5px; text-transform:uppercase; letter-spacing:.04em; color:var(--muted);
    font-weight:700; background:var(--code-bg); }}
  td code {{ font-size:11.5px; }}

  @media (max-width:560px) {{
    main {{ padding:0 10px; }}
    header h1 {{ font-size:17px; }}
    p {{ font-size:14px; }}
    table {{ min-width:400px; font-size:12px; }}
    .tw::after {{ content:'→ свайп'; position:absolute; right:2px; bottom:2px; font-size:9px;
      color:var(--faint); background:var(--card-bg); padding:0 4px; pointer-events:none; }}
  }}
</style></head><body>""")

    A("<header>")
    A("<h1>Coach App — дизайн</h1>")
    A('<div class="sub">девять файлов: контракты, хранилище, BFF, хостинг, клиент, адаптеры, реализация, развилки</div>')
    A(f'<div class="meta">{len(FILES)} разделов · уровень: контрактный и физический · 26.10.2026 · '
      f'источник: design/*.md</div>')
    A("</header>")

    A("<nav>")
    for idx, (fname, short, sub, _body) in enumerate(sections):
        A(f'<a href="#s{idx}">{short}</a>')
    A("</nav>")

    A("<main>")
    for idx, (fname, short, sub, body) in enumerate(sections):
        A(f'<section id="s{idx}">')
        A(f'<div class="h2">{esc(short)}<span class="fn">{esc(fname)}</span></div>')
        A(body)
        A("</section>")
    A("</main></body></html>")

    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(o))

    print(f"written: {OUT} ({os.path.getsize(OUT)} bytes)")
    print(f"sections={len(sections)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
