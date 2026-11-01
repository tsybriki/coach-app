/* Условия установки PWA.
 *
 * Chrome показывает «Установить приложение» только если выполнены все
 * условия сразу. Каждое из них проверяется тут — иначе поломка видна
 * только на телефоне, и выглядит как «Chrome не предлагает установить».
 *
 * Проверяем:
 *  - манифест: имя, start_url, scope, display standalone;
 *  - иконки: 192×192 и 512×512, плюс maskable для Android;
 *  - иконки физически существуют и не пустые;
 *  - иконки входят в service worker (иначе офлайн их не покажет);
 *  - палитра иконки совпадает с палитрой интерфейса.
 */
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync, statSync} from 'node:fs';
import {fileURLToPath} from 'node:url';

const ROOT = fileURLToPath(new URL('../../', import.meta.url));
const MANIFEST = JSON.parse(
  readFileSync(`${ROOT}client/manifest.json`, 'utf-8'));
const SW = readFileSync(`${ROOT}client/sw.js`, 'utf-8');
const CSS = readFileSync(`${ROOT}client/style.css`, 'utf-8');
const HTML = readFileSync(`${ROOT}client/index.html`, 'utf-8');

test('манифест: имя, start_url и scope на месте', () => {
  assert.ok(MANIFEST.name, 'нет name');
  assert.ok(MANIFEST.short_name, 'нет short_name');
  assert.ok(MANIFEST.start_url, 'нет start_url');
  assert.equal(MANIFEST.scope, '/', 'scope должен быть /');
  assert.equal(MANIFEST.display, 'standalone',
    'display должен быть standalone — иначе откроется браузер');
});

test('манифест: иконки 192 и 512 — Chrome без них не предлагает установку', () => {
  const sizes = MANIFEST.icons.map((i) => i.sizes);
  assert.ok(sizes.includes('192x192'), 'нет иконки 192x192');
  assert.ok(sizes.includes('512x512'), 'нет иконки 512x512');
});

test('манифест: есть maskable-иконка — Android обрезает по своей маске', () => {
  const maskable = MANIFEST.icons.filter((i) => (i.purpose || '').includes('maskable'));
  assert.ok(maskable.length > 0, 'нет иконки с purpose: maskable');
});

test('иконки физически существуют и не пустые', () => {
  for (const icon of MANIFEST.icons) {
    const path = `${ROOT}client${icon.src}`;
    const size = statSync(path).size;
    assert.ok(size > 100, `${icon.src} — пустой или слишком мал (${size} B)`);
  }
});

test('иконки входят в service worker — иначе офлайн их не покажет', () => {
  for (const icon of MANIFEST.icons) {
    if (!icon.src.endsWith('.png')) continue;
    assert.ok(SW.includes(icon.src),
      `${icon.src} нет в SHELL service worker'а — офлайн без иконки`);
  }
});

test('index.html: манифест подключён, иконка для вкладки и для iOS', () => {
  assert.match(HTML, /rel="manifest"/, 'манифест не подключён');
  assert.match(HTML, /rel="icon"/, 'нет иконки вкладки');
  assert.match(HTML, /apple-touch-icon/, 'нет apple-touch-icon');
});

test('иконка: фон и цвета взяты из палитры интерфейса', () => {
  // Палитра иконки — из :root в style.css. Расхождение видно глазом:
  // иконка другого тона, чем приложение.
  for (const token of ['--bg', '--panel', '--accent', '--accent2']) {
    const match = CSS.match(new RegExp(`${token}:\\s*(#[0-9a-fA-F]{3,8})`));
    assert.ok(match, `в style.css нет ${token}`);
    const svg = readFileSync(`${ROOT}client/icons/icon.svg`, 'utf-8');
    assert.ok(svg.includes(match[1]),
      `${token} (${match[1]}) нет в иконке — она из другой палитры`);
  }
});

test('service worker: иконки в SHELL, а версия кэша поднята', () => {
  const match = SW.match(/shell-v(\d+)/);
  assert.ok(match, 'в worker нет версии кэша');
  assert.ok(Number(match[1]) >= 18, `версия кэша ${match[1]} — старее v18`);
});
