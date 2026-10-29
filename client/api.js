/* Coach App — работа с сервером.
 *
 * Единственное место, где ходят на сервер. Значит, добавление заголовка
 * Authorization (когда появится авторизация) затронет только этот файл.
 */

const BASE = localStorage.getItem('coach-app-base') || '';

function base() {
  return localStorage.getItem('coach-app-base') || BASE;
}

async function request(path, options = {}) {
  const response = await fetch(base() + path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });

  let body = null;
  try {
    body = await response.json();
  } catch (error) {
    body = null;
  }

  if (!response.ok) {
    const error = new Error((body && body.error && body.error.message) || `HTTP ${response.status}`);
    error.code = body && body.error && body.error.code;
    error.status = response.status;
    error.version = body && body.version;
    error.data = body && body.data;
    throw error;
  }

  return body;
}

export async function getSnapshot() {
  return request('/api/v1/snapshot');
}

export async function getWeek(seasonWeek) {
  return request(`/api/v1/week/${seasonWeek}`);
}

export async function getActual(seasonWeek) {
  return request(`/api/v1/actual/${seasonWeek}`);
}

export async function getAthlete() {
  return request('/api/v1/athlete');
}

export async function getSeason() {
  return request('/api/v1/season');
}

export async function sendCommand(command) {
  return request('/api/v1/commands', {
    method: 'POST',
    body: JSON.stringify(command),
  });
}

export async function narrate(about, diff) {
  return request('/api/v1/narrate', {
    method: 'POST',
    body: JSON.stringify({ about, diff }),
  });
}

/* События: SSE с backoff. */
export function subscribe(onChange) {
  let source = null;
  let delay = 1000;

  const connect = () => {
    source = new EventSource(base() + '/api/v1/events');

    source.onmessage = (event) => {
      delay = 1000;
      try {
        onChange(JSON.parse(event.data));
      } catch (error) {
        /* мусор в потоке игнорируем */
      }
    };

    source.onerror = () => {
      if (source) source.close();
      setTimeout(connect, delay);
      delay = Math.min(delay * 2, 30000);
    };
  };

  connect();
  return () => {
    if (source) source.close();
  };
}
