(() => {
  "use strict";

  const CHANNEL_COUNT = 16;
  const MAX_POINTS = 120;
  const CHANNEL_COLORS = [
    "#3667e9", "#16a66a", "#f39b22", "#df5668",
    "#7857d8", "#1fa7bd", "#a76a2e", "#64748b",
    "#2266cc", "#2e9f7a", "#e17c1d", "#c84c86",
    "#7159c1", "#2b9bb0", "#977341", "#53627a"
  ];

  const state = {
    source: "simulation",
    connected: false,
    running: false,
    sessionStartedAt: null,
    intervalId: null,
    clockId: null,
    samples: [],
    events: [],
    powerHistory: [],
    temperatureHistories: Array.from({ length: CHANNEL_COUNT }, () => []),
    temperatures: Array.from({ length: CHANNEL_COUNT }, (_, i) => 28 + i * 0.35),
    channelsEnabled: Array.from({ length: CHANNEL_COUNT }, (_, i) => i < 8),
    powerWatts: 0,
    rawPower: { value: 0, unit: "W" },
    simulatedPowerSpike: 0,
    simulatedTemperatureSpike: 0,
    serialPort: null,
    serialReader: null,
    serialReadLoopActive: false,
    lastAlertAt: { power: 0, temperature: 0 }
  };

  const el = (id) => document.getElementById(id);

  const refs = {
    sourceSelect: el("sourceSelect"),
    connectBtn: el("connectBtn"),
    sessionBtn: el("sessionBtn"),
    exportBtn: el("exportBtn"),
    resetBtn: el("resetBtn"),
    statusDot: el("statusDot"),
    sidebarStatusDot: el("sidebarStatusDot"),
    connectionTitle: el("connectionTitle"),
    connectionDescription: el("connectionDescription"),
    sidebarStatusText: el("sidebarStatusText"),
    sidebarDeviceText: el("sidebarDeviceText"),
    sessionTime: el("sessionTime"),
    powerCurrent: el("powerCurrent"),
    powerRaw: el("powerRaw"),
    powerAverage: el("powerAverage"),
    temperatureAverage: el("temperatureAverage"),
    temperatureMax: el("temperatureMax"),
    temperatureMaxChannel: el("temperatureMaxChannel"),
    activeChannelsLabel: el("activeChannelsLabel"),
    sampleCount: el("sampleCount"),
    sessionStartedAt: el("sessionStartedAt"),
    powerMax: el("powerMax"),
    alertCount: el("alertCount"),
    channelPreview: el("channelPreview"),
    channelsGrid: el("channelsGrid"),
    temperatureLegend: el("temperatureLegend"),
    eventList: el("eventList"),
    powerChartEmpty: el("powerChartEmpty"),
    temperatureChartEmpty: el("temperatureChartEmpty"),
    intervalInput: el("intervalInput"),
    baudRateInput: el("baudRateInput"),
    temperatureLimitInput: el("temperatureLimitInput"),
    powerLimitInput: el("powerLimitInput"),
    toastContainer: el("toastContainer")
  };

  class LineChart {
    constructor(canvas, options = {}) {
      this.canvas = canvas;
      this.ctx = canvas.getContext("2d");
      this.options = options;
      this.series = [];
      this.resizeObserver = new ResizeObserver(() => this.draw());
      this.resizeObserver.observe(canvas.parentElement);
    }

    setSeries(series) {
      this.series = series;
      this.draw();
    }

    draw() {
      const rect = this.canvas.getBoundingClientRect();
      if (!rect.width || !rect.height) return;

      const ratio = window.devicePixelRatio || 1;
      this.canvas.width = Math.round(rect.width * ratio);
      this.canvas.height = Math.round(rect.height * ratio);
      this.ctx.setTransform(ratio, 0, 0, ratio, 0, 0);

      const width = rect.width;
      const height = rect.height;
      const pad = { top: 18, right: 14, bottom: 30, left: 49 };
      const plotW = width - pad.left - pad.right;
      const plotH = height - pad.top - pad.bottom;

      this.ctx.clearRect(0, 0, width, height);

      const allValues = this.series.flatMap(s => s.values.filter(Number.isFinite));
      if (!allValues.length) return;

      let min = Math.min(...allValues);
      let max = Math.max(...allValues);

      if (this.options.forceZero) min = Math.min(0, min);
      const spread = Math.max(max - min, 1);
      min -= spread * 0.12;
      max += spread * 0.12;

      const yTicks = 5;
      this.ctx.font = "10px Inter, system-ui, sans-serif";
      this.ctx.textAlign = "right";
      this.ctx.textBaseline = "middle";

      for (let i = 0; i < yTicks; i++) {
        const t = i / (yTicks - 1);
        const y = pad.top + plotH * t;
        const value = max - (max - min) * t;

        this.ctx.beginPath();
        this.ctx.strokeStyle = "#e8edf5";
        this.ctx.lineWidth = 1;
        this.ctx.moveTo(pad.left, y);
        this.ctx.lineTo(width - pad.right, y);
        this.ctx.stroke();

        this.ctx.fillStyle = "#7b879d";
        this.ctx.fillText(this.formatAxis(value), pad.left - 9, y);
      }

      const maxLen = Math.max(...this.series.map(s => s.values.length), 1);
      const xFor = (index) => pad.left + (maxLen <= 1 ? 0 : index / (maxLen - 1)) * plotW;
      const yFor = (value) => pad.top + (max - value) / (max - min) * plotH;

      this.series.forEach((series) => {
        const values = series.values;
        if (!values.length) return;

        this.ctx.beginPath();
        this.ctx.strokeStyle = series.color;
        this.ctx.lineWidth = series.width || 2;
        this.ctx.lineJoin = "round";
        this.ctx.lineCap = "round";

        let started = false;
        values.forEach((value, index) => {
          if (!Number.isFinite(value)) return;
          const x = xFor(index + Math.max(0, maxLen - values.length));
          const y = yFor(value);
          if (!started) {
            this.ctx.moveTo(x, y);
            started = true;
          } else {
            this.ctx.lineTo(x, y);
          }
        });
        this.ctx.stroke();

        if (series.fill && values.length > 1) {
          const gradient = this.ctx.createLinearGradient(0, pad.top, 0, height - pad.bottom);
          gradient.addColorStop(0, series.fill);
          gradient.addColorStop(1, "rgba(255,255,255,0)");
          this.ctx.lineTo(xFor(maxLen - 1), height - pad.bottom);
          this.ctx.lineTo(xFor(Math.max(0, maxLen - values.length)), height - pad.bottom);
          this.ctx.closePath();
          this.ctx.fillStyle = gradient;
          this.ctx.fill();
        }
      });

      this.ctx.textAlign = "left";
      this.ctx.textBaseline = "alphabetic";
      this.ctx.fillStyle = "#7b879d";
      this.ctx.fillText("mais antigo", pad.left, height - 7);
      this.ctx.textAlign = "right";
      this.ctx.fillText("agora", width - pad.right, height - 7);
    }

    formatAxis(value) {
      if (this.options.unit === "°C") return `${value.toFixed(0)}°`;
      if (this.options.unit === "W") {
        if (Math.abs(value) >= 1000) return `${(value / 1000).toFixed(1)}k`;
        return `${value.toFixed(0)}`;
      }
      return value.toFixed(1);
    }
  }

  const powerChart = new LineChart(el("powerChart"), { unit: "W", forceZero: true });
  const temperatureChart = new LineChart(el("temperatureChart"), { unit: "°C" });

  function formatClock(date) {
    return new Intl.DateTimeFormat("pt-BR", {
      hour: "2-digit", minute: "2-digit", second: "2-digit"
    }).format(date);
  }

  function formatDateTime(date) {
    return new Intl.DateTimeFormat("pt-BR", {
      day: "2-digit", month: "2-digit", year: "2-digit",
      hour: "2-digit", minute: "2-digit"
    }).format(date);
  }

  function formatDuration(ms) {
    const total = Math.max(0, Math.floor(ms / 1000));
    const h = String(Math.floor(total / 3600)).padStart(2, "0");
    const m = String(Math.floor((total % 3600) / 60)).padStart(2, "0");
    const s = String(total % 60).padStart(2, "0");
    return `${h}:${m}:${s}`;
  }

  function displayPower(watts) {
    if (!Number.isFinite(watts)) return "—";
    if (Math.abs(watts) >= 1000) return `${(watts / 1000).toFixed(2)} kW`;
    if (Math.abs(watts) < 1) return `${(watts * 1000).toFixed(0)} mW`;
    return `${watts.toFixed(1)} W`;
  }

  function powerToWatts(value, unit) {
    const normalized = String(unit || "W").trim().toLowerCase();
    if (normalized === "mw") return Number(value) / 1000;
    if (normalized === "kw") return Number(value) * 1000;
    return Number(value);
  }

  function average(values) {
    const valid = values.filter(Number.isFinite);
    return valid.length ? valid.reduce((a, b) => a + b, 0) / valid.length : NaN;
  }

  function clampHistory(array, value) {
    array.push(value);
    if (array.length > MAX_POINTS) array.shift();
  }

  function setStatus(mode, title, description) {
    [refs.statusDot, refs.sidebarStatusDot].forEach(dot => {
      dot.className = `status-dot ${mode}`;
    });
    refs.connectionTitle.textContent = title;
    refs.connectionDescription.textContent = description;
    refs.sidebarStatusText.textContent = title.replace("Dispositivo ", "");
    refs.sidebarDeviceText.textContent = state.source === "simulation" ? "Fonte simulada" : "USB / Serial";
  }

  function showToast(title, message, type = "info") {
    const node = document.createElement("div");
    node.className = `toast ${type}`;
    node.innerHTML = `
      <div class="toast-bar"></div>
      <div><strong>${escapeHtml(title)}</strong><span>${escapeHtml(message)}</span></div>
      <button aria-label="Fechar">×</button>
    `;
    node.querySelector("button").addEventListener("click", () => node.remove());
    refs.toastContainer.appendChild(node);
    setTimeout(() => node.remove(), 5000);
  }

  function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, ch => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;"
    }[ch]));
  }

  function addEvent(type, message) {
    state.events.unshift({ time: new Date(), type, message });
    state.events = state.events.slice(0, 200);
    renderEvents();
  }

  function renderEvents() {
    if (!state.events.length) {
      refs.eventList.innerHTML = `<div class="empty-state">Nenhum evento registrado.</div>`;
      return;
    }

    const labels = {
      info: "Informação",
      success: "Sucesso",
      warning: "Atenção",
      danger: "Alerta"
    };

    refs.eventList.innerHTML = state.events.map(event => `
      <div class="event-item">
        <span class="event-time">${formatClock(event.time)}</span>
        <span class="event-badge ${event.type}">${labels[event.type] || event.type}</span>
        <span>${escapeHtml(event.message)}</span>
      </div>
    `).join("");
  }

  function renderChannels() {
    refs.channelsGrid.innerHTML = state.channelsEnabled.map((enabled, index) => {
      const temp = state.temperatures[index];
      return `
        <article class="channel-card ${enabled ? "enabled" : ""}">
          <div class="channel-card-head">
            <div class="channel-card-title">
              <span class="channel-number">T${index + 1}</span>
              <strong>Termopar ${index + 1}</strong>
            </div>
            <button class="toggle ${enabled ? "on" : ""}" data-channel="${index}" aria-label="Alternar termopar ${index + 1}"></button>
          </div>
          <div class="channel-reading ${enabled ? "" : "muted"}">
            ${enabled && Number.isFinite(temp) ? `${temp.toFixed(1)} °C` : "Desativado"}
          </div>
          <div class="channel-meta">${enabled ? "Leitura disponível" : "Ignorado na coleta"}</div>
        </article>
      `;
    }).join("");

    refs.channelsGrid.querySelectorAll("[data-channel]").forEach(button => {
      button.addEventListener("click", () => {
        const index = Number(button.dataset.channel);
        state.channelsEnabled[index] = !state.channelsEnabled[index];
        addEvent("info", `Termopar ${index + 1} ${state.channelsEnabled[index] ? "ativado" : "desativado"}.`);
        renderAll();
      });
    });
  }

  function renderChannelPreview() {
    const active = state.channelsEnabled
      .map((enabled, index) => ({ enabled, index }))
      .filter(item => item.enabled)
      .slice(0, 8);

    refs.channelPreview.innerHTML = active.length
      ? active.map(({ index }) => `
          <div class="channel-mini">
            <span>TERMOPAR ${index + 1}</span>
            <strong>${Number.isFinite(state.temperatures[index]) ? `${state.temperatures[index].toFixed(1)} °C` : "—"}</strong>
          </div>
        `).join("")
      : `<div class="empty-state">Nenhum canal ativo.</div>`;
  }

  function renderLegend() {
    refs.temperatureLegend.innerHTML = state.channelsEnabled
      .map((enabled, index) => enabled ? `
        <span class="legend-item">
          <i class="legend-color" style="background:${CHANNEL_COLORS[index]}"></i>T${index + 1}
        </span>
      ` : "")
      .join("");
  }

  function renderCharts() {
    powerChart.setSeries([{
      values: state.powerHistory,
      color: "#3667e9",
      width: 2.4,
      fill: "rgba(54,103,233,.22)"
    }]);

    const temperatureSeries = state.channelsEnabled.map((enabled, index) => enabled ? {
      values: state.temperatureHistories[index],
      color: CHANNEL_COLORS[index],
      width: 1.8
    } : null).filter(Boolean);

    temperatureChart.setSeries(temperatureSeries);
    refs.powerChartEmpty.style.display = state.powerHistory.length ? "none" : "grid";
    refs.temperatureChartEmpty.style.display =
      temperatureSeries.some(series => series.values.length) ? "none" : "grid";
  }

  function renderMetrics() {
    refs.powerCurrent.textContent = state.connected && state.powerWatts
      ? displayPower(state.powerWatts)
      : "—";

    refs.powerRaw.textContent = state.connected && Number.isFinite(state.rawPower.value) && state.powerWatts
      ? `Recebido: ${Number(state.rawPower.value).toLocaleString("pt-BR", { maximumFractionDigits: 3 })} ${state.rawPower.unit}`
      : "Aguardando leitura";

    const powerValues = state.samples.map(s => s.powerW);
    const enabledTemps = state.temperatures.filter((_, i) => state.channelsEnabled[i]);
    const avgTemp = average(enabledTemps);
    const maxTemp = enabledTemps.length ? Math.max(...enabledTemps) : NaN;
    const maxTempIndex = Number.isFinite(maxTemp) ? state.temperatures.indexOf(maxTemp) : -1;

    refs.powerAverage.textContent = displayPower(average(powerValues));
    refs.temperatureAverage.textContent = Number.isFinite(avgTemp) ? `${avgTemp.toFixed(1)} °C` : "—";
    refs.temperatureMax.textContent = Number.isFinite(maxTemp) ? `${maxTemp.toFixed(1)} °C` : "—";
    refs.temperatureMaxChannel.textContent = maxTempIndex >= 0 ? `Termopar ${maxTempIndex + 1}` : "Sem leituras";
    refs.activeChannelsLabel.textContent = `${state.channelsEnabled.filter(Boolean).length} canais ativos`;
    refs.sampleCount.textContent = state.samples.length.toLocaleString("pt-BR");
    refs.sessionStartedAt.textContent = state.sessionStartedAt ? formatDateTime(state.sessionStartedAt) : "—";
    refs.powerMax.textContent = displayPower(powerValues.length ? Math.max(...powerValues) : NaN);
    refs.alertCount.textContent = state.events.filter(e => e.type === "danger" || e.type === "warning").length;
    refs.exportBtn.disabled = !state.samples.length;
  }

  function renderConnection() {
    refs.connectBtn.textContent = state.connected ? "Desconectar" : "Conectar";
    refs.sourceSelect.disabled = state.connected;
    refs.sessionBtn.disabled = !state.connected;
    refs.sessionBtn.textContent = state.running ? "Pausar sessão" : (state.samples.length ? "Continuar sessão" : "Iniciar sessão");

    if (state.running) {
      setStatus("running", "Dispositivo em coleta", "Dados sendo recebidos e armazenados na sessão.");
    } else if (state.connected) {
      setStatus("connected", "Dispositivo conectado", "Conexão pronta. Inicie a sessão para armazenar leituras.");
    } else {
      setStatus("disconnected", "Dispositivo desconectado", "Selecione uma fonte de dados e conecte para iniciar.");
    }
  }

  function renderAll() {
    renderConnection();
    renderMetrics();
    renderChannels();
    renderChannelPreview();
    renderLegend();
    renderCharts();
    renderEvents();
  }

  function generateSimulationPayload() {
    let basePower = 820 + Math.sin(Date.now() / 6500) * 180 + (Math.random() - 0.5) * 80;
    if (state.simulatedPowerSpike > 0) {
      basePower += state.simulatedPowerSpike;
      state.simulatedPowerSpike *= 0.58;
      if (state.simulatedPowerSpike < 10) state.simulatedPowerSpike = 0;
    }
    basePower = Math.max(20, basePower);

    const unitChoices = ["mW", "W", "kW"];
    const unit = unitChoices[Math.floor(Math.random() * unitChoices.length)];
    let rawValue = basePower;
    if (unit === "mW") rawValue = basePower * 1000;
    if (unit === "kW") rawValue = basePower / 1000;

    const temperatures = state.temperatures.map((previous, index) => {
      const target = 30 + index * 0.45 + Math.sin(Date.now() / 9000 + index * 0.7) * 2.5;
      let next = previous + (target - previous) * 0.12 + (Math.random() - 0.5) * 0.35;
      if (state.simulatedTemperatureSpike > 0 && index === 2) {
        next += state.simulatedTemperatureSpike;
        state.simulatedTemperatureSpike *= 0.62;
        if (state.simulatedTemperatureSpike < 0.1) state.simulatedTemperatureSpike = 0;
      }
      return Number(next.toFixed(2));
    });

    return { power: Number(rawValue.toFixed(3)), powerUnit: unit, temperatures };
  }

  function handlePayload(payload) {
    if (!payload || typeof payload !== "object") {
      addEvent("warning", "Leitura ignorada: conteúdo inválido.");
      return;
    }

    const powerW = powerToWatts(payload.power, payload.powerUnit);
    if (!Number.isFinite(powerW)) {
      addEvent("warning", "Leitura ignorada: potência inválida.");
      return;
    }

    const incomingTemps = Array.isArray(payload.temperatures) ? payload.temperatures : [];
    const normalizedTemps = Array.from({ length: CHANNEL_COUNT }, (_, index) => {
      const value = Number(incomingTemps[index]);
      return Number.isFinite(value) ? value : state.temperatures[index];
    });

    state.powerWatts = powerW;
    state.rawPower = { value: payload.power, unit: payload.powerUnit || "W" };
    state.temperatures = normalizedTemps;

    if (state.running) {
      const timestamp = new Date();
      state.samples.push({
        timestamp,
        powerW,
        temperatures: [...normalizedTemps]
      });

      clampHistory(state.powerHistory, powerW);
      normalizedTemps.forEach((temp, index) => clampHistory(state.temperatureHistories[index], temp));
      checkAlerts(powerW, normalizedTemps);
    }

    renderAll();
  }

  function checkAlerts(powerW, temperatures) {
    const now = Date.now();
    const powerLimit = Number(refs.powerLimitInput.value);
    const tempLimit = Number(refs.temperatureLimitInput.value);

    if (Number.isFinite(powerLimit) && powerW > powerLimit && now - state.lastAlertAt.power > 10000) {
      state.lastAlertAt.power = now;
      const message = `Potência acima do limite: ${displayPower(powerW)} (limite ${displayPower(powerLimit)}).`;
      addEvent("danger", message);
      showToast("Alerta de potência", message, "danger");
    }

    const activeReadings = temperatures
      .map((value, index) => ({ value, index }))
      .filter(item => state.channelsEnabled[item.index] && Number.isFinite(item.value));

    const hottest = activeReadings.sort((a, b) => b.value - a.value)[0];
    if (hottest && Number.isFinite(tempLimit) && hottest.value > tempLimit && now - state.lastAlertAt.temperature > 10000) {
      state.lastAlertAt.temperature = now;
      const message = `Termopar ${hottest.index + 1} acima do limite: ${hottest.value.toFixed(1)} °C.`;
      addEvent("danger", message);
      showToast("Alerta de temperatura", message, "danger");
    }
  }

  function restartSimulationTimer() {
    clearInterval(state.intervalId);
    state.intervalId = null;
    if (state.connected && state.source === "simulation") {
      const interval = Number(refs.intervalInput.value) || 1000;
      state.intervalId = setInterval(() => handlePayload(generateSimulationPayload()), interval);
      handlePayload(generateSimulationPayload());
    }
  }

  async function connect() {
    state.source = refs.sourceSelect.value;

    if (state.source === "simulation") {
      state.connected = true;
      addEvent("success", "Simulador conectado.");
      showToast("Conexão estabelecida", "O simulador está pronto para enviar leituras.", "info");
      restartSimulationTimer();
      renderAll();
      return;
    }

    if (!("serial" in navigator)) {
      showToast("USB serial indisponível", "Abra o sistema no Chrome ou Edge em localhost/HTTPS.", "danger");
      addEvent("danger", "O navegador não disponibilizou acesso à porta serial.");
      return;
    }

    try {
      const port = await navigator.serial.requestPort();
      await port.open({ baudRate: Number(refs.baudRateInput.value) || 9600 });
      state.serialPort = port;
      state.connected = true;
      state.serialReadLoopActive = true;
      addEvent("success", `Porta USB/serial aberta em ${refs.baudRateInput.value} baud.`);
      showToast("Dispositivo conectado", "Aguardando mensagens JSON terminadas por quebra de linha.", "info");
      renderAll();
      readSerialLoop(port);
    } catch (error) {
      addEvent("danger", `Falha ao conectar: ${error.message || error}`);
      showToast("Falha na conexão", error.message || "Não foi possível abrir a porta.", "danger");
    }
  }

  async function readSerialLoop(port) {
    const decoder = new TextDecoder();
    let buffer = "";

    try {
      while (state.serialReadLoopActive && port.readable) {
        const reader = port.readable.getReader();
        state.serialReader = reader;
        try {
          while (state.serialReadLoopActive) {
            const { value, done } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });

            let newlineIndex;
            while ((newlineIndex = buffer.indexOf("\n")) >= 0) {
              const line = buffer.slice(0, newlineIndex).trim();
              buffer = buffer.slice(newlineIndex + 1);
              if (!line) continue;

              try {
                handlePayload(JSON.parse(line));
              } catch {
                addEvent("warning", `Linha USB ignorada: ${line.slice(0, 80)}`);
              }
            }
          }
        } finally {
          reader.releaseLock();
          state.serialReader = null;
        }
      }
    } catch (error) {
      if (state.connected) {
        addEvent("danger", `Comunicação serial interrompida: ${error.message || error}`);
        showToast("Comunicação interrompida", "A conexão USB foi encerrada inesperadamente.", "danger");
      }
      await disconnect();
    }
  }

  async function disconnect() {
    state.running = false;
    state.connected = false;
    state.serialReadLoopActive = false;
    clearInterval(state.intervalId);
    state.intervalId = null;

    if (state.serialReader) {
      try { await state.serialReader.cancel(); } catch {}
    }
    if (state.serialPort) {
      try { await state.serialPort.close(); } catch {}
    }
    state.serialReader = null;
    state.serialPort = null;

    addEvent("info", "Dispositivo desconectado.");
    renderAll();
  }

  function toggleSession() {
    if (!state.connected) return;

    state.running = !state.running;
    if (state.running) {
      if (!state.sessionStartedAt) state.sessionStartedAt = new Date();
      addEvent("success", "Sessão de medição iniciada.");
      showToast("Coleta iniciada", "As leituras agora estão sendo armazenadas.", "info");
    } else {
      addEvent("info", "Sessão de medição pausada.");
    }
    renderAll();
  }

  function resetSession() {
    state.running = false;
    state.sessionStartedAt = null;
    state.samples = [];
    state.powerHistory = [];
    state.temperatureHistories = Array.from({ length: CHANNEL_COUNT }, () => []);
    state.lastAlertAt = { power: 0, temperature: 0 };
    addEvent("info", "Dados da sessão removidos.");
    renderAll();
  }

  function exportCsv() {
    if (!state.samples.length) return;

    const headers = [
      "timestamp_iso",
      "potencia_w",
      ...Array.from({ length: CHANNEL_COUNT }, (_, index) => `temperatura_t${index + 1}_c`)
    ];

    const rows = state.samples.map(sample => [
      sample.timestamp.toISOString(),
      sample.powerW.toFixed(6),
      ...sample.temperatures.map(value => Number.isFinite(value) ? value.toFixed(3) : "")
    ]);

    const csv = [headers, ...rows]
      .map(row => row.map(value => `"${String(value).replaceAll('"', '""')}"`).join(";"))
      .join("\r\n");

    const blob = new Blob(["\ufeff", csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `medicao_${new Date().toISOString().replace(/[:.]/g, "-")}.csv`;
    anchor.click();
    URL.revokeObjectURL(url);
    addEvent("success", `${state.samples.length} amostras exportadas para CSV.`);
  }

  function switchSection(section) {
    document.querySelectorAll(".section-panel").forEach(panel => panel.classList.remove("active"));
    document.querySelectorAll(".nav-item").forEach(item => item.classList.remove("active"));

    el(`${section}Section`)?.classList.add("active");
    document.querySelector(`.nav-item[data-section="${section}"]`)?.classList.add("active");

    if (section === "dashboard") {
      requestAnimationFrame(() => renderCharts());
    }
  }

  function setupListeners() {
    document.querySelectorAll(".nav-item").forEach(item => {
      item.addEventListener("click", () => switchSection(item.dataset.section));
    });

    document.querySelectorAll("[data-go-section]").forEach(item => {
      item.addEventListener("click", () => switchSection(item.dataset.goSection));
    });

    refs.sourceSelect.addEventListener("change", () => {
      state.source = refs.sourceSelect.value;
      renderConnection();
    });

    refs.connectBtn.addEventListener("click", async () => {
      if (state.connected) await disconnect();
      else await connect();
    });

    refs.sessionBtn.addEventListener("click", toggleSession);
    refs.exportBtn.addEventListener("click", exportCsv);
    refs.resetBtn.addEventListener("click", resetSession);

    refs.intervalInput.addEventListener("change", restartSimulationTimer);

    el("enableFirstEightBtn").addEventListener("click", () => {
      state.channelsEnabled = state.channelsEnabled.map((_, index) => index < 8);
      addEvent("info", "Termopares 1 a 8 ativados.");
      renderAll();
    });

    el("disableAllBtn").addEventListener("click", () => {
      state.channelsEnabled = state.channelsEnabled.map(() => false);
      addEvent("info", "Todos os termopares foram desativados.");
      renderAll();
    });

    el("clearEventsBtn").addEventListener("click", () => {
      state.events = [];
      renderEvents();
    });

    el("temperatureSpikeBtn").addEventListener("click", () => {
      state.simulatedTemperatureSpike = 62;
      addEvent("warning", "Teste solicitado: pico de temperatura no termopar 3.");
      showToast("Teste preparado", "O próximo ciclo terá um pico de temperatura.", "warning");
    });

    el("powerSpikeBtn").addEventListener("click", () => {
      state.simulatedPowerSpike = 2500;
      addEvent("warning", "Teste solicitado: pico de potência.");
      showToast("Teste preparado", "O próximo ciclo terá um pico de potência.", "warning");
    });

    el("disconnectTestBtn").addEventListener("click", async () => {
      if (!state.connected) {
        showToast("Sem conexão", "Conecte o simulador antes de testar a desconexão.", "warning");
        return;
      }
      await disconnect();
      showToast("Desconexão simulada", "O comportamento de perda de conexão foi executado.", "warning");
    });

    navigator.serial?.addEventListener?.("disconnect", async () => {
      if (state.source === "usb" && state.connected) {
        addEvent("danger", "O equipamento USB foi removido.");
        await disconnect();
      }
    });

    window.addEventListener("beforeunload", () => {
      clearInterval(state.intervalId);
      clearInterval(state.clockId);
    });
  }

  function startClock() {
    state.clockId = setInterval(() => {
      refs.sessionTime.textContent = state.sessionStartedAt
        ? formatDuration(Date.now() - state.sessionStartedAt.getTime())
        : "00:00:00";
    }, 500);
  }

  setupListeners();
  startClock();
  addEvent("info", "Protótipo carregado. Use o simulador para iniciar os testes.");
  renderAll();
})();
