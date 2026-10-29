import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  axisLabels,
  polyline,
  timeLabels,
  toPoints,
  zoneBands,
} from '../../client/chart.js';

test('toPoints: пустой ряд даёт пустой список', () => {
  assert.deepEqual(toPoints([], 300, 100, 0, 200), []);
  assert.deepEqual(toPoints(null, 300, 100, 0, 200), []);
});

test('toPoints: точки растянуты по ширине и выс��те', () => {
  const points = toPoints([[0, 100], [60, 200]], 300, 100, 100, 200);
  assert.equal(points.length, 2);
  assert.equal(points[0].x, 0);
  assert.equal(points[1].x, 300);
  // большее значение — выше (меньший y)
  assert.equal(points[0].y, 100);
  assert.equal(points[1].y, 0);
});

test('toPoints: середина ряда даёт середину по x', () => {
  const points = toPoints([[0, 0], [30, 0], [60, 0]], 300, 100, 0, 10);
  assert.equal(points[1].x, 150);
});

test('toPoints: плоский ряд не схлопывается в линию', () => {
  const points = toPoints([[0, 150], [60, 150]], 300, 100, null, null);
  assert.ok(points[0].y > 0 && points[0].y < 100);
  assert.equal(points[0].y, points[1].y);
});

test('polyline: координаты через запятую', () => {
  const line = polyline([{ x: 0, y: 0 }, { x: 10.25, y: 5.5 }]);
  assert.equal(line, '0.0,0.0 10.3,5.5');
});

test('axisLabels: значения от максимума к минимуму', () => {
  assert.deepEqual(axisLabels(100, 200, 3), [200, 150, 100]);
});

test('axisLabels: нулевой размах — одно значение', () => {
  assert.deepEqual(axisLabels(150, 150, 4), [150]);
});

test('axisLabels: без данных — пусто', () => {
  assert.deepEqual(axisLabels(null, null, 4), []);
});

test('timeLabels: подписи в минутах по процентам ряда', () => {
  const labels = timeLabels([[0, 1], [600, 2], [1200, 3]], 3);
  assert.equal(labels.length, 3);
  assert.equal(labels[0].x, 0);
  assert.equal(labels[2].x, 100);
  assert.equal(labels[0].text, '0');
  assert.equal(labels[2].text, '20');
});

test('zoneBands: зона попадает в диапазон значений', () => {
  const zones = [
    { name: 'Z2', low: 118, high: 135, color: '#fff' },
    { name: 'Z3', low: 135, high: 150, color: '#eee' },
  ];
  const bands = zoneBands(zones, [120, 140], 300, 100, 120, 150);
  assert.equal(bands.length, 2);
  // Z2 (118–135) ниже по пульсу → ниже на графике → больше y
  assert.ok(bands[0].y > bands[1].y);
});

test('zoneBands: зона обрезается по краям диапазона', () => {
  const zones = [{ name: 'Z1', low: 90, high: 130, color: '#fff' }];
  const bands = zoneBands(zones, [120, 140], 300, 100, 120, 140);
  assert.equal(bands.length, 1);
  // зона 90–130, диапазон 120–140 → полоса от 120 до 130
  assert.ok(bands[0].height < 100);
});

test('zoneBands: зона вне диапазона отбрасывается', () => {
  const zones = [{ name: 'Z1', low: 90, high: 100, color: '#fff' }];
  const bands = zoneBands(zones, [140, 150], 300, 100, 140, 160);
  assert.equal(bands.length, 0);
});

test('zoneBands: без зон или данных — пусто', () => {
  assert.deepEqual(zoneBands([], [1, 2], 300, 100, 0, 10), []);
  assert.deepEqual(zoneBands([{ low: 0, high: 1 }], [], 300, 100, 0, 10), []);
});
