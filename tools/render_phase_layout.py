#!/usr/bin/env python3
"""
render_phase_layout.py — артефакт «раскладка недель по фазам» для проверки.

Показывает раскладку программы Дэниэлса по фазам для заданных сроков:
неделя сезона → фаза → неделя программы → чей план применяется.

Числа берутся из рабочего кода (`MethodPlan.schedule_for`), а не
вычисляются на месте: артефакт и реализация не могут разойтись.

Запуск:
    python3 tools/render_phase_layout.py --out /tmp/phase-layout.html
    python3 tools/render_phase_layout.py --weeks 29 19 --out ...
"""
from __future__ import annotations

import argparse
import html
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.adapters.daniels import load_plan  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
REFERENCE = REPO / "reference" / "daniels"

PHASE_NAMES = {1: "I", 2: "II", 3: "III", 4: "IV"}
PHASE_COLORS = {
    1: ("#7ec8e3", "rgba(126,200,227,.10)"),
    2: ("#f0c674", "rgba(240,198,116,.10)"),
    3: ("#d8a0ff", "rgba(216,160,255,.10)"),
    4: ("#ff9b6a", "rgba(255,155,106,.10)"),
}

CSS = """
:root{
  --bg:#0f1115;--panel:#161a22;--panel2:#1d222c;--border:#2a3140;
  --text:#e6e9ef;--muted:#9aa3b2;
  --accent:#7aa2ff;--accent2:#5cd6c0;--warn:#ff9b6a;--good:#7ee787;--cp:#d8a0ff;
}
*{box-sizing:border-box}
html,body{margin:0;background:var(--bg);color:var(--text);
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Inter,sans-serif;
  -webkit-text-size-adjust:100%;line-height:1.4}
body{padding:14px 12px 60px;max-width:780px;margin:0 auto}
h1{font-size:20px;margin:0 0 4px}
h2{font-size:15px;margin:0 0 8px;color:var(--accent)}
h3{font-size:12px;text-transform:uppercase;letter-spacing:.5px;color:var(--muted)}
.sub{color:var(--muted);font-size:12.5px;margin-bottom:14px}
.card{background:var(--panel);border:1px solid var(--border);border-radius:12px;
  padding:12px 14px;margin-bottom:12px}
.counts{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:10px}
.count{background:var(--panel2);border:1px solid var(--border);border-radius:8px;
  padding:5px 10px;font-size:11px;color:var(--muted);white-space:nowrap}
.count b{color:var(--text);font-family:ui-monospace,SFMono-Regular,monospace;
  font-size:12px;margin-right:4px}
.row{display:flex;align-items:center;gap:8px;padding:7px 10px;
  border-radius:9px;margin-bottom:4px;background:var(--panel2);
  border:1px solid var(--border)}
.row.extra{border-style:dashed}
.wk{font-family:ui-monospace,SFMono-Regular,monospace;font-size:13px;
  font-weight:600;min-width:26px;color:var(--text)}
.ph{font-size:10.5px;font-weight:600;padding:2px 8px;border-radius:6px;
  letter-spacing:.5px;white-space:nowrap}
.pw{font-family:ui-monospace,SFMono-Regular,monospace;font-size:12px;
  color:var(--muted);white-space:nowrap}
.pl{margin-left:auto;font-family:ui-monospace,SFMono-Regular,monospace;
  font-size:12px;color:var(--accent2);white-space:nowrap}
.tag{font-size:9.5px;text-transform:uppercase;letter-spacing:.5px;
  color:var(--warn);white-space:nowrap}
.note{font-size:11.5px;color:var(--muted);line-height:1.45;margin:0 0 10px}
.legend{display:flex;flex-wrap:wrap;gap:8px;margin-top:6px}
.lg{display:flex;align-items:center;gap:5px;font-size:10.5px;color:var(--muted);
  white-space:nowrap}
.dot{width:9px;height:9px;border-radius:3px;flex-shrink:0}
.rule{background:var(--panel2);border:1px solid var(--border);border-radius:9px;
  padding:9px 12px;font-size:11.5px;color:var(--muted);line-height:1.5;
  margin-bottom:10px}
.rule b{color:var(--text)}
"""


def render(plan, weeks: int) -> str:
    """Карточка раскладки для одного срока."""
    schedule = plan.schedule_for(weeks)
    if schedule is None:
        return ""
    counts = {p: len(schedule.weeks_for(p)) for p in sorted(schedule.phases)}

    parts = [f'<div class="card"><h3>{weeks} недель до старта</h3>']
    parts.append('<div class="counts">')
    for phase, count in counts.items():
        color, bg = PHASE_COLORS[phase]
        parts.append(
            f'<div class="count"><b style="color:{color}">{count}</b>'
            f'фаза {PHASE_NAMES[phase]}</div>'
        )
    parts.append(
        f'<div class="count"><b>{schedule.total()}</b>всего недель</div>'
    )
    parts.append("</div>")

    offset = 0
    for phase in sorted(schedule.phases):
        color, bg = PHASE_COLORS[phase]
        for program_week in schedule.weeks_for(phase):
            offset += 1
            plan_week = schedule.plan_for(program_week)
            extra = program_week > 24
            parts.append(
                f'<div class="row{" extra" if extra else ""}">'
                f'<span class="wk">{offset}</span>'
                f'<span class="ph" style="color:{color};background:{bg}">'
                f'фаза {PHASE_NAMES[phase]}</span>'
                f'<span class="pw">неделя программы {program_week}</span>'
                f'<span class="pl">план из {plan_week}</span>'
                + ('<span class="tag">лишняя</span>' if extra else "")
                + "</div>"
            )
    parts.append("</div>")
    return "".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--weeks", type=int, nargs="+", default=[29, 19])
    ap.add_argument("--out", default="/tmp/phase-layout.html")
    args = ap.parse_args()

    plan = load_plan(REFERENCE)

    body = [
        '<h1>Раскладка программы Дэниэлса по фазам</h1>',
        '<div class="sub">Неделя сезона → фаза → неделя программы → '
        'чей план применяется. Числа — из рабочего кода '
        '(MethodPlan.schedule_for).</div>',
        '<div class="rule"><b>Правило.</b> При сроке больше 24 недель фазы '
        'собираются из своих недель программы подряд (I — 1–6, II — 7–12, '
        'III — 13–18, IV — 19–24). Лишние недели идут по кругу через фазы '
        'II, III, IV и стоят у края своей фазы: <b>в конец</b> для II и III, '
        '<b>в начало</b> для IV. План лишней недели — с того же края: одна '
        'лишняя неделя берёт неделю с края (II — 12, III — 18, IV — 19), '
        'две и больше — край фазы по кругу (II — 11, 12; III — 17, 18; '
        'IV — 19, 20).</div>',
    ]

    for weeks in args.weeks:
        body.append(render(plan, weeks))

    body.append('<div class="card"><h3>Легенда</h3><div class="legend">')
    for phase in sorted(PHASE_COLORS):
        color, _ = PHASE_COLORS[phase]
        body.append(
            f'<div class="lg"><span class="dot" style="background:{color}">'
            f'</span>фаза {PHASE_NAMES[phase]}</div>'
        )
    body.append(
        '<div class="lg"><span class="dot" style="background:#9aa3b2">'
        '</span>пунктир — лишняя неделя</div>'
    )
    body.append("</div></div>")

    document = (
        '<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1.0">'
        "<title>Раскладка недель по фазам</title>"
        f"<style>{CSS}</style></head><body>"
        + "".join(body)
        + "</body></html>"
    )
    Path(args.out).write_text(document, encoding="utf-8")
    print(f"written: {args.out} ({len(document)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
