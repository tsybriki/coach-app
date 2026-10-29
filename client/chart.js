/* Графики тренировки: пульс, каденция, мощность, дистанция.
 *
 * Рисуем SVG руками: канвас в мобильном PWA смотрится плохо, а SVG
 * масштабируется и остаётся резким.
 *
 * Чистые функции — их можно проверять тестами: node --test tests/client/
 */

/* Точки ряда → координаты внутри полотна.
 *
 * Ряд: [[секунда, значение], …]. Возвращает [{x, y}, …] или пустой
 * список, если данных нет или все значения одинаковы.
 */
export function toPoints(series, width, height, minValue, maxValue) {
  if (!series || !series.length) return [];
  const times = series.map((point) => point[0]);
  const values = series.map((point) => point[1]);
  const tMin = Math.min(...times);
  const tMax = Math.max(...times);
  const span = tMax - tMin || 1;

  let low = minValue;
  let high = maxValue;
  if (low === null || low === undefined) low = Math.min(...values);
  if (high === null || high === undefined) high = Math.max(...values);
  // плоский ряд: дать немного воздуха, иначе линия ляжет на границу
  if (high - low < 1) {
    const padding = Math.max(1, Math.abs(high) * 0.05);
    low -= padding;
    high += padding;
  }
  const vSpan = high - low || 1;

  return series.map(([t, v]) => ({
    x: ((t - tMin) / span) * width,
    y: height - ((v - low) / vSpan) * height,
  }));
}

/* Ломаная линия как SVG-полигон. */
export function polyline(points) {
  return points.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ');
}

/* Зона пульса атлета — полосы на фоне графика.
 *
 * zones: [{name, low, high}] — границы в bpm. Возвращает полосы,
 * попадающие в диапазон значений ряда.
 */
export function zoneBands(zones, values, width, height, minValue, maxValue) {
  if (!zones || !zones.length || !values || !values.length) return [];
  const low = minValue ?? Math.min(...values);
  const high = maxValue ?? Math.max(...values);
  const span = high - low || 1;

  const bands = [];
  for (const zone of zones) {
    if (zone.high <= low || zone.low >= high) continue;
    const from = Math.max(zone.low, low);
    const to = Math.min(zone.high, high);
    const yTop = height - ((to - low) / span) * height;
    const yBottom = height - ((from - low) / span) * height;
    bands.push({
      name: zone.name,
      y: yTop,
      height: Math.max(1, yBottom - yTop),
      color: zone.color,
    });
  }
  return bands;
}

/* Подпись оси Y: значения через равные интервалы. */
export function axisLabels(minValue, maxValue, count = 4) {
  if (minValue === null || minValue === undefined) return [];
  if (maxValue === null || maxValue === undefined) return [];
  const span = maxValue - minValue;
  if (span <= 0) return [Math.round(minValue)];
  const step = span / (count - 1);
  const labels = [];
  for (let i = 0; i < count; i += 1) {
    labels.push(Math.round(maxValue - step * i));
  }
  return labels;
}

/* Подписи оси X: время в минутах.
 *
 * x — процент от начала ряда (0…100), чтобы разметка не зависела от
 * ширины полотна.
 */
export function timeLabels(series, count = 4) {
  if (!series || !series.length) return [];
  const times = series.map((point) => point[0]);
  const tMin = Math.min(...times);
  const tMax = Math.max(...times);
  const span = tMax - tMin || 1;
  const labels = [];
  for (let i = 0; i < count; i += 1) {
    const share = i / (count - 1);
    const t = tMin + span * share;
    labels.push({ x: share * 100, text: `${Math.round(t / 60)}` });
  }
  return labels;
}
