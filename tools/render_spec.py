#!/usr/bin/env python3
"""
render_spec.py — собрать DOMAIN-SPEC.html из MD-спецификации.

Запуск:
    python3 tools/render_spec.py specs/domain/DOMAIN-SPEC.md DOMAIN-SPEC.html

Источник правды — MD. HTML — производная: рисуется, читается с телефона.
Правки вносятся в MD, потом запускается этот скрипт.

Что делает:
  - парсит MD-спецификацию (заголовки, карточки сущностей, таблицы, списки)
  - собирает HTML в стиле DOMAIN-SPEC (палитра домена Coach App)
  - подставляет SVG-диаграмму из specs/domain/assets/
  - добавляет скрипт подтверждения инвариантов (класс confirmed на строке)

Отметки подтверждения: в MD это `✓` в конце текста правила. При сборке превращается
в класс `confirmed` на строке — единственный источник правды о подтверждении.
"""
from __future__ import annotations

import html
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

CSS = """
  :root {
    --bg: #fdf6ed; --card-bg: #fffefb; --ink: #1a1a1a; --muted: #6a6056; --faint: #9a9085;
    --border: #e6dac4; --coral: #ff6b5a; --teal: #14b8a6; --mustard: #d4a017;
    --terra: #c2410c; --sky: #0284c7; --grass: #65a30d; --code-bg: #f4ede0;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  html { -webkit-text-size-adjust: 100%; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: var(--bg); color: var(--ink); line-height: 1.5; font-size: 16px; padding-bottom: 50px; }
  code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }

  header { padding: 16px 14px 12px; border-bottom: 1px solid var(--border); background: var(--card-bg); }
  header h1 { font-size: 19px; font-weight: 700; }
  header .meta { font-size: 11px; color: var(--faint); margin-top: 5px; }

  nav { position: sticky; top: 0; z-index: 10; background: rgba(253,246,237,0.96); backdrop-filter: blur(8px);
    border-bottom: 1px solid var(--border); overflow-x: auto; -webkit-overflow-scrolling: touch;
    white-space: nowrap; padding: 7px 12px; scrollbar-width: none; }
  nav::-webkit-scrollbar { display: none; }
  nav a { display: inline-block; font-size: 12px; color: var(--muted); text-decoration: none;
    padding: 4px 9px; margin-right: 4px; border: 1px solid var(--border); border-radius: 999px; background: var(--card-bg); }

  main { padding: 0 12px; max-width: 760px; margin: 0 auto; }
  section { margin-top: 26px; }
  .h2 { font-size: 16px; font-weight: 700; padding-bottom: 6px; border-bottom: 2px solid var(--ink); margin-bottom: 10px; }
  h3 { font-size: 14px; font-weight: 700; margin: 16px 0 6px; }
  h4 { font-size: 13px; font-weight: 700; margin: 14px 0 5px; color: var(--muted); }
  p { font-size: 14.5px; margin-bottom: 8px; }
  ul, ol { margin: 0 0 9px; padding-left: 22px; font-size: 13.5px; }
  li { margin-bottom: 4px; }
  blockquote { border-left: 3px solid var(--border); padding: 2px 0 2px 10px; margin: 0 0 9px;
    color: var(--muted); font-size: 13px; }
  b { font-weight: 700; }

  .tw { overflow-x: auto; -webkit-overflow-scrolling: touch; margin: 6px 0 12px; position: relative; }
  table { border-collapse: collapse; width: 100%; min-width: 420px; font-size: 12.5px; }
  th, td { text-align: left; padding: 5px 7px; border-bottom: 1px solid var(--border); vertical-align: top; }
  th { font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.04em; color: var(--muted);
    font-weight: 700; background: var(--code-bg); }
  td code { font-size: 11.5px; overflow-wrap: anywhere; }
  td.n { white-space: nowrap; color: var(--faint); }

  .dia { background: var(--card-bg); border: 1px solid var(--border); border-radius: 10px; padding: 8px; overflow-x: auto; }
  .dia svg { width: 100%; min-width: 340px; display: block; }

  .ent { border: 1px solid var(--border); border-radius: 8px; background: var(--card-bg); margin-bottom: 8px; overflow: hidden; }
  .ent > .eh { background: var(--ink); color: #fff; padding: 5px 10px; font-size: 13px; font-weight: 700;
    display: flex; justify-content: space-between; gap: 8px; }
  .ent > .eh .k { font-size: 10px; font-weight: 600; background: rgba(255,255,255,0.18);
    padding: 1px 7px; border-radius: 999px; }
  .ent .role { font-size: 12.5px; color: var(--muted); padding: 8px 10px 0; margin: 0; }
  .ent .pl { margin: 0; padding: 8px 10px 8px 26px; font-size: 12.5px; }
  .ent .pl li { margin-bottom: 2px; }
  .ent .pl code { font-size: 11.5px; overflow-wrap: anywhere; }
  .ent .pl li { overflow-wrap: anywhere; }

  .inv-head { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 8px; }
  .inv-count { font-size: 12px; color: var(--muted); font-weight: 700; }
  .inv-bar { flex: 1 1 140px; min-width: 120px; height: 8px; background: var(--code-bg);
    border: 1px solid var(--border); border-radius: 999px; overflow: hidden; }
  .inv-bar > i { display: block; height: 100%; background: var(--grass); width: 0%; transition: width .3s ease; }
  .inv-badge { font-size: 10px; font-weight: 700; padding: 2px 8px; border-radius: 999px;
    border: 1px solid var(--border); background: var(--code-bg); color: var(--faint); white-space: nowrap; }
  .inv-badge.ok { background: #eff7e6; border-color: #cfe5b8; color: #4a7a12; }
  td.st { width: 22px; text-align: center; }
  td.st .ok { display: inline-block; width: 15px; height: 15px; line-height: 14px; border-radius: 50%;
    background: var(--grass); color: #fff; font-size: 10px; font-weight: 700; }
  td.st .no { color: var(--border); font-size: 11px; }
  tr.confirmed td { background: #f7fbf1; }
  .oklist { background: #f3f9ec; border: 1px solid #cfe5b8; border-radius: 10px; padding: 10px 12px; margin-bottom: 10px; }
  .oklist .ttl { font-size: 12px; font-weight: 700; color: #4a7a12; margin-bottom: 5px; }
  .oklist ul { margin: 0; padding-left: 18px; }
  .oklist li { font-size: 12.5px; margin-bottom: 2px; color: #4a5c2e; }
  .oklist .none { font-size: 12.5px; color: var(--faint); }

  .probs { counter-reset: p; margin: 0; padding-left: 22px; font-size: 13.5px; }
  .probs li { margin-bottom: 7px; }

  hr { border: none; border-top: 1px solid var(--border); margin: 22px 0 0; }
  .end { text-align: center; font-size: 11.5px; color: var(--faint); padding: 20px 0 8px; }

  @media (max-width: 560px) {
    main { padding: 0 10px; }
    header h1 { font-size: 17px; }
    p { font-size: 14px; }
    table { min-width: 380px; font-size: 12px; }
    .tw::after { content: '→ свайп'; position: absolute; right: 2px; bottom: 2px; font-size: 9px;
      color: var(--faint); background: var(--card-bg); padding: 0 4px; pointer-events: none; }
  }
"""

