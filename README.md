# Coach App

Приложение-тренер: операционный контур тренировочного процесса.

## Что это

Новое приложение поверх существующего пайплайна `~/coach`. Пайплайн не переписывается —
он остаётся источником батч-рендеров и первичного состояния для импорта.

## Структура

```
specs/                  источники правды
  domain/               доменная модель (MD) + SVG-диаграмма
    DOMAIN-SPEC.md      21 сущность, 48 инвариантов, 5 вопросов
    assets/             диаграмма сущностей
  logical/              логический уровень
    logical.json        источник: подсистемы, взаимодействия, развилки
    LOGICAL.md          собирается из JSON
  design/               контрактный и физический уровни (9 файлов MD)
    DESIGN.md           собирается из файлов выше

tools/                  сборка и проверки
app/                    код приложения (домен → порты → сервисы → адаптеры → API)
client/                 PWA-клиент
tests/                  тесты
reference/daniels/      справочник методики — версионируемые правила
legacy/                 черновики прошлых редакций — для истории
```

Состояние приложения — в `~/.local/share/coach-app` (путь задаётся
`COACH_APP_DATA`), не в репозитории.

## Сборка

**Источник правды — MD. HTML — производная.**

```
python3 tools/build.py
```

Собирает: `DOMAIN-SPEC.html` · `LOGICAL.html` · `DESIGN.html`, затем гоняет проверки:
счётчики спецификации (сверка HTML с MD) и чекер утечек знания о физическом хранилище.

Отдельные шаги:

```
.venv/bin/python tools/build_logical_md.py    # logical.json → specs/logical/LOGICAL.md
.venv/bin/python tools/build_design_md.py     # specs/design/*.md → specs/design/DESIGN.md
.venv/bin/python tools/render_spec.py         # MD → HTML
.venv/bin/python tools/count_spec.py DOMAIN-SPEC.html specs/domain/DOMAIN-SPEC.md
.venv/bin/python tools/check_storage_leaks.py
.venv/bin/python tools/check_invariant_coverage.py
.venv/bin/python tools/check_docs_vs_code.py  # документы не врут о коде
```

`tools/html2md.py` — разовая односторонняя конвертация, чтобы перевернуть спецификацию
с HTML-источника на MD. Дальше не нужен.

## Тесты

```
.venv/bin/python -m pytest        # Python-часть
npm test                           # клиент
.venv/bin/python -m mypy app      # strict
.venv/bin/python -m ruff check app tests
```

Число тестов намеренно не зафиксировано в документах: оно меняется с каждой
правкой, а проверяется прогоном. `npm test` гоняется через hook
`tests/client/helpers/register.mjs` — голый `node --test tests/client/` роняет
UI-тесты на `EventSource is not defined`, это неподключённый hook, а не дефект
приложения.

## Правила

1. **Решения принимает код.** LLM только формулирует. Числа считает домен.
2. **Ничего не инициируется само.** Любое изменение состояния — команда от пользователя.
3. **Источник правды один.** Производное пересчитывается, не хранится вторым экземпляром.
4. **Логика не знает о формате хранения.** Доступ к данным — только через порты;
   формат знает только адаптер. Проверяется `tools/check_storage_leaks.py`.
5. **Деградация вместо отказа.** Упавший внешний источник ограничивает, но не роняет.
6. **Заглушка честнее выдумки.** Нет правила — «не могу оценить», а не выдуманное число.

## Запуск

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
COACH_APP_DATA=~/.local/share/coach-app \
  .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8443 \
  --ssl-keyfile ~/.local/share/coach-app/tls/key.pem \
  --ssl-certfile ~/.local/share/coach-app/tls/cert.pem
```

Сервис systemd — `deploy/coach-app-tls.service`:

```bash
cp deploy/coach-app-tls.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now coach-app-tls.service
```

Порт 8080 (HTTP) отключён: отдельного инстанса на нём нет. PWA требует
secure context, поэтому телефон ходит только по HTTPS.

## Service worker и HTTPS

Service worker работает только на **HTTPS** или на `localhost`. С телефона
(`https://192.168.178.43:8443`) он работает, но сертификат локальный —
телефон спросит доверие один раз. Сертификат CA ставится с телефона один
раз: открыть `https://192.168.178.43:8443/ca.crt`, сохранить, поставить
как «сертификат CA пользователя».

Выбор — отдельное решение, см. `specs/design/04-хостинг.md`.

## Состояние

База работает: домен, хранилище, сервисы, BFF, клиент. Факт на 01.11.2026:

| Что | Состояние |
|---|---|
| Домен | 21 сущность, 48 инвариантов, все покрыты тестами |
| Планировщик недели | работает по правилам Дэниэлса: качественная работа, раскладка по слотам, висяки |
| Garmin | подключён: `pull_fact`, `import_fit` (разбор тренировки), `link_actual` |
| BFF | 13 маршрутов, ETag, SSE, команды, батч |
| Клиент | 5 разделов, неделя, сезон, план против факта, закрытие, разбор тренировки, очередь команд |
| Макро-план сезона | 27 недель из 49 — приходит импортом из пайплайна; неделя гонки не планируется |
| Связь план↔факт | ставится руками; в данных закрытой недели 8 связей из 9 тренировок |

Открыто:
- правило роста формы — заглушка, вердикт «не могу оценить»;
- переплан остатка недели — принимает команду, но новых тренировок не строит;
- `place_unplaced`, `unplace_request`, `edit_actual`, `set_slots`, `set_plan`,
  `set_goal`, `update_athlete`, `set_equipment`, `override_slots`,
  `set_gate_result`, `decide_gate`, `import_state` — команды объявлены в
  контракте, но в BFF не реализованы;
- миграций схемы нет: формат хранилища ещё не менялся.
