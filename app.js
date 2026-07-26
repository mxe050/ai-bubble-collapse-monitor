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
    moneyStrategistRange: "all",
    marginDebtChart: null,
    marginDebt: null,
    marginDebtRange: "all",
    purchasingPowerChart: null,
    snapshotHistoryIndex: null,
    snapshotComparisonDays: null,
    snapshotComparisonPayload: null,
    globalComparison: null,
    moneyStrategistIpoDate: "",
    valuations: [],
    companyFilter: "all",
    nikkeiBottom: loadNikkeiBottom(),
    nikkeiBottomInitialized: false,
    sakakibaraFairValue: loadSakakibaraFairValue(),
    sakakibaraInitialized: false,
  };

  var numberOne = new Intl.NumberFormat("ja-JP", { maximumFractionDigits: 1 });
  var numberTwo = new Intl.NumberFormat("ja-JP", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  var numberThree = new Intl.NumberFormat("ja-JP", { minimumFractionDigits: 3, maximumFractionDigits: 3 });
  var numberFour = new Intl.NumberFormat("ja-JP", { minimumFractionDigits: 4, maximumFractionDigits: 4 });
  var nikkeiFormat = new Intl.NumberFormat("ja-JP", { maximumFractionDigits: 0 });
  var moneyFormatters = {};
  var priceFormatters = {};

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
      button.setAttribute("aria-selected", active ? "true" : "false");
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
      ? "分散型8社の中央値はAI連動8社を、5日で" + formatPctPoints(analysis.basketAdvantage5dPctPoints, false) + "、20日で" + formatPctPoints(analysis.basketAdvantage20dPctPoints, false) + "上回りました。榊原先生のいうEN-AI側への相対回復と整合する価格差です。"
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

    renderNtRatioChart(analysis);
    renderSakakibaraFairValue(analysis);
    renderSakakibaraMarketPath(analysis);
    renderEnAiProxy(analysis);
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
      + "<div><span>02</span><p><strong>非ITは下落が小さい傾向でも無傷ではない</strong>非IT4社の最大下落中央値は" + formatDrawdown(nonTech.medianMaxDrawdownPct) + "。トヨタは最大" + formatDrawdown(toyota.maxDrawdownPct) + "、ソニーは技術感応型として" + formatDrawdown(sony.maxDrawdownPct) + "でした。</p></div>"
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
      cycle: { min: 2026.50, max: 2028.88 },
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
              maxTicksLimit: state.moneyStrategistRange === "cycle" ? 12 : state.moneyStrategistRange === "current" ? 10 : 14,
              callback: function (value) { return Math.round(value); },
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
    byId("berkshireNetSellingTimeline").innerHTML = periods.map(function (period) {
      return "<li><span>" + escapeHtml(period.label || "") + "</span><strong>純売却 "
        + escapeHtml(formatUsdBillions(period.netSalesBillion)) + "</strong><small>"
        + escapeHtml(period.detail || "") + "</small></li>";
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
    byId("overseasSummary").textContent = intelligence.summary || "海外情報の更新結果がありません。";
    var checked = intelligence.checkedAtUtc ? new Date(intelligence.checkedAtUtc) : null;
    byId("overseasCheckedAt").textContent = checked && !Number.isNaN(checked.valueOf())
      ? "確認 " + new Intl.DateTimeFormat("ja-JP", { dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Tokyo" }).format(checked)
      : "確認時刻なし";
    byId("overseasXStatus").textContent = xWatch.message || "Xの状態を確認できません";
    var topics = Object.entries(intelligence.topicCounts || {}).sort(function (a, b) { return b[1] - a[1]; });
    byId("overseasTopicChips").innerHTML = topics.map(function (row) {
      return "<span>" + escapeHtml(row[0]) + " <strong>" + nikkeiFormat.format(row[1]) + "</strong></span>";
    }).join("");
    var items = (intelligence.newsItems || []).slice(0, 8).concat((xWatch.items || []).slice(0, 4));
    byId("overseasNewsList").innerHTML = items.map(function (row) {
      return "<a href=\"" + escapeHtml(row.url) + "\" target=\"_blank\" rel=\"noopener\"><span>" + escapeHtml(row.evidenceLevel || "海外情報") + "</span><strong>" + escapeHtml(row.title) + "</strong><small>" + escapeHtml(row.source || "") + " / " + escapeHtml(row.topic || "") + "</small></a>";
    }).join("") || "<p>今回の更新では新着候補を取得できませんでした。</p>";
    byId("overseasReadingRule").textContent = intelligence.readingRule || "";
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

  function snapshotEntryForDays(days) {
    var entries = ((state.snapshotHistoryIndex || {}).snapshots || []).slice();
    var currentStamp = state.data && (state.data.generatedAtJst || state.data.generatedAtUtc);
    var currentDate = currentStamp ? new Date(currentStamp) : null;
    if (!currentDate || Number.isNaN(currentDate.valueOf())) return null;
    var target = new Date(currentDate.valueOf());
    target.setDate(target.getDate() - days);
    var targetKey = target.toLocaleDateString("sv-SE", { timeZone: "Asia/Tokyo" });
    return entries
      .filter(function (entry) { return entry.snapshotDate && entry.snapshotDate <= targetKey; })
      .sort(function (a, b) { return b.snapshotDate.localeCompare(a.snapshotDate); })[0] || null;
  }

  function updateSnapshotComparisonButtons() {
    var entries = ((state.snapshotHistoryIndex || {}).snapshots || []);
    document.querySelectorAll(".snapshot-compare-button").forEach(function (button) {
      var days = Number(button.dataset.compareDays);
      var available = Boolean(snapshotEntryForDays(days));
      button.disabled = !available;
      button.classList.toggle("is-active", state.snapshotComparisonDays === days);
      button.setAttribute("aria-pressed", state.snapshotComparisonDays === days ? "true" : "false");
      if (!available) button.title = "この時点の保存データはまだありません";
      else button.title = "";
    });
    if (!entries.length) {
      byId("snapshotAvailability").textContent = "履歴保存は今回から開始します。過去値は推測せず、保存された日だけ比較します。";
      return;
    }
    var oldest = entries.slice().sort(function (a, b) { return a.snapshotDate.localeCompare(b.snapshotDate); })[0];
    byId("snapshotAvailability").textContent = "保存開始 " + oldest.snapshotDate + "。休場・未更新日は対象日以前の最寄り保存日を使います。";
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
    var previousDate = String(previousPayload.generatedAtJst || previousPayload.generatedAtUtc || "").slice(0, 10);
    var currentDate = String(state.data.generatedAtJst || state.data.generatedAtUtc || "").slice(0, 10);
    byId("snapshotComparisonHeading").textContent = (labels[days] || "過去") + "の保存状態との比較";
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

  function renderAll() {
    state.valuations = state.data.companies.map(function (company) { return modelCompany(company); });
    var evidence = scoreEvidence();
    var gates = assessGates(evidence);
    var bubble = assessBubble(evidence);
    var transmission = assessJapanTransmission();
    renderMetadata();
    renderTop(evidence, gates, bubble);
    renderSignals(evidence);
    renderGates(gates);
    renderJapanTransmission(transmission);
    renderSakakibaraMethod();
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


  async function loadData(showMessage) {
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
        byId("dataHealth").textContent = "市場・企業・海外情報を更新中";
        byId("refreshHint").textContent = "取得、再計算、検証を実行しています";
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
      var response = await fetch("data/latest.json?ts=" + Date.now(), { cache: "no-store" });
      if (!response.ok) throw new Error("HTTP " + response.status);
      var payload = await response.json();
      if (!payload.companies || !payload.market || Number(payload.schemaVersion) < 11) throw new Error("データ形式が古いか不正です");
      state.data = payload;
      state.moneyStrategist = await moneyRequest;
      state.marginDebt = await marginDebtRequest;
      state.globalComparison = await globalComparisonRequest;
      state.snapshotHistoryIndex = await snapshotIndexRequest;
      state.snapshotComparisonPayload = null;
      state.snapshotComparisonDays = null;
      renderAll();
      if (typeof window.CustomEvent === "function" && typeof window.dispatchEvent === "function") window.dispatchEvent(new CustomEvent("monitor:data-updated"));
      if (showMessage && refreshMode === "live") {
        byId("refreshHint").textContent = "最新データへ更新しました";
      } else if (showMessage && refreshMode === "static") {
        byId("refreshHint").textContent = "公開済みの最新データを再読込しました";
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
      "beginner-guide": "案内・用語",
      "today": "今日の判定",
      "purchasing-power": "購買力で比較",
      "decision-path": "判断の全体像",
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
      var id = active && active.id ? active.id : "beginner-guide";
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

  function bindEvents() {
    byId("refreshButton").addEventListener("click", function () { loadData(true); });
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
}());