SCRIPT = """
(function () {
  var rows = document.querySelectorAll('#r table tr');
  var inv = [];
  rows.forEach(function (tr) {
    var n = tr.querySelector('td.n');
    if (!n || !/^I\\d+$/.test(n.textContent.trim())) return;
    inv.push({ num: n.textContent.trim(), tr: tr, cell: tr.querySelector('td.st') });
  });
  var total = inv.length;
  document.getElementById('inv-total').textContent = total;
  function paint() {
    var ok = [];
    inv.forEach(function (r) {
      if (r.tr.classList.contains('confirmed')) {
        ok.push(r);
        r.cell.innerHTML = '<span class="ok">\\u2713</span>';
      } else {
        r.cell.innerHTML = '<span class="no">\\u00b7</span>';
      }
    });
    document.getElementById('ok-n').textContent = ok.length;
    document.getElementById('ok-bar').style.width = (total ? (ok.length / total * 100) : 0) + '%';
    var badge = document.getElementById('ok-badge');
    var list = document.getElementById('ok-list');
    if (ok.length === 0) {
      badge.className = 'inv-badge';
      badge.textContent = 'не начато';
    } else if (ok.length === total) {
      badge.className = 'inv-badge ok';
      badge.textContent = 'все подтверждены';
    } else {
      badge.className = 'inv-badge';
      badge.textContent = 'в работе';
    }
    if (ok.length) {
      var items = ok.map(function (r) {
        var t = r.tr.querySelector('td:last-child').textContent.trim();
        return '<li><b>' + r.num + '</b> — ' + t + '</li>';
      }).join('');
      list.innerHTML = '<div class="ttl">Подтверждённые инварианты (' + ok.length + ')</div><ul>' + items + '</ul>';
    } else {
      list.innerHTML = '<div class="ttl">Подтверждённые инварианты</div><div class="none">Пока ни одного. Кирилл читает и подтверждает по одному — подтверждённые помечаются здесь и в таблице.</div>';
    }
  }
  paint();
  var pending = false;
  new MutationObserver(function (muts) {
    var hit = muts.some(function (m) { return m.target.tagName === 'TR'; });
    if (!hit || pending) return;
    pending = true;
    setTimeout(function () { pending = false; paint(); }, 0);
  }).observe(document.getElementById('r'), { attributes: true, subtree: true, attributeFilter: ['class'] });
})();
"""


