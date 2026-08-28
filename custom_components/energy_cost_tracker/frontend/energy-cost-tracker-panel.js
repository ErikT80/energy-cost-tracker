class EnergyCostTrackerPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._summary = null;
    this._history = null;
    this._tab = "overview";
    this._loading = false;
    this._filters = { start: "", end: "", quality: "", activity: "" };
    this._chart = null;
    this._chartRange = null;
    this._chartLoading = false;
    this._chartError = null;
    this._chartView = "month";
    this._chartAnchor = new Date();
    this._chartSeries = {
      net_cost: true,
      pv_value: true,
      battery_profit: true,
      import_price: true,
      export_price: true
    };
  }

  set hass(value) {
    const first = !this._hass;
    const previous = this._hass;
    this._hass = value;
    if (first) {
      this.loadSummary();
      return;
    }
    const cfg = this._summary?.config || {};
    const watched = [cfg.import_price, cfg.export_price].filter(Boolean);
    const priceChanged = watched.some(entityId => previous?.states?.[entityId]?.state !== value?.states?.[entityId]?.state);
    if (priceChanged && this._summary) {
      this.updateLivePricesFromHass();
      if (this._tab === "overview") this.render();
    }
  }
  set narrow(value) { this._narrow = value; }
  set panel(value) { this._panel = value; }

  money(value) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
    const currency = this._summary?.currency || "EUR";
    try { return new Intl.NumberFormat(undefined, { style: "currency", currency }).format(Number(value)); }
    catch (_) { return `${Number(value).toFixed(2)} ${currency}`; }
  }
  num(value, digits = 2) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
    return new Intl.NumberFormat(undefined, { maximumFractionDigits: digits }).format(Number(value));
  }

  periodMoney(period, exactKey, knownKey, incompleteKey) {
    const exact = period?.[exactKey];
    if (exact !== null && exact !== undefined && !Number.isNaN(Number(exact))) {
      return this.money(exact);
    }
    const known = period?.[knownKey];
    if (known === null || known === undefined || Number.isNaN(Number(known))) return "—";
    return `${this.money(known)}${Number(period?.[incompleteKey] || 0) > 0 ? " *" : ""}`;
  }

  incompleteText(period, key) {
    const count = Number(period?.[key] || 0);
    return count > 0 ? `⚠ ${count} interval${count === 1 ? "" : "len"} zonder volledige prijsdata` : "";
  }

  async loadChart(start, end, granularity) {
    if (!this._hass || !start || !end || this._chartLoading) return;
    this._chartLoading = true;
    this._chartError = null;
    try {
      const result = await this._hass.callWS({
        type: "energy_cost_tracker/chart",
        start,
        end,
        granularity
      });
      this._chart = result;
      this._chartRange = { start: result.start, end: result.end };
    } catch (err) {
      this._chartError = String(err);
    }
    this._chartLoading = false;
    this.render();
  }

  chartViewRange(view = this._chartView, anchor = this._chartAnchor || new Date()) {
    const d = new Date(anchor);
    let start;
    let end;
    let granularity;
    if (view === "month") {
      start = new Date(d.getFullYear(), 0, 1, 0, 0, 0, 0);
      end = new Date(d.getFullYear() + 1, 0, 1, 0, 0, 0, 0);
      granularity = "month";
    } else if (view === "day") {
      start = new Date(d.getFullYear(), d.getMonth(), 1, 0, 0, 0, 0);
      end = new Date(d.getFullYear(), d.getMonth() + 1, 1, 0, 0, 0, 0);
      granularity = "day";
    } else {
      start = new Date(d.getFullYear(), d.getMonth(), d.getDate(), 0, 0, 0, 0);
      end = new Date(d.getFullYear(), d.getMonth(), d.getDate() + 1, 0, 0, 0, 0);
      granularity = view === "quarter" ? "quarter" : "hour";
    }
    return { start: start.toISOString(), end: end.toISOString(), granularity };
  }

  async loadChartView(view = this._chartView, anchor = this._chartAnchor || new Date()) {
    this._chartView = view;
    this._chartAnchor = new Date(anchor);
    const range = this.chartViewRange(view, this._chartAnchor);
    await this.loadChart(range.start, range.end, range.granularity);
  }

  async resetChart() {
    await this.loadChartView(this._chartView || "month", new Date());
  }

  shiftChart(direction) {
    const d = new Date(this._chartAnchor || new Date());
    if (this._chartView === "month") d.setFullYear(d.getFullYear() + direction);
    else if (this._chartView === "day") d.setMonth(d.getMonth() + direction);
    else d.setDate(d.getDate() + direction);
    this.loadChartView(this._chartView, d);
  }

  chartViewTitle() {
    const d = new Date(this._chartAnchor || new Date());
    if (this._chartView === "month") return String(d.getFullYear());
    if (this._chartView === "day") return d.toLocaleDateString(undefined, { month: "long", year: "numeric" });
    return d.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "long", year: "numeric" });
  }

  chartLabel(value, granularity) {
    const d = new Date(value);
    if (granularity === "month") return d.toLocaleDateString(undefined, { month: "short" });
    if (granularity === "day") return d.toLocaleDateString(undefined, { day: "numeric" });
    if (granularity === "hour") return d.toLocaleTimeString(undefined, { hour: "2-digit" });
    return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  }

  priceAmount(value) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
    const currency = this._summary?.currency || "EUR";
    try {
      return new Intl.NumberFormat(undefined, { style: "currency", currency, minimumFractionDigits: 3, maximumFractionDigits: 5 }).format(Number(value));
    } catch (_) {
      return `${Number(value).toFixed(4)} ${currency}`;
    }
  }

  price(value) {
    const amount = this.priceAmount(value);
    return amount === "—" ? amount : `${amount}/kWh`;
  }

  configuredPrice(entityId, multiplier = 1, adjustment = 0) {
    const state = entityId ? this._hass?.states?.[entityId] : null;
    const raw = Number(state?.state);
    if (!state || !Number.isFinite(raw)) return null;
    let value = raw;
    const unit = String(state.attributes?.unit_of_measurement || "").trim().toLowerCase().replaceAll(" ", "");
    if (unit.includes("/mwh")) value /= 1000;
    else if (["ct/kwh", "c/kwh", "cent/kwh", "p/kwh", "pence/kwh"].some(token => unit.includes(token))) value /= 100;
    return value * Number(multiplier ?? 1) + Number(adjustment ?? 0);
  }

  updateLivePricesFromHass() {
    const cfg = this._summary?.config || {};
    if (!this._summary) return;
    this._summary.live = this._summary.live || {};
    const importPrice = this.configuredPrice(cfg.import_price, cfg.import_price_multiplier, cfg.import_price_adjustment);
    const exportPrice = this.configuredPrice(cfg.export_price, cfg.export_price_multiplier, cfg.export_price_adjustment);
    if (importPrice !== null) this._summary.live.import_price = importPrice;
    if (exportPrice !== null) this._summary.live.export_price = exportPrice;
  }

  chartViewSelector() {
    const labels = { month: "Maand", day: "Dag", hour: "Uur", quarter: "Kwartier" };
    return `<div class="chartViewSelector">${Object.entries(labels).map(([key,label]) => `<button data-chart-view="${key}" class="${this._chartView === key ? "active" : ""}">${label}</button>`).join("")}</div>`;
  }

  chartControls() {
    const range = this.chartViewRange(this._chartView, this._chartAnchor);
    const disableNext = new Date(range.end).getTime() > Date.now();
    return `<div class="chartControls"><button id="chartPrev" title="Vorige periode">‹</button><button id="chartNow">Nu</button><button id="chartNext" title="Volgende periode" ${disableNext ? "disabled" : ""}>›</button></div>`;
  }

  chartSeriesSelector() {
    const items = [
      ["net_cost", "Nettokosten", "cost"],
      ["pv_value", "PV-waarde", "pv"],
      ["battery_profit", "Batterijwinst", "battery"],
      ["import_price", "Afnameprijs", "importPrice"],
      ["export_price", "Terugleverprijs", "exportPrice"]
    ];
    return `<div class="chartSeriesSelector">${items.map(([key,label,cls]) => `<button data-chart-series="${key}" class="seriesToggle ${cls} ${this._chartSeries[key] ? "active" : "off"}"><i></i>${label}</button>`).join("")}</div>`;
  }

  renderFinanceChart() {
    const chart = this._chart;
    const rows = chart?.rows || [];
    const live = this._summary?.live || {};
    const partial = rows.reduce((n, r) => n + Number(!r.financial_complete || !r.pv_complete || !r.battery_complete), 0);
    const header = `<div class="chartHead"><div><h2>Financieel verloop</h2><div class="sub">${this.chartViewTitle()}${partial ? ` · ⚠ ${partial} onvolledige punten` : ""}</div></div>${this.chartControls()}</div>
      <div class="chartToolbar">${this.chartViewSelector()}<div class="priceNow"><span>Afname nu <b>${this.price(live.import_price)}</b></span><span>Teruglevering nu <b>${this.price(live.export_price)}</b></span></div></div>
      ${this.chartSeriesSelector()}`;
    if (!chart || this._chartLoading) {
      return `<div class="section chartSection">${header}<div class="chartEmpty">${this._chartError || "Grafiek laden…"}</div></div>`;
    }
    if (!rows.length) {
      return `<div class="section chartSection">${header}<div class="chartEmpty">Geen ledgerdata in deze periode.</div></div>`;
    }

    const width = chart.granularity === "quarter" ? Math.max(1000, rows.length * 15 + 142) : 1000, height = 360, left = 70, right = 72, top = 22, bottom = 58;
    const plotW = width - left - right, plotH = height - top - bottom;
    const financeKeys = ["net_cost", "pv_value", "battery_profit"].filter(k => this._chartSeries[k]);
    const priceKeys = ["import_price", "export_price"].filter(k => this._chartSeries[k]);
    const financeValues = [];
    const priceValues = [];
    for (const r of rows) {
      for (const k of financeKeys) { const n = Number(r[k]); if (Number.isFinite(n)) financeValues.push(n); }
      for (const k of priceKeys) { const n = Number(r[k]); if (Number.isFinite(n)) priceValues.push(n); }
    }

    let fMin = Math.min(0, ...financeValues), fMax = Math.max(0, ...financeValues);
    if (fMax - fMin < 0.01) { fMax += 0.01; fMin -= 0.01; }
    let fPad = (fMax - fMin) * 0.08; fMax += fPad; fMin -= fPad;
    let pMin = Math.min(0, ...priceValues), pMax = Math.max(0, ...priceValues);
    if (pMax - pMin < 0.01) { pMax += 0.01; pMin -= 0.01; }
    let pPad = (pMax - pMin) * 0.08; pMax += pPad; pMin -= pPad;

    const fy = v => top + (fMax - Number(v)) / (fMax - fMin) * plotH;
    const py = v => top + (pMax - Number(v)) / (pMax - pMin) * plotH;
    const slotW = plotW / Math.max(1, rows.length);
    const xCenter = i => left + slotW * (i + 0.5);
    const barCount = Math.max(1, financeKeys.length);
    const groupW = Math.min(slotW * 0.78, 48);
    const barGap = financeKeys.length > 1 ? Math.min(3, groupW * 0.06) : 0;
    const barW = Math.max(1, (groupW - barGap * (barCount - 1)) / barCount);
    const zeroY = fy(0);
    const barClass = { net_cost: "costBar", pv_value: "pvBar", battery_profit: "batteryBar" };
    const bars = rows.map((r, i) => financeKeys.map((key, j) => {
      const value = Number(r[key]);
      if (!Number.isFinite(value)) return "";
      const x = xCenter(i) - groupW / 2 + j * (barW + barGap);
      const vy = fy(value);
      const y = Math.min(zeroY, vy);
      const h = Math.max(1, Math.abs(zeroY - vy));
      return `<rect class="chartBar ${barClass[key]}" x="${x.toFixed(2)}" y="${y.toFixed(2)}" width="${barW.toFixed(2)}" height="${h.toFixed(2)}" rx="2"></rect>`;
    }).join("")).join("");

    const pricePath = key => {
      let d = "", open = false;
      rows.forEach((r, i) => {
        const value = Number(r[key]);
        if (!Number.isFinite(value)) { open = false; return; }
        d += `${open ? "L" : "M"}${xCenter(i).toFixed(2)},${py(value).toFixed(2)} `;
        open = true;
      });
      return d.trim();
    };
    const fTicks = Array.from({ length: 5 }, (_, i) => fMin + (fMax - fMin) * i / 4);
    const pTicks = Array.from({ length: 5 }, (_, i) => pMin + (pMax - pMin) * i / 4);
    const xTickCount = Math.min(chart.granularity === "quarter" ? 13 : 7, rows.length);
    const xIndexes = [...new Set(Array.from({ length: xTickCount }, (_, i) => Math.round(i * (rows.length - 1) / Math.max(1, xTickCount - 1))))];

    return `<div class="section chartSection">
      ${header}
      <div class="chartBox">
        <svg id="financeChart" data-view-width="${width}" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" aria-label="Financieel verloop" style="${chart.granularity === "quarter" ? `width:${Math.max(1050, width)}px;max-width:none` : ""}">
          ${fTicks.map(v => `<line class="chartGrid" x1="${left}" x2="${width-right}" y1="${fy(v)}" y2="${fy(v)}"></line><text class="chartYLabel" x="${left-10}" y="${fy(v)+4}" text-anchor="end">${this.money(v)}</text>`).join("")}
          ${priceKeys.length ? pTicks.map(v => `<text class="chartPriceYLabel" x="${width-right+10}" y="${py(v)+4}" text-anchor="start">${this.priceAmount(v)}</text>`).join("") : ""}
          <line class="chartZero" x1="${left}" x2="${width-right}" y1="${zeroY}" y2="${zeroY}"></line>
          ${xIndexes.map(i => `<text class="chartXLabel" x="${xCenter(i)}" y="${height-22}" text-anchor="middle">${this.chartLabel(rows[i].start, chart.granularity)}</text>`).join("")}
          ${bars}
          ${this._chartSeries.import_price ? `<path class="priceLine importPriceLine" d="${pricePath("import_price")}"></path>` : ""}
          ${this._chartSeries.export_price ? `<path class="priceLine exportPriceLine" d="${pricePath("export_price")}"></path>` : ""}
          <line id="chartCursor" class="chartCursor" x1="0" x2="0" y1="${top}" y2="${height-bottom}" visibility="hidden"></line>
        </svg>
        <div id="chartTooltip" class="chartTooltip" hidden></div>
      </div>
      <div class="hint chartHint">Balken gebruiken de linker as (€ per periode). Prijslijnen gebruiken de rechter as (€ per kWh). Maand toont maanden van het gekozen jaar, Dag de dagen van de gekozen maand, Uur de uren van de gekozen dag en Kwartier de 15-minutenblokken van die dag.</div>
    </div>`;
  }

  bindChartInteractions() {
    this.shadowRoot.querySelectorAll("[data-chart-view]").forEach(el => el.addEventListener("click", () => this.loadChartView(el.dataset.chartView, this._chartAnchor)));
    this.shadowRoot.querySelectorAll("[data-chart-series]").forEach(el => el.addEventListener("click", () => {
      const key = el.dataset.chartSeries;
      this._chartSeries[key] = !this._chartSeries[key];
      try { localStorage.setItem("energy_cost_tracker_chart_series", JSON.stringify(this._chartSeries)); } catch (_) {}
      this.render();
    }));
    this.shadowRoot.querySelector("#chartPrev")?.addEventListener("click", () => this.shiftChart(-1));
    this.shadowRoot.querySelector("#chartNext")?.addEventListener("click", () => this.shiftChart(1));
    this.shadowRoot.querySelector("#chartNow")?.addEventListener("click", () => this.resetChart());

    const svg = this.shadowRoot.querySelector("#financeChart");
    if (!svg || !this._chart?.rows?.length) return;
    const rows = this._chart.rows;
    const tooltip = this.shadowRoot.querySelector("#chartTooltip");
    const cursor = this.shadowRoot.querySelector("#chartCursor");
    const left = 70, right = 72, viewW = Number(svg.dataset.viewWidth || 1000);
    const plotW = viewW - left - right;
    const slotW = plotW / Math.max(1, rows.length);

    const indexForEvent = ev => {
      const rect = svg.getBoundingClientRect();
      const vx = (ev.clientX - rect.left) / Math.max(1, rect.width) * viewW;
      return Math.max(0, Math.min(rows.length - 1, Math.floor((vx - left) / Math.max(1, slotW))));
    };
    const showTooltip = ev => {
      if (!tooltip) return;
      const i = indexForEvent(ev);
      const r = rows[i];
      const rect = svg.getBoundingClientRect();
      const px = left + slotW * (i + 0.5);
      if (cursor) { cursor.setAttribute("x1", px); cursor.setAttribute("x2", px); cursor.setAttribute("visibility", "visible"); }
      const partial = !r.financial_complete || !r.pv_complete || !r.battery_complete;
      tooltip.innerHTML = `<b>${this.dateTime(r.start)}</b><br>Nettokosten: ${this.money(r.net_cost)}<br>PV-waarde: ${this.money(r.pv_value)}<br>Batterijwinst: ${this.money(r.battery_profit)}<br>Afnameprijs: ${this.price(r.import_price)}<br>Terugleverprijs: ${this.price(r.export_price)}${partial ? "<br><span>⚠ Bekend subtotaal / onvolledig</span>" : ""}`;
      tooltip.hidden = false;
      let tx = ev.clientX - rect.left + 12;
      if (tx > rect.width - 215) tx = Math.max(4, tx - 230);
      tooltip.style.left = `${tx}px`;
      tooltip.style.top = "12px";
    };

    svg.addEventListener("pointermove", showTooltip);
    svg.addEventListener("pointerleave", () => { if (tooltip) tooltip.hidden = true; if (cursor) cursor.setAttribute("visibility", "hidden"); });
    svg.addEventListener("click", ev => {
      const row = rows[indexForEvent(ev)];
      const nextView = { month: "day", day: "hour", hour: "quarter" }[this._chartView];
      if (!nextView || !row) return;
      const center = new Date((new Date(row.start).getTime() + new Date(row.end).getTime()) / 2);
      this.loadChartView(nextView, center);
    });
  }

  async loadSummary() {
    if (!this._hass || this._loading) return;
    this._loading = true;
    const hadChart = Boolean(this._chartRange);
    try {
      this._summary = await this._hass.callWS({ type: "energy_cost_tracker/summary" });
      this.updateLivePricesFromHass();
      if (!hadChart) {
        try {
          const stored = JSON.parse(localStorage.getItem("energy_cost_tracker_chart_series") || "null");
          if (stored && typeof stored === "object") this._chartSeries = { ...this._chartSeries, ...stored };
        } catch (_) {}
      }
    } catch (err) { this._error = String(err); }
    this._loading = false;
    this.render();
    if (!this._summary) return;
    if (!hadChart) await this.resetChart();
    else {
      const range = this.chartViewRange(this._chartView, this._chartAnchor);
      await this.loadChart(range.start, range.end, range.granularity);
    }
  }

  async loadHistory() {
    if (!this._hass) return;
    const start = this.shadowRoot.querySelector("#start")?.value || "";
    const endDate = this.shadowRoot.querySelector("#end")?.value || "";
    const quality = this.shadowRoot.querySelector("#quality")?.value || "";
    const activity = this.shadowRoot.querySelector("#activity")?.value || "";
    this._filters = { start, end: endDate, quality, activity };
    let end;
    if (endDate) {
      const d = new Date(`${endDate}T23:59:59`);
      end = d.toISOString();
    }
    const startIso = start ? new Date(`${start}T00:00:00`).toISOString() : undefined;
    this._history = await this._hass.callWS({
      type: "energy_cost_tracker/ledger",
      start: startIso,
      end,
      quality: quality || undefined,
      activity: activity || undefined,
      limit: 500,
      offset: 0
    });
    this.render();
  }

  card(title, value, sub = "") {
    return `<div class="card"><div class="label">${title}</div><div class="value">${value}</div>${sub ? `<div class="sub">${sub}</div>` : ""}</div>`;
  }

  period(name) { return this._summary?.periods?.[name] || {}; }

  renderOverview() {
    const t = this.period("today"), m = this.period("month"), bm = this.period("billing_month");
    const inv = this._summary?.battery_inventory || {};
    const todayIssue = this.incompleteText(t, "incomplete_cost_intervals");
    const monthIssue = this.incompleteText(m, "incomplete_cost_intervals");
    const billingIssue = this.incompleteText(bm, "incomplete_cost_intervals");
    const pvIssue = this.incompleteText(t, "incomplete_pv_intervals");
    return `
      ${this.renderFinanceChart()}
      <div class="grid overviewGrid">
        ${this.card("Kosten vandaag", this.periodMoney(t, "net_cost", "known_net_cost", "incomplete_cost_intervals"), `${this.num(t.grid_import_kwh)} kWh afname · ${this.num(t.grid_export_kwh)} kWh terug${todayIssue ? ` · ${todayIssue}` : ""}`)}
        ${this.card("Deze maand", this.periodMoney(m, "net_cost", "known_net_cost", "incomplete_cost_intervals"), monthIssue || `${m.non_exact_intervals || 0} niet-exacte intervallen`)}
        ${this.card("Huidige factuurmaand", this.periodMoney(bm, "net_cost", "known_net_cost", "incomplete_cost_intervals"), `${this.date(bm.period_start)} – ${this.date(bm.period_end)}${billingIssue ? ` · ${billingIssue}` : ""}`)}
        ${this.card("PV-waarde vandaag", this.periodMoney(t, "pv_value", "known_pv_value", "incomplete_pv_intervals"), `${this.num(t.pv_production_kwh)} kWh productie${pvIssue ? ` · ${pvIssue}` : ""}`)}
        ${this.card("Batterijwinst vandaag", this.periodMoney(t, "battery_profit", "known_battery_profit", "incomplete_battery_intervals"), `${this.num(t.battery_charge_kwh)} kWh geladen · ${this.num(t.battery_discharge_kwh)} kWh ontladen`)}
        ${this.card("Batterij cost basis", this.money(inv.cost_basis), inv.average_price == null ? "Nog niet bekend" : `${this.money(inv.average_price)}/kWh · ${inv.basis_known ? "basis bekend" : "basis nog onvolledig"}`)}
      </div>
      <div class="section"><h2>Live</h2><div class="live">
        <span>Net: <b>${this.num(this._summary?.live?.grid_power, 0)} W</b></span>
        <span>PV: <b>${this.num(this._summary?.live?.pv_power, 0)} W</b></span>
        <span>Batterij: <b>${this.num(this._summary?.live?.battery_power, 0)} W</b></span>
        <span>SOC: <b>${this.num(this._summary?.live?.battery_soc, 0)}%</b></span>
      </div></div>`;
  }

  renderCosts() {
    const rows = ["hour","today","week","month","year","billing_month","billing_year","total"];
    const labels = {hour:"Dit uur",today:"Vandaag",week:"Deze week",month:"Deze maand",year:"Dit jaar",billing_month:"Factuurmaand",billing_year:"Factuurjaar",total:"Alles"};
    return `<div class="section"><h2>Kosten</h2><div class="tableWrap"><table><thead><tr><th>Periode</th><th>Afname</th><th>Terugleveropbrengst</th><th>Vast</th><th>Netto</th><th>Kwaliteit</th></tr></thead><tbody>${rows.map(k => { const p=this.period(k); const missing=Number(p.incomplete_cost_intervals || 0); return `<tr><td>${labels[k]}</td><td>${this.periodMoney(p,"import_cost","known_import_cost","incomplete_import_intervals")}</td><td>${this.periodMoney(p,"export_revenue","known_export_revenue","incomplete_export_intervals")}</td><td>${this.money(p.fixed_cost)}</td><td><b>${this.periodMoney(p,"net_cost","known_net_cost","incomplete_cost_intervals")}</b></td><td>${missing ? `${missing} zonder prijs` : `${p.non_exact_intervals || 0} niet exact`}</td></tr>`; }).join("")}</tbody></table></div><p class="hint">* Bekend subtotaal. Voor één of meer intervallen ontbreekt prijsinformatie; het definitieve totaal kan daardoor nog afwijken.</p></div>`;
  }

  renderSolar() {
    const t=this.period("today"), m=this.period("month"), y=this.period("year");
    const solarCard=(title,p)=>this.card(title,this.periodMoney(p,"pv_value","known_pv_value","incomplete_pv_intervals"),`${this.num(p.pv_production_kwh)} kWh${p.incomplete_pv_intervals ? ` · ${this.incompleteText(p,"incomplete_pv_intervals")}` : ""}`);
    return `<div class="grid">${solarCard("PV-waarde vandaag",t)}${solarCard("PV-waarde maand",m)}${solarCard("PV-waarde jaar",y)}</div><p class="hint">PV-waarde is de vermeden importprijs bij direct verbruik, de terugleververgoeding bij export en de gemiste terugleververgoeding als cost basis bij laden van de batterij. * = bekend subtotaal; één of meer intervallen missen prijsinformatie.</p>`;
  }

  renderBattery() {
    const t=this.period("today"), m=this.period("month"), inv=this._summary?.battery_inventory || {};
    return `<div class="grid">${this.card("Winst vandaag",this.periodMoney(t,"battery_profit","known_battery_profit","incomplete_battery_intervals"))}${this.card("Winst maand",this.periodMoney(m,"battery_profit","known_battery_profit","incomplete_battery_intervals"))}${this.card("Laadkosten vandaag",this.money(t.battery_charge_cost))}${this.card("Waarde ontladen vandaag",this.money(t.battery_discharge_value))}${this.card("Opgeslagen cost basis",this.money(inv.cost_basis),`${this.num(inv.energy_kwh)} kWh virtuele voorraad`)}${this.card("Gemiddelde opgeslagen prijs",inv.average_price == null?"—":`${this.money(inv.average_price)}/kWh`,inv.basis_known?"Cost basis bekend":"Nog niet volledig bekend")}</div>`;
  }

  renderHistory() {
    const rows=this._history?.rows || [];
    const f=this._filters || {};
    const selected=(value,current)=>value===current?" selected":"";
    return `<div class="section"><h2>Historie zoeken</h2><div class="filters"><label>Vanaf<input id="start" type="date" value="${f.start || ""}"></label><label>Tot en met<input id="end" type="date" value="${f.end || ""}"></label><label>Activiteit<select id="activity"><option value="">Alle activiteiten</option><option value="grid_import"${selected("grid_import",f.activity)}>Netafname</option><option value="grid_export"${selected("grid_export",f.activity)}>Teruglevering</option><option value="pv"${selected("pv",f.activity)}>PV-productie</option><option value="battery_charge"${selected("battery_charge",f.activity)}>Batterij laden</option><option value="battery_discharge"${selected("battery_discharge",f.activity)}>Batterij ontladen</option><option value="issues"${selected("issues",f.activity)}>Alleen afwijkingen</option></select></label><label>Kwaliteit<select id="quality"><option value="">Alle</option><option${selected("exact",f.quality)}>exact</option><option${selected("reconstructed",f.quality)}>reconstructed</option><option${selected("estimated",f.quality)}>estimated</option><option${selected("missing_price",f.quality)}>missing_price</option><option${selected("unknown_battery_basis",f.quality)}>unknown_battery_basis</option></select></label><button id="search">Zoeken</button></div>${this._history?`<div class="sub">${this._history.total} intervallen gevonden</div>`:""}<div class="tableWrap"><table><thead><tr><th>Tijd</th><th>Afname kWh</th><th>Terug kWh</th><th>PV kWh</th><th>Batt. +</th><th>Batt. -</th><th>Kosten</th><th>PV-waarde</th><th>Batt. winst</th><th>Kwaliteit</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${this.dateTime(r.end_ts)}</td><td>${this.num(r.grid_import_kwh,3)}</td><td>${this.num(r.grid_export_kwh,3)}</td><td>${this.num(r.pv_production_kwh,3)}</td><td>${this.num(r.battery_charge_kwh,3)}</td><td>${this.num(r.battery_discharge_kwh,3)}</td><td>${this.money(r.net_cost)}</td><td>${this.money(r.pv_value)}</td><td>${this.money(r.battery_profit)}</td><td><span class="quality ${r.quality}">${r.quality}</span></td></tr>`).join("")}</tbody></table></div></div>`;
  }

  date(value) { if(!value) return "—"; return new Date(value).toLocaleDateString(); }
  dateTime(value) { if(!value) return "—"; return new Date(value).toLocaleString(); }

  render() {
    if (!this.shadowRoot) return;
    const content = !this._summary ? `<div class="loading">${this._error || "Laden…"}</div>` : ({overview:()=>this.renderOverview(),costs:()=>this.renderCosts(),solar:()=>this.renderSolar(),battery:()=>this.renderBattery(),history:()=>this.renderHistory()}[this._tab]());
    this.shadowRoot.innerHTML = `<style>
      :host{display:block;box-sizing:border-box;background:var(--primary-background-color);color:var(--primary-text-color);min-height:100vh;font-family:var(--paper-font-body1_-_font-family,system-ui)}*{box-sizing:border-box}.page{max-width:1500px;margin:auto;padding:20px}.head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:16px}.head h1{font-size:26px;margin:0}.refresh{border:0;background:var(--primary-color);color:var(--text-primary-color,#fff);padding:10px 14px;border-radius:10px;cursor:pointer}.tabs{display:flex;gap:6px;overflow:auto;margin-bottom:18px}.tab{border:0;border-radius:999px;padding:9px 14px;background:var(--card-background-color);color:var(--primary-text-color);cursor:pointer;white-space:nowrap}.tab.active{background:var(--primary-color);color:#fff}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}.card,.section{background:var(--card-background-color);border-radius:14px;padding:16px;box-shadow:var(--ha-card-box-shadow,0 2px 6px rgba(0,0,0,.12))}.label{font-size:13px;color:var(--secondary-text-color)}.value{font-size:28px;font-weight:700;margin:6px 0}.sub,.hint{font-size:12px;color:var(--secondary-text-color)}.section{margin-top:14px}.section h2{margin:0 0 14px}.live{display:flex;flex-wrap:wrap;gap:18px}.tableWrap{overflow:auto}table{width:100%;border-collapse:collapse;font-size:13px}th,td{text-align:left;padding:10px;border-bottom:1px solid var(--divider-color);white-space:nowrap}th{color:var(--secondary-text-color);font-weight:600}.filters{display:flex;gap:10px;flex-wrap:wrap;align-items:end;margin-bottom:12px}.filters label{display:grid;gap:4px;font-size:12px;color:var(--secondary-text-color)}input,select,button{font:inherit;padding:9px;border-radius:8px;border:1px solid var(--divider-color);background:var(--card-background-color);color:var(--primary-text-color)}.filters button{background:var(--primary-color);color:#fff;border:0}.quality{padding:3px 7px;border-radius:8px;background:var(--secondary-background-color)}.quality.exact{font-weight:600}.loading{padding:40px;text-align:center}.overviewGrid{margin-top:14px}.chartSection{padding:16px 16px 12px}.chartHead{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;flex-wrap:wrap}.chartHead h2{margin:0 0 3px}.chartControls{display:flex;gap:6px;flex-wrap:wrap}.chartControls button{min-width:38px;border:0;background:var(--secondary-background-color);cursor:pointer}.chartControls button:disabled{opacity:.35;cursor:default}.chartControls #chartNow{padding-inline:12px}.chartToolbar{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-top:12px}.chartViewSelector{display:flex;padding:3px;background:var(--secondary-background-color);border-radius:10px;overflow:auto}.chartViewSelector button{border:0;background:transparent;padding:7px 11px;white-space:nowrap;cursor:pointer}.chartViewSelector button.active{background:var(--primary-color);color:#fff}.priceNow{display:flex;gap:8px;flex-wrap:wrap;font-size:12px;color:var(--secondary-text-color)}.priceNow span{padding:6px 9px;border-radius:9px;background:var(--secondary-background-color)}.priceNow b{color:var(--primary-text-color)}.chartSeriesSelector{display:flex;gap:7px;overflow:auto;padding:10px 0 3px;scrollbar-width:thin}.seriesToggle{display:flex;align-items:center;gap:6px;border:1px solid var(--divider-color);background:var(--card-background-color);padding:6px 9px;white-space:nowrap;cursor:pointer;font-size:12px}.seriesToggle.off{opacity:.42}.seriesToggle i{display:inline-block;width:12px;height:12px;border-radius:3px}.seriesToggle.cost i{background:var(--error-color,#db4437)}.seriesToggle.pv i{background:var(--warning-color,#f9a825)}.seriesToggle.battery i{background:var(--success-color,#43a047)}.seriesToggle.importPrice i{height:3px;border-radius:3px;background:var(--primary-color)}.seriesToggle.exportPrice i{height:3px;border-radius:3px;background:var(--accent-color,#7e57c2)}.chartBox{position:relative;width:100%;height:360px;margin-top:4px;overflow-x:auto;overflow-y:hidden}.chartBox svg{width:100%;height:100%;display:block;touch-action:pan-y;cursor:crosshair}.chartGrid{stroke:var(--divider-color);stroke-width:1;vector-effect:non-scaling-stroke}.chartZero{stroke:var(--secondary-text-color);stroke-width:1.2;opacity:.7;vector-effect:non-scaling-stroke}.chartBar{vector-effect:non-scaling-stroke;opacity:.82}.costBar{fill:var(--error-color,#db4437)}.pvBar{fill:var(--warning-color,#f9a825)}.batteryBar{fill:var(--success-color,#43a047)}.priceLine{fill:none;stroke-width:2.2;vector-effect:non-scaling-stroke;stroke-linejoin:round;stroke-linecap:round}.importPriceLine{stroke:var(--primary-color)}.exportPriceLine{stroke:var(--accent-color,#7e57c2);stroke-dasharray:6 4}.chartYLabel,.chartXLabel,.chartPriceYLabel{fill:var(--secondary-text-color);font-size:12px}.chartCursor{stroke:var(--primary-text-color);stroke-width:1;opacity:.35;vector-effect:non-scaling-stroke}.chartTooltip{position:absolute;z-index:2;min-width:190px;padding:9px 10px;border-radius:9px;background:var(--card-background-color);box-shadow:0 3px 14px rgba(0,0,0,.35);font-size:12px;pointer-events:none;line-height:1.5;border:1px solid var(--divider-color)}.chartTooltip span{color:var(--warning-color,#f9a825)}.chartEmpty{height:220px;display:grid;place-items:center;color:var(--secondary-text-color)}.chartHint{margin:4px 0 0}@media(max-width:600px){.page{padding:12px}.head h1{font-size:22px}.value{font-size:23px}.chartBox{height:310px}.chartSection{padding:14px 10px 10px}.chartHead{gap:8px}.chartControls{width:100%}.chartControls button{flex:1}.chartToolbar{align-items:stretch}.chartViewSelector{width:100%}.chartViewSelector button{flex:1}.priceNow{width:100%}.priceNow span{flex:1;min-width:145px}.chartYLabel,.chartXLabel,.chartPriceYLabel{font-size:13px}.chartSeriesSelector{margin-inline:-2px}}
    </style><div class="page"><div class="head"><h1>Energy Cost Tracker</h1><button class="refresh" id="refresh">Vernieuwen</button></div><div class="tabs">${[["overview","Overzicht"],["costs","Kosten"],["solar","Zonnepanelen"],["battery","Batterij"],["history","Historie"]].map(([k,l])=>`<button class="tab ${this._tab===k?"active":""}" data-tab="${k}">${l}</button>`).join("")}</div>${content}</div>`;
    this.shadowRoot.querySelectorAll("[data-tab]").forEach(el=>el.addEventListener("click",()=>{this._tab=el.dataset.tab;this.render();if(this._tab==="history"&&!this._history)this.loadHistory();}));
    this.shadowRoot.querySelector("#refresh")?.addEventListener("click",()=>this.loadSummary());
    this.shadowRoot.querySelector("#search")?.addEventListener("click",()=>this.loadHistory());
    this.bindChartInteractions();
  }
}
if (!customElements.get("energy-cost-tracker-panel")) {
  customElements.define("energy-cost-tracker-panel", EnergyCostTrackerPanel);
}
