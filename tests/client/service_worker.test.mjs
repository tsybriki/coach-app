/* Правила service worker'а.
 *
 * Service worker — это отдельный кусок кода, который легко сломать, не
 * заметив: он не входит в `app.js`, его тесты не гоняют обычные UI-тесты,
 * а на экране он проявляется как «приложение сломано».
 *
 * Проверяем два правила:
 *
 * 1. **Оболочка — network-first.** При наличии сети отдаётся свежий файл,
 *    кэш обновляется на ходу. Cache-first отдавал старый `app.js` из кэша
 *    worker'а: правка в коде не доезжала до экрана, а в инкогнито, где
 *    worker'а нет, работало. Отсюда разница между профилями браузера.
 * 2. **Сам worker — из сети.** Иначе новая версия worker'а не может
 *    установиться: он обслуживает себя из своего же кэша.
 */
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';

const SW = readFileSync(
  fileURLToPath(new URL('../../client/sw.js', import.meta.url)),
  'utf-8',
);

/* Убираем комментарии: правило ищется в коде, а не в прозе. */
const CODE = SW.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');

test('оболочка: сеть вперёд, кэш — только офлайн', () => {
  const fetchIndex = CODE.indexOf('fetch(request)');
  const cacheMatchIndex = CODE.indexOf('caches.match(request)');
  assert.ok(fetchIndex >= 0, 'в worker нет fetch(request)');
  assert.ok(cacheMatchIndex >= 0, 'в worker нет caches.match(request)');
  assert.ok(
    fetchIndex < cacheMatchIndex,
    'кэш читается раньше сети — это cache-first, правки в коде не доедут',
  );
});

test('cache-first в worker не остался', () => {
  assert.doesNotMatch(
    CODE,
    /return\s+cached\s*\|\|\s*network/,
    'worker отдаёт кэш раньше сети — правки в коде не доедут до экрана',
  );
});

test('сам service worker обслуживается из сети', () => {
  assert.match(
    CODE,
    /pathname\s*===\s*['"]\/sw\.js['"]/,
    'worker не исключён из своего же кэша — новая версия не установится',
  );
});

test('worker берёт управление сразу и чистит старые кэши', () => {
  assert.match(CODE, /skipWaiting\(\)/, 'новый worker не перехватывает страницу сразу');
  assert.match(CODE, /clients\.claim\(\)/, 'открытые страницы не переводятся на нового worker');
  assert.match(CODE, /caches\.delete/, 'старые кэши не удаляются');
});

test('версия кэша объявлена и отличается от прошлой', () => {
  const match = SW.match(/shell-v(\d+)/);
  assert.ok(match, 'в worker нет версии кэша');
  const version = Number(match[1]);
  assert.ok(version >= 17, `версия кэша ${version} — старее v17`);
});

test('ошибки и команды не кэшируются', () => {
  assert.match(
    CODE,
    /request\.method\s*!==\s*['"]GET['"]/,
    'не-GET запросы не исключены из перехвата',
  );
});