def esc(s: str) -> str:
    return html.escape(s, quote=False)


def inline(s: str) -> str:
    """MD-инлайн → HTML: `код`, **жирный**, *курсив*."""
    s = esc(s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])", r"<i>\1</i>", s)
    return s


def parse_md(md: str) -> dict:
    """Разобрать MD-спецификацию в ЛИНЕЙНЫЙ поток блоков.

    Порядок блоков сохраняется — иначе таблицы теряются. Сущности группируются
    в карточки на месте: h3 + следующие за ним li.
    """
    lines = md.split("\n")
    d: dict = {"counters": "", "blocks": [], "svg": None}

    i = 0
    cur_entity = None

    def flush_entity():
        nonlocal cur_entity
        if cur_entity:
            d["blocks"].append(cur_entity)
            cur_entity = None

    while i < len(lines):
        s = lines[i].strip()

        if not s:
            i += 1
            continue

        if s.startswith("Coach App · v"):
            d["counters"] = s
            i += 1
            continue

        m = re.match(r"!\[.*?\]\((.*?)\)", s)
        if m:
            d["svg"] = m.group(1)
            i += 1
            continue

        # таблица
        if "|" in s and i + 1 < len(lines) and re.match(r"^\|[\s:|-]+\|$", lines[i + 1].strip()):
            head = [c.strip() for c in s.strip("|").split("|")]
            i += 2
            rows = []
            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            d["blocks"].append({"type": "table", "head": head, "rows": rows})
            continue

        # заголовки
        m = re.match(r"^(#{2,4})\s+(.*)$", s)
        if m:
            lvl, title = len(m.group(1)), m.group(2)
            if lvl == 3 and _in_entities(d):
                flush_entity()
                m2 = re.match(r"^(.*?)\s+\*\((.*?)\)\*$", title)
                cur_entity = {"type": "entity", "name": m2.group(1).strip() if m2 else title,
                              "kind": m2.group(2) if m2 else "", "role": "", "fields": []}
            else:
                flush_entity()
                d["blocks"].append({"type": f"h{lvl}", "text": title})
            i += 1
            continue

        # список
        if re.match(r"^[-*]\s+", s):
            item = re.sub(r"^[-*]\s+", "", s)
            if cur_entity is not None:
                cur_entity["fields"].append(item)
            else:
                d["blocks"].append({"type": "li", "text": item})
            i += 1
            continue

        # нумерованный пункт (вопросы)
        m = re.match(r"^(\d+)\.\s+(.*)$", s)
        if m:
            flush_entity()
            d["blocks"].append({"type": "num", "n": int(m.group(1)), "text": m.group(2)})
            i += 1
            continue

        # цитата
        if s.startswith("> "):
            flush_entity()
            d["blocks"].append({"type": "quote", "text": s[2:]})
            i += 1
            continue

        # абзац: если мы внутри карточки сущности — это её роль
        if cur_entity is not None:
            cur_entity["role"] = s
            i += 1
            continue
        flush_entity()
        d["blocks"].append({"type": "p", "text": s})
        i += 1

    flush_entity()
    return d


