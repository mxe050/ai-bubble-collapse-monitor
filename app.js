(function () {
  "use strict";

  var state = {
    data: null,
    manual: loadManual(),
    selectedTicker: "NVDA",
    marketChart: null,
    valuationChart: null,
    nikkeiBottomChart: null,
    ntRatioChart: null,
    moneyStrategistChart: null,
    moneyStrategist: null,
    moneyStrategistRange: window.matchMedia && window.matchMedia("(max-width: 699px)").matches ? "current" : "all",
    marginDebtChart: null,
    marginDebt: null,
    marginDebtRange: window.matchMedia && window.matchMedia("(max-width: 699px)").matches ? "20y" : "all",
    purchasingPowerChart: null,
    snapshotHistoryIndex: null,
    snapshotComparisonDays: null,
    snapshotComparisonPayload: null,
    snapshotComparisonEntry: null,
    globalComparison: null,
    marketSummary: null,
    liveIntelligence: null,
    briefingSort: "latest",
    moneyStrategistIpoDate: "",
    valuations: [],
    companyFilter: "all",
    nikkeiBottom: loadNikkeiBottom(),
    nikkeiBottomInitialized: false,
    sakakibaraFairValue: loadSakakibaraFairValue(),
    sakakibaraInitialized: false,
    nikkeiAiThreeSeries: null,
    nikkeiAiThreeSeriesChart: null,
  };

  var numberOne = new Intl.NumberFormat("ja-JP", { maximumFractionDigits: 1 });
  var numberTwo = new Intl.NumberFormat("ja-JP", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  var numberThree = new Intl.NumberFormat("ja-JP", { minimumFractionDigits: 3, maximumFractionDigits: 3 });
  var numberFour = new Intl.NumberFormat("ja-JP", { minimumFractionDigits: 4, maximumFractionDigits: 4 });
  var nikkeiFormat = new Intl.NumberFormat("ja-JP", { maximumFractionDigits: 0 });
  var moneyFormatters = {};
  var priceFormatters = {};
  var LIVE_SNAPSHOT_REFRESH_INTERVAL_MS = 60000;
  var fullDataLoadInFlight = false;
  var liveSnapshotRefreshInFlight = false;

  var COMPANY_FILTERS = {
    all: { label: "全社", description: "海外AI10社と日本企業16社を、同じFCFストレステストで見比べます。" },
    "overseas-ai": { label: "海外・AI関連", description: "従来の崩壊判定を構成する海外AI関連10社です。崩壊スコアはこの母集団だけで計算します。" },
    "japan-ai": { label: "日本・AI連動", description: "AI、半導体、DX、自動化への投資と、収益・評価が比較的強く連動する日本企業8社です。" },
    "japan-diversified": { label: "日本・分散型", description: "AIを活用しながら、自動車、医療、ゲーム、コンテンツ、空調、消費など複数の実需に支えられる日本企業8社です。" },
  };
  var COMPANY_CATEGORY_ORDER = ["overseas-ai", "japan-ai", "japan-diversified"];

  var NIKKEI_PRESETS = {
    mild: { label: "急落・利益減速", epsCut: 10, targetPe: 18, targetPb: 2.0, historyDrawdown: 35 },
    standard: { label: "標準的な株価崩壊", epsCut: 25, targetPe: 16, targetPb: 1.5, historyDrawdown: 50 },
    severe: { label: "深い信用収縮", epsCut: 40, targetPe: 14, targetPb: 1.0, historyDrawdown: 65 },
  };

  function byId(id) {
    return document.getElementById(id);
  }

  function finite(value) {
    if (value === null || value === undefined || value === "") return null;
    var number = Number(value);
    return Number.isFinite(number) ? number : null;
  }

  function clamp(value, low, high) {
    return Math.min(high, Math.max(low, value));
  }

  function formatPercent(value, signed) {
    if (value === null || value === undefined || !Number.isFinite(Number(value))) return "未確認";
    var number = Number(value);
    var prefix = signed && number > 0 ? "+" : "";
    return prefix + numberOne.format(number) + "%";
  }

  function formatLivePercent(value, signed) {
    if (value === null || value === undefined || !Number.isFinite(Number(value))) return "\u672a\u78ba\u8a8d";
    var number = Number(value);
    var prefix = signed && number > 0 ? "+" : "";
    return prefix + numberTwo.format(number) + "%";
  }

  function formatPctPoints(value, signed) {
    if (value === null || value === undefined || !Number.isFinite(Number(value))) return "未確認";
    var number = Number(value);
    var prefix = signed && number > 0 ? "+" : "";
    return prefix + numberOne.format(number) + "ポイント";
  }

  function formatMoney(value, currency) {
    if (value === null || value === undefined || !Number.isFinite(Number(value))) return "未確認";
    var code = currency || "USD";
    if (!moneyFormatters[code]) {
      moneyFormatters[code] = new Intl.NumberFormat("ja-JP", {
        notation: "compact",
        maximumFractionDigits: 2,
        style: "currency",
        currency: code,
      });
    }
    return moneyFormatters[code].format(Number(value));
  }

  function formatPrice(value, currency) {
    if (value === null || value === undefined || !Number.isFinite(Number(value))) return "算定不可";
    var code = currency || "USD";
    if (!priceFormatters[code]) {
      priceFormatters[code] = new Intl.NumberFormat(code === "JPY" ? "ja-JP" : "en-US", {
        minimumFractionDigits: code === "JPY" ? 0 : 2,
        maximumFractionDigits: code === "JPY" ? 0 : 2,
        style: "currency",
        currency: code,
      });
    }
    return priceFormatters[code].format(Number(value));
  }

  function formatNikkei(value) {
    if (value === null || value === undefined || !Number.isFinite(Number(value))) return "算定不可";
    return nikkeiFormat.format(Number(value)) + "円";
  }

  function formatHistoricalIndex(value, indexName) {
    if (value === null || value === undefined || !Number.isFinite(Number(value))) return "未確認";
    return nikkeiFormat.format(Number(value)) + (indexName === "日経平均" ? "円" : "pt");
  }

  function cssValueClass(value, inverse) {
    if (value === null || value === undefined) return "unknown";
    if (Math.abs(value) < 0.05) return "neutral";
    var good = inverse ? value < 0 : value > 0;
    return good ? "positive" : "negative";
  }

  function escapeHtml(value) {
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function companyCategory(company) {
    return company && company.category ? company.category : "overseas-ai";
  }

  function displayTicker(company) {
    return company && (company.displayTicker || company.ticker) ? (company.displayTicker || company.ticker) : "";
  }

  function chartCompanyLabel(company) {
    if (!company) return "";
    if (company.chartLabel) return company.chartLabel;
    return company.country === "JP" ? company.name : displayTicker(company);
  }

  function visibleCompanies() {
    if (!state.data || !Array.isArray(state.data.companies)) return [];
    if (state.companyFilter === "all") return state.data.companies.slice();
    return state.data.companies.filter(function (company) {
      return companyCategory(company) === state.companyFilter;
    });
  }

  function categoryClass(category) {
    return "category-" + String(category || "overseas-ai").replace(/[^a-z0-9-]/g, "");
  }

  function formatDrawdown(value) {
    var number = finite(value);
    return number === null ? "未確認" : "−" + formatPercent(Math.abs(number), false);
  }

  function formatShortDate(value) {
    if (!value) return "";
    var parts = String(value).split("-");
    return parts.length === 3 ? Number(parts[1]) + "/" + Number(parts[2]) : String(value);
  }

  function safeHttpsUrl(value) {
    if (!value) return "";
    try {
      var base = typeof window !== "undefined" && window.location ? window.location.href : undefined;
      var parsed = new URL(String(value), base);
      return parsed.protocol === "https:" ? parsed.href : "";
    } catch (_error) {
      return "";
    }
  }

  function liveSourceLink(url, label, className) {
    var safeUrl = safeHttpsUrl(url);
    var classes = [className || "", safeUrl ? "" : "live-source-unavailable"].filter(Boolean).join(" ");
    var classAttribute = classes ? " class=\"" + escapeHtml(classes) + "\"" : "";
    if (!safeUrl) {
      return "<span" + classAttribute + " aria-disabled=\"true\">" + escapeHtml(label) + "（リンク未確認）</span>";
    }
    return "<a" + classAttribute + " href=\"" + escapeHtml(safeUrl)
      + "\" target=\"_blank\" rel=\"noopener noreferrer\">" + escapeHtml(label) + "</a>";
  }

  function formatLiveTime(value, prefix) {
    if (!value) return (prefix || "") + "時刻未確認";
    var parsed = new Date(value);
    if (Number.isNaN(parsed.valueOf())) return (prefix || "") + "時刻未確認";
    return (prefix || "") + new Intl.DateTimeFormat("ja-JP", {
      month: "numeric",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      timeZone: "Asia/Tokyo",
    }).format(parsed);
  }

  function formatLiveValue(key, quote) {
    var value = finite(quote && quote.value);
    if (value === null) return "未確認";
    if (key === "USDJPY") return numberThree.format(value) + "円";
    if (key === "US10Y") return numberTwo.format(value) + "%";
    if (key === "VIX") return numberTwo.format(value);
    if ((quote && quote.currency) === "JPY" || key.indexOf("NIKKEI") === 0) return nikkeiFormat.format(value);
    return numberTwo.format(value);
  }

  function formatLiveChange(key, quote) {
    if (!quote || quote.referenceValidationStatus !== "verified") return "基準値を再確認中";
    if (key === "US10Y") {
      var changePoints = finite(quote && quote.changePoints);
      if (changePoints === null) return "\u672a\u78ba\u8a8d";
      var basisPoints = changePoints * 100;
      return (basisPoints > 0 ? "+" : "") + numberOne.format(basisPoints) + "bp";
    }
    return formatLivePercent(finite(quote && quote.changePct), true);
  }

  function premarketDirection(key, change) {
    if (change === null || Math.abs(change) < 0.05) {
      return { tone: "neutral", marker: "→" };
    }
    var contextOnly = key === "USDJPY" || key === "US10Y" || key === "US2Y" || key === "VIX";
    return {
      tone: contextOnly ? "context" : change > 0 ? "up" : "down",
      marker: change > 0 ? "↑" : "↓",
    };
  }

  function liveSparkline(points, stateClass, label) {
    var usable = (points || []).map(function (point) { return finite(point.value); }).filter(function (value) { return value !== null; });
    if (usable.length < 2) return "";
    var min = Math.min.apply(null, usable);
    var max = Math.max.apply(null, usable);
    var span = max - min || 1;
    var coords = usable.map(function (value, index) {
      var x = usable.length === 1 ? 0 : index / (usable.length - 1) * 160;
      var y = 38 - (value - min) / span * 32;
      return x.toFixed(1) + "," + y.toFixed(1);
    }).join(" ");
    return "<svg class=\"live-sparkline " + escapeHtml(stateClass || "neutral")
      + "\" viewBox=\"0 0 160 42\" preserveAspectRatio=\"none\" role=\"img\" aria-label=\""
      + escapeHtml(label || "価格推移") + "\" focusable=\"false\">"
      + "<polyline points=\"" + coords + "\"></polyline></svg>";
  }

  function format2026HighCell(company) {
    var drawdown = finite(company.drawdownFrom2026HighPct);
    if (drawdown === null) return "<span class=\"unknown\">未確認</span>";
    var details = [];
    if (finite(company.peak2026) !== null) details.push(formatPrice(company.peak2026, company.currency));
    if (company.peak2026Date) details.push(formatShortDate(company.peak2026Date));
    return "<strong>" + formatDrawdown(drawdown) + "</strong>"
      + (details.length ? "<span class=\"company-high-detail\">高値 " + escapeHtml(details.join(" / ")) + "</span>" : "");
  }

  function updateCompanyFilterUi() {
    var config = COMPANY_FILTERS[state.companyFilter] || COMPANY_FILTERS.all;
    document.querySelectorAll(".company-filter-button").forEach(function (button) {
      var active = button.dataset.companyFilter === state.companyFilter;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", active ? "true" : "false");
      if (button.dataset.companyFilter === "all" && state.data) {
        button.textContent = "全" + state.data.companies.length + "社";
      }
    });
    if (byId("companyFilterDescription")) byId("companyFilterDescription").textContent = config.description;
    if (byId("companyFilterCount")) byId("companyFilterCount").textContent = visibleCompanies().length + "社を表示";
  }

  function loadManual() {
    try {
      var parsed = JSON.parse(localStorage.getItem("aiBubbleManualV2") || "null");
      return parsed || {
        epsCut: null,
        epsCompanies: null,
        priceDrop: null,
        cancellations: null,
        inventoryGap: null,
      };
    } catch (error) {
      return { epsCut: null, epsCompanies: null, priceDrop: null, cancellations: null, inventoryGap: null };
    }
  }

  function saveManual() {
    localStorage.setItem("aiBubbleManualV2", JSON.stringify(state.manual));
  }

  function loadNikkeiBottom() {
    var empty = {
      scenario: "standard",
      referencePrice: null,
      currentPe: null,
      currentPb: null,
      epsCut: null,
      targetPe: null,
      targetPb: null,
      historyDrawdown: null,
    };
    try {
      var parsed = JSON.parse(localStorage.getItem("aiBubbleNikkeiBottomV4") || "null");
      return parsed ? Object.assign(empty, parsed) : empty;
    } catch (error) {
      return empty;
    }
  }

  function saveNikkeiBottom() {
    localStorage.setItem("aiBubbleNikkeiBottomV4", JSON.stringify(state.nikkeiBottom));
  }

  function loadSakakibaraFairValue() {
    var empty = { eps: null, targetPe: null, bps: null, roePct: null, growthYears: null };
    try {
      var parsed = JSON.parse(localStorage.getItem("aiBubbleSakakibaraFairValueV1") || "null");
      return parsed ? Object.assign(empty, parsed) : empty;
    } catch (error) {
      return empty;
    }
  }

  function saveSakakibaraFairValue() {
    localStorage.setItem("aiBubbleSakakibaraFairValueV1", JSON.stringify(state.sakakibaraFairValue));
  }

  function inputOrNull(id) {
    var raw = byId(id).value.trim();
    return raw === "" ? null : finite(raw);
  }

  function boundedInput(id, minimum, maximum) {
    var value = inputOrNull(id);
    return value === null ? null : clamp(value, minimum, maximum);
  }

  function setManualInputs() {
    var mapping = {
      manualEpsCut: "epsCut",
      manualEpsCompanies: "epsCompanies",
      manualPriceDrop: "priceDrop",
      manualCancellations: "cancellations",
      manualInventoryGap: "inventoryGap",
    };
    Object.keys(mapping).forEach(function (id) {
      var value = state.manual[mapping[id]];
      byId(id).value = value === null || value === undefined ? "" : value;
    });
  }

  function dcfValue(fcf, growthPct, discountPct, terminalPct, years) {
    var cashFlow = finite(fcf);
    var growth = finite(growthPct);
    var discount = finite(discountPct);
    var terminal = finite(terminalPct);
    if (cashFlow === null || cashFlow <= 0 || growth === null || discount === null || terminal === null) return null;
    growth /= 100;
    discount /= 100;
    terminal /= 100;
    if (discount <= terminal || years < 1) return null;
    var present = 0;
    var future = cashFlow;
    for (var year = 1; year <= years; year += 1) {
      future *= 1 + growth;
      present += future / Math.pow(1 + discount, year);
    }
    var terminalValue = future * (1 + terminal) / (discount - terminal);
    present += terminalValue / Math.pow(1 + discount, years);
    return present;
  }

  function companyValuationFcf(company) {
    var adjusted = finite(company.valuationFcf);
    return adjusted === null ? finite(company.ttmFreeCashFlow) : adjusted;
  }

  function reverseDcfGrowth(company, discountPct, terminalPct, years) {
    var market = finite(company.marketCap);
    var fcf = companyValuationFcf(company);
    if (market === null || market <= 0 || fcf === null || fcf <= 0) return null;
    var low = -45;
    var high = 80;
    var lowValue = dcfValue(fcf, low, discountPct, terminalPct, years);
    var highValue = dcfValue(fcf, high, discountPct, terminalPct, years);
    if (lowValue !== null && market < lowValue) return low;
    if (highValue === null || market > highValue) return null;
    for (var count = 0; count < 90; count += 1) {
      var middle = (low + high) / 2;
      var value = dcfValue(fcf, middle, discountPct, terminalPct, years);
      if (value === null) return null;
      if (value < market) low = middle;
      else high = middle;
    }
    return (low + high) / 2;
  }

  function modelCompany(company, overrides) {
    var assumptions = company.assumptions || {};
    var discount = overrides && overrides.discount !== undefined ? overrides.discount : assumptions.discountRatePct;
    var terminal = overrides && overrides.terminal !== undefined ? overrides.terminal : assumptions.terminalGrowthPct;
    var baseGrowth = overrides && overrides.baseGrowth !== undefined ? overrides.baseGrowth : assumptions.baseGrowthPct;
    var years = assumptions.forecastYears || 10;
    var market = finite(company.marketCap);
    var price = finite(company.price);
    var fcf = companyValuationFcf(company);
    var bearGrowth = finite(assumptions.bearGrowthPct);
    var bullGrowth = finite(assumptions.bullGrowthPct);
    var existing = dcfValue(fcf, 0, discount, 0, years);
    var bear = dcfValue(fcf, bearGrowth, discount + 1.5, Math.max(0, terminal - 0.75), years);
    var base = dcfValue(fcf, baseGrowth, discount, terminal, years);
    var bull = dcfValue(fcf, bullGrowth, Math.max(5.5, discount - 0.75), Math.min(4, terminal + 0.25), years);
    var implied = reverseDcfGrowth(company, discount, terminal, years);
    var toPrice = function (value) {
      return value !== null && market && price ? value / market * price : null;
    };
    return {
      ticker: company.ticker,
      company: company,
      market: market,
      valuationFcf: fcf,
      existingValue: existing,
      bearValue: bear,
      baseValue: base,
      bullValue: bull,
      existingPrice: toPrice(existing),
      bearPrice: toPrice(bear),
      basePrice: toPrice(base),
      bullPrice: toPrice(bull),
      premiumPct: market && base !== null ? (market - base) / market * 100 : null,
      baseGapPct: market && base !== null ? (base / market - 1) * 100 : null,
      bearGapPct: market && bear !== null ? (bear / market - 1) * 100 : null,
      bullGapPct: market && bull !== null ? (bull / market - 1) * 100 : null,
      impliedGrowthPct: implied,
      impliedGapPct: implied !== null && baseGrowth !== null ? implied - baseGrowth : null,
      discountPct: discount,
      terminalPct: terminal,
      baseGrowthPct: baseGrowth,
      bearGrowthPct: bearGrowth,
      bullGrowthPct: bullGrowth,
      years: years,
    };
  }

  function median(values) {
    var usable = values.filter(function (value) { return value !== null && value !== undefined && Number.isFinite(Number(value)); })
      .map(Number).sort(function (a, b) { return a - b; });
    if (!usable.length) return null;
    var middle = Math.floor(usable.length / 2);
    return usable.length % 2 ? usable[middle] : (usable[middle - 1] + usable[middle]) / 2;
  }

  function stepScore(value, bands) {
    if (value === null || value === undefined || !Number.isFinite(Number(value))) return null;
    for (var index = 0; index < bands.length; index += 1) {
      if (Number(value) >= bands[index][0]) return bands[index][1];
    }
    return 0;
  }

  function reverseStepScore(value, bands) {
    if (value === null || value === undefined || !Number.isFinite(Number(value))) return null;
    for (var index = 0; index < bands.length; index += 1) {
      if (Number(value) <= bands[index][0]) return bands[index][1];
    }
    return 0;
  }

  function component(value, max, score) {
    return value === null || value === undefined || score === null
      ? { observed: 0, known: 0, unknown: max }
      : { observed: clamp(score, 0, max), known: max, unknown: 0 };
  }

  function combineSignal(id, title, purpose, details, parts, max) {
    var observed = parts.reduce(function (sum, part) { return sum + part.observed; }, 0);
    var known = parts.reduce(function (sum, part) { return sum + part.known; }, 0);
    var unknown = parts.reduce(function (sum, part) { return sum + part.unknown; }, 0);
    var normalized = known ? observed / known : 0;
    var signalState = known < max * 0.5 ? "unknown" : normalized >= 0.65 ? "high" : normalized >= 0.3 ? "medium" : "low";
    return { id: id, title: title, purpose: purpose, details: details, observed: observed, known: known, unknown: unknown, max: max, state: signalState };
  }

  function scoreEvidence() {
    var data = state.data;
    var sox = data.market.series.SOX || {};
    var basket = data.market.aiBasket || {};
    var derived = data.derived || {};
    var hy = data.macro.highYieldOas || {};
    var overseasAiValuations = state.valuations.filter(function (item) {
      return companyCategory(item.company) === "overseas-ai";
    });
    var valuationRows = overseasAiValuations.filter(function (item) {
      return finite(item.premiumPct) !== null && finite(item.impliedGapPct) !== null;
    });
    var valuationPremium = valuationRows.length >= 7
      ? median(valuationRows.map(function (item) { return item.premiumPct; }))
      : null;
    var impliedGap = valuationRows.length >= 7
      ? median(valuationRows.map(function (item) { return item.impliedGapPct; }))
      : null;

    var price = combineSignal(
      "price", "米国の価格レジーム", "米国上場半導体相場について、一日の急落ではなく下落の深さ・持続・広がりを確認します。",
      "SOX下落 " + formatPercent(sox.drawdown3yPct, false) + "、200日線下 " + (finite(sox.weeksBelowSma200) === null ? "未確認" : numberOne.format(sox.weeksBelowSma200) + "週") + "、海外AI10社の200日線割れ " + formatPercent(basket.breadthBelowSma200Pct, false),
      [
        component(sox.drawdown3yPct, 16, stepScore(sox.drawdown3yPct, [[40, 16], [35, 14], [30, 11], [20, 7], [10, 3]])),
        component(sox.weeksBelowSma200, 7, stepScore(sox.weeksBelowSma200, [[8, 7], [6, 6], [4, 4], [1, 2]])),
        component(basket.medianDrawdown3yPct, 4, stepScore(basket.medianDrawdown3yPct, [[45, 4], [30, 3], [20, 2], [10, 1]])),
        component(basket.breadthBelowSma200Pct, 3, stepScore(basket.breadthBelowSma200Pct, [[80, 3], [60, 2], [40, 1]])),
      ], 30
    );

    var valuation = combineSignal(
      "valuation", "評価への脆弱性", "これは崩壊発生の証拠ではありません。市場価格が本サイトの基準FCFシナリオをどれだけ上回るかを示すストレス指標です。",
      "比較可能 " + valuationRows.length + "/10社、基準シナリオ外の部分の中央値 " + formatPercent(valuationPremium, false) + "、暗黙成長と基準成長の差 " + formatPercent(impliedGap, true),
      [
        component(valuationPremium, 12, stepScore(valuationPremium, [[45, 12], [30, 10], [20, 7], [10, 4], [0, 1]])),
        component(impliedGap, 8, stepScore(impliedGap, [[12, 8], [8, 6], [5, 4], [2, 2]])),
      ], 20
    );

    var revenueCoverage = finite(derived.latestQuarterRevenueGrowthCoverage);
    var fcfCoverage = finite(derived.fcfDeteriorationCoverage);
    var capexCoverage = finite(derived.hyperscalerCapexCoverage);
    var revenueGrowth = revenueCoverage !== null && revenueCoverage >= 7
      ? finite(derived.medianLatestQuarterRevenueGrowthYoYPct) : null;
    var fcfBreadth = fcfCoverage !== null && fcfCoverage >= 7
      ? finite(derived.fcfDeteriorationBreadthPct) : null;
    var capexCuts = capexCoverage === 4 ? finite(derived.hyperscalersWithCapexCuts) : null;
    var epsEvidence = state.manual.epsCut;
    var epsScore = epsEvidence === null ? null : stepScore(epsEvidence, [[20, 7], [15, 6], [10, 4], [5, 2]]);
    if (epsScore !== null && state.manual.epsCompanies !== null && state.manual.epsCompanies >= 4) epsScore = Math.min(7, epsScore + 1);
    var fundamentals = combineSignal(
      "fundamentals", "基礎収益・顧客投資", "最新四半期を前年同期と比較し、売上・FCF・ハイパースケーラー設備投資が広く悪化したかを確認します。",
      "売上中央値 " + formatPercent(revenueGrowth, true) + "（" + (revenueCoverage === null ? "0" : revenueCoverage) + "/10社）、FCFが20%以上悪化 " + (finite(derived.fcfDeteriorationCount) === null ? "未確認" : derived.fcfDeteriorationCount + "/" + fcfCoverage + "社") + "、CapExを10%以上削減 " + (capexCuts === null ? "未確認" : capexCuts + "/4社") + "、予想EPS修正 " + formatPercent(state.manual.epsCut === null ? null : -state.manual.epsCut, true),
      [
        component(revenueGrowth, 7, reverseStepScore(revenueGrowth, [[-10, 7], [0, 5], [5, 2]])),
        component(fcfBreadth, 6, stepScore(fcfBreadth, [[70, 6], [50, 4], [30, 2]])),
        component(capexCuts, 5, stepScore(capexCuts, [[2, 5], [1, 3]])),
        component(epsEvidence, 7, epsScore),
      ], 25
    );

    var capitalCycle = combineSignal(
      "capital", "資本循環・供給", "過剰投資が製品価格低下、在庫増加、計画中止へ変わったかを確認します。",
      "製品価格低下 " + formatPercent(state.manual.priceDrop, false) + "、計画中止 " + (state.manual.cancellations === null ? "未確認" : state.manual.cancellations + "件") + "、在庫乖離 " + formatPercent(state.manual.inventoryGap, false),
      [
        component(state.manual.priceDrop, 7, stepScore(state.manual.priceDrop, [[25, 7], [20, 6], [10, 3], [5, 1]])),
        component(state.manual.cancellations, 4, stepScore(state.manual.cancellations, [[5, 4], [2, 2], [1, 1]])),
        component(state.manual.inventoryGap, 4, stepScore(state.manual.inventoryGap, [[25, 4], [20, 3], [10, 2], [5, 1]])),
      ], 15
    );

    var oasValue = finite(hy.valuePct);
    var oasRise = finite(hy.riseFrom3mLowPctPoints);
    var credit = combineSignal(
      "credit", "米国信用・資金調達", "米国AI投資の失敗が、米国ハイイールド社債の資金調達条件へ波及したかを確認します。",
      "米国HY OAS " + (oasValue === null ? "未確認" : numberOne.format(oasValue * 100) + "bp") + "、3か月低値から " + (oasRise === null ? "未確認" : "+" + numberOne.format(oasRise * 100) + "bp"),
      [
        component(oasValue, 7, stepScore(oasValue, [[6, 7], [5, 6], [4, 3], [3.5, 1]])),
        component(oasRise, 3, stepScore(oasRise, [[2, 3], [1, 2], [0.5, 1]])),
      ], 10
    );

    var signals = [price, valuation, fundamentals, capitalCycle, credit];
    var confirmationSignals = [price, fundamentals, capitalCycle, credit];
    var observed = confirmationSignals.reduce(function (sum, signal) { return sum + signal.observed; }, 0);
    var known = confirmationSignals.reduce(function (sum, signal) { return sum + signal.known; }, 0);
    var unknown = confirmationSignals.reduce(function (sum, signal) { return sum + signal.unknown; }, 0);
    return {
      signals: signals,
      observed: Math.round(observed),
      known: known,
      unknown: unknown,
      coverage: Math.round(known / 80 * 100),
      maxPossible: Math.round(observed + unknown),
      confirmationMax: 80,
      valuationObserved: Math.round(valuation.observed),
      valuationKnown: valuation.known,
      valuationPremium: valuationPremium,
      impliedGap: impliedGap,
    };
  }

  function triState(anyTrue, allKnown) {
    return anyTrue ? "true" : allKnown ? "false" : "unknown";
  }

  function assessGates(evidence) {
    var data = state.data;
    var sox = data.market.series.SOX || {};
    var priceKnown = finite(sox.drawdown3yPct) !== null && finite(sox.weeksBelowSma200) !== null;
    var gateA = priceKnown
      ? (sox.drawdown3yPct >= 35 && sox.weeksBelowSma200 >= 6 ? "true" : "false")
      : "unknown";

    var derived = data.derived || {};
    var revenueCoverage = finite(derived.latestQuarterRevenueGrowthCoverage);
    var fcfCoverage = finite(derived.fcfDeteriorationCoverage);
    var capexCoverage = finite(derived.hyperscalerCapexCoverage);
    var revenueGrowth = revenueCoverage !== null && revenueCoverage >= 7
      ? finite(derived.medianLatestQuarterRevenueGrowthYoYPct) : null;
    var fcfBreadth = fcfCoverage !== null && fcfCoverage >= 7
      ? finite(derived.fcfDeteriorationBreadthPct) : null;
    var capexCuts = capexCoverage === 4 ? finite(derived.hyperscalersWithCapexCuts) : null;
    var epsKnown = state.manual.epsCut !== null;
    var fundamentalTrue = (epsKnown && state.manual.epsCut >= 15)
      || (revenueGrowth !== null && revenueGrowth <= -5)
      || (fcfBreadth !== null && fcfBreadth >= 50)
      || (capexCuts !== null && capexCuts >= 2);
    var gateB = triState(
      fundamentalTrue,
      epsKnown && revenueGrowth !== null && fcfBreadth !== null && capexCuts !== null
    );

    var hy = data.macro.highYieldOas || {};
    var oas = finite(hy.valuePct);
    var rise = finite(hy.riseFrom3mLowPctPoints);
    var manualKnown = state.manual.priceDrop !== null && state.manual.cancellations !== null && state.manual.inventoryGap !== null;
    var transmissionTrue = (state.manual.priceDrop !== null && state.manual.priceDrop >= 20)
      || (state.manual.cancellations !== null && state.manual.cancellations >= 5)
      || (state.manual.inventoryGap !== null && state.manual.inventoryGap >= 20)
      || (oas !== null && oas >= 5)
      || (rise !== null && rise >= 2);
    var gateC = triState(transmissionTrue, manualKnown && oas !== null && rise !== null);

    var collapseName;
    var collapseReason;
    if (gateA === "true" && gateB === "true" && gateC === "true" && evidence.observed >= 45) {
      collapseName = "米国AI相場の崩壊を確認";
      collapseReason = "米国上場半導体の価格、利益仮説、供給・信用の3ゲートがそろい、崩壊確認証拠も45/80点以上です。日本への波及は別に判定します。";
    } else if (gateA === "true" && (gateB === "true" || gateC === "true")) {
      collapseName = "米国AI相場で崩壊進行の可能性";
      collapseReason = "米国上場半導体の長期トレンド転換に、利益または供給・信用の悪化が重なっています。日本への波及は別に確認します。";
    } else if ((finite(sox.drawdown3yPct) !== null && sox.drawdown3yPct >= 20) || evidence.observed >= 20) {
      collapseName = "米国AI相場の調整・再評価";
      collapseReason = "米国側の価格または複数指標に警戒信号がありますが、3ゲートはそろっていません。";
    } else {
      collapseName = "米国AI相場の崩壊は未確認";
      collapseReason = "高評価の可能性はあっても、米国側の価格・利益・供給・信用の連鎖はまだ確認できません。";
    }
    return { A: gateA, B: gateB, C: gateC, collapseName: collapseName, collapseReason: collapseReason };
  }

  function assessBubble(evidence) {
    var premium = evidence.valuationPremium;
    var gap = evidence.impliedGap;
    if (premium === null && gap === null) {
      return { name: "企業価値を算定できず", reason: "正のFCFまたは時価総額データが不足しています。" };
    }
    if ((premium !== null && premium >= 25) && (gap !== null && gap >= 5)) {
      return { name: "基準DCFとの差が大きい", reason: "現在のFCFと基準前提だけでは市場価格を十分に説明できず、市場はより高い成長または別の価値要因を織り込んでいます。" };
    }
    if ((premium !== null && premium >= 10) || (gap !== null && gap >= 2)) {
      return { name: "割高リスクあり", reason: "実体ある利益に加え、長い競争優位と高成長の継続が価格に含まれています。" };
    }
    return { name: "基準シナリオ内", reason: "本モデルでは、現在のFCFと基準成長で価格の多くを説明できます。" };
  }

  function assessJapanTransmission() {
    var market = state.data.market || {};
    var sox = market.series.SOX || {};
    var nikkei = market.series.NIKKEI || {};
    var japan = market.japanAiBasket || {};
    var soxDrawdown = finite(sox.drawdown3yPct);
    var soxFiveDay = finite(sox.change5dPct);
    var usKnown = soxDrawdown !== null || soxFiveDay !== null;
    var usStress = (soxDrawdown !== null && soxDrawdown >= 20)
      || (soxFiveDay !== null && soxFiveDay <= -8);

    var shortSignals = [
      finite(nikkei.change5dPct) !== null && nikkei.change5dPct <= -5,
      finite(japan.medianChange5dPct) !== null && japan.medianChange5dPct <= -5,
    ];
    var structuralChecks = [
      finite(nikkei.drawdown3yPct) === null ? null : nikkei.drawdown3yPct >= 20,
      finite(nikkei.weeksBelowSma200) === null ? null : nikkei.weeksBelowSma200 >= 4,
      finite(japan.medianDrawdown3yPct) === null ? null : japan.medianDrawdown3yPct >= 25,
      finite(japan.breadthBelowSma200Pct) === null ? null : japan.breadthBelowSma200Pct >= 60,
    ];
    var shortCount = shortSignals.filter(Boolean).length;
    var structuralKnown = structuralChecks.filter(function (value) { return value !== null; }).length;
    var structuralCount = structuralChecks.filter(Boolean).length;
    var status;
    var reason;
    var level;
    if (!usKnown) {
      status = "判定不能";
      reason = "SOXの下落率を取得できないため、米国起点の波及を判定できません。";
      level = "unknown";
    } else if (!usStress) {
      status = "米国起点のストレスは未確認";
      reason = "SOXが3年高値から20%以上下落、または5日で8%以上下落という本サイトの先行警報に達していません。";
      level = "low";
    } else if (structuralCount >= 2) {
      status = "日本への持続的な市場波及を確認";
      reason = "米国側の先行警報に加え、日経平均と日本AI・半導体連動8社で、深い下落・200日線割れ・下落の広がりのうち複数を確認しました。";
      level = "high";
    } else if (shortCount >= 1 || structuralCount >= 1) {
      status = "短期波及あり、持続的な崩壊は未確認";
      reason = "米国側の先行警報と日本株の短期下落は重なっていますが、日本側の長期トレンド転換条件は" + structuralCount + "/" + structuralKnown + "項目にとどまります。";
      level = "medium";
    } else {
      status = "日本への波及は未確認";
      reason = "米国側にストレスはありますが、日本株の短期下落や長期トレンド転換は確認できません。米国下落から日本下落への機械的な連動は仮定しません。";
      level = "low";
    }
    return {
      status: status,
      reason: reason,
      level: level,
      soxDrawdown: soxDrawdown,
      nikkeiDrawdown: finite(nikkei.drawdown3yPct),
      japanDrawdown: finite(japan.medianDrawdown3yPct),
      japanBreadth: finite(japan.breadthBelowSma200Pct),
      structuralCount: structuralCount,
      structuralKnown: structuralKnown,
    };
  }

  function renderJapanTransmission(transmission) {
    var status = byId("japanTransmissionStatus");
    if (!status) return;
    status.textContent = transmission.status;
    status.dataset.state = transmission.level;
    byId("japanTransmissionReason").textContent = transmission.reason;
    byId("transmissionSoxDrawdown").textContent = formatPercent(transmission.soxDrawdown, false);
    byId("transmissionNikkeiDrawdown").textContent = formatPercent(transmission.nikkeiDrawdown, false);
    byId("transmissionJapanAiDrawdown").textContent = formatPercent(transmission.japanDrawdown, false);
    byId("transmissionJapanBreadth").textContent = formatPercent(transmission.japanBreadth, false);
  }

  function renderDailySummary(evidence, gates, bubble, transmission) {
    var list = byId("dailySummaryList");
    var lead = byId("dailySummaryLead");
    if (!list || !lead) return;
    var market = state.data.market || {};
    var series = market.series || {};
    var usRisk = market.usBubbleRisk || {};
    var sakakibara = market.sakakibaraAnalysis || {};
    var marketPath = sakakibara.marketPath || {};
    var kioxia = sakakibara.kioxiaCase || {};
    var calm = kioxia.calmValuation || {};
    var liveKioxia = liveQuoteForKey("KIOXIA");
    var kioxiaCurrent = finite(liveKioxia ? liveKioxia.value : kioxia.close);
    var kioxiaPriceLabel = liveKioxia ? "ライブ価格" : "最新終値";
    var macro = state.data.macro || {};
    var highYield = macro.highYieldOas || {};
    var financial = macro.financialConditions || {};
    var marginLatest = (state.marginDebt || {}).latest || {};
    var globalModels = (state.globalComparison || {}).theoreticalModels || {};
    var spModel = globalModels.sp500 || {};
    var nikkeiModel = globalModels.nikkei225 || {};
    var sp500 = series.SP500 || {};
    var sox = series.SOX || {};
    var nikkei = series.NIKKEI || {};
    var vix = series.VIX || {};
    var aiBasket = market.aiBasket || {};
    var revenueGrowth = finite((state.data.derived || {}).medianLatestQuarterRevenueGrowthYoYPct);
    var fcfDeterioration = finite((state.data.derived || {}).fcfDeteriorationBreadthPct);
    var vixLevel = finite(vix.close);
    var oasLevel = finite(highYield.valuePct);
    var nfciLevel = finite(financial.value);
    var fundamentalStress = (revenueGrowth !== null && revenueGrowth <= 0) || (fcfDeterioration !== null && fcfDeterioration >= 60);
    var creditPanic = (vixLevel !== null && vixLevel >= 40) || (oasLevel !== null && oasLevel >= 5) || (nfciLevel !== null && nfciLevel >= 0.5);
    var systemicPanic = gates.collapseName === "米国AI相場の崩壊を確認" || finite(usRisk.score) >= 60 || creditPanic;
    var leadConclusion = systemicPanic
      ? "価格、企業実体、信用市場へ悪化が広がっており、市場全体の崩壊を強く警戒する段階です。"
      : "AI・半導体の評価上乗せは大きく、同分野の価格調整と日本の集中解消は進んでいます。一方、米国の広範な企業業績と信用市場まで同時に崩れた状態は確認できず、現状は「バブル的な期待は残るが、市場全体のパニック崩壊は未確認」です。";
    lead.textContent = (state.data.marketDate || "基準日未確認") + "時点。" + leadConclusion;

    var spRiskText = finite(usRisk.score) === null
      ? "崩壊進行度は未確認です。"
      : "崩壊進行度は" + numberOne.format(usRisk.score) + "/100で「" + (usRisk.stageLabel || "段階未確認") + "」。S&P 500は3年高値から" + formatPercent(sp500.drawdown3yPct, false) + "下です。";
    var fairText = (spModel.latest && nikkeiModel.latest)
      ? "5年平準化利益モデルに対する上乗せは、S&P 500が" + formatPercent(spModel.latest.marketPremiumPct, true) + "、日経平均が" + formatPercent(nikkeiModel.latest.marketPremiumPct, true) + "です。モデル前提で変わる比較値です。"
      : "理論価値モデルの最新値は未確認です。";
    var kioxiaText = finite(calm.referencePriceJpy) === null
      ? "直近2決算による冷静な評価基準は未確認です。"
      : "キオクシアは" + kioxiaPriceLabel + formatPrice(kioxiaCurrent, "JPY") + "に対し、直近2決算だけを使う中心値は" + formatPrice(calm.referencePriceJpy, "JPY") + "、感度幅は" + formatPrice(calm.sensitivityLowPriceJpy, "JPY") + "～" + formatPrice(calm.sensitivityHighPriceJpy, "JPY") + "です。売買目標ではありません。";
    var livePackage = state.liveIntelligence || {};
    var livePremarket = livePackage.premarket || {};
    var liveQuotes = livePremarket.quotes || {};
    var livePrimaryKey = livePremarket.primaryNikkeiFutureKey;
    var livePrimary = livePrimaryKey ? (liveQuotes[livePrimaryKey] || {}) : {};
    var liveShock = livePackage.marketShock || {};
    var premarketText = livePrimaryKey
      ? (livePrimary.shortLabel || "日経先物") + "は" + formatLiveValue(livePrimaryKey, livePrimary)
        + "、現物終値との差は" + formatPercent(finite(livePremarket.nikkeiFutureCashGapPct), true)
        + "。米国4指数先物の単純平均は" + formatPercent(finite(livePremarket.usFuturesAverageChangePct), true)
        + "、USD/JPYは" + (finite(liveShock.current) === null ? "未確認" : numberThree.format(liveShock.current) + "円")
        + "です。"
        + (liveShock.severity === "critical" || liveShock.severity === "warning"
          ? "為替急変を検知していますが、介入確認状態は「" + (liveShock.interventionLabel || "確認中") + "」です。"
          : "")
        + "先物差を予想始値や売買指示とは扱いません。"
      : "日経先物・米国先物・ドル円・米金利・VIXの速報を取得できませんでした。各カードの時刻を確認してください。";
    var items = [
      { label: "総合判定", text: bubble.name + "。" + gates.collapseName + "。高評価と崩壊確認は別々に判定しています。" },
      { label: "米国市場全体", text: spRiskText },
      { label: "半導体・AI株", text: "SOXは高値から" + formatPercent(sox.drawdown3yPct, false) + "下落。海外AI 10社の最大下落率中央値は" + formatPercent(aiBasket.medianDrawdown3yPct, false) + "、200日線割れは" + formatPercent(aiBasket.breadthBelowSma200Pct, false) + "です。" },
      { label: "企業の実体", text: "監視AI企業の売上成長率中央値は" + formatPercent(revenueGrowth, true) + "、FCF悪化企業は" + formatPercent(fcfDeterioration, false) + "です。" + (fundamentalStress ? "企業実体にも悪化が広がっているため、価格だけの調整とはみなしません。" : "現時点では、価格下落が監視企業全体の業績崩壊へ広がったとはまだ言えません。") },
      { label: "恐怖・信用市場", text: "VIXは" + (vixLevel === null ? "未確認" : numberOne.format(vixLevel)) + "、米国HY OASは" + formatPercent(oasLevel, false) + "、NFCIは" + (nfciLevel === null ? "未確認" : numberTwo.format(nfciLevel)) + "です。" + (creditPanic ? "少なくとも1指標が警戒線に達しており、信用収縮を伴うパニックを警戒します。" : "3指標を合わせると、信用収縮を伴うパニックは未確認です。") },
      { label: "強制売りの燃料", text: "信用買い残÷GDPは" + formatPercent(marginLatest.marginDebtToGdpPct, false) + "、2010年以降の" + (finite(marginLatest.ratioPercentileSince2010Pct) === null ? "順位未確認" : numberOne.format(marginLatest.ratioPercentileSince2010Pct) + "パーセンタイル") + "です。燃料の多さは警戒材料ですが、暴落開始の証明ではありません。" },
      { label: "日本への波及", text: "日経平均は2026年高値から" + formatPercent(nikkei.drawdownFrom2026HighPct, false) + "下落。波及判定は「" + transmission.status + "」で、米国AI株だけの調整と日本全体の崩れを分けて見ています。" },
      { label: "集中相場の揺り戻し", text: "NT倍率は直近ピークから" + formatPercent((sakakibara.ntRatio || {}).declineFromPeakPct, false) + "低下し、確認条件は" + (sakakibara.confirmationCount || 0) + "/" + (sakakibara.confirmationMax || 4) + "。現在の経路判定は「" + (marketPath.label || "未判定") + "」です。" },
      { label: "市場価格と実体価値", text: fairText },
      { label: "個別例・キオクシア", text: kioxiaText },
      { label: "朝方・先物", text: premarketText },
    ];
    list.innerHTML = items.map(function (item) {
      return "<li><strong>" + escapeHtml(item.label) + "</strong><span>" + escapeHtml(item.text) + "</span></li>";
    }).join("");
  }

  function renderTop(evidence, gates, bubble) {
    byId("bubbleRegime").textContent = bubble.name;
    byId("bubbleReason").textContent = bubble.reason;
    byId("collapseRegime").textContent = gates.collapseName;
    byId("collapseReason").textContent = gates.collapseReason;
    byId("evidenceScore").textContent = evidence.observed;
    byId("coverageValue").textContent = evidence.coverage;
    byId("scoreRange").textContent = evidence.unknown
      ? "未確認項目をすべて悪化と仮定した上限 " + evidence.maxPossible + "/80点"
      : "崩壊確認80点分を確認済み";
    byId("coverageReason").textContent = evidence.unknown
      ? "残り" + evidence.unknown + "点分は未確認"
      : "崩壊確認項目の欠損なし";

    var plain;
    if (gates.collapseName === "米国AI相場の崩壊を確認") {
      plain = "米国AI・半導体相場では、割高修正だけでなく将来利益と供給・信用への波及を伴う崩壊条件がそろっています。日本への波及は別判定です。";
    } else if (bubble.name === "基準DCFとの差が大きい") {
      plain = "価格には強い期待またはモデル外の企業価値が含まれます。ただし『基準DCFより高い』ことと『相場が崩壊した』ことは同じではありません。";
    } else {
      plain = "一部の株価下落だけでは崩壊とは言えません。米国側の価格・企業業績・設備投資・信用と、日本への波及を分けて追います。";
    }
    byId("headlineConclusion").textContent = plain;
    byId("uncertaintySummary").textContent = evidence.unknown
      ? "特に予想EPS、製品価格、在庫、正式な計画中止が未確認です。評価への脆弱性20点は、崩壊確認80点には加算していません。"
      : "崩壊確認の主要入力はそろっています。ただし、評価への脆弱性20点とモデル不確実性は別に残ります。";
  }

  function renderSignals(evidence) {
    byId("signalGrid").innerHTML = evidence.signals.map(function (signal, index) {
      var percent = signal.known ? signal.observed / signal.max * 100 : 0;
      var label = signal.state === "high" ? "強い警戒" : signal.state === "medium" ? "警戒" : signal.state === "low" ? "低い" : "未確認が多い";
      return "<article class=\"signal-card\" data-state=\"" + signal.state + "\">"
        + "<div class=\"signal-top\"><span>0" + (index + 1) + " / " + signal.max + "点</span><span class=\"signal-score\">" + signal.observed + "点・" + label + "</span></div>"
        + "<h3>" + escapeHtml(signal.title) + "</h3>"
        + "<p>" + escapeHtml(signal.purpose) + "</p>"
        + "<div class=\"meter\" aria-label=\"" + signal.max + "点中" + signal.observed + "点\"><span style=\"width:" + clamp(percent, 0, 100) + "%\"></span></div>"
        + "<div class=\"signal-detail\">" + escapeHtml(signal.details) + (signal.unknown ? "<br><span class=\"unknown\">未確認 " + signal.unknown + "点分</span>" : "") + "</div>"
        + "</article>";
    }).join("");
  }

  function renderGate(id, value) {
    var element = byId(id);
    element.classList.remove("is-true", "is-false", "is-unknown");
    element.classList.add("is-" + value);
    var result = element.querySelector(".gate-result");
    result.textContent = value === "true" ? "充足：悪化を確認" : value === "false" ? "未充足：条件に達していない" : "未確認：必要データが不足";
  }

  function renderGates(gates) {
    renderGate("gatePrice", gates.A);
    renderGate("gateFundamental", gates.B);
    renderGate("gateTransmission", gates.C);
  }

  function renderMarketReading() {
    var sox = state.data.market.series.SOX || {};
    var basket = state.data.market.aiBasket || {};
    var items = [
      "SOXは米国市場に上場する半導体30社の指数です。企業の本拠地に地理的制限はありませんが、日本株指数ではありません。",
      "SOXは3年高値から" + formatPercent(sox.drawdown3yPct, false) + "。米国価格ゲートの35%には" + (sox.drawdown3yPct >= 35 ? "達しています。" : "達していません。"),
      "SOXが200日線を下回った期間は約" + (finite(sox.weeksBelowSma200) === null ? "未確認" : numberOne.format(sox.weeksBelowSma200) + "週") + "。一時的な下落か、米国上場半導体の長期トレンド転換かを区別します。",
      "海外AI10社のうち200日線を下回る割合は" + formatPercent(basket.breadthBelowSma200Pct, false) + "。指数だけでなく米国上場銘柄群への広がりを示します。",
      "日本への波及は、上の専用章で日経平均と日本AI・半導体連動8社を使って別判定します。",
    ];
    byId("marketReading").innerHTML = items.map(function (item) { return "<li>" + escapeHtml(item) + "</li>"; }).join("");
  }

  function chartTextColor() {
    return getComputedStyle(document.documentElement).getPropertyValue("--muted").trim() || "#647386";
  }

  function formatMarginDebt(value) {
    var number = finite(value);
    return number === null ? "未確認" : "$" + numberTwo.format(number / 1000000) + "兆";
  }

  function formatMonthJa(value) {
    if (!value) return "未確認";
    var parts = String(value).split("-").map(Number);
    return parts.length >= 2 && Number.isFinite(parts[0]) && Number.isFinite(parts[1])
      ? parts[0] + "年" + parts[1] + "月"
      : String(value);
  }

  function marginDebtRangeBounds() {
    var data = state.marginDebt || {};
    var series = data.series || [];
    var latestX = decimalYearFromIso(((data.latest || {}).date)) || new Date().getFullYear();
    var firstX = series.length ? decimalYearFromIso(series[0].date) : 1959;
    var years = { "30y": 30, "20y": 20, "10y": 10, "5y": 5 };
    if (state.marginDebtRange === "all" || !years[state.marginDebtRange]) {
      return { min: firstX - 0.3, max: latestX + 0.8 };
    }
    return { min: latestX - years[state.marginDebtRange], max: latestX + 0.35 };
  }

  function renderMarginDebtRangeUi() {
    document.querySelectorAll(".margin-range-button").forEach(function (button) {
      var active = button.dataset.marginRange === state.marginDebtRange;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", active ? "true" : "false");
    });
  }

  function assessMarginDebtChain() {
    var latest = (state.marginDebt || {}).latest || {};
    var derived = (state.data || {}).derived || {};
    var market = (state.data || {}).market || {};
    var series = market.series || {};
    var hy = ((state.data || {}).macro || {}).highYieldOas || {};
    var percentile = finite(latest.ratioPercentileSince2010Pct);
    var debtYoy = finite(latest.marginDebtChange12mPct);
    var debt1m = finite(latest.marginDebtChange1mPct);
    var debt3m = finite(latest.marginDebtChange3mPct);

    var fuelLevel = percentile !== null && percentile >= 95 && debtYoy !== null && debtYoy >= 20
      ? "high" : percentile !== null && percentile >= 80 ? "medium" : "low";
    var fuelLabel = fuelLevel === "high" ? "強制売りの燃料は非常に多い"
      : fuelLevel === "medium" ? "借入ポジションは多い" : "歴史的な極端さは未確認";

    var capexCoverage = finite(derived.hyperscalerCapexCoverage);
    var capexCuts = capexCoverage === 4 ? finite(derived.hyperscalersWithCapexCuts) : null;
    var revenueCoverage = finite(derived.latestQuarterRevenueGrowthCoverage);
    var revenueGrowth = revenueCoverage !== null && revenueCoverage >= 7
      ? finite(derived.medianLatestQuarterRevenueGrowthYoYPct) : null;
    var fcfCoverage = finite(derived.fcfDeteriorationCoverage);
    var fcfBreadth = fcfCoverage !== null && fcfCoverage >= 7
      ? finite(derived.fcfDeteriorationBreadthPct) : null;
    var triggerCount = [
      capexCuts !== null && capexCuts >= 2,
      revenueGrowth !== null && revenueGrowth <= 0,
      fcfBreadth !== null && fcfBreadth >= 50,
    ].filter(Boolean).length;
    var triggerKnown = [capexCuts, revenueGrowth, fcfBreadth].filter(function (value) { return value !== null; }).length;
    var triggerLevel = triggerCount >= 2 ? "high" : triggerCount === 1 ? "medium" : triggerKnown < 2 ? "unknown" : "low";
    var triggerLabel = triggerLevel === "high" ? "事業面の引き金を複数確認"
      : triggerLevel === "medium" ? "事業面に一つの変調"
        : triggerLevel === "unknown" ? "事業面の確認不足" : "設備投資・需要の同時悪化は未確認";

    var sox = series.SOX || {};
    var vix = series.VIX || {};
    var marketStressCount = [
      finite(sox.change5dPct) !== null && sox.change5dPct <= -8,
      finite(vix.close) !== null && vix.close >= 30,
      finite(hy.valuePct) !== null && hy.valuePct >= 5,
    ].filter(Boolean).length;
    var debtContraction = (debt1m !== null && debt1m <= -5) || (debt3m !== null && debt3m <= -10);
    var unwindLevel = debtContraction && marketStressCount >= 2 ? "high"
      : debtContraction || marketStressCount >= 2 ? "medium" : "low";
    var unwindLabel = unwindLevel === "high" ? "強制売り連鎖を疑う"
      : unwindLevel === "medium" ? "巻き戻しの初期警戒" : "信用買い残の巻き戻しは未確認";

    var overall;
    if (unwindLevel === "high") overall = "レバレッジの巻き戻しと市場横断ストレスが重なっています";
    else if (triggerLevel === "high") overall = "燃料は多く、事業面の引き金も増えています";
    else if (fuelLevel === "high") overall = "燃料は多いが、強制売りの連鎖はまだ確認できません";
    else overall = "レバレッジは監視対象ですが、崩壊の連鎖は未確認です";

    return {
      fuelLevel: fuelLevel,
      fuelLabel: fuelLabel,
      fuelDetail: "2010年2月以降の比率順位 " + formatPercent(percentile, false)
        + "、信用買い残の前年比 " + formatPercent(debtYoy, true) + "。高水準は売りの開始時期を示しません。",
      triggerLevel: triggerLevel,
      triggerLabel: triggerLabel,
      triggerDetail: "CapExを10%以上削減 " + (capexCuts === null ? "未確認" : capexCuts + "/4社")
        + "、売上中央値 " + formatPercent(revenueGrowth, true)
        + "、FCFが20%以上悪化した比率 " + formatPercent(fcfBreadth, false) + "。",
      unwindLevel: unwindLevel,
      unwindLabel: unwindLabel,
      unwindDetail: "信用買い残は前月比 " + formatPercent(debt1m, true)
        + "、3か月比 " + formatPercent(debt3m, true)
        + "。SOX急落・VIX 30以上・OAS 5%以上の該当は " + marketStressCount + "/3項目です。",
      overall: overall,
    };
  }

  function renderMarginDebtChart() {
    var data = state.marginDebt;
    var canvas = byId("marginDebtChart");
    if (!data || !canvas || typeof Chart === "undefined") return;
    if (state.marginDebtChart) state.marginDebtChart.destroy();
    var bounds = marginDebtRangeBounds();
    var rows = (data.series || []).filter(function (row) {
      var x = decimalYearFromIso(row.date);
      return x !== null && x >= bounds.min - 0.2 && x <= bounds.max + 0.2;
    });
    var events = (data.events || []).filter(function (event) {
      var x = decimalYearFromIso(event.date);
      return x !== null && x >= bounds.min && x <= bounds.max;
    });
    var points = rows.map(function (row) {
      return { x: decimalYearFromIso(row.date), y: row.marginDebtToGdpPct, row: row };
    });
    var annotationPlugin = {
      id: "marginDebtAnnotations",
      beforeDatasetsDraw: function (chart) {
        var latestX = decimalYearFromIso((data.latest || {}).date);
        if (latestX === null || latestX < bounds.min || latestX > bounds.max) return;
        var ctx = chart.ctx;
        var xScale = chart.scales.x;
        var area = chart.chartArea;
        var startX = xScale.getPixelForValue(Math.max(bounds.min, latestX - 0.95));
        ctx.save();
        ctx.fillStyle = "rgba(201, 45, 49, 0.11)";
        ctx.fillRect(startX, area.top, area.right - startX, area.bottom - area.top);
        ctx.restore();
      },
      afterDatasetsDraw: function (chart) {
        var ctx = chart.ctx;
        var xScale = chart.scales.x;
        var yScale = chart.scales.y;
        var compact = chart.width < 720;
        ctx.save();
        ctx.textAlign = "center";
        ctx.textBaseline = "bottom";
        ctx.font = (compact ? "700 10px " : "700 11px ") + "Meiryo, sans-serif";
        var labeledEvents = events.filter(function (event) {
          if (!compact || events.length <= 5) return true;
          return /1987|2000|2007|2021/.test(event.date) || event.date === (data.latest || {}).date;
        });
        labeledEvents.forEach(function (event, index) {
          var x = xScale.getPixelForValue(decimalYearFromIso(event.date));
          var y = yScale.getPixelForValue(event.marginDebtToGdpPct);
          var labelY = chart.chartArea.top + 30 + (index % 3) * (compact ? 42 : 46);
          var lines = String(event.chartLabel || event.label).split("|");
          var labelX = Math.max(chart.chartArea.left + 48, Math.min(chart.chartArea.right - 48, x));
          var lineHeight = compact ? 12 : 14;
          var boxWidth = Math.min(compact ? 104 : 142, Math.max.apply(null, lines.map(function (line) {
            return ctx.measureText(line).width;
          })) + 14);
          var boxHeight = lines.length * lineHeight + 8;
          var isLatest = event.date === (data.latest || {}).date;
          ctx.strokeStyle = isLatest ? "#c92d31" : "rgba(75, 94, 111, 0.78)";
          ctx.lineWidth = isLatest ? 2 : 1;
          ctx.beginPath();
          ctx.moveTo(labelX, labelY + boxHeight / 2);
          ctx.lineTo(x, y - 7);
          ctx.stroke();
          ctx.fillStyle = "rgba(255, 255, 255, 0.94)";
          ctx.fillRect(labelX - boxWidth / 2, labelY - boxHeight / 2, boxWidth, boxHeight);
          ctx.strokeRect(labelX - boxWidth / 2, labelY - boxHeight / 2, boxWidth, boxHeight);
          ctx.fillStyle = isLatest ? "#b6242b" : "#173854";
          lines.forEach(function (line, lineIndex) {
            ctx.fillText(line, labelX, labelY - ((lines.length - 1) * lineHeight) / 2 + lineIndex * lineHeight + 4);
          });
          ctx.fillStyle = isLatest ? "#c92d31" : "#173854";
          ctx.beginPath();
          ctx.arc(x, y, isLatest ? 5 : 3.5, 0, Math.PI * 2);
          ctx.fill();
        });
        ctx.restore();
      },
    };

    state.marginDebtChart = new Chart(canvas, {
      type: "line",
      data: {
        datasets: [{
          label: "Margin Debt / GDP",
          data: points,
          parsing: false,
          borderColor: "#126b9a",
          backgroundColor: "rgba(18, 107, 154, 0.12)",
          borderWidth: 3,
          pointRadius: 0,
          pointHitRadius: 8,
          fill: true,
          tension: 0.08,
        }],
      },
      plugins: [annotationPlugin],
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "nearest", intersect: false },
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              title: function (items) {
                return items.length ? formatMonthJa(items[0].raw.row.date) : "";
              },
              label: function (context) {
                var row = context.raw.row;
                return [
                  "信用買い残 / GDP: " + numberTwo.format(row.marginDebtToGdpPct) + "%",
                  "信用買い残: " + formatMarginDebt(row.marginDebtUsdMillions),
                  "GDP: $" + numberOne.format(row.nominalGdpUsdBillions / 1000) + "兆（" + formatMonthJa(row.nominalGdpDate) + "）",
                ];
              },
            },
          },
        },
        scales: {
          x: {
            type: "linear",
            min: bounds.min,
            max: bounds.max,
            grid: { color: "rgba(97, 113, 132, 0.11)" },
            ticks: {
              color: chartTextColor(),
              maxTicksLimit: state.marginDebtRange === "all" ? 12 : 10,
              callback: function (value) { return Math.round(value); },
            },
          },
          y: {
            beginAtZero: true,
            suggestedMax: 5,
            grid: { color: "rgba(97, 113, 132, 0.16)" },
            ticks: {
              color: chartTextColor(),
              callback: function (value) { return numberOne.format(value) + "%"; },
            },
          },
        },
      },
    });
  }

  function renderMarginDebt() {
    var data = state.marginDebt;
    if (!data || !data.latest) {
      byId("marginDebtStatus").textContent = "信用買い残データを読み込めません";
      byId("marginDebtStatusDetail").textContent = "FINRA・GDP系列の更新状態を確認してください。";
      return;
    }
    var latest = data.latest;
    var chain = assessMarginDebtChain();
    byId("marginDebtLatest").textContent = formatMarginDebt(latest.marginDebtUsdMillions);
    byId("marginDebtLatestDate").textContent = formatMonthJa(latest.date) + "・FINRA";
    byId("marginDebtRatio").textContent = numberTwo.format(latest.marginDebtToGdpPct) + "%";
    byId("marginDebtRatioDate").textContent = "GDP " + formatMonthJa(latest.nominalGdpDate) + "で暫定計算";
    byId("marginDebtYoy").textContent = formatPercent(latest.marginDebtChange12mPct, true);
    byId("marginDebtYoyDetail").textContent = "前月比 " + formatPercent(latest.marginDebtChange1mPct, true)
      + " / 3か月比 " + formatPercent(latest.marginDebtChange3mPct, true);
    byId("marginDebtSp500Gap").textContent = formatPctPoints(latest.debtGrowthMinusSp500PctPoints, true);
    byId("marginDebtSp500Detail").textContent = "S&P 500前年比 " + formatPercent(latest.sp500Change12mPct, true)
      + "（" + formatMonthJa(latest.sp500Date) + "まで）";
    byId("marginDebtPercentile").textContent = formatPercent(latest.ratioPercentileSince2010Pct, false);
    byId("marginDebtPercentileDetail").textContent = "2010年2月以降の同一定義に近い期間";
    byId("marginDebtStatus").textContent = chain.overall;
    byId("marginDebtStatus").dataset.level = chain.unwindLevel === "high" ? "high" : chain.triggerLevel === "high" ? "medium" : chain.fuelLevel;
    byId("marginDebtStatusDetail").textContent = "高い比率はタイミング予測ではありません。燃料、引き金、巻き戻しの三段階が重なった時だけ、パニック経路を強く疑います。";
    byId("marginDebtTimingNote").textContent = latest.gdpTimingNote || "";
    byId("marginWorkedPeriod").textContent = formatMonthJa(latest.date) + "の計算";
    byId("marginDebtRawInput").textContent = nikkeiFormat.format(latest.marginDebtUsdMillions) + " 百万ドル（" + formatMonthJa(latest.date) + "）";
    byId("marginGdpRawInput").textContent = numberThree.format(latest.nominalGdpUsdBillions) + " 十億ドル（" + formatMonthJa(latest.nominalGdpDate) + "）";
    byId("marginWorkedFormula").textContent = nikkeiFormat.format(latest.marginDebtUsdMillions)
      + " ÷（" + numberThree.format(latest.nominalGdpUsdBillions) + " × 1,000）× 100 = "
      + numberFour.format(latest.marginDebtToGdpPct) + "%";
    byId("marginWorkedTiming").textContent = latest.gdpTimingNote || "信用買い残は月次、GDPは四半期の直近公表値を対応させます。";

    ["fuel", "trigger", "unwind"].forEach(function (key) {
      var prefix = key.charAt(0).toUpperCase() + key.slice(1);
      var card = byId("marginChain" + prefix);
      card.dataset.level = chain[key + "Level"];
      card.querySelector("strong").textContent = chain[key + "Label"];
      card.querySelector("p").textContent = chain[key + "Detail"];
    });

    byId("marginDebtEventList").innerHTML = (data.events || []).map(function (event) {
      return "<div><time>" + escapeHtml(formatMonthJa(event.date)) + "</time><strong>"
        + numberTwo.format(event.marginDebtToGdpPct) + "%</strong><span>"
        + escapeHtml(event.label) + "</span><p>" + escapeHtml(event.description || "") + "</p></div>";
    }).join("");
    byId("marginDebtSourceRegime").innerHTML = (data.sourceRegimes || []).map(function (regime) {
      return "<div><strong>" + escapeHtml(regime.label) + "</strong><span>"
        + escapeHtml(formatMonthJa(regime.start)) + "～" + escapeHtml(formatMonthJa(regime.end))
        + "</span><p>" + escapeHtml(regime.importantLimit) + "</p></div>";
    }).join("");
    renderMarginDebtRangeUi();
    renderMarginDebtChart();
  }

  function renderBottomBusinessEvidence() {
    var derived = (state.data || {}).derived || {};
    var capexCoverage = finite(derived.hyperscalerCapexCoverage);
    var capexCuts = capexCoverage === 4 ? finite(derived.hyperscalersWithCapexCuts) : null;
    var capexGrowth = capexCoverage === 4 ? finite(derived.medianHyperscalerCapexGrowthYoYPct) : null;
    var revenueCoverage = finite(derived.latestQuarterRevenueGrowthCoverage);
    var revenueGrowth = revenueCoverage !== null && revenueCoverage >= 7
      ? finite(derived.medianLatestQuarterRevenueGrowthYoYPct) : null;
    var fcfCoverage = finite(derived.fcfDeteriorationCoverage);
    var fcfBreadth = fcfCoverage !== null && fcfCoverage >= 7
      ? finite(derived.fcfDeteriorationBreadthPct) : null;

    var capexLevel = capexCuts === null ? "unknown" : capexCuts >= 2 ? "fail" : capexGrowth !== null && capexGrowth >= 0 ? "pass" : "watch";
    var demandLevel = revenueGrowth === null ? "unknown" : revenueGrowth <= 0 ? "fail" : revenueGrowth >= 5 ? "pass" : "watch";
    var returnsLevel = fcfBreadth === null ? "unknown" : fcfBreadth >= 50 ? "fail" : fcfBreadth < 30 ? "pass" : "watch";
    var labels = {
      pass: "維持を確認",
      watch: "減速を監視",
      fail: "悪化を確認",
      unknown: "データ不足",
    };
    var rows = [
      {
        id: "bottomCapexEvidence", level: capexLevel, label: labels[capexLevel],
        detail: "ハイパースケーラー4社のCapEx中央値は前年比 " + formatPercent(capexGrowth, true)
          + "、10%以上削減は " + (capexCuts === null ? "未確認" : capexCuts + "/4社") + "。",
      },
      {
        id: "bottomDemandEvidence", level: demandLevel, label: labels[demandLevel],
        detail: "海外AI10社の最新四半期売上中央値は前年比 " + formatPercent(revenueGrowth, true)
          + "（比較可能 " + (revenueCoverage === null ? "0" : revenueCoverage) + "/10社）。",
      },
      {
        id: "bottomReturnsEvidence", level: returnsLevel, label: labels[returnsLevel],
        detail: "FCFが前年同期比20%以上悪化した企業は " + formatPercent(fcfBreadth, false)
          + "（比較可能 " + (fcfCoverage === null ? "0" : fcfCoverage) + "/10社）。",
      },
    ];
    rows.forEach(function (row) {
      var card = byId(row.id);
      if (!card) return;
      card.dataset.level = row.level;
      card.querySelector("strong").textContent = row.label;
      card.querySelector("p").textContent = row.detail;
    });
    var bad = rows.filter(function (row) { return row.level === "fail"; }).length;
    var good = rows.filter(function (row) { return row.level === "pass"; }).length;
    byId("bottomBusinessConclusion").textContent = bad
      ? "株価が反発しても、事業面の悪化が残っています。価格だけで底と判断しません。"
      : good === 3
        ? "設備投資・需要・FCFの三つは維持されています。ただし価格と信用の反転確認も必要です。"
        : "一部の裏付けはありますが、三つがそろっていません。反発を構造的な底とはまだ呼びません。";
  }
  function renderMarketChart() {
    if (typeof Chart === "undefined") return;
    var rows = state.data.market.normalizedChart || [];
    if (!rows.length) return;
    if (state.marketChart) state.marketChart.destroy();
    state.marketChart = new Chart(byId("marketChart"), {
      type: "line",
      data: {
        labels: rows.map(function (row) { return row.date; }),
        datasets: [
          { label: "SOX（米国上場半導体）", data: rows.map(function (row) { return row.sox; }), borderColor: "#126b9a", backgroundColor: "transparent", borderWidth: 2.5, pointRadius: 0, tension: 0.08 },
          { label: "海外AI株 等ウェイト", data: rows.map(function (row) { return row.aiBasket; }), borderColor: "#c94b18", backgroundColor: "transparent", borderWidth: 2.5, pointRadius: 0, tension: 0.08 },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: { legend: { position: "bottom", labels: { color: chartTextColor(), boxWidth: 20, usePointStyle: true } }, tooltip: { callbacks: { label: function (context) { return context.dataset.label + " " + numberOne.format(context.parsed.y); } } } },
        scales: {
          x: { grid: { display: false }, ticks: { color: chartTextColor(), maxTicksLimit: 7 } },
          y: { grid: { color: "rgba(100,115,134,.15)" }, ticks: { color: chartTextColor(), callback: function (value) { return value; } }, title: { display: true, text: "3年前=100", color: chartTextColor() } },
        },
      },
    });
  }

  function renderValuationChart() {
    if (typeof Chart === "undefined") return;
    var filter = state.companyFilter;
    var chartItems = state.valuations.filter(function (item) {
      var categoryMatches = filter === "all" || companyCategory(item.company) === filter;
      return categoryMatches && item.market;
    });
    var config = COMPANY_FILTERS[filter] || COMPANY_FILTERS.all;
    var availableCount = chartItems.filter(function (item) { return item.baseValue !== null && item.existingValue !== null; }).length;
    var omitted = chartItems.length - availableCount;
    var groupTitle = filter === "all" ? "全" + visibleCompanies().length + "社" : config.label + " " + visibleCompanies().length + "社";
    if (byId("valuationChartTitle")) byId("valuationChartTitle").textContent = groupTitle + "の時価総額を3つに分解";
    if (byId("valuationChartSubtitle")) {
      byId("valuationChartSubtitle").textContent = availableCount + "社をDCF分解"
        + (omitted > 0 ? "。正の評価用FCFがない" + omitted + "社はグレーで比較不可と表示" : "")
        + "。円とドルの金額そのものは比較しません。";
    }
    var frame = byId("valuationChartFrame");
    if (frame) frame.style.height = Math.max(360, Math.min(1240, 160 + chartItems.length * 40)) + "px";
    if (state.valuationChart) {
      state.valuationChart.destroy();
      state.valuationChart = null;
    }
    if (!chartItems.length) return;

    var decomposition = chartItems.map(function (item) {
      if (item.baseValue === null || item.existingValue === null) {
        return { existing: 0, growth: 0, premium: 0, unavailable: 100 };
      }
      var existing = clamp(item.existingValue / item.market * 100, 0, 100);
      var base = clamp(item.baseValue / item.market * 100, 0, 100);
      var growth = Math.max(0, base - existing);
      var premium = Math.max(0, 100 - Math.max(existing, base));
      return { existing: existing, growth: growth, premium: premium, unavailable: 0 };
    });
    state.valuationChart = new Chart(byId("valuationChart"), {
      type: "bar",
      data: {
        labels: chartItems.map(function (item) { return chartCompanyLabel(item.company); }),
        datasets: [
          { label: "現在FCF横ばいシナリオ", data: decomposition.map(function (row) { return row.existing; }), backgroundColor: "#173854" },
          { label: "基準成長の追加価値", data: decomposition.map(function (row) { return row.growth; }), backgroundColor: "#087f75" },
          { label: "基準シナリオ外（資産・成長・モデル差）", data: decomposition.map(function (row) { return row.premium; }), backgroundColor: "#c94b18" },
          { label: "DCF比較不可", data: decomposition.map(function (row) { return row.unavailable; }), backgroundColor: "#aab4bf" },
        ],
      },
      options: {
        indexAxis: "y",
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "nearest", intersect: false },
        plugins: {
          legend: { position: "bottom", labels: { color: chartTextColor(), boxWidth: 15 } },
          tooltip: {
            callbacks: {
              title: function (items) {
                var item = chartItems[items[0].dataIndex];
                return item.company.name + "（" + displayTicker(item.company) + "）";
              },
              label: function (context) { return context.dataset.label + " " + numberOne.format(context.parsed.x) + "%"; },
            },
          },
        },
        scales: {
          x: { stacked: true, max: 100, grid: { color: "rgba(100,115,134,.15)" }, ticks: { color: chartTextColor(), callback: function (value) { return value + "%"; } } },
          y: { stacked: true, grid: { display: false }, ticks: { color: chartTextColor(), autoSkip: false, font: { weight: "bold", size: window.innerWidth < 620 ? 11 : 12 } } },
        },
      },
    });
  }

  function renderCompanyTable() {
    var lookup = Object.fromEntries(state.valuations.map(function (item) { return [item.ticker, item]; }));
    var companies = visibleCompanies();
    updateCompanyFilterUi();
    byId("companyRows").innerHTML = companies.map(function (company) {
      var model = lookup[company.ticker];
      var baseGap = model ? model.baseGapPct : null;
      var implied = model ? model.impliedGrowthPct : null;
      var category = companyCategory(company);
      var valuationFcfValue = model ? model.valuationFcf : companyValuationFcf(company);
      var usesAdjustedFcf = company.valuationFcfBasis && company.valuationFcfBasis !== "標準化された連結TTM FCF";
      var fcfDetail = usesAdjustedFcf
        ? "<br><span class=\"neutral\">公式調整値 / 利回り " + formatPercent(company.valuationFcfYieldPct, false) + "</span><br><span class=\"neutral\">自動取得 " + formatMoney(company.ttmFreeCashFlow, company.currency) + "</span>"
        : "<br><span class=\"neutral\">連結TTM / 利回り " + formatPercent(company.valuationFcfYieldPct, false) + "</span>";
      var impliedText = model && model.baseValue !== null ? formatPercent(implied, false) : "算定不可";
      var baseText = model && model.baseValue !== null ? formatPercent(baseGap, true) : "算定不可";
      return "<tr>"
        + "<td><strong class=\"company-name\">" + escapeHtml(company.name) + "</strong><span class=\"company-group\">" + escapeHtml(displayTicker(company) + " / " + company.group) + "</span></td>"
        + "<td><span class=\"company-category " + categoryClass(category) + "\">" + escapeHtml(company.categoryLabel || COMPANY_FILTERS[category].label) + "</span></td>"
        + "<td>" + formatPrice(company.price, company.currency) + "<br><span class=\"" + cssValueClass(company.change1dPct, false) + "\">" + formatPercent(company.change1dPct, true) + "</span></td>"
        + "<td class=\"" + cssValueClass(company.drawdown3yPct, true) + "\">" + formatDrawdown(company.drawdown3yPct) + "</td>"
        + "<td class=\"" + cssValueClass(company.drawdownFrom2026HighPct, true) + "\">" + format2026HighCell(company) + "</td>"
        + "<td class=\"" + cssValueClass(company.revenueGrowthYoYPct, false) + "\">" + formatPercent(company.revenueGrowthYoYPct, true) + "</td>"
        + "<td><strong>" + formatMoney(valuationFcfValue, company.currency) + "</strong>" + fcfDetail + "</td>"
        + "<td class=\"" + (implied !== null && implied > company.assumptions.baseGrowthPct + 5 ? "negative" : implied === null ? "unknown" : "neutral") + "\">" + impliedText + "</td>"
        + "<td class=\"" + (baseGap === null ? "unknown" : cssValueClass(baseGap, false)) + "\">" + baseText + "</td>"
        + "<td><button type=\"button\" class=\"icon-button detail-button\" data-ticker=\"" + escapeHtml(company.ticker) + "\" title=\"" + escapeHtml(company.name) + "の前提と感度を表示\"><i data-lucide=\"panel-right-open\" aria-hidden=\"true\"></i></button></td>"
        + "</tr>";
    }).join("");

    byId("companySelect").innerHTML = COMPANY_CATEGORY_ORDER.map(function (category) {
      var groupCompanies = state.data.companies.filter(function (company) { return companyCategory(company) === category; });
      if (!groupCompanies.length) return "";
      var options = groupCompanies.map(function (company) {
        return "<option value=\"" + escapeHtml(company.ticker) + "\">" + escapeHtml(displayTicker(company) + " / " + company.name) + "</option>";
      }).join("");
      return "<optgroup label=\"" + escapeHtml(COMPANY_FILTERS[category].label) + "\">" + options + "</optgroup>";
    }).join("");

    if (!lookup[state.selectedTicker]) state.selectedTicker = companies[0] ? companies[0].ticker : (state.data.companies[0] ? state.data.companies[0].ticker : "");
    byId("companySelect").value = state.selectedTicker;
    document.querySelectorAll(".detail-button").forEach(function (button) {
      button.addEventListener("click", function () {
        state.selectedTicker = button.dataset.ticker;
        byId("companySelect").value = state.selectedTicker;
        setDefaultControls();
        renderCompanyDetail();
        byId("companyDetail").scrollIntoView({ behavior: "smooth", block: "start" });
      });
    });
    if (window.lucide) window.lucide.createIcons();
  }

  function currentCompany() {
    return state.data.companies.find(function (company) { return company.ticker === state.selectedTicker; });
  }

  function setDefaultControls() {
    var company = currentCompany();
    if (!company) return;
    byId("baseGrowthInput").value = company.assumptions.baseGrowthPct;
    byId("discountInput").value = company.assumptions.discountRatePct;
    byId("terminalInput").value = company.assumptions.terminalGrowthPct;
    updateOutputs();
  }

  function updateOutputs() {
    byId("baseGrowthOutput").textContent = formatPercent(finite(byId("baseGrowthInput").value), false);
    byId("discountOutput").textContent = formatPercent(finite(byId("discountInput").value), false);
    byId("terminalOutput").textContent = formatPercent(finite(byId("terminalInput").value), false);
  }

  function gapText(gap) {
    if (gap === null) return "算定不可";
    return gap >= 0 ? "現在値より " + formatPercent(gap, true) : "現在値から " + formatPercent(Math.abs(gap), false) + " 下落";
  }

  function renderCompanyDetail() {
    var company = currentCompany();
    if (!company) return;
    updateOutputs();
    var model = modelCompany(company, {
      baseGrowth: finite(byId("baseGrowthInput").value),
      discount: finite(byId("discountInput").value),
      terminal: finite(byId("terminalInput").value),
    });
    var category = companyCategory(company);
    var categoryLabel = company.categoryLabel || (COMPANY_FILTERS[category] ? COMPANY_FILTERS[category].label : category);
    var classificationUrl = company.classificationSourceUrl || company.irUrl;
    var valuationFcfValue = companyValuationFcf(company);
    byId("detailCompanyName").textContent = company.name + "（" + displayTicker(company) + "）";
    byId("detailCompanyContext").innerHTML = escapeHtml(
      (company.market || "市場未確認") + " / " + (company.currency || "USD") + "。"
      + company.group + "。財務基準日 " + (company.filingDate || "未確認") + "。"
    ) + " <a href=\"" + escapeHtml(company.irUrl) + "\" target=\"_blank\" rel=\"noopener\">公式IRを開く</a>";

    if (byId("companyClassification")) {
      byId("companyClassification").innerHTML =
        "<div><span class=\"company-category " + categoryClass(category) + "\">" + escapeHtml(categoryLabel) + "</span>"
        + "<p><strong>この分類にした理由</strong>" + escapeHtml(company.classificationNote || "事業構成とAI投資テーマへの収益感応度から分類しています。") + "</p>"
        + "<a href=\"" + escapeHtml(classificationUrl) + "\" target=\"_blank\" rel=\"noopener\">分類根拠となる企業資料</a></div>"
        + "<div class=\"company-model-warning\"><p><strong>DCFに入れたFCF</strong>"
        + escapeHtml(formatMoney(valuationFcfValue, company.currency) + " / " + (company.valuationFcfBasis || "標準化された連結TTM FCF"))
        + "<strong>計算方法</strong>" + escapeHtml(company.valuationFcfFormula || "自動取得した連結TTM FCFを使用。")
        + "<strong>この会社をDCFで読むときの注意</strong>"
        + escapeHtml(company.valuationCaveat || "企業IRで一時要因を照合してください。")
        + (company.financialServicesTreatment ? "<strong>金融事業の扱い</strong>" + escapeHtml(company.financialServicesTreatment) : "")
        + "</p><a href=\"" + escapeHtml(company.valuationFcfSourceUrl || company.fundamentalsSourceUrl) + "\" target=\"_blank\" rel=\"noopener\">評価用FCFの出典を開く</a></div>";
    }

    var stats = [
      ["時価総額", formatMoney(company.marketCap, company.currency)],
      ["企業価値（EV概算）", formatMoney(company.enterpriseValue, company.currency)],
      ["TTM売上", formatMoney(company.ttmRevenue, company.currency)],
      ["営業利益率", formatPercent(company.operatingMarginPct, false)],
      ["評価用FCF", formatMoney(valuationFcfValue, company.currency)],
      ["評価用FCF利回り", formatPercent(company.valuationFcfYieldPct, false)],
    ];
    byId("fundamentalStrip").innerHTML = stats.map(function (row) {
      return "<div class=\"fundamental-stat\"><span>" + escapeHtml(row[0]) + "</span><strong>" + escapeHtml(row[1]) + "</strong></div>";
    }).join("");

    byId("bearValue").textContent = formatPrice(model.bearPrice, company.currency);
    byId("bearDownside").textContent = gapText(model.bearGapPct);
    byId("baseValue").textContent = formatPrice(model.basePrice, company.currency);
    byId("baseDownside").textContent = gapText(model.baseGapPct);
    byId("bullValue").textContent = formatPrice(model.bullPrice, company.currency);
    byId("bullDownside").textContent = gapText(model.bullGapPct);
    byId("impliedGrowth").textContent = model.baseValue === null ? "算定不可" : formatPercent(model.impliedGrowthPct, false);

    if (model.baseValue === null) {
      var unavailable = company.ticker === "9984.T"
        ? "ソフトバンクグループは投資持株会社であり、連結FCFが負でも保有資産が消えるわけではありません。この画面の連結FCF型DCFでは算定せず、Armなどの保有資産価値から純有利子負債を引くNAV/SOTPで再評価する必要があります。"
        : "FCFが正でない、または必要データが不足しているため、この方法では価値を算定できません。売上倍率だけで機械的に埋めず、算定不可として残します。";
      byId("scenarioExplanation").textContent = unavailable + " " + (company.valuationCaveat || "");
    } else {
      var comparison = model.impliedGrowthPct === null
        ? "現在価格を説明するFCF成長率は、このモデルの探索上限までに解けませんでした。"
        : "現在価格は、FCFが今後10年間に年平均" + formatPercent(model.impliedGrowthPct, false) + "成長する前提に相当します。";
      var downside = model.baseGapPct < 0
        ? "基準前提では現在価格から約" + formatPercent(Math.abs(model.baseGapPct), false) + "下の水準です。"
        : "基準前提では現在価格を約" + formatPercent(model.baseGapPct, false) + "上回ります。";
      byId("scenarioExplanation").textContent = comparison + " " + downside
        + " 弱気値は底値保証ではなく、FCF、資本コスト、競争条件を置いた場合の計算結果です。 "
        + "DCF入力は「" + (company.valuationFcfBasis || "標準化された連結TTM FCF") + "」です。 "
        + (company.valuationCaveat || "");
    }
    renderSensitivity(company, model);
  }

  function renderSensitivity(company, model) {
    var growths = [model.baseGrowthPct - 4, model.baseGrowthPct - 2, model.baseGrowthPct, model.baseGrowthPct + 2, model.baseGrowthPct + 4];
    var discounts = [model.discountPct - 2, model.discountPct - 1, model.discountPct, model.discountPct + 1, model.discountPct + 2];
    var html = "<thead><tr><th>資本コスト＼FCF成長</th>" + growths.map(function (growth) { return "<th>" + formatPercent(growth, false) + "</th>"; }).join("") + "</tr></thead><tbody>";
    discounts.forEach(function (discount) {
      html += "<tr><th>" + formatPercent(discount, false) + "</th>";
      growths.forEach(function (growth) {
        var value = dcfValue(companyValuationFcf(company), growth, discount, model.terminalPct, model.years);
        var price = value !== null && company.marketCap && company.price ? value / company.marketCap * company.price : null;
        var near = price !== null && Math.abs(price / company.price - 1) <= 0.1;
        html += "<td class=\"" + (near ? "near-market" : "") + "\">" + formatPrice(price, company.currency) + "</td>";
      });
      html += "</tr>";
    });
    html += "</tbody>";
    byId("sensitivityTable").innerHTML = html;
  }


  function renderNtRatioChart(analysis) {
    if (typeof Chart === "undefined") return;
    var nt = analysis.ntRatio || {};
    var rows = Array.isArray(nt.history) ? nt.history : [];
    if (!rows.length) return;
    if (state.ntRatioChart) state.ntRatioChart.destroy();
    state.ntRatioChart = new Chart(byId("ntRatioChart"), {
      type: "line",
      data: {
        labels: rows.map(function (row) { return row.date; }),
        datasets: [
          {
            label: "NT倍率",
            data: rows.map(function (row) { return row.ntRatio; }),
            borderColor: "#b33b2e",
            backgroundColor: "rgba(179,59,46,.08)",
            borderWidth: 3,
            pointRadius: 0,
            tension: 0.12,
            fill: true,
          },
          {
            label: "2021年高値 15.68",
            data: rows.map(function () { return 15.68; }),
            borderColor: "#7b8794",
            borderWidth: 1.5,
            borderDash: [6, 5],
            pointRadius: 0,
          },
          {
            label: "2025年高値 15.78",
            data: rows.map(function () { return 15.78; }),
            borderColor: "#16796f",
            borderWidth: 1.5,
            borderDash: [3, 4],
            pointRadius: 0,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { position: "bottom", labels: { color: chartTextColor(), boxWidth: 18 } },
          tooltip: {
            callbacks: {
              title: function (items) { return items[0] ? items[0].label : ""; },
              label: function (context) { return context.datasetIndex === 0 ? "NT倍率 " + numberTwo.format(context.parsed.y) + "倍" : context.dataset.label; },
            },
          },
        },
        scales: {
          x: {
            grid: { display: false },
            ticks: { color: chartTextColor(), maxTicksLimit: 8, maxRotation: 0 },
          },
          y: {
            grid: { color: "rgba(100,115,134,.15)" },
            ticks: { color: chartTextColor(), callback: function (value) { return numberOne.format(value) + "倍"; } },
          },
        },
      },
    });
  }

  function renderSakakibaraGate(id, passed) {
    var element = byId(id);
    if (!element) return;
    element.classList.remove("is-pass", "is-fail", "is-unknown");
    var status = passed === true ? "is-pass" : passed === false ? "is-fail" : "is-unknown";
    element.classList.add(status);
    var label = passed === true ? "確認" : passed === false ? "未確認" : "データ不足";
    element.querySelector("em").textContent = label;
  }

  function initializeSakakibaraFairValue(analysis) {
    if (state.sakakibaraInitialized) return;
    var article = analysis.articleScenario || {};
    var settings = state.sakakibaraFairValue;
    if (finite(settings.eps) === null) settings.eps = finite(article.eps);
    if (finite(settings.targetPe) === null) settings.targetPe = finite(article.targetPe);
    if (finite(settings.bps) === null) settings.bps = finite(article.bps);
    if (finite(settings.roePct) === null) settings.roePct = finite(article.roePct);
    if (finite(settings.growthYears) === null) settings.growthYears = finite(article.growthYears);
    state.sakakibaraInitialized = true;
    syncSakakibaraControls();
  }

  function syncSakakibaraControls() {
    var settings = state.sakakibaraFairValue;
    byId("sakEpsInput").value = finite(settings.eps) === null ? "" : settings.eps;
    byId("sakTargetPeInput").value = finite(settings.targetPe) === null ? "" : settings.targetPe;
    byId("sakBpsInput").value = finite(settings.bps) === null ? "" : settings.bps;
    byId("sakRoeInput").value = finite(settings.roePct) === null ? "" : settings.roePct;
    byId("sakGrowthYearsInput").value = finite(settings.growthYears) === null ? "" : settings.growthYears;
  }

  function readSakakibaraControls() {
    var read = function (id) {
      var value = byId(id).value.trim();
      return value === "" ? null : finite(value);
    };
    state.sakakibaraFairValue = {
      eps: read("sakEpsInput"),
      targetPe: read("sakTargetPeInput"),
      bps: read("sakBpsInput"),
      roePct: read("sakRoeInput"),
      growthYears: read("sakGrowthYearsInput"),
    };
    saveSakakibaraFairValue();
  }

  function renderSakakibaraFairValue(analysis) {
    initializeSakakibaraFairValue(analysis);
    var settings = state.sakakibaraFairValue;
    var eps = finite(settings.eps);
    var targetPe = finite(settings.targetPe);
    var bps = finite(settings.bps);
    var roePct = finite(settings.roePct);
    var years = finite(settings.growthYears);
    var valid = [eps, targetPe, bps, roePct, years].every(function (value) { return value !== null; })
      && eps > 0 && targetPe > 0 && bps > 0 && roePct > -100 && years >= 0;
    var jgb = analysis.jgb || {};
    byId("sakJgbYield").textContent = finite(jgb.tenYearPct) === null ? "未確認" : numberTwo.format(jgb.tenYearPct) + "%";
    byId("sakJgbDate").textContent = jgb.date ? "基準日 " + jgb.date : "基準日未確認";
    if (!valid) {
      byId("sakPeFairValue").textContent = "入力を確認";
      byId("sakPbFairValue").textContent = "入力を確認";
      byId("sakFairRange").textContent = "算定不可";
      byId("sakPeFormula").textContent = "正のEPS・PERを入力してください。";
      byId("sakPbFormula").textContent = "正のBPS、ROEは−100%超、年数は0以上で入力してください。";
      return;
    }
    var targetPb = Math.pow(1 + roePct / 100, years);
    var earningsValue = eps * targetPe;
    var bookValue = bps * targetPb;
    byId("sakPeFairValue").textContent = formatNikkei(earningsValue);
    byId("sakPbFairValue").textContent = formatNikkei(bookValue);
    byId("sakPeFormula").textContent = nikkeiFormat.format(eps) + "円 × " + numberOne.format(targetPe) + "倍";
    byId("sakPbFormula").textContent = nikkeiFormat.format(bps) + "円 × (1 + " + numberOne.format(roePct) + "%)^" + nikkeiFormat.format(years) + "年 = PBR " + numberTwo.format(targetPb) + "倍";
    byId("sakFairRange").textContent = formatNikkei(Math.min(earningsValue, bookValue)) + " ～ " + formatNikkei(Math.max(earningsValue, bookValue));
  }

  function proxyDimension(row) {
    var dimensions = [
      { label: "品質", value: finite(row.qualityScore), max: finite(row.qualityMax) },
      { label: "相対割安", value: finite(row.valueScore), max: finite(row.valueMax) },
      { label: "売られすぎ", value: finite(row.oversoldScore), max: finite(row.oversoldMax) },
      { label: "相対回復", value: finite(row.rotationScore), max: finite(row.rotationMax) },
    ].filter(function (item) { return item.value !== null && item.max > 0; });
    dimensions.sort(function (a, b) { return b.value / b.max - a.value / a.max; });
    return dimensions[0] ? dimensions[0].label + "が相対的な強み" : "取得項目が不足";
  }

  function proxyScoreCell(value, maximum) {
    var score = finite(value);
    var max = finite(maximum);
    return score === null || max === null || max <= 0
      ? "<span class=\"unknown\">未確認</span>"
      : "<strong>" + numberOne.format(score) + "</strong><small>/" + numberOne.format(max) + "</small>";
  }

  function renderEnAiProxy(analysis) {
    var rows = Array.isArray(analysis.enAiProxy) ? analysis.enAiProxy : [];
    byId("enAiProxyRows").innerHTML = rows.map(function (row) {
      var pe = finite(row.approxTrailingPe);
      var pb = finite(row.approxPriceToBook);
      var dividend = finite(row.trailingDividendYieldPct);
      var score = finite(row.score);
      var coverage = finite(row.coveragePct);
      return "<tr>"
        + "<th><strong>" + escapeHtml(row.name) + "</strong><small>" + escapeHtml(String(row.ticker).replace(".T", "")) + "・" + escapeHtml(proxyDimension(row)) + "</small></th>"
        + "<td><strong class=\"proxy-total\">" + (score === null ? "未確認" : numberOne.format(score)) + "</strong><small>取得率 " + formatPercent(coverage, false) + "</small></td>"
        + "<td>" + proxyScoreCell(row.qualityScore, row.qualityMax) + "</td>"
        + "<td>" + proxyScoreCell(row.valueScore, row.valueMax) + "</td>"
        + "<td>" + proxyScoreCell(row.oversoldScore, row.oversoldMax) + "</td>"
        + "<td>" + proxyScoreCell(row.rotationScore, row.rotationMax) + "</td>"
        + "<td><strong>" + (pe === null ? "PER未確認" : "PER " + numberOne.format(pe) + "倍") + "</strong><small>"
        + (pb === null ? "PBR未確認" : "PBR " + numberOne.format(pb) + "倍") + " / "
        + (dividend === null ? "配当未確認" : "配当 " + numberOne.format(dividend) + "%") + "</small></td>"
        + "<td class=\"" + cssValueClass(row.change20dPct, false) + "\"><strong>" + formatPercent(row.change20dPct, true) + "</strong><small>高値から " + formatDrawdown(row.drawdownFrom2026HighPct) + "</small></td>"
        + "</tr>";
    }).join("");
    var leaders = rows.filter(function (row) { return finite(row.score) !== null; }).slice(0, 3);
    var leaderText = leaders.map(function (row) {
      return row.name + "（" + numberOne.format(row.score) + "点、" + proxyDimension(row) + "）";
    }).join("、");
    byId("enAiProxyInterpretation").textContent = leaders.length
      ? "現在の代理上位は " + leaderText + " です。これは8社内の相対順位で、割安の絶対判定でも購入推奨でもありません。PERは時価総額÷TTM純利益、PBRは時価総額÷直近株主資本、配当利回りは直近365日の実績配当÷株価という近似です。"
      : "代理スコアに必要な財務・価格データを取得できませんでした。";
  }

  function renderThresholdCalibration(elementId, sample, suffix) {
    var element = byId(elementId);
    if (!element) return;
    if (!sample || !Array.isArray(sample.thresholds) || !sample.thresholds.length) {
      element.textContent = "標本データ不足";
      return;
    }
    var sampleMaximum = finite(sample.maximum);
    var bands = sample.thresholds.map(function (row) {
      if (sampleMaximum !== null && finite(row.value) !== null && row.value > sampleMaximum) {
        return numberOne.format(row.value) + suffix + " = 標本上限超過（最大" + numberTwo.format(sampleMaximum) + suffix + "）";
      }
      return numberOne.format(row.value) + suffix + " = 標本内P" + numberOne.format(row.percentileRank);
    }).join("、");
    element.textContent = (sample.sampleStartDate || "開始日不明") + "～" + (sample.sampleEndDate || "終了日不明")
      + "の" + numberOne.format(sample.sampleCount) + "観測で、" + bands + "。"
      + (sample.historyNote ? " " + sample.historyNote : "");
  }

  function renderMarketPathComponents(targetId, components) {
    byId(targetId).innerHTML = (components || []).map(function (component) {
      var score = finite(component.score);
      var known = finite(component.knownMax);
      var maximum = finite(component.maxScore);
      var width = maximum && score !== null ? clamp(score / maximum * 100, 0, 100) : 0;
      return "<article class=\"path-component\"><div><span>" + escapeHtml(component.label || component.id) + "</span><strong>"
        + (score === null || known === null ? "未確認" : numberOne.format(score) + "/" + numberOne.format(known) + "点")
        + "</strong></div><div class=\"path-component-bar\"><i style=\"width:" + width + "%\"></i></div><p>"
        + escapeHtml(component.detail || "内訳を確認できません。") + "</p></article>";
    }).join("");
  }

  function renderSakakibaraMarketPath(analysis) {
    var path = analysis.marketPath || {};
    var panel = byId("marketPathPanel");
    var route = finite(path.routeIndex);
    var normalization = path.normalization || {};
    var panic = path.panic || {};
    var anchor = path.valuationAnchor || {};
    var inputs = path.inputs || {};

    panel.className = "market-path-panel is-" + escapeHtml(path.statusCode || "insufficient");
    byId("marketPathLabel").textContent = path.label || "データ不足";
    byId("marketPathAsOf").textContent = analysis.asOfDate || "未確認";
    byId("marketPathIndex").textContent = route === null
      ? "未確認"
      : (route > 0 ? "+" : "") + numberOne.format(route);
    byId("marketPathMarker").style.left = route === null ? "50%" : clamp((route + 100) / 2, 0, 100) + "%";

    byId("marketPathNormalizationScore").textContent = finite(normalization.score) === null
      ? "未確認" : numberOne.format(normalization.score) + "/100";
    byId("marketPathNormalizationCoverage").textContent = "取得率 " + formatPercent(normalization.coveragePct, false);
    byId("marketPathPanicScore").textContent = finite(panic.score) === null
      ? "未確認" : numberOne.format(panic.score) + "/100";
    byId("marketPathPanicCoverage").textContent = "取得率 " + formatPercent(panic.coveragePct, false);

    renderMarketPathComponents("marketPathNormalizationComponents", normalization.components);
    renderMarketPathComponents("marketPathPanicComponents", panic.components);

    var currentUpper = finite(anchor.moveFromCurrentToUpperPct);
    var currentLower = finite(anchor.moveFromCurrentToLowerPct);
    byId("marketPathCurrentToRange").textContent = currentUpper === null || currentLower === null
      ? "未確認"
      : "上端 " + formatPercent(currentUpper, true) + " / 下端 " + formatPercent(currentLower, true);
    var peakUpper = finite(anchor.drawdownFromPeakToUpperPct);
    var peakLower = finite(anchor.drawdownFromPeakToLowerPct);
    byId("marketPathPeakToRange").textContent = peakUpper === null || peakLower === null
      ? "未確認"
      : "上端 −" + formatPercent(peakUpper, false) + " / 下端 −" + formatPercent(peakLower, false);

    byId("marketPathVix").textContent = finite(inputs.vix) === null
      ? "未確認"
      : numberOne.format(inputs.vix) + "（5日 " + formatPercent(inputs.vix5dPct, true) + "）";
    byId("marketPathHyOas").textContent = finite(inputs.highYieldOasPct) === null
      ? "未確認"
      : numberTwo.format(inputs.highYieldOasPct) + "%（3か月低値から " + formatPctPoints(inputs.highYieldOasRise3mPctPoints, true) + "）";

    var positiveBreadth = finite(inputs.diversifiedPositive5dPct);
    var reading;
    if (path.statusCode === "normalization-strong" || path.statusCode === "normalization-watch") {
      reading = "<p><strong>現在の結論：</strong>" + escapeHtml(path.label) + "です。正常化" + numberOne.format(normalization.score)
        + "点に対し、パニックは" + numberOne.format(panic.score) + "点です。</p>"
        + "<p><strong>なぜパニック型ではないのか：</strong>日経平均は5日で" + formatPercent(inputs.nikkei5dPct, true)
        + "と急落していますが、TOPIXは" + formatPercent(inputs.topix5dPct, true) + "にとどまり、分散型8社のうち"
        + (positiveBreadth === null ? "上昇比率は未確認" : formatPercent(positiveBreadth, false) + "が上昇")
        + "しています。VIXは" + (finite(inputs.vix) === null ? "未確認" : numberOne.format(inputs.vix))
        + "、米国HY OASは" + (finite(inputs.highYieldOasPct) === null ? "未確認" : numberTwo.format(inputs.highYieldOasPct) + "%")
        + "で、現時点では信用・流動性危機を伴う全面的な投げ売りを示していません。</p>"
        + "<p><strong>残る警戒：</strong>日経平均の下落速度にはパニック点が付きます。TOPIXと分散型株まで下落が広がり、VIXとHY OASが同時に上昇すれば、約6万円への評価正常化からパニック経路へ判定が変わります。</p>";
    } else if (path.statusCode === "panic" || path.statusCode === "panic-watch" || path.statusCode === "mixed") {
      reading = "<p><strong>現在の結論：</strong>" + escapeHtml(path.label) + "です。正常化" + numberOne.format(normalization.score)
        + "点、パニック" + numberOne.format(panic.score) + "点で、市場全体への波及を警戒します。</p>"
        + "<p><strong>読み方：</strong>約6万円は評価アンカーであり、パニック時の下限ではありません。TOPIX、分散型株、VIX、HY OASの悪化が続く間は、企業価値からの一時的な下方乖離を想定します。</p>";
    } else {
      reading = "<p><strong>現在の結論：</strong>" + escapeHtml(path.label || "方向不明") + "です。データ取得率と各内訳を確認し、単独の指数だけで判断しません。</p>";
    }
    byId("marketPathInterpretation").innerHTML = reading;
    var calibration = path.calibration || {};
    renderThresholdCalibration("thresholdVixBasis", calibration.vix, "");
    renderThresholdCalibration("thresholdOasBasis", calibration.oas, "%");
    var basketAudit = calibration.basket || {};
    byId("thresholdBasketBasis").textContent = basketAudit.constituentCount
      ? basketAudit.constituentCount + "社なので1社=" + numberOne.format(basketAudit.oneStockSharePct)
        + "ポイント。中央値は4番目と5番目で決まり、統計的有意差を検定した指標ではありません。"
      : "8社バスケットの監査情報を取得できませんでした。";
  }

  function renderSakakibaraMethod() {
    var analysis = state.data && state.data.market ? state.data.market.sakakibaraAnalysis || {} : {};
    if (!analysis.ntRatio) {
      byId("sakakibaraStage").textContent = "計算データ不足";
      byId("sakakibaraStageReason").textContent = "日経平均とTOPIXの同日終値を十分に取得できませんでした。";
      return;
    }
    var nt = analysis.ntRatio || {};
    var gates = analysis.gates || {};
    var relative = analysis.relativeMarket || {};
    var nikkei = relative.nikkei || {};
    var topix = relative.topix || {};
    var ai = analysis.japanAiBasket || {};
    var diversified = analysis.japanDiversifiedBasket || {};
    var kioxia = analysis.kioxiaCase || {};

    byId("sakakibaraStage").textContent = analysis.stage || "未判定";
    byId("sakakibaraAsOf").textContent = analysis.asOfDate || "未確認";
    byId("sakakibaraGateCount").textContent = (analysis.confirmationCount || 0) + "/" + (analysis.confirmationMax || 4);
    byId("sakakibaraNtLatest").textContent = finite(nt.latest) === null ? "未確認" : numberTwo.format(nt.latest) + "倍";
    byId("sakakibaraNtDate").textContent = nt.latestDate ? nt.latestDate + "・日経平均÷TOPIX" : "日付未確認";
    var stageReason = gates.distortion
      ? "直近のNT倍率には一極集中の歪みが残っています。そのうえで、揺り戻しを示す4条件のうち" + (analysis.confirmationCount || 0) + "条件を確認しました。"
      : "NT倍率が本ルールの高水準条件に達していないため、揺り戻しの前提となる一極集中の歪みを確認していません。";
    byId("sakakibaraStageReason").textContent = stageReason;

    byId("sakNtPeak").textContent = finite(nt.peak252d) === null ? "未確認" : numberTwo.format(nt.peak252d) + "倍";
    byId("sakNtPeakDate").textContent = nt.peak252dDate || "日付未確認";
    byId("sakNtPeakDecline").textContent = finite(nt.declineFromPeakPct) === null ? "未確認" : "−" + formatPercent(nt.declineFromPeakPct, false);
    byId("sakNt20dChange").textContent = formatPercent(nt.change20dPct, true);
    byId("sakNtInterpretation").textContent = gates.ntReversal
      ? "NT倍率は直近ピークから" + formatPercent(nt.declineFromPeakPct, false) + "低下し、20日でも" + formatPercent(nt.change20dPct, true) + "です。高株価の集中銘柄が市場全体より弱くなり、歪みが縮小している動きと整合します。"
      : "NT倍率の水準が高くても、ピークから十分に低下し20日方向も下向きになるまでは、集中の修正が始まったとは判定しません。";

    renderSakakibaraGate("sakGateNt", gates.ntReversal);
    renderSakakibaraGate("sakGateMarket", gates.broadOutperformance);
    renderSakakibaraGate("sakGateBasket", gates.basketRotation);
    renderSakakibaraGate("sakGateBreadth", gates.breadthConfirmation);

    byId("sakNikkei5d").textContent = formatPercent(nikkei.change5dPct, true);
    byId("sakTopix5d").textContent = formatPercent(topix.change5dPct, true);
    byId("sakMarketSpread5d").textContent = "TOPIX優位 " + formatPctPoints(relative.topixAdvantage5dPctPoints, true);
    byId("sakNikkei20d").textContent = formatPercent(nikkei.change20dPct, true);
    byId("sakTopix20d").textContent = formatPercent(topix.change20dPct, true);
    byId("sakMarketSpread20d").textContent = "TOPIX優位 " + formatPctPoints(relative.topixAdvantage20dPctPoints, true);
    byId("sakMarketInterpretation").textContent = finite(relative.topixAdvantage20dPctPoints) !== null && relative.topixAdvantage20dPctPoints > 0
      ? "20日ではTOPIXが日経平均を" + formatPctPoints(relative.topixAdvantage20dPctPoints, false) + "上回りました。市場全体も下落し得ますが、価格加重の日経平均に大きく効く銘柄の下落が、幅広い日本株より強い状態です。"
      : "TOPIXの相対優位を確認できません。日経平均の集中銘柄だけが特に弱い、という揺り戻し像とはまだ一致しません。";

    byId("sakAi5d").textContent = formatPercent(ai.medianChange5dPct, true);
    byId("sakDiv5d").textContent = formatPercent(diversified.medianChange5dPct, true);
    byId("sakBasketSpread5d").textContent = "分散型優位 " + formatPctPoints(analysis.basketAdvantage5dPctPoints, true);
    byId("sakAi20d").textContent = formatPercent(ai.medianChange20dPct, true);
    byId("sakDiv20d").textContent = formatPercent(diversified.medianChange20dPct, true);
    byId("sakBasketSpread20d").textContent = "分散型優位 " + formatPctPoints(analysis.basketAdvantage20dPctPoints, true);
    byId("sakBasketInterpretation").textContent = gates.basketRotation
      ? "分散型8社の中央値はAI連動8社を、5日で" + formatPctPoints(analysis.basketAdvantage5dPctPoints, false) + "、20日で" + formatPctPoints(analysis.basketAdvantage20dPctPoints, false) + "上回りました。このモデルでいうEN-AI側への相対回復と整合する価格差です。"
      : "分散型8社がAI連動8社を十分に上回っていません。指数差だけで揺り戻しと判断せず、企業群でも確認できるまで保留します。";

    var breadthCoverage = diversified.positive5dCoverage || diversified.count || 0;
    byId("sakBreadthOutperform").textContent = finite(diversified.outperformNikkei5dCount) === null ? "未確認" : diversified.outperformNikkei5dCount + "/" + breadthCoverage + "社";
    byId("sakBreadthPositive").textContent = finite(diversified.positive5dCount) === null ? "未確認" : diversified.positive5dCount + "/" + breadthCoverage + "社";
    byId("sakBreadthInterpretation").textContent = gates.breadthConfirmation
      ? "相対的な強さが複数の分散型企業へ広がっています。1社の決算や材料だけで生じた指数差である可能性は下がりますが、8社の小標本である点は残ります。"
      : "分散型企業への広がりが基準に達していません。少数銘柄の上昇だけなら、継続的な揺り戻しとは区別します。";

    byId("sakKioxiaStartDate").textContent = formatShortDate(kioxia.articleStartDate) || "3/31";
    byId("sakKioxiaStart").textContent = formatPrice(kioxia.articleStartLow, "JPY");
    byId("sakKioxiaPeakDate").textContent = formatShortDate(kioxia.peak2026Date) || "高値日未確認";
    byId("sakKioxiaPeak").textContent = formatPrice(kioxia.peak2026, "JPY");
    byId("sakKioxiaRise").textContent = "起点から " + formatPercent(kioxia.riseFromArticleStartToPeakPct, true) + "（約" + (finite(kioxia.riseFromArticleStartToPeakPct) === null ? "―" : numberTwo.format(1 + kioxia.riseFromArticleStartToPeakPct / 100)) + "倍）";
    byId("sakKioxiaCurrentDate").textContent = formatShortDate(kioxia.date) || "最新";
    byId("sakKioxiaCurrent").textContent = formatPrice(kioxia.close, "JPY");
    byId("sakKioxiaFall").textContent = "高値から −" + formatPercent(kioxia.drawdownFrom2026HighPct, false);
    byId("sakKioxiaInterpretation").textContent = "3月31日の日中安値" + formatPrice(kioxia.articleStartLow, "JPY") + "から6月22日の日中高値" + formatPrice(kioxia.peak2026, "JPY") + "まで" + formatPercent(kioxia.riseFromArticleStartToPeakPct, true) + "上昇し、その後は最新値まで" + formatPercent(kioxia.drawdownFrom2026HighPct, false) + "下落しました。短期間の急騰と急落は期待の過熱・剥落と整合しますが、1社の事例だけで市場全体のバブル崩壊を証明するものではありません。";

    var calm = kioxia.calmValuation || {};
    var calmReports = calm.reports || [];
    var q3Report = calmReports[0] || {};
    var fyReport = calmReports[1] || {};
    var adoptedRevenue = finite(calm.forecastRevenueJpyMillions);
    var quarterAnnualizedRevenue = finite(calm.latestQuarterAnnualizedRevenueJpyMillions);
    byId("sakKioxiaReportOneLabel").textContent = Number(q3Report.periodMonths) === 3 ? "最新Q1・売上前年比（比較材料）" : "最新決算の売上前年比";
    byId("sakKioxiaReportTwoLabel").textContent = "前回決算・売上前年比";
    byId("sakKioxiaGrowthAssumptionLabel").textContent = "採用する年間売上";
    byId("sakKioxiaGrowthAssumptionCaption").textContent = calm.revenueMethod || "最新四半期は年換算で比較するだけで、通期予想とは扱いません";
    byId("sakKioxiaNormalizedMarginCaption").textContent = calm.marginMethod || "好調な単四半期の利益率を恒久化しません";
    byId("sakKioxiaQ3Growth").textContent = formatPercent(q3Report.revenueGrowthYoYPct, true);
    byId("sakKioxiaQ3Period").textContent = q3Report.periodLabel ? q3Report.periodLabel + "・" + (q3Report.releaseDate || "公表日未確認") : "未確認";
    byId("sakKioxiaFyGrowth").textContent = formatPercent(fyReport.revenueGrowthYoYPct, true);
    byId("sakKioxiaFyPeriod").textContent = fyReport.periodLabel ? fyReport.periodLabel + "・" + (fyReport.releaseDate || "公表日未確認") : "未確認";
    byId("sakKioxiaGrowthAssumption").textContent = adoptedRevenue === null ? "未確認" : "約" + numberTwo.format(adoptedRevenue / 1000000) + "兆円";
    byId("sakKioxiaNormalizedMargin").textContent = formatPercent(calm.referenceNetMarginPct, false);
    byId("sakKioxiaShares").textContent = finite(calm.sharesOutstanding) === null ? "未確認" : nikkeiFormat.format(calm.sharesOutstanding) + "株";
    byId("sakKioxiaCalmPrice").textContent = formatPrice(calm.referencePriceJpy, "JPY");
    byId("sakKioxiaCalmRange").textContent = "PER " + (finite(calm.sensitivityPeLow) === null ? "―" : numberOne.format(calm.sensitivityPeLow)) + "～" + (finite(calm.sensitivityPeHigh) === null ? "―" : numberOne.format(calm.sensitivityPeHigh)) + "倍: " + formatPrice(calm.sensitivityLowPriceJpy, "JPY") + "～" + formatPrice(calm.sensitivityHighPriceJpy, "JPY");
    byId("sakKioxiaCalmFormula").textContent = finite(calm.referencePriceJpy) === null
      ? "必要な決算入力を確認できませんでした。"
      : "計算式：" + (calm.revenueMethod || "公表済みの売上水準を使う") + "。採用する年間売上は" + (adoptedRevenue === null ? "未確認" : "約" + numberTwo.format(adoptedRevenue / 1000000) + "兆円") + "、利益率は" + formatPercent(calm.referenceNetMarginPct, false) + "、PERは" + numberOne.format(calm.referencePe) + "倍、発行済株式数は" + nikkeiFormat.format(calm.sharesOutstanding) + "株として中心値を計算します。" + (quarterAnnualizedRevenue === null ? "" : " 最新Q1の単純年換算は約" + numberTwo.format(quarterAnnualizedRevenue / 1000000) + "兆円ですが、通期予想とはみなしません。");
    var currentMultiple = finite(calm.currentPriceMultiple);
    byId("sakKioxiaCalmGap").textContent = currentMultiple === null
      ? "現在値との差は未確認です。"
      : "最新終値" + formatPrice(kioxia.close, "JPY") + "は中心値の約" + numberTwo.format(currentMultiple) + "倍（中心値比" + formatPercent(calm.currentPremiumToReferencePct, true) + "）。株価がこの差を維持するには、売上成長、利益率、評価倍率のいずれかが本モデルより高く続く必要があります。";
    byId("sakKioxiaCalmInterpretation").textContent = calm.interpretation || "この中心値は売買推奨、目標株価、底値予測ではありません。";
    if (q3Report.sourceUrl) byId("sakKioxiaQ3Source").href = q3Report.sourceUrl;
    if (fyReport.sourceUrl) byId("sakKioxiaFySource").href = fyReport.sourceUrl;
    if (q3Report.periodLabel) byId("sakKioxiaQ3Source").textContent = q3Report.periodLabel + " 決算資料";
    if (fyReport.periodLabel) byId("sakKioxiaFySource").textContent = fyReport.periodLabel + " 決算資料";
    renderKioxiaLiveOverlay(kioxia);

    renderNtRatioChart(analysis);
    renderSakakibaraFairValue(analysis);
    renderSakakibaraMarketPath(analysis);
    renderEnAiProxy(analysis);
  }

  function nikkeiAiSourceMarkup(source) {
    var item = source || {};
    var label = String(item.label || item.name || "出典");
    if (item.used_for) label += "（" + String(item.used_for) + "）";
    var href = safeHttpsUrl(item.url);
    if (!href) return "<span>" + escapeHtml(label) + "</span>";
    return '<a href="' + escapeHtml(href) + '" target="_blank" rel="noopener noreferrer">' + escapeHtml(label) + "</a>";
  }

  function renderNikkeiAiThreeSeries() {
    var payload = state.nikkeiAiThreeSeries || {};
    var meta = payload.meta || {};
    var summary = payload.summary || {};
    var quality = payload.quality || {};
    var targets = Array.isArray(payload.bubble_suspect) ? payload.bubble_suspect : [];
    var keeps = Array.isArray(payload.explicit_keep) ? payload.explicit_keep : [];
    var warnings = Array.isArray(payload.warnings) ? payload.warnings.filter(Boolean) : [];
    var sources = Array.isArray(payload.sources) ? payload.sources : [];
    var series = (Array.isArray(payload.series) ? payload.series : []).filter(function (row) {
      return row && row.date && finite(row.nikkei_actual) !== null;
    });
    var summaryNode = byId("nikkeiAiThreeSummary");
    var targetNode = byId("nikkeiAiTargetNames");
    var stockRows = byId("nikkeiAiStockRows");
    var qualityNode = byId("nikkeiAiQualityNotes");
    var badge = byId("nikkeiAiMethodBadge");
    var canvas = byId("nikkeiAiThreeSeriesChart");
    var notice = byId("nikkeiAiComparisonNotice");
    var chartTitle = byId("nikkeiAiChartTitle");
    var chartSubtitle = byId("nikkeiAiChartSubtitle");
    var readingNode = byId("nikkeiAiReading");
    var comparisonStatus = String(meta.comparison_status || quality.data_state || "");
    var comparisonSeriesPresent = series.some(function (row) {
      return finite(row.ai_overheat_normalized) !== null || finite(row.ai_overheat_excluded) !== null;
    });
    var comparisonUncomputed = comparisonStatus.indexOf("comparison-uncomputed") !== -1
      || (!targets.length && comparisonStatus.indexOf("actual-only") === 0) || !comparisonSeriesPresent;
    var syntheticSeriesAvailable = !comparisonUncomputed && comparisonSeriesPresent;
    var uncomputedDetail = targets.length
      ? "対象銘柄は設定されていますが、日経平均を正確に再構築するための時点別構成銘柄・PAF・除数が未接続です。"
      : "AIバブル疑義銘柄が未設定で、日経平均を正確に再構築するための時点別構成銘柄・PAF・除数も未接続です。";
    if (!summaryNode || !targetNode || !stockRows || !qualityNode) return;

    if (badge) badge.textContent = meta.method_label || "計算方法を確認中";
    if (notice) {
      notice.hidden = !comparisonUncomputed;
      notice.innerHTML = comparisonUncomputed
        ? "<strong>3系列比較は未算出です</strong><p>" + uncomputedDetail + "AI関連という理由だけで自動除外せず、実績と同値の線を重ねて比較済みのようには表示しません。</p>"
        : "";
    }
    if (chartTitle) chartTitle.textContent = comparisonUncomputed ? "10年間の実績（比較未算出）" : "10年間の3系列比較";
    if (chartSubtitle) chartSubtitle.textContent = comparisonUncomputed
      ? "共通起点＝100・日経平均の実績のみ表示"
      : "共通起点＝100・価格指数・配当なし";
    if (canvas) canvas.setAttribute("aria-label", comparisonUncomputed
      ? "日経平均の10年間実績。AI過熱の比較系列は未算出"
      : "日経平均とAI過熱調整後の3系列比較");
    if (readingNode) {
      readingNode.innerHTML = comparisonUncomputed
        ? "<p><strong>現在表示：</strong>日経平均の実績系列だけです。</p><p><strong>未算出の理由：</strong>対象銘柄と、過去の構成・PAF・除数の完全な履歴がそろっていません。</p><p><strong>次に必要なこと：</strong>対象を明示し、再構築誤差を検証できる履歴データを接続してから比較します。</p>"
        : "<p><strong>実績－標準化：</strong>指定したAI過熱銘柄の異常上昇部分が日経平均を押し上げた大きさの試算です。</p><p><strong>標準化－除外：</strong>対象企業を一般的な価格上昇の範囲で残した効果の試算です。</p><p>これは公式指数、投資助言、バブルの統計的認定ではありません。</p>";
    }

    if (!series.length) {
      summaryNode.innerHTML = '<article class="nikkei-ai-summary-card is-loading"><span>比較データ</span><strong>未確認</strong><small>日経平均の3系列データを取得できませんでした。</small></article>';
    } else {
      var combinedWeight = finite(summary.current_combined_weight_pct);
      var metricCards = [
        {
          label: "実績・10年騰落率",
          value: formatPercent(summary.actual_return_pct, true),
          caption: "日経平均の実際の価格指数",
        },
        {
          label: "過熱を標準化した騰落率",
          value: syntheticSeriesAvailable ? formatPercent(summary.normalized_return_pct, true) : "未算出",
          caption: syntheticSeriesAvailable ? "異常上昇部分だけを一般株経路に調整" : "対象・履歴データの接続後に計算",
          uncomputed: !syntheticSeriesAvailable,
        },
        {
          label: "過熱銘柄を除外した騰落率",
          value: syntheticSeriesAvailable ? formatPercent(summary.excluded_return_pct, true) : "未算出",
          caption: syntheticSeriesAvailable ? "価格加重の再構成を行う想定" : "対象・履歴データの接続後に計算",
          uncomputed: !syntheticSeriesAvailable,
        },
        {
          label: "実績－標準化",
          value: syntheticSeriesAvailable ? formatPctPoints(summary.ai_excess_contribution_percentage_points, true) : "—",
          caption: syntheticSeriesAvailable ? "AI過熱の超過寄与という試算" : "ゼロではなく未算出",
          uncomputed: !syntheticSeriesAvailable,
        },
        {
          label: "対象銘柄の合計ウエート",
          value: combinedWeight === null ? (targets.length ? "未確認" : "未設定") : formatPercent(combinedWeight, false),
          caption: targets.length ? "最新時点の価格加重ベース" : "対象銘柄がまだ設定されていません",
        },
      ];
      summaryNode.innerHTML = metricCards.map(function (card) {
        return '<article class="nikkei-ai-summary-card' + (card.uncomputed ? " is-uncomputed" : "") + '"><span>' + escapeHtml(card.label)
          + "</span><strong>" + escapeHtml(card.value) + "</strong><small>" + escapeHtml(card.caption) + "</small></article>";
      }).join("");
    }

    if (targets.length) {
      targetNode.innerHTML = "<strong>対象銘柄：</strong>" + targets.map(function (item) {
        var name = String(item.name || item.company_name || "名称未確認");
        var code = String(item.code || item.ticker || "");
        return escapeHtml(name + (code ? "（" + code + "）" : ""));
      }).join("、");
      stockRows.innerHTML = targets.map(function (item) {
        var status = item.data_status || item.status || "未確認";
        var peerCount = finite(item.peer_count);
        var actual = finite(item.actual_return_pct);
        var peer = finite(item.peer_path_return_pct);
        var removed = finite(item.removed_excess_return_percentage_points);
        var weight = finite(item.current_nikkei_weight_pct);
        return "<tr>"
          + "<td>" + escapeHtml(item.code || item.ticker || "未確認") + "</td>"
          + "<td>" + escapeHtml(item.name || item.company_name || "未確認") + "</td>"
          + "<td>" + escapeHtml(item.effective_from || "未確認") + "</td>"
          + "<td>" + escapeHtml(item.reason || "未確認") + "</td>"
          + "<td>" + (peerCount === null ? "未確認" : numberOne.format(peerCount) + "社") + "</td>"
          + "<td>" + escapeHtml(formatPercent(actual, true)) + "</td>"
          + "<td>" + escapeHtml(formatPercent(peer, true)) + "</td>"
          + "<td>" + escapeHtml(formatPctPoints(removed, true)) + "</td>"
          + "<td>" + escapeHtml(formatPercent(weight, false)) + "</td>"
          + "<td>" + escapeHtml(status) + "</td>"
          + "</tr>";
      }).join("");
    } else {
      targetNode.innerHTML = "<strong>対象銘柄：未設定</strong> — AIバブル疑義銘柄が未設定です。AI関連という理由だけでは自動的に除外していません。";
      stockRows.innerHTML = '<tr><td colspan="10">AIバブル疑義銘柄が未設定です。AI関連という理由だけでは自動的に除外していません。</td></tr>';
    }

    var qualityMarkup = [];
    qualityMarkup.push("<p><strong>計算の位置づけ：</strong>" + escapeHtml(meta.method_label || "未確認") + "</p>");
    qualityMarkup.push("<p><strong>データ範囲：</strong>" + escapeHtml((meta.start_date || "開始日未確認") + " から " + (meta.end_date || "終了日未確認"))
      + "。日次計算・週次表示、基準値 " + escapeHtml(meta.base_value || 100) + "、配当なしです。</p>");
    qualityMarkup.push("<p><strong>実績系列：</strong>" + escapeHtml(meta.price_field || "価格系列を確認中")
      + "。公式日次データは " + escapeHtml(meta.official_daily_available_from || "未確認") + " 以降を優先しています。</p>");
    qualityMarkup.push("<p><strong>\u66f4\u65b0\u6642\u523b\uff1a</strong>" + escapeHtml(meta.generated_at || "\u672a\u78ba\u8a8d") + "</p>");
    var crosscheck = quality.monthly_crosscheck || {};
    if (finite(crosscheck.matched_months) !== null) {
      qualityMarkup.push("<p><strong>月次照合：</strong>" + escapeHtml(numberOne.format(crosscheck.matched_months))
        + "か月を照合" + (crosscheck.within_0_02_jpy ? "し、公式月次終値との差は0.02円以内です。" : "しています。") + "</p>");
    }
    var missingItems = Array.isArray(quality.missing_items) ? quality.missing_items.filter(Boolean) : [];
    if (missingItems.length) {
      qualityMarkup.push("<p><strong>未取得のため試算しない項目：</strong>" + escapeHtml(missingItems.join("、")) + "</p>");
    }
    if (keeps.length) {
      qualityMarkup.push("<p><strong>除外しない指定：</strong>" + keeps.map(function (item) {
        var name = String(item.name || "名称未確認");
        var code = item.code ? "（" + item.code + "）" : "";
        return escapeHtml(name + code);
      }).join("、") + "</p>");
    }
    if (warnings.length) {
      qualityMarkup.push('<ul class="nikkei-ai-warning-list">' + warnings.map(function (warning) {
        return "<li>" + escapeHtml(warning) + "</li>";
      }).join("") + "</ul>");
    }
    if (sources.length) {
      qualityMarkup.push('<p class="nikkei-ai-source-links"><strong>出典：</strong>' + sources.map(nikkeiAiSourceMarkup).join(" / ") + "</p>");
    }
    qualityNode.innerHTML = qualityMarkup.join("");

    if (state.nikkeiAiThreeSeriesChart) {
      state.nikkeiAiThreeSeriesChart.destroy();
      state.nikkeiAiThreeSeriesChart = null;
    }
    if (typeof Chart === "undefined" || !canvas || !series.length) return;

    var labels = series.map(function (row) { return row.date; });
    var latest = series[series.length - 1] || {};
    var normalizedValues = comparisonUncomputed ? series.map(function () { return null; }) : series.map(function (row) { return finite(row.ai_overheat_normalized); });
    var excludedValues = comparisonUncomputed ? series.map(function () { return null; }) : series.map(function (row) { return finite(row.ai_overheat_excluded); });
    state.nikkeiAiThreeSeriesChart = new Chart(canvas, {
      type: "line",
      data: {
        labels: labels,
        datasets: [
          {
            label: "日経平均・実績",
            data: series.map(function (row) { return finite(row.nikkei_actual); }),
            borderColor: "#1b4d6f",
            backgroundColor: "rgba(27,77,111,.08)",
            borderWidth: 2.8,
            pointRadius: 0,
            tension: 0.12,
          },
          {
            label: comparisonUncomputed ? "AI過熱を標準化（未算出）" : "AI過熱を標準化",
            data: normalizedValues,
            borderColor: comparisonUncomputed ? "#a99470" : "#11836f",
            borderWidth: 2.4,
            borderDash: [7, 4],
            pointRadius: 0,
            tension: 0.12,
          },
          {
            label: comparisonUncomputed ? "AI過熱銘柄を除外（未算出）" : "AI過熱銘柄を除外",
            data: excludedValues,
            borderColor: comparisonUncomputed ? "#a99470" : "#b64a3b",
            borderWidth: 2.2,
            borderDash: [2, 4],
            pointRadius: 0,
            tension: 0.12,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { position: "bottom", labels: { color: chartTextColor(), boxWidth: 18, usePointStyle: true } },
          tooltip: {
            callbacks: {
              title: function (items) { return items[0] ? items[0].label : ""; },
              label: function (context) {
                var value = finite(context.parsed && context.parsed.y);
                return context.dataset.label + " " + (value === null ? "未算出" : numberOne.format(value));
              },
              afterBody: function (items) {
                var index = items[0] && Number.isFinite(items[0].dataIndex) ? items[0].dataIndex : -1;
                var row = index >= 0 ? series[index] : latest;
                var lines = [];
                if (finite(row.nikkei_close) !== null) lines.push("日経平均終値 " + numberTwo.format(row.nikkei_close) + "円");
                if (finite(row.actual_minus_normalized) !== null) lines.push("実績－標準化 " + formatPctPoints(row.actual_minus_normalized, true));
                if (finite(row.normalized_minus_excluded) !== null) lines.push("標準化－除外 " + formatPctPoints(row.normalized_minus_excluded, true));
                return lines;
              },
            },
          },
        },
        scales: {
          x: {
            grid: { display: false },
            ticks: {
              color: chartTextColor(),
              maxTicksLimit: window.matchMedia && window.matchMedia("(max-width: 700px)").matches ? 6 : 12,
              maxRotation: 0,
              callback: function (_value, index) {
                return String(labels[index] || "").slice(0, 7).replace("-", "/");
              },
            },
          },
          y: {
            grid: { color: "rgba(100,115,134,.15)" },
            ticks: { color: chartTextColor(), callback: function (value) { return numberOne.format(value); } },
            title: { display: true, text: "10年前＝100", color: chartTextColor() },
          },
        },
      },
    });
  }
  function renderNikkeiAiContributionProxy() {
    var payload = state.nikkeiAiThreeSeries || {};
    var meta = payload.meta || {}, summary = payload.summary || {}, quality = payload.quality || {};
    var candidates = Array.isArray(payload.candidates) ? payload.candidates : [];
    var targets = Array.isArray(payload.selected_candidates) ? payload.selected_candidates : [];
    var keeps = Array.isArray(payload.explicit_keep) ? payload.explicit_keep : [];
    var actualSeries = (Array.isArray(payload.actual_series) ? payload.actual_series : []).filter(function (row) { return row && row.date && finite(row.nikkei_close) !== null; });
    var series = (Array.isArray(payload.series) ? payload.series : []).filter(function (row) { return row && row.date && finite(row.nikkei_actual) !== null && finite(row.nikkei_close) !== null; });
    var historicalEvents = (Array.isArray(payload.historical_events) ? payload.historical_events : []).filter(function (event) { return event && event.date && event.label; });
    var warnings = Array.isArray(payload.warnings) ? payload.warnings.filter(Boolean) : [];
    var sources = Array.isArray(payload.sources) ? payload.sources : [];
    var status = String(meta.comparison_status || quality.data_state || "");
    var hasProxy = status === "public-contribution-proxy" && series.some(function (row) { return finite(row.ai_overheat_normalized) !== null && finite(row.ai_overheat_excluded) !== null; });
    var coverage = finite(quality.coverage_pct), dayCounts = quality.day_counts || {};
    var summaryNode = byId("nikkeiAiThreeSummary"), targetNode = byId("nikkeiAiTargetNames"), stockRows = byId("nikkeiAiStockRows"), qualityNode = byId("nikkeiAiQualityNotes"), badge = byId("nikkeiAiMethodBadge"), canvas = byId("nikkeiAiThreeSeriesChart"), notice = byId("nikkeiAiComparisonNotice"), title = byId("nikkeiAiChartTitle"), subtitle = byId("nikkeiAiChartSubtitle"), reading = byId("nikkeiAiReading"), eventTimeline = byId("nikkeiAiEventTimeline"), eventNote = byId("nikkeiAiEventNote");
    if (!summaryNode || !targetNode || !stockRows || !qualityNode) return;

    var actualByDate = {};
    (actualSeries.length ? actualSeries : series).forEach(function (row) {
      actualByDate[row.date] = { date: row.date, nikkei_close: finite(row.nikkei_close) };
    });
    series.forEach(function (row) {
      if (!actualByDate[row.date]) actualByDate[row.date] = { date: row.date, nikkei_close: finite(row.nikkei_close) };
    });
    var chartRows = Object.keys(actualByDate).sort().map(function (key) { return actualByDate[key]; }).filter(function (row) { return finite(row.nikkei_close) !== null; });
    var fullStart = chartRows[0] || {};
    var fullEnd = chartRows[chartRows.length - 1] || {};
    var proxyBaseClose = finite(series[0] && series[0].nikkei_close);
    var latestProxyRow = series[series.length - 1] || {};
    var latestActualClose = finite(summary.latest_actual_close);
    if (latestActualClose === null) latestActualClose = finite(latestProxyRow.nikkei_close);
    var latestNormalizedClose = finite(summary.latest_normalized_close);
    if (latestNormalizedClose === null && proxyBaseClose !== null) {
      var latestNormalizedIndex = finite(latestProxyRow.ai_overheat_normalized);
      latestNormalizedClose = latestNormalizedIndex === null ? null : proxyBaseClose * latestNormalizedIndex / 100;
    }
    var latestExcludedClose = finite(summary.latest_excluded_close);
    if (latestExcludedClose === null && proxyBaseClose !== null) {
      var latestExcludedIndex = finite(latestProxyRow.ai_overheat_excluded);
      latestExcludedClose = latestExcludedIndex === null ? null : proxyBaseClose * latestExcludedIndex / 100;
    }
    var latestActualMinusNormalized = finite(summary.actual_minus_normalized_jpy);
    if (latestActualMinusNormalized === null && latestActualClose !== null && latestNormalizedClose !== null) {
      latestActualMinusNormalized = latestActualClose - latestNormalizedClose;
    }
    var latestActualMinusExcluded = finite(summary.actual_minus_excluded_jpy);
    if (latestActualMinusExcluded === null && latestActualClose !== null && latestExcludedClose !== null) {
      latestActualMinusExcluded = latestActualClose - latestExcludedClose;
    }
    var latestAsOfDate = latestProxyRow.date || meta.market_date || "";
    function formatYen(value) {
      var amount = finite(value);
      return amount === null ? "未確認" : nikkeiFormat.format(amount) + "円";
    }
    function actualGapCaption(value) {
      var gap = finite(value);
      if (gap === null) return "実績との差は未確認";
      return gap >= 0 ? "実績より" + formatYen(gap) + "低い" : "実績より" + formatYen(-gap) + "高い";
    }
    function rangeText(startDate, endDate) {
      return startDate && endDate ? String(startDate) + "〜" + String(endDate) : "取得済み期間";
    }
    var eventAnchors = historicalEvents.map(function (event) {
      var anchor = null;
      for (var eventIndex = 0; eventIndex < chartRows.length; eventIndex += 1) {
        if (chartRows[eventIndex].date >= String(event.date)) { anchor = chartRows[eventIndex]; break; }
      }
      return {
        date: String(event.date), short_label: String(event.short_label || event.label), label: String(event.label),
        category: String(event.category || "市場の背景"), note: String(event.note || ""),
        source_label: String(event.source_label || "公式資料"), source_url: event.source_url || "",
        chart_date: anchor ? anchor.date : "", chart_close: anchor ? finite(anchor.nikkei_close) : null,
      };
    }).filter(function (event) { return event.chart_date && event.chart_close !== null; });

    var stateLabel = status === "public-contribution-proxy" ? "公開データproxy"
      : status === "data-insufficient-exact-reconstruction-inputs" ? "完全再構成モード：データ不足"
        : status === "actual-only-no-screened-candidates" ? "実績のみ（候補0社）" : "実績のみ（データ不足）";
    if (badge) badge.textContent = stateLabel + " / " + (meta.method_label || "データ状態を確認");
    if (notice) {
      notice.hidden = false;
      notice.innerHTML = hasProxy
        ? "<strong>" + escapeHtml(stateLabel) + "：寄与ベースの比較</strong><p>" + escapeHtml(meta.proxy_disclaimer || "合成系列は研究用proxyです。") + (coverage !== null && coverage < 90 ? " 10年全体の十分な連続カバレッジがないため、取得できた連続区間だけを表示しています。" : "") + "</p>"
        : "<strong>" + escapeHtml(stateLabel) + "</strong><p>" + escapeHtml(warnings[0] || "比較に必要な公開入力がそろっていません。") + " 欠損日はゼロ・補間・実績同値で埋めていません。</p>";
    }
    if (title) title.textContent = hasProxy ? "円建ての3系列比較（実績・標準化・AI候補除外）" : "日経平均の10年実績";
    if (subtitle) subtitle.textContent = hasProxy
      ? "実績は10年、2本のproxyは " + rangeText(meta.display_start_date, meta.display_end_date) + " の公開日次寄与が連続する区間だけを、同じ円単位で表示します。"
      : "日経平均の10年実績のみを表示しています。";
    if (canvas) canvas.setAttribute("aria-label", hasProxy ? "日経平均の実績、AI過熱候補をTOPIX並みに標準化した値、AI過熱候補を除いた残存部分を同じ円単位で示す3系列比較" : "日経平均の10年実績");

    if (reading) reading.innerHTML = hasProxy
      ? "<p><strong>一般市場並みに置換：</strong>対象候補の日次騰落をTOPIXの日次騰落に置き換えた研究用proxyです。比較開始日の実額を基準に円換算しています。</p><p><strong>残存部分：</strong>対象候補の日次寄与を外して残りを比率で表した研究用proxyです。公開入力がない過去へ延長していません。</p><p><strong>出来事の注記：</strong>各出来事は背景確認用であり、日経平均の変動を単一要因で説明するものではありません。カードから公式資料を直接確認できます。</p>"
      : "<p><strong>日経平均の実額：</strong>公開データで確認できる10年の価格水準を円建てで表示します。比較に必要な公開入力がそろわないため、2本のproxyは描きません。</p><p>原因を後付けで単一化せず、公式資料と実績を分けて確認します。</p>";

    var cards = hasProxy ? [
      ["日経平均・実績（" + latestAsOfDate + "）", formatYen(latestActualClose), "公式終値。3つとも同じ日経平均の円建て換算値です。"],
      ["AI過熱候補をTOPIX並みに標準化", formatYen(latestNormalizedClose), actualGapCaption(latestActualMinusNormalized) + "。対象候補の当日騰落をTOPIX騰落へ置換したproxyです。"],
      ["AI過熱候補を除いた残存部分", formatYen(latestExcludedClose), actualGapCaption(latestActualMinusExcluded) + "。対象候補の当日寄与を取り除いたproxyです。"],
      ["今回の自動選定", numberOne.format(targets.length) + "社", targets.length ? "固定20社ではなく、価格・寄与の客観条件を満たした候補だけです。" : "条件を満たす候補がないためproxyは表示しません。"],
      ["proxyの公開データ範囲", coverage === null ? "―" : numberOne.format(coverage) + "%", "exact " + numberOne.format(finite(dayCounts.exact) || 0) + "日 / missing " + numberOne.format(finite(dayCounts.missing) || 0) + "日"]
    ] : [
      ["日経平均・実績", formatYen(fullEnd.nikkei_close), (fullStart.date || "開始日") + "の" + formatYen(fullStart.nikkei_close) + "から " + formatPercent(summary.actual_full_period_return_pct, true)],
      ["候補ユニバース", numberOne.format(finite(summary.candidate_count) || 0) + "社", "既存の日本AI関連銘柄とキオクシアを毎回スクリーニングします。"],
      ["条件を満たした候補", numberOne.format(finite(summary.selected_candidate_count) || 0) + "社", "候補がなければ実績と同値の線を作りません。"],
      ["proxyの公開データ範囲", coverage === null ? "―" : numberOne.format(coverage) + "%", "公開日次ウエートがそろう連続区間だけを計算します。"],
      ["表示上の扱い", "実績のみ", "データ不足時は標準化・除外の値を推計しません。"]
    ];
    summaryNode.innerHTML = cards.map(function (card) { return '<article class="nikkei-ai-summary-card"><span>' + escapeHtml(card[0]) + "</span><strong>" + escapeHtml(card[1]) + "</strong><small>" + escapeHtml(card[2]) + "</small></article>"; }).join("");
    function eventSourceMarkup(event) {
      var href = safeHttpsUrl(event.source_url);
      return href ? '<a href="' + escapeHtml(href) + '" target="_blank" rel="noopener noreferrer">' + escapeHtml(event.source_label) + "</a>" : "<span>公式資料（リンク未確認）</span>";
    }
    if (eventTimeline) {
      eventTimeline.innerHTML = eventAnchors.length ? eventAnchors.map(function (event) {
        return '<article class="nikkei-ai-event-card"><div class="nikkei-ai-event-meta"><time datetime="' + escapeHtml(event.date) + '">' + escapeHtml(event.date) + '</time><span class="nikkei-ai-event-category">' + escapeHtml(event.category) + '</span></div><h5>' + escapeHtml(event.label) + '</h5><p>' + escapeHtml(event.note) + '</p>' + eventSourceMarkup(event) + '</article>';
      }).join("") : '<p class="nikkei-ai-event-empty">公式ソース付きの出来事データを確認中です。</p>';
    }
    if (eventNote) eventNote.textContent = "日経平均の値動きを単一の出来事で説明するものではありません。背景確認のため、各項目から公式資料を直接開けます。";
    targetNode.innerHTML = targets.length ? "<strong>本サイトの価格・寄与基準によるAI過熱候補：</strong>" + targets.map(function (item) { return escapeHtml((item.name || "名称未取得") + "（" + (item.code || "コード未取得") + "、" + (item.status === "manual_include" ? "手動追加" : "自動暫定選定") + "）"); }).join("、") : "<strong>本サイトの価格・寄与基準によるAI過熱候補：</strong>今回の公開データと設定では、3条件以上を満たす候補はありません。";

    function screenCell(item) {
      item = item || {};
      var value = finite(item.value), threshold = finite(item.threshold), result = item.met === true ? "該当" : item.met === false ? "非該当" : "判定不能";
      return '<span class="nikkei-ai-screen-cell">' + escapeHtml(value === null ? "―" : formatPercent(value, true)) + "<small>" + escapeHtml((threshold === null ? "" : "基準 " + numberOne.format(threshold) + "% / ") + result) + "</small></span>";
    }
    function candidateStatus(item) { return ({ auto_screened_provisional: "自動暫定選定", manual_include: "手動追加", manual_exclude: "手動除外", explicit_keep: "明示維持", not_selected: "非選定" })[item.status] || "要確認"; }
    stockRows.innerHTML = candidates.length ? candidates.map(function (item) {
      var condition = item.conditions || {}, current = finite(item.current_nikkei_weight_pct), peak = finite(item.peak_nikkei_weight_pct);
      return "<tr><td>" + escapeHtml(item.code || "―") + "</td><td>" + escapeHtml(item.name || "名称未取得") + "</td><td><strong>" + escapeHtml(candidateStatus(item)) + "</strong><small>" + escapeHtml(item.selection_reason || "") + "</small></td><td>" + screenCell(condition.A) + "</td><td>" + screenCell(condition.B) + "</td><td>" + screenCell(condition.C) + "</td><td>" + screenCell(condition.D) + "</td><td>" + escapeHtml((item.passed_conditions || []).join("・") || "なし") + "</td><td>" + escapeHtml(current === null ? "―" : formatPercent(current, false)) + " / 最大 " + escapeHtml(peak === null ? "―" : formatPercent(peak, false)) + "</td><td>" + escapeHtml(item.data_status || item.weight_method || "公開データ") + "</td></tr>";
    }).join("") : '<tr><td colspan="10">候補ユニバースを確認できませんでした。</td></tr>';

    var notes = [
      "<p><strong>実績期間：</strong>" + escapeHtml((meta.start_date || "―") + " → " + (meta.end_date || "―")) + "。表示区間は " + escapeHtml((meta.display_start_date || "―") + " → " + (meta.display_end_date || "―")) + " です。</p>",
      "<p><strong>日次品質：</strong>exact " + escapeHtml(numberOne.format(finite(dayCounts.exact) || 0)) + "日、reconstructed " + escapeHtml(numberOne.format(finite(dayCounts.reconstructed) || 0)) + "日、legacy_reconstructed " + escapeHtml(numberOne.format(finite(dayCounts.legacy_reconstructed) || 0)) + "日、missing " + escapeHtml(numberOne.format(finite(dayCounts.missing) || 0)) + "日。</p>",
      "<p><strong>ウエート：</strong>" + escapeHtml(quality.weight_method || "―") + "</p>",
      "<p><strong>価格：</strong>" + escapeHtml(quality.price_method || meta.price_field || "―") + "</p>"
    ];
    if (meta.market_date) notes.unshift("<p><strong>最終市場日：</strong>" + escapeHtml(meta.market_date) + "</p>");
    if (quality.membership_handling) notes.push("<p><strong>採用・除外日の扱い：</strong>" + escapeHtml(quality.membership_handling) + "</p>");
    if (finite(summary.current_combined_weight_pct) !== null || finite(summary.peak_combined_weight_pct) !== null) {
      notes.push("<p><strong>対象候補合計ウエート：</strong>現在 " + escapeHtml(formatPercent(summary.current_combined_weight_pct, false)) + "、比較期間の最大 " + escapeHtml(formatPercent(summary.peak_combined_weight_pct, false)) + "。この値はproxyの対象範囲を示すもので、公式指数の構成比ではありません。</p>");
    }
    var priceAudits = Array.isArray(quality.candidate_price_audit) ? quality.candidate_price_audit : [];
    var splitEventCount = priceAudits.reduce(function (total, item) { return total + (Array.isArray(item.split_events) ? item.split_events.length : 0); }, 0);
    if (priceAudits.length) notes.push("<p><strong>株式分割の確認：</strong>候補銘柄の分割イベントを " + escapeHtml(numberOne.format(splitEventCount)) + " 件取得。配当込みAdj Closeは使いません。</p>");
    var candidatePriceLinks = priceAudits.filter(function (item) { return safeHttpsUrl(item.source_url); }).map(function (item) { return nikkeiAiSourceMarkup({ label: String(item.code || "候補") + " Close", url: item.source_url }); });
    if (candidatePriceLinks.length) notes.push('<p class="nikkei-ai-source-links"><strong>候補別終値：</strong>' + candidatePriceLinks.join(" / ") + "</p>");
    if (keeps.length) notes.push("<p><strong>明示的に維持：</strong>" + keeps.map(function (item) { return escapeHtml((item.name || "名称未取得") + "（" + (item.code || "コード未取得") + "）"); }).join("、") + "。AIとの接点だけでは自動的に除外しません。</p>");
    if ((quality.missing_items || []).length) notes.push("<p><strong>未取得のため再構成に使っていない入力：</strong>" + escapeHtml(quality.missing_items.join("、")) + "</p>");
    if (finite(quality.missing_date_count) !== null) notes.push("<p><strong>欠損日：</strong>" + escapeHtml(numberOne.format(quality.missing_date_count)) + "日。該当日を0・補間・実績同値で埋めていません。</p>");
    if (warnings.length) notes.push('<ul class="nikkei-ai-warning-list">' + warnings.map(function (item) { return "<li>" + escapeHtml(item) + "</li>"; }).join("") + "</ul>");
    if (sources.length) notes.push('<p class="nikkei-ai-source-links"><strong>出典：</strong>' + sources.map(nikkeiAiSourceMarkup).join(" / ") + "</p>");
    qualityNode.innerHTML = notes.join("");

    if (state.nikkeiAiThreeSeriesChart) { state.nikkeiAiThreeSeriesChart.destroy(); state.nikkeiAiThreeSeriesChart = null; }
    if (typeof Chart === "undefined" || !canvas || !chartRows.length) return;

    var labels = chartRows.map(function (row) { return row.date; });
    var proxyByDate = {};
    series.forEach(function (row) { proxyByDate[row.date] = row; });
    var eventsByChartDate = {};
    eventAnchors.forEach(function (event) {
      event.chart_index = labels.indexOf(event.chart_date);
      if (!eventsByChartDate[event.chart_date]) eventsByChartDate[event.chart_date] = [];
      eventsByChartDate[event.chart_date].push(event);
    });
    function nominalProxyValue(row, field) {
      var proxyRow = proxyByDate[row.date] || {};
      var directValue = finite(proxyRow[field + "_close"]);
      if (directValue !== null) return directValue;
      var indexValue = finite(proxyRow[field]);
      return proxyBaseClose === null || indexValue === null ? null : proxyBaseClose * indexValue / 100;
    }
    var datasets = [{
      label: "日経平均・実績（円）",
      data: chartRows.map(function (row) { return finite(row.nikkei_close); }),
      borderColor: "#1b4d6f", backgroundColor: "rgba(27,77,111,.08)", borderWidth: 2.8, pointRadius: 0, tension: .12, spanGaps: false,
    }];
    if (hasProxy && proxyBaseClose !== null) {
      datasets.push({
        label: "AI過熱候補をTOPIX並みに標準化（円換算）",
        data: chartRows.map(function (row) { return nominalProxyValue(row, "ai_overheat_normalized"); }),
        borderColor: "#11836f", borderWidth: 2.4, borderDash: [7, 4], pointRadius: 0, tension: .12, spanGaps: false,
      });
      datasets.push({
        label: "AI過熱候補を除いた残存部分（円換算）",
        data: chartRows.map(function (row) { return nominalProxyValue(row, "ai_overheat_excluded"); }),
        borderColor: "#b64a3b", borderWidth: 2.2, borderDash: [2, 4], pointRadius: 0, tension: .12, spanGaps: false,
      });
    }
    var historicalEventPlugin = {
      id: "nikkeiAiHistoricalEvents",
      afterDatasetsDraw: function (chartInstance) {
        var options = chartInstance.options.plugins && chartInstance.options.plugins.nikkeiAiHistoricalEvents;
        var events = options && Array.isArray(options.events) ? options.events : [];
        var xScale = chartInstance.scales.x, yScale = chartInstance.scales.y, area = chartInstance.chartArea;
        if (!events.length || !xScale || !yScale || !area) return;
        var context = chartInstance.ctx, showLabels = !!options.showLabels;
        context.save();
        events.forEach(function (event, index) {
          if (!Number.isFinite(event.chart_index) || event.chart_index < 0) return;
          var x = xScale.getPixelForValue(event.chart_index);
          var y = yScale.getPixelForValue(event.chart_close);
          if (!Number.isFinite(x) || !Number.isFinite(y)) return;
          context.strokeStyle = "rgba(33, 104, 121, .32)";
          context.lineWidth = 1;
          context.setLineDash([3, 4]);
          context.beginPath(); context.moveTo(x, area.top); context.lineTo(x, area.bottom); context.stroke();
          context.setLineDash([]);
          context.fillStyle = "#f0a338";
          context.strokeStyle = "#ffffff";
          context.lineWidth = 1.5;
          context.beginPath(); context.arc(x, y, 3.5, 0, Math.PI * 2); context.fill(); context.stroke();
          if (showLabels) {
            var label = String(event.short_label || event.label);
            context.font = "600 10px system-ui, sans-serif";
            var width = context.measureText(label).width;
            var labelX = Math.max(area.left + 2, Math.min(x + 4, area.right - width - 2));
            var labelY = area.top + 13 + (index % 3) * 13;
            context.fillStyle = "#4e6875";
            context.fillText(label, labelX, labelY);
          }
        });
        context.restore();
      },
    };
    state.nikkeiAiThreeSeriesChart = new Chart(canvas, {
      type: "line",
      data: { labels: labels, datasets: datasets },
      plugins: eventAnchors.length ? [historicalEventPlugin] : [],
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { position: "bottom", labels: { color: chartTextColor(), boxWidth: 18, usePointStyle: true } },
          nikkeiAiHistoricalEvents: { events: eventAnchors, showLabels: !(window.matchMedia && window.matchMedia("(max-width: 700px)").matches) },
          tooltip: {
            callbacks: {
              title: function (items) { return items[0] ? items[0].label : ""; },
              label: function (context) {
                var value = finite(context.parsed && context.parsed.y);
                return context.dataset.label + " " + (value === null ? "未確認" : formatYen(value));
              },
              afterBody: function (items) {
                var index = items[0] && Number.isFinite(items[0].dataIndex) ? items[0].dataIndex : chartRows.length - 1;
                var row = chartRows[index] || {};
                var proxyRow = proxyByDate[row.date] || {};
                var lines = [];
                if (finite(row.nikkei_close) !== null) lines.push("日経平均終値 " + formatYen(row.nikkei_close));
                if (proxyRow.quality) lines.push("proxy品質 " + proxyRow.quality);
                if (finite(proxyRow.combined_weight_pct) !== null) lines.push("対象合計ウエート " + numberOne.format(proxyRow.combined_weight_pct) + "%");
                (eventsByChartDate[row.date] || []).forEach(function (event) { lines.push("出来事: " + event.label); });
                return lines;
              },
            },
          },
        },
        scales: {
          x: {
            grid: { display: false },
            ticks: {
              color: chartTextColor(),
              maxTicksLimit: window.matchMedia && window.matchMedia("(max-width: 700px)").matches ? 6 : 12,
              maxRotation: 0,
              callback: function (_value, index) { return String(labels[index] || "").slice(0, 7).replace("-", "/"); },
            },
          },
          y: {
            grid: { color: "rgba(100,115,134,.15)" },
            ticks: { color: chartTextColor(), callback: function (value) { return numberOne.format(value) + "円"; } },
            title: { display: true, text: "日経平均（円）", color: chartTextColor() },
          },
        },
      },
    });
  }

  function latestOfficialDisclosureForIssuer(issuerCode) {
    var target = String(issuerCode || "").toUpperCase().trim();
    if (!target) return null;
    var live = state.liveIntelligence || {};
    var briefingItems = ((live.briefing || {}).items || []);
    var cachedDisclosures = Array.isArray(live.companyDisclosureCache) ? live.companyDisclosureCache : [];
    var items = briefingItems.concat(cachedDisclosures).filter(function (item) {
      return item && String(item.issuerCode || "").toUpperCase().trim() === target
        && (/official/.test(String(item.sourceKind || "").toLowerCase()) || Boolean(item.disclosureId));
    });
    var financialItems = items.filter(function (item) {
      return /financial|earnings|決算/.test(String(item.disclosureCategory || "") + " " + String(item.topic || "") + " " + String(item.title || ""));
    });
    var candidates = financialItems.length ? financialItems : items;
    return candidates.sort(function (left, right) {
      return (briefingTimestamp(right) || 0) - (briefingTimestamp(left) || 0);
    })[0] || null;
  }

  function renderKioxiaLiveOverlay(kioxia) {
    var live = liveQuoteForKey("KIOXIA");
    var current = finite(live ? live.value : kioxia.close);
    var currentDate = live ? liveQuoteDate(live) : (kioxia.date || "");
    var peak = finite(kioxia.peak2026);
    var drawdown = peak !== null && current !== null ? (1 - current / peak) * 100 : finite(kioxia.drawdownFrom2026HighPct);
    if (current !== null) {
      byId("sakKioxiaCurrentDate").textContent = formatShortDate(currentDate) || "最新";
      byId("sakKioxiaCurrent").textContent = formatPrice(current, "JPY");
      byId("sakKioxiaFall").textContent = "高値から −" + formatPercent(drawdown, false);
    }
    byId("sakKioxiaCurrentMeta").textContent = live
      ? "ライブ価格・" + liveQuoteStateLabel(live) + " / 値 " + formatLiveTime(liveQuoteTime(live), "")
      : "保存済み日次終値 / " + (currentDate || "日付未確認");

    var calm = kioxia.calmValuation || {};
    var referencePrice = finite(calm.referencePriceJpy);
    var multiple = current !== null && referencePrice !== null && referencePrice > 0 ? current / referencePrice : null;
    byId("sakKioxiaCalmGap").textContent = multiple === null
      ? "現在値との差は未確認です。"
      : (live ? "ライブ価格" : "最新終値") + formatPrice(current, "JPY") + "は中心値の約" + numberTwo.format(multiple) + "倍（中心値比" + formatPercent((multiple - 1) * 100, true) + "）。株価がこの差を維持するには、売上成長、利益率、評価倍率のいずれかが本モデルより高く続く必要があります。";

    var disclosure = latestOfficialDisclosureForIssuer(kioxia.issuerCode || "285A");
    var report = ((calm.reports || [])[0]) || {};
    var sourceUrl = safeHttpsUrl(disclosure && disclosure.url) || safeHttpsUrl(report.sourceUrl)
      || "https://www.kioxia-holdings.com/ja-jp/ir.html";
    if (disclosure) {
      var copy = briefingCopy(disclosure);
      var title = copy.japaneseTitle || disclosure.title || "最新の公式IR";
      var summary = copy.japaneseSummary || disclosure.summary || "公式開示の内容はリンク先で確認してください。";
      byId("sakKioxiaLiveIrHeading").textContent = "最新の公式IR：" + title;
      byId("sakKioxiaLiveIrSummary").textContent = briefingPublicationLabel(disclosure) + " / " + summary;
      byId("sakKioxiaLiveIrLink").textContent = "公式開示を直接開く";
    } else {
      byId("sakKioxiaLiveIrHeading").textContent = "最新の公式IRを確認する";
      byId("sakKioxiaLiveIrSummary").textContent = report.periodLabel
        ? report.periodLabel + "の会社公表資料を表示しています。ライブ適時開示が届いた場合はここを自動で差し替えます。"
        : "ライブ適時開示は未確認です。公式IRページで確認してください。";
      byId("sakKioxiaLiveIrLink").textContent = "キオクシアIRを開く";
    }
    byId("sakKioxiaLiveIrLink").href = sourceUrl;
  }

  function initializeNikkeiSettings() {
    if (state.nikkeiBottomInitialized || !state.data) return;
    var reference = state.data.market.nikkeiValuationReference || {};
    var scenario = NIKKEI_PRESETS[state.nikkeiBottom.scenario] ? state.nikkeiBottom.scenario : "standard";
    var preset = NIKKEI_PRESETS[scenario];
    state.nikkeiBottom.scenario = scenario;
    if (finite(state.nikkeiBottom.referencePrice) === null) state.nikkeiBottom.referencePrice = finite(reference.price);
    if (finite(state.nikkeiBottom.currentPe) === null) state.nikkeiBottom.currentPe = finite(reference.indexPe);
    if (finite(state.nikkeiBottom.currentPb) === null) state.nikkeiBottom.currentPb = finite(reference.indexPb);
    if (finite(state.nikkeiBottom.epsCut) === null) state.nikkeiBottom.epsCut = preset.epsCut;
    if (finite(state.nikkeiBottom.targetPe) === null) state.nikkeiBottom.targetPe = preset.targetPe;
    if (finite(state.nikkeiBottom.targetPb) === null) state.nikkeiBottom.targetPb = preset.targetPb;
    if (finite(state.nikkeiBottom.historyDrawdown) === null) state.nikkeiBottom.historyDrawdown = preset.historyDrawdown;
    state.nikkeiBottomInitialized = true;
    syncNikkeiControls();
  }

  function syncNikkeiControls() {
    var settings = state.nikkeiBottom;
    byId("nikkeiReferencePrice").value = finite(settings.referencePrice) === null ? "" : settings.referencePrice;
    byId("nikkeiCurrentPe").value = finite(settings.currentPe) === null ? "" : settings.currentPe;
    byId("nikkeiCurrentPb").value = finite(settings.currentPb) === null ? "" : settings.currentPb;
    byId("nikkeiEpsCut").value = settings.epsCut;
    byId("nikkeiTargetPe").value = settings.targetPe;
    byId("nikkeiTargetPb").value = settings.targetPb;
    byId("nikkeiHistoricalDrawdown").value = settings.historyDrawdown;
    ["sakEpsInput", "sakTargetPeInput", "sakBpsInput", "sakRoeInput", "sakGrowthYearsInput"].forEach(function (id) {
      byId(id).addEventListener("input", function () {
        readSakakibaraControls();
        if (state.data) renderSakakibaraFairValue(state.data.market.sakakibaraAnalysis || {});
      });
    });
    byId("resetSakakibaraAssumptions").addEventListener("click", function () {
      var article = state.data && state.data.market.sakakibaraAnalysis
        ? state.data.market.sakakibaraAnalysis.articleScenario || {}
        : {};
      state.sakakibaraFairValue = {
        eps: finite(article.eps),
        targetPe: finite(article.targetPe),
        bps: finite(article.bps),
        roePct: finite(article.roePct),
        growthYears: finite(article.growthYears),
      };
      saveSakakibaraFairValue();
      syncSakakibaraControls();
      if (state.data) renderSakakibaraFairValue(state.data.market.sakakibaraAnalysis || {});
    });
    document.querySelectorAll('input[name="nikkeiScenario"]').forEach(function (input) {
      input.checked = input.value === settings.scenario;
    });
    updateNikkeiOutputs();
  }

  function updateNikkeiOutputs() {
    byId("nikkeiEpsCutOutput").textContent = formatPercent(finite(byId("nikkeiEpsCut").value), false);
    byId("nikkeiTargetPeOutput").textContent = numberOne.format(finite(byId("nikkeiTargetPe").value)) + "倍";
    byId("nikkeiTargetPbOutput").textContent = numberOne.format(finite(byId("nikkeiTargetPb").value)) + "倍";
    byId("nikkeiHistoricalDrawdownOutput").textContent = formatPercent(finite(byId("nikkeiHistoricalDrawdown").value), false);
  }

  function readNikkeiControls() {
    var read = function (id) {
      var raw = byId(id).value.trim();
      return raw === "" ? null : finite(raw);
    };
    state.nikkeiBottom.referencePrice = read("nikkeiReferencePrice");
    state.nikkeiBottom.currentPe = read("nikkeiCurrentPe");
    state.nikkeiBottom.currentPb = read("nikkeiCurrentPb");
    state.nikkeiBottom.epsCut = read("nikkeiEpsCut");
    state.nikkeiBottom.targetPe = read("nikkeiTargetPe");
    state.nikkeiBottom.targetPb = read("nikkeiTargetPb");
    state.nikkeiBottom.historyDrawdown = read("nikkeiHistoricalDrawdown");
    saveNikkeiBottom();
    updateNikkeiOutputs();
  }

  function applyNikkeiPreset(name) {
    var preset = NIKKEI_PRESETS[name] || NIKKEI_PRESETS.standard;
    state.nikkeiBottom.scenario = name in NIKKEI_PRESETS ? name : "standard";
    state.nikkeiBottom.epsCut = preset.epsCut;
    state.nikkeiBottom.targetPe = preset.targetPe;
    state.nikkeiBottom.targetPb = preset.targetPb;
    state.nikkeiBottom.historyDrawdown = preset.historyDrawdown;
    saveNikkeiBottom();
    syncNikkeiControls();
    if (state.data) renderNikkeiBottom();
  }

  function calculateNikkeiBottom() {
    var nikkei = state.data.market.series.NIKKEI || {};
    var settings = state.nikkeiBottom;
    var current = finite(nikkei.close);
    var peak = finite(nikkei.peak3y);
    var referencePrice = finite(settings.referencePrice);
    var currentPe = finite(settings.currentPe);
    var currentPb = finite(settings.currentPb);
    var epsCut = finite(settings.epsCut);
    var targetPe = finite(settings.targetPe);
    var targetPb = finite(settings.targetPb);
    var historyDrawdown = finite(settings.historyDrawdown);
    if ([current, peak, referencePrice, currentPe, currentPb, targetPe, targetPb, historyDrawdown].some(function (value) { return value === null || value <= 0; }) || epsCut === null || epsCut < 0 || epsCut > 100 || historyDrawdown > 100) return null;
    var currentEps = referencePrice / currentPe;
    var currentBps = referencePrice / currentPb;
    var earningsAnchor = currentEps * (1 - epsCut / 100) * targetPe;
    var bookAnchor = currentBps * targetPb;
    var historyAnchor = peak * (1 - historyDrawdown / 100);
    var anchors = [earningsAnchor, bookAnchor, historyAnchor];
    var lower = Math.min.apply(Math, anchors);
    var upper = Math.max.apply(Math, anchors);
    var center = median(anchors);
    var denominator = peak - upper;
    var proximity = current <= upper ? 100 : denominator > 0 ? clamp((peak - current) / denominator * 100, 0, 100) : 0;
    return {
      scenario: settings.scenario,
      scenarioLabel: (NIKKEI_PRESETS[settings.scenario] || NIKKEI_PRESETS.standard).label,
      current: current,
      peak: peak,
      referencePrice: referencePrice,
      currentPe: currentPe,
      currentPb: currentPb,
      currentEps: currentEps,
      currentBps: currentBps,
      epsCut: epsCut,
      targetPe: targetPe,
      targetPb: targetPb,
      historyDrawdown: historyDrawdown,
      earningsAnchor: earningsAnchor,
      bookAnchor: bookAnchor,
      historyAnchor: historyAnchor,
      lower: lower,
      upper: upper,
      center: center,
      proximity: proximity,
      remainingToUpperPct: current > upper ? (1 - upper / current) * 100 : 0,
      belowLowerPct: current < lower ? (1 - current / lower) * 100 : 0,
    };
  }

  function confirmationItem(id, title, score, max, status, detail) {
    return { id: id, title: title, score: score, max: max, status: status, detail: detail };
  }

  function assessNikkeiConfirmation(model) {
    var nikkei = state.data.market.series.NIKKEI || {};
    var hy = state.data.macro.highYieldOas || {};
    var basket = state.data.market.japanAiBasket || {};
    var current = model.current;
    var nearZone = current <= model.upper * 1.10;
    var reachedZone = current <= model.upper;
    var zoneScore = reachedZone ? 40 : nearZone ? 20 : 0;
    var zoneStatus = reachedZone ? "pass" : nearZone ? "watch" : "fail";
    var zoneDetail = reachedZone
      ? (current < model.lower ? "想定下端を下回っています。前提を再点検し、反転確認を優先します。" : "選択した底値ゾーンへ到達しています。")
      : nearZone ? "ゾーン上端まで10%以内です。" : "まだ底値ゾーン上端より高い位置です。";

    var daysSinceLow = finite(nikkei.tradingDaysSince120dLow);
    var rebound = finite(nikkei.reboundFrom120dLowPct);
    var basePass = daysSinceLow !== null && rebound !== null && daysSinceLow >= 15 && rebound >= 8;
    var baseWatch = daysSinceLow !== null && rebound !== null && daysSinceLow >= 7 && rebound >= 4;
    var baseScore = basePass ? 25 : baseWatch ? 12 : 0;
    var baseDetail = daysSinceLow === null || rebound === null
      ? "120取引日の安値情報を取得できません。"
      : "120日安値から" + formatPercent(rebound, true) + "、安値から" + numberOne.format(daysSinceLow) + "取引日経過。";

    var above50 = nikkei.aboveSma50 === true;
    var slope50 = finite(nikkei.sma50Slope20dPct);
    var trendPass = above50 && slope50 !== null && slope50 > 0;
    var trendWatch = above50 || (slope50 !== null && slope50 > 0);
    var trendScore = trendPass ? 20 : trendWatch ? 10 : 0;
    var trendDetail = "終値は50日線の" + (above50 ? "上" : "下") + "、50日線の20日変化は" + formatPercent(slope50, true) + "。";

    var creditTurn = finite(hy.declineFrom3mHighPctPoints);
    var creditPass = creditTurn !== null && creditTurn >= 0.5;
    var creditWatch = creditTurn !== null && creditTurn >= 0.25;
    var creditScore = creditPass ? 10 : creditWatch ? 5 : 0;
    var creditDetail = creditTurn === null
      ? "信用スプレッドの3か月高値を確認できません。"
      : "HY OASは3か月高値から" + numberOne.format(creditTurn * 100) + "bp縮小。";

    var breadth = finite(basket.breadthBelowSma200Pct);
    var breadthPass = breadth !== null && breadth <= 50;
    var breadthWatch = breadth !== null && breadth <= 70;
    var breadthScore = breadthPass ? 5 : breadthWatch ? 2 : 0;
    var breadthDetail = breadth === null
      ? "日本AI・半導体連動8社の広がりを確認できません。"
      : "日本AI・半導体連動8社の200日線割れは" + formatPercent(breadth, false) + "。本サイト独自の代理指標で、日経225全銘柄の騰落数ではありません。";

    var rawScore = zoneScore + baseScore + trendScore + creditScore + breadthScore;
    var total = zoneScore === 0 ? 0 : rawScore;
    var label;
    if (zoneScore === 0) label = "価格帯に未到達：反転判定は保留";
    else if (current < model.lower && total < 75) label = "ストレス想定を超過：底打ちは未確認";
    else if (total >= 75) label = "底打ち確認が強い";
    else if (total >= 55) label = "反転証拠が増えている";
    else if (total >= 35) label = "初期反転の可能性";
    else label = "底打ちは未確認";

    return {
      score: total,
      rawScore: rawScore,
      label: label,
      nearZone: nearZone,
      reachedZone: reachedZone,
      items: [
        confirmationItem("zone", "底値ゾーンへの到達", zoneScore, 40, zoneStatus, zoneDetail),
        confirmationItem("base", "安値更新の停止と反発", baseScore, 25, basePass ? "pass" : baseWatch ? "watch" : "fail", baseDetail),
        confirmationItem("trend", "50日線の反転", trendScore, 20, trendPass ? "pass" : trendWatch ? "watch" : "fail", trendDetail),
        confirmationItem("credit", "信用不安の後退", creditScore, 10, creditPass ? "pass" : creditWatch ? "watch" : creditTurn === null ? "unknown" : "fail", creditDetail),
        confirmationItem("breadth", "下落の広がりの改善", breadthScore, 5, breadthPass ? "pass" : breadthWatch ? "watch" : breadth === null ? "unknown" : "fail", breadthDetail),
      ],
    };
  }

  function renderNikkeiBottomChart(model) {
    if (typeof Chart === "undefined") return;
    if (state.nikkeiBottomChart) state.nikkeiBottomChart.destroy();
    state.nikkeiBottomChart = new Chart(byId("nikkeiBottomChart"), {
      type: "bar",
      data: {
        labels: ["現在値", "歴史下落率", "利益×PER", "純資産×PBR"],
        datasets: [{
          data: [model.current, model.historyAnchor, model.earningsAnchor, model.bookAnchor],
          backgroundColor: ["#173854", "#6552a3", "#c94b18", "#087f75"],
          borderWidth: 0,
        }],
      },
      options: {
        indexAxis: "y",
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: function (context) { return formatNikkei(context.parsed.x); } } },
        },
        scales: {
          x: { beginAtZero: true, grid: { color: "rgba(100,115,134,.15)" }, ticks: { color: chartTextColor(), callback: function (value) { return nikkeiFormat.format(value); } } },
          y: { grid: { display: false }, ticks: { color: chartTextColor(), font: { weight: "bold" } } },
        },
      },
    });
  }

  function renderNikkeiHistory() {
    var episodes = state.data.market.historicalEpisodes || [];
    var useText = function (id) {
      if (id === "covid-japan" || id === "growth-reset-2021") return "浅いシナリオの参照";
      if (id === "gfc-japan" || id === "japan-bubble-first-leg") return "深いシナリオの参照";
      if (id === "dotcom") return "AI期待崩壊の極端例";
      return "長期的な下限例。標準値にはしない";
    };
    byId("nikkeiHistoryRows").innerHTML = episodes.map(function (episode) {
      var duration = episode.durationDays < 365
        ? numberOne.format(episode.durationDays / 30.44) + "か月"
        : numberOne.format(episode.durationDays / 365.25) + "年";
      return "<tr><th>" + escapeHtml(episode.name) + "<small>" + escapeHtml(episode.note) + "</small></th>"
        + "<td>" + escapeHtml(episode.index) + "</td>"
        + "<td>" + formatHistoricalIndex(episode.peak, episode.index) + "<small>" + escapeHtml(episode.peakDate) + "</small></td>"
        + "<td>" + formatHistoricalIndex(episode.trough, episode.index) + "<small>" + escapeHtml(episode.troughDate) + "</small></td>"
        + "<td class=\"negative\">−" + formatPercent(episode.drawdownPct, false) + "</td>"
        + "<td>" + duration + "</td><td>" + escapeHtml(useText(episode.id)) + "</td></tr>";
    }).join("");
  }

  function formatDotcomQuote(value, unit) {
    var numeric = finite(value);
    if (numeric === null) return "未取得";
    var formatted = Math.abs(numeric) < 1000 && Math.abs(numeric % 1) > 0.001
      ? numberOne.format(numeric)
      : nikkeiFormat.format(Math.round(numeric));
    return formatted + (unit === "円" ? "円" : " pt");
  }

  function dotcomStressBlock(scenario) {
    if (!scenario || !scenario.available) {
      return "<div class='dotcom-stress-unavailable'><strong>直近終値を取得できませんでした</strong><small>歴史比較は表示できます。次回更新時に再取得します。</small></div>";
    }
    var unit = scenario.quoteUnit || "指数ポイント";
    var referenceLabel = scenario.referenceWindow === "japan-extended"
      ? "日本の延長窓の最大下落"
      : scenario.referenceWindow === "company-peak-to-post-dotcom-trough" ? "銘柄自身のピーク→谷" : "共通比較窓の最大下落";
    return "<div class='dotcom-stress-flow'>"
      + "<div><span>取得できた直近終値</span><strong>" + formatDotcomQuote(scenario.currentClose, unit) + "</strong><small>市場日 " + escapeHtml(scenario.quoteDate || "未確認") + "</small></div>"
      + "<i aria-hidden='true'>→</i>"
      + "<div class='is-stress'><span>機械的ストレス換算値</span><strong>" + formatDotcomQuote(scenario.stressPrice, unit) + "</strong><small>" + escapeHtml(referenceLabel) + " " + formatDrawdown(scenario.historicalDrawdownPct) + "</small></div>"
      + "</div>"
      + "<div class='dotcom-stress-meta'><span>残存率 <strong>" + formatPercent((scenario.historicalRetentionRatio || 0) * 100, false) + "</strong></span>"
      + "<span>追加下落額 <strong>−" + formatDotcomQuote(scenario.additionalDownsideValue, unit) + "</strong></span>"
      + "<span>現在値 ÷ 換算値 <strong>" + numberOne.format(scenario.currentToStressMultiple) + "倍</strong></span></div>";
  }

  function renderDotComComparison() {
    var comparison = state.data && state.data.market ? state.data.market.dotComComparison || {} : {};
    var rows = Array.isArray(comparison.rows) ? comparison.rows : [];
    var summaries = Array.isArray(comparison.groupSummaries) ? comparison.groupSummaries : [];
    var windowInfo = comparison.window || {};
    var summaryByGroup = {};
    summaries.forEach(function (summary) { summaryByGroup[summary.group] = summary; });

    if (!rows.length) {
      byId("dotcomWindowBasis").textContent = "歴史比較データを読み込めませんでした。";
      byId("dotcomGroupSummary").innerHTML = "";
      byId("dotcomComparisonRows").innerHTML = "";
      byId("dotcomComparisonCards").innerHTML = "";
      byId("dotcomDividendCase").innerHTML = "<p>連続配当ケースを読み込めませんでした。</p>";
      byId("dotcomDividendCase").classList.remove("is-loading");
      byId("dotcomKeyFinding").innerHTML = "";
      return;
    }

    byId("dotcomWindowBasis").innerHTML =
      "<div><span>比較窓</span><strong>" + escapeHtml(windowInfo.startDate || "") + " → " + escapeHtml(windowInfo.endDate || "") + "</strong><small>" + escapeHtml(windowInfo.definition || "") + "</small></div>"
      + "<div><span>同じ期間の騰落率</span><strong>窓の初日から最終日</strong><small>開始時に保有し続けた場合の変化。銘柄自身の天井とは限りません。</small></div>"
      + "<div><span>期間内の最大下落</span><strong>銘柄ごとの高値から安値</strong><small>途中で経験した最大の含み損に近く、資金管理にはこちらが重要です。</small></div>"
      + "<div><span>日本の延長期間</span><strong>～" + escapeHtml(comparison.japanExtendedEndDate || "") + "</strong><small>日本株はNASDAQの底後も下げたため、国内銘柄だけ延長して確認します。</small></div>";

    byId("dotcomGroupSummary").innerHTML = summaries.map(function (summary) {
      var groupClass = "group-" + String(summary.group || "").replace(/[^a-z-]/g, "");
      return "<article class='dotcom-summary-item " + groupClass + "'>"
        + "<span>" + escapeHtml(summary.label || summary.group) + "</span>"
        + "<strong>" + formatDrawdown(summary.medianMaxDrawdownPct) + "</strong>"
        + "<small>期間内最大下落の中央値（" + escapeHtml(summary.count) + "系列）</small>"
        + "<p>同じ窓の騰落率中央値 " + formatPercent(summary.medianWindowReturnPct, true) + "</p>"
        + "</article>";
    }).join("");

    var dividendCase = comparison.dividendContinuityCase || {};
    var evidence = dividendCase.selectionEvidence || {};
    var caseScenario = dividendCase.stressScenario || {};
    var caseLinks = [];
    if (evidence.marketSegmentSourceUrl) caseLinks.push("<a href='" + escapeHtml(evidence.marketSegmentSourceUrl) + "' target='_blank' rel='noopener'>東証プライム区分</a>");
    if (evidence.dividendSourceUrl) caseLinks.push("<a href='" + escapeHtml(evidence.dividendSourceUrl) + "' target='_blank' rel='noopener'>配当の公式根拠</a>");
    if (dividendCase.historicalPriceSourceUrl) caseLinks.push("<a href='" + escapeHtml(dividendCase.historicalPriceSourceUrl) + "' target='_blank' rel='noopener'>当時の価格履歴</a>");
    if (dividendCase.currentPriceSourceUrl) caseLinks.push("<a href='" + escapeHtml(dividendCase.currentPriceSourceUrl) + "' target='_blank' rel='noopener'>現在値の取得元</a>");
    byId("dotcomDividendCase").classList.remove("is-loading");
    byId("dotcomDividendCase").innerHTML = dividendCase.id
      ? "<div class='dotcom-case-topline'><div><span class='dotcom-case-eyebrow'>独立検証例・群中央値には不算入</span><h4>" + escapeHtml(dividendCase.name || "") + " <small>" + escapeHtml(dividendCase.symbol || "") + "</small></h4></div>"
        + "<div class='dotcom-continuity-badges'><span>" + escapeHtml(evidence.marketSegment || "東証プライム") + "</span><span>直近" + escapeHtml(evidence.dividendFiscalYearCount || "20") + "期で無配なし</span><span>" + escapeHtml(evidence.dividendFiscalYearCount || "20") + "期連続増配</span></div></div>"
        + "<p class='dotcom-case-thesis'>実需型の小売企業で配当を継続していても、市場・景気・信用の悪化から株価は切り離されません。選定条件は<strong>20年以上、各期の年間配当が0円超</strong>であり、「20年間無配」ではありません。</p>"
        + "<div class='dotcom-case-history'><div><span>ITバブル期の先行ピーク</span><strong>" + formatDotcomQuote(dividendCase.peakClose, "円") + "</strong><small>" + escapeHtml(dividendCase.peakDate || "") + "</small></div><i aria-hidden='true'>→</i><div><span>その後の最安値</span><strong>" + formatDotcomQuote(dividendCase.troughClose, "円") + "</strong><small>" + escapeHtml(dividendCase.troughDate || "") + " / " + formatDrawdown(dividendCase.historicalDrawdownPct) + "</small></div></div>"
        + dotcomStressBlock(caseScenario)
        + "<div class='dotcom-case-evidence'><p><strong>配当条件：</strong>" + escapeHtml(evidence.dividendCondition || "") + "</p><p><strong>価格基準：</strong>" + escapeHtml(dividendCase.historicalPriceBasis || "") + "</p><p><strong>読み方：</strong>" + escapeHtml(dividendCase.note || "") + "</p></div>"
        + "<div class='dotcom-source-links'>" + caseLinks.join("") + "</div>"
        + "<p class='dotcom-nonforecast'>上の換算値は企業価値・将来利益・将来配当を織り込まない機械計算です。予測株価、目標株価、適正値、底値ではありません。</p>"
      : "<p>連続配当ケースを読み込めませんでした。</p>";

    byId("dotcomStressWarning").textContent = (comparison.stressInterpretation || "")
      + " 歴史12系列は「" + (comparison.priceBasis || "価格履歴") + "」、現在値は「" + (comparison.currentQuoteBasis || "直近終値") + "」です。";

    byId("dotcomComparisonCards").innerHTML = rows.map(function (row) {
      var summary = summaryByGroup[row.group] || {};
      var groupClass = "group-" + String(row.group || "").replace(/[^a-z-]/g, "");
      var scenario = row.stressScenario || {};
      var extended = finite(row.extendedMaxDrawdownPct);
      var extendedText = extended === null
        ? "<div><span>日本の延長窓</span><strong>対象外</strong><small>米国は共通比較窓で完結</small></div>"
        : "<div><span>日本の延長窓</span><strong>" + formatDrawdown(extended) + "</strong><small>" + escapeHtml(row.extendedPeakDate || "") + " → " + escapeHtml(row.extendedTroughDate || "") + "</small></div>";
      var links = "<a href='" + escapeHtml(row.sourceUrl || "#") + "' target='_blank' rel='noopener'>価格履歴</a>";
      if (row.classificationSourceUrl) links += "<a href='" + escapeHtml(row.classificationSourceUrl) + "' target='_blank' rel='noopener'>分類根拠</a>";
      return "<article class='dotcom-company-card " + groupClass + "'>"
        + "<div class='dotcom-company-head'><span class='dotcom-group-tag'>" + escapeHtml(summary.label || row.group) + "</span><h5>" + escapeHtml(row.name || "") + "</h5><small>" + escapeHtml(row.region || "") + " / " + escapeHtml(row.symbol || "") + "</small></div>"
        + "<div class='dotcom-history-metrics'><div><span>共通窓の騰落率</span><strong class='" + cssValueClass(row.windowReturnPct, false) + "'>" + formatPercent(row.windowReturnPct, true) + "</strong><small>" + escapeHtml(row.startDate || "") + " → " + escapeHtml(row.endDate || "") + "</small></div>"
        + "<div><span>期間内の最大下落</span><strong class='negative'>" + formatDrawdown(row.maxDrawdownPct) + "</strong><small>" + escapeHtml(row.peakDate || "") + " → " + escapeHtml(row.troughDate || "") + "</small></div>" + extendedText + "</div>"
        + dotcomStressBlock(scenario)
        + "<p class='dotcom-card-note'>" + escapeHtml(row.note || "") + "</p><div class='dotcom-source-links'>" + links + "</div>"
        + "</article>";
    }).join("");

    byId("dotcomComparisonRows").innerHTML = rows.map(function (row) {
      var summary = summaryByGroup[row.group] || {};
      var groupClass = "group-" + String(row.group || "").replace(/[^a-z-]/g, "");
      var extended = finite(row.extendedMaxDrawdownPct);
      var extendedCell = extended === null
        ? "<span class='not-applicable'>対象外</span><small>米国の比較窓で確認</small>"
        : "<strong>" + formatDrawdown(extended) + "</strong><small>" + escapeHtml(row.extendedPeakDate || "") + " → " + escapeHtml(row.extendedTroughDate || "") + "</small>";
      var classificationLink = row.classificationSourceUrl
        ? " <a href='" + escapeHtml(row.classificationSourceUrl) + "' target='_blank' rel='noopener'>分類根拠</a>"
        : "";
      return "<tr class='" + groupClass + "'>"
        + "<th><span class='dotcom-group-tag'>" + escapeHtml(summary.label || row.group) + "</span><strong>" + escapeHtml(row.name) + "</strong><small>" + escapeHtml(row.region) + " / " + escapeHtml(row.symbol) + "</small></th>"
        + "<td class='" + cssValueClass(row.windowReturnPct, false) + "'><strong>" + formatPercent(row.windowReturnPct, true) + "</strong><small>" + escapeHtml(row.startDate) + " → " + escapeHtml(row.endDate) + "</small></td>"
        + "<td class='negative'><strong>" + formatDrawdown(row.maxDrawdownPct) + "</strong><small>" + escapeHtml(row.peakDate) + " → " + escapeHtml(row.troughDate) + "</small></td>"
        + "<td class='negative'>" + extendedCell + "</td>"
        + "<td><p>" + escapeHtml(row.note) + "</p><a href='" + escapeHtml(row.sourceUrl) + "' target='_blank' rel='noopener'>価格履歴</a>" + classificationLink + "</td>"
        + "</tr>";
    }).join("");

    var direct = summaryByGroup["direct-tech"] || {};
    var broad = summaryByGroup["broad-market"] || {};
    var nonTech = summaryByGroup["non-tech"] || {};
    var rowById = {};
    rows.forEach(function (row) { rowById[row.id] = row; });
    var toyota = rowById.toyota || {};
    var sony = rowById.sony || {};
    var honda = rowById.honda || {};
    byId("dotcomKeyFinding").innerHTML =
      "<div><span>01</span><p><strong>直撃群だけでなく市場全体も大きく下落</strong>IT・半導体直撃群の最大下落中央値は" + formatDrawdown(direct.medianMaxDrawdownPct) + "、市場全体でも" + formatDrawdown(broad.medianMaxDrawdownPct) + "でした。同時期には景気・利益見通し・投資家のリスク許容度の悪化も重なり、下落はIT株だけにとどまりませんでした。</p></div>"
      + "<div><span>02</span><p><strong>非ITは下落が小さい傾向でも無傷ではない</strong>非IT" + escapeHtml(nonTech.count || 0) + "社の最大下落中央値は" + formatDrawdown(nonTech.medianMaxDrawdownPct) + "。トヨタは最大" + formatDrawdown(toyota.maxDrawdownPct) + "、ソニーは技術感応型として" + formatDrawdown(sony.maxDrawdownPct) + "でした。</p></div>"
      + "<div><span>03</span><p><strong>終点だけを見ると途中の痛みを見落とす</strong>ホンダは同じ期間の終点では" + formatPercent(honda.windowReturnPct, true) + "でも、途中の最大下落は" + formatDrawdown(honda.maxDrawdownPct) + "でした。底値で買う計画には、最終リターンより途中の最大下落と反転条件が重要です。</p></div>";

    byId("dotcomOverlapWarning").textContent = comparison.overlapWarning || "";
    byId("dotcomSelectionWarning").textContent = comparison.selectionWarning || "";
  }
  function renderNikkeiChecklist(confirmation) {
    byId("nikkeiChecklist").innerHTML = confirmation.items.map(function (item) {
      var icon = item.status === "pass" ? "check" : item.status === "watch" ? "clock-3" : item.status === "unknown" ? "circle-help" : "minus";
      var label = item.status === "pass" ? "充足" : item.status === "watch" ? "接近" : item.status === "unknown" ? "未確認" : "未充足";
      return "<div class=\"check-item is-" + item.status + "\"><i data-lucide=\"" + icon + "\" aria-hidden=\"true\"></i><div><strong>" + escapeHtml(item.title) + "</strong><span>" + item.score + "/" + item.max + "点・" + label + "</span><p>" + escapeHtml(item.detail) + "</p></div></div>";
    }).join("");
  }

  function renderObservationLadder(model, confirmation) {
    var levels = [
      { name: "観測1", value: model.upper, description: "底値ゾーン上端。利益・簿価・歴史のいずれかが最初に示す水準。", reached: model.current <= model.upper },
      { name: "観測2", value: model.center, description: "3アンカーの中央値。複数の方法が重なる中心候補。", reached: model.current <= model.center },
      { name: "観測3", value: model.lower, description: "底値ゾーン下端。選択シナリオの最も厳しいアンカー。", reached: model.current <= model.lower },
      { name: "確認", value: null, description: "価格到達後に底打ち確認度75点以上。安値を一点で当てる代わりの反転条件。", reached: confirmation.score >= 75 },
    ];
    byId("nikkeiObservationLadder").innerHTML = levels.map(function (level, index) {
      return "<div class=\"observation-level " + (level.reached ? "is-reached" : "") + "\"><span>0" + (index + 1) + "</span><div><strong>" + level.name + (level.value === null ? "" : "・" + formatNikkei(level.value)) + "</strong><p>" + escapeHtml(level.description) + "</p></div><em>" + (level.reached ? "条件到達" : "未到達") + "</em></div>";
    }).join("");
  }

  function renderNikkeiBottom() {
    initializeNikkeiSettings();
    var nikkei = state.data.market.series.NIKKEI || {};
    var reference = state.data.market.nikkeiValuationReference || {};
    byId("nikkeiCurrent").textContent = formatNikkei(nikkei.close);
    byId("nikkeiDate").textContent = nikkei.date ? "市場日 " + nikkei.date : "市場日未確認";
    byId("nikkeiPeak").textContent = formatNikkei(nikkei.peak3y);
    byId("nikkeiPeakDate").textContent = nikkei.peak3yDate || "日付未確認";
    byId("nikkeiCurrentDrawdown").textContent = finite(nikkei.drawdown3yPct) === null ? "未確認" : "−" + formatPercent(nikkei.drawdown3yPct, false);
    byId("nikkeiReferenceDate").textContent = reference.date || "要入力";
    if (reference.sourceUrl) byId("nikkeiOfficialLink").href = reference.sourceUrl;

    var model = calculateNikkeiBottom();
    if (!model) {
      byId("nikkeiZone").textContent = "PER・PBRを入力してください";
      byId("nikkeiZoneContext").textContent = "日経公式日次サマリーの指数ベースPER・PBRを確認すると計算できます。";
      byId("nikkeiRemaining").textContent = "―";
      byId("nikkeiProximity").textContent = "―";
      byId("nikkeiConfirmationScore").textContent = "―";
      byId("nikkeiPositionMessage").textContent = "入力待ちです。";
      byId("todayNikkeiZone").textContent = "PER・PBRの入力待ち";
      byId("todayNikkeiDistance").textContent = "―";
      byId("todayNikkeiProximity").textContent = "―";
      byId("todayNikkeiConfirmation").textContent = "―";
      byId("todayNikkeiBottomMessage").textContent = "日経公式の指数ベースPER・PBRを確認すると計算できます。";
      return;
    }

    var confirmation = assessNikkeiConfirmation(model);
    var zoneText = formatNikkei(model.lower) + " ～ " + formatNikkei(model.upper);
    var remainingText = model.current > model.upper ? "あと−" + numberOne.format(model.remainingToUpperPct) + "%" : model.current < model.lower ? "下端超過" : "ゾーン内";
    var proximityText = numberOne.format(model.proximity) + "%";
    var confirmationText = confirmation.score + "/100";
    var positionMessage = model.current > model.upper
      ? "現在値からゾーン上端までは、あと" + formatPercent(model.remainingToUpperPct, false) + "の下落距離があり、選択シナリオの底値帯にはまだ到達していません。"
      : model.current < model.lower ? "現在値は想定下端を" + formatPercent(model.belowLowerPct, false) + "下回っています。シナリオ前提の再評価が必要です。"
        : "現在値は選択シナリオの底値ゾーン内です。価格だけで決めず、反転確認を併読します。";

    byId("nikkeiZone").textContent = zoneText;
    byId("nikkeiZoneContext").textContent = model.scenarioLabel + "：利益−" + numberOne.format(model.epsCut) + "%・PER " + numberOne.format(model.targetPe) + "倍・PBR " + numberOne.format(model.targetPb) + "倍・歴史下落−" + numberOne.format(model.historyDrawdown) + "%";
    byId("nikkeiRemaining").textContent = remainingText;
    byId("nikkeiProximity").textContent = proximityText;
    byId("nikkeiConfirmationScore").textContent = confirmationText;
    byId("nikkeiPositionMessage").textContent = positionMessage;

    byId("todayNikkeiZone").textContent = zoneText;
    byId("todayNikkeiDistance").textContent = remainingText;
    byId("todayNikkeiProximity").textContent = proximityText;
    byId("todayNikkeiConfirmation").textContent = confirmationText;
    byId("todayNikkeiBottomMessage").textContent = positionMessage;

    var anchors = [
      { key: "history", label: "歴史下落率アンカー", value: model.historyAnchor, detail: "直近3年高値から" + formatPercent(model.historyDrawdown, false) + "下落" },
      { key: "earnings", label: "利益×PERアンカー", value: model.earningsAnchor, detail: "EPSを" + formatPercent(model.epsCut, false) + "減らし、PER " + numberOne.format(model.targetPe) + "倍" },
      { key: "book", label: "純資産×PBRアンカー", value: model.bookAnchor, detail: "現在BPSにPBR " + numberOne.format(model.targetPb) + "倍" },
    ];
    byId("nikkeiAnchorList").innerHTML = anchors.map(function (anchor) {
      return "<div class=\"anchor-item " + anchor.key + "\"><span>" + escapeHtml(anchor.label) + "</span><strong>" + formatNikkei(anchor.value) + "</strong><small>" + escapeHtml(anchor.detail) + "</small></div>";
    }).join("");

    var widthPct = (model.upper / model.lower - 1) * 100;
    byId("nikkeiExplanation").innerHTML = "<p><strong>なぜこの範囲か：</strong>3つの計算は「" + formatNikkei(model.earningsAnchor) + "」「" + formatNikkei(model.bookAnchor) + "」「" + formatNikkei(model.historyAnchor) + "」です。最小から最大までを残し、都合のよい平均値だけを底値にしていません。</p>"
      + "<p><strong>不確実性：</strong>ゾーン幅は下端に対して" + formatPercent(widthPct, false) + "です。幅が広いほど、利益予想・簿価・過去類推が一致しておらず、推計精度が低いことを意味します。</p>"
      + "<p><strong>現在の読み方：</strong>底値接近度" + numberOne.format(model.proximity) + "%は、高値からゾーン上端までの距離をどこまで進んだかです。崩壊確率でも、購入推奨度でもありません。</p>";

    byId("nikkeiConfirmationLarge").textContent = confirmation.score + "/100";
    byId("nikkeiConfirmationLabel").textContent = confirmation.label;
    byId("nikkeiConfirmationBar").style.width = clamp(confirmation.score, 0, 100) + "%";
    renderNikkeiChecklist(confirmation);
    renderObservationLadder(model, confirmation);
    renderNikkeiHistory();
    renderNikkeiBottomChart(model);
    if (window.lucide) window.lucide.createIcons();
  }


  function decimalYearFromIso(value) {
    if (!value) return null;
    var parts = String(value).split("-").map(Number);
    if (parts.length < 3 || parts.some(function (part) { return !Number.isFinite(part); })) return null;
    var start = Date.UTC(parts[0], 0, 1);
    var current = Date.UTC(parts[0], parts[1] - 1, parts[2]);
    var end = Date.UTC(parts[0] + 1, 0, 1);
    return parts[0] + (current - start) / (end - start);
  }

  function formatIndexLevel(value) {
    var number = finite(value);
    return number === null ? "未確認" : nikkeiFormat.format(number) + " pt";
  }

  function moneyStrategistRangeBounds() {
    var ranges = {
      all: { min: 1900, max: 2028.99 },
      postwar: { min: 1950, max: 2028.99 },
      modern: { min: 1990, max: 2028.99 },
      current: { min: 2020, max: 2028.99 },
      cycle: { min: 2026.00, max: 2028.99 },
    };
    return ranges[state.moneyStrategistRange] || ranges.all;
  }

  function renderMoneyStrategistRangeUi() {
    document.querySelectorAll(".ms-range-button").forEach(function (button) {
      var active = button.dataset.msRange === state.moneyStrategistRange;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", active ? "true" : "false");
    });
    var cyclePanel = byId("msCyclePanel");
    if (cyclePanel) cyclePanel.hidden = state.moneyStrategistRange !== "cycle";
    document.querySelectorAll(".ms-cycle-legend").forEach(function (item) {
      item.hidden = state.moneyStrategistRange !== "cycle";
    });
  }

  function addDaysIso(iso, days) {
    if (!iso) return null;
    var date = new Date(iso + "T00:00:00Z");
    if (Number.isNaN(date.valueOf())) return null;
    date.setUTCDate(date.getUTCDate() + days);
    return date.toISOString().slice(0, 10);
  }

  function formatCalendarDate(value) {
    if (!value) return "日付未定";
    var date = new Date(value + "T00:00:00Z");
    if (Number.isNaN(date.valueOf())) return value;
    return new Intl.DateTimeFormat("ja-JP", { year: "numeric", month: "short", day: "numeric", timeZone: "UTC" }).format(date);
  }

  function moneyStrategistIpoEvents() {
    var ipoDate = state.moneyStrategistIpoDate;
    if (!ipoDate) return [];
    return [
      { type: "ipo", date: ipoDate, label: "仮のAI大型IPO", status: "ユーザー仮定" },
      { type: "ipo-report", start: addDaysIso(ipoDate, 45), end: addDaysIso(ipoDate, 90), label: "初回10-Q・初期決算の確認帯", status: "会計期で変動" },
      { type: "unlock", date: addDaysIso(ipoDate, 180), label: "典型的な180日ロックアップ", status: "実際の目論見書を優先" },
    ];
  }

  function renderMoneyStrategistCalendar() {
    var data = state.moneyStrategist;
    var calendar = data && data.marketCalendar;
    var summary = byId("msCalendarSummary");
    var input = byId("msIpoAssumption");
    var explanation = byId("msIpoAssumptionText");
    if (!calendar || !summary) return;
    if (input && input.value !== state.moneyStrategistIpoDate) input.value = state.moneyStrategistIpoDate;

    var eventRows = (calendar.events || []).concat(calendar.politicalWindows || []).concat(calendar.earningsWindows || []);
    var grouped = { "2026": [], "2027": [], "2028": [] };
    eventRows.forEach(function (event) {
      var anchor = event.date || event.start || "";
      var year = anchor.slice(0, 4);
      if (!grouped[year]) return;
      grouped[year].push(event);
    });
    Object.keys(grouped).forEach(function (year) {
      grouped[year].sort(function (a, b) { return String(a.date || a.start).localeCompare(String(b.date || b.start)); });
    });
    function statusLabel(status) {
      return status === "confirmed" ? "確定" : status === "tentative" ? "暫定" : status === "official-cycle" ? "公式の標準過程" : "定例観測";
    }
    summary.innerHTML = Object.keys(grouped).map(function (year) {
      var rows = grouped[year].map(function (event) {
        var dateText = event.date ? formatCalendarDate(event.date) : formatCalendarDate(event.start) + "～" + formatCalendarDate(event.end);
        return "<li><span class=\"" + escapeHtml(event.status || "recurring") + "\">" + escapeHtml(statusLabel(event.status)) + "</span><div><strong>" + escapeHtml(dateText) + "</strong><p>" + escapeHtml(event.label) + "</p></div></li>";
      }).join("");
      return "<section><h4>" + year + "年</h4><ul>" + rows + "</ul></section>";
    }).join("");

    if (!explanation) return;
    var assumptions = moneyStrategistIpoEvents();
    if (!assumptions.length) {
      explanation.textContent = calendar.ipoWatch.notScheduledReason;
      return;
    }
    explanation.textContent = "仮に" + formatCalendarDate(assumptions[0].date) + "へ上場した場合、初期決算の確認帯は" + formatCalendarDate(assumptions[1].start) + "～" + formatCalendarDate(assumptions[1].end) + "、典型的な180日解除は" + formatCalendarDate(assumptions[2].date) + "です。いずれも公開S-1の条件が出るまで試算です。";
  }

  function renderMoneyStrategistChart() {
    var data = state.moneyStrategist;
    var canvas = byId("moneyStrategistChart");
    if (!data || !canvas || !window.Chart) return;
    if (state.moneyStrategistChart) state.moneyStrategistChart.destroy();

    var ranges = data.crashes.map(function (crash) {
      return { start: decimalYearFromIso(crash.peakDate), end: decimalYearFromIso(crash.troughDate) };
    });
    function isCrashSegment(x) {
      return ranges.some(function (range) { return x >= range.start && x <= range.end; });
    }

    var history = data.series.history.map(function (row) {
      return { x: row.x, y: row.value, date: row.date, sourceType: row.sourceType };
    });
    var inflation = data.inflation || {};
    var cpiHistory = (inflation.history || []).map(function (row) {
      return { x: row.x, y: row.value, date: row.date, sourceType: "BLS CPI-U via FRED" };
    });
    var forecast = data.forecast.illustrativePath.map(function (row) {
      return { x: row.x, y: row.value, date: row.date, note: row.label };
    });
    var japan = data.japanBubbleMarker;
    var bounds = moneyStrategistRangeBounds();

    var annotationPlugin = {
      id: "moneyStrategistAnnotations",
      beforeDatasetsDraw: function (chart) {
        var area = chart.chartArea;
        var xScale = chart.scales.x;
        if (!area || !xScale) return;
        var ctx = chart.ctx;
        ctx.save();
        var riskColors = ["rgba(20,116,186,0.10)", "rgba(20,92,150,0.12)", "rgba(84,135,170,0.09)"];
        data.forecast.riskWindows.forEach(function (windowItem, index) {
          var start = decimalYearFromIso(windowItem.start);
          var end = decimalYearFromIso(windowItem.end);
          if (end < xScale.min || start > xScale.max) return;
          var left = xScale.getPixelForValue(Math.max(start, xScale.min));
          var right = xScale.getPixelForValue(Math.min(end, xScale.max));
          ctx.fillStyle = riskColors[index] || riskColors[0];
          ctx.fillRect(left, area.top, right - left, area.bottom - area.top);
        });
        if (state.moneyStrategistRange === "cycle" && data.marketCalendar) {
          (data.marketCalendar.earningsWindows || []).forEach(function (windowItem) {
            var start = decimalYearFromIso(windowItem.start);
            var end = decimalYearFromIso(windowItem.end);
            if (end < xScale.min || start > xScale.max) return;
            var left = xScale.getPixelForValue(Math.max(start, xScale.min));
            var right = xScale.getPixelForValue(Math.min(end, xScale.max));
            ctx.fillStyle = "rgba(202,139,28,0.10)";
            ctx.fillRect(left, area.top, right - left, area.bottom - area.top);
          });
          var ipoReport = moneyStrategistIpoEvents().find(function (event) { return event.type === "ipo-report"; });
          if (ipoReport) {
            var reportStart = decimalYearFromIso(ipoReport.start);
            var reportEnd = decimalYearFromIso(ipoReport.end);
            if (reportEnd >= xScale.min && reportStart <= xScale.max) {
              var reportLeft = xScale.getPixelForValue(Math.max(reportStart, xScale.min));
              var reportRight = xScale.getPixelForValue(Math.min(reportEnd, xScale.max));
              ctx.fillStyle = "rgba(142,71,160,0.13)";
              ctx.fillRect(reportLeft, area.top, reportRight - reportLeft, area.bottom - area.top);
            }
          }
        }
        ctx.restore();
      },
      afterDatasetsDraw: function (chart) {
        var area = chart.chartArea;
        var xScale = chart.scales.x;
        if (!area || !xScale) return;
        var ctx = chart.ctx;
        if (japan.x >= xScale.min && japan.x <= xScale.max) {
          var japanX = xScale.getPixelForValue(japan.x);
          ctx.save();
          ctx.strokeStyle = "#d59b14";
          ctx.lineWidth = 2;
          ctx.setLineDash([6, 5]);
          ctx.beginPath();
          ctx.moveTo(japanX, area.top);
          ctx.lineTo(japanX, area.bottom);
          ctx.stroke();
          ctx.setLineDash([]);
          ctx.fillStyle = "#7a5400";
          ctx.font = "700 13px Meiryo, sans-serif";
          ctx.textAlign = japanX > area.right - 190 ? "right" : "left";
          ctx.fillText("日本のバブルピーク 1989/12/29", japanX + (ctx.textAlign === "right" ? -8 : 8), area.top + 17);
          ctx.restore();
        }
        if (state.moneyStrategistRange !== "cycle" || !data.marketCalendar) return;
        ctx.save();
        (data.marketCalendar.events || []).forEach(function (event, index) {
          var value = decimalYearFromIso(event.date);
          if (value < xScale.min || value > xScale.max) return;
          var x = xScale.getPixelForValue(value);
          var election = event.type === "election";
          ctx.strokeStyle = election ? "#7b2f83" : "#08776b";
          ctx.lineWidth = election ? 2.3 : 1.25;
          ctx.setLineDash(election ? [] : [3, 4]);
          ctx.beginPath();
          ctx.moveTo(x, area.top);
          ctx.lineTo(x, election ? area.bottom : area.top + 54);
          ctx.stroke();
          ctx.setLineDash([]);
          ctx.fillStyle = election ? "#642269" : "#08776b";
          ctx.font = election ? "800 12px Meiryo, sans-serif" : "700 10px Meiryo, sans-serif";
          ctx.textAlign = x > area.right - 125 ? "right" : "left";
          var label = election ? event.shortLabel : "FOMC";
          if (election || chart.width >= 650) ctx.fillText(label, x + (ctx.textAlign === "right" ? -5 : 5), area.top + 12 + (index % 3) * 13);
        });
        moneyStrategistIpoEvents().filter(function (event) { return event.date; }).forEach(function (event, index) {
          var value = decimalYearFromIso(event.date);
          if (value < xScale.min || value > xScale.max) return;
          var x = xScale.getPixelForValue(value);
          ctx.strokeStyle = "#9b3d8f";
          ctx.lineWidth = 2;
          ctx.setLineDash([7, 5]);
          ctx.beginPath();
          ctx.moveTo(x, area.top);
          ctx.lineTo(x, area.bottom);
          ctx.stroke();
          ctx.setLineDash([]);
          ctx.fillStyle = "#7c2b72";
          ctx.font = "800 11px Meiryo, sans-serif";
          ctx.textAlign = x > area.right - 160 ? "right" : "left";
          ctx.fillText(event.type === "ipo" ? "仮のIPO" : "仮の180日解除", x + (ctx.textAlign === "right" ? -6 : 6), area.bottom - 12 - index * 16);
        });
        ctx.restore();
      },
    };

    state.moneyStrategistChart = new Chart(canvas, {
      type: "line",
      data: {
        datasets: [
          {
            label: "米国株の歴史系列",
            data: history,
            parsing: false,
            borderColor: "#294b61",
            backgroundColor: "transparent",
            borderWidth: 2.25,
            pointRadius: 0,
            pointHitRadius: 7,
            tension: 0,
            segment: {
              borderColor: function (context) {
                var midpoint = (context.p0.parsed.x + context.p1.parsed.x) / 2;
                return isCrashSegment(midpoint) ? "#c63838" : "#294b61";
              },
              borderWidth: function (context) {
                var midpoint = (context.p0.parsed.x + context.p1.parsed.x) / 2;
                return isCrashSegment(midpoint) ? 3.4 : 2.1;
              },
            },
          },
          {
            label: "米国CPI-U（右軸）",
            data: cpiHistory,
            yAxisID: "yCpi",
            parsing: false,
            borderColor: "#c17a00",
            backgroundColor: "transparent",
            borderWidth: 3,
            pointRadius: 0,
            pointHitRadius: 7,
            tension: 0.08,
            spanGaps: false,
          },
          {
            label: "動画数値の換算シナリオ",
            data: forecast,
            parsing: false,
            borderColor: "#1474ba",
            backgroundColor: "#1474ba",
            borderWidth: 4,
            borderDash: [10, 6],
            pointRadius: 5,
            pointHoverRadius: 7,
            tension: 0.15,
          },
          {
            label: "日本の資産バブル時点",
            data: [{ x: japan.x, y: japan.sp500Value, date: japan.date, note: japan.label }],
            parsing: false,
            showLine: false,
            pointStyle: "rectRot",
            pointRadius: 7,
            pointHoverRadius: 9,
            pointBackgroundColor: "#d59b14",
            pointBorderColor: "#7a5400",
            pointBorderWidth: 1.5,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        normalized: true,
        interaction: { mode: "nearest", intersect: false, axis: "x" },
        layout: { padding: { top: 36, right: 12, bottom: 4, left: 2 } },
        plugins: {
          legend: { display: false },
          tooltip: {
            displayColors: true,
            callbacks: {
              title: function (items) { return items[0] && items[0].raw ? items[0].raw.date : ""; },
              label: function (context) {
                var raw = context.raw || {};
                var text = context.dataset.yAxisID === "yCpi"
                  ? context.dataset.label + ": " + numberThree.format(Number(raw.y)) + "（1982～84年＝100）"
                  : context.dataset.label + ": " + formatIndexLevel(raw.y);
                return raw.note ? [text, raw.note] : text;
              },
              afterLabel: function (context) {
                var raw = context.raw || {};
                return raw.sourceType ? raw.sourceType : "";
              },
            },
          },
        },
        scales: {
          x: {
            type: "linear",
            min: bounds.min,
            max: bounds.max,
            grid: { color: "rgba(53,82,101,0.09)" },
            ticks: {
              color: "#526876",
              font: { size: 12, weight: "600" },
              maxTicksLimit: state.moneyStrategistRange === "cycle" ? 7 : state.moneyStrategistRange === "current" ? 10 : 14,
              stepSize: state.moneyStrategistRange === "cycle" ? 0.5 : undefined,
              callback: function (value) {
                if (state.moneyStrategistRange === "cycle") {
                  var year = Math.round(value);
                  return Math.abs(Number(value) - year) < 0.01 ? String(year) : "";
                }
                return Math.round(value);
              },
            },
            title: { display: true, text: "年", color: "#536675", font: { size: 13, weight: "700" } },
          },
          y: {
            type: "linear",
            beginAtZero: true,
            grace: "5%",
            grid: { color: "rgba(53,82,101,0.11)" },
            ticks: {
              color: "#526876",
              font: { size: 12, weight: "600" },
              maxTicksLimit: 9,
              callback: function (value) { return nikkeiFormat.format(Number(value)); },
            },
            title: { display: true, text: "米国株の名目価格指数（実数、配当なし）", color: "#536675", font: { size: 13, weight: "700" } },
          },
          yCpi: {
            type: "linear",
            position: "right",
            beginAtZero: true,
            display: cpiHistory.length > 0,
            grid: { drawOnChartArea: false },
            ticks: {
              color: "#8a5b00",
              font: { size: 12, weight: "700" },
              maxTicksLimit: 8,
              callback: function (value) { return numberOne.format(Number(value)); },
            },
            title: { display: true, text: "米国CPI-U（1982～84年＝100）", color: "#8a5b00", font: { size: 13, weight: "700" } },
          },
        },
      },
      plugins: [annotationPlugin],
    });
  }

  function renderMoneyStrategist() {
    var data = state.moneyStrategist;
    var status = byId("msChartLimit");
    if (!data) {
      if (status) status.textContent = "長期チャート用データを読み込めませんでした。最新データの他の章は引き続き利用できます。";
      return;
    }
    byId("msCurrentLevel").textContent = formatIndexLevel(data.series.latestValue);
    byId("msAsOf").textContent = data.series.latestDate + " 終値";
    byId("msMidtermMean").textContent = numberOne.format(data.audit.midtermYears.meanMaxDrawdownPct) + "%";
    byId("msTop10Weight").textContent = numberOne.format(data.audit.currentSignals.top10WeightPct.value) + "%";
    byId("msNyFedProbability").textContent = numberOne.format(data.audit.currentSignals.nyFedRecessionProbabilityPct.value) + "%";
    byId("msEarlyLevel").textContent = formatIndexLevel(data.forecast.levels.midtermCorrection18Pct);
    byId("msRecessionLevel").textContent = formatIndexLevel(data.forecast.levels.recessionAverage30Pct);
    byId("msMeanReversionRange").textContent = formatIndexLevel(data.forecast.levels.capeMeanReversion55To60Pct[0]) + "～" + formatIndexLevel(data.forecast.levels.capeMeanReversion55To60Pct[1]);
    var inflation = data.inflation || {};
    var cpiBase = (inflation.history || []).find(function (row) { return row.date === inflation.comparisonBaseDate; });
    var stockBase = (data.series.history || []).find(function (row) { return row.date === inflation.comparisonBaseDate; });
    var cpiMultiple = cpiBase && finite(cpiBase.value) ? finite(inflation.latestValue) / finite(cpiBase.value) : null;
    var stockMultiple = stockBase && finite(stockBase.value) ? finite(data.series.latestValue) / finite(stockBase.value) : null;
    var realMultiple = cpiMultiple && stockMultiple ? stockMultiple / cpiMultiple : null;
    byId("msCpiLatest").textContent = finite(inflation.latestValue) === null ? "未確認" : numberThree.format(inflation.latestValue);
    byId("msCpiLatestDate").textContent = (inflation.latestDate || "日付未確認") + "・1982～84年＝100";
    byId("msCpiMultiple").textContent = cpiMultiple === null ? "未確認" : numberOne.format(cpiMultiple) + "倍";
    byId("msStockMultiple").textContent = stockMultiple === null ? "未確認" : numberOne.format(stockMultiple) + "倍";
    byId("msRealStockMultiple").textContent = realMultiple === null ? "未確認" : numberOne.format(realMultiple) + "倍";
    byId("msCpiLimit").textContent = inflation.importantLimit || "CPI-Uは最新の公式公表月で停止し、将来値を推測しません。";
    status.textContent = data.forecast.importantLimit;
    renderMoneyStrategistCalendar();
    renderMoneyStrategistRangeUi();
    renderMoneyStrategistChart();
  }


  function formatUsdBillions(value) {
    var numeric = finite(value);
    return numeric === null ? "未確認" : (numeric < 0 ? "−" : "") + "$" + numberOne.format(Math.abs(numeric)) + "B";
  }

  function formatShares(value) {
    var numeric = finite(value);
    if (numeric === null) return "未確認";
    if (Math.abs(numeric) >= 1000000) return numberOne.format(numeric / 1000000) + "百万株";
    if (Math.abs(numeric) >= 10000) return numberOne.format(numeric / 10000) + "万株";
    return nikkeiFormat.format(numeric) + "株";
  }

  function renderUsRisk() {
    var risk = ((state.data.market || {}).usBubbleRisk || {});
    var score = finite(risk.score);
    byId("usRiskScore").textContent = score === null ? "算定不可" : numberOne.format(score) + " / 100";
    byId("usRiskAsOf").textContent = (risk.asOfDate || "基準日未確認") + " 終値基準";
    byId("usRiskStage").textContent = risk.stageLabel || "データ不足";
    byId("usRiskStage").className = "us-risk-stage " + escapeHtml(risk.stageCode || "insufficient");
    byId("usRiskNarrative").textContent = risk.narrative || "主要指標を確認しています。";
    byId("usRiskMeterFill").style.width = (score === null ? 0 : clamp(score, 0, 100)) + "%";
    var previous = risk.previousUpdate || {};
    var change = finite(previous.scoreChange);
    byId("usRiskChange").textContent = change === null
      ? "この方法での前回値はまだありません。次回更新から変化幅を表示します。"
      : "前回更新から " + (change > 0 ? "+" : "") + numberOne.format(change) + "ポイント（前回 " + numberOne.format(previous.score) + "）。";

    byId("usRiskComponents").innerHTML = (risk.components || []).map(function (component) {
      var componentScore = finite(component.score) || 0;
      var knownMax = finite(component.knownMax) || 0;
      var width = knownMax ? clamp(componentScore / knownMax * 100, 0, 100) : 0;
      return "<article><div class=\"us-risk-component-heading\"><strong>" + escapeHtml(component.label) + "</strong><span>" + numberOne.format(componentScore) + " / " + numberOne.format(knownMax) + "</span></div>"
        + "<div class=\"us-component-meter\" aria-hidden=\"true\"><span style=\"width:" + width + "%\"></span></div>"
        + "<p>" + escapeHtml(component.detail || "") + "</p></article>";
    }).join("");

    byId("usScenarioRows").innerHTML = (risk.scenarios || []).map(function (scenario) {
      return "<tr><th>" + escapeHtml(scenario.label) + "</th><td>−" + numberOne.format(scenario.drawdownFromPeakPct) + "%</td><td>" + formatIndexLevel(scenario.level) + "</td><td>" + formatPercent(scenario.moveFromCurrentPct, true) + "</td><td>" + escapeHtml(scenario.note) + "</td></tr>";
    }).join("") || "<tr><td colspan=\"5\">S&amp;P 500の高値と終値を取得できませんでした。</td></tr>";
    var rules = risk.rules || {};
    byId("usRiskRuleMeaning").textContent = rules.meaning || "";
    byId("usRiskThresholdBasis").textContent = rules.thresholdBasis || "";
    byId("usRiskProbabilityNote").textContent = rules.notProbability || "";

    var signals = (((state.moneyStrategist || {}).audit || {}).currentSignals || {});
    byId("usCape").textContent = finite((signals.cape || {}).value) === null ? "未確認" : numberTwo.format(signals.cape.value);
    byId("usConcentration").textContent = finite((signals.top10WeightPct || {}).value) === null ? "未確認" : numberOne.format(signals.top10WeightPct.value) + "%";
  }

  function renderBerkshireMonitor() {
    var monitor = ((state.data.market || {}).berkshireMonitor || {});
    var latest = monitor.balanceLatest || {};
    var filing = monitor.thirteenF || {};
    var longContext = monitor.longTermContext || {};
    var netSelling = longContext.netSelling || {};
    var periods = netSelling.periods || [];
    var liquidityHistory = Array.isArray(longContext.liquidityHistory) ? longContext.liquidityHistory : [];
    var historyForYear = function (year) {
      return liquidityHistory.find(function (row) { return String(row.periodEnd || row.label || "").indexOf(String(year)) >= 0; }) || {};
    };
    var liquidity2024 = historyForYear(2024);
    var liquidity2025 = historyForYear(2025);
    var liquidityLatest = liquidityHistory[liquidityHistory.length - 1] || latest;
    var sales2024 = periods.find(function (row) { return String(row.label || "").indexOf("2024") >= 0; }) || {};
    var sales2025 = periods.find(function (row) { return String(row.label || "").indexOf("2025") >= 0; }) || {};
    var operating2025 = finite(liquidity2025.operatingCashFlowBillion);
    var totalAssetLiquidRatio = finite(latest.totalAssetLiquidRatioPct);
    if (totalAssetLiquidRatio === null && finite(latest.totalAssetsBillion) !== null && finite(latest.netLiquidReserveBillion) !== null && latest.totalAssetsBillion > 0) {
      totalAssetLiquidRatio = latest.netLiquidReserveBillion / latest.totalAssetsBillion * 100;
    }
    var historyLabels = liquidityHistory.slice(-3).map(function (row) {
      return (row.label || row.periodEnd || "期末") + " " + formatUsdBillions(row.netLiquidReserveBillion);
    });
    byId("berkshireLiquidityHistory").textContent = historyLabels.length ? historyLabels.join(" → ") : "期末残高を確認中";
    byId("berkshireLiquidityHistoryCaption").textContent = "純売却は当期のフロー、ここは過去の売却代金や営業CFを含む期末残高です。";
    byId("berkshireRatioClarifier").textContent = "投資プール内 " + formatPercent(latest.investmentPoolLiquidRatioPct, false)
      + (totalAssetLiquidRatio === null ? " / 総資産比は未算出" : " / 総資産比 " + formatPercent(totalAssetLiquidRatio, false));
    byId("berkshireRatioClarifierCaption").textContent = "54.99%のような投資プール比率と、会社全体の総資産比は分母が違います。";
    if (finite(sales2025.netSalesBillion) !== null && finite(liquidity2024.netLiquidReserveBillion) !== null && finite(liquidity2025.netLiquidReserveBillion) !== null) {
      byId("berkshireCashFlowConclusion").textContent = "2025年の純売却は" + formatUsdBillions(sales2025.netSalesBillion) + "へ縮小しましたが、売り越しは続きました。";
      byId("berkshireCashFlowDetail").textContent = "2024年の純売却" + formatUsdBillions(sales2024.netSalesBillion)
        + "で積み上がった資金に" + (operating2025 === null ? "営業活動による資金" : "2025年の営業CF " + formatUsdBillions(operating2025))
        + "が加わり、期末待機資金は" + formatUsdBillions(liquidity2024.netLiquidReserveBillion) + "から" + formatUsdBillions(liquidity2025.netLiquidReserveBillion) + "へ増えました。低い2025年の売却額だけで現金比率が低いとは読めません。";
    } else {
      byId("berkshireCashFlowConclusion").textContent = "純売却（その年の動き）と待機資金（積み上がった残高）を分けて確認します。";
      byId("berkshireCashFlowDetail").textContent = "純売却が減っても、過去の売却代金・営業キャッシュフロー・買戻しの有無で期末残高は増減します。";
    }
    byId("berkshireNarrative").textContent = monitor.narrative || "バークシャーの最新公表値を確認できませんでした。";
    byId("berkshireReserve").textContent = formatUsdBillions(latest.netLiquidReserveBillion);
    byId("berkshireReserveChange").textContent = "前期比 " + formatUsdBillions(monitor.reserveChangeBillion) + "（" + formatPercent(monitor.reserveChangePct, true) + "）";
    byId("berkshireCashRatio").textContent = formatPercent(latest.investmentPoolLiquidRatioPct, false);
    byId("berkshireCashRatioChange").textContent = "前期比 " + formatPctPoints(monitor.investmentPoolLiquidRatioChangePctPoints, true);
    byId("berkshireEquities").textContent = formatUsdBillions(latest.equitySecuritiesBillion);
    byId("berkshireEquitiesChange").textContent = "前期比 " + formatUsdBillions(monitor.equitySecuritiesChangeBillion);
    byId("berkshirePeriod").textContent = latest.periodEnd || "未確認";
    byId("berkshireCalculation").textContent = monitor.calculationNote || "";
    byId("berkshireLimit").textContent = monitor.thirteenFLimit || "";
    byId("berkshireBalanceSource").href = latest.sourceUrl || "https://www.berkshirehathaway.com/reports.html";
    byId("berkshire13fSource").href = (filing.latest || {}).sourceUrl || "https://www.sec.gov/edgar/browse/?CIK=1067983";
    var commentator = longContext.commentator || {};
    byId("berkshireCommentatorSource").href = commentator.url || "https://www.youtube.com/watch?v=Y8fJNR_xsnI";
    byId("berkshireCommentatorSource").textContent = (commentator.displayName || "Finance Bureau") + "の解説";
    byId("berkshireLongTermSummary").textContent = longContext.summary || "長期の株式売買を一次資料で確認できませんでした。";
    byId("berkshireNetSellerQuarters").textContent = finite(netSelling.consecutiveQuarters) === null
      ? "未確認"
      : nikkeiFormat.format(netSelling.consecutiveQuarters) + "四半期連続";
    byId("berkshireNetSellerPeriod").textContent = netSelling.startLabel && netSelling.endLabel
      ? netSelling.startLabel + "～" + netSelling.endLabel
      : "期間未確認";
    byId("berkshireCumulativeNetSales").textContent = formatUsdBillions(netSelling.cumulativeNetSalesBillion);
    var acceleration = periods.reduce(function (largest, period) {
      return finite(period.netSalesBillion) !== null
        && (!largest || Number(period.netSalesBillion) > Number(largest.netSalesBillion)) ? period : largest;
    }, null);
    byId("berkshireAcceleration").textContent = acceleration ? acceleration.label : "未確認";
    byId("berkshireAccelerationDetail").textContent = acceleration
      ? "純売却 " + formatUsdBillions(acceleration.netSalesBillion)
      : "年次資料を確認できませんでした";
    var maxNetSales = periods.reduce(function (maximum, period) {
      var amount = finite(period.netSalesBillion);
      return amount !== null ? Math.max(maximum, Math.max(0, amount)) : maximum;
    }, 0);
    byId("berkshireNetSellingTimeline").innerHTML = periods.map(function (period) {
      var amount = finite(period.netSalesBillion);
      var width = amount === null || maxNetSales <= 0 ? 0 : Math.max(5, Math.round(amount / maxNetSales * 100));
      return "<li><span>" + escapeHtml(period.label || "") + "</span><strong>純売却 "
        + escapeHtml(formatUsdBillions(period.netSalesBillion)) + "</strong><small>"
        + escapeHtml(period.detail || "") + "</small><b class=\"berkshire-sale-scale\" aria-label=\"純売却額の相対的な大きさ\"><i style=\"width:" + width + "%\"></i></b></li>";
    }).join("") || "<li><span>未確認</span><strong>長期データなし</strong></li>";
    byId("berkshireFactSummary").textContent = longContext.factSummary || "";
    byId("berkshireInterpretation").textContent = longContext.interpretation || "";
    byId("berkshireContextCaution").textContent = longContext.caution || "";
    byId("berkshireScopeNote").textContent = longContext.scopeNote || "";
    byId("berkshireContextSources").innerHTML = (longContext.sources || []).map(function (source) {
      return "<a href=\"" + escapeHtml(source.url || "#") + "\" target=\"_blank\" rel=\"noopener\">"
        + escapeHtml(source.label || "一次資料") + "</a>";
    }).join("");

    function changeRows(rows) {
      return (rows || []).map(function (row) {
        var pct = finite(row.changePct);
        var comparison = row.status === "新規" ? "新規 " + formatShares(row.latestShares)
          : row.status === "全売却" ? "全売却 " + formatShares(Math.abs(row.changeShares))
          : (pct !== null ? formatPercent(pct, true) : formatShares(row.changeShares));
        return "<div class=\"berkshire-change-row\"><div><strong>" + escapeHtml(row.name) + "</strong><small>" + escapeHtml(row.securityClass || "") + "</small></div><span>" + escapeHtml(row.status || "") + "</span><b>" + escapeHtml(comparison) + "</b></div>";
      }).join("") || "<p>比較可能な変更を取得できませんでした。</p>";
    }
    byId("berkshireBuys").innerHTML = changeRows(filing.buys);
    byId("berkshireSells").innerHTML = changeRows(filing.sells);
  }

  function renderOverseasIntelligence() {
    var intelligence = state.data.overseasIntelligence || {};
    var xWatch = intelligence.x || {};
    var live = state.liveIntelligence || {};
    var briefing = live.briefing || {};
    var allLiveItems = Array.isArray(briefing.items) ? briefing.items : [];
    var liveItems = allLiveItems.filter(function (item) {
      if (!item || typeof item !== "object") return false;
      var country = String(item.sourceCountry || "").toUpperCase();
      var topic = String(item.topicKey || "") + " " + String(item.topic || "");
      return country !== "JP" && !/japan|日本/.test(topic);
    }).sort(function (left, right) {
      return (briefingTimestamp(right) || 0) - (briefingTimestamp(left) || 0);
    }).slice(0, 8);
    var checkedAt = live.generatedAtUtc || live.generatedAtJst || intelligence.checkedAtUtc || "";
    var checked = checkedAt ? new Date(checkedAt) : null;
    var counts = { official: 0, reported: 0, observation: 0 };
    liveItems.forEach(function (item) {
      var verification = String(item.verification || "").toLowerCase();
      var kind = String(item.sourceKind || "").toLowerCase();
      var bucket = /^primary/.test(verification) || /^official/.test(kind) ? "official"
        : /^reported/.test(verification) ? "reported" : "observation";
      counts[bucket] += 1;
    });
    byId("overseasSummary").textContent = liveItems.length
      ? "海外の新着候補を" + formatLiveTime(checkedAt, "") + " JSTに再確認。上段は新しい順に、公式資料と主要報道を優先して表示します。"
      : (intelligence.summary || "海外情報の更新結果がありません。");
    byId("overseasTakeaway").textContent = liveItems.length
      ? "今すぐ見る候補 " + liveItems.length + "件：公式確認 " + counts.official + "件 / 主要報道・公式確認待ち " + counts.reported + "件 / 観測・原文確認待ち " + counts.observation + "件"
      : "ライブ候補を取得できなかったため、下の保存済み背景記事を表示します。";
    byId("overseasVerificationPath").textContent = "「公式確認」は中央銀行・政府・企業IRなどの一次資料です。「主要報道」は原文を開いて公式資料へ進みます。「観測」はSNSや索引の発見段階で、投資判断の根拠にしません。";
    byId("overseasCheckedAt").textContent = checked && !Number.isNaN(checked.valueOf())
      ? "ライブ確認 " + new Intl.DateTimeFormat("ja-JP", { dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Tokyo" }).format(checked)
      : "ライブ確認時刻なし";
    byId("overseasXStatus").textContent = "SNS・投稿は観測扱い。公式資料と主要報道を優先して照合";
    var topicCounts = {};
    liveItems.forEach(function (item) {
      var topic = item.topic || item.topicKey || "海外材料";
      topicCounts[topic] = (topicCounts[topic] || 0) + 1;
    });
    var topics = Object.keys(topicCounts).map(function (key) { return [key, topicCounts[key]]; })
      .sort(function (left, right) { return right[1] - left[1]; });
    byId("overseasTopicChips").innerHTML = topics.map(function (row) {
      return "<span>" + escapeHtml(row[0]) + " <strong>" + nikkeiFormat.format(row[1]) + "</strong></span>";
    }).join("");
    byId("overseasNewsList").innerHTML = liveItems.map(function (item) {
      var copy = briefingCopy(item);
      var verification = String(item.verification || "").toLowerCase();
      var sourceKind = String(item.sourceKind || "").toLowerCase();
      var bucket = /^primary/.test(verification) || /^official/.test(sourceKind) ? "official"
        : /^reported/.test(verification) ? "reported" : "observation";
      var bucketLabel = bucket === "official" ? "公式確認" : bucket === "reported" ? "主要報道・公式確認待ち" : "観測・原文確認待ち";
      var japaneseTitle = copy.japaneseTitle || item.title || "海外の最新材料";
      var japaneseSummary = copy.japaneseSummary || "日本語要旨は未取得です。原文を直接確認してください。";
      var originalTitle = copy.originalTitle || item.title || "";
      var originalSummary = copy.originalSummary || item.summary || "";
      return '<article class="overseas-live-card" data-verification="' + escapeHtml(bucket) + '">'
        + '<div class="overseas-live-meta"><span>' + escapeHtml(bucketLabel) + '</span><span>' + escapeHtml(briefingPublicationLabel(item)) + '</span><span>' + escapeHtml(item.source || item.publisher || "情報源未確認") + '</span></div>'
        + '<h4>' + escapeHtml(japaneseTitle) + '</h4><p>' + escapeHtml(japaneseSummary) + '</p>'
        + '<details><summary>原文と掲載情報を確認</summary><p lang="' + escapeHtml(copy.originalLanguage || "en") + '">' + escapeHtml(originalTitle) + (originalSummary ? " — " + escapeHtml(originalSummary) : "") + '</p></details>'
        + liveSourceLink(item.url, originalSourceLinkLabel(item.url), "overseas-live-link") + '</article>';
    }).join("") || "<p>今回のライブ取得では海外の新着候補を確認できませんでした。保存済み記事は下から確認できます。</p>";
    var archiveItems = (intelligence.newsItems || []).slice(0, 12).concat((xWatch.items || []).slice(0, 6));
    byId("overseasArchiveCount").textContent = archiveItems.length + "件";
    byId("overseasArchiveList").innerHTML = archiveItems.map(function (row) {
      var label = row.title || "保存済み背景記事";
      return '<div>' + liveSourceLink(row.url, label, "overseas-archive-link")
        + '<small>' + escapeHtml(row.source || "") + " / " + escapeHtml(row.topic || row.evidenceLevel || "背景情報") + '</small></div>';
    }).join("") || "<p>保存済みの背景記事はありません。</p>";
    byId("overseasReadingRule").textContent = (intelligence.readingRule || "") + " 上段の原文リンクから一次資料・記事の詳細を直接確認できます。";
  }

  function renderUsMarketIntelligence() {
    renderUsRisk();
    renderBerkshireMonitor();
    renderOverseasIntelligence();
  }


  function renderSources() {
    var grouped = {};
    (state.data.sourceStatus || []).forEach(function (source) {
      var key = source.name;
      if (!grouped[key]) grouped[key] = { name: key, url: source.url, ok: 0, failed: 0, notes: [], successNotes: [], retrievedAt: null };
      var retrievedAt = source.retrieved_at || source.retrievedAt || null;
      if (retrievedAt && (!grouped[key].retrievedAt || retrievedAt > grouped[key].retrievedAt)) grouped[key].retrievedAt = retrievedAt;
      if (source.ok) {
        grouped[key].ok += 1;
        if (source.note && grouped[key].successNotes.indexOf(source.note) < 0) grouped[key].successNotes.push(source.note);
      } else {
        grouped[key].failed += 1;
        if (source.note) grouped[key].notes.push(source.note);
      }
    });
    byId("sourceStatusList").innerHTML = Object.values(grouped).map(function (group) {
      var failed = group.failed > 0;
      var summary = group.ok + "件成功" + (failed ? " / " + group.failed + "件失敗" : "");
      var targets = group.successNotes.slice(0, 5).join("、");
      if (group.successNotes.length > 5) targets += " ほか" + (group.successNotes.length - 5) + "件";
      var note = failed ? group.notes.slice(0, 2).join(" / ") : targets ? "対象: " + targets : "取得済み";
      var retrievedDate = group.retrievedAt ? new Date(group.retrievedAt) : null;
      var retrievedText = retrievedDate && !Number.isNaN(retrievedDate.valueOf())
        ? new Intl.DateTimeFormat("ja-JP", { dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Tokyo" }).format(retrievedDate)
        : "時刻未記録";
      return "<a class=\"source-item " + (failed ? "failed" : "") + "\" href=\"" + escapeHtml(group.url) + "\" target=\"_blank\" rel=\"noopener\">"
        + "<span aria-hidden=\"true\"></span><div><p><strong>" + escapeHtml(group.name) + "</strong>：" + escapeHtml(summary) + "</p>"
        + "<small class=\"source-retrieved\">最終取得 " + escapeHtml(retrievedText) + "</small><small>" + escapeHtml(note) + "</small></div></a>";
    }).join("");
  }

  function snapshotTargetKey(days) {
    var currentStamp = state.data && (state.data.generatedAtJst || state.data.generatedAtUtc);
    var currentDate = currentStamp ? new Date(currentStamp) : null;
    if (!currentDate || Number.isNaN(currentDate.valueOf())) return null;
    var target = new Date(currentDate.valueOf());
    target.setDate(target.getDate() - days);
    return target.toLocaleDateString("sv-SE", { timeZone: "Asia/Tokyo" });
  }

  function snapshotEntryForDays(days) {
    var entries = ((state.snapshotHistoryIndex || {}).snapshots || []).slice();
    var targetKey = snapshotTargetKey(days);
    if (!targetKey) return null;
    var candidate = entries
      .filter(function (entry) { return entry.snapshotDate && entry.snapshotDate <= targetKey; })
      .sort(function (a, b) { return b.snapshotDate.localeCompare(a.snapshotDate); })[0] || null;
    if (!candidate) return null;
    var targetMs = Date.parse(targetKey + "T00:00:00Z");
    var candidateMs = Date.parse(candidate.snapshotDate + "T00:00:00Z");
    var lagDays = Math.round((targetMs - candidateMs) / 86400000);
    return lagDays >= 0 && lagDays <= 3 ? candidate : null;
  }

  function updateSnapshotComparisonButtons() {
    var entries = ((state.snapshotHistoryIndex || {}).snapshots || []);
    document.querySelectorAll(".snapshot-compare-button").forEach(function (button) {
      var days = Number(button.dataset.compareDays);
      var available = Boolean(snapshotEntryForDays(days));
      button.disabled = !available;
      button.classList.toggle("is-active", state.snapshotComparisonDays === days);
      button.setAttribute("aria-pressed", state.snapshotComparisonDays === days ? "true" : "false");
      if (!available) button.title = "対象日の前3日以内に保存データがありません";
      else button.title = "";
    });
    if (!entries.length) {
      byId("snapshotAvailability").textContent = "履歴保存は今回から開始します。過去値は推測せず、保存された日だけ比較します。";
      return;
    }
    var oldest = entries.slice().sort(function (a, b) { return a.snapshotDate.localeCompare(b.snapshotDate); })[0];
    byId("snapshotAvailability").textContent = "保存開始 " + oldest.snapshotDate + "。休場・未更新日は対象日以前3日以内の最寄り保存日を使い、実際の日付を表示します。";
  }

  function snapshotMetric(payload, key) {
    var market = (payload || {}).market || {};
    var series = market.series || {};
    var macro = (payload || {}).macro || {};
    var risk = market.usBubbleRisk || {};
    var purchasingPower = market.purchasingPowerStress || {};
    var basket = market.aiBasket || {};
    var quality = (payload || {}).dataQuality || {};
    var values = {
      usRisk: finite(risk.score),
      sp500: finite((series.SP500 || {}).close),
      nikkei: finite((series.NIKKEI || {}).close),
      vix: finite((series.VIX || {}).close),
      oas: finite((macro.highYieldOas || {}).valuePct),
      breadth: finite(basket.breadthBelowSma200Pct),
      goldRatio: finite(purchasingPower.sp500GoldRatio),
      failures: finite(quality.failedRequests),
    };
    return values[key];
  }

  function renderSnapshotComparison() {
    var previousPayload = state.snapshotComparisonPayload;
    var panel = byId("snapshotComparison");
    if (!previousPayload || !state.data) {
      panel.hidden = true;
      return;
    }
    panel.hidden = false;
    var days = state.snapshotComparisonDays;
    var labels = { 1: "昨日", 7: "1週間前", 30: "1か月前" };
    var previousDate = (state.snapshotComparisonEntry || {}).snapshotDate
      || String(previousPayload.generatedAtJst || previousPayload.generatedAtUtc || "").slice(0, 10);
    var currentDate = String(state.data.generatedAtJst || state.data.generatedAtUtc || "").slice(0, 10);
    var targetKey = snapshotTargetKey(days);
    var comparisonLabel = previousDate === targetKey
      ? (labels[days] || "過去")
      : (labels[days] || "過去") + "に近い保存日（" + previousDate + "）";
    byId("snapshotComparisonHeading").textContent = comparisonLabel + "との比較";
    byId("snapshotComparisonDates").textContent = previousDate + "（市場 " + (previousPayload.marketDate || "未確認") + "）→ " + currentDate + "（市場 " + (state.data.marketDate || "未確認") + "）";

    var definitions = [
      { key: "usRisk", label: "米国株の崩壊進行度", unit: " / 100", difference: "points", riskHigher: true },
      { key: "sp500", label: "S&P 500", unit: " pt", difference: "percent", digits: 1 },
      { key: "nikkei", label: "日経平均", unit: " 円", difference: "percent", digits: 0 },
      { key: "vix", label: "VIX", unit: "", difference: "percent", riskHigher: true },
      { key: "oas", label: "米国HY OAS", unit: "%", difference: "points", riskHigher: true },
      { key: "breadth", label: "海外AI・200日線割れ", unit: "%", difference: "points", riskHigher: true },
      { key: "goldRatio", label: "S&P 500 ÷ 金", unit: "", difference: "percent", riskHigher: false, riskLower: true, digits: 3 },
      { key: "failures", label: "データ取得失敗", unit: "件", difference: "points", riskHigher: true, digits: 0 },
    ];
    byId("snapshotComparisonGrid").innerHTML = definitions.map(function (definition) {
      var current = snapshotMetric(state.data, definition.key);
      var previous = snapshotMetric(previousPayload, definition.key);
      if (current === null || previous === null) {
        return "<article class=\"neutral\"><span>" + escapeHtml(definition.label) + "</span><strong>比較不可</strong><small>一方の保存値なし</small></article>";
      }
      var change = definition.difference === "percent" && previous !== 0
        ? (current / previous - 1) * 100 : current - previous;
      var riskDirection = definition.riskLower ? -change : change;
      var className = Math.abs(change) < 0.0001 ? "neutral" : definition.riskHigher || definition.riskLower
        ? (riskDirection > 0 ? "risk-up" : "risk-down") : "neutral";
      var digits = definition.digits === undefined ? 1 : definition.digits;
      var valueText = new Intl.NumberFormat("ja-JP", { maximumFractionDigits: digits }).format(current) + definition.unit;
      var changeText = (change > 0 ? "+" : "") + numberOne.format(change)
        + (definition.difference === "percent" ? "%" : definition.key === "failures" ? "件" : "ポイント");
      return "<article class=\"" + className + "\"><span>" + escapeHtml(definition.label) + "</span><strong>" + escapeHtml(valueText) + "</strong><small>過去値 "
        + new Intl.NumberFormat("ja-JP", { maximumFractionDigits: digits }).format(previous) + definition.unit + " / 差 " + escapeHtml(changeText) + "</small></article>";
    }).join("");
    var methodChanged = previousPayload.methodVersion && previousPayload.methodVersion !== state.data.methodVersion;
    byId("snapshotComparisonNote").textContent = (methodChanged
      ? "計算方法の版が異なります（" + previousPayload.methodVersion + " → " + state.data.methodVersion + "）。スコア差は参考比較です。 " : "")
      + "過去値はその日に保存した当時公表値です。月次系列が後日改定されても、この比較用スナップショットは再計算しません。";
  }

  async function loadSnapshotComparison(days) {
    var entry = snapshotEntryForDays(days);
    state.snapshotComparisonDays = days;
    state.snapshotComparisonPayload = null;
    state.snapshotComparisonEntry = entry;
    updateSnapshotComparisonButtons();
    if (!entry) {
      byId("snapshotComparison").hidden = false;
      byId("snapshotComparisonHeading").textContent = "比較データなし";
      byId("snapshotComparisonDates").textContent = "保存開始前の状況は復元しません";
      byId("snapshotComparisonGrid").innerHTML = "";
      byId("snapshotComparisonNote").textContent = "今後の日次更新で履歴が蓄積すると、自動的に比較できるようになります。";
      return;
    }
    try {
      var response = await fetch("data/history/" + entry.file + "?ts=" + Date.now(), { cache: "no-store" });
      if (!response.ok) throw new Error("HTTP " + response.status);
      state.snapshotComparisonPayload = await response.json();
      renderSnapshotComparison();
    } catch (error) {
      byId("snapshotComparison").hidden = false;
      byId("snapshotComparisonHeading").textContent = "保存データを読み込めませんでした";
      byId("snapshotComparisonDates").textContent = entry.snapshotDate || "日付未確認";
      byId("snapshotComparisonGrid").innerHTML = "";
      byId("snapshotComparisonNote").textContent = error.message;
    }
  }

  function renderPurchasingPower() {
    var monitor = ((state.data.market || {}).purchasingPowerStress || {});
    var changes = monitor.changes || {};
    var divergence = monitor.divergence || {};
    var policy = monitor.policySpread || {};
    var saving = monitor.personalSavingRate || {};
    byId("ppAsOf").textContent = monitor.asOfDate ? "市場 " + monitor.asOfDate : "基準日未確認";
    byId("ppStatus").textContent = divergence.label || "算定不可";
    byId("ppStatus").className = "purchasing-power-status " + escapeHtml(divergence.code || "insufficient");
    byId("ppStatusDetail").textContent = "S&P 500は20日 " + formatPercent((changes.sp500 || {})["20dPct"], true)
      + "、金建て比率は " + formatPercent((changes.sp500GoldRatio || {})["20dPct"], true) + "。";
    byId("ppSp500").textContent = finite(monitor.sp500) === null ? "未確認" : numberOne.format(monitor.sp500) + " pt";
    byId("ppSp500Change").textContent = "20日 " + formatPercent((changes.sp500 || {})["20dPct"], true);
    byId("ppGold").textContent = finite(monitor.goldUsdPerOunce) === null ? "未確認" : "$" + numberOne.format(monitor.goldUsdPerOunce) + " / oz";
    byId("ppGoldChange").textContent = "20日 " + formatPercent((changes.gold || {})["20dPct"], true);
    byId("ppRatio").textContent = finite(monitor.sp500GoldRatio) === null ? "未確認" : numberThree.format(monitor.sp500GoldRatio);
    byId("ppRatioChange").textContent = "20日 " + formatPercent((changes.sp500GoldRatio || {})["20dPct"], true);
    byId("ppPolicySpread").textContent = finite(policy.spreadPctPoints) === null ? "未確認" : formatPctPoints(policy.spreadPctPoints, true);
    byId("ppPolicyDate").textContent = "観測日 " + (policy.date || "未確認");
    byId("ppSavings").textContent = finite(saving.value) === null ? "未確認" : formatPercent(saving.value, false);
    byId("ppSavingsDate").textContent = "観測月 " + (saving.date || "未確認") + "（最新改定値）";

    if (!window.Chart || !(monitor.chart || []).length) return;
    if (state.purchasingPowerChart) state.purchasingPowerChart.destroy();
    var context = byId("purchasingPowerChart").getContext("2d");
    state.purchasingPowerChart = new Chart(context, {
      type: "line",
      data: {
        labels: monitor.chart.map(function (row) { return row.date; }),
        datasets: [
          { label: "S&P 500（ドル建て）", data: monitor.chart.map(function (row) { return row.sp500NominalIndex; }), borderColor: "#126e82", borderWidth: 2.4, pointRadius: 0, tension: 0.08 },
          { label: "S&P 500 ÷ 金", data: monitor.chart.map(function (row) { return row.sp500GoldIndex; }), borderColor: "#b68b24", borderWidth: 2.8, pointRadius: 0, tension: 0.08 },
          { label: "金価格", data: monitor.chart.map(function (row) { return row.goldIndex; }), borderColor: "rgba(182,139,36,.38)", borderWidth: 1.4, pointRadius: 0, tension: 0.08 },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: { legend: { position: "bottom", labels: { color: chartTextColor(), boxWidth: 18 } } },
        scales: {
          x: { ticks: { color: chartTextColor(), maxTicksLimit: 9 }, grid: { display: false } },
          y: { ticks: { color: chartTextColor() }, grid: { color: "rgba(20,42,61,.09)" }, title: { display: true, text: "起点＝100" } },
        },
      },
    });
  }

  function renderMetadata() {
    var quality = state.data.dataQuality || {};
    var failures = quality.failedRequests || 0;
    var health = byId("dataHealth");
    health.className = "status-dot " + (failures === 0 ? "ok" : quality.successfulRequests ? "warn" : "error");
    health.textContent = failures === 0 ? "自動取得成功" : failures + "件の取得失敗";
    byId("marketDate").textContent = state.data.marketDate || "未確認";
    var generated = state.data.generatedAtJst ? new Date(state.data.generatedAtJst) : null;
    byId("generatedAt").textContent = generated && !Number.isNaN(generated.valueOf())
      ? new Intl.DateTimeFormat("ja-JP", { dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Tokyo" }).format(generated)
      : "未確認";
  }

  function liveQuoteMap() {
    var live = state.liveIntelligence || {};
    var premarket = live.premarket || {};
    var quotes = premarket.quotes || {};
    return quotes && typeof quotes === "object" && !Array.isArray(quotes) ? quotes : {};
  }

  function liveQuoteForKey(key) {
    if (!key) return null;
    var quote = liveQuoteMap()[key];
    var staleMinutes = finite(quote && quote.staleMinutes);
    if (staleMinutes !== null && staleMinutes > 72 * 60) return null;
    return quote && typeof quote === "object" && finite(quote.value) !== null ? quote : null;
  }

  function liveQuoteTime(quote) {
    return quote && (quote.quoteTimeUtc || quote.quoteTimeJst || quote.retrievedAtUtc) || "";
  }

  function liveQuoteDate(quote) {
    var value = liveQuoteTime(quote);
    var parsed = value ? new Date(value) : null;
    if (!parsed || Number.isNaN(parsed.valueOf())) return "";
    return new Intl.DateTimeFormat("sv-SE", {
      year: "numeric", month: "2-digit", day: "2-digit", timeZone: "Asia/Tokyo",
    }).format(parsed);
  }

  function liveQuoteStateLabel(quote) {
    var marketState = String(quote && quote.marketState || "").toLowerCase();
    if (/updating|regular|open/.test(marketState)) return "取引中";
    if (/pre|post|extended|after/.test(marketState)) return "時間外";
    if (/closed|delayed/.test(marketState)) return "直近終値";
    return "ライブ価格";
  }

  function summaryDateLabel(metric) {
    if (!metric || !metric.date) return "\u65e5\u4ed8\u672a\u78ba\u8a8d";
    if (metric.stale) return metric.date + "\u30fb\u66f4\u65b0\u9045\u5ef6\uff0f\u518d\u78ba\u8a8d\u4e2d";
    return metric.live ? metric.date + "\u30fb" + liveQuoteStateLabel(metric) : metric.date;
  }

  function summaryMetric(definition) {
    var market = state.data && state.data.market ? state.data.market : {};
    var series = market.series || {};
    var macro = state.data && state.data.macro ? state.data.macro : {};
    var row = {};
    var value = null;
    if (!definition) return { value: null, date: "", change: null, sourceUrl: "" };
    if (finite(definition.value) !== null) {
      value = finite(definition.value);
      row = definition;
    } else if (definition.scope === "macro") {
      row = macro[definition.key] || {};
      value = finite(row[definition.field || "value"]);
    } else {
      row = series[definition.key] || {};
      value = finite(row[definition.field || "close"]);
    }
    var liveKey = definition.liveKey || "";
    var live = liveQuoteForKey(liveKey);
    if (live) {
      var liveFreshness = String(live.freshnessStatus || "").toLowerCase();
      var liveNeedsReview = liveFreshness === "stale" || liveFreshness === "unverified";
      return {
        value: liveNeedsReview ? null : finite(live.value),
        date: liveQuoteDate(live) || row.date || definition.date || "",
        change: !liveNeedsReview && live.referenceValidationStatus === "verified" ? finite(live.changePct) : null,
        referenceLabel: live.referenceLabel || "\u524d\u65e5\u6bd4",
        referenceValidationStatus: live.referenceValidationStatus || "unavailable",
        sourceUrl: live.sourceUrl || row.sourceUrl || definition.sourceUrl || "",
        live: true,
        liveKey: liveKey,
        quoteTime: liveQuoteTime(live),
        marketState: live.marketState || "",
        stale: liveNeedsReview,
        freshnessNote: live.freshnessNote || live.referenceError || "",
      };
    }
    var rowFreshness = String(row.freshnessStatus || "").toLowerCase();
    var rowNeedsReview = rowFreshness === "stale" || rowFreshness === "unverified";
    return {
      value: rowNeedsReview ? null : value,
      date: row.date || definition.date || "",
      change: rowNeedsReview ? null : finite(row.change1dPct),
      sourceUrl: row.sourceUrl || definition.sourceUrl || "",
      stale: rowNeedsReview,
      freshnessNote: row.freshnessNote || row.sourceNote || "",
    };
  }

  function summaryValue(metric, definition) {
    if (metric.value === null) return "未確認";
    var digits = Number.isFinite(Number(definition.digits)) ? Number(definition.digits) : 2;
    var formatter = new Intl.NumberFormat("ja-JP", {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    });
    return (definition.prefix || "") + formatter.format(metric.value) + (definition.unit || "");
  }

  function summaryChange(metric, definition) {
    if (metric.stale) return "\u57fa\u6e96\u65e5\u30fb\u53d6\u5f97\u7d4c\u8def\u3092\u518d\u78ba\u8a8d\u4e2d";
    if (metric.live) {
      var liveTime = metric.quoteTime ? formatLiveTime(metric.quoteTime, "") : "時刻未確認";
      var liveState = liveQuoteStateLabel({ marketState: metric.marketState });
      var referenceLabel = metric.referenceLabel || "前日比";
      if (metric.change === null) {
        return liveState + "・" + referenceLabel + "を再確認中 / " + liveTime;
      }
      return liveState + "・" + referenceLabel + " " + formatPercent(metric.change, true) + " / " + liveTime;
    }
    if (metric.change === null || definition.scope === "macro" || finite(definition.value) !== null) {
      return metric.date ? "基準日 " + metric.date : "基準日未確認";
    }
    return "前日比 " + formatPercent(metric.change, true) + (metric.date ? " / " + metric.date : "");
  }

  function summaryDirection(metric) {
    if (metric.change === null) return "unknown";
    if (Math.abs(metric.change) < 0.005) return "flat";
    return metric.change > 0 ? "up" : "down";
  }

  function summaryMoveSentence(metric, label) {
    var referenceLabel = metric.referenceLabel || "\u524d\u65e5\u6bd4";
    if (metric.stale) return label + "\u306f\u57fa\u6e96\u65e5\u30fb\u53d6\u5f97\u7d4c\u8def\u3092\u518d\u78ba\u8a8d\u4e2d\u3067\u3059\u3002";
    if (metric.change === null) return label + "\u306e" + referenceLabel + "\u306f\u518d\u78ba\u8a8d\u4e2d\u3067\u3059\u3002";
    return label + "\u306f" + referenceLabel + formatPercent(metric.change, true) + "\u3067\u3059\u3002";
  }

  function summarySourceLink(url, label) {
    return liveSourceLink(url, label);
  }

  function renderMarketSummary() {
    var container = byId("regionalMarketCards");
    var config = state.marketSummary;
    if (!container) return;
    if (!config || !Array.isArray(config.regions)) {
      container.innerHTML = '<article class="regional-market-card unavailable"><p>地域別サマリーを読み込めませんでした。</p></article>';
      byId("marketSummaryStatus").className = "status-dot error";
      byId("marketSummaryStatus").textContent = "サマリー読込失敗";
      return;
    }

    var generated = state.data && state.data.generatedAtJst ? new Date(state.data.generatedAtJst) : null;
    var liveGeneratedValue = (state.liveIntelligence || {}).generatedAtUtc || (state.liveIntelligence || {}).generatedAtJst || "";
    var liveGenerated = liveGeneratedValue ? new Date(liveGeneratedValue) : null;
    var displayGenerated = liveGenerated && !Number.isNaN(liveGenerated.valueOf()) ? liveGenerated : generated;
    var generatedAgeMinutes = displayGenerated && !Number.isNaN(displayGenerated.valueOf())
      ? (Date.now() - displayGenerated.valueOf()) / 60000 : null;
    var policyAsOf = config.policyAsOfJst ? new Date(config.policyAsOfJst) : null;
    var policyAgeDays = policyAsOf && !Number.isNaN(policyAsOf.valueOf()) ? (Date.now() - policyAsOf.valueOf()) / 86400000 : null;
    var hasFreshLive = generatedAgeMinutes !== null && generatedAgeMinutes >= -5 && generatedAgeMinutes <= 90;
    var isStale = !hasFreshLive;
    var referenceKeys = ["NIKKEI_CASH", "SP500_CASH", "CSI300_CASH", "DXY", "ACWI_CASH", "USDJPY"];
    var hasUnverifiedReference = referenceKeys.some(function (key) {
      var quote = liveQuoteMap()[key] || {};
      return quote.referenceValidationStatus !== "verified";
    });
    var policyNeedsDateCheck = policyAgeDays !== null && policyAgeDays > 1;
    var dateTimeFormat = new Intl.DateTimeFormat("ja-JP", {
      dateStyle: "medium",
      timeStyle: "short",
      timeZone: "Asia/Tokyo",
    });

    byId("marketSummaryStatus").className = "status-dot " + (isStale || hasUnverifiedReference ? "warn" : "ok");
    byId("marketSummaryStatus").textContent = isStale
      ? "価格の基準日時を確認"
      : hasUnverifiedReference ? "一部の価格基準値を再確認中" : policyNeedsDateCheck ? "ライブ価格を確認済み（政策文は日付確認）" : "ライブ価格を確認済み";
    byId("marketSummaryDataAsOf").textContent = displayGenerated && !Number.isNaN(displayGenerated.valueOf())
      ? dateTimeFormat.format(displayGenerated) : "未確認";
    byId("marketSummaryPolicyAsOf").textContent = policyAsOf && !Number.isNaN(policyAsOf.valueOf())
      ? dateTimeFormat.format(policyAsOf) : "未確認";
    var headlineSp = summaryMetric({ key: "SP500", liveKey: "SP500_CASH" });
    var headlineAcwi = summaryMetric({ key: "ACWI", liveKey: "ACWI_CASH" });
    var headlineGold = summaryMetric({ key: "GOLD" });
    byId("marketSummaryHeadline").textContent =
      summaryMoveSentence(headlineSp, "S&P 500") + " "
      + summaryMoveSentence(headlineAcwi, "オールカントリー代理の上場投資信託（ETF）") + " "
      + summaryMoveSentence(headlineGold, "金先物") + " "
      + (config.headlinePolicy || "");
    byId("marketSummaryNote").textContent = config.importantLimit || "各指標は公表頻度が異なるため、基準日を個別に確認してください。";

    container.innerHTML = config.regions.map(function (region) {
      var fallbackLiveKeys = {
        japan: { stock: "NIKKEI_CASH", fx: "USDJPY" },
        "united-states": { stock: "SP500_CASH", fx: "DXY" },
        china: { stock: "CSI300_CASH" },
        "all-country": { stock: "ACWI_CASH", fx: "DXY" },
      };
      var fallback = fallbackLiveKeys[region.id] || {};
      var stock = summaryMetric(Object.assign({}, region.stock || {}, { liveKey: (region.stock || {}).liveKey || fallback.stock || "" }));
      var fx = summaryMetric(Object.assign({}, region.fx || {}, { liveKey: (region.fx || {}).liveKey || fallback.fx || "" }));
      var rate = summaryMetric(region.rate);
      var extra = region.extra ? summaryMetric(region.extra) : null;
      var direction = summaryDirection(stock);
      var stateText = direction === "up" ? "主な株価は上昇" : direction === "down" ? "主な株価は下落" : direction === "flat" ? "主な株価は横ばい" : "主な株価は未確認";
      var stockClass = stock.live ? " class=\"is-live\"" : "";
      var fxClass = fx.live ? " class=\"is-live\"" : "";
      var extraClass = extra && extra.live ? " class=\"is-live\"" : "";
      var policy = region.policy || {};
      var policySources = Array.isArray(policy.sources) ? policy.sources : [];
      var sourceLinks = policySources.map(function (source) {
        return summarySourceLink(source.url, source.label);
      }).join("<span aria-hidden=\"true\"> / </span>");
      var extraMetric = region.extra ? '<div' + extraClass + '><span>' + escapeHtml(region.extra.category || "補足") + '</span><small>'
        + summarySourceLink(extra.sourceUrl, region.extra.label) + '</small><strong>' + escapeHtml(summaryValue(extra, region.extra))
        + '</strong><em class="' + summaryDirection(extra) + '">' + escapeHtml(summaryChange(extra, region.extra)) + "</em></div>" : "";
      return '<article class="regional-market-card region-' + escapeHtml(region.id || "other") + '" data-direction="' + escapeHtml(direction) + '">'
        + '<div class="regional-market-card-heading"><div><span>REGION</span><h3>' + escapeHtml(region.name || "地域") + '</h3><small class="regional-market-state ' + escapeHtml(direction) + '">' + escapeHtml(stateText) + '</small></div>'
        + '<span class="regional-market-date">' + escapeHtml(summaryDateLabel(stock)) + "</span></div>"
        + '<p class="regional-market-summary">' + escapeHtml(summaryMoveSentence(stock, region.stock.label) + " " + (region.summary || "政策材料を確認中です。")) + "</p>"
        + '<div class="regional-market-metrics' + (region.extra ? " has-extra" : "") + '">'
        + '<div' + stockClass + '><span>株</span><small>' + summarySourceLink(stock.sourceUrl, region.stock.label) + '</small><strong>' + escapeHtml(summaryValue(stock, region.stock)) + '</strong><em class="' + summaryDirection(stock) + '">' + escapeHtml(summaryChange(stock, region.stock)) + "</em></div>"
        + '<div' + fxClass + '><span>為替</span><small>' + summarySourceLink(fx.sourceUrl, region.fx.label) + '</small><strong>' + escapeHtml(summaryValue(fx, region.fx)) + '</strong><em class="' + summaryDirection(fx) + '">' + escapeHtml(summaryChange(fx, region.fx)) + "</em></div>"
        + '<div><span>金利</span><small>' + summarySourceLink(rate.sourceUrl, region.rate.label) + '</small><strong>' + escapeHtml(summaryValue(rate, region.rate)) + '</strong><em class="flat">' + escapeHtml(summaryChange(rate, region.rate)) + "</em></div>"
        + extraMetric
        + "</div>"
        + '<div class="regional-policy"><span>' + escapeHtml(policy.label || "政策・政治") + '</span><p>' + escapeHtml(policy.text || "確認中です。") + "</p>"
        + (sourceLinks ? '<div class="regional-policy-sources">' + sourceLinks + "</div>" : "")
        + "</div></article>";
    }).join("");
  }

  function renderDecisionPath() {
    var comparison = state.globalComparison;
    var market = state.data && state.data.market ? state.data.market : {};
    var path = market.sakakibaraAnalysis && market.sakakibaraAnalysis.marketPath
      ? market.sakakibaraAnalysis.marketPath : {};
    var usRisk = market.usBubbleRisk || {};
    var nikkeiSeries = market.series && market.series.NIKKEI ? market.series.NIKKEI : {};
    var hy = state.data && state.data.macro ? state.data.macro.highYieldOas || {} : {};
    if (!comparison || !comparison.theoreticalModels || !comparison.theoreticalModels.nikkei225) return;

    var model = comparison.theoreticalModels.nikkei225;
    var latest = model.latest || {};
    var panic = comparison.panicOvershootModel || {};
    var current = finite(nikkeiSeries.close) || finite(latest.market);
    var normalizationScore = finite(path.normalization && path.normalization.score);
    var panicScore = finite(path.panic && path.panic.score);
    var vix = finite(market.series && market.series.VIX && market.series.VIX.close);
    var oas = finite(hy.valuePct);
    var premium = finite(latest.marketPremiumPct);
    var routeLabel = path.label || "経路を判定できません";
    var normalMove = current && finite(latest.central) !== null ? (latest.central / current - 1) * 100 : null;
    var panicMove = current && finite(panic.panicCentralJpy) !== null ? (panic.panicCentralJpy / current - 1) * 100 : null;

    byId("pathAsOf").textContent = "市場 " + (state.data.marketDate || "未確認") + " / 価値モデル " + String(model.latestDate || "未確認").slice(0, 7);
    byId("pathFairValue").textContent = "中心 " + formatNikkei(latest.central) + "（" + formatNikkei(latest.low) + "～" + formatNikkei(latest.high) + "）";
    byId("pathPremium").textContent = premium === null ? "未算出" : "市場は中心より" + formatPercent(premium, true);
    byId("pathCollapse").textContent = finite(usRisk.score) === null
      ? "米国崩壊進行度を確認中" : "米国 " + numberOne.format(usRisk.score) + "/100・" + (usRisk.stageLabel || "段階を確認");
    byId("pathRoute").textContent = routeLabel;
    byId("pathBottom").textContent = "正常化 " + formatNikkei(latest.central) + " / パニック " + formatNikkei(panic.panicCentralJpy);

    byId("currentRouteBadge").textContent = routeLabel;
    byId("currentRouteBadge").dataset.route = path.statusCode || "unknown";
    byId("routeSummary").textContent =
      "正常化方向 " + (normalizationScore === null ? "未確認" : numberOne.format(normalizationScore) + "/100")
      + "、パニック方向 " + (panicScore === null ? "未確認" : numberOne.format(panicScore) + "/100")
      + "。VIX " + (vix === null ? "未確認" : numberOne.format(vix))
      + "、米国HY OAS " + (oas === null ? "未確認" : numberTwo.format(oas) + "%")
      + "です。これは直近の方向判定で、将来の経路を保証しません。";
    byId("routeExpectationValue").textContent = formatNikkei(latest.latestEarningsValue);
    byId("routeNormalizationValue").textContent =
      formatNikkei(latest.central) + "（" + formatNikkei(latest.low) + "～" + formatNikkei(latest.high) + "）";
    byId("routePanicValue").textContent =
      formatNikkei(panic.panicCentralJpy) + "（" + formatNikkei(panic.panicCentralRangeLowJpy) + "～" + formatNikkei(panic.panicCentralRangeHighJpy) + "）";
    byId("routeSevereFloor").textContent = formatNikkei(panic.severeSensitivityFloorJpy);

    byId("nikkeiRouteStatus").textContent = routeLabel;
    byId("nikkeiRouteStatus").dataset.route = path.statusCode || "unknown";
    byId("nikkeiPathExplanation").textContent =
      "現在は正常化方向 " + (normalizationScore === null ? "未確認" : numberOne.format(normalizationScore) + "/100")
      + "、パニック方向 " + (panicScore === null ? "未確認" : numberOne.format(panicScore) + "/100")
      + "です。市場横断のパニックが確認されない間は第1～2層を基本経路とし、信用悪化が加速した場合に第3層を重くします。";
    byId("nikkeiExpectationRange").textContent = formatNikkei(latest.latestEarningsValue);
    byId("nikkeiNormalizationRange").textContent =
      formatNikkei(latest.central) + " / 幅 " + formatNikkei(latest.low) + "～" + formatNikkei(latest.high);
    byId("nikkeiPanicRange").textContent =
      formatNikkei(panic.panicCentralJpy) + " / 帯 " + formatNikkei(panic.panicCentralRangeLowJpy) + "～" + formatNikkei(panic.panicCentralRangeHighJpy);
    byId("nikkeiPanicSevere").textContent = formatNikkei(panic.severeSensitivityFloorJpy);

    byId("todayNikkeiZone").textContent = "正常化 " + formatNikkei(latest.low) + "～" + formatNikkei(latest.high);
    byId("todayNikkeiBottomMessage").textContent =
      "現在は「" + routeLabel + "」。パニック中心帯は " + formatNikkei(panic.panicCentralRangeLowJpy) + "～" + formatNikkei(panic.panicCentralRangeHighJpy)
      + "ですが、予測ではなく信用収縮時のストレス帯です。";
    byId("todayNikkeiDistance").textContent = normalMove === null ? "未算出" : formatPercent(normalMove, true);
    byId("todayNikkeiProximity").textContent = panicMove === null ? "未算出" : formatPercent(panicMove, true);
  }

  function renderCrashLens(evidence, gates) {
    var valuationNode = byId("crashLensValuationStatus");
    var leverageNode = byId("crashLensLeverageStatus");
    var confirmationNode = byId("crashLensConfirmationStatus");
    if (!valuationNode || !leverageNode || !confirmationNode) return;

    var currentSignals = ((((state.moneyStrategist || {}).audit || {}).currentSignals) || {});
    var cape = currentSignals.cape || {};
    var top10 = currentSignals.top10WeightPct || {};
    var valuationParts = [];
    if (finite(cape.value) !== null) {
      valuationParts.push("CAPE Ratio " + numberTwo.format(cape.value) + (cape.date ? "（" + cape.date + "）" : ""));
    }
    if (finite(top10.value) !== null) {
      valuationParts.push("上位10社 " + numberOne.format(top10.value) + "%" + (top10.date ? "（" + top10.date + "）" : ""));
    }
    valuationNode.textContent = valuationParts.length ? valuationParts.join(" / ") : "評価指標を取得できません";

    var margin = (state.marginDebt || {}).latest || {};
    var leverageParts = [];
    if (finite(margin.marginDebtUsdMillions) !== null) leverageParts.push("信用買い残 " + formatMarginDebt(margin.marginDebtUsdMillions));
    if (finite(margin.marginDebtToGdpPct) !== null) leverageParts.push("GDP比 " + numberTwo.format(margin.marginDebtToGdpPct) + "%");
    if (finite(margin.marginDebtChange12mPct) !== null) leverageParts.push("前年比 " + formatPercent(margin.marginDebtChange12mPct, true));
    leverageNode.textContent = leverageParts.length
      ? leverageParts.join(" / ") + (margin.date ? "（" + formatMonthJa(margin.date) + "）" : "")
      : "信用レバレッジ指標を取得できません";

    function gateText(value) {
      return value === "true" ? "充足" : value === "false" ? "未充足" : "未確認";
    }
    confirmationNode.textContent = (gates.collapseName || "判定不能")
      + " / 崩壊確認 " + numberOne.format(evidence.observed) + "/80点"
      + " / ゲートA " + gateText(gates.A)
      + "・B " + gateText(gates.B)
      + "・C " + gateText(gates.C);
  }

  function renderPremarketBriefing() {
    var root = byId("premarketBriefing");
    var lead = byId("premarketLead");
    var cardsNode = byId("premarketCards");
    if (!root || !lead || !cardsNode) return;
    var live = state.liveIntelligence || {};
    var premarket = live.premarket || {};
    var quotes = premarket.quotes || {};
    var keys = Object.keys(quotes);
    if (!keys.length) {
      root.dataset.state = "missing";
      lead.innerHTML = "<strong>先物・時間外情報を取得できませんでした。</strong><p>公開スナップショットの更新時刻と取得元を確認してください。</p>";
      cardsNode.innerHTML = "<p class=\"briefing-empty\">日経先物、米国株先物、ドル円、米金利、VIXは現在未確認です。</p>";
      if (byId("premarketCheckedAt")) byId("premarketCheckedAt").textContent = "確認時刻なし";
      if (byId("premarketMarketState")) byId("premarketMarketState").textContent = "取得不能";
      return;
    }

    root.dataset.state = "ready";
    if (byId("premarketCheckedAt")) byId("premarketCheckedAt").textContent = formatLiveTime(premarket.checkedAtUtc, "");
    if (byId("premarketMarketState")) byId("premarketMarketState").textContent = premarket.marketStateLabel || "更新状態未確認";
    var primaryKey = premarket.primaryNikkeiFutureKey;
    var primary = primaryKey ? (quotes[primaryKey] || {}) : {};
    var gapPct = finite(premarket.nikkeiFutureCashGapPct);
    var gapPoints = finite(premarket.nikkeiFutureCashGapPoints);
    var cues = (premarket.strategyCues || []).slice(0, 4);
    lead.innerHTML = "<span class=\"label\">東証休場中の中心情報</span>"
      + "<strong>" + escapeHtml(primary.shortLabel || "日経先物") + " "
      + escapeHtml(primaryKey ? formatLiveValue(primaryKey, primary) : "未確認") + "</strong>"
      + "<p>現物終値比 " + escapeHtml(formatPercent(gapPct, true))
      + (gapPoints === null ? "" : "（" + escapeHtml(nikkeiFormat.format(gapPoints)) + "ポイント）")
      + "。米国4指数先物の平均 " + escapeHtml(formatPercent(finite(premarket.usFuturesAverageChangePct), true))
      + "。先物差は予想始値ではありません。</p>"
      + (cues.length ? "<ul class=\"premarket-cue-list\">" + cues.map(function (cue) {
        return "<li data-state=\"" + escapeHtml(cue.state || "neutral") + "\"><strong>"
          + escapeHtml(cue.title || "") + "</strong><span>" + escapeHtml(cue.text || "") + "</span></li>";
      }).join("") + "</ul>" : "");

    var order = [
      "NIKKEI_FUTURES_YEN",
      "NIKKEI_FUTURES_USD",
      "SP500_FUTURES",
      "NASDAQ100_FUTURES",
      "DOW_FUTURES",
      "RUSSELL2000_FUTURES",
      "USDJPY",
      "US10Y",
      "VIX",
    ];
    cardsNode.innerHTML = order.filter(function (key) { return quotes[key]; }).map(function (key) {
      var quote = quotes[key] || {};
      var change = quote.referenceValidationStatus === "verified" ? finite(quote.changePct) : null;
      var direction = premarketDirection(key, change);
      var stateLabel = quote.marketState === "updating" ? "取引・更新中" : "休場または遅延";
      var sparkline = liveSparkline(quote.sparkline, direction.tone, "直近1週間の価格推移");
      return "<article class=\"premarket-card\" data-key=\"" + escapeHtml(key) + "\">"
        + "<span>" + escapeHtml(quote.group === "japan" ? "日本株先物" : quote.group === "us" ? "米国株先物" : quote.group === "fx" ? "為替" : quote.group === "rates" ? "米国金利" : "市場心理") + "</span>"
        + "<h4>" + escapeHtml(quote.label || key) + "</h4>"
        + "<strong class=\"premarket-card-value\">" + escapeHtml(formatLiveValue(key, quote)) + "</strong>"
        + "<span class=\"premarket-card-change " + direction.tone + "\">" + escapeHtml(quote.referenceLabel || "前日比") + " " + direction.marker + " "
        + escapeHtml(formatLiveChange(key, quote)) + "</span>"
        + (sparkline ? "<div class=\"premarket-sparkline\">" + sparkline + "<small>1週間の推移（直近5取引日）</small></div>" : "")
        + "<small class=\"premarket-card-meta\">" + escapeHtml(stateLabel) + " / "
        + escapeHtml(formatLiveTime(quote.quoteTimeUtc, "値 ")) + "</small>"
        + liveSourceLink(quote.sourceUrl, "価格取得元を確認", "premarket-source-link")
        + "</article>";
    }).join("");
    if (byId("premarketCaution")) byId("premarketCaution").textContent = premarket.caution || premarket.summary || "";
  }

  function verificationLabel(value) {
    var labels = {
      primary: "一次資料",
      "primary-statement": "本人・公式発言",
      "archived-statement": "第三者アーカイブ",
      reported: "報道",
      "reported-unconfirmed": "主要報道・公式未確認",
      "public-indexed": "公開索引",
      unverified: "未確認",
    };
    return labels[value] || value || "確認状態不明";
  }

  function briefingFilterMatches(topic, sourceKind, filter) {
    if (!filter || filter === "all") return true;
    if (filter === "us") return topic === "us-stocks" || sourceKind === "official-us";
    if (filter === "jp") {
      return topic === "japan-stocks" || sourceKind === "official-japan" || sourceKind === "official-company";
    }
    if (filter === "ai") return topic === "ai-bubble";
    return topic === filter;
  }

  function isJapaneseText(value) {
    return /[ぁ-んァ-ヶ一-龠々ー]/.test(String(value || ""));
  }

  function firstBriefingText(values) {
    for (var index = 0; index < values.length; index += 1) {
      if (typeof values[index] === "string" && values[index].trim()) return values[index].trim();
    }
    return "";
  }

  function briefingCopy(item) {
    item = item || {};
    var original = item.original && typeof item.original === "object" ? item.original : {};
    var structuredJapanese = item.japanese && typeof item.japanese === "object" ? item.japanese : {};
    var reference = item.referenceTranslation && typeof item.referenceTranslation === "object"
      ? item.referenceTranslation : {};
    var translation = item.translation && typeof item.translation === "object" ? item.translation : {};
    var translatedJapanese = translation.ja && typeof translation.ja === "object" ? translation.ja : {};
    var originalTitle = firstBriefingText([
      original.title, item.originalTitle, item.titleOriginal, item.sourceTitle, item.headlineOriginal, item.title,
    ]);
    var originalSummaryExplicit = firstBriefingText([
      original.excerpt, original.summary, item.originalSummary, item.summaryOriginal, item.sourceSummary, item.descriptionOriginal,
    ]);
    var japaneseTitle = firstBriefingText([
      structuredJapanese.title, item.titleJa, item.japaneseTitle, item.translatedTitleJa,
      reference.title, translatedJapanese.title, isJapaneseText(item.title) ? item.title : "",
    ]);
    var japaneseSummary = firstBriefingText([
      structuredJapanese.summary, item.summaryJa, item.japaneseSummary, item.translatedSummaryJa,
      reference.summary, translatedJapanese.summary, isJapaneseText(item.summary) ? item.summary : "",
    ]);
    var originalSummary = originalSummaryExplicit || (!isJapaneseText(item.summary) ? firstBriefingText([item.summary]) : "");
    var originalIsJapanese = isJapaneseText(originalTitle) || isJapaneseText(originalSummary);
    var originalLanguage = firstBriefingText([original.language, item.originalLanguage, item.language]) || (originalIsJapanese ? "ja" : "en");
    var translationMode = firstBriefingText([
      structuredJapanese.mode,
      item.translationType,
      item.translationStatus,
      reference.type,
      reference.status,
      translatedJapanese.type,
      translatedJapanese.status,
      typeof item.translation === "string" ? item.translation : "",
    ]).toLowerCase();
    var hasJapaneseReference = Boolean(japaneseTitle || japaneseSummary);
    var translationLabel = firstBriefingText([structuredJapanese.label]);
    if (!translationLabel && translationMode === "structured-gist") translationLabel = "構造化要旨（翻訳ではありません）";
    else if (!translationLabel && translationMode === "editorial-summary") translationLabel = "編集要約";
    else if (!translationLabel && translationMode === "source-japanese") translationLabel = "日本語原文";
    else if (!translationLabel && originalIsJapanese) translationLabel = "日本語原文";
    else if (!translationLabel && hasJapaneseReference && /human|reviewed|verified|checked|editor/.test(translationMode)) translationLabel = "参考訳・確認済み";
    else if (!translationLabel && hasJapaneseReference && /machine|automatic|auto|ai|deepl/.test(translationMode)) translationLabel = "参考訳・自動";
    else if (!translationLabel && hasJapaneseReference) translationLabel = "参考訳";
    else if (!translationLabel) translationLabel = "日本語情報未取得";
    return {
      japaneseTitle: japaneseTitle,
      japaneseSummary: japaneseSummary,
      originalTitle: originalTitle,
      originalSummary: originalSummary,
      originalLanguage: originalLanguage,
      translationLabel: translationLabel,
      translationMode: translationMode,
      translationState: originalIsJapanese ? "original" : hasJapaneseReference ? "available" : "missing",
    };
  }

  function externalJapaneseUrl(value) {
    var safeUrl = safeHttpsUrl(value);
    return safeUrl ? "https://translate.google.com/translate?sl=auto&tl=ja&u=" + encodeURIComponent(safeUrl) : "";
  }

  function originalSourceLinkLabel(value) {
    var safeUrl = safeHttpsUrl(value);
    if (!safeUrl) return "原文リンク未確認";
    try {
      var host = new URL(safeUrl).hostname.toLowerCase();
      if (host === "news.google.com") return "元記事を開く（Google News経由）";
      if (host === "www.bing.com" || host === "bing.com") return "元記事を開く（Bing経由）";
    } catch (_error) {
      return "原文を開く";
    }
    return "原文を直接開く";
  }

  function briefingTimestampValue(item) {
    return item && (item.effectivePublishedAtUtc || item.publishedAtUtc || item.indexedAtUtc || item.publishedAt || item.datePublished);
  }

  function briefingTimestamp(item) {
    var value = briefingTimestampValue(item);
    var parsed = value ? new Date(value) : null;
    return parsed && !Number.isNaN(parsed.valueOf()) ? parsed.valueOf() : null;
  }

  function briefingPublicationLabel(item) {
    var value = briefingTimestampValue(item);
    if (!value || briefingTimestamp(item) === null) return "時刻未確認";
    var basis = String(item && item.timestampBasis || "").toLowerCase();
    var precision = String(item && item.timestampPrecision || "").toLowerCase();
    if (precision === "date" || precision === "day") {
      var dateOnly = new Intl.DateTimeFormat("ja-JP", {
        year: "numeric", month: "numeric", day: "numeric", timeZone: "Asia/Tokyo",
      }).format(new Date(value));
      return "日付のみ " + dateOnly;
    }
    var timeText = formatLiveTime(value, "") + " JST";
    return basis === "index-seen" ? "海外索引で発見 " + timeText : timeText;
  }

  function briefingFreshnessTone(value) {
    var key = String(value || "unknown").toLowerCase().replace(/^is-/, "");
    if (key === "breaking" || key === "fresh" || key === "realtime") return "is-fresh";
    if (key === "developing" || key === "recent") return "is-recent";
    if (key === "today") return "is-today";
    if (key === "context" || key === "aging" || key === "aged") return "is-context";
    if (key === "old" || key === "stale") return "is-old";
    return "is-unknown";
  }

  function briefingFreshness(item) {
    var timestamp = briefingTimestamp(item);
    var precision = String(item && item.timestampPrecision || "").toLowerCase();
    if (timestamp !== null && (precision === "date" || precision === "day")) {
      return { label: "日付のみ", tone: "is-context", bucket: "context", ageMinutes: null };
    }
    if (timestamp !== null) {
      var currentAgeMinutes = Math.max(0, (Date.now() - timestamp) / 60000);
      if (currentAgeMinutes <= 30) return { label: "30分以内", tone: "is-fresh", bucket: "breaking", ageMinutes: currentAgeMinutes };
      if (currentAgeMinutes <= 180) return { label: "3時間以内", tone: "is-recent", bucket: "developing", ageMinutes: currentAgeMinutes };
      if (currentAgeMinutes <= 1440) return { label: "24時間以内", tone: "is-today", bucket: "today", ageMinutes: currentAgeMinutes };
      return { label: "背景情報", tone: "is-context", bucket: "context", ageMinutes: currentAgeMinutes };
    }
    var provided = item && item.freshness && typeof item.freshness === "object" ? item.freshness : {};
    var providedAgeMinutes = finite(provided.ageMinutes);
    if (provided.label || provided.tone || provided.bucket || providedAgeMinutes !== null) {
      return {
        label: firstBriefingText([provided.label]) || (providedAgeMinutes === null ? "鮮度未確認" : Math.round(providedAgeMinutes) + "分前"),
        tone: briefingFreshnessTone(provided.tone || provided.bucket),
        bucket: provided.bucket || "unknown",
        ageMinutes: providedAgeMinutes,
      };
    }
    return { label: "鮮度未確認", tone: "is-unknown", bucket: "unknown", ageMinutes: null };
  }

  function corroborationLabel(value) {
    return {
      "official-primary": "公式一次資料",
      "multi-source": "複数の独立ソース",
      "single-source": "単一ソース",
    }[value] || "確認状態未分類";
  }

  function briefingRelatedLinksMarkup(item) {
    var links = Array.isArray(item.relatedLinks) ? item.relatedLinks : [];
    if (!links.length) return "<p class=\"briefing-related-empty\">同一話題の別原文はありません。</p>";
    return "<div class=\"briefing-related-links\"><strong>同一話題の関連原文</strong><ul>" + links.map(function (link) {
      var label = link.title || (link.source ? link.source + "の原文" : "関連原文を直接開く");
      return "<li>" + liveSourceLink(link.url, label, "briefing-related-link")
        + "<small>" + escapeHtml(link.source || "情報源不明") + " / "
        + escapeHtml(verificationLabel(link.verification)) + " / "
        + escapeHtml(briefingPublicationLabel(link))
        + (link.rankingEvidence === false ? " / 補助検索（順位証拠には不使用）" : "")
        + "</small></li>";
    }).join("") + "</ul></div>";
  }

  function briefingCardMarkup(item) {
    item = item || {};
    var topic = item.topicKey || "policy";
    var sourceKind = item.sourceKind || "other";
    var verification = item.verification || "unverified";
    var verificationState = verification === "primary" || verification === "primary-statement"
      ? "confirmed"
      : verification === "unverified" || verification === "public-indexed" ? "unverified" : "reported";
    var stanceLabels = { bullish: "強気", bearish: "弱気", mixed: "強弱混在", neutral: "中立・方向なし" };
    var talk = finite(item.talkScore);
    var priority = finite(item.priorityScore);
    var independentSources = finite(item.independentSourceCount);
    var clusterSize = finite(item.clusterSize);
    var rankingClusterSize = finite(item.rankingClusterSize);
    var rankingClusterMarkup = rankingClusterSize !== null && clusterSize !== null && rankingClusterSize !== clusterSize
      ? "<span><small>順位証拠クラスタ</small><strong>" + escapeHtml(nikkeiFormat.format(rankingClusterSize) + "件") + "</strong></span>"
      : "";
    var issuerMentions = finite(item.issuerNewsMentionCount);
    var issuerNewsSources = finite(item.issuerIndependentNewsSourceCount);
    var issuerBuzz = finite(item.issuerBuzzScore);
    var issuerBuzzMarkup = sourceKind === "official-company"
      ? "<span><small>全社共通検索の会社言及</small><strong>" + escapeHtml(issuerMentions === null ? "未算出" : nikkeiFormat.format(issuerMentions) + "件") + "</strong></span>"
        + "<span><small>会社言及の独立配信元</small><strong>" + escapeHtml(issuerNewsSources === null ? "未算出" : nikkeiFormat.format(issuerNewsSources) + "件") + "</strong></span>"
        + "<span><small>会社話題度</small><strong>" + escapeHtml(issuerBuzz === null ? "未算出" : nikkeiFormat.format(issuerBuzz) + "/12") + "</strong></span>"
      : "";
    var evidenceNote = sourceKind === "official-company"
      ? "表示クラスタ件数は直接開ける関連記事を含みます。独立ソース数と順位証拠クラスタは、全社共通の一般ニュース・通信社記事だけで比較し、企業別の追加検索とSNS投稿は順位を自己強化しないよう除外しています。会社話題度も同じ原則で算出します。"
      : "独立ソース数は発信元の異なる報道・一次資料を数え、クラスタ件数は転載や同内容の記事を含み得ます。";
    var copy = briefingCopy(item);
    var freshness = briefingFreshness(item);
    var originalTitle = copy.originalTitle || "Original headline unavailable";
    var japaneseTitle = copy.japaneseTitle || "日本語見出し未取得";
    var japaneseSummary = copy.japaneseSummary || "外部日本語表示または原文で内容を確認してください。";
    var originalSummaryMarkup = copy.originalSummary
      ? "<p class=\"briefing-original-summary\">" + escapeHtml(copy.originalSummary) + "</p>"
      : "<p class=\"briefing-copy-missing\" lang=\"ja\">原文要約は取得範囲にありません。原文リンクで確認してください。</p>";
    var authorMarkup = item.author ? "<span>発信者 " + escapeHtml(item.author) + "</span>" : "";
    return "<article class=\"briefing-card\" data-briefing-card=\"true\" data-briefing-id=\"" + escapeHtml(item.id || "")
      + "\" data-topic=\"" + escapeHtml(topic)
      + "\" data-source-kind=\"" + escapeHtml(sourceKind) + "\" data-verification=\"" + escapeHtml(verificationState) + "\">"
      + "<div class=\"briefing-card-head\"><span class=\"briefing-topic-badge\">" + escapeHtml(item.topic || topic) + "</span>"
      + "<span class=\"briefing-source-badge\">" + escapeHtml(item.source || "情報源不明") + "</span>"
      + "<span class=\"briefing-freshness-badge " + freshness.tone + "\" data-briefing-freshness>" + escapeHtml(freshness.label) + "</span></div>"
      + "<div class=\"briefing-language-grid\">"
      + "<section class=\"briefing-copy briefing-copy-ja\" lang=\"ja\"><span class=\"briefing-language-label\">"
      + escapeHtml(copy.translationLabel) + "</span><h4>" + escapeHtml(japaneseTitle) + "</h4><p>" + escapeHtml(japaneseSummary) + "</p></section>"
      + "<section class=\"briefing-copy briefing-copy-original\" lang=\"" + escapeHtml(copy.originalLanguage) + "\"><span class=\"briefing-language-label\">原文</span>"
      + "<p class=\"briefing-original-title\">" + escapeHtml(originalTitle) + "</p>" + originalSummaryMarkup + "</section></div>"
      + "<div class=\"briefing-card-facts\"><span><small>鮮度</small><strong data-briefing-freshness-fact>" + escapeHtml(freshness.label) + "</strong></span>"
      + "<span><small>公表・発見</small><strong>" + escapeHtml(briefingPublicationLabel(item)) + "</strong></span>"
      + "<span><small>検証</small><strong>" + escapeHtml(verificationLabel(verification)) + "</strong></span>"
      + "<span><small>日本語欄</small><strong>" + escapeHtml(copy.translationLabel) + "</strong></span></div>"
      + "<div class=\"briefing-card-meta\"><span>方向 " + escapeHtml(stanceLabels[item.stance] || "未分類") + "</span>"
      + "<span>重要度 " + escapeHtml(priority === null ? "未算出" : nikkeiFormat.format(priority)) + "</span>"
      + "<span>取得範囲の注目度 " + escapeHtml(talk === null ? "未算出" : nikkeiFormat.format(talk) + "/100") + "</span>"
      + authorMarkup + "<span>" + escapeHtml(formatLiveTime(item.retrievedAtUtc, "取得 ")) + " JST</span></div>"
      + "<div class=\"briefing-source-links briefing-card-source-links\">"
      + liveSourceLink(item.url, originalSourceLinkLabel(item.url), "briefing-original-link")
      + liveSourceLink(externalJapaneseUrl(item.url), "外部日本語表示", "briefing-japanese-link") + "</div>"
      + "<details class=\"briefing-card-details\"><summary>根拠・制約を確認</summary>"
      + "<p>" + escapeHtml(item.identityNote || "掲載元、時刻、本文をリンク先で確認してください。") + "</p>"
      + "<div class=\"briefing-evidence-stats\"><span><small>独立ソース</small><strong>"
      + escapeHtml(independentSources === null ? "未算出" : nikkeiFormat.format(independentSources) + "件") + "</strong></span>"
      + "<span><small>同一話題クラスタ</small><strong>" + escapeHtml(clusterSize === null ? "未算出" : nikkeiFormat.format(clusterSize) + "件") + "</strong></span>"
      + rankingClusterMarkup
      + issuerBuzzMarkup
      + "<span><small>裏付け</small><strong>" + escapeHtml(corroborationLabel(item.corroborationState)) + "</strong></span></div>"
      + "<p class=\"briefing-evidence-note\">" + escapeHtml(evidenceNote) + "</p>"
      + briefingRelatedLinksMarkup(item) + "</details></article>";
  }

  function currentBriefingFilter() {
    var selected = document.querySelector("input[name='briefing-topic']:checked");
    return selected ? selected.value : "all";
  }

  function currentBriefingSort() {
    var selected = document.querySelector("input[name='briefing-sort']:checked");
    return selected ? selected.value : (state.briefingSort || "latest");
  }

  function compareBriefingDates(left, right) {
    var leftTime = briefingTimestamp(left);
    var rightTime = briefingTimestamp(right);
    if (leftTime === null && rightTime !== null) return 1;
    if (leftTime !== null && rightTime === null) return -1;
    if (leftTime !== rightTime) return (rightTime || 0) - (leftTime || 0);
    return String(left.id || left.title || "").localeCompare(String(right.id || right.title || ""), "ja");
  }

  function briefingItemsForFilter(filter, sort) {
    var live = state.liveIntelligence || {};
    var briefing = live.briefing || {};
    var mode = sort || state.briefingSort || "latest";
    return (briefing.items || []).filter(function (item) {
      return briefingFilterMatches(item.topicKey || "policy", item.sourceKind || "other", filter);
    }).slice().sort(function (left, right) {
      if (mode === "priority") {
        var priorityDelta = (finite(right.priorityScore) || 0) - (finite(left.priorityScore) || 0);
        if (priorityDelta) return priorityDelta;
      }
      if (mode === "attention") {
        var attentionDelta = (finite(right.talkScore) || 0) - (finite(left.talkScore) || 0);
        if (attentionDelta) return attentionDelta;
      }
      return compareBriefingDates(left, right);
    });
  }

  function briefingMoreDetails() {
    return typeof document.querySelector === "function" ? document.querySelector(".briefing-more") : null;
  }

  function updateBriefingVisibleState(filter, matchingCount, sort) {
    var details = briefingMoreDetails();
    var primaryCount = Math.min(matchingCount, 6);
    var visibleCount = primaryCount + (details && details.open ? Math.max(0, matchingCount - 6) : 0);
    if (byId("briefingVisibleCount")) byId("briefingVisibleCount").textContent = nikkeiFormat.format(visibleCount);
    if (byId("briefingFilterStatus")) {
      var labels = { all: "すべて", us: "米国株", jp: "日本株", ai: "AIバブル", "fx-rates": "為替・金利" };
      var sortLabels = { latest: "最新順", priority: "重要度順", attention: "注目度順" };
      var remainder = Math.max(0, matchingCount - visibleCount);
      byId("briefingFilterStatus").textContent = (labels[filter] || "すべて") + "・" + (sortLabels[sort] || "最新順") + "：全"
        + matchingCount + "件中" + visibleCount + "件を表示しています。"
        + (remainder ? "残り" + remainder + "件は「続報・追加材料」にあります。" : "");
    }
  }

  function applyBriefingFilter(filter, sort) {
    var cardsNode = byId("briefingPrimaryCards");
    var moreNode = byId("briefingMoreCards");
    if (!cardsNode || !moreNode) return;
    state.briefingSort = sort || state.briefingSort || "latest";
    var matchingItems = briefingItemsForFilter(filter, state.briefingSort);
    cardsNode.innerHTML = matchingItems.slice(0, 6).map(briefingCardMarkup).join("")
      || "<p class=\"briefing-empty\">このトピックの主要速報はありません。</p>";
    moreNode.innerHTML = matchingItems.slice(6).map(briefingCardMarkup).join("")
      || "<p class=\"briefing-empty\">追加情報はありません。</p>";
    var details = briefingMoreDetails();
    if (details) {
      details.open = false;
      details.hidden = matchingItems.length <= 6;
    }
    updateBriefingVisibleState(filter, matchingItems.length, state.briefingSort);
  }

  function refreshRenderedBriefingFreshness() {
    var live = state.liveIntelligence || {};
    var items = ((live.briefing || {}).items || []);
    var byItemId = new Map(items.map(function (item) { return [String(item.id || ""), item]; }));
    document.querySelectorAll("[data-briefing-id]").forEach(function (card) {
      var item = byItemId.get(String(card.dataset.briefingId || ""));
      if (!item) return;
      var freshness = briefingFreshness(item);
      var badge = card.querySelector("[data-briefing-freshness]");
      var fact = card.querySelector("[data-briefing-freshness-fact]");
      if (badge) {
        badge.className = "briefing-freshness-badge " + freshness.tone;
        badge.textContent = freshness.label;
      }
      if (fact) fact.textContent = freshness.label;
    });
  }

  function renderLiveBriefing() {
    var root = byId("live-briefing");
    var cardsNode = byId("briefingPrimaryCards");
    var moreNode = byId("briefingMoreCards");
    if (!root || !cardsNode || !moreNode) return;
    var live = state.liveIntelligence || {};
    var briefing = live.briefing || {};
    var health = live.dataHealth || {};
    var items = briefing.items || [];
    var channels = Array.isArray(briefing.channels) ? briefing.channels : [];
    var successfulChannels = channels.filter(function (channel) { return channel.status === "ok"; }).length;
    var limitedChannels = channels.filter(function (channel) {
      return channel.status === "limited" || channel.status === "not-configured";
    }).length;
    var failedChannels = Math.max(0, channels.length - successfulChannels - limitedChannels);
    var checkedChannels = Math.max(0, channels.length - failedChannels);
    var primaryItemCount = items.filter(function (item) {
      return item.verification === "primary" || item.verification === "primary-statement";
    }).length;
    var latestPublishedItem = items.slice().sort(compareBriefingDates)[0] || null;
    var hasLiveSnapshot = Boolean(state.liveIntelligence
      && (live.generatedAtUtc || briefing.checkedAtUtc || items.length || channels.length));
    root.dataset.state = hasLiveSnapshot ? "ready" : "missing";
    if (byId("briefingCheckedAt")) byId("briefingCheckedAt").textContent = hasLiveSnapshot
      ? formatLiveTime(briefing.checkedAtUtc || live.generatedAtUtc, "") : "確認時刻なし";
    if (byId("briefingCoverage")) {
      byId("briefingCoverage").textContent = hasLiveSnapshot
        ? checkedChannels + "/" + channels.length + "経路確認（完全" + successfulChannels + "・限定" + limitedChannels + "）・" + items.length + "件"
        : "取得不能・0件";
    }
    if (byId("briefingMetricTotal")) byId("briefingMetricTotal").textContent = nikkeiFormat.format(items.length) + "件";
    if (byId("briefingMetricPrimary")) byId("briefingMetricPrimary").textContent = nikkeiFormat.format(primaryItemCount) + "件";
    if (byId("briefingMetricLatest")) byId("briefingMetricLatest").textContent = latestPublishedItem
      ? briefingPublicationLabel(latestPublishedItem) : "時刻未確認";
    if (byId("briefingMetricChannels")) byId("briefingMetricChannels").textContent = channels.length
      ? checkedChannels + "/" + channels.length + "経路確認・" + limitedChannels + "限定" : "経路未確認";
    if (byId("briefingChannelSummary")) byId("briefingChannelSummary").textContent = channels.length
      ? "取得済み" + successfulChannels + "・限定" + limitedChannels + "・失敗" + failedChannels
      : "取得経路を確認できません";

    var xApi = (live.sourceStatus || []).find(function (source) { return source.kind === "x-api"; });
    var generated = live.generatedAtUtc ? new Date(live.generatedAtUtc) : null;
    var ageMinutes = generated && !Number.isNaN(generated.valueOf()) ? (Date.now() - generated.valueOf()) / 60000 : null;
    var warnings = [];
    if (!hasLiveSnapshot) warnings.push("速報スナップショットを取得できませんでした。前回値ではなく未確認として表示します。");
    if (health.status && health.status !== "ok") warnings.push(health.message || "一部取得経路が限定または失敗しています。");
    if (xApi && xApi.status === "not-configured") warnings.push("X APIは未接続です。公開ウェブ索引とXの直接検索リンクを表示し、欠測を中立・弱気とは扱いません。");
    if (ageMinutes !== null && ageMinutes > 35) warnings.push("スナップショットは" + Math.round(ageMinutes) + "分前です。カードの取得時刻を確認してください。");
    var translationStatus = briefing.translationStatus || {};
    if (translationStatus.status === "not-configured") {
      warnings.push("日本語欄はDeepL未接続のため、英単語の置換ではなく日本語の構造化要旨を表示します。翻訳ではない項目はカード内で明記しています。");
    } else if (translationStatus.label) {
      warnings.push("日本語欄：" + translationStatus.label + "。自動訳は未校閲として原文を併記します。");
    }
    if (byId("briefingWarning")) {
      byId("briefingWarning").textContent = warnings.join(" ") || "主要経路を取得済みです。SNSの反応数は事実確認度や相場方向を意味しません。";
    }

    if (byId("briefingChannelStatus")) {
      byId("briefingChannelStatus").innerHTML = channels.map(function (channel) {
        var stateClass = channel.status === "ok" ? "is-ok" : channel.status === "limited" || channel.status === "not-configured" ? "is-limited" : "is-error";
        var directUrl = safeHttpsUrl(channel.directUrl);
        var content = "<b>" + escapeHtml(channel.label || channel.key) + "</b><small>"
          + escapeHtml(channel.statusLabel || channel.status || "不明") + "</small>";
        return directUrl
          ? "<a class=\"briefing-channel " + stateClass + "\" href=\"" + escapeHtml(directUrl)
            + "\" target=\"_blank\" rel=\"noopener noreferrer\" title=\"" + escapeHtml(channel.limitation || "") + "\">" + content + "</a>"
          : "<span class=\"briefing-channel " + stateClass + " live-source-unavailable\" aria-disabled=\"true\" title=\""
            + escapeHtml(channel.limitation || "") + "\">" + content + "</span>";
      }).join("") || "<span class=\"briefing-channel is-error\"><b>取得経路</b><small>未確認</small></span>";
    }

    var shock = live.marketShock || {};
    var lead = briefing.lead || {};
    if (byId("briefingLead")) {
      if (!hasLiveSnapshot || (!shock.instrument && finite(shock.current) === null)) {
        byId("briefingLead").innerHTML = "<article class=\"briefing-lead-card\" data-topic=\"fx-rates\" data-verification=\"unverified\">"
          + "<div class=\"briefing-card-head\"><span class=\"briefing-priority-badge\">未確認</span>"
          + "<span class=\"briefing-topic-badge\">為替・金利</span><time>時刻未確認</time></div>"
          + "<div class=\"briefing-lead-body\"><div><p class=\"briefing-eyebrow\">USD/JPY 急変監視</p>"
          + "<h4>ドル円の急変情報を取得できませんでした。</h4><p>価格、報道、財務省の確認状況を未確認として扱います。</p></div>"
          + "<dl class=\"briefing-lead-facts\"><div><dt>介入ステータス</dt><dd>未確認</dd></div>"
          + "<div><dt>現在値 / 前日比</dt><dd>未確認</dd></div><div><dt>確認レンジ</dt><dd>未確認</dd></div>"
          + "<div><dt>関連報道候補 / 取得範囲の注目度</dt><dd>未確認</dd></div></dl></div></article>";
      } else {
        var reportedCount = finite(shock.reportedEvidenceCount);
        var leadTalkScore = finite(lead.talkScore);
        var hasRecentShock = shock.recentDirectionalShock === true;
        var historicalShock = !hasRecentShock && (shock.severity === "critical" || shock.severity === "warning");
        var shockBadge = historicalShock ? "当日急変の履歴" : (shock.severityLabel || "急変監視");
        var eventEnd = shock.directionalShockEventEndUtc
          ? formatLiveTime(shock.directionalShockEventEndUtc, "") + " JST終了" : "時刻未確認";
        var eventRecency = hasRecentShock
          ? "直近3時間以内"
          : historicalShock ? "当日履歴（直近3時間の新規急変なし）" : "直近急変なし";
        var rangeText = finite(shock.sessionLow) === null || finite(shock.sessionHigh) === null
          ? "レンジ未確認" : numberThree.format(shock.sessionLow) + "～" + numberThree.format(shock.sessionHigh) + "円";
        byId("briefingLead").innerHTML = "<article class=\"briefing-lead-card\" data-topic=\"fx-rates\" data-verification=\""
          + escapeHtml(shock.officiallyConfirmed ? "confirmed" : "unverified") + "\">"
          + "<div class=\"briefing-card-head\"><span class=\"briefing-priority-badge\">" + escapeHtml(shockBadge) + "</span>"
          + "<span class=\"briefing-topic-badge\">為替・金利</span><time datetime=\"" + escapeHtml(shock.observedAtUtc || "") + "\">"
          + escapeHtml(formatLiveTime(shock.observedAtUtc, "値 ")) + "</time></div>"
          + "<div class=\"briefing-lead-body\"><div><p class=\"briefing-eyebrow\">USD/JPY 急変監視</p><h4>"
          + escapeHtml(shock.headline || "ドル円を確認中") + "</h4><p>" + escapeHtml(shock.summary || "") + "</p>"
          + "<div class=\"briefing-source-links\">" + liveSourceLink(shock.priceSourceUrl, "価格チャート", "briefing-original-link")
          + liveSourceLink(shock.officialVerificationUrl, "財務省の公式確認ページ", "briefing-original-link") + "</div></div>"
          + "<dl class=\"briefing-lead-facts\"><div><dt>介入ステータス</dt><dd>" + escapeHtml(shock.interventionLabel || "判定保留") + "</dd></div>"
          + "<div><dt>現在値 / 前日比</dt><dd>" + escapeHtml(finite(shock.current) === null ? "未確認" : numberThree.format(shock.current) + "円 / " + formatPercent(finite(shock.changePct), true)) + "</dd></div>"
          + "<div><dt>急変時刻 / 確認レンジ</dt><dd>" + escapeHtml(eventRecency + "・" + eventEnd + " / " + rangeText) + "</dd></div>"
          + "<div><dt>関連報道候補 / 取得範囲の注目度</dt><dd>" + escapeHtml((reportedCount === null ? "未確認" : reportedCount + "件")
            + " / " + (leadTalkScore === null ? "未確認" : leadTalkScore + "/100")) + "</dd></div></dl>"
          + "</div></article>";
      }
    }

    function balanceMarkup(rows, emptyText) {
      return (rows || []).slice(0, 3).map(function (row) {
        var rowUrl = safeHttpsUrl(row.url);
        var fullRow = items.find(function (item) {
          return (row.id && item.id === row.id)
            || (rowUrl && safeHttpsUrl(item.url) === rowUrl);
        }) || row;
        var copy = briefingCopy(fullRow);
        var japaneseTitle = copy.japaneseTitle || "日本語要旨未取得";
        var originalTitle = copy.originalTitle || "";
        var rowTitle = "<strong>" + escapeHtml(japaneseTitle) + "</strong>";
        var titleMarkup = rowUrl
          ? '<a href="' + escapeHtml(rowUrl) + '" target="_blank" rel="noopener noreferrer">' + rowTitle + "</a>"
          : rowTitle + ' <span class="live-source-unavailable" aria-disabled="true">（リンク未確認）</span>';
        var originalMarkup = originalTitle && originalTitle !== japaneseTitle
          ? '<span class="briefing-balance-original" lang="' + escapeHtml(copy.originalLanguage) + '">' + escapeHtml(originalTitle) + "</span>" : "";
        return "<li>" + titleMarkup + originalMarkup + "<small>" + escapeHtml(fullRow.source || "") + " / "
          + escapeHtml(verificationLabel(fullRow.verification)) + "</small></li>";
      }).join("") || "<li>" + escapeHtml(emptyText) + "</li>";
    }
    if (byId("briefingBullList")) byId("briefingBullList").innerHTML = balanceMarkup(briefing.bullish, "取得範囲で強気材料を分類できませんでした。");
    if (byId("briefingBearList")) byId("briefingBearList").innerHTML = balanceMarkup(briefing.bearish, "取得範囲で弱気材料を分類できませんでした。");

    applyBriefingFilter(currentBriefingFilter(), currentBriefingSort());
  }

  function renderAll() {
    state.valuations = state.data.companies.map(function (company) { return modelCompany(company); });
    var evidence = scoreEvidence();
    var gates = assessGates(evidence);
    var bubble = assessBubble(evidence);
    var transmission = assessJapanTransmission();
    renderMetadata();
    renderMarketSummary();
    renderPremarketBriefing();
    renderTop(evidence, gates, bubble);
    renderDailySummary(evidence, gates, bubble, transmission);
    renderLiveBriefing();
    renderSignals(evidence);
    renderGates(gates);
    renderJapanTransmission(transmission);
    renderSakakibaraMethod();
    renderNikkeiAiContributionProxy();
    renderMoneyStrategist();
    renderMarginDebt();
    renderCrashLens(evidence, gates);
    renderUsMarketIntelligence();
    renderPurchasingPower();
    updateSnapshotComparisonButtons();
    if (state.snapshotComparisonPayload) renderSnapshotComparison();
    renderMarketReading();
    renderMarketChart();
    renderDotComComparison();
    renderNikkeiBottom();
    renderBottomBusinessEvidence();
    renderDecisionPath();
    updateCompanyFilterUi();
    renderValuationChart();
    renderCompanyTable();
    setDefaultControls();
    renderCompanyDetail();
    renderSources();
    if (window.lucide) window.lucide.createIcons();
  }

  async function requestFreshUpdate() {
    var response;
    try {
      response = await fetch("api/refresh", { method: "POST", cache: "no-store", headers: { "Accept": "application/json" } });
    } catch (_error) {
      return { executed: false, reason: "static-host" };
    }
    if (response.status === 404 || response.status === 405) return { executed: false, reason: "static-host" };
    var contentType = response.headers.get("content-type") || "";
    var payload = contentType.indexOf("application/json") >= 0 ? await response.json() : null;
    if (!response.ok || !payload || !payload.ok) {
      throw new Error((payload && (payload.error || payload.detail)) || "更新処理に失敗しました");
    }
    return { executed: true, payload: payload };
  }

  function liveSnapshotGeneratedTime(snapshot) {
    var value = snapshot && snapshot.generatedAtUtc;
    var parsed = value ? new Date(value) : null;
    return parsed && !Number.isNaN(parsed.valueOf()) ? parsed.valueOf() : null;
  }

  function liveSnapshotCandidateIsValid(candidate) {
    if (!candidate || typeof candidate !== "object" || Array.isArray(candidate)) return false;
    var generatedAt = candidate.generatedAtUtc || candidate.generatedAtJst;
    if (!generatedAt || Number.isNaN(new Date(generatedAt).valueOf())) return false;
    if (!candidate.briefing || typeof candidate.briefing !== "object" || Array.isArray(candidate.briefing)) return false;
    if (!candidate.premarket || typeof candidate.premarket !== "object" || Array.isArray(candidate.premarket)) return false;
    if (!candidate.premarket.quotes || typeof candidate.premarket.quotes !== "object" || Array.isArray(candidate.premarket.quotes)) return false;
    if (!Object.keys(candidate.premarket.quotes).length) return false;
    if (!Object.keys(candidate.premarket.quotes).every(function (key) { var quote = candidate.premarket.quotes[key]; return quote && typeof quote === "object" && !Array.isArray(quote); })) return false;
    if (!Array.isArray(candidate.briefing.items)) return false;
    if (!candidate.briefing.items.every(function (item) {
      return item && typeof item === "object" && !Array.isArray(item);
    })) return false;
    if (candidate.briefing.channels !== undefined && (
      !Array.isArray(candidate.briefing.channels) || !candidate.briefing.channels.every(function (row) {
        return row && typeof row === "object" && !Array.isArray(row);
      })
    )) return false;
    if (candidate.sourceStatus !== undefined && (
      !Array.isArray(candidate.sourceStatus) || !candidate.sourceStatus.every(function (row) {
        return row && typeof row === "object" && !Array.isArray(row);
      })
    )) return false;
    return true;
  }

  function captureBriefingViewState() {
    var details = briefingMoreDetails();
    var openCardIds = new Set();
    var cards = typeof document.querySelectorAll === "function"
      ? document.querySelectorAll("[data-briefing-id]") : [];
    Array.from(cards || []).forEach(function (card) {
      var cardDetails = typeof card.querySelector === "function"
        ? card.querySelector(".briefing-card-details") : null;
      if (cardDetails && cardDetails.open && card.dataset && card.dataset.briefingId) {
        openCardIds.add(String(card.dataset.briefingId));
      }
    });
    var active = document.activeElement;
    var activeCard = active && typeof active.closest === "function"
      ? active.closest("[data-briefing-id]") : null;
    return {
      moreOpen: Boolean(details && details.open),
      openCardIds: openCardIds,
      focusedCardId: activeCard && activeCard.dataset
        ? String(activeCard.dataset.briefingId || "") : "",
    };
  }

  function restoreBriefingViewState(viewState) {
    var saved = viewState || {};
    var details = briefingMoreDetails();
    if (details && saved.moreOpen && !details.hidden) details.open = true;
    var focusTarget = null;
    var cards = typeof document.querySelectorAll === "function"
      ? document.querySelectorAll("[data-briefing-id]") : [];
    Array.from(cards || []).forEach(function (card) {
      var itemId = String((card.dataset && card.dataset.briefingId) || "");
      var cardDetails = typeof card.querySelector === "function"
        ? card.querySelector(".briefing-card-details") : null;
      if (cardDetails && saved.openCardIds && saved.openCardIds.has(itemId)) {
        cardDetails.open = true;
      }
      if (itemId && itemId === saved.focusedCardId && cardDetails) {
        focusTarget = typeof cardDetails.querySelector === "function"
          ? cardDetails.querySelector("summary") : null;
      }
    });
    if (focusTarget && typeof focusTarget.focus === "function") focusTarget.focus();
  }

  function renderUpdatedLiveSnapshot(viewState) {
    var savedViewState = viewState || captureBriefingViewState();
    renderMarketSummary();
    renderPremarketBriefing();
    var analysis = state.data && state.data.market ? state.data.market.sakakibaraAnalysis || {} : {};
    renderKioxiaLiveOverlay(analysis.kioxiaCase || {});
    renderOverseasIntelligence();
    renderLiveBriefing();
    restoreBriefingViewState(savedViewState);
    var details = briefingMoreDetails();
    if (details && details.open && !details.hidden) {
      var filter = currentBriefingFilter();
      var sort = currentBriefingSort();
      updateBriefingVisibleState(filter, briefingItemsForFilter(filter, sort).length, sort);
    }
    refreshRenderedBriefingFreshness();
    if (window.lucide) window.lucide.createIcons();
  }

  async function refreshLiveSnapshot() {
    if (fullDataLoadInFlight || liveSnapshotRefreshInFlight) return false;
    liveSnapshotRefreshInFlight = true;
    try {
      var response = await fetch("data/live-intelligence.json?ts=" + Date.now(), {
        cache: "no-store",
        headers: { "Accept": "application/json" },
      });
      if (!response.ok) return false;
      var candidate = await response.json();
      if (!liveSnapshotCandidateIsValid(candidate)) return false;
      var candidateTime = liveSnapshotGeneratedTime(candidate);
      var currentTime = liveSnapshotGeneratedTime(state.liveIntelligence);
      if (candidateTime === null || (currentTime !== null && candidateTime <= currentTime)) return false;
      var previousLiveIntelligence = state.liveIntelligence;
      var viewState = captureBriefingViewState();
      state.liveIntelligence = candidate;
      try {
        renderUpdatedLiveSnapshot(viewState);
      } catch (_renderError) {
        state.liveIntelligence = previousLiveIntelligence;
        try {
          renderUpdatedLiveSnapshot(viewState);
        } catch (_rollbackError) {
          // Keep the last valid state even if the current DOM cannot be redrawn.
        }
        return false;
      }
      if (typeof window.CustomEvent === "function" && typeof window.dispatchEvent === "function") {
        window.dispatchEvent(new CustomEvent("monitor:live-intelligence-updated", {
          detail: { generatedAtUtc: candidate.generatedAtUtc },
        }));
      }
      return true;
    } catch (_error) {
      return false;
    } finally {
      liveSnapshotRefreshInFlight = false;
    }
  }

  function setupLiveSnapshotRefresh() {
    var refreshWhenVisible = function () {
      if (typeof document.hidden === "boolean" && document.hidden) return;
      return refreshLiveSnapshot();
    };
    var timer = setInterval(refreshWhenVisible, LIVE_SNAPSHOT_REFRESH_INTERVAL_MS);
    if (timer && typeof timer.unref === "function") timer.unref();
    if (typeof window.addEventListener === "function") window.addEventListener("focus", refreshWhenVisible);
    if (typeof document.addEventListener === "function") {
      document.addEventListener("visibilitychange", refreshWhenVisible);
    }
  }


  async function loadData(showMessage) {
    fullDataLoadInFlight = true;
    var button = byId("refreshButton");
    button.classList.add("is-loading");
    button.disabled = true;
    if (showMessage) {
      byId("dataHealth").className = "status-dot";
      byId("dataHealth").textContent = "再読込中";
    }
    var refreshMode = "initial";
    var refreshWarning = "";
    try {
      if (showMessage) {
        byId("dataHealth").textContent = "市場・先物・為替・海外情報を更新中";
        byId("refreshHint").textContent = "取引中価格・先物・公式IR・海外情報を再読込しています";
        try {
          var refreshResult = await requestFreshUpdate();
          refreshMode = refreshResult.executed ? "live" : "static";
        } catch (refreshError) {
          refreshMode = "failed";
          refreshWarning = refreshError.message;
        }
      }
      var moneyRequest = fetch("data/money-strategist-history.json?ts=" + Date.now(), { cache: "no-store" })
        .then(function (response) { return response.ok ? response.json() : null; })
        .catch(function () { return null; });
      var marginDebtRequest = fetch("data/margin-debt-history.json?ts=" + Date.now(), { cache: "no-store" })
        .then(function (marginResponse) { return marginResponse.ok ? marginResponse.json() : null; })
        .catch(function () { return null; });
      var globalComparisonRequest = fetch("data/global-market-value-comparison.json?ts=" + Date.now(), { cache: "no-store" })
        .then(function (globalResponse) { return globalResponse.ok ? globalResponse.json() : null; })
        .catch(function () { return null; });
      var snapshotIndexRequest = fetch("data/history/index.json?ts=" + Date.now(), { cache: "no-store" })
        .then(function (historyResponse) { return historyResponse.ok ? historyResponse.json() : null; })
        .catch(function () { return null; });
      var marketSummaryRequest = fetch("data/market-summary.json?ts=" + Date.now(), { cache: "no-store" })
        .then(function (summaryResponse) { return summaryResponse.ok ? summaryResponse.json() : null; })
        .catch(function () { return null; });
      var liveIntelligenceRequest = fetch("data/live-intelligence.json?ts=" + Date.now(), { cache: "no-store" })
        .then(function (liveResponse) { return liveResponse.ok ? liveResponse.json() : null; })
        .catch(function () { return null; });
      var nikkeiAiThreeSeriesRequest = fetch("data/nikkei-ai-three-series.json?ts=" + Date.now(), { cache: "no-store" })
        .then(function (nikkeiAiResponse) { return nikkeiAiResponse.ok ? nikkeiAiResponse.json() : null; })
        .catch(function () { return null; });
      var response = await fetch("data/latest.json?ts=" + Date.now(), { cache: "no-store" });
      if (!response.ok) throw new Error("HTTP " + response.status);
      var payload = await response.json();
      if (!payload.companies || !payload.market || Number(payload.schemaVersion) < 11) throw new Error("データ形式が古いか不正です");
      state.data = payload;
      state.moneyStrategist = await moneyRequest;
      state.marginDebt = await marginDebtRequest;
      state.globalComparison = await globalComparisonRequest;
      state.snapshotHistoryIndex = await snapshotIndexRequest;
      state.marketSummary = await marketSummaryRequest;
      state.liveIntelligence = await liveIntelligenceRequest;
      state.nikkeiAiThreeSeries = await nikkeiAiThreeSeriesRequest;
      state.snapshotComparisonPayload = null;
      state.snapshotComparisonDays = null;
      state.snapshotComparisonEntry = null;
      renderAll();
      if (typeof window.CustomEvent === "function" && typeof window.dispatchEvent === "function") window.dispatchEvent(new CustomEvent("monitor:data-updated"));
      if (showMessage && refreshMode === "live") {
        byId("refreshHint").textContent = "最新データへ更新しました";
      } else if (showMessage && refreshMode === "static") {
        byId("refreshHint").textContent = "公開済みの最新スナップショット（先物・為替・海外情報を含む）を再読込しました";
      } else if (showMessage && refreshMode === "failed") {
        byId("dataHealth").className = "status-dot warn";
        byId("dataHealth").textContent = "更新失敗・前回値を表示";
        byId("refreshHint").textContent = refreshWarning;
      }
    } catch (error) {
      byId("dataHealth").className = "status-dot error";
      byId("dataHealth").textContent = "読込失敗";
      byId("headlineConclusion").textContent = "最新データを読み込めませんでした。公開処理の状態またはネットワークを確認してください。";
      byId("uncertaintySummary").textContent = error.message;
    } finally {
      fullDataLoadInFlight = false;
      button.classList.remove("is-loading");
      button.disabled = false;
      if (window.lucide) window.lucide.createIcons();
    }
  }

  function setupSectionNavigation() {
    var currentLabel = byId("currentSectionLabel");
    if (!currentLabel) return;
    var links = Array.prototype.slice.call(document.querySelectorAll(".section-nav a[data-track]"));
    var sections = Array.prototype.slice.call(document.querySelectorAll("main > section[id]"));
    if (!links.length || !sections.length || typeof window.addEventListener !== "function") return;

    var sectionLabels = {
      "market-summary": "本日のマーケット",
      "beginner-guide": "本日のまとめ",
      "live-briefing": "速報・介入・市場の話題",
      "today": "今日の判定",
      "purchasing-power": "購買力で比較",
      "decision-path": "価値・過熱の判断手順",
      "global-comparison": "市場の過熱度",
      "us-japan-link": "米国から日本への波及",
      "sakakibara-method": "正常化とパニック",
      "money-strategist": "過去との類似点",
      "margin-leverage": "信用レバレッジ",
      "signals": "米国側の崩壊確認",
      "nikkei-bottom": "底値候補と反転",
      "valuation": "企業価値",
      "manual-inputs": "未取得データ",
      "history": "ITバブルからの教訓",
      "methodology": "計算根拠",
      "sources": "データの来歴",
    };
    var pending = false;

    function updateCurrentSection() {
      pending = false;
      var referenceY = (window.scrollY || document.documentElement.scrollTop || 0) + 110;
      var active = sections[0];
      sections.forEach(function (section) {
        if (section.offsetTop <= referenceY) active = section;
      });
      var id = active && active.id ? active.id : "market-summary";
      currentLabel.textContent = sectionLabels[id] || "ページ内を表示";
      links.forEach(function (link) {
        var tracked = String(link.dataset.track || "").split(",");
        var isCurrent = tracked.indexOf(id) >= 0;
        link.classList.toggle("is-current", isCurrent);
        link.setAttribute("aria-current", isCurrent ? "location" : "false");
      });
    }

    window.addEventListener("scroll", function () {
      if (pending) return;
      pending = true;
      window.requestAnimationFrame(updateCurrentSection);
    }, { passive: true });
    window.addEventListener("resize", updateCurrentSection);
    updateCurrentSection();
  }

  function monitorCopyText() {
    var root = document.body || (typeof document.querySelector === "function" ? document.querySelector("main") : null) || document.documentElement;
    var visibleText = root && (root.innerText || root.textContent) ? (root.innerText || root.textContent) : "";
    var fullText = root && root.textContent ? root.textContent : visibleText;
    var text = fullText.length > visibleText.length ? fullText : visibleText;
    var title = document.title || "AIバブル崩壊・日経平均底値モニター";
    return (title + "\nコピー時刻: " + new Intl.DateTimeFormat("ja-JP", {
      dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Tokyo",
    }).format(new Date()) + "\n\n" + String(text || ""))
      .replace(/\r/g, "")
      .replace(/[ \t]+\n/g, "\n")
      .replace(/\n{3,}/g, "\n\n")
      .replace(/[ \t]{2,}/g, " ")
      .trim();
  }

  async function copyMonitorText() {
    var status = byId("copyMonitorStatus");
    if (window.matchMedia && window.matchMedia("(max-width: 700px)").matches) {
      if (status) status.textContent = "この操作はPC版向けです。";
      return false;
    }
    var text = monitorCopyText();
    try {
      if (typeof navigator !== "undefined" && navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
        await navigator.clipboard.writeText(text);
      } else {
        var host = document.body || document.documentElement;
        if (!document.createElement || !host || typeof host.appendChild !== "function") throw new Error("clipboard unavailable");
        var area = document.createElement("textarea");
        area.value = text;
        area.setAttribute("readonly", "");
        area.style.position = "fixed";
        area.style.opacity = "0";
        host.appendChild(area);
        area.select();
        var copied = document.execCommand && document.execCommand("copy");
        host.removeChild(area);
        if (!copied) throw new Error("clipboard unavailable");
      }
      if (status) status.textContent = "ページ全体のテキストをコピーしました。NotebookLMなどへ貼り付けできます。";
      return true;
    } catch (_error) {
      if (status) status.textContent = "コピーできませんでした。PCのHTTPSページで再度お試しください。";
      return false;
    }
  }

  function bindEvents() {
    byId("refreshButton").addEventListener("click", function () { loadData(true); });
    var copyButton = byId("copyMonitorButton");
    if (copyButton) copyButton.addEventListener("click", copyMonitorText);
    document.querySelectorAll("input[name='briefing-topic']").forEach(function (radio) {
      radio.addEventListener("change", function () {
        if (this.checked) applyBriefingFilter(this.value || "all", currentBriefingSort());
      });
    });
    document.querySelectorAll("input[name='briefing-sort']").forEach(function (radio) {
      radio.addEventListener("change", function () {
        if (this.checked) applyBriefingFilter(currentBriefingFilter(), this.value || "latest");
      });
    });
    var briefingMore = briefingMoreDetails();
    if (briefingMore) {
      briefingMore.addEventListener("toggle", function () {
        var filter = currentBriefingFilter();
        var sort = currentBriefingSort();
        updateBriefingVisibleState(filter, briefingItemsForFilter(filter, sort).length, sort);
      });
    }
    document.querySelectorAll(".snapshot-compare-button").forEach(function (button) {
      button.addEventListener("click", function () {
        loadSnapshotComparison(Number(this.dataset.compareDays));
      });
    });
    document.querySelectorAll(".margin-range-button").forEach(function (button) {
      button.addEventListener("click", function () {
        state.marginDebtRange = this.dataset.marginRange || "all";
        renderMarginDebtRangeUi();
        renderMarginDebtChart();
      });
    });
    document.querySelectorAll(".ms-range-button").forEach(function (button) {
      button.addEventListener("click", function () {
        state.moneyStrategistRange = this.dataset.msRange || "all";
        renderMoneyStrategistRangeUi();
        renderMoneyStrategistCalendar();
        renderMoneyStrategistChart();
      });
    });
    var ipoAssumption = byId("msIpoAssumption");
    if (ipoAssumption) ipoAssumption.addEventListener("change", function () {
      state.moneyStrategistIpoDate = this.value || "";
      renderMoneyStrategistCalendar();
      renderMoneyStrategistChart();
    });
    var ipoClear = byId("msIpoClear");
    if (ipoClear) ipoClear.addEventListener("click", function () {
      state.moneyStrategistIpoDate = "";
      if (ipoAssumption) ipoAssumption.value = "";
      renderMoneyStrategistCalendar();
      renderMoneyStrategistChart();
    });
    document.querySelectorAll(".company-filter-button").forEach(function (button) {
      button.addEventListener("click", function () {
        if (!state.data) return;
        state.companyFilter = button.dataset.companyFilter || "all";
        var companies = visibleCompanies();
        if (!companies.some(function (company) { return company.ticker === state.selectedTicker; })) {
          state.selectedTicker = companies[0] ? companies[0].ticker : state.selectedTicker;
        }
        updateCompanyFilterUi();
        renderValuationChart();
        renderCompanyTable();
        setDefaultControls();
        renderCompanyDetail();
      });
    });
    byId("companySelect").addEventListener("change", function () {
      state.selectedTicker = this.value;
      var selected = currentCompany();
      if (selected && state.companyFilter !== "all" && companyCategory(selected) !== state.companyFilter) {
        state.companyFilter = companyCategory(selected);
        updateCompanyFilterUi();
        renderValuationChart();
        renderCompanyTable();
      }
      setDefaultControls();
      renderCompanyDetail();
    });
    ["baseGrowthInput", "discountInput", "terminalInput"].forEach(function (id) {
      byId(id).addEventListener("input", function () {
        updateOutputs();
        renderCompanyDetail();
      });
    });
    byId("resetAssumptions").addEventListener("click", function () {
      setDefaultControls();
      renderCompanyDetail();
    });
    document.querySelectorAll('input[name="nikkeiScenario"]').forEach(function (input) {
      input.addEventListener("change", function () {
        if (this.checked) applyNikkeiPreset(this.value);
      });
    });
    ["nikkeiReferencePrice", "nikkeiCurrentPe", "nikkeiCurrentPb", "nikkeiEpsCut", "nikkeiTargetPe", "nikkeiTargetPb", "nikkeiHistoricalDrawdown"].forEach(function (id) {
      byId(id).addEventListener("input", function () {
        readNikkeiControls();
        if (state.data) renderNikkeiBottom();
      });
    });
    byId("resetNikkeiAssumptions").addEventListener("click", function () {
      var reference = state.data ? state.data.market.nikkeiValuationReference || {} : {};
      var preset = NIKKEI_PRESETS.standard;
      state.nikkeiBottom = {
        scenario: "standard",
        referencePrice: finite(reference.price),
        currentPe: finite(reference.indexPe),
        currentPb: finite(reference.indexPb),
        epsCut: preset.epsCut,
        targetPe: preset.targetPe,
        targetPb: preset.targetPb,
        historyDrawdown: preset.historyDrawdown,
      };
      saveNikkeiBottom();
      syncNikkeiControls();
      if (state.data) renderNikkeiBottom();
    });
    byId("manualForm").addEventListener("submit", function (event) {
      event.preventDefault();
      state.manual = {
        epsCut: boundedInput("manualEpsCut", 0, 100),
        epsCompanies: boundedInput("manualEpsCompanies", 0, 10),
        priceDrop: boundedInput("manualPriceDrop", 0, 100),
        cancellations: boundedInput("manualCancellations", 0, 50),
        inventoryGap: boundedInput("manualInventoryGap", -100, 200),
      };
      saveManual();
      if (state.data) renderAll();
      byId("manualMessage").textContent = "確認済みの入力値を保存し、再判定しました。";
    });
    byId("clearManual").addEventListener("click", function () {
      state.manual = { epsCut: null, epsCompanies: null, priceDrop: null, cancellations: null, inventoryGap: null };
      saveManual();
      setManualInputs();
      if (state.data) renderAll();
      byId("manualMessage").textContent = "すべて未確認へ戻しました。";
    });
  }

  setManualInputs();
  bindEvents();
  setupSectionNavigation();
  if (window.lucide) window.lucide.createIcons();
  loadData(false);
  setupLiveSnapshotRefresh();
  var briefingFreshnessTimer = setInterval(refreshRenderedBriefingFreshness, 60000);
  if (briefingFreshnessTimer && typeof briefingFreshnessTimer.unref === "function") {
    briefingFreshnessTimer.unref();
  }
}());
