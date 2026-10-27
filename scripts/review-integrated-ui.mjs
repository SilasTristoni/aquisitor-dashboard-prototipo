// Synthetic API/WebSocket fixtures; no customer data or hardware access.
// Prerequisites: frontend build, generate-client-preview-fixtures.py --samples 300
// --output build/integrated-071/audit/reports, Playwright supplied by
// THERMOPOWER_PLAYWRIGHT_MODULE (or installed locally).
import { createServer } from 'node:http';
import { readFile, mkdir, writeFile } from 'node:fs/promises';
import { resolve, extname } from 'node:path';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
const { chromium } = createRequire(import.meta.url)(process.env.THERMOPOWER_PLAYWRIGHT_MODULE || 'playwright');

const output = resolve(process.env.UX_OUTPUT || 'build/integrated-071/audit');
await mkdir(output, { recursive: true });
const preview = JSON.parse(await readFile(resolve(process.env.UX_FIXTURE || resolve(output, 'reports/preview.json')), 'utf8'));
if (process.env.UX_AVAILABILITY) {
  const offset = Date.now() - 301000 - Date.parse(preview.sessions[0].started_at);
  const shift = value => {
    if (typeof value === 'string' && /^\d{4}-\d\d-\d\dT/.test(value) && Number.isFinite(Date.parse(value))) return new Date(Date.parse(value) + offset).toISOString();
    if (Array.isArray(value)) return value.map(shift);
    if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, shift(item)]));
    return value;
  };
  Object.assign(preview, shift(preview));
}
const root = resolve(process.env.UX_DIST || 'frontend/dist');
const server = createServer(async (request, response) => {
  try {
    const file = resolve(root, `.${new URL(request.url, 'http://localhost').pathname}`);
    if (!file.startsWith(root)) { response.writeHead(403).end(); return; }
    const path = extname(file) ? file : resolve(root, process.env.UX_ENTRY || 'index.html');
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
  ['shared', '/compartilhado#synthetic-review-only'],
  ['lost-sources', '/'], ['paused', '/'], ['company', '/identidade-corporativa'], ['portal', '/portal-externo'], ['empty', '/'], ['connected', '/'], ['synchronizing', '/'], ['active', '/'],
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
const browser = await chromium.launch({ channel: 'msedge', headless: true });
try {
  for (const [physicalWidth, physicalHeight] of JSON.parse(process.env.UX_VIEWPORTS || "[[1440,1000],[768,1024],[390,844]]")) {
    if (process.env.UX_WIDTHS && !process.env.UX_WIDTHS.split(',').includes(String(physicalWidth))) continue;
    for (const zoom of [1]) {
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
        let active = ['active', 'degraded', 'finished', 'lost-sources', 'paused'].includes(scenario);
        let started = session.started_at;
        let releaseStart;
        const startGate = new Promise(done => { releaseStart = done; });
        const scenarioStarted = Date.now();
        const status = id => ({
          device_id: id, device_name: devices.find(d => d.id === id).name,
          state: scenario === 'lost-sources' && Date.now() - scenarioStarted > 1500 ? 'disconnected' : connected ? 'reading' : 'disconnected', connected: connected && !(scenario === 'lost-sources' && Date.now() - scenarioStarted > 1500), reading: connected,
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
          else if (apiPath.endsWith('/availability')) payload = paginated(preview.series[0].availability ?? []);
          else if (apiPath === '/public/shares/access') payload = { ...preview, name: session.name, metadata: session.metadata, status: 'finished', official: true, permissions: { graphs: true, pdf: false, csv: false, xlsx: false } };
          else if (apiPath === '/company-identity') payload = { identity_id: '12345678-1234-1234-1234-123456789abc', company_name: 'Empresa DEMO', laboratory: 'Laboratorio sintetico', logo: null };
          else if (apiPath === '/results-portal/configuration') payload = { configured: true, can_configure: true, url: 'https://api.synthetic.example.test', installation_id: 'synthetic-lab', managed_by_environment: false };
          else if (apiPath.endsWith('/shares') || apiPath.endsWith('/annotations')) payload = paginated([]);
          else if (apiPath === '/build-info') payload = { demo_credentials: null, version: '0.7.1-engineering', environment: 'client-preview', build: 'synthetic-review', build_date: '2026-09-18T14:00:00Z', client_preview: true };
          else if (apiPath === '/devices') payload = devices;
          else if (/\/devices\/\d+\/status$/.test(apiPath)) payload = status(Number(apiPath.split('/')[2]));
          else if (apiPath.endsWith('/channels')) payload = session.channels.map(c => ({ ...c, device_id: 1, sensor_type: 'K', unit: '°C', correction_offset: 0, display_order: c.channel }));
          else if (apiPath === '/sessions' && route.request().method() === 'POST') {
            if (scenario === 'synchronizing') await startGate;
            active = true; payload = { ...session, started_at: started, status: 'running' };
          } else if (apiPath === '/sessions/1/finish') { active = false; payload = { ...session, status: 'finished' }; }
          else if (apiPath === '/sessions') payload = paginated(url.searchParams.has('status') && url.searchParams.get('status') !== 'finished' ? (active ? [{ ...session, status: scenario === 'paused' ? 'paused' : 'running', started_at: started }] : []) : [{ ...session, operator: user.name }]);
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
          else if (apiPath === '/diagnostics') payload = { backend_online: true, database_online: true, database_dialect: 'sqlite', system_version: '0.7.1-engineering', environment: 'revisão sintética', disk_free_bytes: 30e9, uptime_seconds: 600, websocket_clients: 1, devices: devices.map(d => status(d.id)) };
          else if (apiPath === '/statistics/executive') payload = { total_sessions: 1, monitored_hours: 0.083, total_samples: 600, total_alerts: 0 };
          else if (['/reports', '/channel-profiles', '/alert-rules'].includes(apiPath)) payload = [];
          else throw new Error(`Unmocked ${apiPath}`);
          await route.fulfill({ json: payload });
        });
        await page.routeWebSocket('**/api/v1/ws*', socket => {
          if (!connected || path !== '/') return;
          if (process.env.UX_AVAILABILITY) {
            const stream = [
              ...preview.series[0].electrical.map(point => ({ timestamp: point.timestamp, received_timestamp: point.timestamp, device_id: 2, session_id: 1, source_role: 'electrical', power_w: point.active_power_w, raw_power: point.active_power_w, raw_power_unit: 'W', temperatures_c: [], quality: 'good' })),
              ...preview.series[0].temperatures.map(point => ({ timestamp: point.timestamp, received_timestamp: point.timestamp, device_id: 1, session_id: 1, source_role: 'temperature', power_w: null, temperatures_c: Array.from({ length: 32 }, (_, i) => point[`channel_${i + 1}`] ?? null), quality: 'good' })),
            ].sort((a, b) => Date.parse(a.timestamp) - Date.parse(b.timestamp));
            const timer = setTimeout(() => stream.forEach(payload => socket.send(JSON.stringify({ type: 'measurement.created', payload }))), 500);
            socket.onClose(() => clearTimeout(timer));
            return;
          }
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
        if (scenario === 'lost-sources') await page.getByText(/Linha cinza tracejada/).waitFor();
        if (scenario === 'paused') await page.getByText('Ensaio pausado', { exact: true }).waitFor();
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
        if (scenario === 'degraded') await page.getByText('Frequência térmica reduzida', { exact: false }).first().waitFor();
        if (path === '/' && connected && !process.env.UX_AVAILABILITY) await page.waitForFunction(() => [...document.querySelectorAll('path.recharts-line-curve')].some(p => (p.getAttribute('d')?.match(/L/g) ?? []).length >= 299));
        await page.evaluate(() => document.fonts.ready);
        // Finish Recharts measurements/animations before recording the rendered layout.
        await page.waitForTimeout(400);
        if (process.env.UX_AVAILABILITY && !process.env.UX_BASELINE) {
          await page.waitForFunction(() => document.querySelectorAll('.availability-reference line').length === 6);
          const references = await page.locator('.availability-reference line').evaluateAll(lines => lines.map(line => ({ x1: Number(line.getAttribute('x1')), x2: Number(line.getAttribute('x2')), y1: Number(line.getAttribute('y1')), y2: Number(line.getAttribute('y2')) })));
          assert.ok(references.every(line => Object.values(line).every(Number.isFinite)));
          assert.equal(references.filter(line => Math.abs(line.y1 - line.y2) < 0.01 && line.x2 > line.x1).length, 2, 'two horizontal zero references required');
          assert.equal(references.filter(line => line.y2 < line.y1).length, 2, 'two recoveries to real samples required');
        }
        if (process.env.UX_CHART_CHECKS && scenario === 'lost-sources') {
          await page.waitForFunction(() => Number(document.querySelector('.xAxis .recharts-cartesian-axis-line')?.getAttribute('x2')) > 0);
          const geometry = await page.evaluate(() => {
            const axis = document.querySelector('.xAxis .recharts-cartesian-axis-line');
            const right = Number(axis?.getAttribute('x2'));
            const references = [...document.querySelectorAll('.recharts-reference-line-line')];
            return { right, count: references.length, outside: references.filter(line =>
              Math.max(Number(line.getAttribute('x1')), Number(line.getAttribute('x2'))) > right + 1).length };
          });
          assert.ok(geometry.count >= 2 && geometry.right > 0, JSON.stringify(geometry));
          assert.equal(geometry.outside, 0, `Outage reference outside time axis: ${JSON.stringify(geometry)}`);
        }
        const layout = await page.evaluate(() => ({
          width: innerWidth, documentWidth: document.documentElement.scrollWidth,
          overflow: [...document.querySelectorAll('.metric-card, .panel, .page-header')].filter(e => e.getBoundingClientRect().right > innerWidth + 2).map(e => e.className),
          curves: document.querySelectorAll('path.recharts-line-curve').length,
        }));
        if (process.env.UX_LAYOUT_CHECKS) {
          if (scenario === 'company') {
            const save = await page.getByRole('button', { name: /^Salvar identifica/ }).boundingBox();
            assert.ok(save.width < 240, 'Save action must keep natural width');
            await page.locator('input[type=file]').focus();
            assert.ok(await page.locator('input[type=file]').evaluate(e => e === document.activeElement), 'Upload remains keyboard accessible');
          }
          if (scenario === 'empty') {
            const boxes = await page.locator('.source-controls select, .source-controls > button').evaluateAll(items => items.map(e => { const r=e.getBoundingClientRect(); return { height:r.height, bottom:r.bottom, right:r.right }; }));
            assert.equal(boxes.length, 3);
            assert.ok(boxes.every(r => Math.abs(r.height - 44) < 1), 'Controls must share height');
            if (physicalWidth > 600) assert.ok(Math.max(...boxes.map(r => r.bottom))-Math.min(...boxes.map(r => r.bottom)) < 1, 'Controls must align at bottom');
          }
        }
        const name = `${physicalWidth}-${Math.round(zoom * 100)}-${scenario}`;
        await mkdir(output, { recursive: true });
        await page.screenshot({ path: resolve(output, `${name}.png`), fullPage: true });
        if (process.env.UX_CHART_CHECKS && await page.locator('.chart-container, .preview-chart').count()) {
          await page.locator('.chart-container, .preview-chart').first().screenshot({ path: resolve(output, `${name}-chart.png`) });
        }
        results.push({ name, layout, errors });
        if (layout.documentWidth > layout.width + 1) console.log(await page.evaluate(() => [...document.querySelectorAll('body *')].filter(element => element.getBoundingClientRect().right > innerWidth + 1).slice(0, 18).map(element => ({ tag: element.tagName, class: element.className, text: element.textContent?.slice(0, 50), right: element.getBoundingClientRect().right }))));
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
  const previous = await readFile(resolve(output, 'visual-results.json'), 'utf8').then(JSON.parse).catch(() => []);
  const combined = new Map([...previous, ...results].map(item => [item.name, item]));
  await writeFile(resolve(output, 'visual-results.json'), JSON.stringify([...combined.values()], null, 2));
  await browser.close(); server.close();
}