def _in_entities(d: dict) -> bool:
    """Мы внутри секции «2 · Сущности»?"""
    for b in reversed(d["blocks"]):
        if b["type"] == "h2":
            return b["text"].startswith("2 ·")
    return False


def render(d: dict, svg_text: str) -> str:
    """Собрать HTML из линейного потока блоков. Порядок сохраняется."""
    o: list[str] = []
    A = o.append

    A("<!DOCTYPE html>")
    A('<html lang="ru"><head><meta charset="UTF-8">')
    A('<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">')
    A("<title>Coach App — модель домена (спецификация)</title>")
    A(f"<style>{CSS}</style>")
    A("</head><body>")

    A("<header>")
    A("<h1>Модель домена — спецификация</h1>")
    A(f'<div class="meta">{esc(d["counters"])}</div>')
    A('<div class="meta">состав: диаграмма · сущности · связи · вопросы</div>')
    A("</header>")

    A("<nav>")
    A('<a href="#d">1 · Диаграмма</a>')
    A('<a href="#e">2 · Сущности</a>')
    A('<a href="#r">3 · Связи</a>')
    A('<a href="#p">4 · Вопросы</a>')
    A("</nav>")

    A("<main>")

    in_section = None          # текущий id секции
    section_open = False
    pending_inv = False        # следующая таблица — инварианты
    in_ul = False              # открыт ли <ul> для последовательных li
    in_ol = False              # открыт ли <ol> для нумерованных пунктов

    def open_section(sid: str, title: str):
        nonlocal in_section, section_open
        if section_open:
            A("</section>")
        A(f'<section id="{sid}">')
        A(f'<div class="h2">{esc(title)}</div>')
        in_section = sid
        section_open = True

    def close_section():
        nonlocal section_open
        if section_open:
            A("</section>")
            section_open = False

    for blk in d["blocks"]:
        t = blk["type"]

        if t != "li" and in_ul:
            A("</ul>")
            in_ul = False
        if t != "num" and in_ol:
            A("</ol>")
            in_ol = False

        if t == "h2":
            title = blk["text"]
            if title.startswith("1 ·"):
                open_section("d", title)
                A('<div class="dia">')
                A(svg_text)
                A("</div>")
            elif title.startswith("2 ·"):
                open_section("e", title)
            elif title.startswith("3 ·"):
                open_section("r", title)
            elif title.startswith("4 ·"):
                open_section("p", title)
            continue

        if t == "h3":
            A(f"<h3>{inline(blk['text'])}</h3>")
            pending_inv = blk["text"].startswith("Инварианты")
            if pending_inv:
                A('<div class="inv-head">')
                A('<span class="inv-count">Подтверждено <span id="ok-n">0</span> из '
                  '<span id="inv-total">0</span></span>')
                A('<span class="inv-bar"><i id="ok-bar"></i></span>')
                A('<span class="inv-badge" id="ok-badge">не начато</span>')
                A("</div>")
                A('<div class="oklist" id="ok-list">')
                A('<div class="ttl">Подтверждённые инварианты</div>')
                A('<div class="none">Пока ни одного. Кирилл читает и подтверждает по одному — '
                  'подтверждённые помечаются здесь и в таблице.</div>')
                A("</div>")
            continue

        if t == "h4":
            A(f"<h4>{inline(blk['text'])}</h4>")
            continue

        if t == "entity":
            A('<div class="ent">')
            k = f'<span class="k">{esc(blk["kind"])}</span>' if blk["kind"] else ""
            A(f'<div class="eh"><span>{esc(blk["name"])}</span>{k}</div>')
            if blk["role"]:
                A(f'<div class="role">{inline(blk["role"])}</div>')
            A('<ul class="pl">')
            for f in blk["fields"]:
                A(f"<li>{inline(f)}</li>")
            A("</ul></div>")
            continue

        if t == "table":
            A('<div class="tw"><table>')
            A("<tr>" + "".join(f"<th>{inline(h)}</th>" for h in blk["head"]) + "</tr>")
            for row in blk["rows"]:
                if pending_inv and len(row) >= 2 and re.match(r"^I\d+$", row[0].strip()):
                    confirmed = row[1].rstrip().endswith("\u2713")
                    text = row[1].rstrip()[:-1].rstrip() if confirmed else row[1]
                    cls = ' class="confirmed"' if confirmed else ""
                    A(f'<tr{cls}><td class="n">{inline(row[0])}</td>'
                      f'<td class="st"><span class="no">\u00b7</span></td>'
                      f'<td>{inline(text)}</td></tr>')
                else:
                    A("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in row) + "</tr>")
            A("</table></div>")
            pending_inv = False
            continue

        if t == "num":
            if not in_ol:
                cls = " class=\"probs\"" if in_section == "p" else ""
                A(f"<ol{cls}>")
                in_ol = True
            A(f"<li>{inline(blk['text'])}</li>")
            continue

        if t == "quote":
            A(f"<blockquote>{inline(blk['text'])}</blockquote>")
            continue

        if t == "li":
            # последовательные li собираются в один <ul>
            if not in_ul:
                A("<ul>")
                in_ul = True
            A(f"<li>{inline(blk['text'])}</li>")
            continue

        if t == "p":
            A(f"<p>{inline(blk['text'])}</p>")
            continue

    if in_ul:
        A("</ul>")
        in_ul = False
    if in_ol:
        A("</ol>")
        in_ol = False
    close_section()

    A("<hr>")
    A('<p class="end">Coach App · модель домена</p>')
    A("</main>")
    A(f"<script>{SCRIPT}</script>")
    A("</body></html>")
    return "\n".join(o)


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: render_spec.py <вход.md> <выход.html>")
        return 1
    md_path, out_path = sys.argv[1], sys.argv[2]
    md = open(md_path, encoding="utf-8").read()
    d = parse_md(md)

    svg_path = os.path.join(os.path.dirname(os.path.abspath(md_path)), "assets", "domain-diagram.svg")
    if not os.path.exists(svg_path):
        print(f"MISSING SVG: {svg_path}")
        return 1
    svg_text = open(svg_path, encoding="utf-8").read()

    out = render(d, svg_text)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(out)
    print(f"written: {out_path} ({os.path.getsize(out_path)} bytes)")
    ents = sum(1 for b in d["blocks"] if b["type"] == "entity")
    invs = sum(1 for b in d["blocks"] if b["type"] == "table"
               and b["head"] and b["head"][0] == "#" for _ in [0])
    nums = sum(1 for b in d["blocks"] if b["type"] == "num")
    print(f"entities={ents} questions={nums}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
