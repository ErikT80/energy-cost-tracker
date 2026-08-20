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

  async loadSummary() {
    if (!this._hass || this._loading) return;
    this._loading = true;
    try {
      this._summary = await this._hass.callWS({ type: "energy_cost_tracker/summary" });
    } catch (err) { this._error = String(err); }
    this._loading = false;
    this.render();
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
    return `
      <div class="grid">
        ${this.card("Kosten vandaag", this.money(t.net_cost), `${this.num(t.grid_import_kwh)} kWh afname · ${this.num(t.grid_export_kwh)} kWh terug`)}
        ${this.card("Deze maand", this.money(m.net_cost), `${m.non_exact_intervals || 0} niet-exacte intervallen`)}
        ${this.card("Huidige factuurmaand", this.money(bm.net_cost), `${this.date(bm.period_start)} – ${this.date(bm.period_end)}`)}
        ${this.card("PV-waarde vandaag", this.money(t.pv_value), `${this.num(t.pv_production_kwh)} kWh productie`)}
        ${this.card("Batterijwinst vandaag", this.money(t.battery_profit), `${this.num(t.battery_charge_kwh)} kWh geladen · ${this.num(t.battery_discharge_kwh)} kWh ontladen`)}
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
    return `<div class="section"><h2>Kosten</h2><div class="tableWrap"><table><thead><tr><th>Periode</th><th>Afname</th><th>Terugleveropbrengst</th><th>Vast</th><th>Netto</th><th>Kwaliteit</th></tr></thead><tbody>${rows.map(k => { const p=this.period(k); return `<tr><td>${labels[k]}</td><td>${this.money(p.import_cost)}</td><td>${this.money(p.export_revenue)}</td><td>${this.money(p.fixed_cost)}</td><td><b>${this.money(p.net_cost)}</b></td><td>${p.non_exact_intervals || 0} niet exact</td></tr>`; }).join("")}</tbody></table></div></div>`;
  }

  renderSolar() {
    const t=this.period("today"), m=this.period("month"), y=this.period("year");
    return `<div class="grid">${this.card("PV-waarde vandaag",this.money(t.pv_value),`${this.num(t.pv_production_kwh)} kWh`)}${this.card("PV-waarde maand",this.money(m.pv_value),`${this.num(m.pv_production_kwh)} kWh`)}${this.card("PV-waarde jaar",this.money(y.pv_value),`${this.num(y.pv_production_kwh)} kWh`)}</div><p class="hint">PV-waarde is de vermeden importprijs bij direct verbruik, de terugleververgoeding bij export en de gemiste terugleververgoeding als cost basis bij laden van de batterij.</p>`;
  }

  renderBattery() {
    const t=this.period("today"), m=this.period("month"), inv=this._summary?.battery_inventory || {};
    return `<div class="grid">${this.card("Winst vandaag",this.money(t.battery_profit))}${this.card("Winst maand",this.money(m.battery_profit))}${this.card("Laadkosten vandaag",this.money(t.battery_charge_cost))}${this.card("Waarde ontladen vandaag",this.money(t.battery_discharge_value))}${this.card("Opgeslagen cost basis",this.money(inv.cost_basis),`${this.num(inv.energy_kwh)} kWh virtuele voorraad`)}${this.card("Gemiddelde opgeslagen prijs",inv.average_price == null?"—":`${this.money(inv.average_price)}/kWh`,inv.basis_known?"Cost basis bekend":"Nog niet volledig bekend")}</div>`;
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
      :host{display:block;box-sizing:border-box;background:var(--primary-background-color);color:var(--primary-text-color);min-height:100vh;font-family:var(--paper-font-body1_-_font-family,system-ui)}*{box-sizing:border-box}.page{max-width:1500px;margin:auto;padding:20px}.head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:16px}.head h1{font-size:26px;margin:0}.refresh{border:0;background:var(--primary-color);color:var(--text-primary-color,#fff);padding:10px 14px;border-radius:10px;cursor:pointer}.tabs{display:flex;gap:6px;overflow:auto;margin-bottom:18px}.tab{border:0;border-radius:999px;padding:9px 14px;background:var(--card-background-color);color:var(--primary-text-color);cursor:pointer;white-space:nowrap}.tab.active{background:var(--primary-color);color:#fff}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}.card,.section{background:var(--card-background-color);border-radius:14px;padding:16px;box-shadow:var(--ha-card-box-shadow,0 2px 6px rgba(0,0,0,.12))}.label{font-size:13px;color:var(--secondary-text-color)}.value{font-size:28px;font-weight:700;margin:6px 0}.sub,.hint{font-size:12px;color:var(--secondary-text-color)}.section{margin-top:14px}.section h2{margin:0 0 14px}.live{display:flex;flex-wrap:wrap;gap:18px}.tableWrap{overflow:auto}table{width:100%;border-collapse:collapse;font-size:13px}th,td{text-align:left;padding:10px;border-bottom:1px solid var(--divider-color);white-space:nowrap}th{color:var(--secondary-text-color);font-weight:600}.filters{display:flex;gap:10px;flex-wrap:wrap;align-items:end;margin-bottom:12px}.filters label{display:grid;gap:4px;font-size:12px;color:var(--secondary-text-color)}input,select,button{font:inherit;padding:9px;border-radius:8px;border:1px solid var(--divider-color);background:var(--card-background-color);color:var(--primary-text-color)}.filters button{background:var(--primary-color);color:#fff;border:0}.quality{padding:3px 7px;border-radius:8px;background:var(--secondary-background-color)}.quality.exact{font-weight:600}.loading{padding:40px;text-align:center}@media(max-width:600px){.page{padding:12px}.head h1{font-size:22px}.value{font-size:23px}}
    </style><div class="page"><div class="head"><h1>Energy Cost Tracker</h1><button class="refresh" id="refresh">Vernieuwen</button></div><div class="tabs">${[["overview","Overzicht"],["costs","Kosten"],["solar","Zonnepanelen"],["battery","Batterij"],["history","Historie"]].map(([k,l])=>`<button class="tab ${this._tab===k?"active":""}" data-tab="${k}">${l}</button>`).join("")}</div>${content}</div>`;
    this.shadowRoot.querySelectorAll("[data-tab]").forEach(el=>el.addEventListener("click",()=>{this._tab=el.dataset.tab;this.render();if(this._tab==="history"&&!this._history)this.loadHistory();}));
    this.shadowRoot.querySelector("#refresh")?.addEventListener("click",()=>this.loadSummary());
    this.shadowRoot.querySelector("#search")?.addEventListener("click",()=>this.loadHistory());
  }
}
if (!customElements.get("energy-cost-tracker-panel")) {
  customElements.define("energy-cost-tracker-panel", EnergyCostTrackerPanel);
}
