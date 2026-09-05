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
    this._chartNeedsInitialScroll = false;
    this._chartScrollTarget = null;
    this._touchTooltipIndex = null;
    this._touchTooltipAt = 0;
    this._suppressChartClickUntil = 0;
    this._chartSeries = {
      net_cost: true,
      pv_value: true,
      battery_profit: true,
      import_price: true,
      export_price: true,
      solar_production: true,
      solar_direct: true,
      solar_export: true,
      solar_battery: true,
      solar_value: true,
      solar_export_price: true,
      battery_charge_energy: true,
      battery_discharge_energy: true,
      battery_charge_cost_series: true,
      battery_discharge_value_series: true,
      battery_profit_series: true
    };
    this._chartTheme = "home_assistant";
    this._investmentDraft = { pv: null, battery: null };
    this._investmentSaving = false;
    this._investmentStatus = "";
    this._batteryEmptySaving = false;
    this._batteryEmptyStatus = "";
    this._fixedCostDraft = { effective_from: "", daily: null, monthly: null, annual: null, annual_rebate: null };
    this._fixedCostEditing = null;
    this._fixedCostSaving = false;
    this._fixedCostStatus = "";
    this._accessUsers = null;
    this._accessSaving = false;
    this._accessStatus = "";
    this._invoice = null;
    this._invoiceView = "month";
    this._invoiceLoading = false;
    this._invoiceError = "";
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
    const languageChanged = previous?.locale?.language !== value?.locale?.language;
    if ((priceChanged || languageChanged) && this._summary) {
      if (priceChanged) this.updateLivePricesFromHass();
      this.render();
    }
  }
  set narrow(value) { this._narrow = value; }
  set panel(value) { this._panel = value; }

  isAdmin() { return Boolean(this._hass?.user?.is_admin); }

  language() {
    return String(this._hass?.locale?.language || this._hass?.language || navigator.language || "en").toLowerCase();
  }

  locale() {
    return this.language().startsWith("nl") ? "nl-NL" : "en-GB";
  }

  tr(nl, en) {
    return this.language().startsWith("nl") ? nl : en;
  }

  qualityLabel(value) {
    const labels = {
      exact: ["Exact", "Exact"],
      reconstructed: ["Gereconstrueerd", "Reconstructed"],
      estimated: ["Geschat", "Estimated"],
      missing_price: ["Ontbrekende prijs", "Missing price"],
      unknown_battery_basis: ["Onbekende batterijbasis", "Unknown battery basis"]
    };
    const pair = labels[value];
    return pair ? this.tr(pair[0], pair[1]) : value;
  }

  money(value) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
    const currency = this._summary?.currency || "EUR";
    try { return new Intl.NumberFormat(this.locale(), { style: "currency", currency }).format(Number(value)); }
    catch (_) { return `${Number(value).toFixed(2)} ${currency}`; }
  }
  num(value, digits = 2) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
    return new Intl.NumberFormat(this.locale(), { maximumFractionDigits: digits }).format(Number(value));
  }

  percent(value, digits = 1) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
    return `${new Intl.NumberFormat(this.locale(), { minimumFractionDigits: 0, maximumFractionDigits: digits }).format(Number(value))}%`;
  }

  solarSelfConsumption(period) {
    const production = Number(period?.pv_production_kwh);
    if (!Number.isFinite(production) || production <= 0) return null;
    const direct = Number(period?.pv_direct_kwh || 0);
    const toBattery = Number(period?.pv_to_battery_kwh || 0);
    const ratio = (Math.max(0, direct) + Math.max(0, toBattery)) / production * 100;
    return Math.max(0, Math.min(100, ratio));
  }

  knownPeriodValue(period, exactKey, knownKey) {
    const exact = Number(period?.[exactKey]);
    if (period?.[exactKey] !== null && period?.[exactKey] !== undefined && Number.isFinite(exact)) return exact;
    const known = Number(period?.[knownKey]);
    return period?.[knownKey] !== null && period?.[knownKey] !== undefined && Number.isFinite(known) ? known : null;
  }

  investmentPercent(value, investment) {
    const earned = Number(value);
    const cost = Number(investment);
    if (!Number.isFinite(earned) || !Number.isFinite(cost) || cost <= 0) return null;
    return earned / cost * 100;
  }

  kpiStrip(items) {
    const visible = (items || []).filter(item => item && item.value !== undefined);
    if (!visible.length) return "";
    const count = Math.min(4, visible.length);
    return `<div class="section kpiStrip kpiCount${count}">${visible.map(item => `<div class="kpiItem"><span>${item.label}</span><b>${item.value}</b>${item.sub ? `<small>${item.sub}</small>` : ""}</div>`).join("")}</div>`;
  }

  chartCoveragePartial(known, total) {
    const k = Number(known);
    const t = Number(total);
    return Number.isFinite(k) && Number.isFinite(t) && t > 1e-9 && k + 1e-9 < t;
  }

  chartAverageMetrics(kind) {
    const a = this._chart?.averages || {};
    const metrics = [];
    if (kind === "overview") {
      metrics.push({
        label: this.tr("Gem. importprijs", "Avg. import price"),
        value: this.price(a.import_price),
        partial: this.chartCoveragePartial(a.priced_import_kwh, a.grid_import_kwh)
      });
      metrics.push({
        label: this.tr("Gem. exportprijs", "Avg. export price"),
        value: this.price(a.export_price),
        partial: this.chartCoveragePartial(a.priced_export_kwh, a.grid_export_kwh)
      });
    } else if (kind === "solar") {
      metrics.push({
        label: this.tr("Gem. waarde PV", "Avg. solar value"),
        value: this.price(a.pv_value_per_kwh),
        partial: this.chartCoveragePartial(a.valued_pv_kwh, a.pv_production_kwh)
      });
      metrics.push({
        label: this.tr("Gem. verkoopprijs PV", "Avg. solar export price"),
        value: this.price(a.pv_export_price),
        partial: this.chartCoveragePartial(a.priced_pv_export_kwh, a.pv_export_kwh)
      });
    } else {
      metrics.push({
        label: this.tr("Gem. laadkostprijs", "Avg. charge cost"),
        value: this.price(a.battery_charge_cost_per_kwh),
        partial: this.chartCoveragePartial(a.costed_battery_charge_kwh, a.battery_charge_kwh)
      });
      metrics.push({
        label: this.tr("Gem. ontlaadwaarde", "Avg. discharge value"),
        value: this.price(a.battery_discharge_value_per_kwh),
        partial: this.chartCoveragePartial(a.valued_battery_discharge_kwh, a.battery_discharge_kwh)
      });
    }
    const anyPartial = metrics.some(item => item.partial);
    return `<div class="chartPeriodMetrics">${metrics.map(item => `<div><span>${item.label}</span><b>${item.value}${item.partial ? " *" : ""}</b></div>`).join("")}${anyPartial ? `<small>* ${this.tr("alleen energie met bekende prijs", "priced energy only")}</small>` : ""}</div>`;
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

  periodMoneyScaled(period, exactKey, knownKey, incompleteKey, multiplier = 1) {
    const exact = period?.[exactKey];
    if (exact !== null && exact !== undefined && !Number.isNaN(Number(exact))) {
      return this.money(Number(exact) * multiplier);
    }
    const known = period?.[knownKey];
    if (known === null || known === undefined || Number.isNaN(Number(known))) return "—";
    return `${this.money(Number(known) * multiplier)}${Number(period?.[incompleteKey] || 0) > 0 ? " *" : ""}`;
  }

  invoiceRangeLabel(start, end) {
    if (!start || !end) return "—";
    const a = new Date(start);
    const b = new Date(new Date(end).getTime() - 1);
    const options = { day: "numeric", month: "short", year: "numeric" };
    const timeZone = this._hass?.config?.time_zone;
    if (timeZone) options.timeZone = timeZone;
    return `${a.toLocaleDateString(this.locale(), options)} – ${b.toLocaleDateString(this.locale(), options)}`;
  }

  async loadInvoice(view = this._invoiceView, anchor = null) {
    if (!this._hass || this._invoiceLoading) return;
    this._invoiceView = view;
    this._invoiceLoading = true;
    this._invoiceError = "";
    this.render();
    try {
      const msg = { type: "energy_cost_tracker/invoice", view };
      if (anchor) msg.anchor = anchor;
      this._invoice = await this._hass.callWS(msg);
    } catch (err) {
      this._invoiceError = String(err);
    }
    this._invoiceLoading = false;
    this.render();
  }

  shiftInvoice(direction) {
    if (!this._invoice) return;
    const anchor = direction < 0 ? this._invoice.prev_anchor : this._invoice.next_anchor;
    this.loadInvoice(this._invoiceView, anchor);
  }

  invoiceViewSelector() {
    return `<div class="invoiceViewSelector"><button data-invoice-view="month" class="${this._invoiceView === "month" ? "active" : ""}">${this.tr("Factuurmaand", "Billing month")}</button><button data-invoice-view="year" class="${this._invoiceView === "year" ? "active" : ""}">${this.tr("Factuurjaar", "Billing year")}</button></div>`;
  }

  incompleteText(period, key) {
    const count = Number(period?.[key] || 0);
    return count > 0 ? this.tr(`⚠ ${count} interval${count === 1 ? "" : "len"} zonder volledige prijsdata`, `⚠ ${count} interval${count === 1 ? "" : "s"} without complete price data`) : "";
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
      // Auto-focus is scheduled by loadChartView/tab changes. Plain data refreshes
      // deliberately preserve the user's current horizontal scroll position.
      this._chartNeedsInitialScroll = false;
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

  chartDefaultFocusTarget(view = this._chartView, anchor = this._chartAnchor || new Date()) {
    const range = this.chartViewRange(view, anchor);
    const start = new Date(range.start).getTime();
    const end = new Date(range.end).getTime();
    const now = Date.now();
    const anchorMs = new Date(anchor).getTime();
    const candidate = now >= start && now < end ? now : anchorMs;
    return Math.max(start, Math.min(end - 1, Number.isFinite(candidate) ? candidate : start));
  }

  scheduleChartAutoFocus() {
    this._chartScrollTarget = this.chartDefaultFocusTarget(this._chartView, this._chartAnchor);
  }

  // NOAA-style sunrise/sunset approximation. The result is used only to crop
  // Solar day charts; financial accounting remains based on the full ledger day.
  solarEventUtcHours(date, sunrise) {
    const lat = Number(this._hass?.config?.latitude);
    const lon = Number(this._hass?.config?.longitude);
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;
    const year = date.getFullYear(), month = date.getMonth(), day = date.getDate();
    const start = Date.UTC(year, 0, 0);
    const current = Date.UTC(year, month, day);
    const n = Math.floor((current - start) / 86400000);
    const lngHour = lon / 15;
    const t = n + ((sunrise ? 6 : 18) - lngHour) / 24;
    const m = 0.9856 * t - 3.289;
    let l = m + 1.916 * Math.sin(m * Math.PI / 180) + 0.020 * Math.sin(2 * m * Math.PI / 180) + 282.634;
    l = (l + 360) % 360;
    let ra = Math.atan(0.91764 * Math.tan(l * Math.PI / 180)) * 180 / Math.PI;
    ra = (ra + 360) % 360;
    const lQuadrant = Math.floor(l / 90) * 90;
    const raQuadrant = Math.floor(ra / 90) * 90;
    ra = (ra + lQuadrant - raQuadrant) / 15;
    const sinDec = 0.39782 * Math.sin(l * Math.PI / 180);
    const cosDec = Math.cos(Math.asin(sinDec));
    const zenith = 90.833;
    const cosH = (Math.cos(zenith * Math.PI / 180) - sinDec * Math.sin(lat * Math.PI / 180)) /
      (cosDec * Math.cos(lat * Math.PI / 180));
    if (cosH > 1 || cosH < -1) return null;
    let h = Math.acos(cosH) * 180 / Math.PI;
    if (sunrise) h = 360 - h;
    h /= 15;
    const localMean = h + ra - 0.06571 * t - 6.622;
    return ((localMean - lngHour) % 24 + 24) % 24;
  }

  solarDaylightWindow(anchor = this._chartAnchor || new Date()) {
    const date = new Date(anchor);
    const sunriseUtc = this.solarEventUtcHours(date, true);
    const sunsetUtc = this.solarEventUtcHours(date, false);
    if (sunriseUtc === null || sunsetUtc === null) return null;
    const utcMidnight = Date.UTC(date.getFullYear(), date.getMonth(), date.getDate());
    let rise = new Date(utcMidnight + sunriseUtc * 3600000);
    let set = new Date(utcMidnight + sunsetUtc * 3600000);
    // Keep the events on the selected local calendar day if UTC wrapping put an
    // event on the neighbouring local day.
    const selectedKey = `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`;
    for (const item of [[rise, "rise"], [set, "set"]]) {
      const d = item[0];
      const key = `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
      if (key !== selectedKey) {
        const candidates = [new Date(d.getTime() - 86400000), new Date(d.getTime() + 86400000)];
        const match = candidates.find(c => `${c.getFullYear()}-${c.getMonth()}-${c.getDate()}` === selectedKey);
        if (match) {
          if (item[1] === "rise") rise = match; else set = match;
        }
      }
    }
    // Include twilight margin, then round outward to clean whole-hour bounds.
    rise = new Date(rise.getTime() - 30 * 60000);
    set = new Date(set.getTime() + 30 * 60000);
    const start = new Date(rise); start.setMinutes(0, 0, 0);
    const end = new Date(set);
    if (end.getMinutes() || end.getSeconds() || end.getMilliseconds()) end.setHours(end.getHours() + 1);
    end.setMinutes(0, 0, 0);
    const dayStart = new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
    const dayEnd = new Date(date.getFullYear(), date.getMonth(), date.getDate() + 1).getTime();
    return { start: Math.max(dayStart, start.getTime()), end: Math.min(dayEnd, end.getTime()) };
  }

  async loadChartView(view = this._chartView, anchor = this._chartAnchor || new Date(), scrollTarget = undefined) {
    this._chartView = view;
    this._chartAnchor = new Date(anchor);
    this._chartScrollTarget = scrollTarget !== undefined && scrollTarget !== null
      ? new Date(scrollTarget).getTime()
      : this.chartDefaultFocusTarget(view, this._chartAnchor);
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
    if (this._chartView === "day") return d.toLocaleDateString(this.locale(), { month: "long", year: "numeric" });
    return d.toLocaleDateString(this.locale(), { weekday: "short", day: "numeric", month: "long", year: "numeric" });
  }

  chartLabel(value, granularity) {
    const d = new Date(value);
    if (granularity === "month") return d.toLocaleDateString(this.locale(), { month: "short" });
    if (granularity === "day") return d.toLocaleDateString(this.locale(), { day: "numeric" });
    if (granularity === "hour") return d.toLocaleTimeString(this.locale(), { hour: "2-digit", minute: "2-digit" });
    return d.toLocaleTimeString(this.locale(), { hour: "2-digit", minute: "2-digit" });
  }

  chartTimeTicks(chartStartMs, chartEndMs, granularity, plotW, timeX, timelineBuckets) {
    // Day-based views use fixed clock boundaries rather than evenly sampled
    // timestamps. This keeps the axis readable (00:00, 03:00, ...) and avoids
    // labels such as 00:51 or 07:42 that have no semantic meaning.
    if (granularity === "hour" || granularity === "quarter") {
      const stepHours = granularity === "quarter" ? 2 : 3;
      const start = new Date(chartStartMs);
      start.setMinutes(0, 0, 0);
      const ticks = [];
      const cursor = new Date(start);
      let guard = 0;
      while (cursor.getTime() < chartEndMs - 1000 && guard < 48) {
        if (cursor.getTime() >= chartStartMs - 1000) {
          ticks.push({
            x: timeX(cursor.getTime()),
            label: cursor.toLocaleTimeString(this.locale(), { hour: "2-digit", minute: "2-digit" })
          });
        }
        cursor.setHours(cursor.getHours() + stepHours);
        guard += 1;
      }
      // Only a true midnight-to-midnight chart gets an explicit 24:00 endpoint.
      const startDate = new Date(chartStartMs), endDate = new Date(chartEndMs);
      const fullLocalDay = startDate.getHours() === 0 && startDate.getMinutes() === 0
        && endDate.getHours() === 0 && endDate.getMinutes() === 0
        && endDate.getTime() > startDate.getTime();
      if (fullLocalDay && ticks.length) ticks.push({ x: timeX(chartEndMs), label: "24:00" });
      return ticks;
    }

    const targetXSpacing = 100;
    const xTickCount = Math.max(2, Math.min(timelineBuckets, Math.floor(plotW / targetXSpacing) + 1));
    return Array.from({ length: xTickCount }, (_, i) => {
      const ratio = (i + 0.5) / xTickCount;
      const ms = chartStartMs + ratio * (chartEndMs - chartStartMs);
      return { x: timeX(ms), label: this.chartLabel(new Date(ms).toISOString(), granularity) };
    }).filter((tick, index, all) => index === 0 || tick.label !== all[index - 1].label);
  }

  chartIntervalLabel(row, granularity) {
    const start = new Date(row.start);
    const end = new Date(row.end);
    const sameDay = start.getFullYear() === end.getFullYear()
      && start.getMonth() === end.getMonth()
      && start.getDate() === end.getDate();
    const time = d => d.toLocaleTimeString(this.locale(), { hour: "2-digit", minute: "2-digit" });
    const date = d => d.toLocaleDateString(this.locale(), { day: "2-digit", month: "2-digit", year: "numeric" });

    if (granularity === "hour" || granularity === "quarter") {
      if (sameDay) return `${date(start)} · ${time(start)}–${time(end)}`;
      return `${date(start)} ${time(start)} – ${date(end)} ${time(end)}`;
    }
    if (granularity === "day") {
      return date(start);
    }
    return `${start.toLocaleDateString(this.locale(), { month: "long", year: "numeric" })}`;
  }

  priceAxisAmount(value) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
    const currency = this._summary?.currency || "EUR";
    try {
      return new Intl.NumberFormat(this.locale(), { style: "currency", currency, minimumFractionDigits: 2, maximumFractionDigits: 3 }).format(Number(value));
    } catch (_) {
      return `${Number(value).toFixed(3)} ${currency}`;
    }
  }

  priceAmount(value) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
    const currency = this._summary?.currency || "EUR";
    try {
      return new Intl.NumberFormat(this.locale(), { style: "currency", currency, minimumFractionDigits: 3, maximumFractionDigits: 5 }).format(Number(value));
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
    const labels = {
      month: this.tr("Jaar", "Year"),
      day: this.tr("Maand", "Month"),
      hour: this.tr("Dag", "Day"),
      quarter: this.tr("Dag 15 min", "Day 15 min")
    };
    return `<div class="chartViewSelector">${Object.entries(labels).map(([key,label]) => `<button data-chart-view="${key}" class="${this._chartView === key ? "active" : ""}">${label}</button>`).join("")}</div>`;
  }

  chartControls() {
    const range = this.chartViewRange(this._chartView, this._chartAnchor);
    const disableNext = new Date(range.end).getTime() > Date.now();
    return `<div class="chartControls"><button id="chartPrev" title="${this.tr("Vorige periode", "Previous period")}">‹</button><button id="chartNow">${this.tr("Nu", "Now")}</button><button id="chartNext" title="${this.tr("Volgende periode", "Next period")}" ${disableNext ? "disabled" : ""}>›</button></div>`;
  }

  hasPv() { return Boolean(this._summary?.config?.has_pv); }
  hasPvHistory() { return Boolean(this._summary?.config?.has_pv_history); }
  showPv() { return this.hasPv() || this.hasPvHistory(); }
  hasPvPower() { return Boolean(this._summary?.config?.has_pv_power); }
  hasBattery() { return Boolean(this._summary?.config?.has_battery); }
  hasBatteryHistory() { return Boolean(this._summary?.config?.has_battery_history); }
  showBattery() { return this.hasBattery() || this.hasBatteryHistory(); }
  hasBatteryPower() { return Boolean(this._summary?.config?.has_battery_power); }
  hasBatterySoc() { return Boolean(this._summary?.config?.has_battery_soc); }


  chartSeriesSelector() {
    const items = [
      ["net_cost", this.tr("Nettokosten", "Net cost"), "cost", true],
      ["pv_value", this.tr("PV-waarde", "Solar value"), "pv", this.showPv()],
      ["battery_profit", this.tr("Batterijwinst", "Battery profit"), "battery", this.showBattery()],
      ["import_price", this.tr("Importtarief", "Import tariff"), "importPrice", true],
      ["export_price", this.tr("Exporttarief", "Export tariff"), "exportPrice", true]
    ].filter(([, , , available]) => available);
    return `<div class="chartSeriesSelector">${items.map(([key,label,cls]) => `<button data-chart-series="${key}" class="seriesToggle ${cls} ${this._chartSeries[key] ? "active" : "off"}"><i></i>${label}</button>`).join("")}</div>`;
  }

  chartThemeOptions() {
    return [
      ["home_assistant", this.tr("Home Assistant", "Home Assistant")],
      ["energy", this.tr("Hoog contrast", "High contrast")],
      ["ocean", this.tr("Oceaan", "Ocean")],
      ["sunset", this.tr("Zonsondergang", "Sunset")],
      ["forest", this.tr("Bos", "Forest")],
      ["mono", this.tr("Monochroom", "Monochrome")]
    ];
  }

  chartThemePalettes() {
    return {
      home_assistant: {
        cost: "var(--error-color,#db4437)", pv: "var(--warning-color,#f9a825)", battery: "var(--success-color,#43a047)",
        import: "var(--primary-color,#03a9f4)", export: "var(--accent-color,#7e57c2)",
        solarProduction: "#fbc02d", solarDirect: "#66bb6a", solarExport: "#fb8c00", solarBattery: "#42a5f5", solarValue: "#ab47bc",
        batteryCharge: "#42a5f5", batteryDischarge: "#66bb6a", batteryChargeCost: "#ef5350", batteryDischargeValue: "#26a69a", batteryProfit: "#ab47bc"
      },
      energy: {
        cost: "#ff1744", pv: "#ffea00", battery: "#00e676", import: "#00b0ff", export: "#d500f9",
        solarProduction: "#ffea00", solarDirect: "#76ff03", solarExport: "#ff9100", solarBattery: "#2979ff", solarValue: "#d500f9",
        batteryCharge: "#2979ff", batteryDischarge: "#00e676", batteryChargeCost: "#ff1744", batteryDischargeValue: "#00e5ff", batteryProfit: "#d500f9"
      },
      ocean: {
        cost: "#ff6b6b", pv: "#67e8f9", battery: "#2dd4bf", import: "#2563eb", export: "#7c3aed",
        solarProduction: "#22d3ee", solarDirect: "#2dd4bf", solarExport: "#2563eb", solarBattery: "#7c3aed", solarValue: "#06b6d4",
        batteryCharge: "#2563eb", batteryDischarge: "#2dd4bf", batteryChargeCost: "#ff6b6b", batteryDischargeValue: "#22d3ee", batteryProfit: "#7c3aed"
      },
      sunset: {
        cost: "#e11d48", pv: "#fbbf24", battery: "#f472b6", import: "#f97316", export: "#8b5cf6",
        solarProduction: "#fbbf24", solarDirect: "#fb7185", solarExport: "#f97316", solarBattery: "#8b5cf6", solarValue: "#db2777",
        batteryCharge: "#8b5cf6", batteryDischarge: "#f472b6", batteryChargeCost: "#e11d48", batteryDischargeValue: "#f97316", batteryProfit: "#c026d3"
      },
      forest: {
        cost: "#b45309", pv: "#bef264", battery: "#16a34a", import: "#64748b", export: "#0f766e",
        solarProduction: "#bef264", solarDirect: "#22c55e", solarExport: "#d97706", solarBattery: "#0f766e", solarValue: "#65a30d",
        batteryCharge: "#64748b", batteryDischarge: "#16a34a", batteryChargeCost: "#b45309", batteryDischargeValue: "#14b8a6", batteryProfit: "#166534"
      },
      mono: {
        cost: "#f5f5f5", pv: "#cfcfcf", battery: "#8f8f8f", import: "#ffffff", export: "#737373",
        solarProduction: "#f5f5f5", solarDirect: "#cfcfcf", solarExport: "#8f8f8f", solarBattery: "#666666", solarValue: "#b5b5b5",
        batteryCharge: "#e5e5e5", batteryDischarge: "#a3a3a3", batteryChargeCost: "#737373", batteryDischargeValue: "#d4d4d4", batteryProfit: "#525252"
      }
    };
  }

  chartThemePalette(key = this._chartTheme) {
    const palettes = this.chartThemePalettes();
    return palettes[key] || palettes.home_assistant;
  }

  chartThemeStyle() {
    const p = this.chartThemePalette();
    return Object.entries(p).map(([key,value]) => `--ect-${key.replace(/[A-Z]/g, m => `-${m.toLowerCase()}`)}:${value}`).join(";");
  }

  fixedCostProfiles() {
    const rows = this._summary?.config?.fixed_cost_profiles;
    return Array.isArray(rows) ? [...rows].sort((a,b) => String(a.effective_from).localeCompare(String(b.effective_from))) : [];
  }

  fixedCostSeed() {
    const cfg = this._summary?.config || {};
    const rows = this.fixedCostProfiles();
    const source = rows.length ? rows[rows.length - 1] : (cfg.fixed_cost_base || {});
    return {
      effective_from: rows.length ? "" : String(cfg.tracking_start_date || ""),
      daily: Number(source.daily || 0),
      monthly: Number(source.monthly || 0),
      annual: Number(source.annual || 0),
      annual_rebate: Number(source.annual_rebate || 0)
    };
  }

  ensureFixedCostDraft() {
    if (this._fixedCostDraft.daily !== null) return;
    this._fixedCostDraft = this.fixedCostSeed();
  }

  renderFixedCostSettings() {
    this.ensureFixedCostDraft();
    const cfg = this._summary?.config || {};
    const rows = this.fixedCostProfiles();
    const base = cfg.fixed_cost_base || {};
    const currency = this._summary?.currency || "EUR";
    const d = this._fixedCostDraft;
    const fmt = value => Number.isFinite(Number(value)) ? Number(value) : 0;
    const rowHtml = rows.map(row => `<tr>
      <td>${new Date(`${row.effective_from}T12:00:00`).toLocaleDateString(this.locale())}</td>
      <td>${this.money(row.daily)}</td><td>${this.money(row.monthly)}</td><td>${this.money(row.annual)}</td><td>${this.money(row.annual_rebate)}</td>
      <td class="fixedCostActions"><button data-fixed-edit="${row.effective_from}">${this.tr("Bewerken","Edit")}</button><button data-fixed-delete="${row.effective_from}">${this.tr("Verwijderen","Delete")}</button></td>
    </tr>`).join("");
    return `<div class="settingsGroup fixedCostSettings"><div class="settingsTitle">${this.tr("Vaste kosten per ingangsdatum", "Fixed costs by effective date")}</div>
      <div class="settingsStatus">${this.tr("Een regel vervangt vanaf 00:00 op de gekozen datum alle vaste kosten. Je kunt toekomstige wijzigingen vooraf invoeren; regels in het verleden corrigeren alleen de vaste en netto kosten in de bestaande historie.", "A row replaces all fixed costs from 00:00 on the selected date. Future changes can be entered in advance; past-dated rows only correct fixed and net costs in existing history.")}</div>
      <div class="fixedCostBase"><span>${this.tr("Basis vóór de eerste gedateerde regel", "Base before the first dated row")}</span><b>${this.tr("dag", "day")}: ${this.money(base.daily || 0)} · ${this.tr("maand", "month")}: ${this.money(base.monthly || 0)} · ${this.tr("jaar", "year")}: ${this.money(base.annual || 0)} · ${this.tr("korting", "rebate")}: ${this.money(base.annual_rebate || 0)}</b></div>
      ${rows.length ? `<div class="tableWrap fixedCostTable"><table><thead><tr><th>${this.tr("Vanaf","From")}</th><th>${this.tr("Per dag","Per day")}</th><th>${this.tr("Per maand","Per month")}</th><th>${this.tr("Per jaar","Per year")}</th><th>${this.tr("Jaarlijkse korting","Annual rebate")}</th><th></th></tr></thead><tbody>${rowHtml}</tbody></table></div>` : ""}
      <div class="fixedCostFields">
        <label><span>${this.tr("Ingangsdatum", "Effective date")}</span><input id="fixedEffectiveFrom" type="date" value="${d.effective_from || ""}"></label>
        <label><span>${this.tr("Vaste kosten/dag", "Fixed costs/day")} (${currency})</span><input data-fixed-field="daily" type="number" step="any" inputmode="decimal" value="${fmt(d.daily)}"></label>
        <label><span>${this.tr("Vaste kosten/maand", "Fixed costs/month")} (${currency})</span><input data-fixed-field="monthly" type="number" step="0.01" inputmode="decimal" value="${fmt(d.monthly)}"></label>
        <label><span>${this.tr("Vaste kosten/jaar", "Fixed costs/year")} (${currency})</span><input data-fixed-field="annual" type="number" step="0.01" inputmode="decimal" value="${fmt(d.annual)}"></label>
        <label><span>${this.tr("Jaarlijkse korting", "Annual rebate")} (${currency})</span><input data-fixed-field="annual_rebate" type="number" min="0" step="0.01" inputmode="decimal" value="${fmt(d.annual_rebate)}"></label>
      </div>
      <div class="settingsActions"><button id="saveFixedCost" class="primaryAction" ${this._fixedCostSaving ? "disabled" : ""}>${this._fixedCostSaving ? this.tr("Opslaan…","Saving…") : (this._fixedCostEditing ? this.tr("Wijziging opslaan","Save change") : this.tr("Tariefregel opslaan","Save rate row"))}</button>${this._fixedCostEditing ? `<button id="cancelFixedCost">${this.tr("Annuleren","Cancel")}</button>` : ""}${this._fixedCostStatus ? `<span class="settingsStatus">${this._fixedCostStatus}</span>` : ""}</div>
    </div>`;
  }

  editFixedCost(dateKey) {
    const row = this.fixedCostProfiles().find(item => String(item.effective_from) === String(dateKey));
    if (!row) return;
    this._fixedCostEditing = String(dateKey);
    this._fixedCostDraft = {
      effective_from: String(row.effective_from), daily: Number(row.daily || 0), monthly: Number(row.monthly || 0),
      annual: Number(row.annual || 0), annual_rebate: Number(row.annual_rebate || 0)
    };
    this._fixedCostStatus = "";
    this.render();
  }

  cancelFixedCostEdit() {
    this._fixedCostEditing = null;
    this._fixedCostDraft = this.fixedCostSeed();
    this._fixedCostStatus = "";
    this.render();
  }

  async persistFixedCostProfiles(profiles) {
    return await this._hass.callWS({ type: "energy_cost_tracker/fixed_costs/update", profiles });
  }

  async saveFixedCost() {
    if (!this._hass || this._fixedCostSaving) return;
    const dateValue = String(this._fixedCostDraft.effective_from || "");
    if (!/^\d{4}-\d{2}-\d{2}$/.test(dateValue)) {
      this._fixedCostStatus = this.tr("Kies eerst een geldige ingangsdatum.", "Choose a valid effective date first.");
      this.render();
      return;
    }
    const row = {
      effective_from: dateValue,
      daily: Number(this._fixedCostDraft.daily || 0), monthly: Number(this._fixedCostDraft.monthly || 0),
      annual: Number(this._fixedCostDraft.annual || 0), annual_rebate: Math.max(0, Number(this._fixedCostDraft.annual_rebate || 0))
    };
    let profiles = this.fixedCostProfiles().filter(item => String(item.effective_from) !== String(this._fixedCostEditing || dateValue));
    profiles = profiles.filter(item => String(item.effective_from) !== dateValue);
    profiles.push(row);
    profiles.sort((a,b) => String(a.effective_from).localeCompare(String(b.effective_from)));
    this._fixedCostSaving = true;
    this._fixedCostStatus = "";
    this.render();
    try {
      const result = await this.persistFixedCostProfiles(profiles);
      this._summary = await this._hass.callWS({ type: "energy_cost_tracker/summary" });
      this.updateLivePricesFromHass();
      this._fixedCostEditing = null;
      this._fixedCostDraft = this.fixedCostSeed();
      const changed = Number(result?.changed_intervals || 0);
      this._fixedCostStatus = changed > 0
        ? this.tr(`Opgeslagen · ${changed} historische intervallen bijgewerkt`, `Saved · ${changed} historical intervals updated`)
        : this.tr("Opgeslagen", "Saved");
    } catch (err) {
      this._fixedCostStatus = `${this.tr("Opslaan mislukt","Save failed")}: ${String(err)}`;
    }
    this._fixedCostSaving = false;
    this.render();
  }

  async deleteFixedCost(dateKey) {
    if (!this._hass || this._fixedCostSaving) return;
    if (!window.confirm(this.tr(`Tariefregel vanaf ${dateKey} verwijderen?`, `Delete fixed-cost row from ${dateKey}?`))) return;
    const profiles = this.fixedCostProfiles().filter(item => String(item.effective_from) !== String(dateKey));
    this._fixedCostSaving = true;
    this._fixedCostStatus = "";
    this.render();
    try {
      const result = await this.persistFixedCostProfiles(profiles);
      this._summary = await this._hass.callWS({ type: "energy_cost_tracker/summary" });
      this.updateLivePricesFromHass();
      this._fixedCostEditing = null;
      this._fixedCostDraft = this.fixedCostSeed();
      const changed = Number(result?.changed_intervals || 0);
      this._fixedCostStatus = changed > 0
        ? this.tr(`Verwijderd · ${changed} historische intervallen bijgewerkt`, `Deleted · ${changed} historical intervals updated`)
        : this.tr("Verwijderd", "Deleted");
    } catch (err) {
      this._fixedCostStatus = `${this.tr("Verwijderen mislukt","Delete failed")}: ${String(err)}`;
    }
    this._fixedCostSaving = false;
    this.render();
  }

  async loadPanelAccess() {
    if (!this._hass || !this.isAdmin()) return;
    try {
      const result = await this._hass.callWS({ type: "energy_cost_tracker/access/users" });
      this._accessUsers = Array.isArray(result?.users) ? result.users : [];
      this._accessStatus = "";
    } catch (err) {
      this._accessUsers = [];
      this._accessStatus = `${this.tr("Gebruikers laden mislukt", "Failed to load users")}: ${String(err)}`;
    }
    this.render();
  }

  renderPanelAccessSettings() {
    if (!this.isAdmin()) return "";
    if (this._accessUsers === null) {
      return `<div class="settingsGroup accessSettings"><div class="settingsTitle">${this.tr("Toegang", "Access")}</div><div class="settingsStatus">${this.tr("Gebruikers laden…", "Loading users…")}</div></div>`;
    }
    const rows = this._accessUsers.map(user => {
      const adminLabel = user.is_admin ? `<span class="accessBadge">${user.is_owner ? this.tr("Eigenaar", "Owner") : this.tr("Admin", "Admin")}</span>` : "";
      const inactive = !user.is_active ? `<span class="accessBadge muted">${this.tr("Inactief", "Inactive")}</span>` : "";
      return `<label class="accessUser ${!user.is_active ? "inactive" : ""}"><span class="accessUserMain"><input type="checkbox" data-access-user="${user.id}" ${user.allowed ? "checked" : ""} ${user.is_admin || !user.is_active ? "disabled" : ""}><span>${user.name}</span></span><span class="accessBadges">${adminLabel}${inactive}</span></label>`;
    }).join("");
    return `<div class="settingsGroup accessSettings"><div class="settingsTitle">${this.tr("Toegang tot side panel", "Side panel access")}</div>
      <div class="settingsStatus">${this.tr("Admins hebben altijd toegang. Gewone gebruikers zien Energy Cost Tracker standaard niet; vink alleen de gebruikers aan die het side panel mogen zien.", "Admins always have access. Regular users do not see Energy Cost Tracker by default; enable only the users who may see the side panel.")}</div>
      <div class="accessUsers">${rows || `<span class="settingsStatus">${this.tr("Geen gebruikers gevonden", "No users found")}</span>`}</div>
      <div class="settingsActions"><button id="savePanelAccess" class="primaryAction" ${this._accessSaving ? "disabled" : ""}>${this._accessSaving ? this.tr("Opslaan…", "Saving…") : this.tr("Toegang opslaan", "Save access")}</button>${this._accessStatus ? `<span class="settingsStatus">${this._accessStatus}</span>` : ""}</div>
    </div>`;
  }

  async savePanelAccess() {
    if (!this._hass || !this.isAdmin() || this._accessSaving) return;
    const allowedUserIds = [...this.shadowRoot.querySelectorAll("[data-access-user]")]
      .filter(el => !el.disabled && el.checked)
      .map(el => el.dataset.accessUser);
    this._accessSaving = true;
    this._accessStatus = "";
    this.render();
    try {
      const result = await this._hass.callWS({
        type: "energy_cost_tracker/access/update",
        allowed_user_ids: allowedUserIds
      });
      this._accessUsers = Array.isArray(result?.users) ? result.users : this._accessUsers;
      this._accessStatus = this.tr("Opgeslagen", "Saved");
    } catch (err) {
      this._accessStatus = `${this.tr("Opslaan mislukt", "Save failed")}: ${String(err)}`;
    }
    this._accessSaving = false;
    this.render();
  }

  renderSettings() {
    const themes = this.chartThemeOptions();
    const cfg = this._summary?.config || {};
    if (this._investmentDraft.pv === null) this._investmentDraft.pv = Number(cfg.pv_investment || 0);
    if (this._investmentDraft.battery === null) this._investmentDraft.battery = Number(cfg.battery_investment || 0);
    const currency = this._summary?.currency || "EUR";
    const investmentFields = [
      ...(this.showPv() ? [{ key: "pv", label: this.tr("Investering zonnepanelen", "Solar investment"), value: this._investmentDraft.pv }] : []),
      ...(this.showBattery() ? [{ key: "battery", label: this.tr("Investering batterij", "Battery investment"), value: this._investmentDraft.battery }] : [])
    ];
    return `<div class="section settingsSection"><h2>${this.tr("Instellingen", "Settings")}</h2>
      ${this.renderPanelAccessSettings()}
      <div class="settingsGroup themeSettings"><div class="settingsTitle">${this.tr("Grafiekthema", "Chart theme")}</div>
        <div class="themeGrid">${themes.map(([key,label]) => {
          const palette = this.chartThemePalette(key);
          const swatches = [palette.cost, palette.pv, palette.battery, palette.import, palette.export];
          return `<button class="themeOption ${this._chartTheme === key ? "active" : ""}" data-chart-theme="${key}"><span class="themeSwatches">${swatches.map(color => `<i style="background:${color}"></i>`).join("")}</span><span>${label}</span></button>`;
        }).join("")}</div>
      </div>
      ${this.renderFixedCostSettings()}
      ${investmentFields.length ? `<div class="settingsGroup investmentSettings"><div class="settingsTitle">${this.tr("Investeringen", "Investments")}</div>
        <div class="investmentFields">${investmentFields.map(item => `<label><span>${item.label} (${currency})</span><input type="number" min="0" step="0.01" inputmode="decimal" data-investment="${item.key}" value="${Number.isFinite(Number(item.value)) && Number(item.value) > 0 ? Number(item.value) : ""}" placeholder="0.00"></label>`).join("")}</div>
        <div class="settingsActions"><button id="saveInvestments" class="primaryAction" ${this._investmentSaving ? "disabled" : ""}>${this._investmentSaving ? this.tr("Opslaan…", "Saving…") : this.tr("Opslaan", "Save")}</button>${this._investmentStatus ? `<span class="settingsStatus">${this._investmentStatus}</span>` : ""}</div>
      </div>` : ""}
      ${this.renderBatteryBasisSettings()}
    </div>`;
  }

  renderBatteryBasisSettings() {
    if (!this.hasBattery()) return "";
    const inv = this._summary?.battery_inventory || {};
    if (this.hasBatterySoc()) {
      return `<div class="settingsGroup batteryBasisSettings"><div class="settingsTitle">${this.tr("Batterij cost basis", "Battery cost basis")}</div><div class="settingsStatus">${this.tr("Automatische leegdetectie via de geconfigureerde SOC-hulpsensor(en). SOC wordt niet gebruikt voor de financiële berekeningen.", "Automatic empty detection uses the configured SOC helper sensor(s). SOC is not used for financial calculations.")}</div></div>`;
    }
    if (inv.basis_known) {
      return `<div class="settingsGroup batteryBasisSettings"><div class="settingsTitle">${this.tr("Batterij cost basis", "Battery cost basis")}</div><div class="settingsStatus">${this.tr("Cost basis is bekend. Een SOC-sensor is hiervoor niet meer nodig zolang de tracking doorloopt.", "The cost basis is known. An SOC sensor is no longer needed for this as long as tracking continues.")}</div></div>`;
    }
    return `<div class="settingsGroup batteryBasisSettings"><div class="settingsTitle">${this.tr("Batterij cost basis", "Battery cost basis")}</div>
      <div class="settingsStatus">${this.tr("De beginvoorraad van de batterij is nog onbekend. Gebruik deze actie alleen wanneer alle gekoppelde batterijen daadwerkelijk leeg zijn.", "The battery's initial inventory is still unknown. Use this action only when all connected batteries are physically empty.")}</div>
      <div class="settingsActions"><button id="markBatteryEmpty" class="warningAction" ${this._batteryEmptySaving ? "disabled" : ""}>${this._batteryEmptySaving ? this.tr("Bezig…", "Working…") : this.tr("Batterij is nu leeg", "Battery is empty now")}</button>${this._batteryEmptyStatus ? `<span class="settingsStatus">${this._batteryEmptyStatus}</span>` : ""}</div>
    </div>`;
  }

  async markBatteryEmpty() {
    if (!this._hass || this._batteryEmptySaving) return;
    const confirmed = window.confirm(this.tr(
      "Bevestig alleen als alle gekoppelde batterijen nu daadwerkelijk leeg zijn. Hiermee wordt de onbekende beginvoorraad afgesloten.",
      "Confirm only if all connected batteries are physically empty now. This resolves the unknown initial inventory."
    ));
    if (!confirmed) return;
    this._batteryEmptySaving = true;
    this._batteryEmptyStatus = "";
    this.render();
    try {
      await this._hass.callWS({ type: "energy_cost_tracker/battery/mark_empty" });
      this._summary = await this._hass.callWS({ type: "energy_cost_tracker/summary" });
      this.updateLivePricesFromHass();
      this._batteryEmptyStatus = this.tr("Cost basis is nu bekend", "Cost basis is now known");
    } catch (err) {
      this._batteryEmptyStatus = `${this.tr("Actie mislukt", "Action failed")}: ${String(err)}`;
    }
    this._batteryEmptySaving = false;
    this.render();
  }

  async saveInvestmentSettings() {
    if (!this._hass || this._investmentSaving) return;
    const payload = { type: "energy_cost_tracker/settings/update" };
    if (this.showPv()) payload.pv_investment = Math.max(0, Number(this._investmentDraft.pv || 0));
    if (this.showBattery()) payload.battery_investment = Math.max(0, Number(this._investmentDraft.battery || 0));
    this._investmentSaving = true;
    this._investmentStatus = "";
    this.render();
    try {
      await this._hass.callWS(payload);
      this._summary = await this._hass.callWS({ type: "energy_cost_tracker/summary" });
      this.updateLivePricesFromHass();
      this._investmentDraft.pv = Number(this._summary?.config?.pv_investment || 0);
      this._investmentDraft.battery = Number(this._summary?.config?.battery_investment || 0);
      this._investmentStatus = this.tr("Opgeslagen", "Saved");
    } catch (err) {
      this._investmentStatus = `${this.tr("Opslaan mislukt", "Save failed")}: ${String(err)}`;
    }
    this._investmentSaving = false;
    this.render();
  }

  renderInvestmentProgress(kind) {
    const cfg = this._summary?.config || {};
    const total = this.period("total");
    const isSolar = kind === "solar";
    const investment = Number(isSolar ? cfg.pv_investment : cfg.battery_investment);
    if (!Number.isFinite(investment) || investment <= 0) return "";
    const exactKey = isSolar ? "pv_value" : "battery_profit";
    const knownKey = isSolar ? "known_pv_value" : "known_battery_profit";
    const incompleteKey = isSolar ? "incomplete_pv_intervals" : "incomplete_battery_intervals";
    const earned = this.knownPeriodValue(total, exactKey, knownKey);
    const ratio = this.investmentPercent(earned, investment);
    const incomplete = Number(total?.[incompleteKey] || 0) > 0;
    const barWidth = ratio === null ? 0 : Math.max(0, Math.min(100, ratio));
    return `<div class="section investmentProgress">
      <div class="investmentCompact"><div><span>${isSolar ? this.tr("Investering zonnepanelen", "Solar investment") : this.tr("Investering batterij", "Battery investment")}</span><b>${earned === null ? "—" : `${this.money(earned)}${incomplete ? " *" : ""}`} / ${this.money(investment)}</b></div><strong>${ratio === null ? "—" : `${this.percent(ratio)}${incomplete ? " *" : ""}`}</strong></div>
      <div class="investmentBar" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${ratio === null ? 0 : Math.round(barWidth)}"><i style="width:${barWidth.toFixed(2)}%"></i></div>
    </div>`;
  }

  assetChartSeries(kind) {
    if (kind === "solar") {
      return {
        bars: [
          { toggle: "solar_production", key: "pv_production_kwh", label: this.tr("PV-productie", "Solar production"), cls: "solarProduction" },
          { toggle: "solar_direct", key: "pv_direct_kwh", label: this.tr("Direct verbruik", "Direct use"), cls: "solarDirect" },
          { toggle: "solar_export", key: "pv_export_kwh", label: this.tr("Teruglevering", "Grid export"), cls: "solarExport" },
          ...(this.showBattery() ? [{ toggle: "solar_battery", key: "pv_to_battery_kwh", label: this.tr("Naar batterij", "To battery"), cls: "solarBattery" }] : [])
        ],
        lines: [
          { toggle: "solar_value", key: "pv_value", label: this.tr("PV-waarde", "Solar value"), cls: "solarValue" }
        ]
      };
    }
    return {
      bars: [
        { toggle: "battery_charge_energy", key: "battery_charge_kwh", label: this.tr("Laden", "Charge"), cls: "batteryCharge" },
        { toggle: "battery_discharge_energy", key: "battery_discharge_kwh", label: this.tr("Ontladen", "Discharge"), cls: "batteryDischarge" }
      ],
      lines: [
        { toggle: "battery_charge_cost_series", key: "battery_charge_cost", label: this.tr("Laadkosten", "Charge cost"), cls: "batteryChargeCost" },
        { toggle: "battery_discharge_value_series", key: "battery_discharge_value", label: this.tr("Ontlaadwaarde", "Discharge value"), cls: "batteryDischargeValue" },
        { toggle: "battery_profit_series", key: "battery_profit", label: this.tr("Batterijwinst", "Battery profit"), cls: "batteryProfitValue" }
      ]
    };
  }

  assetChartSeriesSelector(kind) {
    const cfg = this.assetChartSeries(kind);
    // These are aggregated €-per-period lines, so their toggles are valid in every view.
    const items = [...cfg.bars.map(x => ({...x, line:false})), ...cfg.lines.map(x => ({...x, line:true}))];
    return `<div class="chartSeriesSelector">${items.map(item => `<button data-chart-series="${item.toggle}" class="seriesToggle ${item.cls} ${item.line ? "lineToggle" : ""} ${this._chartSeries[item.toggle] ? "active" : "off"}"><i></i>${item.label}</button>`).join("")}</div>`;
  }

  renderFinanceChart() {
    const chart = this._chart;
    const rows = chart?.rows || [];
    const partial = rows.reduce((n, r) => n + Number(
      !r.financial_complete
      || (this.showPv() && !r.pv_complete)
      || (this.showBattery() && !r.battery_complete)
    ), 0);
    const header = `<div class="chartHead"><div><h2>${this.tr("Financieel verloop", "Financial overview")}</h2><div class="sub">${this.chartViewTitle()}${partial ? ` · ⚠ ${partial} ${this.tr("onvolledige punten", "incomplete points")}` : ""}</div></div>${this.chartControls()}</div>
      <div class="chartToolbar">${this.chartViewSelector()}${this.chartAverageMetrics("overview")}</div>
      ${this.chartSeriesSelector()}`;
    if (!chart || this._chartLoading) {
      return `<div class="section chartSection">${header}<div class="chartEmpty">${this._chartError || this.tr("Grafiek laden…", "Loading chart…")}</div></div>`;
    }
    if (!rows.length) {
      return `<div class="section chartSection">${header}<div class="chartEmpty">${this.tr("Geen ledgerdata in deze periode.", "No ledger data in this period.")}</div></div>`;
    }

    const hostWidth = Math.floor(this.getBoundingClientRect().width || window.innerWidth || 1000);
    const availableWidth = Math.max(320, Math.min(1460, hostWidth - (hostWidth <= 600 ? 36 : 64)));
    const minSlot = { month: 56, day: 30, hour: 36, quarter: 22 }[chart.granularity] || 32;
    const height = hostWidth <= 600 ? 350 : 390;
    const left = hostWidth <= 600 ? 58 : 72;
    const right = hostWidth <= 600 ? 62 : 76;
    const top = 32;
    const bottom = hostWidth <= 600 ? 54 : 62;
    const chartStartMs = new Date(chart.start).getTime();
    const chartEndMs = new Date(chart.end).getTime();
    const bucketUnitMs = { month: 30.4375 * 86400000, day: 86400000, hour: 3600000, quarter: 900000 }[chart.granularity] || 3600000;
    const timelineBuckets = Math.max(1, Math.round((chartEndMs - chartStartMs) / bucketUnitMs));
    const width = Math.max(availableWidth, left + right + timelineBuckets * minSlot);
    const plotW = width - left - right;
    const plotH = height - top - bottom;
    const financeKeys = [
      ["net_cost", true],
      ["pv_value", this.showPv()],
      ["battery_profit", this.showBattery()]
    ].filter(([key, available]) => available && this._chartSeries[key]).map(([key]) => key);
    // Tariff lines use the same aggregation level as the financial bars but are
    // independent of the user's import/export volume. The backend time-weights
    // the persisted tariff across each displayed bucket: Year -> month,
    // Month -> day, Day -> hour, Day 15 min -> quarter-hour tariff.
    // The period KPI above the chart remains the separate realized/action-weighted
    // price (cost or revenue divided by the actually priced energy).
    const priceRows = rows;
    const priceSeries = [
      ["import_price", "import_tariff_price"],
      ["export_price", "export_tariff_price"]
    ].filter(([toggle]) => this._chartSeries[toggle]);
    const priceKeys = priceSeries.map(([, key]) => key);
    const finite = value => value === null || value === undefined || value === "" ? null : (Number.isFinite(Number(value)) ? Number(value) : null);

    // Financial series overlap around zero instead of stacking. Every bar keeps
    // the same width and its real value/height; larger values are rendered first
    // so smaller values remain visible in front.
    const financeValues = rows.flatMap(r => financeKeys
      .map(key => finite(r[key]))
      .filter(value => value !== null));

    const niceAxis = (minValue, maxValue, targetTicks = 5, includeZero = false) => {
      let min = Number.isFinite(minValue) ? minValue : 0;
      let max = Number.isFinite(maxValue) ? maxValue : 1;
      if (includeZero) {
        min = Math.min(0, min);
        max = Math.max(0, max);
      }
      if (max <= min) {
        const delta = Math.max(Math.abs(max) * 0.1, 0.01);
        min -= delta;
        max += delta;
      }
      const rawStep = (max - min) / Math.max(2, targetTicks - 1);
      const magnitude = 10 ** Math.floor(Math.log10(Math.max(rawStep, 1e-9)));
      const normalized = rawStep / magnitude;
      const niceFactor = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 2.5 ? 2.5 : normalized <= 5 ? 5 : 10;
      const step = niceFactor * magnitude;
      let niceMin = Math.floor(min / step) * step;
      let niceMax = Math.ceil(max / step) * step;
      if (includeZero && min >= 0) niceMin = 0;
      if (includeZero && max <= 0) niceMax = 0;
      if (niceMax <= niceMin) niceMax = niceMin + step;
      const ticks = [];
      for (let value = niceMin, guard = 0; value <= niceMax + step * 0.25 && guard < 12; value += step, guard += 1) {
        ticks.push(Math.abs(value) < step * 1e-9 ? 0 : value);
      }
      return { min: niceMin, max: niceMax, ticks };
    };

    let financeMin = Math.min(0, ...(financeValues.length ? financeValues : [0]));
    let financeMax = Math.max(0, ...(financeValues.length ? financeValues : [0]));
    let financeAxis = niceAxis(financeMin, financeMax, 6, true);

    const priceValues = [];
    for (const r of priceRows) {
      for (const key of priceKeys) {
        const value = finite(r[key]);
        if (value !== null) priceValues.push(value);
      }
    }

    const ticksForFixedDomain = (min, max, targetTicks = 5) => {
      if (!Number.isFinite(min) || !Number.isFinite(max) || max <= min) return [0];
      const rawStep = (max - min) / Math.max(2, targetTicks - 1);
      const magnitude = 10 ** Math.floor(Math.log10(Math.max(rawStep, 1e-9)));
      const normalized = rawStep / magnitude;
      const niceFactor = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 2.5 ? 2.5 : normalized <= 5 ? 5 : 10;
      const step = niceFactor * magnitude;
      const ticks = [];
      const first = Math.ceil((min - step * 1e-9) / step) * step;
      for (let value = first, guard = 0; value <= max + step * 1e-9 && guard < 14; value += step, guard += 1) {
        ticks.push(Math.abs(value) < step * 1e-9 ? 0 : value);
      }
      if (min <= 0 && max >= 0 && !ticks.some(value => Math.abs(value) < step * 1e-9)) ticks.push(0);
      ticks.sort((a, b) => a - b);
      return ticks;
    };

    const alignedAxis = (dataMin, dataMax, zeroRatio, targetTicks = 5) => {
      const safeRatio = Math.min(1 - 1e-6, Math.max(1e-6, zeroRatio));
      const negativeNeed = Math.max(0, -dataMin);
      const positiveNeed = Math.max(0, dataMax);
      const spanNeeded = Math.max(
        negativeNeed / safeRatio,
        positiveNeed / (1 - safeRatio),
        0.001
      ) * 1.08;
      const min = -safeRatio * spanNeeded;
      const max = (1 - safeRatio) * spanNeeded;
      return { min, max, ticks: ticksForFixedDomain(min, max, targetTicks) };
    };

    let priceAxis = null;
    if (priceValues.length) {
      let pMin = Math.min(...priceValues);
      let pMax = Math.max(...priceValues);
      const priceSpan = Math.max(pMax - pMin, Math.max(Math.abs(pMax), Math.abs(pMin), 0.05) * 0.04, 0.005);
      pMin -= priceSpan * 0.08;
      pMax += priceSpan * 0.08;

      // Both Y axes share exactly the same zero baseline. Normally the financial
      // axis is leading. If its zero is at an edge while tariff data crosses
      // zero, give the financial axis some empty room so negative tariffs are
      // still visible without moving the shared zero line.
      let zeroRatio = (0 - financeAxis.min) / (financeAxis.max - financeAxis.min); // fraction from bottom
      const financeZeroAtBottom = zeroRatio <= 1e-9;
      const financeZeroAtTop = zeroRatio >= 1 - 1e-9;
      if ((financeZeroAtBottom && pMin < 0) || (financeZeroAtTop && pMax > 0)) {
        const priceReference = niceAxis(pMin, pMax, 5, true);
        let candidateRatio = (0 - priceReference.min) / (priceReference.max - priceReference.min);
        // If the two axes contain values on opposite sides of zero only, neither
        // edge can be the shared baseline. Put zero in the middle so both remain visible.
        if (candidateRatio <= 1e-9 || candidateRatio >= 1 - 1e-9) candidateRatio = 0.5;
        zeroRatio = candidateRatio;
        financeAxis = alignedAxis(financeMin, financeMax, zeroRatio, 6);
      }

      zeroRatio = (0 - financeAxis.min) / (financeAxis.max - financeAxis.min);
      if (zeroRatio <= 1e-9 && pMin >= 0) {
        priceAxis = { min: 0, max: niceAxis(0, pMax, 5, true).max, ticks: niceAxis(0, pMax, 5, true).ticks };
      } else if (zeroRatio >= 1 - 1e-9 && pMax <= 0) {
        const axis = niceAxis(pMin, 0, 5, true);
        priceAxis = { min: axis.min, max: 0, ticks: axis.ticks };
      } else {
        priceAxis = alignedAxis(pMin, pMax, zeroRatio, 5);
      }
    }

    const fy = v => top + (financeAxis.max - Number(v)) / (financeAxis.max - financeAxis.min) * plotH;
    const py = v => top + (priceAxis.max - Number(v)) / (priceAxis.max - priceAxis.min) * plotH;
    const slotW = plotW / timelineBuckets;
    const timeX = ms => left + Math.max(0, Math.min(1, (ms - chartStartMs) / Math.max(1, chartEndMs - chartStartMs))) * plotW;
    const rowX = r => timeX((new Date(r.start).getTime() + new Date(r.end).getTime()) / 2);
    const groupW = Math.max(5, Math.min(slotW * 0.72, 46));
    const zeroY = fy(0);
    const barClass = { net_cost: "costBar", pv_value: "pvBar", battery_profit: "batteryBar" };

    const bars = rows.map((r, i) => {
      const visibleBars = financeKeys
        .map((key, seriesIndex) => ({ key, seriesIndex, value: finite(r[key]) }))
        .filter(item => item.value !== null && item.value !== 0)
        .sort((a, b) => {
          const magnitude = Math.abs(b.value) - Math.abs(a.value);
          return magnitude !== 0 ? magnitude : a.seriesIndex - b.seriesIndex;
        });

      const barW = Math.max(4, groupW);
      return visibleBars.map((item) => {
        // Largest absolute value is rendered first (behind), but every series
        // uses the same width so the visible top/bottom still reflects the real
        // value without implying a different bar weight.
        const yValue = fy(item.value);
        const y = Math.min(zeroY, yValue);
        const h = Math.max(1, Math.abs(zeroY - yValue));
        return `<rect class="chartBar ${barClass[item.key]}" x="${(rowX(r) - barW / 2).toFixed(2)}" y="${y.toFixed(2)}" width="${barW.toFixed(2)}" height="${h.toFixed(2)}" rx="2"></rect>`;
      }).join("");
    }).join("");

    const pricePath = key => {
      if (!priceAxis) return "";
      let d = "", open = false;
      priceRows.forEach(r => {
        const value = finite(r[key]);
        if (value === null) { open = false; return; }
        const center = (new Date(r.start).getTime() + new Date(r.end).getTime()) / 2;
        d += `${open ? "L" : "M"}${timeX(center).toFixed(2)},${py(value).toFixed(2)} `;
        open = true;
      });
      return d.trim();
    };

    const xTicks = this.chartTimeTicks(chartStartMs, chartEndMs, chart.granularity, plotW, timeX, timelineBuckets);

    return `<div class="section chartSection">
      ${header}
      <div class="chartBox">
        <svg id="financeChart" data-chart-context="overview" data-view-width="${width}" data-chart-start="${chartStartMs}" data-chart-end="${chartEndMs}" data-chart-left="${left}" data-chart-right="${right}" width="${width}" height="${height}" aria-label="${this.tr("Financieel verloop", "Financial overview")}" style="width:${width}px;height:${height}px;max-width:none">
          <text class="chartAxisTitle" x="${left}" y="16">${this.tr("€ per periode", "€ per period")}</text>
          ${priceAxis ? `<text class="chartAxisTitle chartAxisTitleRight" x="${width-right}" y="16" text-anchor="end">€/kWh</text>` : ""}
          ${financeAxis.ticks.map(v => `<line class="chartGrid" x1="${left}" x2="${width-right}" y1="${fy(v)}" y2="${fy(v)}"></line><text class="chartYLabel" x="${left-10}" y="${fy(v)+4}" text-anchor="end">${this.money(v)}</text>`).join("")}
          ${priceAxis ? priceAxis.ticks.map(v => `<text class="chartPriceYLabel" x="${width-right+10}" y="${py(v)+4}" text-anchor="start">${this.priceAxisAmount(v)}</text>`).join("") : ""}
          <line class="chartZero" x1="${left}" x2="${width-right}" y1="${zeroY}" y2="${zeroY}"></line>
          ${xTicks.map(tick => `<text class="chartXLabel" x="${tick.x}" y="${height-22}" text-anchor="middle">${tick.label}</text>`).join("")}
          ${bars}
          ${this._chartSeries.import_price && priceAxis ? `<path class="priceLine importPriceLine" d="${pricePath("import_tariff_price")}"></path>` : ""}
          ${this._chartSeries.export_price && priceAxis ? `<path class="priceLine exportPriceLine" d="${pricePath("export_tariff_price")}"></path>` : ""}
          <line id="chartCursor" class="chartCursor" x1="0" x2="0" y1="${top}" y2="${height-bottom}" visibility="hidden"></line>
        </svg>
        <div id="chartTooltip" class="chartTooltip" hidden></div>
      </div>
    </div>`;
  }

  renderAssetChart(kind) {
    const chart = this._chart;
    const allRows = chart?.rows || [];
    const cfg = this.assetChartSeries(kind);
    const barsCfg = cfg.bars.filter(item => this._chartSeries[item.toggle]);
    const linesCfg = cfg.lines.filter(item => this._chartSeries[item.toggle]);
    const isSolar = kind === "solar";
    let displayStartMs = chart ? new Date(chart.start).getTime() : 0;
    let displayEndMs = chart ? new Date(chart.end).getTime() : 0;
    if (chart && isSolar && ["hour", "quarter"].includes(chart.granularity)) {
      const daylight = this.solarDaylightWindow(this._chartAnchor);
      if (daylight && daylight.end > daylight.start) {
        displayStartMs = Math.max(displayStartMs, daylight.start);
        displayEndMs = Math.min(displayEndMs, daylight.end);
      }
    }
    const rows = allRows.filter(row => {
      const start = new Date(row.start).getTime(), end = new Date(row.end).getTime();
      return end > displayStartMs && start < displayEndMs;
    });
    const partial = rows.reduce((n, r) => n + Number(isSolar ? !r.pv_complete : !r.battery_complete), 0);
    const title = isSolar ? this.tr("Zonne-energie verloop", "Solar energy overview") : this.tr("Batterijverloop", "Battery overview");
    const header = `<div class="chartHead"><div><h2>${title}</h2><div class="sub">${this.chartViewTitle()}${partial ? ` · ⚠ ${partial} ${this.tr("onvolledige punten", "incomplete points")}` : ""}</div></div>${this.chartControls()}</div>
      <div class="chartToolbar">${this.chartViewSelector()}${this.chartAverageMetrics(kind)}</div>
      ${this.assetChartSeriesSelector(kind)}`;
    if (!chart || this._chartLoading) return `<div class="section chartSection">${header}<div class="chartEmpty">${this._chartError || this.tr("Grafiek laden…", "Loading chart…")}</div></div>`;
    if (!rows.length) return `<div class="section chartSection">${header}<div class="chartEmpty">${this.tr("Geen ledgerdata in deze periode.", "No ledger data in this period.")}</div></div>`;

    const hostWidth = Math.floor(this.getBoundingClientRect().width || window.innerWidth || 1000);
    const availableWidth = Math.max(320, Math.min(1460, hostWidth - (hostWidth <= 600 ? 36 : 64)));
    const minSlot = { month: 56, day: 30, hour: 36, quarter: 22 }[chart.granularity] || 32;
    const height = hostWidth <= 600 ? 350 : 390;
    const left = hostWidth <= 600 ? 58 : 72;
    const right = hostWidth <= 600 ? 66 : 80;
    const top = 32;
    const bottom = hostWidth <= 600 ? 54 : 62;
    const chartStartMs = displayStartMs;
    const chartEndMs = displayEndMs;
    const bucketUnitMs = { month: 30.4375 * 86400000, day: 86400000, hour: 3600000, quarter: 900000 }[chart.granularity] || 3600000;
    const timelineBuckets = Math.max(1, Math.round((chartEndMs - chartStartMs) / bucketUnitMs));
    const width = Math.max(availableWidth, left + right + timelineBuckets * minSlot);
    const plotW = width - left - right;
    const plotH = height - top - bottom;
    const finite = value => value === null || value === undefined || value === "" ? null : (Number.isFinite(Number(value)) ? Number(value) : null);

    const niceAxis = (minValue, maxValue, targetTicks = 5, includeZero = false) => {
      let min = Number.isFinite(minValue) ? minValue : 0;
      let max = Number.isFinite(maxValue) ? maxValue : 1;
      if (includeZero) { min = Math.min(0,min); max = Math.max(0,max); }
      if (max <= min) { const delta = Math.max(Math.abs(max)*0.1,0.01); min -= delta; max += delta; }
      const rawStep = (max-min)/Math.max(2,targetTicks-1);
      const magnitude = 10 ** Math.floor(Math.log10(Math.max(rawStep,1e-9)));
      const normalized = rawStep/magnitude;
      const factor = normalized<=1?1:normalized<=2?2:normalized<=2.5?2.5:normalized<=5?5:10;
      const step = factor*magnitude;
      let niceMin = Math.floor(min/step)*step;
      let niceMax = Math.ceil(max/step)*step;
      if (includeZero && min>=0) niceMin=0;
      if (includeZero && max<=0) niceMax=0;
      if (niceMax<=niceMin) niceMax=niceMin+step;
      const ticks=[];
      for(let v=niceMin,g=0;v<=niceMax+step*.25&&g<12;v+=step,g++) ticks.push(Math.abs(v)<step*1e-9?0:v);
      return {min:niceMin,max:niceMax,ticks};
    };
    const ticksForFixedDomain = (min,max,targetTicks=5) => {
      if (!Number.isFinite(min)||!Number.isFinite(max)||max<=min) return [0];
      const raw=(max-min)/Math.max(2,targetTicks-1), mag=10**Math.floor(Math.log10(Math.max(raw,1e-9))), norm=raw/mag;
      const factor=norm<=1?1:norm<=2?2:norm<=2.5?2.5:norm<=5?5:10, step=factor*mag, ticks=[];
      const first=Math.ceil((min-step*1e-9)/step)*step;
      for(let v=first,g=0;v<=max+step*1e-9&&g<14;v+=step,g++) ticks.push(Math.abs(v)<step*1e-9?0:v);
      if(min<=0&&max>=0&&!ticks.some(v=>Math.abs(v)<step*1e-9)) ticks.push(0);
      return ticks.sort((a,b)=>a-b);
    };
    const alignedAxis=(dataMin,dataMax,zeroRatio,targetTicks=5)=>{
      const ratio=Math.min(1-1e-6,Math.max(1e-6,zeroRatio));
      const span=Math.max(Math.max(0,-dataMin)/ratio,Math.max(0,dataMax)/(1-ratio),0.001)*1.08;
      const min=-ratio*span,max=(1-ratio)*span;
      return {min,max,ticks:ticksForFixedDomain(min,max,targetTicks)};
    };

    const primaryValues = rows.flatMap(r => barsCfg.map(item => finite(r[item.key])).filter(v => v !== null));
    let primaryMin = Math.min(0,...(primaryValues.length?primaryValues:[0]));
    let primaryMax = Math.max(0,...(primaryValues.length?primaryValues:[0]));
    let primaryAxis = niceAxis(primaryMin,primaryMax,6,true);
    const secondaryValues = rows.flatMap(r => linesCfg.map(item => finite(r[item.key])).filter(v => v !== null));
    let secondaryAxis = null;
    if (secondaryValues.length) {
      let sMin=Math.min(...secondaryValues), sMax=Math.max(...secondaryValues);
      const span=Math.max(sMax-sMin,Math.max(Math.abs(sMin),Math.abs(sMax),0.05)*0.04,0.005);
      sMin-=span*.08; sMax+=span*.08;
      let zeroRatio=(0-primaryAxis.min)/(primaryAxis.max-primaryAxis.min);
      if ((zeroRatio<=1e-9&&sMin<0)||(zeroRatio>=1-1e-9&&sMax>0)) {
        const ref=niceAxis(sMin,sMax,5,true);
        let candidate=(0-ref.min)/(ref.max-ref.min);
        if(candidate<=1e-9||candidate>=1-1e-9) candidate=.5;
        primaryAxis=alignedAxis(primaryMin,primaryMax,candidate,6);
        zeroRatio=candidate;
      }
      if(zeroRatio<=1e-9&&sMin>=0) secondaryAxis=niceAxis(0,sMax,5,true);
      else if(zeroRatio>=1-1e-9&&sMax<=0) secondaryAxis=niceAxis(sMin,0,5,true);
      else secondaryAxis=alignedAxis(sMin,sMax,zeroRatio,5);
    }

    const fy=v=>top+(primaryAxis.max-Number(v))/(primaryAxis.max-primaryAxis.min)*plotH;
    const sy=v=>top+(secondaryAxis.max-Number(v))/(secondaryAxis.max-secondaryAxis.min)*plotH;
    const slotW=plotW/timelineBuckets, timeX=ms=>left+Math.max(0,Math.min(1,(ms-chartStartMs)/Math.max(1,chartEndMs-chartStartMs)))*plotW, rowX=r=>timeX((new Date(r.start).getTime()+new Date(r.end).getTime())/2), groupW=Math.max(5,Math.min(slotW*.72,46)), zeroY=fy(0);
    const bars=rows.map((r,i)=>{
      const items=barsCfg.map((item,index)=>({...item,index,value:finite(r[item.key])})).filter(x=>x.value!==null&&x.value!==0).sort((a,b)=>Math.abs(b.value)-Math.abs(a.value)||a.index-b.index);
      return items.map(item=>{const yv=fy(item.value),y=Math.min(zeroY,yv),h=Math.max(1,Math.abs(zeroY-yv));return `<rect class="chartBar ${item.cls}Bar" x="${(rowX(r)-groupW/2).toFixed(2)}" y="${y.toFixed(2)}" width="${groupW.toFixed(2)}" height="${h.toFixed(2)}" rx="2"></rect>`}).join("");
    }).join("");
    const linePath=item=>{if(!secondaryAxis)return"";let d="",open=false;rows.forEach(r=>{const v=finite(r[item.key]);if(v===null){open=false;return;}d+=`${open?"L":"M"}${rowX(r).toFixed(2)},${sy(v).toFixed(2)} `;open=true;});return d.trim();};
    const xTicks=this.chartTimeTicks(chartStartMs,chartEndMs,chart.granularity,plotW,timeX,timelineBuckets);
    const primaryTitle=this.tr("kWh per periode","kWh per period"), secondaryTitle=this.tr("€ per periode","€ per period");

    return `<div class="section chartSection">${header}<div class="chartBox"><svg id="financeChart" data-chart-context="${kind}" data-view-width="${width}" data-chart-start="${chartStartMs}" data-chart-end="${chartEndMs}" data-chart-left="${left}" data-chart-right="${right}" width="${width}" height="${height}" aria-label="${title}" style="width:${width}px;height:${height}px;max-width:none">
      <text class="chartAxisTitle" x="${left}" y="16">${primaryTitle}</text>${secondaryAxis?`<text class="chartAxisTitle" x="${width-right}" y="16" text-anchor="end">${secondaryTitle}</text>`:""}
      ${primaryAxis.ticks.map(v=>`<line class="chartGrid" x1="${left}" x2="${width-right}" y1="${fy(v)}" y2="${fy(v)}"></line><text class="chartYLabel" x="${left-10}" y="${fy(v)+4}" text-anchor="end">${this.num(v,3)}</text>`).join("")}
      ${secondaryAxis?secondaryAxis.ticks.map(v=>`<text class="chartPriceYLabel" x="${width-right+10}" y="${sy(v)+4}" text-anchor="start">${this.money(v)}</text>`).join(""):""}
      <line class="chartZero" x1="${left}" x2="${width-right}" y1="${zeroY}" y2="${zeroY}"></line>
      ${xTicks.map(tick=>`<text class="chartXLabel" x="${tick.x}" y="${height-22}" text-anchor="middle">${tick.label}</text>`).join("")}${bars}
      ${linesCfg.map(item=>`<path class="priceLine ${item.cls}Line" d="${linePath(item)}"></path>`).join("")}
      <line id="chartCursor" class="chartCursor" x1="0" x2="0" y1="${top}" y2="${height-bottom}" visibility="hidden"></line></svg><div id="chartTooltip" class="chartTooltip" hidden></div></div></div>`;
  }

  bindChartInteractions() {
    this.shadowRoot.querySelectorAll("[data-chart-view]").forEach(el => el.addEventListener("click", () => this.loadChartView(el.dataset.chartView, this._chartAnchor)));
    this.shadowRoot.querySelectorAll("[data-chart-series]").forEach(el => el.addEventListener("click", () => {
      const key = el.dataset.chartSeries;
      this._chartSeries[key] = !this._chartSeries[key];
      try { localStorage.setItem("energy_cost_tracker_chart_series", JSON.stringify(this._chartSeries)); } catch (_) {}
      this.render();
    }));
    this.shadowRoot.querySelectorAll("[data-chart-theme]").forEach(el => el.addEventListener("click", () => {
      this._chartTheme = el.dataset.chartTheme;
      try { localStorage.setItem("energy_cost_tracker_chart_theme", this._chartTheme); } catch (_) {}
      this.render();
    }));
    this.shadowRoot.querySelector("#chartPrev")?.addEventListener("click", () => this.shiftChart(-1));
    this.shadowRoot.querySelector("#chartNext")?.addEventListener("click", () => this.shiftChart(1));
    this.shadowRoot.querySelector("#chartNow")?.addEventListener("click", () => this.resetChart());

    const svg = this.shadowRoot.querySelector("#financeChart");
    const chartBox = this.shadowRoot.querySelector(".chartBox");
    if (!svg || !this._chart?.rows?.length) return;

    const tooltip = this.shadowRoot.querySelector("#chartTooltip");
    const cursor = this.shadowRoot.querySelector("#chartCursor");
    const hostWidth = Math.floor(this.getBoundingClientRect().width || window.innerWidth || 1000);
    const left = Number(svg.dataset.chartLeft || (hostWidth <= 600 ? 58 : 72));
    const right = Number(svg.dataset.chartRight || (hostWidth <= 600 ? 62 : 76));
    const viewW = Number(svg.dataset.viewWidth || 1000);
    const plotW = viewW - left - right;
    const chartStartMs = Number(svg.dataset.chartStart || new Date(this._chart.start).getTime());
    const chartEndMs = Number(svg.dataset.chartEnd || new Date(this._chart.end).getTime());
    const rows = this._chart.rows.filter(row => new Date(row.end).getTime() > chartStartMs && new Date(row.start).getTime() < chartEndMs);
    const bucketUnitMs = { month: 30.4375 * 86400000, day: 86400000, hour: 3600000, quarter: 900000 }[this._chart.granularity] || 3600000;
    const timelineBuckets = Math.max(1, Math.round((chartEndMs - chartStartMs) / bucketUnitMs));
    const slotW = plotW / timelineBuckets;
    const timeX = ms => left + Math.max(0, Math.min(1, (ms - chartStartMs) / Math.max(1, chartEndMs - chartStartMs))) * plotW;
    const rowX = row => timeX((new Date(row.start).getTime() + new Date(row.end).getTime()) / 2);

    if (chartBox && this._chartScrollTarget !== null) {
      const target = this._chartScrollTarget;
      this._chartScrollTarget = null;
      requestAnimationFrame(() => {
        const clampedTarget = Math.max(chartStartMs, Math.min(chartEndMs, target));
        const targetX = timeX(clampedTarget);
        const wanted = targetX - chartBox.clientWidth / 2;
        chartBox.scrollLeft = Math.max(0, Math.min(chartBox.scrollWidth - chartBox.clientWidth, wanted));
      });
    } else if (chartBox && this._chartNeedsInitialScroll) {
      this._chartNeedsInitialScroll = false;
      requestAnimationFrame(() => {
        const targetX = timeX(Math.min(Date.now(), chartEndMs));
        chartBox.scrollLeft = Math.max(0, Math.min(chartBox.scrollWidth - chartBox.clientWidth, targetX - chartBox.clientWidth / 2));
      });
    }

    const indexForEvent = ev => {
      const rect = svg.getBoundingClientRect();
      const vx = (ev.clientX - rect.left) / Math.max(1, rect.width) * viewW;
      const ratio = Math.max(0, Math.min(1, (vx - left) / Math.max(1, plotW)));
      const target = chartStartMs + ratio * (chartEndMs - chartStartMs);
      const containing = rows.findIndex(row => target >= new Date(row.start).getTime() && target < new Date(row.end).getTime());
      if (containing >= 0) return containing;
      let best = null, distance = Infinity;
      rows.forEach((row, index) => {
        const center = (new Date(row.start).getTime() + new Date(row.end).getTime()) / 2;
        const d = Math.abs(center - target);
        if (d < distance) { best = index; distance = d; }
      });
      return distance <= bucketUnitMs ? best : null;
    };
    const showTooltip = (ev, forcedIndex = null) => {
      if (!tooltip) return;
      const i = forcedIndex === null ? indexForEvent(ev) : forcedIndex;
      if (i === null || i === undefined || !rows[i]) { hideTooltip(); return; }
      const r = rows[i];
      const rect = svg.getBoundingClientRect();
      const context = svg.dataset.chartContext || "overview";
      const detailRows = context === "overview"
        ? []
        : (Array.isArray(this._chart?.line_rows) ? this._chart.line_rows : []);
      let detail = null;
      if (detailRows.length) {
        const pointerX = ev?.clientX ?? (rect.left + rowX(r) / viewW * rect.width);
        const ratio = Math.max(0, Math.min(1, (pointerX - rect.left) / Math.max(1, rect.width)));
        const targetMs = new Date(this._chart.start).getTime() + ratio * (new Date(this._chart.end).getTime() - new Date(this._chart.start).getTime());
        detail = detailRows.reduce((best, candidate) => {
          const center = (new Date(candidate.start).getTime() + new Date(candidate.end).getTime()) / 2;
          if (!best) return candidate;
          const bestCenter = (new Date(best.start).getTime() + new Date(best.end).getTime()) / 2;
          return Math.abs(center - targetMs) < Math.abs(bestCenter - targetMs) ? candidate : best;
        }, null);
      }
      const px = rowX(r);
      if (cursor) { cursor.setAttribute("x1", px); cursor.setAttribute("x2", px); cursor.setAttribute("visibility", "visible"); }
      if (context === "solar") {
        const partial = !r.pv_complete;
        tooltip.innerHTML = `<b>${this.chartIntervalLabel(r, this._chart?.granularity)}</b><br>${this.tr("PV-productie", "Solar production")}: ${this.num(r.pv_production_kwh,3)} kWh<br>${this.tr("Direct verbruik", "Direct use")}: ${this.num(r.pv_direct_kwh,3)} kWh<br>${this.tr("Teruglevering", "Grid export")}: ${this.num(r.pv_export_kwh,3)} kWh${this.showBattery() ? `<br>${this.tr("Naar batterij", "To battery")}: ${this.num(r.pv_to_battery_kwh,3)} kWh` : ""}<br>${this.tr("Zelfconsumptie", "Self-consumption")}: ${this.percent(this.solarSelfConsumption(r))}<br>${this.tr("PV-waarde", "Solar value")}: ${this.money(r.pv_value)}${partial ? `<br><span>⚠ ${this.tr("Bekend subtotaal / onvolledig", "Known subtotal / incomplete")}</span>` : ""}`;
      } else if (context === "battery") {
        const partial = !r.battery_complete;
        tooltip.innerHTML = `<b>${this.chartIntervalLabel(r, this._chart?.granularity)}</b><br>${this.tr("Laden", "Charge")}: ${this.num(r.battery_charge_kwh,3)} kWh<br>${this.tr("Ontladen", "Discharge")}: ${this.num(r.battery_discharge_kwh,3)} kWh<br>${this.tr("Laadkosten", "Charge cost")}: ${this.money(r.battery_charge_cost)}<br>${this.tr("Ontlaadwaarde", "Discharge value")}: ${this.money(r.battery_discharge_value)}<br>${this.tr("Batterijwinst", "Battery profit")}: ${this.money(r.battery_profit)}${partial ? `<br><span>⚠ ${this.tr("Bekend subtotaal / onvolledig", "Known subtotal / incomplete")}</span>` : ""}`;
      } else {
        const partial = !r.financial_complete || (this.showPv() && !r.pv_complete) || (this.showBattery() && !r.battery_complete);
        const pvLine = this.showPv() ? `<br>${this.tr("PV-waarde", "Solar value")}: ${this.money(r.pv_value)}` : "";
        const batteryLine = this.showBattery() ? `<br>${this.tr("Batterijwinst", "Battery profit")}: ${this.money(r.battery_profit)}` : "";
        tooltip.innerHTML = `<b>${this.chartIntervalLabel(r, this._chart?.granularity)}</b><br>${this.tr("Nettokosten", "Net cost")}: ${this.money(r.net_cost)}${pvLine}${batteryLine}<br>${this.tr("Importtarief", "Import tariff")}: ${this.price(r.import_tariff_price)}<br>${this.tr("Exporttarief", "Export tariff")}: ${this.price(r.export_tariff_price)}${partial ? `<br><span>⚠ ${this.tr("Bekend subtotaal / onvolledig", "Known subtotal / incomplete")}</span>` : ""}`;
      }
      tooltip.hidden = false;
      const pointerX = ev?.clientX ?? (rect.left + px / viewW * rect.width);
      let tx = pointerX - rect.left + 12;
      if (tx > rect.width - 215) tx = Math.max(4, tx - 230);
      tooltip.style.left = `${tx}px`;
      tooltip.style.top = "12px";
    };

    const hideTooltip = () => {
      if (tooltip) tooltip.hidden = true;
      if (cursor) cursor.setAttribute("visibility", "hidden");
    };

    const drillDown = row => {
      const nextView = { month: "day", day: "hour", hour: "quarter" }[this._chartView];
      if (!nextView || !row) return;
      const start = new Date(row.start).getTime();
      const end = new Date(row.end).getTime();
      const now = Date.now();
      const target = now >= start && now < end ? now : (start + end) / 2;
      this._touchTooltipIndex = null;
      hideTooltip();
      this.loadChartView(nextView, new Date(target), new Date(target));
    };

    const coarsePointer = (() => {
      try { return Boolean(window.matchMedia?.("(pointer: coarse)")?.matches); }
      catch (_) { return false; }
    })();
    const isTouchLikeEvent = ev => ev?.pointerType === "touch"
      || ev?.pointerType === "pen"
      || coarsePointer
      || hostWidth <= 600;
    const handleTap = (ev, index) => {
      if (index === null || index === undefined || !rows[index]) return;
      const now = Date.now();
      const secondTap = this._touchTooltipIndex === index && now - this._touchTooltipAt < 1800;
      if (secondTap) {
        drillDown(rows[index]);
        return;
      }
      this._touchTooltipIndex = index;
      this._touchTooltipAt = now;
      showTooltip(ev, index);
    };

    let touchStart = null;
    svg.addEventListener("pointermove", ev => {
      if (isTouchLikeEvent(ev)) return;
      showTooltip(ev);
    });
    svg.addEventListener("pointerleave", ev => {
      if (!isTouchLikeEvent(ev)) hideTooltip();
    });
    svg.addEventListener("pointerdown", ev => {
      if (!isTouchLikeEvent(ev)) return;
      const index = indexForEvent(ev);
      if (index === null) return;
      touchStart = { x: ev.clientX, y: ev.clientY, index };
    });
    svg.addEventListener("pointerup", ev => {
      if (!isTouchLikeEvent(ev) || !touchStart) return;
      const dx = ev.clientX - touchStart.x;
      const dy = ev.clientY - touchStart.y;
      const distance = Math.hypot(dx, dy);
      const index = touchStart.index;
      touchStart = null;
      this._suppressChartClickUntil = Date.now() + 500;

      // A swipe is scrolling, not a tooltip/drill action.
      if (distance > 10) {
        this._touchTooltipIndex = null;
        hideTooltip();
        return;
      }

      handleTap(ev, index);
    });
    svg.addEventListener("pointercancel", ev => {
      if (touchStart && isTouchLikeEvent(ev)) {
        // Native scrolling can cancel the pointer sequence. Suppress any
        // synthetic click that the WebView might still emit afterwards.
        this._suppressChartClickUntil = Date.now() + 500;
        this._touchTooltipIndex = null;
        hideTooltip();
      }
      touchStart = null;
    });
    svg.addEventListener("click", ev => {
      if (Date.now() < this._suppressChartClickUntil) return;
      const index = indexForEvent(ev);
      if (index === null) return;
      // Some Android WebViews report taps as mouse/unspecified pointer events.
      // Preserve the mobile one-tap tooltip / second-tap drill-down behavior
      // based on coarse/narrow input rather than pointerType alone.
      if (isTouchLikeEvent(ev)) {
        handleTap(ev, index);
        return;
      }
      drillDown(rows[index]);
    });
  }

  async loadSummary() {
    if (!this._hass || this._loading) return;
    this._loading = true;
    const hadChart = Boolean(this._chartRange);
    try {
      this._summary = await this._hass.callWS({ type: "energy_cost_tracker/summary" });
      this.updateLivePricesFromHass();
      if ((this._tab === "solar" && !this.showPv()) || (this._tab === "battery" && !this.showBattery())) {
        this._tab = "overview";
      }
      if (!this.showPv() && this._filters.activity === "pv") this._filters.activity = "";
      if (!this.showBattery() && ["battery_charge", "battery_discharge"].includes(this._filters.activity)) this._filters.activity = "";
      if (!this.showBattery() && this._filters.quality === "unknown_battery_basis") this._filters.quality = "";
      if (!hadChart) {
        try {
          const stored = JSON.parse(localStorage.getItem("energy_cost_tracker_chart_series") || "null");
          if (stored && typeof stored === "object") this._chartSeries = { ...this._chartSeries, ...stored };
          const storedTheme = localStorage.getItem("energy_cost_tracker_chart_theme");
          if (this.chartThemeOptions().some(([key]) => key === storedTheme)) this._chartTheme = storedTheme;
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
    if (this._invoice) await this.loadInvoice(this._invoiceView, this._invoice.anchor);
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

  availableTabs() {
    return [
      ["overview", this.tr("Overzicht", "Overview"), true],
      ["costs", this.tr("Kosten", "Costs"), true],
      ["solar", this.tr("Zonnepanelen", "Solar"), this.showPv()],
      ["battery", this.tr("Batterij", "Battery"), this.showBattery()],
      ["history", this.tr("Historie", "History"), true],
      ["settings", this.tr("Instellingen", "Settings"), this.isAdmin()]
    ].filter(([, , available]) => available);
  }

  renderOverview() {
    const t = this.period("today"), bm = this.period("billing_month");
    const kpis = [
      {
        label: this.tr("Kosten vandaag", "Cost today"),
        value: this.periodMoney(t, "net_cost", "known_net_cost", "incomplete_cost_intervals"),
        sub: `${this.num(t.grid_import_kwh)} kWh ${this.tr("afname", "import")} · ${this.num(t.grid_export_kwh)} kWh ${this.tr("terug", "export")}`
      },
      {
        label: this.tr("Huidige factuurmaand", "Current billing month"),
        value: this.periodMoney(bm, "net_cost", "known_net_cost", "incomplete_cost_intervals"),
        sub: `${this.date(bm.period_start)} – ${this.date(bm.period_end)}`
      },
      this.showPv() ? {
        label: this.tr("PV-waarde vandaag", "Solar value today"),
        value: this.periodMoney(t, "pv_value", "known_pv_value", "incomplete_pv_intervals"),
        sub: `${this.num(t.pv_production_kwh)} kWh ${this.tr("productie", "production")}`
      } : null,
      this.showBattery() ? {
        label: this.tr("Batterijwinst vandaag", "Battery profit today"),
        value: this.periodMoney(t, "battery_profit", "known_battery_profit", "incomplete_battery_intervals"),
        sub: `${this.num(t.battery_charge_kwh)} kWh ${this.tr("geladen", "charged")} · ${this.num(t.battery_discharge_kwh)} kWh ${this.tr("ontladen", "discharged")}`
      } : null
    ];
    return `
      ${this.renderFinanceChart()}
      ${this.kpiStrip(kpis)}
      <div class="section liveStrip"><span>${this.tr("Net", "Grid")} <b>${this.num(this._summary?.live?.grid_power, 0)} W</b></span>${this.hasPvPower() ? `<span>PV <b>${this.num(this._summary?.live?.pv_power, 0)} W</b></span>` : ""}${this.hasBatteryPower() ? `<span>${this.tr("Batterij", "Battery")} <b>${this.num(this._summary?.live?.battery_power, 0)} W</b></span>` : ""}</div>`;
  }

  renderLegacyCostsOverview() {
    const rows = ["hour","today","week","month","year","billing_month","billing_year","total"];
    const labels = {
      hour:this.tr("Dit uur", "This hour"),
      today:this.tr("Vandaag", "Today"),
      week:this.tr("Deze week", "This week"),
      month:this.tr("Deze maand", "This month"),
      year:this.tr("Dit jaar", "This year"),
      billing_month:this.tr("Factuurmaand", "Billing month"),
      billing_year:this.tr("Factuurjaar", "Billing year"),
      total:this.tr("Alles", "All time")
    };
    return `<details class="section periodOverview"><summary>${this.tr("Periodeoverzicht", "Period overview")}</summary><div class="tableWrap"><table><thead><tr><th>${this.tr("Periode", "Period")}</th><th>${this.tr("Afname", "Import")}</th><th>${this.tr("Terugleveropbrengst", "Export revenue")}</th><th>${this.tr("Vast", "Fixed")}</th><th>${this.tr("Netto", "Net")}</th><th>${this.tr("Kwaliteit", "Quality")}</th></tr></thead><tbody>${rows.map(k => { const p=this.period(k); const missing=Number(p.incomplete_cost_intervals || 0); return `<tr><td>${labels[k]}</td><td>${this.periodMoney(p,"import_cost","known_import_cost","incomplete_import_intervals")}</td><td>${this.periodMoney(p,"export_revenue","known_export_revenue","incomplete_export_intervals")}</td><td>${this.money(p.fixed_cost)}</td><td><b>${this.periodMoney(p,"net_cost","known_net_cost","incomplete_cost_intervals")}</b></td><td>${missing ? `${missing} ${this.tr("zonder prijs", "without price")}` : `${p.non_exact_intervals || 0} ${this.tr("niet exact", "not exact")}`}</td></tr>`; }).join("")}</tbody></table></div></details>`;
  }

  renderInvoiceMain() {
    if (this._invoiceLoading && !this._invoice) return `<div class="section invoiceSection"><div class="invoiceLoading">${this.tr("Factuurgegevens laden…", "Loading invoice data…")}</div></div>`;
    if (this._invoiceError) return `<div class="section invoiceSection"><div class="invoiceLoading">${this._invoiceError}</div></div>`;
    const invoice = this._invoice;
    if (!invoice) return `<div class="section invoiceSection"><div class="invoiceLoading">${this.tr("Factuurgegevens laden…", "Loading invoice data…")}</div></div>`;
    const p = invoice.period || {};
    const fixed = p.fixed_breakdown || {};
    const incomplete = Number(p.incomplete_cost_intervals || 0);
    const nonExact = Number(p.non_exact_intervals || 0);
    const noData = Number(p.intervals || 0) === 0;
    const currentBadge = invoice.is_current ? `<span class="invoiceBadge">${this.tr("Lopend", "Current")}</span>` : "";
    const quality = incomplete
      ? `<div class="invoiceWarning">⚠ ${incomplete} ${this.tr(incomplete === 1 ? "interval mist prijsinformatie; bedragen met * zijn bekende subtotalen." : "intervallen missen prijsinformatie; bedragen met * zijn bekende subtotalen.", incomplete === 1 ? "interval is missing price information; amounts marked * are known subtotals." : "intervals are missing price information; amounts marked * are known subtotals.")}</div>`
      : (nonExact ? `<div class="invoiceMeta">${nonExact} ${this.tr("niet-exacte intervallen", "non-exact intervals")}</div>` : "");
    return `<div class="section invoiceSection">
      <div class="invoiceHead"><div><h2>${this._invoiceView === "month" ? this.tr("Factuurmaand", "Billing month") : this.tr("Factuurjaar", "Billing year")}</h2><div class="sub">${this.invoiceRangeLabel(invoice.period_start, invoice.period_end)} ${currentBadge}</div></div><div class="invoiceControls"><button id="invoicePrev" title="${this.tr("Vorige periode", "Previous period")}">‹</button><button id="invoiceNow">${this.tr("Nu", "Now")}</button><button id="invoiceNext" title="${this.tr("Volgende periode", "Next period")}" ${invoice.is_current ? "disabled" : ""}>›</button></div></div>
      ${this.invoiceViewSelector()}
      ${noData ? `<div class="invoiceNoData">${this.tr("Geen Energy Cost Tracker-data beschikbaar voor deze factuurperiode.", "No Energy Cost Tracker data is available for this billing period.")}</div>` : `<div class="invoiceBreakdown">
        <div class="invoiceGroupTitle">${this.tr("Energie", "Energy")}</div>
        <div class="invoiceLine"><div><b>${this.tr("Netafname", "Grid import")}</b><span>${this.num(p.grid_import_kwh, 2)} kWh</span></div><strong>${this.periodMoney(p,"import_cost","known_import_cost","incomplete_import_intervals")}</strong></div>
        <div class="invoiceLine"><div><b>${this.tr("Teruglevering", "Grid export")}</b><span>${this.num(p.grid_export_kwh, 2)} kWh</span></div><strong>${this.periodMoneyScaled(p,"export_revenue","known_export_revenue","incomplete_export_intervals",-1)}</strong></div>
        <div class="invoiceGroupTitle">${this.tr("Vaste kosten en aftrekposten", "Fixed costs and deductions")}</div>
        <div class="invoiceLine"><span>${this.tr("Vaste kosten per dag", "Daily fixed costs")}</span><strong>${this.money(fixed.daily || 0)}</strong></div>
        <div class="invoiceLine"><span>${this.tr("Vaste kosten per maand", "Monthly fixed costs")}</span><strong>${this.money(fixed.monthly || 0)}</strong></div>
        <div class="invoiceLine"><span>${this.tr("Vaste kosten per jaar", "Annual fixed costs")}</span><strong>${this.money(fixed.annual || 0)}</strong></div>
        <div class="invoiceLine"><span>${this.tr("Jaarlijkse aftrek", "Annual deduction")}</span><strong>${this.money(-Number(fixed.annual_rebate || 0))}</strong></div>
        <div class="invoiceLine invoiceSubtotal"><span>${this.tr("Totaal vaste kosten", "Total fixed costs")}</span><strong>${this.money(p.fixed_cost)}</strong></div>
        <div class="invoiceLine invoiceTotal"><span>${this.tr("Totaal factuurperiode", "Total billing period")}</span><strong>${this.periodMoney(p,"net_cost","known_net_cost","incomplete_cost_intervals")}</strong></div>
      </div>${quality}` }
    </div>`;
  }

  renderInvoiceYearMonths() {
    if (this._invoiceView !== "year" || !this._invoice?.months?.length) return "";
    const rows = this._invoice.months;
    return `<div class="section invoiceMonths"><h2>${this.tr("Factuurmaanden", "Billing months")}</h2><div class="tableWrap"><table><thead><tr><th>${this.tr("Periode", "Period")}</th><th>${this.tr("Netafname", "Import")}</th><th>${this.tr("Teruglevering", "Export")}</th><th>${this.tr("Vast / aftrek", "Fixed / deductions")}</th><th>${this.tr("Totaal", "Total")}</th></tr></thead><tbody>${rows.map(r => { const empty = Number(r.intervals || 0) === 0; return `<tr class="invoiceMonthRow ${empty ? "empty" : ""}" data-invoice-month="${String(r.period_start).slice(0,10)}"><td><b>${this.invoiceRangeLabel(r.period_start,r.period_end)}</b></td>${empty ? `<td>—</td><td>—</td><td>—</td><td>—</td>` : `<td>${this.periodMoney(r,"import_cost","known_import_cost","incomplete_import_intervals")}<small>${this.num(r.grid_import_kwh,2)} kWh</small></td><td>${this.periodMoneyScaled(r,"export_revenue","known_export_revenue","incomplete_export_intervals",-1)}<small>${this.num(r.grid_export_kwh,2)} kWh</small></td><td>${this.money(r.fixed_cost)}</td><td><b>${this.periodMoney(r,"net_cost","known_net_cost","incomplete_cost_intervals")}</b></td>`}</tr>`; }).join("")}</tbody></table></div></div>`;
  }

  renderCosts() {
    return `${this.renderInvoiceMain()}${this.renderInvoiceYearMonths()}${this.renderLegacyCostsOverview()}`;
  }

  renderSolar() {
    const t=this.period("today"), m=this.period("month");
    const historicalNotice = !this.hasPv() && this.hasPvHistory()
      ? `<div class="assetHistoryNotice">${this.tr("Momenteel zijn geen zonnepanelen geconfigureerd. De onderstaande gegevens komen uit de bewaarde historie.", "No solar system is currently configured. The data below comes from retained history.")}</div>`
      : "";
    const liveSub = this.hasPvPower() ? `${this.tr("Nu", "Now")} ${this.num(this._summary?.live?.pv_power,0)} W` : "";
    const kpis = [
      { label:this.tr("Productie vandaag","Production today"), value:`${this.num(t.pv_production_kwh)} kWh`, sub:liveSub },
      { label:this.tr("Zelfconsumptie","Self-consumption"), value:this.percent(this.solarSelfConsumption(t)) },
      { label:this.tr("PV-waarde vandaag","Solar value today"), value:this.periodMoney(t,"pv_value","known_pv_value","incomplete_pv_intervals") },
      { label:this.tr("PV-waarde maand","Solar value this month"), value:this.periodMoney(m,"pv_value","known_pv_value","incomplete_pv_intervals") }
    ];
    return `${historicalNotice}${this.renderAssetChart("solar")}${this.kpiStrip(kpis)}${this.renderInvestmentProgress("solar")}`;
  }

  renderBattery() {
    const t=this.period("today"), m=this.period("month"), inv=this._summary?.battery_inventory || {};
    const historicalNotice = !this.hasBattery() && this.hasBatteryHistory()
      ? `<div class="assetHistoryNotice">${this.tr("Momenteel is geen batterij geconfigureerd. De onderstaande gegevens komen uit de bewaarde historie.", "No battery is currently configured. The data below comes from retained history.")}</div>`
      : "";
    const liveSub = this.hasBatteryPower() ? `${this.tr("Nu", "Now")} ${this.num(this._summary?.live?.battery_power,0)} W` : "";
    const kpis = [
      { label:this.tr("Geladen vandaag","Charged today"), value:`${this.num(t.battery_charge_kwh)} kWh`, sub:liveSub },
      { label:this.tr("Ontladen vandaag","Discharged today"), value:`${this.num(t.battery_discharge_kwh)} kWh` },
      { label:this.tr("Winst vandaag","Profit today"), value:this.periodMoney(t,"battery_profit","known_battery_profit","incomplete_battery_intervals") },
      { label:this.tr("Winst maand","Profit this month"), value:this.periodMoney(m,"battery_profit","known_battery_profit","incomplete_battery_intervals") }
    ];
    const inventory = this.hasBattery() ? `<div class="section assetDetailLine"><span>${this.tr("Batterijvoorraad", "Battery inventory")}</span><b>${this.num(inv.energy_kwh)} kWh</b><span>${this.tr("cost basis", "cost basis")} ${this.money(inv.cost_basis)}</span>${inv.average_price == null ? "" : `<span>${this.tr("gem. opgeslagen", "avg. stored")} ${this.price(inv.average_price)}</span>`}<span>${inv.basis_known ? this.tr("basis bekend", "basis known") : this.tr("basis onvolledig", "basis incomplete")}</span></div>` : "";
    return `${historicalNotice}${this.renderAssetChart("battery")}${this.kpiStrip(kpis)}${inventory}${this.renderInvestmentProgress("battery")}`;
  }

  renderHistory() {
    const rows=this._history?.rows || [];
    const f=this._filters || {};
    const selected=(value,current)=>value===current?" selected":"";
    const activityOptions = [
      `<option value="">${this.tr("Alle activiteiten", "All activities")}</option>`,
      `<option value="grid_import"${selected("grid_import",f.activity)}>${this.tr("Netafname", "Grid import")}</option>`,
      `<option value="grid_export"${selected("grid_export",f.activity)}>${this.tr("Teruglevering", "Grid export")}</option>`,
      this.showPv() ? `<option value="pv"${selected("pv",f.activity)}>${this.tr("PV-productie", "Solar production")}</option>` : "",
      this.showBattery() ? `<option value="battery_charge"${selected("battery_charge",f.activity)}>${this.tr("Batterij laden", "Battery charging")}</option>` : "",
      this.showBattery() ? `<option value="battery_discharge"${selected("battery_discharge",f.activity)}>${this.tr("Batterij ontladen", "Battery discharging")}</option>` : "",
      `<option value="issues"${selected("issues",f.activity)}>${this.tr("Alleen afwijkingen", "Issues only")}</option>`
    ].join("");
    const tariffHeaders = `<th>${this.tr("Importprijs", "Import price")}</th><th>${this.tr("Exportprijs", "Export price")}</th>`;
    const optionalHeaders = `${this.showPv() ? "<th>PV kWh</th>" : ""}${this.showBattery() ? `<th>${this.tr("Batt. +", "Batt. +")}</th><th>${this.tr("Batt. -", "Batt. -")}</th>` : ""}`;
    const optionalFinancialHeaders = `${this.showPv() ? `<th>${this.tr("PV-waarde", "Solar value")}</th>` : ""}${this.showBattery() ? `<th>${this.tr("Batt. winst", "Batt. profit")}</th>` : ""}`;
    const body = rows.map(r=>`<tr><td>${this.dateTime(r.end_ts)}</td><td>${this.num(r.grid_import_kwh,3)}</td><td>${this.num(r.grid_export_kwh,3)}</td><td>${this.price(r.import_price)}</td><td>${this.price(r.export_price)}</td>${this.showPv() ? `<td>${this.num(r.pv_production_kwh,3)}</td>` : ""}${this.showBattery() ? `<td>${this.num(r.battery_charge_kwh,3)}</td><td>${this.num(r.battery_discharge_kwh,3)}</td>` : ""}<td>${this.money(r.net_cost)}</td>${this.showPv() ? `<td>${this.money(r.pv_value)}</td>` : ""}${this.showBattery() ? `<td>${this.money(r.battery_profit)}</td>` : ""}<td><span class="quality ${r.quality}">${this.qualityLabel(r.quality)}</span></td></tr>`).join("");
    const qualityOptions = ["exact","reconstructed","estimated","missing_price", ...(this.showBattery() ? ["unknown_battery_basis"] : [])]
      .map(value => `<option value="${value}"${selected(value,f.quality)}>${this.qualityLabel(value)}</option>`).join("");
    return `<div class="section"><h2>${this.tr("Historie zoeken", "Search history")}</h2><div class="filters"><label>${this.tr("Vanaf", "From")}<input id="start" type="date" value="${f.start || ""}"></label><label>${this.tr("Tot en met", "Through")}<input id="end" type="date" value="${f.end || ""}"></label><label>${this.tr("Activiteit", "Activity")}<select id="activity">${activityOptions}</select></label><label>${this.tr("Kwaliteit", "Quality")}<select id="quality"><option value="">${this.tr("Alle", "All")}</option>${qualityOptions}</select></label><button id="search">${this.tr("Zoeken", "Search")}</button></div>${this._history?`<div class="sub">${this._history.total} ${this.tr("intervallen gevonden", "intervals found")}</div>`:""}<div class="tableWrap"><table><thead><tr><th>${this.tr("Tijd", "Time")}</th><th>${this.tr("Afname kWh", "Import kWh")}</th><th>${this.tr("Terug kWh", "Export kWh")}</th>${tariffHeaders}${optionalHeaders}<th>${this.tr("Kosten", "Cost")}</th>${optionalFinancialHeaders}<th>${this.tr("Kwaliteit", "Quality")}</th></tr></thead><tbody>${body}</tbody></table></div></div>`;
  }

  date(value) { if(!value) return "—"; return new Date(value).toLocaleDateString(this.locale()); }
  dateTime(value) { if(!value) return "—"; return new Date(value).toLocaleString(this.locale()); }

  render() {
    if (!this.shadowRoot) return;
    if (!this.availableTabs().some(([key]) => key === this._tab)) this._tab = "overview";
    const content = !this._summary ? `<div class="loading">${this._error || this.tr("Laden…", "Loading…")}</div>` : ({overview:()=>this.renderOverview(),costs:()=>this.renderCosts(),solar:()=>this.renderSolar(),battery:()=>this.renderBattery(),history:()=>this.renderHistory(),settings:()=>this.renderSettings()}[this._tab]());
    this.shadowRoot.innerHTML = `<style>
      :host{display:block;box-sizing:border-box;background:var(--primary-background-color);color:var(--primary-text-color);min-height:100vh;font-family:var(--paper-font-body1_-_font-family,system-ui)}*{box-sizing:border-box}.page{max-width:1500px;margin:auto;padding:20px}.head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:16px}.head h1{font-size:26px;margin:0}.refresh{border:0;background:var(--primary-color);color:var(--text-primary-color,#fff);padding:10px 14px;border-radius:10px;cursor:pointer}.tabs{display:flex;gap:6px;overflow:auto;margin-bottom:18px}.tab{border:0;border-radius:999px;padding:9px 14px;background:var(--card-background-color);color:var(--primary-text-color);cursor:pointer;white-space:nowrap}.tab.active{background:var(--primary-color);color:#fff}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}.card,.section{background:var(--card-background-color);border-radius:14px;padding:16px;box-shadow:var(--ha-card-box-shadow,0 2px 6px rgba(0,0,0,.12))}.label{font-size:13px;color:var(--secondary-text-color)}.value{font-size:28px;font-weight:700;margin:6px 0}.sub,.hint{font-size:12px;color:var(--secondary-text-color)}.section{margin-top:14px}.section h2{margin:0 0 14px}.live{display:flex;flex-wrap:wrap;gap:18px}.tableWrap{overflow:auto}table{width:100%;border-collapse:collapse;font-size:13px}th,td{text-align:left;padding:10px;border-bottom:1px solid var(--divider-color);white-space:nowrap}th{color:var(--secondary-text-color);font-weight:600}.filters{display:flex;gap:10px;flex-wrap:wrap;align-items:end;margin-bottom:12px}.filters label{display:grid;gap:4px;font-size:12px;color:var(--secondary-text-color)}input,select,button{font:inherit;padding:9px;border-radius:8px;border:1px solid var(--divider-color);background:var(--card-background-color);color:var(--primary-text-color)}.filters button{background:var(--primary-color);color:#fff;border:0}.quality{padding:3px 7px;border-radius:8px;background:var(--secondary-background-color)}.quality.exact{font-weight:600}.loading{padding:40px;text-align:center}.overviewGrid{margin-top:14px}.kpiStrip{display:grid;gap:0;padding:0;overflow:hidden}.kpiStrip.kpiCount1{grid-template-columns:1fr}.kpiStrip.kpiCount2{grid-template-columns:repeat(2,minmax(0,1fr))}.kpiStrip.kpiCount3{grid-template-columns:repeat(3,minmax(0,1fr))}.kpiStrip.kpiCount4{grid-template-columns:repeat(4,minmax(0,1fr))}.kpiItem{display:grid;align-content:center;gap:4px;min-height:92px;padding:14px 16px;border-left:1px solid var(--divider-color)}.kpiItem:first-child{border-left:0}.kpiItem span{font-size:12px;color:var(--secondary-text-color)}.kpiItem b{font-size:21px;line-height:1.15}.kpiItem small{font-size:11px;color:var(--secondary-text-color);line-height:1.25}.liveStrip{display:flex;gap:22px;align-items:center;flex-wrap:wrap;padding:11px 16px;font-size:12px;color:var(--secondary-text-color)}.liveStrip b{margin-left:5px;color:var(--primary-text-color)}.assetDetailLine{display:flex;gap:16px;align-items:center;flex-wrap:wrap;padding:11px 16px;font-size:12px;color:var(--secondary-text-color)}.assetDetailLine b{font-size:14px;color:var(--primary-text-color)}.assetHistoryNotice{margin:0 0 12px;padding:10px 12px;border-radius:10px;background:var(--secondary-background-color);color:var(--secondary-text-color);font-size:12px}.chartSection{padding:16px 16px 12px}.chartHead{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;flex-wrap:wrap}.chartHead h2{margin:0 0 3px}.chartControls{display:flex;gap:6px;flex-wrap:wrap}.chartControls button{min-width:38px;border:0;background:var(--secondary-background-color);cursor:pointer}.chartControls button:disabled{opacity:.35;cursor:default}.chartControls #chartNow{padding-inline:12px}.chartToolbar{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-top:12px}.chartViewSelector{display:flex;padding:3px;background:var(--secondary-background-color);border-radius:10px;overflow:auto}.chartViewSelector button{border:0;background:transparent;padding:7px 11px;white-space:nowrap;cursor:pointer}.chartViewSelector button.active{background:var(--primary-color);color:#fff}.chartPeriodMetrics{display:grid;grid-template-columns:repeat(2,minmax(130px,1fr));gap:6px;min-width:min(100%,330px)}.chartPeriodMetrics>div{display:grid;gap:2px;padding:6px 9px;border-radius:9px;background:var(--secondary-background-color)}.chartPeriodMetrics span,.chartPeriodMetrics small{font-size:11px;color:var(--secondary-text-color)}.chartPeriodMetrics b{font-size:13px;color:var(--primary-text-color)}.chartPeriodMetrics>small{grid-column:1/-1;text-align:right;padding-right:2px}.priceNow{display:flex;gap:8px;flex-wrap:wrap;font-size:12px;color:var(--secondary-text-color)}.priceNow span{padding:6px 9px;border-radius:9px;background:var(--secondary-background-color)}.priceNow b{color:var(--primary-text-color)}.chartToolbarRight{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.assetNow{display:flex;gap:8px;flex-wrap:wrap;font-size:12px;color:var(--secondary-text-color)}.assetNow span{padding:6px 9px;border-radius:9px;background:var(--secondary-background-color)}.assetNow b{color:var(--primary-text-color)}.chartSeriesSelector{display:flex;gap:7px;overflow:auto;padding:10px 0 3px;scrollbar-width:thin}.seriesToggle{display:flex;align-items:center;gap:6px;border:1px solid var(--divider-color);background:var(--card-background-color);padding:6px 9px;white-space:nowrap;cursor:pointer;font-size:12px}.seriesToggle.off{opacity:.42}.seriesToggle i{display:inline-block;width:12px;height:12px;border-radius:3px}.seriesToggle.cost i{background:var(--ect-cost)}.seriesToggle.pv i{background:var(--ect-pv)}.seriesToggle.battery i{background:var(--ect-battery)}.seriesToggle.importPrice i{height:3px;border-radius:3px;background:var(--ect-import)}.seriesToggle.exportPrice i{height:3px;border-radius:3px;background:var(--ect-export)}.seriesToggle.solarProduction i{background:var(--ect-solar-production)}.seriesToggle.solarDirect i{background:var(--ect-solar-direct)}.seriesToggle.solarExport i{background:var(--ect-solar-export)}.seriesToggle.solarBattery i{background:var(--ect-solar-battery)}.seriesToggle.solarValue i{background:var(--ect-solar-value)}.seriesToggle.solarExportPrice i{background:var(--ect-export)}.seriesToggle.batteryCharge i{background:var(--ect-battery-charge)}.seriesToggle.batteryDischarge i{background:var(--ect-battery-discharge)}.seriesToggle.batteryChargeCost i{background:var(--ect-battery-charge-cost)}.seriesToggle.batteryDischargeValue i{background:var(--ect-battery-discharge-value)}.seriesToggle.batteryProfitValue i{background:var(--ect-battery-profit)}.seriesToggle.lineToggle i{height:3px;border-radius:3px}.chartBox{position:relative;width:100%;height:390px;margin-top:4px;overflow-x:auto;overflow-y:hidden;-webkit-overflow-scrolling:touch;overscroll-behavior-x:contain;touch-action:pan-x pan-y;scrollbar-width:thin}.chartBox svg{display:block;touch-action:pan-x pan-y;cursor:crosshair;flex:none;user-select:none;-webkit-user-select:none}.chartGrid{stroke:var(--divider-color);stroke-width:1;vector-effect:non-scaling-stroke}.chartZero{stroke:var(--secondary-text-color);stroke-width:1.2;opacity:.7;vector-effect:non-scaling-stroke}.chartBar{vector-effect:non-scaling-stroke;opacity:.74;stroke:rgba(255,255,255,.20);stroke-width:1}.costBar{fill:var(--ect-cost)}.pvBar{fill:var(--ect-pv)}.batteryBar{fill:var(--ect-battery)}.priceLine{fill:none;stroke-width:2.2;vector-effect:non-scaling-stroke;stroke-linejoin:round;stroke-linecap:round}.importPriceLine{stroke:var(--ect-import)}.exportPriceLine{stroke:var(--ect-export);stroke-dasharray:6 4}.solarProductionBar{fill:var(--ect-solar-production)}.solarDirectBar{fill:var(--ect-solar-direct)}.solarExportBar{fill:var(--ect-solar-export)}.solarBatteryBar{fill:var(--ect-solar-battery)}.batteryChargeBar{fill:var(--ect-battery-charge)}.batteryDischargeBar{fill:var(--ect-battery-discharge)}.solarValueLine{stroke:var(--ect-solar-value)}.solarExportPriceLine{stroke:var(--ect-export);stroke-dasharray:6 4}.batteryChargeCostLine{stroke:var(--ect-battery-charge-cost)}.batteryDischargeValueLine{stroke:var(--ect-battery-discharge-value)}.batteryProfitValueLine{stroke:var(--ect-battery-profit);stroke-dasharray:6 4}.chartYLabel,.chartXLabel,.chartPriceYLabel{fill:var(--secondary-text-color);font-size:12px}.chartAxisTitle{fill:var(--secondary-text-color);font-size:11px;font-weight:600}.chartCursor{stroke:var(--primary-text-color);stroke-width:1;opacity:.35;vector-effect:non-scaling-stroke}.chartTooltip{position:absolute;z-index:2;min-width:190px;padding:9px 10px;border-radius:9px;background:var(--card-background-color);box-shadow:0 3px 14px rgba(0,0,0,.35);font-size:12px;pointer-events:none;line-height:1.5;border:1px solid var(--divider-color)}.chartTooltip span{color:var(--warning-color,#f9a825)}.chartEmpty{height:220px;display:grid;place-items:center;color:var(--secondary-text-color)}.chartHint{margin:4px 0 0}.invoiceSection{max-width:920px}.invoiceHead{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;flex-wrap:wrap}.invoiceHead h2{margin:0 0 4px}.invoiceBadge{display:inline-block;margin-left:7px;padding:2px 7px;border-radius:999px;background:var(--primary-color);color:#fff;font-size:11px;vertical-align:1px}.invoiceControls{display:flex;gap:6px}.invoiceControls button{min-width:40px;border:0;background:var(--secondary-background-color);cursor:pointer}.invoiceControls button:disabled{opacity:.35;cursor:default}.invoiceViewSelector{display:inline-flex;margin-top:14px;padding:3px;border-radius:10px;background:var(--secondary-background-color)}.invoiceViewSelector button{border:0;background:transparent;cursor:pointer}.invoiceViewSelector button.active{background:var(--primary-color);color:#fff}.invoiceBreakdown{margin-top:16px;border-top:1px solid var(--divider-color)}.invoiceGroupTitle{padding:18px 0 7px;font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:.05em;color:var(--secondary-text-color)}.invoiceLine{display:flex;align-items:center;justify-content:space-between;gap:18px;padding:10px 0;border-bottom:1px solid var(--divider-color)}.invoiceLine>div{display:grid;gap:3px}.invoiceLine span,.invoiceLine>div span{font-size:12px;color:var(--secondary-text-color)}.invoiceLine strong{font-size:15px;text-align:right}.invoiceSubtotal{border-top:1px solid var(--divider-color);margin-top:2px}.invoiceTotal{padding:15px 0;border-top:2px solid var(--divider-color);border-bottom:0}.invoiceTotal span{font-size:15px;font-weight:700;color:var(--primary-text-color)}.invoiceTotal strong{font-size:22px}.invoiceWarning{margin-top:12px;padding:10px 12px;border-radius:9px;background:color-mix(in srgb,var(--warning-color,#f9a825) 14%,transparent);font-size:12px}.invoiceMeta{margin-top:10px;font-size:12px;color:var(--secondary-text-color)}.invoiceLoading{padding:36px;text-align:center;color:var(--secondary-text-color)}.invoiceNoData{margin-top:16px;padding:22px;border-radius:10px;background:var(--secondary-background-color);text-align:center;color:var(--secondary-text-color)}.invoiceMonths{max-width:1100px}.invoiceMonthRow{cursor:pointer}.invoiceMonthRow:hover{background:var(--secondary-background-color)}.invoiceMonthRow.empty{opacity:.55}.invoiceMonthRow small{display:block;margin-top:3px;color:var(--secondary-text-color)}.periodOverview summary{cursor:pointer;font-weight:600}.periodOverview[open] summary{margin-bottom:12px}.settingsSection{max-width:900px}.settingsGroup{margin-top:4px}.themeSettings{margin-top:24px;padding-top:20px;border-top:1px solid var(--divider-color)}.accessSettings{margin-top:4px}.accessUsers{display:grid;gap:7px;margin-top:12px}.accessUser{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:10px 12px;border-radius:10px;background:var(--secondary-background-color)}.accessUser.inactive{opacity:.55}.accessUserMain{display:flex;align-items:center;gap:9px}.accessUserMain input{margin:0}.accessBadges{display:flex;gap:6px;flex-wrap:wrap}.accessBadge{font-size:11px;padding:3px 7px;border-radius:999px;background:var(--primary-color);color:#fff}.accessBadge.muted{background:var(--divider-color);color:var(--primary-text-color)}.settingsTitle{font-size:14px;font-weight:600;margin-bottom:10px}.themeGrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}.themeOption{display:grid;gap:10px;text-align:left;padding:12px;border:1px solid var(--divider-color);background:var(--secondary-background-color);cursor:pointer}.themeOption.active{border:2px solid var(--primary-color);padding:11px}.themeSwatches{display:grid;grid-template-columns:repeat(5,1fr);height:26px;border-radius:7px;overflow:hidden}.themeSwatches i{display:block}.investmentSettings{margin-top:24px;padding-top:20px;border-top:1px solid var(--divider-color)}.fixedCostSettings{margin-top:24px;padding-top:20px;border-top:1px solid var(--divider-color)}.batteryBasisSettings{margin-top:24px;padding-top:20px;border-top:1px solid var(--divider-color)}.investmentFields{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}.fixedCostFields{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin-top:14px}.fixedCostFields label{display:grid;gap:6px;font-size:13px;color:var(--secondary-text-color)}.fixedCostBase{display:grid;gap:5px;margin-top:10px;padding:10px 12px;border-radius:10px;background:var(--secondary-background-color);font-size:12px}.fixedCostBase span{color:var(--secondary-text-color)}.fixedCostTable{margin-top:12px}.fixedCostActions{display:flex;gap:6px}.fixedCostActions button{padding:6px 8px;font-size:12px}.investmentFields label{display:grid;gap:6px;font-size:13px;color:var(--secondary-text-color)}.investmentFields input{width:100%;color:var(--primary-text-color)}.settingsActions{display:flex;align-items:center;gap:12px;margin-top:12px}.primaryAction{border:0;background:var(--primary-color);color:#fff;cursor:pointer}.primaryAction:disabled{opacity:.55;cursor:default}.warningAction{border:0;background:var(--warning-color,#f9a825);color:var(--text-primary-color,#fff);cursor:pointer}.warningAction:disabled{opacity:.55;cursor:default}.settingsStatus{font-size:12px;color:var(--secondary-text-color)}.investmentProgress{max-width:900px;padding:13px 16px}.investmentCompact{display:flex;align-items:end;justify-content:space-between;gap:16px}.investmentCompact>div{display:grid;gap:3px}.investmentCompact span{font-size:12px;color:var(--secondary-text-color)}.investmentCompact b{font-size:15px}.investmentCompact strong{font-size:18px}.investmentBar{height:10px;margin-top:14px;border-radius:999px;overflow:hidden;background:var(--secondary-background-color)}.investmentBar i{display:block;height:100%;border-radius:inherit;background:var(--primary-color)}.investmentProgress .hint{margin-top:7px}@media(max-width:600px){.page{padding:12px}.kpiStrip,.kpiStrip.kpiCount1,.kpiStrip.kpiCount2,.kpiStrip.kpiCount3,.kpiStrip.kpiCount4{grid-template-columns:repeat(2,minmax(0,1fr))}.kpiItem{min-height:78px;padding:11px 12px;border-left:1px solid var(--divider-color);border-top:1px solid var(--divider-color)}.kpiItem:nth-child(-n+2){border-top:0}.kpiItem:nth-child(odd){border-left:0}.kpiStrip.kpiCount1 .kpiItem,.kpiStrip.kpiCount3 .kpiItem:last-child{grid-column:1/-1}.kpiItem b{font-size:18px}.chartPeriodMetrics{width:100%;min-width:0}.chartPeriodMetrics>div{padding:7px 9px}.assetDetailLine{gap:8px 14px}.investmentCompact{align-items:flex-start}.investmentCompact strong{font-size:16px}.page{padding:12px}.head h1{font-size:22px}.value{font-size:23px}.chartBox{height:350px}.chartSection{padding:14px 10px 10px}.chartHead{gap:8px}.chartControls{width:100%}.chartControls button{flex:1}.chartToolbar{align-items:stretch}.chartViewSelector{width:100%}.chartViewSelector button{flex:1}.priceNow{width:100%}.priceNow span{flex:1;min-width:145px}.chartToolbarRight{width:100%}.assetNow{width:100%}.chartYLabel,.chartXLabel,.chartPriceYLabel{font-size:13px}.chartSeriesSelector{margin-inline:-2px}.settingsActions{align-items:flex-start;flex-direction:column}.primaryAction{width:100%}.invoiceSection{padding:14px}.invoiceControls{width:100%}.invoiceControls button{flex:1}.invoiceViewSelector{display:flex;width:100%}.invoiceViewSelector button{flex:1}.invoiceLine{gap:10px}.invoiceTotal strong{font-size:19px}}
    </style><div class="page" style="${this.chartThemeStyle()}"><div class="head"><h1>Energy Cost Tracker</h1><button class="refresh" id="refresh">${this.tr("Vernieuwen", "Refresh")}</button></div><div class="tabs">${this.availableTabs().map(([k,l])=>`<button class="tab ${this._tab===k?"active":""}" data-tab="${k}">${l}</button>`).join("")}</div>${content}</div>`;
    this.shadowRoot.querySelectorAll("[data-tab]").forEach(el=>el.addEventListener("click",()=>{this._tab=el.dataset.tab;if(["overview","solar","battery"].includes(this._tab))this.scheduleChartAutoFocus();this.render();if(this._tab==="history"&&!this._history)this.loadHistory();if(this._tab==="costs"&&!this._invoice)this.loadInvoice(this._invoiceView);if(this._tab==="settings"&&this.isAdmin()&&this._accessUsers===null)this.loadPanelAccess();}));
    this.shadowRoot.querySelector("#refresh")?.addEventListener("click",()=>this.loadSummary());
    this.shadowRoot.querySelector("#search")?.addEventListener("click",()=>this.loadHistory());
    this.shadowRoot.querySelectorAll("[data-invoice-view]").forEach(el => el.addEventListener("click", () => { if (el.dataset.invoiceView !== this._invoiceView) this.loadInvoice(el.dataset.invoiceView); }));
    this.shadowRoot.querySelector("#invoicePrev")?.addEventListener("click", () => this.shiftInvoice(-1));
    this.shadowRoot.querySelector("#invoiceNext")?.addEventListener("click", () => this.shiftInvoice(1));
    this.shadowRoot.querySelector("#invoiceNow")?.addEventListener("click", () => this.loadInvoice(this._invoiceView));
    this.shadowRoot.querySelectorAll("[data-invoice-month]").forEach(el => el.addEventListener("click", () => this.loadInvoice("month", el.dataset.invoiceMonth)));
    this.shadowRoot.querySelectorAll("[data-investment]").forEach(el => el.addEventListener("input", () => {
      const key = el.dataset.investment;
      this._investmentDraft[key] = el.value === "" ? 0 : Number(el.value);
      this._investmentStatus = "";
    }));
    this.shadowRoot.querySelector("#saveInvestments")?.addEventListener("click", () => this.saveInvestmentSettings());
    this.shadowRoot.querySelector("#savePanelAccess")?.addEventListener("click", () => this.savePanelAccess());
    this.shadowRoot.querySelector("#fixedEffectiveFrom")?.addEventListener("input", ev => { this._fixedCostDraft.effective_from = ev.target.value; this._fixedCostStatus = ""; });
    this.shadowRoot.querySelectorAll("[data-fixed-field]").forEach(el => el.addEventListener("input", () => { this._fixedCostDraft[el.dataset.fixedField] = el.value === "" ? 0 : Number(el.value); this._fixedCostStatus = ""; }));
    this.shadowRoot.querySelector("#saveFixedCost")?.addEventListener("click", () => this.saveFixedCost());
    this.shadowRoot.querySelector("#cancelFixedCost")?.addEventListener("click", () => this.cancelFixedCostEdit());
    this.shadowRoot.querySelectorAll("[data-fixed-edit]").forEach(el => el.addEventListener("click", () => this.editFixedCost(el.dataset.fixedEdit)));
    this.shadowRoot.querySelectorAll("[data-fixed-delete]").forEach(el => el.addEventListener("click", () => this.deleteFixedCost(el.dataset.fixedDelete)));
    this.shadowRoot.querySelector("#markBatteryEmpty")?.addEventListener("click", () => this.markBatteryEmpty());
    this.bindChartInteractions();
  }
}
if (!customElements.get("energy-cost-tracker-panel")) {
  customElements.define("energy-cost-tracker-panel", EnergyCostTrackerPanel);
}
