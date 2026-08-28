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
    this._chartTimer = null;
    this._chartPointer = null;
  }

  set hass(value) {
    const first = !this._hass;
    this._hass = value;
    if (first) this.loadSummary();
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

  async loadChart(start, end, granularity = "auto") {
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

  async resetChart() {
    const month = this.period("month");
    if (!month.period_start) return;
    const now = new Date();
    const periodEnd = month.period_end ? new Date(month.period_end) : now;
    const monthStart = new Date(month.period_start);
    const firstLedger = month.first_ts ? new Date(month.first_ts) : monthStart;
    const start = new Date(Math.max(monthStart.getTime(), firstLedger.getTime())).toISOString();
    const end = new Date(Math.min(now.getTime(), periodEnd.getTime())).toISOString();
    await this.loadChart(start, end, "day");
  }

  scheduleChart(startMs, endMs, granularity = "auto") {
    if (!(endMs > startMs)) return;
    clearTimeout(this._chartTimer);
    this._chartTimer = setTimeout(() => {
      this.loadChart(new Date(startMs).toISOString(), new Date(endMs).toISOString(), granularity);
    }, 160);
  }

  zoomChart(factor, centerRatio = 0.5) {
    if (!this._chartRange) return;
    const start = new Date(this._chartRange.start).getTime();
    const end = new Date(this._chartRange.end).getTime();
    const span = end - start;
    const minSpan = 30 * 60 * 1000;
    const maxSpan = 5 * 365 * 86400 * 1000;
    const newSpan = Math.max(minSpan, Math.min(maxSpan, span * factor));
    const center = start + span * Math.max(0, Math.min(1, centerRatio));
    let newStart = center - newSpan * centerRatio;
    let newEnd = newStart + newSpan;
    const now = Date.now();
    if (newEnd > now) { newStart -= newEnd - now; newEnd = now; }
    this.scheduleChart(newStart, newEnd);
  }

  panChart(direction) {
    if (!this._chartRange) return;
    const start = new Date(this._chartRange.start).getTime();
    const end = new Date(this._chartRange.end).getTime();
    const span = end - start;
    let newStart = start + direction * span * 0.6;
    let newEnd = end + direction * span * 0.6;
    if (newEnd > Date.now()) { const d = newEnd - Date.now(); newStart -= d; newEnd -= d; }
    this.loadChart(new Date(newStart).toISOString(), new Date(newEnd).toISOString(), "auto");
  }

  chartLabel(value, granularity) {
    const d = new Date(value);
    if (granularity === "month") return d.toLocaleDateString(undefined, { month: "short", year: "numeric" });
    if (granularity === "day") return d.toLocaleDateString(undefined, { day: "numeric", month: "short" });
    if (granularity === "hour") return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
    return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  }

  chartGranularityLabel(value) {
    return ({ month: "maanden", day: "dagen", hour: "uren", quarter: "kwartieren" })[value] || value || "";
  }

  renderFinanceChart() {
    const chart = this._chart;
    const rows = chart?.rows || [];
    const granularity = chart?.granularity || "day";
    const rangeText = this._chartRange
      ? `${this.date(this._chartRange.start)} – ${this.date(this._chartRange.end)}`
      : "Huidige maand";
    if (!chart || this._chartLoading) {
      return `<div class="section chartSection"><div class="chartHead"><div><h2>Financieel verloop</h2><div class="sub">${rangeText}</div></div></div><div class="chartEmpty">${this._chartError || "Grafiek laden…"}</div></div>`;
    }
    if (!rows.length) {
      return `<div class="section chartSection"><div class="chartHead"><div><h2>Financieel verloop</h2><div class="sub">${rangeText}</div></div>${this.chartControls()}</div><div class="chartEmpty">Geen ledgerdata in dit bereik.</div></div>`;
    }

    const width = 1000, height = 330, left = 66, right = 22, top = 22, bottom = 58;
    const plotW = width - left - right, plotH = height - top - bottom;
    const startMs = new Date(chart.start).getTime();
    const endMs = new Date(chart.end).getTime();
    const values = [];
    for (const r of rows) for (const k of ["net_cost", "pv_value", "battery_profit"]) {
      const n = Number(r[k]); if (Number.isFinite(n)) values.push(n);
    }
    let min = Math.min(0, ...values), max = Math.max(0, ...values);
    if (max - min < 0.01) { max += 0.01; min -= 0.01; }
    const pad = (max - min) * 0.08; max += pad; min -= pad;
    const x = r => left + ((new Date(r.start).getTime() + new Date(r.end).getTime()) / 2 - startMs) / Math.max(1, endMs - startMs) * plotW;
    const y = v => top + (max - Number(v)) / (max - min) * plotH;
    const pathFor = key => {
      let d = "", open = false;
      for (const r of rows) {
        const v = Number(r[key]);
        if (!Number.isFinite(v)) { open = false; continue; }
        d += `${open ? "L" : "M"}${x(r).toFixed(2)},${y(v).toFixed(2)} `; open = true;
      }
      return d.trim();
    };
    const yTicks = Array.from({ length: 5 }, (_, i) => min + (max - min) * i / 4);
    const xTickCount = Math.min(6, rows.length);
    const xIndexes = [...new Set(Array.from({ length: xTickCount }, (_, i) => Math.round(i * (rows.length - 1) / Math.max(1, xTickCount - 1))))];
    const partial = rows.reduce((n, r) => n + Number(!r.financial_complete || !r.pv_complete || !r.battery_complete), 0);
    return `<div class="section chartSection">
      <div class="chartHead"><div><h2>Financieel verloop</h2><div class="sub">${rangeText} · ${this.chartGranularityLabel(granularity)}${partial ? ` · ⚠ ${partial} onvolledige punten` : ""}</div></div>${this.chartControls()}</div>
      <div class="chartLegend"><span class="legendCost"><i></i>Nettokosten</span><span class="legendPv"><i></i>PV-waarde</span><span class="legendBattery"><i></i>Batterijwinst</span></div>
      <div class="chartBox">
        <svg id="financeChart" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" aria-label="Financieel verloop">
          ${yTicks.map(v => `<line class="chartGrid" x1="${left}" x2="${width-right}" y1="${y(v)}" y2="${y(v)}"></line><text class="chartYLabel" x="${left-10}" y="${y(v)+4}" text-anchor="end">${this.money(v)}</text>`).join("")}
          <line class="chartZero" x1="${left}" x2="${width-right}" y1="${y(0)}" y2="${y(0)}"></line>
          ${xIndexes.map(i => `<text class="chartXLabel" x="${x(rows[i])}" y="${height-22}" text-anchor="middle">${this.chartLabel(rows[i].start, granularity)}</text>`).join("")}
          <path class="chartLine costLine" d="${pathFor("net_cost")}"></path>
          <path class="chartLine pvLine" d="${pathFor("pv_value")}"></path>
          <path class="chartLine batteryLine" d="${pathFor("battery_profit")}"></path>
          <line id="chartCursor" class="chartCursor" x1="0" x2="0" y1="${top}" y2="${height-bottom}" visibility="hidden"></line>
        </svg>
        <div id="chartTooltip" class="chartTooltip" hidden></div>
      </div>
      <div class="hint chartHint">Tik op een dag om naar uren te gaan en op een uur om kwartieren te tonen. Op desktop kun je ook met het muiswiel of door horizontaal te slepen inzoomen. Waarden met ontbrekende prijsdata worden als bekend subtotaal weergegeven.</div>
    </div>`;
  }

  chartControls() {
    return `<div class="chartControls"><button id="chartPrev" title="Vorige periode">‹</button><button id="chartZoomOut" title="Uitzoomen">−</button><button id="chartZoomIn" title="Inzoomen">+</button><button id="chartNext" title="Volgende periode">›</button><button id="chartReset">Deze maand</button></div>`;
  }

  bindChartInteractions() {
    this.shadowRoot.querySelector("#chartZoomIn")?.addEventListener("click", () => this.zoomChart(0.5));
    this.shadowRoot.querySelector("#chartZoomOut")?.addEventListener("click", () => this.zoomChart(2));
    this.shadowRoot.querySelector("#chartPrev")?.addEventListener("click", () => this.panChart(-1));
    this.shadowRoot.querySelector("#chartNext")?.addEventListener("click", () => this.panChart(1));
    this.shadowRoot.querySelector("#chartReset")?.addEventListener("click", () => this.resetChart());

    const svg = this.shadowRoot.querySelector("#financeChart");
    if (!svg || !this._chart?.rows?.length) return;
    const rows = this._chart.rows;
    const tooltip = this.shadowRoot.querySelector("#chartTooltip");
    const cursor = this.shadowRoot.querySelector("#chartCursor");
    const left = 66, right = 22, viewW = 1000;
    const rangeStart = new Date(this._chart.start).getTime();
    const rangeEnd = new Date(this._chart.end).getTime();
    const plotW = viewW - left - right;

    const ratioForEvent = ev => {
      const rect = svg.getBoundingClientRect();
      const vx = (ev.clientX - rect.left) / Math.max(1, rect.width) * viewW;
      return Math.max(0, Math.min(1, (vx - left) / plotW));
    };
    const nearest = ratio => {
      const target = rangeStart + ratio * (rangeEnd - rangeStart);
      let best = rows[0], bestD = Infinity;
      for (const r of rows) {
        const c = (new Date(r.start).getTime() + new Date(r.end).getTime()) / 2;
        const d = Math.abs(c - target);
        if (d < bestD) { bestD = d; best = r; }
      }
      return best;
    };
    const showTooltip = ev => {
      if (!tooltip) return;
      const ratio = ratioForEvent(ev);
      const r = nearest(ratio);
      const rect = svg.getBoundingClientRect();
      const center = (new Date(r.start).getTime() + new Date(r.end).getTime()) / 2;
      const px = left + (center - rangeStart) / Math.max(1, rangeEnd - rangeStart) * plotW;
      if (cursor) { cursor.setAttribute("x1", px); cursor.setAttribute("x2", px); cursor.setAttribute("visibility", "visible"); }
      const partial = !r.financial_complete || !r.pv_complete || !r.battery_complete;
      tooltip.innerHTML = `<b>${this.dateTime(r.start)}</b><br>Nettokosten: ${this.money(r.net_cost)}<br>PV-waarde: ${this.money(r.pv_value)}<br>Batterijwinst: ${this.money(r.battery_profit)}${partial ? "<br><span>⚠ Bekend subtotaal / onvolledig</span>" : ""}`;
      tooltip.hidden = false;
      let tx = ev.clientX - rect.left + 12;
      if (tx > rect.width - 190) tx = Math.max(4, tx - 205);
      tooltip.style.left = `${tx}px`;
      tooltip.style.top = "12px";
    };

    svg.addEventListener("pointermove", ev => { showTooltip(ev); });
    svg.addEventListener("pointerleave", () => { if (tooltip) tooltip.hidden = true; if (cursor) cursor.setAttribute("visibility", "hidden"); });
    svg.addEventListener("wheel", ev => { ev.preventDefault(); this.zoomChart(ev.deltaY < 0 ? 0.62 : 1.6, ratioForEvent(ev)); }, { passive: false });
    svg.addEventListener("pointerdown", ev => { this._chartPointer = { x: ev.clientX, y: ev.clientY, ratio: ratioForEvent(ev), type: ev.pointerType }; });
    svg.addEventListener("pointerup", ev => {
      const down = this._chartPointer; this._chartPointer = null;
      if (!down) return;
      const dx = ev.clientX - down.x, dy = ev.clientY - down.y;
      if (down.type === "mouse" && Math.abs(dx) > 28 && Math.abs(dx) > Math.abs(dy)) {
        const a = Math.min(down.ratio, ratioForEvent(ev));
        const b = Math.max(down.ratio, ratioForEvent(ev));
        const start = rangeStart + a * (rangeEnd - rangeStart);
        const end = rangeStart + b * (rangeEnd - rangeStart);
        if (end - start >= 30 * 60 * 1000) this.loadChart(new Date(start).toISOString(), new Date(end).toISOString(), "auto");
        return;
      }
      if (Math.hypot(dx, dy) > 14) return;
      const row = nearest(ratioForEvent(ev));
      const next = ({ month: "day", day: "hour", hour: "quarter" })[this._chart.granularity];
      if (next) this.loadChart(row.start, row.end, next);
    });

  }

  async loadSummary() {
    if (!this._hass || this._loading) return;
    this._loading = true;
    const hadChart = Boolean(this._chartRange);
    try {
      this._summary = await this._hass.callWS({ type: "energy_cost_tracker/summary" });
    } catch (err) { this._error = String(err); }
    this._loading = false;
    this.render();
    if (!this._summary) return;
    if (!hadChart) {
      await this.resetChart();
    } else if (this._chartRange) {
      await this.loadChart(this._chartRange.start, this._chartRange.end, this._chart?.granularity || "auto");
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
      :host{display:block;box-sizing:border-box;background:var(--primary-background-color);color:var(--primary-text-color);min-height:100vh;font-family:var(--paper-font-body1_-_font-family,system-ui)}*{box-sizing:border-box}.page{max-width:1500px;margin:auto;padding:20px}.head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:16px}.head h1{font-size:26px;margin:0}.refresh{border:0;background:var(--primary-color);color:var(--text-primary-color,#fff);padding:10px 14px;border-radius:10px;cursor:pointer}.tabs{display:flex;gap:6px;overflow:auto;margin-bottom:18px}.tab{border:0;border-radius:999px;padding:9px 14px;background:var(--card-background-color);color:var(--primary-text-color);cursor:pointer;white-space:nowrap}.tab.active{background:var(--primary-color);color:#fff}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}.card,.section{background:var(--card-background-color);border-radius:14px;padding:16px;box-shadow:var(--ha-card-box-shadow,0 2px 6px rgba(0,0,0,.12))}.label{font-size:13px;color:var(--secondary-text-color)}.value{font-size:28px;font-weight:700;margin:6px 0}.sub,.hint{font-size:12px;color:var(--secondary-text-color)}.section{margin-top:14px}.section h2{margin:0 0 14px}.live{display:flex;flex-wrap:wrap;gap:18px}.tableWrap{overflow:auto}table{width:100%;border-collapse:collapse;font-size:13px}th,td{text-align:left;padding:10px;border-bottom:1px solid var(--divider-color);white-space:nowrap}th{color:var(--secondary-text-color);font-weight:600}.filters{display:flex;gap:10px;flex-wrap:wrap;align-items:end;margin-bottom:12px}.filters label{display:grid;gap:4px;font-size:12px;color:var(--secondary-text-color)}input,select,button{font:inherit;padding:9px;border-radius:8px;border:1px solid var(--divider-color);background:var(--card-background-color);color:var(--primary-text-color)}.filters button{background:var(--primary-color);color:#fff;border:0}.quality{padding:3px 7px;border-radius:8px;background:var(--secondary-background-color)}.quality.exact{font-weight:600}.loading{padding:40px;text-align:center}.overviewGrid{margin-top:14px}.chartSection{padding:16px 16px 12px}.chartHead{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;flex-wrap:wrap}.chartHead h2{margin:0 0 3px}.chartControls{display:flex;gap:6px;flex-wrap:wrap}.chartControls button{min-width:38px;border:0;background:var(--secondary-background-color);cursor:pointer}.chartControls #chartReset{padding-inline:12px}.chartLegend{display:flex;gap:16px;flex-wrap:wrap;margin:12px 0 2px;font-size:12px;color:var(--secondary-text-color)}.chartLegend span{display:flex;align-items:center;gap:6px}.chartLegend i{display:inline-block;width:16px;height:3px;border-radius:3px}.legendCost i{background:var(--error-color,#db4437)}.legendPv i{background:var(--warning-color,#f9a825)}.legendBattery i{background:var(--success-color,#43a047)}.chartBox{position:relative;width:100%;height:330px;margin-top:4px;overflow:hidden}.chartBox svg{width:100%;height:100%;display:block;touch-action:pan-y;cursor:crosshair}.chartGrid{stroke:var(--divider-color);stroke-width:1;vector-effect:non-scaling-stroke}.chartZero{stroke:var(--secondary-text-color);stroke-width:1.2;opacity:.7;vector-effect:non-scaling-stroke}.chartLine{fill:none;stroke-width:2.4;vector-effect:non-scaling-stroke;stroke-linejoin:round;stroke-linecap:round}.costLine{stroke:var(--error-color,#db4437)}.pvLine{stroke:var(--warning-color,#f9a825)}.batteryLine{stroke:var(--success-color,#43a047)}.chartYLabel,.chartXLabel{fill:var(--secondary-text-color);font-size:12px}.chartCursor{stroke:var(--primary-text-color);stroke-width:1;opacity:.35;vector-effect:non-scaling-stroke}.chartTooltip{position:absolute;z-index:2;min-width:170px;padding:9px 10px;border-radius:9px;background:var(--card-background-color);box-shadow:0 3px 14px rgba(0,0,0,.35);font-size:12px;pointer-events:none;line-height:1.5;border:1px solid var(--divider-color)}.chartTooltip span{color:var(--warning-color,#f9a825)}.chartEmpty{height:220px;display:grid;place-items:center;color:var(--secondary-text-color)}.chartHint{margin:4px 0 0}@media(max-width:600px){.page{padding:12px}.head h1{font-size:22px}.value{font-size:23px}.chartBox{height:285px}.chartSection{padding:14px 10px 10px}.chartControls{width:100%}.chartControls button{flex:1}.chartYLabel,.chartXLabel{font-size:14px}.chartLegend{gap:10px}}
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
