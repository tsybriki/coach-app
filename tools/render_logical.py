#!/usr/bin/env python3
"""
render_logical.py — рендер логического уровня Coach App из logical.json.

Запуск:
    python3 tools/render_logical.py

На входе:  specs/logical/logical.json (source of truth)
На выходе: LOGICAL.html (self-contained, читается с телефона офлайн)

MD-версия (спецификация/LOGICAL.md) собирается отдельно: tools/build_logical_md.py
"""
from __future__ import annotations

import html
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "specs", "logical", "logical.json")
OUT = os.path.join(ROOT, "LOGICAL.html")

# палитра — из DOMAIN-SPEC.html (домен Coach App)
C = {
    "bg": "#fdf6ed",
    "card": "#fffefb",
    "ink": "#1a1a1a",
    "muted": "#6a6056",
    "faint": "#9a9085",
    "border": "#e6dac4",
    "code": "#f4ede0",
    "src": "#6a6056",
    "decide": "#c2410c",
    "observe": "#0b7d71",
    "out": "#a17405",
    "contour": "#7c3aed",
}

FILL = {
    "src": "rgba(106,96,86,0.07)",
    "decide": "rgba(194,65,12,0.07)",
    "observe": "rgba(20,184,166,0.08)",
    "out": "rgba(212,160,23,0.09)",
    "contour": "rgba(124,58,237,0.07)",
}


def esc(s) -> str:
    return html.escape(str(s), quote=True)


def svg_diagram(d: dict) -> str:
    p: list[str] = [f'<svg viewBox="{esc(d["viewBox"])}" role="img" aria-label="Логические подсистемы">']

    for a in d.get("arrows", []):
        p.append(
            f'<path d="{esc(a["path"])}" fill="none" stroke="{C["muted"]}" stroke-width="1.2" '
            f'stroke-dasharray="5,3" marker-end="url(#ar)"/>'
        )
        bx, by = a["badge"]
        p.append(
            f'<circle cx="{bx}" cy="{by}" r="7.5" fill="{C["card"]}" stroke="{C["muted"]}" stroke-width="1"/>'
        )
        p.append(
            f'<text x="{bx}" y="{by + 2.8}" font-size="8" font-weight="700" fill="{C["muted"]}" '
            f'text-anchor="middle">{esc(a["n"])}</text>'
        )

    for s in d.get("strips", []):
        tone = s.get("tone", "src")
        color = C.get(tone, C["muted"])
        fill = FILL.get(tone, "#fff")
        x, y, w, h = s["x"], s["y"], s["w"], s["h"]
        dash = ' stroke-dasharray="7,4"' if tone == "contour" else ""
        p.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="{fill}" stroke="{color}" '
            f'stroke-width="1.3"{dash}/>'
        )
        ty = y + 15
        p.append(f'<text x="{x + 10}" y="{ty}" font-size="10.5" font-weight="700" fill="{color}">'
                 f'{esc(s["title"])}</text>')
        if s.get("sub"):
            ty += 11
            p.append(f'<text x="{x + 10}" y="{ty}" font-size="8.2" fill="{C["faint"]}">'
                     f'{esc(s["sub"])}</text>')
        for ln in s.get("lines", []):
            ty += 11
            p.append(f'<text x="{x + 10}" y="{ty}" font-size="8.3" fill="{C["muted"]}">{esc(ln)}</text>')
        if s.get("chip"):
            ch = s["chip"]
            cy = y + h - 13
            p.append(f'<rect x="{x + 10}" y="{cy - 8}" width="{ch["w"]}" height="12" rx="6" '
                     f'fill="{C["card"]}" stroke="{color}" stroke-width="0.8"/>')
            p.append(f'<text x="{x + 10 + ch["w"] / 2}" y="{cy + 1}" font-size="7.4" fill="{color}" '
                     f'text-anchor="middle">{esc(ch["text"])}</text>')
        if s.get("foot"):
            ty += 11
            p.append(f'<text x="{x + 10}" y="{ty}" font-size="7.6" fill="{C["faint"]}" '
                     f'font-style="italic">{esc(s["foot"])}</text>')

    p.append(
        '<defs><marker id="ar" markerWidth="9" markerHeight="7" refX="8" refY="3.5" orient="auto">'
        f'<polygon points="0 0, 9 3.5, 0 7" fill="{C["muted"]}"/></marker></defs>'
    )
    p.append("</svg>")
    return "\n".join(p)


