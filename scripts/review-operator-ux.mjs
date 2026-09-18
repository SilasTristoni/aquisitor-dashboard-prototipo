// Synthetic API/WebSocket fixtures; no customer data or hardware access.
// Prerequisites: frontend build, generate-client-preview-fixtures.py --samples 300
// --output build/ux-review/reports, Playwright under build/browser-tools.
import { createServer } from 'node:http';
import { readFile, mkdir, writeFile } from 'node:fs/promises';
import { resolve, extname } from 'node:path';
import assert from 'node:assert/strict';
import { chromium } from '../build/browser-tools/node_modules/playwright/index.mjs';

const output = resolve('build/ux-review');
const preview = JSON.parse(await readFile(resolve(output, 'reports/preview.json'), 'utf8'));
const root = resolve('frontend/dist');
const server = createServer(async (request, response) => {
  try {
    const file = resolve(root, `.${new URL(request.url, 'http://localhost').pathname}`);
    if (!file.startsWith(root)) { response.writeHead(403).end(); return; }
    const path = extname(file) ? file : resolve(root, 'index.html');
    response.setHeader('Content-Type', ({ '.js': 'text/javascript', '.css': 'text/css', '.html': 'text/html' })[extname(path)] ?? 'application/octet-stream');
    response.end(await readFile(path));
  } catch { response.writeHead(404).end(); }
});
await new Promise(done => server.listen(0, '127.0.0.1', done));
const base = `http://127.0.0.1:${server.address().port}`;
const user = { id: 1, name: 'Operador de revisão', email: 'operator@example.test', role: 'admin', active: true };
const devices = preview.sessions[0].devices.map(d => ({ ...d, active: true, protocol: d.id === 1 ? 'at4532_serial' : 'gpm8213_serial', connection_type: 'serial', metadata: {} }));
const session = { ...preview.sessions[0], operator: user, device: devices[0], device_id: 2, devices: devices.map(d => ({ role: d.role, device: d })), statistics: { duration_seconds: 300.15 }, channels: preview.statistics.channels.map(c => ({ channel: c.channel, name: c.friendly_name, enabled: true })), sync_tolerance_ms: 1500, sample_count: 600, alert_count: 0, device_name: 'GPM + AT4532', average_power_w: 60, maximum_temperature_c: 81 };
const paginated = items => ({ items, page: 1, page_size: 100, total: items.length, pages: items.length ? 1 : 0 });
const scenarios = [
  ['empty', '/'], ['connected', '/'], ['synchronizing', '/'], ['active', '/'],
  ['degraded', '/'], ['finished', '/'], ['session', '/sessoes/1'],
  ['exports', '/sessoes/1'], ['period-report', '/relatorios'], ['equipment-error', '/equipamentos'],
  ['sessions', '/sessoes'], ['channels', '/canais'], ['alerts', '/alertas'],
  ['compare', '/comparacao'], ['measurements', '/medicoes'], ['events', '/eventos'],
  ['imports', '/importar'], ['users', '/usuarios'], ['diagnostics', '/diagnostico'],
  ['executive', '/executivo'], ['setup', '/configuracao-inicial'], ['login', '/login'],
  ['help', '/diagnostico'], ['about', '/diagnostico'],
  ['export-error', '/sessoes/1'], ['support-event', '/eventos'],
];
const results = [];
const browser = await chromium.launch({ channel: 'chrome', headless: true });
try {
  for (const [physicalWidth, physicalHeight] of [[1366, 768], [1920, 1080]]) {
    for (const zoom of [1, 1.25]) {
      // Reproduce browser zoom's CSS viewport and device pixel ratio deterministically.
      const viewport = { width: Math.floor(physicalWidth / zoom), height: Math.floor(physicalHeight / zoom) };
      const context = await browser.newContext({ viewport, deviceScaleFactor: zoom, timezoneId: 'America/Sao_Paulo', locale: 'pt-BR' });
      for (const [scenario, path] of scenarios) {
        if (process.env.UX_SCENARIOS && !process.env.UX_SCENARIOS.split(',').includes(scenario)) continue;
        const page = await context.newPage();
        page.setDefaultTimeout(30_000);
        const errors = [];
        page.on('pageerror', error => errors.push(error.message));
        page.on('dialog', dialog => dialog.accept());
        if (scenario !== 'login') await page.addInitScript(() => localStorage.setItem('thermopower.token', 'synthetic-local-review'));
        else await page.addInitScript(() => localStorage.removeItem('thermopower.token'));
        let connected = scenario !== 'empty';
        let active = ['active', 'degraded', 'finished'].includes(scenario);
        let started = session.started_at;
        let releaseStart;
        const startGate = new Promise(done => { releaseStart = done; });
        const status = id => ({
          device_id: id, device_name: devices.find(d => d.id === id).name,
          state: connected ? 'reading' : 'disconnected', connected, reading: connected,
          source_role: id === 1 ? 'temperature' : 'electrical',
          session_id: active ? 1 : null, expected_interval_ms: 1000,
          observed_interval_ms: scenario === 'degraded' && id === 1 ? 6000 : 1000,
          cadence_degraded: scenario === 'degraded' && id === 1,
          last_message_at: new Date().toISOString(), sample_count: id === 1 && scenario === 'degraded' ? 50 : 300,
          session_sample_count: 300, persisted_sample_count: 300, valid_channels: 8,
          messages_per_second: 1, read_errors: 0, buffered_measurements: 0,
          acquisition_diagnostics: { successful_fetches: 300, fetch_timeouts: 1, consecutive_fetch_timeouts: 0, reconnect_count: 0, average_fetch_interval_ms: 1000, average_successful_rx_interval_ms: 1000, maximum_gap_ms: 2400, average_query_duration_ms: 375, last_successful_fetch_at: session.ended_at },
        });
        await page.route('**/api/v1/**', async route => {
          const url = new URL(route.request().url());
          const apiPath = url.pathname.replace('/api/v1', '');
          let payload;
          if (apiPath === '/auth/me') payload = user;
          else if (apiPath === '/build-info') payload = { demo_credentials: null, version: '0.6.4-client-preview', environment: 'client-preview', build: 'synthetic-review', build_date: '2026-09-18T14:00:00Z', client_preview: true };
          else if (apiPath === '/devices') payload = devices;
          else if (/\/devices\/\d+\/status$/.test(apiPath)) payload = status(Number(apiPath.split('/')[2]));
          else if (apiPath.endsWith('/channels')) payload = session.channels.map(c => ({ ...c, device_id: 1, sensor_type: 'K', unit: '°C', correction_offset: 0, display_order: c.channel }));
          else if (apiPath === '/sessions' && route.request().method() === 'POST') {
            if (scenario === 'synchronizing') await startGate;
            active = true; payload = { ...session, started_at: started, status: 'running' };
          } else if (apiPath === '/sessions/1/finish') { active = false; payload = { ...session, status: 'finished' }; }
          else if (apiPath === '/sessions') payload = paginated(url.searchParams.has('status') && url.searchParams.get('status') !== 'finished' ? (active ? [{ ...session, status: 'running', started_at: started }] : []) : [{ ...session, operator: user.name }]);
          else if (apiPath === '/sessions/1') payload = session;
          else if (apiPath === '/reports/period/preview') payload = preview;
          else if (apiPath === '/reports/period/executive.pdf' && scenario === 'export-error') {
            await route.fulfill({ status: 500, json: { error: { message: 'Não foi possível gerar o resumo executivo.', correlation_id: 'TP-EXP-A82F31' } } }); return;
          }
          else if (apiPath === '/events' && scenario === 'support-event') payload = paginated([{ id: 1, timestamp: session.ended_at, level: 'error', category: 'EXPORT', message: 'Não foi possível gerar o resumo executivo.', session_id: 1, details: { correlation_id: 'TP-EXP-A82F31', exception_type: 'ModuleNotFoundError', operation: 'POST /reports/period/executive.pdf' } }]);
          else if (apiPath === '/hardware/discovery') payload = [];
          else if (apiPath.endsWith('/protocol-probe')) {
            await route.fulfill({ status: 409, json: { detail: 'O equipamento está atualmente em aquisição pelo ThermoPower. Desconecte-o antes de executar o diagnóstico de comunicação.' } }); return;
          } else if (['/alerts', '/events', '/measurements'].includes(apiPath)) payload = paginated([]);
          else if (apiPath === '/users') payload = [user];
          else if (apiPath === '/diagnostics') payload = { backend_online: true, database_online: true, database_dialect: 'sqlite', system_version: '0.6.4-client-preview', environment: 'revisão sintética', disk_free_bytes: 30e9, uptime_seconds: 600, websocket_clients: 1, devices: devices.map(d => status(d.id)) };
          else if (apiPath === '/statistics/executive') payload = { total_sessions: 1, monitored_hours: 0.083, total_samples: 600, total_alerts: 0 };
          else if (['/reports', '/channel-profiles', '/alert-rules'].includes(apiPath)) payload = [];
          else throw new Error(`Unmocked ${apiPath}`);
          await route.fulfill({ json: payload });
        });
        await page.routeWebSocket('**/api/v1/ws*', socket => {
          if (!connected || path !== '/') return;
          started = new Date(Date.now() - 301_000).toISOString();
          let index = 0;
          const timer = setInterval(() => {
            if (index >= 300) { clearInterval(timer); return; }
            for (let batch = 0; batch < 20 && index < 300; batch++) {
            const time = new Date(Date.parse(started) + index * 1000).toISOString();
            const power = preview.series[0].electrical[index].active_power_w;
            socket.send(JSON.stringify({ type: 'measurement.created', payload: { timestamp: time, received_timestamp: time, device_id: 2, session_id: active ? 1 : null, source_role: 'electrical', power_w: power, raw_power: power, raw_power_unit: 'W', temperatures_c: [], quality: 'good' } }));
            if (scenario !== 'degraded' || index % 6 === 0) {
              const thermal = preview.series[0].temperatures[index];
              socket.send(JSON.stringify({ type: 'measurement.created', payload: { timestamp: time, received_timestamp: time, device_id: 1, session_id: active ? 1 : null, source_role: 'temperature', power_w: null, temperatures_c: Array.from({ length: 32 }, (_, i) => thermal[`channel_${i + 1}`] ?? null), quality: 'good' } }));
            }
            index++;
            }
          }, 25);
          socket.onClose(() => clearInterval(timer));
        });
        await page.goto(base + path);
        await page.locator('h1, .login-card h2').first().waitFor();
        if (path === '/' && connected) await page.waitForFunction(() => document.querySelectorAll('path.recharts-line-curve').length >= 9);
        if (scenario === 'synchronizing') {
          await page.getByRole('button', { name: 'Iniciar ensaio', exact: true }).click();
          await page.getByRole('button', { name: 'Sincronizando fontes...' }).waitFor();
        }
        if (scenario === 'finished') {
          await page.getByRole('button', { name: 'Finalizar ensaio', exact: true }).click();
          await page.getByRole('link', { name: 'Ver resultados' }).waitFor();
        }
        if (scenario === 'exports') await page.getByText('Exportar', { exact: true }).click();
        if (scenario === 'help' || scenario === 'about') {
          await page.locator('.help-menu > summary').click();
          if (scenario === 'about') {
            await page.getByRole('button', { name: 'Sobre o ThermoPower' }).click();
            await page.getByRole('dialog').waitFor();
          }
        }
        if (scenario === 'export-error') {
          await page.getByText('Exportar', { exact: true }).click();
          await page.getByRole('button', { name: 'Resumo executivo · PDF' }).click();
          await page.getByText('Os dados da sessão permanecem salvos.').waitFor();
          assert.equal(await page.getByRole('button', { name: 'Tentar novamente' }).count(), 1);
          assert.equal(await page.getByRole('button', { name: 'Exportar diagnóstico' }).count(), 1);
        }
        if (scenario === 'support-event') {
          await page.getByText('Mostrar detalhes técnicos').click();
          await page.getByText('Código: TP-EXP-A82F31', { exact: true }).waitFor();
        }
        if (scenario === 'period-report') {
          await page.getByRole('button', { name: 'Gerar prévia' }).click();
          await page.locator('.preview-chart').waitFor();
        }
        if (scenario === 'equipment-error') {
          await page.getByRole('button', { name: 'Testar leitura', exact: true }).first().click();
          await page.getByText('O equipamento está atualmente em aquisição pelo ThermoPower.', { exact: false }).waitFor();
        }
        if (scenario === 'degraded') await page.getByText('Leitura térmica abaixo da frequência esperada', { exact: false }).first().waitFor();
        if (path === '/' && connected) await page.waitForFunction(() => [...document.querySelectorAll('path.recharts-line-curve')].some(p => (p.getAttribute('d')?.match(/L/g) ?? []).length >= 299));
        await page.evaluate(() => document.fonts.ready);
        // Finish Recharts measurements/animations before recording the rendered layout.
        await page.waitForTimeout(400);
        const layout = await page.evaluate(() => ({
          width: innerWidth, documentWidth: document.documentElement.scrollWidth,
          overflow: [...document.querySelectorAll('.metric-card, .panel, .page-header')].filter(e => e.getBoundingClientRect().right > innerWidth + 2).map(e => e.className),
          curves: document.querySelectorAll('path.recharts-line-curve').length,
        }));
        const name = `${physicalWidth}-${Math.round(zoom * 100)}-${scenario}`;
        await mkdir(output, { recursive: true });
        await page.screenshot({ path: resolve(output, `${name}.png`), fullPage: true });
        results.push({ name, layout, errors });
        assert.equal(errors.length, 0, `${name}: ${errors.join('; ')}`);
        assert.ok(layout.documentWidth <= layout.width + 1, `${name}: horizontal overflow ${JSON.stringify(layout)}`);
        assert.equal(layout.overflow.length, 0, `${name}: clipped cards`);
        console.log(`PASS ${name}`);
        releaseStart();
        await page.close();
      }
      await context.close();
    }
  }
} finally {
  await writeFile(resolve(output, 'visual-results.json'), JSON.stringify(results, null, 2));
  await browser.close(); server.close();
}
