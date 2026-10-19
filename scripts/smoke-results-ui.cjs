// Development-only browser smoke. Serves built assets on loopback; all API data is synthetic.
const { chromium } = require(process.env.THERMOPOWER_PLAYWRIGHT_MODULE || "playwright");
const http = require("node:http");
const fs = require("node:fs");
const path = require("node:path");
const assert = require("node:assert/strict");
const root = path.resolve(__dirname, "..");
const output = path.join(root, "build/product-tests/ui");
const origin = Date.parse("2026-10-16T12:00:00Z");
const at = seconds => new Date(origin + seconds * 1000).toISOString();
const labels = { 25: "T25 — Saída de ar", 29: "T29 — Carcaça", 32: "T32 — Open" };
const peak = { label: labels[25], channel: 25, value_c: 80, timestamp: at(90), session_elapsed_seconds: 90, period_elapsed_seconds: 60 };
const channels = [25, 29, 32].map(channel => ({ channel, label: labels[channel], friendly_name: labels[channel], count: channel === 32 ? 0 : 10, mean: channel === 32 ? null : 60, min: channel === 32 ? null : 30, max: channel === 32 ? null : 80, range: 50, standard_deviation: 10, p95: 78, peak: channel === 32 ? null : { ...peak, channel, label: labels[channel] } }));
const stream = { session_id: 42, session_started_at: at(0), electrical: [30, 40, 50, 150, 160, 170].map((s, i) => ({ timestamp: at(s), active_power_w: i === 2 ? 0 : 500 })), temperatures: [30, 60, 90, 120, 150, 180].map(s => ({ timestamp: at(s), channel_25: s === 90 ? 80 : 50, channel_29: 45, channel_32: null })), gaps: [{ source: "electrical", after: at(50), before: at(150) }] };
const preview = { selected_channels: [25, 29, 32], channel_labels: labels, series: [stream], annotations: [], period: { start: at(30), end: at(180), timezone: "America/Sao_Paulo" }, statistics: { general: { full_session_duration_seconds: 180, analyzed_period_seconds: 150, electrical_sample_count: 6, temperature_sample_count: 6, gap_count: 1, source_quality: [] }, electrical: { active_power_w: { min: 0, max: 500, mean: 416.7, p95: 500 }, energy_wh: 5 }, temperature: { peak, max: 80, critical_channel_label: labels[25], critical_timestamp: at(90), maximum_delta_t: { value_c: 35, cold_channel: 29, hot_channel: 25 } }, channels } };
const session = { id: 42, name: "Ensaio sintético de experiência", status: "finished", started_at: at(0), ended_at: at(180), analysis_period: { start: at(30), end: at(180), label: "Período oficial" }, metadata: { product: "Produto sintético", model: "Teste", sample: "A" }, channels, device: { name: "Simulador" }, devices: [], operator: { name: "Operador de teste" }, statistics: { duration_seconds: 180 } };
const result = { ...preview, name: session.name, metadata: session.metadata, status: "finished", official: true, analysis_label: "Período oficial", permissions: { graphs: true, csv: true, pdf: false, xlsx: false } };

async function main() {
  fs.mkdirSync(output, { recursive: true });
  const server = http.createServer((req, res) => {
    const requested = decodeURIComponent(new URL(req.url, "http://localhost").pathname);
    const roots = [path.join(root, "frontend/dist-portal"), path.join(root, "frontend/dist")];
    const file = requested.startsWith("/assets/") ? roots.map(base => path.resolve(base, "." + requested)).find(candidate => roots.some(base => candidate.startsWith(base + path.sep)) && fs.existsSync(candidate)) : requested === "/portal.html" ? path.join(roots[0], "portal.html") : path.join(roots[1], "index.html");
    if (!file) { res.writeHead(404); res.end(); return; }
    res.setHeader("Content-Type", file.endsWith(".js") ? "text/javascript" : file.endsWith(".css") ? "text/css" : "text/html");
    res.end(fs.readFileSync(file));
  });
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  let browser;
  try {
    browser = await chromium.launch({ headless: true, channel: "msedge" });
    const checks = [];
    for (const [name, width, height] of [["desktop", 1440, 1000], ["mobile", 390, 844]]) {
      for (const shared of [true, false]) {
        const page = await browser.newPage({ viewport: { width, height } });
        const errors = [];
        page.on("pageerror", error => errors.push(error.message));
        await page.addInitScript(() => localStorage.setItem("thermopower.token", "synthetic-test-only"));
        await page.route("**/api/v1/**", async route => {
          const url = new URL(route.request().url());
          let value = { items: [], pages: 1, total: 0 };
          if (url.pathname.endsWith("/public/shares/access")) value = result;
          else if (url.pathname.endsWith("/auth/me")) value = { id: 1, name: "Operador de teste", role: "operator" };
          else if (url.pathname.endsWith("/sessions/42")) value = session;
          else if (url.pathname.endsWith("/reports/period/preview")) value = preview;
          await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(value) });
        });
        await page.goto(`http://127.0.0.1:${server.address().port}/${shared ? "portal.html#synthetic-result-token" : "sessoes/42"}`);
        await page.getByRole("heading", { name: session.name }).waitFor();
        await page.getByTestId("thermal-peak").first().waitFor();
        await page.locator(".recharts-line-curve").first().waitFor();
        const fits = await page.locator("body").evaluate(element => element.scrollWidth <= window.innerWidth + 1);
        if (!fits) {
          await page.screenshot({ path: path.join(output, `${name}-${shared ? "shared" : "session"}-overflow.png`), fullPage: true });
          console.log(name, shared ? "shared" : "session", await page.evaluate(() => [...document.querySelectorAll("body *")].filter(element => element.getBoundingClientRect().right > innerWidth + 1).slice(0, 15).map(element => ({ tag: element.tagName, class: element.className, width: element.getBoundingClientRect().width, right: element.getBoundingClientRect().right }))));
        }
        assert.equal(fits, true, "Page must fit viewport; tables may scroll inside their region");
        assert.equal(await page.getByRole("button", { name: "Conectar fontes" }).count(), 0);
        if (shared) {
          assert.equal(await page.getByRole("button", { name: "Baixar CSV" }).count(), 1);
          assert.equal(await page.getByRole("button", { name: "Baixar PDF" }).count(), 0);
        } else {
          assert.equal(await page.getByLabel("Canais nos arquivos").inputValue(), "selected");
        }
        assert.deepEqual(errors, []);
        const file = `${name}-${shared ? "shared" : "session"}.png`;
        await page.screenshot({ path: path.join(output, file), fullPage: true });
        checks.push({ viewport: name, page: shared ? "shared" : "session", errors, overflow: false, screenshot: file });
        await page.close();
      }
    }
    fs.writeFileSync(path.join(output, "results.json"), JSON.stringify(checks, null, 2));
    process.stdout.write(JSON.stringify(checks, null, 2) + "\n");
  } finally {
    await browser?.close();
    await new Promise(resolve => server.close(resolve));
  }
}
main().catch(error => { process.stderr.write(error.stack + "\n"); process.exitCode = 1; });
