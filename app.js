(function () {
  "use strict";

  var state = {
    data: null,
    manual: loadManual(),
    selectedTicker: "NVDA",
    marketChart: null,
    valuationChart: null,
    valuations: [],
  };

  var moneyCompact = new Intl.NumberFormat("ja-JP", {
    notation: "compact",
    maximumFractionDigits: 2,
    style: "currency",
    currency: "USD",
  });
  var numberOne = new Intl.NumberFormat("ja-JP", { maximumFractionDigits: 1 });
  var priceFormat = new Intl.NumberFormat("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
    style: "currency",
    currency: "USD",
  });

  function byId(id) {
    return document.getElementById(id);
  }

  function finite(value) {
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

  function formatMoney(value) {
    if (value === null || value === undefined || !Number.isFinite(Number(value))) return "未確認";
    return moneyCompact.format(Number(value));
  }

  function formatPrice(value) {
    if (value === null || value === undefined || !Number.isFinite(Number(value))) return "算定不可";
    return priceFormat.format(Number(value));
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

  function inputOrNull(id) {
    var raw = byId(id).value.trim();
    return raw === "" ? null : finite(raw);
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

  function reverseDcfGrowth(company, discountPct, terminalPct, years) {
    var market = finite(company.marketCap);
    var fcf = finite(company.ttmFreeCashFlow);
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
    var fcf = finite(company.ttmFreeCashFlow);
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
    var valuationPremium = median(state.valuations.map(function (item) { return item.premiumPct; }));
    var impliedGap = median(state.valuations.map(function (item) { return item.impliedGapPct; }));

    var price = combineSignal(
      "price", "価格レジーム", "一日の急落ではなく、下落の深さ・持続・広がりを確認します。",
      "SOX下落 " + formatPercent(sox.drawdown3yPct, false) + "、200日線下 " + (finite(sox.weeksBelowSma200) === null ? "未確認" : numberOne.format(sox.weeksBelowSma200) + "週") + "、200日線割れ銘柄 " + formatPercent(basket.breadthBelowSma200Pct, false),
      [
        component(sox.drawdown3yPct, 16, stepScore(sox.drawdown3yPct, [[40, 16], [35, 14], [30, 11], [20, 7], [10, 3]])),
        component(sox.weeksBelowSma200, 7, stepScore(sox.weeksBelowSma200, [[8, 7], [6, 6], [4, 4], [1, 2]])),
        component(basket.medianDrawdown3yPct, 4, stepScore(basket.medianDrawdown3yPct, [[45, 4], [30, 3], [20, 2], [10, 1]])),
        component(basket.breadthBelowSma200Pct, 3, stepScore(basket.breadthBelowSma200Pct, [[80, 3], [60, 2], [40, 1]])),
      ], 30
    );

    var valuation = combineSignal(
      "valuation", "企業価値の脆弱性", "市場価格が基準DCFをどれだけ上回り、どれほど高いFCF成長を要求するかを測ります。",
      "モデル超過分の中央値 " + formatPercent(valuationPremium, false) + "、暗黙成長と基準成長の差 " + formatPercent(impliedGap, true),
      [
        component(valuationPremium, 12, stepScore(valuationPremium, [[45, 12], [30, 10], [20, 7], [10, 4], [0, 1]])),
        component(impliedGap, 8, stepScore(impliedGap, [[12, 8], [8, 6], [5, 4], [2, 2]])),
      ], 20
    );

    var epsEvidence = state.manual.epsCut;
    var epsScore = epsEvidence === null ? null : stepScore(epsEvidence, [[20, 7], [15, 6], [10, 4], [5, 2]]);
    if (epsScore !== null && state.manual.epsCompanies !== null && state.manual.epsCompanies >= 4) epsScore = Math.min(7, epsScore + 1);
    var fundamentals = combineSignal(
      "fundamentals", "基礎収益・投資", "売上とFCFが悪化し、顧客企業が設備投資を減らしたかを確認します。",
      "売上成長中央値 " + formatPercent(derived.medianRevenueGrowthYoYPct, true) + "、FCF成長中央値 " + formatPercent(derived.medianFreeCashFlowGrowthYoYPct, true) + "、CapEx大幅削減 " + (derived.hyperscalersWithCapexCuts === null || derived.hyperscalersWithCapexCuts === undefined ? "未確認" : derived.hyperscalersWithCapexCuts + "社") + "、EPS修正 " + formatPercent(state.manual.epsCut === null ? null : -state.manual.epsCut, true),
      [
        component(derived.medianRevenueGrowthYoYPct, 7, reverseStepScore(derived.medianRevenueGrowthYoYPct, [[-10, 7], [0, 5], [5, 2]])),
        component(derived.medianFreeCashFlowGrowthYoYPct, 6, reverseStepScore(derived.medianFreeCashFlowGrowthYoYPct, [[-20, 6], [0, 4], [10, 2]])),
        component(derived.hyperscalersWithCapexCuts, 5, stepScore(derived.hyperscalersWithCapexCuts, [[2, 5], [1, 3]])),
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
      "credit", "信用・資金調達", "AI投資の失敗が、社債や資金調達条件へ波及したかを確認します。",
      "HY OAS " + (oasValue === null ? "未確認" : numberOne.format(oasValue * 100) + "bp") + "、3か月低値から " + (oasRise === null ? "未確認" : "+" + numberOne.format(oasRise * 100) + "bp"),
      [
        component(oasValue, 7, stepScore(oasValue, [[6, 7], [5, 6], [4, 3], [3.5, 1]])),
        component(oasRise, 3, stepScore(oasRise, [[2, 3], [1, 2], [0.5, 1]])),
      ], 10
    );

    var signals = [price, valuation, fundamentals, capitalCycle, credit];
    var observed = signals.reduce(function (sum, signal) { return sum + signal.observed; }, 0);
    var known = signals.reduce(function (sum, signal) { return sum + signal.known; }, 0);
    var unknown = signals.reduce(function (sum, signal) { return sum + signal.unknown; }, 0);
    return {
      signals: signals,
      observed: Math.round(observed),
      known: known,
      unknown: unknown,
      coverage: Math.round(known),
      maxPossible: Math.round(observed + unknown),
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

    var fcfGrowth = finite(data.derived.medianFreeCashFlowGrowthYoYPct);
    var capexCuts = finite(data.derived.hyperscalersWithCapexCuts);
    var epsKnown = state.manual.epsCut !== null;
    var fundamentalTrue = (epsKnown && state.manual.epsCut >= 15) || (fcfGrowth !== null && fcfGrowth <= -15) || (capexCuts !== null && capexCuts >= 2);
    var gateB = triState(fundamentalTrue, epsKnown && fcfGrowth !== null && capexCuts !== null);

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
    if (gateA === "true" && gateB === "true" && gateC === "true" && evidence.observed >= 65) {
      collapseName = "バブル崩壊を確認";
      collapseReason = "価格・利益・実体波及の3ゲートがそろい、観測証拠も65点以上です。";
    } else if (gateA === "true" && (gateB === "true" || gateC === "true")) {
      collapseName = "崩壊進行の可能性";
      collapseReason = "価格レジーム転換に、利益または実体波及の悪化が重なっています。";
    } else if ((finite(sox.drawdown3yPct) !== null && sox.drawdown3yPct >= 20) || evidence.observed >= 25) {
      collapseName = "調整・再評価局面";
      collapseReason = "価格または複数指標に警戒信号がありますが、3ゲートはそろっていません。";
    } else {
      collapseName = "崩壊は未確認";
      collapseReason = "高評価の可能性はあっても、価格・利益・波及の連鎖はまだ確認できません。";
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
      return { name: "バブル・プレミアム大", reason: "基準DCFを大きく上回り、市場は基準より高いFCF成長を要求しています。" };
    }
    if ((premium !== null && premium >= 10) || (gap !== null && gap >= 2)) {
      return { name: "割高リスクあり", reason: "実体ある利益に加え、長い競争優位と高成長の継続が価格に含まれています。" };
    }
    return { name: "基準シナリオ内", reason: "本モデルでは、現在のFCFと基準成長で価格の多くを説明できます。" };
  }

  function renderTop(evidence, gates, bubble) {
    byId("bubbleRegime").textContent = bubble.name;
    byId("bubbleReason").textContent = bubble.reason;
    byId("collapseRegime").textContent = gates.collapseName;
    byId("collapseReason").textContent = gates.collapseReason;
    byId("evidenceScore").textContent = evidence.observed;
    byId("coverageValue").textContent = evidence.coverage;
    byId("scoreRange").textContent = evidence.unknown
      ? "未確認項目をすべて悪化と仮定した上限 " + evidence.maxPossible + "点"
      : "主要項目を確認済み";
    byId("coverageReason").textContent = evidence.unknown
      ? "残り" + evidence.unknown + "点分は未確認"
      : "欠損なし";

    var plain;
    if (gates.collapseName === "バブル崩壊を確認") {
      plain = "割高の修正だけでなく、将来利益と実体・信用への波及を伴う崩壊条件がそろっています。";
    } else if (bubble.name === "バブル・プレミアム大") {
      plain = "価格には強い期待が含まれていますが、現在のところ『高い』ことと『崩壊した』ことは同じではありません。";
    } else {
      plain = "一部の株価下落だけでは崩壊とは言えません。企業のFCFと設備投資、信用市場の変化を同時に追う段階です。";
    }
    byId("headlineConclusion").textContent = plain;
    byId("uncertaintySummary").textContent = evidence.unknown
      ? "特に予想EPS、製品価格、在庫、正式な計画中止が未確認です。これらを入力すると判定範囲が狭まります。"
      : "主要入力が確認されているため、判定の欠損による幅はありません。ただしモデル不確実性は残ります。";
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
      "SOXは3年高値から" + formatPercent(sox.drawdown3yPct, false) + "。崩壊ゲートの35%には" + (sox.drawdown3yPct >= 35 ? "達しています。" : "達していません。"),
      "SOXが200日線を下回った期間は約" + (finite(sox.weeksBelowSma200) === null ? "未確認" : numberOne.format(sox.weeksBelowSma200) + "週") + "。一時的な下落か、長期トレンド転換かを区別します。",
      "主要AI株のうち200日線を下回る割合は" + formatPercent(basket.breadthBelowSma200Pct, false) + "。指数だけでなく下落の広がりを示します。",
      "直近1日の主要AI株中央値は" + formatPercent(basket.medianChange1dPct, true) + "。短期変化は警報として使いますが、単独で崩壊判定には使いません。",
    ];
    byId("marketReading").innerHTML = items.map(function (item) { return "<li>" + escapeHtml(item) + "</li>"; }).join("");
  }

  function chartTextColor() {
    return getComputedStyle(document.documentElement).getPropertyValue("--muted").trim() || "#647386";
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
          { label: "SOX", data: rows.map(function (row) { return row.sox; }), borderColor: "#126b9a", backgroundColor: "transparent", borderWidth: 2.5, pointRadius: 0, tension: 0.08 },
          { label: "主要AI株 等ウェイト", data: rows.map(function (row) { return row.aiBasket; }), borderColor: "#c94b18", backgroundColor: "transparent", borderWidth: 2.5, pointRadius: 0, tension: 0.08 },
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
    var usable = state.valuations.filter(function (item) { return item.market && item.baseValue !== null && item.existingValue !== null; });
    if (!usable.length) return;
    var decomposition = usable.map(function (item) {
      var existing = clamp(item.existingValue / item.market * 100, 0, 100);
      var base = clamp(item.baseValue / item.market * 100, 0, 100);
      var growth = Math.max(0, base - existing);
      var premium = Math.max(0, 100 - Math.max(existing, base));
      return { existing: existing, growth: growth, premium: premium };
    });
    if (state.valuationChart) state.valuationChart.destroy();
    state.valuationChart = new Chart(byId("valuationChart"), {
      type: "bar",
      data: {
        labels: usable.map(function (item) { return item.ticker; }),
        datasets: [
          { label: "既存利益の価値", data: decomposition.map(function (row) { return row.existing; }), backgroundColor: "#173854" },
          { label: "合理的な成長価値", data: decomposition.map(function (row) { return row.growth; }), backgroundColor: "#087f75" },
          { label: "モデル超過分", data: decomposition.map(function (row) { return row.premium; }), backgroundColor: "#c94b18" },
        ],
      },
      options: {
        indexAxis: "y",
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { position: "bottom", labels: { color: chartTextColor(), boxWidth: 15 } }, tooltip: { callbacks: { label: function (context) { return context.dataset.label + " " + numberOne.format(context.parsed.x) + "%"; } } } },
        scales: {
          x: { stacked: true, max: 100, grid: { color: "rgba(100,115,134,.15)" }, ticks: { color: chartTextColor(), callback: function (value) { return value + "%"; } } },
          y: { stacked: true, grid: { display: false }, ticks: { color: chartTextColor(), font: { weight: "bold" } } },
        },
      },
    });
  }

  function renderCompanyTable() {
    var lookup = Object.fromEntries(state.valuations.map(function (item) { return [item.ticker, item]; }));
    byId("companyRows").innerHTML = state.data.companies.map(function (company) {
      var model = lookup[company.ticker];
      var baseGap = model ? model.baseGapPct : null;
      var implied = model ? model.impliedGrowthPct : null;
      return "<tr>"
        + "<td><strong class=\"company-name\">" + escapeHtml(company.name) + "</strong><span class=\"company-group\">" + escapeHtml(company.ticker + " / " + company.group) + "</span></td>"
        + "<td>" + formatPrice(company.price) + "<br><span class=\"" + cssValueClass(company.change1dPct, false) + "\">" + formatPercent(company.change1dPct, true) + "</span></td>"
        + "<td class=\"" + cssValueClass(company.drawdown3yPct, true) + "\">−" + formatPercent(company.drawdown3yPct, false) + "</td>"
        + "<td class=\"" + cssValueClass(company.revenueGrowthYoYPct, false) + "\">" + formatPercent(company.revenueGrowthYoYPct, true) + "</td>"
        + "<td>" + formatMoney(company.ttmFreeCashFlow) + "<br><span class=\"neutral\">利回り " + formatPercent(company.freeCashFlowYieldPct, false) + "</span></td>"
        + "<td class=\"" + (implied !== null && implied > company.assumptions.baseGrowthPct + 5 ? "negative" : "neutral") + "\">" + formatPercent(implied, false) + "</td>"
        + "<td class=\"" + cssValueClass(baseGap, false) + "\">" + formatPercent(baseGap, true) + "</td>"
        + "<td><button type=\"button\" class=\"icon-button detail-button\" data-ticker=\"" + escapeHtml(company.ticker) + "\" title=\"" + escapeHtml(company.name) + "の前提と感度を表示\"><i data-lucide=\"panel-right-open\" aria-hidden=\"true\"></i></button></td>"
        + "</tr>";
    }).join("");

    byId("companySelect").innerHTML = state.data.companies.map(function (company) {
      return "<option value=\"" + escapeHtml(company.ticker) + "\">" + escapeHtml(company.ticker + " / " + company.name) + "</option>";
    }).join("");
    if (!lookup[state.selectedTicker]) state.selectedTicker = state.data.companies[0] ? state.data.companies[0].ticker : "";
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
    byId("detailCompanyName").textContent = company.name + "（" + company.ticker + "）";
    byId("detailCompanyContext").innerHTML = escapeHtml(company.group + "。財務基準日 " + (company.filingDate || "未確認") + "。")
      + " <a href=\"" + escapeHtml(company.irUrl) + "\" target=\"_blank\" rel=\"noopener\">企業IRで照合</a>";
    var stats = [
      ["時価総額", formatMoney(company.marketCap)],
      ["企業価値", formatMoney(company.enterpriseValue)],
      ["TTM売上", formatMoney(company.ttmRevenue)],
      ["営業利益率", formatPercent(company.operatingMarginPct, false)],
      ["TTM FCF", formatMoney(company.ttmFreeCashFlow)],
      ["FCF利回り", formatPercent(company.freeCashFlowYieldPct, false)],
    ];
    byId("fundamentalStrip").innerHTML = stats.map(function (row) {
      return "<div class=\"fundamental-stat\"><span>" + escapeHtml(row[0]) + "</span><strong>" + escapeHtml(row[1]) + "</strong></div>";
    }).join("");

    byId("bearValue").textContent = formatPrice(model.bearPrice);
    byId("bearDownside").textContent = gapText(model.bearGapPct);
    byId("baseValue").textContent = formatPrice(model.basePrice);
    byId("baseDownside").textContent = gapText(model.baseGapPct);
    byId("bullValue").textContent = formatPrice(model.bullPrice);
    byId("bullDownside").textContent = gapText(model.bullGapPct);
    byId("impliedGrowth").textContent = formatPercent(model.impliedGrowthPct, false);

    if (model.baseValue === null) {
      byId("scenarioExplanation").textContent = "FCFが正でない、または必要データが不足しているため、この方法では価値を算定できません。赤字企業を売上倍率だけで機械的に評価しないための制限です。";
    } else {
      var comparison = model.impliedGrowthPct === null ? "暗黙成長率は上限範囲内で解けませんでした。" : "現在価格は、FCFが今後10年間に年平均" + formatPercent(model.impliedGrowthPct, false) + "成長する前提に相当します。";
      var downside = model.baseGapPct < 0
        ? "基準前提では現在価格から約" + formatPercent(Math.abs(model.baseGapPct), false) + "下の水準です。"
        : "基準前提では現在価格を約" + formatPercent(model.baseGapPct, false) + "上回ります。";
      byId("scenarioExplanation").textContent = comparison + " " + downside + " 弱気値は底値保証ではなく、FCF・割引率・競争条件を置いた場合の計算結果です。";
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
        var value = dcfValue(company.ttmFreeCashFlow, growth, discount, model.terminalPct, model.years);
        var price = value !== null && company.marketCap && company.price ? value / company.marketCap * company.price : null;
        var near = price !== null && Math.abs(price / company.price - 1) <= 0.1;
        html += "<td class=\"" + (near ? "near-market" : "") + "\">" + formatPrice(price) + "</td>";
      });
      html += "</tr>";
    });
    html += "</tbody>";
    byId("sensitivityTable").innerHTML = html;
  }

  function renderSources() {
    var grouped = {};
    (state.data.sourceStatus || []).forEach(function (source) {
      var key = source.name;
      if (!grouped[key]) grouped[key] = { name: key, url: source.url, ok: 0, failed: 0, notes: [] };
      if (source.ok) grouped[key].ok += 1;
      else {
        grouped[key].failed += 1;
        if (source.note) grouped[key].notes.push(source.note);
      }
    });
    byId("sourceStatusList").innerHTML = Object.values(grouped).map(function (group) {
      var failed = group.failed > 0;
      var summary = group.ok + "件成功" + (failed ? " / " + group.failed + "件失敗" : "");
      var note = failed ? group.notes.slice(0, 2).join(" / ") : "取得済み";
      return "<a class=\"source-item " + (failed ? "failed" : "") + "\" href=\"" + escapeHtml(group.url) + "\" target=\"_blank\" rel=\"noopener\">"
        + "<span aria-hidden=\"true\"></span><div><p><strong>" + escapeHtml(group.name) + "</strong>：" + escapeHtml(summary) + "</p><small>" + escapeHtml(note) + "</small></div></a>";
    }).join("");
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

  function renderAll() {
    state.valuations = state.data.companies.map(function (company) { return modelCompany(company); });
    var evidence = scoreEvidence();
    var gates = assessGates(evidence);
    var bubble = assessBubble(evidence);
    renderMetadata();
    renderTop(evidence, gates, bubble);
    renderSignals(evidence);
    renderGates(gates);
    renderMarketReading();
    renderMarketChart();
    renderValuationChart();
    renderCompanyTable();
    setDefaultControls();
    renderCompanyDetail();
    renderSources();
    if (window.lucide) window.lucide.createIcons();
  }

  async function loadData(showMessage) {
    var button = byId("refreshButton");
    button.classList.add("is-loading");
    button.disabled = true;
    if (showMessage) {
      byId("dataHealth").className = "status-dot";
      byId("dataHealth").textContent = "再読込中";
    }
    try {
      var response = await fetch("data/latest.json?ts=" + Date.now(), { cache: "no-store" });
      if (!response.ok) throw new Error("HTTP " + response.status);
      var payload = await response.json();
      if (!payload.companies || !payload.market) throw new Error("データ形式が不正です");
      state.data = payload;
      renderAll();
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

  function bindEvents() {
    byId("refreshButton").addEventListener("click", function () { loadData(true); });
    byId("companySelect").addEventListener("change", function () {
      state.selectedTicker = this.value;
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
    byId("manualForm").addEventListener("submit", function (event) {
      event.preventDefault();
      state.manual = {
        epsCut: inputOrNull("manualEpsCut"),
        epsCompanies: inputOrNull("manualEpsCompanies"),
        priceDrop: inputOrNull("manualPriceDrop"),
        cancellations: inputOrNull("manualCancellations"),
        inventoryGap: inputOrNull("manualInventoryGap"),
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
  if (window.lucide) window.lucide.createIcons();
  loadData(false);
}());