def render(d: dict) -> str:
    m = d["meta"]
    o: list[str] = []
    A = o.append

    A("<!DOCTYPE html>")
    A('<html lang="ru"><head><meta charset="UTF-8">')
    A('<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">')
    A(f'<title>{esc(d["title"])}</title>')
    A("<style>")
    A(f"""
  :root {{
    --bg:{C['bg']}; --card-bg:{C['card']}; --ink:{C['ink']}; --muted:{C['muted']};
    --faint:{C['faint']}; --border:{C['border']}; --code-bg:{C['code']};
    --src:{C['src']}; --decide:{C['decide']}; --observe:{C['observe']};
    --out:{C['out']}; --contour:{C['contour']};
  }}
  * {{ box-sizing:border-box; margin:0; padding:0; }}
  html {{ -webkit-text-size-adjust:100%; }}
  body {{ font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
    background:var(--bg); color:var(--ink); line-height:1.5; font-size:16px; padding-bottom:48px; }}
  code {{ font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; }}

  header {{ padding:16px 14px 12px; border-bottom:1px solid var(--border); background:var(--card-bg); }}
  header h1 {{ font-size:19px; font-weight:700; }}
  header .sub {{ font-size:12.5px; color:var(--muted); margin-top:4px; }}
  header .meta {{ font-size:11px; color:var(--faint); margin-top:6px; line-height:1.6; }}

  nav {{ position:sticky; top:0; z-index:10; background:rgba(253,246,237,.96); backdrop-filter:blur(8px);
    border-bottom:1px solid var(--border); overflow-x:auto; white-space:nowrap; padding:7px 12px; scrollbar-width:none; }}
  nav::-webkit-scrollbar {{ display:none; }}
  nav a {{ display:inline-block; font-size:12px; color:var(--muted); text-decoration:none;
    padding:4px 9px; margin-right:4px; border:1px solid var(--border); border-radius:999px; background:var(--card-bg); }}

  main {{ padding:0 12px; max-width:780px; margin:0 auto; }}
  section {{ margin-top:26px; }}
  .h2 {{ font-size:16px; font-weight:700; padding-bottom:6px; border-bottom:2px solid var(--ink); margin-bottom:10px; }}
  h3 {{ font-size:14px; font-weight:700; margin:16px 0 6px; }}
  p {{ font-size:14.5px; margin-bottom:8px; }}
  .lead {{ font-size:14px; color:var(--muted); }}
  .muted {{ color:var(--muted); }}

  .dia {{ background:var(--card-bg); border:1px solid var(--border); border-radius:10px; padding:8px; overflow-x:auto; }}
  .dia svg {{ width:100%; min-width:340px; display:block; }}
  .cap {{ font-size:12px; color:var(--muted); margin-top:7px; }}

  .legend {{ display:flex; flex-wrap:wrap; gap:6px 14px; margin-top:9px; }}
  .legend span {{ display:inline-flex; align-items:center; gap:5px; font-size:11.5px; color:var(--muted); }}
  .legend i {{ width:11px; height:11px; border-radius:3px; border:1.5px solid; display:inline-block; }}

  .lvl {{ border:1px solid var(--border); border-radius:8px; background:var(--card-bg); padding:8px 11px;
    margin-bottom:6px; display:grid; grid-template-columns:auto 1fr auto; gap:2px 8px; align-items:baseline; }}
  .lvl .ln {{ font-size:13px; font-weight:700; white-space:nowrap; }}
  .lvl .lq {{ font-size:12.5px; color:var(--muted); }}
  .lvl .ls {{ font-size:10.5px; font-weight:700; padding:1px 8px; border-radius:999px; white-space:nowrap;
    border:1px solid var(--border); background:var(--code-bg); color:var(--faint); }}
  .lvl.now {{ border-color:var(--decide); }}
  .lvl.now .ls {{ background:var(--decide); color:#fff; border-color:var(--decide); }}
  .lvl .ld {{ grid-column:1 / -1; font-size:11.5px; color:var(--faint); margin-top:3px; }}

  .ent {{ border:1px solid var(--border); border-radius:8px; background:var(--card-bg); margin-bottom:8px; overflow:hidden; }}
  .ent .eh {{ background:var(--ink); color:#fff; padding:5px 10px; font-size:13px; font-weight:700;
    display:flex; justify-content:space-between; gap:8px; align-items:center; }}
  .ent .eh .dot {{ width:9px; height:9px; border-radius:50%; flex:0 0 auto; display:inline-block; }}
  .ent .bd {{ padding:9px 11px; font-size:12.5px; }}
  .ent .bd p {{ font-size:12.5px; margin-bottom:6px; }}
  .ent .bd .lab {{ color:var(--faint); font-size:10px; text-transform:uppercase; letter-spacing:.04em; }}
  .ent .bd .f {{ margin-bottom:5px; }}
  .ent .bd .f b {{ font-weight:700; }}
  .ent .bd .bnd {{ font-size:12px; color:var(--muted); border-top:1px solid var(--border);
    padding-top:6px; margin-top:7px; }}

  .ent3 {{ border:1px solid var(--border); border-radius:8px; background:var(--card-bg);
    padding:9px 11px; margin-bottom:8px; }}
  .ent3 .t {{ font-size:13px; font-weight:700; color:var(--decide); margin-bottom:5px; }}
  .ent3 .t .step {{ display:inline-block; min-width:18px; height:18px; line-height:18px; text-align:center;
    border-radius:50%; background:var(--decide); color:#fff; font-size:10px; font-weight:700;
    margin-right:6px; }}
  .ent3 ol {{ margin:0; padding-left:20px; font-size:12.5px; }}
  .ent3 ol li {{ margin-bottom:3px; }}
  .ent3 .kv {{ font-size:12px; margin-top:7px; border-top:1px solid var(--border); padding-top:6px; }}
  .ent3 .kv div {{ margin-bottom:3px; }}
  .ent3 .kv b {{ color:var(--muted); font-weight:700; }}

  .link {{ border:1px solid var(--border); border-radius:8px; background:var(--card-bg);
    padding:8px 10px; margin-bottom:6px; }}
  .link .ln {{ display:flex; align-items:baseline; gap:6px; font-size:12.5px; font-weight:700; }}
  .link .ln .nb {{ display:inline-block; min-width:17px; height:17px; line-height:17px; text-align:center;
    border-radius:50%; background:var(--code-bg); border:1px solid var(--border); color:var(--muted);
    font-size:10px; font-weight:700; flex:0 0 auto; }}
  .link .ln .ar {{ color:var(--faint); font-weight:400; }}
  .link .ln .to {{ color:var(--observe); }}
  .link .lw {{ font-size:12.5px; margin-top:3px; padding-left:23px; }}
  .link .lwh {{ font-size:11.5px; color:var(--faint); margin-top:1px; padding-left:23px; }}

  .fork {{ border:1px solid var(--border); border-radius:8px; background:var(--card-bg); padding:9px 11px; margin-bottom:8px; }}
  .fork .fq {{ font-size:13px; font-weight:700; margin-bottom:6px; }}
  .fork .opt {{ font-size:12.5px; margin-bottom:4px; }}
  .fork .ch {{ font-size:12px; color:var(--muted); margin-top:6px; }}

  .note {{ background:var(--code-bg); border:1px solid var(--border); border-radius:8px;
    padding:9px 11px; font-size:12.5px; margin-bottom:8px; }}

  .phys {{ font-size:12.5px; padding:7px 0; border-bottom:1px solid var(--border); }}
  .phys .pf {{ font-weight:700; margin-bottom:1px; display:block; }}
  .phys .pt {{ color:var(--muted); font-size:12px; display:block; }}

  hr {{ border:none; border-top:1px solid var(--border); margin:22px 0 0; }}
  .end {{ text-align:center; font-size:11.5px; color:var(--faint); padding:20px 0 8px; }}

  @media (max-width:560px) {{
    main {{ padding:0 10px; }}
    header h1 {{ font-size:17px; }}
    p {{ font-size:14px; }}
    .tw::after {{ content:'→ свайп'; position:absolute; right:2px; bottom:2px; font-size:9px;
      color:var(--faint); background:var(--card-bg); padding:0 4px; pointer-events:none; }}
  }}
""")
    A("</style></head><body>")

    A("<header>")
    A(f'<h1>{esc(d["title"])}</h1>')
    A(f'<div class="sub">{esc(d["subtitle"])}</div>')
    A(f'<div class="meta">v{esc(d["version"])} · подсистем: {m["subsystems"]} · '
      f'взаимодействий: {m["interactions"]} · развилок: {m["forks"]}</div>')
    A(f'<div class="meta">уровень: {esc(m["level"])}</div>')
    A("</header>")

    A("<nav>")
    A('<a href="#l">1 · Уровни</a>')
    A('<a href="#d">2 · Схема</a>')
    A('<a href="#p">3 · Планировщик</a>')
    A('<a href="#s">4 · Подсистемы</a>')
    A('<a href="#i">5 · Взаимодействия</a>')
    A('<a href="#ph">6 · Физика</a>')
    A('<a href="#f">7 · Развилки</a>')
    A("</nav>")

    A("<main>")

    A('<section id="l">')
    A('<div class="h2">1 · Уровни абстракции</div>')
    for lv in d["levels"]:
        cls = "lvl now" if lv["state"].startswith("проработан") else "lvl"
        A(f'<div class="{cls}">')
        A(f'<span class="ln">{esc(lv["name"])}</span>')
        A(f'<span class="lq">{esc(lv["q"])}</span>')
        A(f'<span class="ls">{esc(lv["state"])}</span>')
        A(f'<span class="ld">{esc(lv["detail"])}</span>')
        A("</div>")
    A("</section>")

    A('<section id="d">')
    A('<div class="h2">2 · Схема</div>')
    A(f'<p class="lead">{esc(d["lead"])}</p>')
    A('<div class="dia">')
    A(svg_diagram(d["diagram"]))
    A("</div>")
    A('<div class="legend">')
    for lg in d["diagram"]["legend"]:
        color = C.get(lg["tone"], C["muted"])
        A(f'<span><i style="border-color:{color};background:{FILL.get(lg["tone"], "#fff")}"></i>'
          f'{esc(lg["text"])}</span>')
    A("</div>")
    A(f'<p class="cap">{esc(d["diagram"]["caption"])}</p>')
    A("</section>")

    A('<section id="p">')
    A('<div class="h2">3 · Планировщик</div>')
    A(f'<p class="lead">{esc(d["planner"]["lead"])}</p>')
    for i, e in enumerate(d["planner"]["entries"], 1):
        A('<div class="ent3">')
        A(f'<div class="t"><span class="step">{i}</span>{esc(e["name"])}</div>')
        A('<ol>')
        for s in e["steps"]:
            A(f'<li>{esc(s)}</li>')
        A("</ol>")
        A('<div class="kv">')
        A(f'<div><b>вход</b> {esc(e["input"])}</div>')
        A(f'<div><b>цифры</b> {esc(e["numbers"])}</div>')
        if e.get("have"):
            A(f'<div><b>есть</b> {esc(e["have"])}</div>')
        if e.get("missing"):
            A(f'<div><b>нет</b> {esc(e["missing"])}</div>')
        A("</div>")
        A("</div>")
    A("</section>")

    A('<section id="s">')
    A('<div class="h2">4 · Подсистемы</div>')
    for s in d["subsystems"]:
        color = C.get(s.get("tone", "src"), C["muted"])
        A('<div class="ent">')
        A('<div class="eh">')
        A(f'<span><span class="dot" style="background:{color}"></span> {esc(s["name"])}</span>')
        A(f'<span style="font-size:10px;font-weight:700;background:{color};color:#fff;padding:1px 8px;'
          f'border-radius:999px">{esc(s["tone"])}</span>')
        A("</div>")
        A('<div class="bd">')
        A(f'<p>{esc(s["role"])}</p>')
        A(f'<div class="f"><span class="lab">решает</span><br><b>{esc(s["decides"])}</b></div>')
        A(f'<div class="f"><span class="lab">владеет</span><br>{esc(s["owns"])}</div>')
        A(f'<div class="f"><span class="lab">обращается к</span><br>{esc(s["calls"])}</div>')
        A(f'<div class="bnd"><span class="lab">граница</span><br>{esc(s["boundary"])}</div>')
        A("</div>")
        A("</div>")
    A("</section>")

    A('<section id="i">')
    A('<div class="h2">5 · Взаимодействия</div>')
    for it in d["interactions"]:
        A('<div class="link">')
        A(f'<div class="ln"><span class="nb">{it["n"]}</span>'
          f'<span class="fr">{esc(it["from"])}</span>'
          f'<span class="ar">→</span>'
          f'<span class="to">{esc(it["to"])}</span></div>')
        A(f'<div class="lw">{esc(it["what"])}</div>')
        A(f'<div class="lwh">{esc(it["when"])}</div>')
        A("</div>")
    A("</section>")

    A('<section id="ph">')
    A('<div class="h2">6 · Куда это ложится физически</div>')
    A(f'<p class="lead">{esc(d["physical"]["lead"])}</p>')
    for r in d["physical"]["rows"]:
        A(f'<div class="phys"><span class="pf">{esc(r["from"])}</span>'
          f'<span class="pt">{esc(r["to"])}</span></div>')
    A("</section>")

    A('<section id="f">')
    A('<div class="h2">7 · Развилки</div>')
    for f in d["forks"]:
        A('<div class="fork">')
        A(f'<div class="fq">{f["n"]}. {esc(f["question"])}</div>')
        A(f'<div class="opt"><b>A</b> — {esc(f["a"])}</div>')
        A(f'<div class="opt"><b>B</b> — {esc(f["b"])}</div>')
        A(f'<div class="ch">что меняет: {esc(f["changes"])}</div>')
        A("</div>")
    A("</section>")

    A('<section id="n">')
    A('<div class="h2">Замечания по текущему состоянию</div>')
    for n in d.get("notes", []):
        A(f'<div class="note">{esc(n)}</div>')
    A("</section>")

    A("<hr>")
    A(f'<p class="end">Coach App · логический уровень v{esc(d["version"])}</p>')
    A("</main></body></html>")

    return "\n".join(o)


def main() -> int:
    with open(SRC, encoding="utf-8") as f:
        data = json.load(f)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(render(data))
    print(f"written: {OUT} ({os.path.getsize(OUT)} bytes)")
    print(f"subsystems={len(data['subsystems'])} interactions={len(data['interactions'])} "
          f"forks={len(data['forks'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
