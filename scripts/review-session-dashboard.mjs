// Run after npm run build; Playwright is isolated under build/browser-tools.
import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { resolve, extname } from 'node:path';
import { chromium } from '../build/browser-tools/node_modules/playwright/index.mjs';

const root = resolve('frontend/dist');
const server = createServer(async (request, response) => {
  try {
    const file = resolve(root, `.${new URL(request.url, 'http://localhost').pathname}`);
    if (!file.startsWith(root)) { response.writeHead(403).end(); return; }
    const path = extname(file) ? file : resolve(root, 'index.html');
    const content = await readFile(path);
    response.setHeader('Content-Type', ({ '.js': 'text/javascript', '.css': 'text/css', '.html': 'text/html' })[extname(path)] ?? 'application/octet-stream');
    response.end(content);
  } catch { response.writeHead(404).end(); }
});
await new Promise((done) => server.listen(0, '127.0.0.1', done));
const browser = await chromium.launch({ channel: 'chrome', headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 1920, height: 1200 }, timezoneId: 'America/Sao_Paulo' });
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.addInitScript(() => localStorage.setItem('thermopower.token', 'synthetic-local-review'));
  const start = Date.now() - 120_000;
  const devices = [
    { id: 1, name: 'AT4532 · fixture sintética', protocol: 'at4532_serial', active: true },
    { id: 2, name: 'GPM-8213 · fixture sintética', protocol: 'gpm8213_serial', active: true },
  ];
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    const payload = path.endsWith('/auth/me') ? { id: 1, name: 'Revisão sintética', email: 'fixture@example.test', role: 'admin' }
      : path.endsWith('/devices') ? devices
      : path.endsWith('/sessions') ? { items: [{ id: 10, device_id: 2, status: 'running', started_at: new Date(start).toISOString().replace('Z', '') }] }
      : path.endsWith('/channels') ? []
      : path.endsWith('/status') ? { connected: true, state: 'reading', sample_count: 120, session_sample_count: 120, persisted_sample_count: 120, expected_interval_ms: 1000 }
      : {};
    await route.fulfill({ json: payload });
  });
  await page.routeWebSocket('**/api/v1/ws*', (socket) => {
    let index = 0;
    const timer = setInterval(() => {
      if (index >= 120) { clearInterval(timer); return; }
      const timestamp = new Date(start + index * 1000).toISOString();
      const power = 190 * Math.exp(-index / 18) + 60;
      socket.send(JSON.stringify({ type: 'measurement.created', payload: { timestamp, received_timestamp: timestamp, device_id: 2, session_id: 10, source_role: 'electrical', power_w: power, raw_power: power, raw_power_unit: 'W', temperatures_c: [], quality: 'good' } }));
      const temperatures = [...Array(24).fill(null), ...Array.from({ length: 8 }, (_, c) => 24 + index * (0.35 + c * 0.04))];
      socket.send(JSON.stringify({ type: 'measurement.created', payload: { timestamp: new Date(start - 300_000).toISOString(), received_timestamp: new Date(start + index * 1000 + 150).toISOString(), device_id: 1, session_id: 10, source_role: 'temperature', power_w: null, raw_power: null, raw_power_unit: 'W', temperatures_c: temperatures, quality: 'good' } }));
      index++;
    }, 25);
    socket.onClose(() => clearInterval(timer));
  });
  await page.goto(`http://127.0.0.1:${server.address().port}/`);
  await page.waitForFunction(() => [...document.querySelectorAll('path.recharts-line-curve')].filter((p) => (p.getAttribute('d')?.match(/L/g) ?? []).length === 119).length === 9);
  await page.screenshot({ path: 'build/session-clock-review/dashboard.png', fullPage: true });
  if (errors.length) throw new Error(errors.join('\n'));
  console.log('PASS: 120 electrical + 120 thermal samples; nine rendered curves; America/Sao_Paulo; no browser errors.');
} finally {
  await browser.close();
  server.close();
}
