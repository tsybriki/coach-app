/* Подмена модулей API и хранилища при импорте приложения.
 *
 * Node умеет перехватывать загрузку модулей через `module.register()`.
 * Нужен, чтобы UI-тесты импортировали настоящее `client/app.js` — с его
 * рендером и обработчиками — но получили заглушки вместо сети и
 * IndexedDB.
 */
import {register} from 'node:module';
import {pathToFileURL} from 'node:url';

register('./hooks.mjs', pathToFileURL(import.meta.filename));
