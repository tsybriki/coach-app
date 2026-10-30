/* Хук загрузки модулей: api.js и store.js → заглушки.
 *
 * Регистрируется через `module.register()`. Сопоставление — по имени
 * файла, чтобы работало независимо от каталога.
 */

const STUBS = new Map([
  ['api.js', new URL('./api.stub.mjs', import.meta.url).href],
  ['store.js', new URL('./store.stub.mjs', import.meta.url).href],
]);

export async function resolve(specifier, context, nextResolve) {
  for (const [name, stub] of STUBS) {
    if (specifier.endsWith(`/${name}`) || specifier === `./${name}`) {
      return {url: stub, shortCircuit: true};
    }
  }
  return nextResolve(specifier, context);
}
