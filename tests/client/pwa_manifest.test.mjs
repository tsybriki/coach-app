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

test('иконка: есть мастер-файл — из него рисуются все версии', () => {
  // Иконка — готовая картинка (знак «Чёрный тренер»), а не рисунок из
  // палитры. Мастер — источник правды: без него иконки не перерисовать.
  const path = `${ROOT}client/icons/icon-source.png`;
  const size = statSync(path).size;
  assert.ok(size > 1000, `мастер-файл пустой или слишком мал (${size} B)`);
});

test('иконка: фон maskable-версии совпадает с фоном приложения', () => {
  // Maskable-версия заливается фоном темы. Если он не совпадёт, по краям
  // маски Android будет видно чужой прямоугольник.
  const match = CSS.match(/--bg:\s*(#[0-9a-fA-F]{3,8})/);
  assert.ok(match, 'в style.css нет --bg');
  const hex = match[1];
  const rgb = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
  const expected = `rgb(${rgb.join(',')})`;
  const svg = readFileSync(`${ROOT}client/icons/icon-v2.svg`, 'utf-8');
  assert.ok(svg.includes(expected),
    `фон иконки ${expected} не совпадает с --bg ${hex}`);
});

test('service worker: иконки в SHELL, а версия кэша поднята', () => {
  const match = SW.match(/shell-v(\d+)/);
  assert.ok(match, 'в worker нет версии кэша');
  assert.ok(Number(match[1]) >= 18, `версия кэша ${match[1]} — старее v18`);
});

test('иконки версионированы в URL — иначе Chrome не обновит иконку', () => {
  // Chrome обновляет иконку установленного PWA, только если изменился
  // URL иконки. Новый файл под старым URL он не подхватит: иконка
  // останется прежней, пока приложение не удалят и не поставят заново.
  //
  // Поэтому в пути иконки есть версия: icon-v2.png, а не icon.png.
  for (const icon of MANIFEST.icons) {
    assert.match(icon.src, /-v\d+\./,
      `${icon.src} — без версии в URL, Chrome не обновит иконку`);
  }
});

test('index.html: иконки ссылаются на те же версионированные файлы', () => {
  // Ссылка в разметке и манифест должны совпадать: иначе вкладка
  // покажет одну иконку, а установленное приложение — другую.
  const icon192 = MANIFEST.icons.find((i) => i.sizes === '192x192');
  assert.ok(icon192, 'нет иконки 192 в манифесте');
  assert.ok(HTML.includes(icon192.src),
    `index.html ссылается не на ${icon192.src}`);
});

test('версионированные файлы иконок физически существуют', () => {
  for (const icon of MANIFEST.icons) {
    if (!icon.src.endsWith('.png')) continue;
    const path = `${ROOT}client${icon.src}`;
    const size = statSync(path).size;
    assert.ok(size > 1000, `${icon.src} — пустой или слишком мал (${size} B)`);
  }
});
