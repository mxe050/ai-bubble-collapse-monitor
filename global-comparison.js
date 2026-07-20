(function () {
  "use strict";

  var DATA_URL = "data/global-market-value-comparison.json";
  var state = {
    payload: null,
    chart: null,
    range: "all",
    normalization: "fixed",
    showSp500Nominal: true,
    showTheoreticalValueSeries: true,
    showCrises: true,
    legendVisible: {},
  };

  function byId(id) {
    return document.getElementById(id);
  }

  function finite(value) {
    if (value == null || value === "") return null;
    var number = Number(value);
    return Number.isFinite(number) ? number : null;
  }

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function formatDate(value) {
    if (!value) return "未取得";
    var date = new Date(String(value).slice(0, 10) + "T00:00:00Z");
    if (Number.isNaN(date.valueOf())) return String(value);
    return new Intl.DateTimeFormat("ja-JP", {
      year: "numeric", month: "long", timeZone: "UTC",
    }).format(date);
  }

  function formatTimestamp(value) {
    if (!value) return "未取得";
    var date = new Date(value);
    if (Number.isNaN(date.valueOf())) return String(value);
    return new Intl.DateTimeFormat("ja-JP", {
      dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Tokyo",
    }).format(date);
  }

  function formatNumber(value, digits) {
    var number = finite(value);
    if (number == null) return "欠損";
    return number.toLocaleString("ja-JP", {
      maximumFractionDigits: digits == null ? 2 : digits,
      minimumFractionDigits: 0,
    });
  }

  function decimalYear(value) {
    var parts = String(value).slice(0, 10).split("-").map(Number);
    if (!parts[0] || !parts[1]) return null;
    return parts[0] + (parts[1] - 1) / 12 + ((parts[2] || 1) - 1) / 365.25;
  }

  function dateFromDecimalYear(value) {
    var year = Math.floor(value);
    var month = Math.max(1, Math.min(12, Math.round((value - year) * 12) + 1));
    return year + "年" + month + "月";
  }

  function readUrlState() {
    var params = new URLSearchParams(window.location.search);
    state.showSp500Nominal = params.get("hideSp500Nominal") !== "true";
    state.showTheoreticalValueSeries = params.get("showTheoreticalValue") !== "false";
    state.showCrises = params.get("showComparisonCrises") !== "false";
    var range = params.get("comparisonRange");
    if (["all", "30", "20", "10", "5", "custom"].indexOf(range) >= 0) state.range = range;
    var normalization = params.get("comparisonNormalization");
    if (["fixed", "visible"].indexOf(normalization) >= 0) state.normalization = normalization;
    if (params.get("comparisonStart") && byId("gcCustomStart")) byId("gcCustomStart").value = params.get("comparisonStart");
    if (params.get("comparisonEnd") && byId("gcCustomEnd")) byId("gcCustomEnd").value = params.get("comparisonEnd");
  }

  function writeUrlState() {
    var url = new URL(window.location.href);
    if (state.showSp500Nominal) url.searchParams.delete("hideSp500Nominal");
    else url.searchParams.set("hideSp500Nominal", "true");
    if (state.showTheoreticalValueSeries) url.searchParams.delete("showTheoreticalValue");
    else url.searchParams.set("showTheoreticalValue", "false");
    if (state.showCrises) url.searchParams.delete("showComparisonCrises");
    else url.searchParams.set("showComparisonCrises", "false");
    if (state.range === "all") url.searchParams.delete("comparisonRange");
    else url.searchParams.set("comparisonRange", state.range);
    if (state.normalization === "fixed") url.searchParams.delete("comparisonNormalization");
    else url.searchParams.set("comparisonNormalization", state.normalization);
    if (state.range === "custom") {
      var start = byId("gcCustomStart").value;
      var end = byId("gcCustomEnd").value;
      if (start) url.searchParams.set("comparisonStart", start); else url.searchParams.delete("comparisonStart");
      if (end) url.searchParams.set("comparisonEnd", end); else url.searchParams.delete("comparisonEnd");
    } else {
      url.searchParams.delete("comparisonStart");
      url.searchParams.delete("comparisonEnd");
    }
    window.history.replaceState({}, "", url);
  }

  function subtractYears(dateText, years) {
    var parts = String(dateText).slice(0, 10).split("-").map(Number);
    return String(parts[0] - years).padStart(4, "0") + "-" + String(parts[1]).padStart(2, "0") + "-01";
  }

  function rangeBounds() {
    var points = state.payload.points || [];
    var first = points.length ? points[0].date : null;
    var last = points.length ? points[points.length - 1].date : null;
    if (state.range === "custom") {
      var customStart = byId("gcCustomStart").value;
      var customEnd = byId("gcCustomEnd").value;
      return {
        start: customStart ? customStart + "-01" : first,
        end: customEnd ? customEnd + "-01" : last,
      };
    }
    if (state.range !== "all") return { start: subtractYears(last, Number(state.range)), end: last };
    return { start: first, end: last };
  }

  function visibleRows() {
    var bounds = rangeBounds();
    return (state.payload.points || []).filter(function (row) {
      return row.date >= bounds.start && row.date <= bounds.end;
    });
  }

  function effectiveVisible(definition) {
    var visible = state.legendVisible[definition.id] !== false;
    if (definition.id === "sp500Nominal" && !state.showSp500Nominal) visible = false;
    if (definition.isTheoretical && !state.showTheoreticalValueSeries) visible = false;
    return visible;
  }

  function normalizedValues(rows, definition) {
    if (state.normalization === "fixed") {
      return rows.map(function (row) { return finite(row[definition.normalizedField]); });
    }
    var base = null;
    var anchorField = definition.normalizationAnchorField || definition.rawField;
    rows.some(function (row) {
      var value = finite(row[anchorField]);
      if (value != null && value !== 0) {
        base = value;
        return true;
      }
      return false;
    });
    return rows.map(function (row) {
      var value = finite(row[definition.rawField]);
      return value == null || base == null ? null : value / base * 100;
    });
  }

  function dashFor(definition) {
    if (definition.lineStyle === "dashed") return [10, 6];
    if (definition.lineStyle === "dash-dot-diamond") return [14, 5, 3, 5];
    return [];
  }

  function pointStyleFor(definition) {
    return definition.lineStyle === "dash-dot-diamond" ? "rectRot" : false;
  }

  function buildDatasets(rows) {
    return state.payload.seriesDefinitions.map(function (definition) {
      var values = normalizedValues(rows, definition);
      var available = values.some(function (value) { return value != null; });
      return {
        id: definition.id,
        label: definition.shortName + (definition.isTheoretical && !available ? "（算出不可）" : ""),
        data: rows.map(function (row, index) {
          return { x: row.x, y: values[index], sourceRow: row };
        }),
        borderColor: definition.color,
        backgroundColor: definition.color,
        borderWidth: definition.lineStyle === "dashed" ? 2.4 : 3.2,
        borderDash: dashFor(definition),
        pointStyle: pointStyleFor(definition),
        pointRadius: definition.isTheoretical ? 2.8 : 0,
        pointHoverRadius: 5,
        pointHitRadius: 8,
        spanGaps: false,
        tension: 0,
        hidden: !effectiveVisible(definition),
        parsing: false,
        normalized: true,
      };
    });
  }

  var whiteBackgroundPlugin = {
    id: "gcWhiteBackground",
    beforeDraw: function (chart) {
      var context = chart.ctx;
      context.save();
      context.globalCompositeOperation = "destination-over";
      context.fillStyle = "#ffffff";
      context.fillRect(0, 0, chart.width, chart.height);
      context.restore();
    },
  };

  var crisisPlugin = {
    id: "gcCrisisZones",
    beforeDatasetsDraw: function (chart) {
      if (!state.showCrises || !state.payload) return;
      var area = chart.chartArea;
      var scale = chart.scales.x;
      if (!area || !scale) return;
      var context = chart.ctx;
      context.save();
      (state.payload.crises || []).forEach(function (crisis) {
        var start = decimalYear(crisis.startDate);
        var end = decimalYear(crisis.endDate);
        if (start == null || end == null || end < scale.min || start > scale.max) return;
        var left = Math.max(area.left, scale.getPixelForValue(Math.max(start, scale.min)));
        var right = Math.min(area.right, scale.getPixelForValue(Math.min(end, scale.max)));
        if (right - left < 3) right = Math.min(area.right, left + 3);
        context.fillStyle = crisis.color;
        context.fillRect(left, area.top, Math.max(1, right - left), area.bottom - area.top);
      });
      context.restore();
    },
    afterDatasetsDraw: function (chart) {
      if (!state.showCrises || !state.payload) return;
      var area = chart.chartArea;
      var scale = chart.scales.x;
      if (!area || !scale) return;
      var context = chart.ctx;
      context.save();
      context.font = "700 11px Meiryo, sans-serif";
      context.fillStyle = "#34475c";
      context.textAlign = "center";
      (state.payload.crises || []).forEach(function (crisis) {
        var start = decimalYear(crisis.startDate);
        var end = decimalYear(crisis.endDate);
        if (start == null || end == null || end < scale.min || start > scale.max) return;
        var center = Math.max(area.left + 28, Math.min(area.right - 28, scale.getPixelForValue((Math.max(start, scale.min) + Math.min(end, scale.max)) / 2)));
        context.fillText(crisis.label, center, area.top + 16);
      });
      context.restore();
    },
  };

  function definitionForDataset(dataset) {
    return state.payload.seriesDefinitions.find(function (row) { return row.id === dataset.id; });
  }

  function tooltipLines(context) {
    var definition = definitionForDataset(context.dataset);
    var row = context.raw.sourceRow;
    var lines = [definition.name + "：" + formatNumber(context.parsed.y, 2) + "（基準=100）"];
    if (definition.id === "sp500Nominal") {
      lines.push("名目指数水準：" + formatNumber(row.sp500Nominal, 2));
      lines.push("データ：Yahoo Finance 月次終値");
    } else if (definition.id === "sp500Real") {
      lines.push("名目指数：" + formatNumber(row.sp500Nominal, 2));
      lines.push("米国CPI：" + formatNumber(row.usCpi, 3));
      lines.push("CPI参照値：" + formatNumber(state.payload.cpiReferences.us.value, 3));
      lines.push("実質指数：" + formatNumber(row.sp500Real, 2));
    } else if (definition.id === "sp500TheoreticalReal") {
      lines.push("推計理論価値（名目）：" + formatNumber(row.sp500TheoreticalNominal, 2));
      lines.push("感応度レンジ：" + formatNumber(row.sp500TheoreticalLow, 2) + "～" + formatNumber(row.sp500TheoreticalHigh, 2));
      lines.push("5年平準化EPS：" + formatNumber(row.sp500EarningsPower, 2));
      lines.push("理論PER：" + formatNumber(row.sp500FairPe, 2) + "倍");
      lines.push("直近EPS：" + formatNumber(row.sp500LatestEarnings, 2));
      lines.push("直近EPS維持参考：" + formatNumber(row.sp500TheoreticalAtLatestEarnings, 2));
      lines.push("10年国債：" + formatNumber(row.sp500RiskFreePct, 2) + "% / ERP：" + formatNumber(row.sp500ErpPct, 2) + "%");
      lines.push("長期名目成長：" + formatNumber(row.sp500NominalGrowthPct, 2) + "% / 信用上乗せ：" + formatNumber(row.sp500CreditStressPct, 2) + "%");
      lines.push("市場価格の上乗せ：" + formatNumber(row.sp500MarketPremiumPct, 1) + "%");
      lines.push("利益データ：" + (row.sp500EarningsAvailableThroughYear || "未取得") + "年まで");
    } else if (definition.id === "nikkeiUsd") {
      lines.push("円建て日経平均：" + formatNumber(row.nikkeiJpy, 2));
      lines.push("1米ドル：" + formatNumber(row.usdjpyJpyPerUsd, 2) + "円");
      lines.push("ドル換算指数：" + formatNumber(row.nikkeiUsd, 2));
    } else if (definition.id === "nikkeiRealUsd") {
      lines.push("円建て日経平均：" + formatNumber(row.nikkeiJpy, 2));
      lines.push("日本CPI：" + formatNumber(row.japanCpi, 2));
      lines.push("CPI参照値：" + formatNumber(state.payload.cpiReferences.japan.value, 2));
      lines.push("実質円建て指数：" + formatNumber(row.nikkeiRealJpy, 2));
      lines.push("1米ドル：" + formatNumber(row.usdjpyJpyPerUsd, 2) + "円");
      lines.push("実質ドル換算指数：" + formatNumber(row.nikkeiRealUsd, 2));
    } else if (definition.id === "nikkeiTheoreticalUsd") {
      lines.push("推計理論価値（円）：" + formatNumber(row.nikkeiTheoreticalJpy, 2));
      lines.push("感応度レンジ：" + formatNumber(row.nikkeiTheoreticalLowJpy, 2) + "～" + formatNumber(row.nikkeiTheoreticalHighJpy, 2));
      lines.push("1米ドル：" + formatNumber(row.usdjpyJpyPerUsd, 2) + "円");
      lines.push("5年平準化EPS：" + formatNumber(row.nikkeiEarningsPower, 2));
      lines.push("公式指数PER：" + formatNumber(row.nikkeiIndexWeightPe, 2) + "倍 / 復元EPS：" + formatNumber(row.nikkeiIndexEps, 2));
      lines.push("直近EPS：" + formatNumber(row.nikkeiLatestEarnings, 2));
      lines.push("直近EPS維持参考：" + formatNumber(row.nikkeiTheoreticalAtLatestEarningsJpy, 2) + "円");
      lines.push("理論PER：" + formatNumber(row.nikkeiFairPe, 2) + "倍");
      lines.push("10年国債：" + formatNumber(row.nikkeiRiskFreePct, 2) + "% / ERP：" + formatNumber(row.nikkeiErpPct, 2) + "%");
      lines.push("長期名目成長：" + formatNumber(row.nikkeiNominalGrowthPct, 2) + "% / 信用上乗せ：" + formatNumber(row.nikkeiCreditStressPct, 2) + "%");
      lines.push("市場価格の上乗せ：" + formatNumber(row.nikkeiMarketPremiumPct, 1) + "%");
      lines.push("公式PER観測日：" + (row.nikkeiPeObservationDate || "未取得"));
    }
    lines.push("この系列の固定基準日：" + formatDate(state.payload.seriesBaseDates[definition.id] || state.payload.baseDate));
    return lines;
  }

  function renderChart() {
    if (!state.payload || typeof window.Chart !== "function") return;
    var rows = visibleRows();
    var canvas = byId("globalComparisonChart");
    if (!canvas || !rows.length) return;
    if (state.chart) state.chart.destroy();
    state.chart = new window.Chart(canvas, {
      type: "line",
      data: { datasets: buildDatasets(rows) },
      plugins: [whiteBackgroundPlugin, crisisPlugin],
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 260 },
        interaction: { mode: "nearest", intersect: false, axis: "x" },
        layout: { padding: { top: 6, right: 8, bottom: 2, left: 2 } },
        scales: {
          x: {
            type: "linear",
            min: rows[0].x,
            max: rows[rows.length - 1].x,
            grid: { color: "rgba(100, 116, 139, 0.12)" },
            ticks: {
              maxTicksLimit: window.innerWidth < 700 ? 6 : 11,
              callback: function (value) { return String(Math.round(value)); },
              color: "#526476",
              font: { family: "Meiryo, sans-serif", size: 12, weight: "600" },
            },
            title: { display: true, text: "年（月次）", color: "#34475c", font: { weight: "700" } },
          },
          y: {
            type: "linear",
            beginAtZero: true,
            min: 0,
            grid: { color: "rgba(100, 116, 139, 0.14)" },
            ticks: {
              color: "#526476",
              callback: function (value) { return Number(value).toLocaleString("ja-JP"); },
              font: { family: "Meiryo, sans-serif", size: 12, weight: "600" },
            },
            title: { display: true, text: "基準日＝100（線形軸）", color: "#34475c", font: { weight: "700" } },
          },
        },
        plugins: {
          title: {
            display: true,
            text: "S&P 500・日経平均：市場価格、実質価格、推計理論価値（線形軸）",
            color: "#102033",
            font: { family: "Meiryo, sans-serif", size: window.innerWidth < 700 ? 13 : 16, weight: "700" },
            padding: { bottom: 12 },
          },
          legend: {
            display: true,
            position: "bottom",
            labels: {
              usePointStyle: false,
              boxWidth: 36,
              boxHeight: 3,
              padding: 16,
              color: "#24384c",
              font: { family: "Meiryo, sans-serif", size: window.innerWidth < 700 ? 10 : 12, weight: "700" },
            },
            onClick: function (_event, item, legend) {
              var chart = legend.chart;
              var dataset = chart.data.datasets[item.datasetIndex];
              state.legendVisible[dataset.id] = !chart.isDatasetVisible(item.datasetIndex);
              renderChart();
            },
          },
          tooltip: {
            backgroundColor: "rgba(16, 32, 51, 0.96)",
            titleFont: { family: "Meiryo, sans-serif", weight: "700" },
            bodyFont: { family: "Meiryo, sans-serif", size: 12 },
            padding: 12,
            displayColors: true,
            callbacks: {
              title: function (items) { return items.length ? formatDate(items[0].raw.sourceRow.date) : ""; },
              label: tooltipLines,
              footer: function () {
                return "固定基準日：" + formatDate(state.payload.baseDate) + " / データ更新：" + formatTimestamp(state.payload.generatedAtJst);
              },
            },
          },
        },
      },
    });
    updateChartSummary(rows);
  }

  function updateChartSummary(rows) {
    byId("gcDisplayedRange").textContent = formatDate(rows[0].date) + "～" + formatDate(rows[rows.length - 1].date);
    var visibleCount = state.payload.seriesDefinitions.filter(effectiveVisible).length;
    var availableCount = state.chart.data.datasets.filter(function (dataset, index) {
      return state.chart.isDatasetVisible(index) && dataset.data.some(function (point) { return point.y != null; });
    }).length;
    byId("gcVisibleSeries").textContent = visibleCount + "系列を選択 / " + availableCount + "系列に実データ";
  }

  function renderMetadata() {
    byId("gcBaseDate").textContent = formatDate(state.payload.baseDate);
    byId("gcLatestDate").textContent = formatDate(state.payload.latestCommonMonth);
    byId("gcUpdatedAt").textContent = formatTimestamp(state.payload.generatedAtJst);
    byId("gcObservationCount").textContent = formatNumber(state.payload.observationCount, 0) + "か月";
    byId("gcFxDirection").textContent = state.payload.exchangeRate.definition + "（" + state.payload.exchangeRate.seriesId + "）";
    var errorPanel = byId("gcDataWarnings");
    if ((state.payload.errors || []).length) {
      errorPanel.hidden = false;
      errorPanel.textContent = "更新上の注意：" + state.payload.errors.join(" / ");
    } else {
      errorPanel.hidden = true;
    }
  }

  function renderSources() {
    var container = byId("gcSourceList");
    if (!container) return;
    container.innerHTML = (state.payload.sources || []).map(function (source) {
      var label = source.name || source.provider || source.seriesId || source.symbol || "データソース";
      var detail = [source.seriesId || source.symbol, source.unit, source.latestMonth ? "最終月 " + source.latestMonth : null, source.cacheState].filter(Boolean).join(" / ");
      var url = source.sourceUrl || source.sourceAgencyUrl || source.downloadUrl;
      var body = "<strong>" + escapeHtml(label) + "</strong><span>" + escapeHtml(detail || "取得情報を確認済み") + "</span>";
      return url
        ? '<a href="' + escapeHtml(url) + '" target="_blank" rel="noopener">' + body + '</a>'
        : "<div>" + body + "</div>";
    }).join("");
  }

  function modelLabel(row) {
    return row && row.status === "available" ? "推計あり" : "推計不可";
  }

  function modelGapText(value) {
    var number = finite(value);
    if (number == null) return "未算出";
    if (Math.abs(number) < 0.05) return "市場価格と中心値がほぼ同じ";
    return number > 0
      ? "市場価格が中心値より" + formatNumber(number, 1) + "%高い"
      : "市場価格が中心値より" + formatNumber(Math.abs(number), 1) + "%低い";
  }

  function renderCoverage() {
    [
      { id: "Sp", row: state.payload.theoreticalModels.sp500, unit: "" },
      { id: "Nk", row: state.payload.theoreticalModels.nikkei225, unit: "円" },
    ].forEach(function (item) {
      var row = item.row;
      var latest = row && row.latest ? row.latest : {};
      var available = row && row.status === "available";
      var suffix = item.unit;
      byId("gc" + item.id + "ModelStatus").textContent = modelLabel(row);
      byId("gc" + item.id + "ModelStatus").className = "gc-coverage-state " + (available ? "ok" : "missing");
      byId("gc" + item.id + "ModelDate").textContent = row && row.latestDate ? formatDate(row.latestDate) : "未取得";
      byId("gc" + item.id + "EarningsPower").textContent = formatNumber(latest.earningsPower, 2);
      byId("gc" + item.id + "TheoreticalCenter").textContent = formatNumber(latest.central, 0) + suffix;
      byId("gc" + item.id + "TheoreticalRange").textContent = formatNumber(latest.low, 0) + "～" + formatNumber(latest.high, 0) + suffix;
      byId("gc" + item.id + "LatestEarningsValue").textContent = formatNumber(latest.latestEarningsValue, 0) + suffix;
      byId("gc" + item.id + "FairPe").textContent = formatNumber(latest.fairPe, 1) + "倍";
      byId("gc" + item.id + "MarketGap").textContent = modelGapText(latest.marketPremiumPct);
      byId("gc" + item.id + "ModelReason").textContent = available
        ? "中心値は5年平準化EPS、直近EPS維持参考は最近の利益へ同じ理論PERを掛けた別計算です。幅は要求収益率と成長率の感応度です。"
        : "必要な利益・金利データがそろっていないため表示していません。";
    });
  }

  function updateControls() {
    document.querySelectorAll("[data-gc-range]").forEach(function (button) {
      var active = button.dataset.gcRange === state.range;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
    byId("gcCustomRange").hidden = state.range !== "custom";
    byId("gcNormalization").value = state.normalization;
    var spButton = byId("gcToggleSpNominal");
    spButton.textContent = state.showSp500Nominal
      ? "比較を拡大：S&P 500名目を除外"
      : "全体表示：S&P 500名目を戻す";
    spButton.setAttribute("aria-pressed", String(!state.showSp500Nominal));
    var theoreticalButton = byId("gcToggleTheoretical");
    theoreticalButton.textContent = state.showTheoreticalValueSeries
      ? "理論価値2系列を非表示"
      : "理論価値2系列を表示";
    theoreticalButton.setAttribute("aria-pressed", String(!state.showTheoreticalValueSeries));
    var crisisButton = byId("gcToggleCrises");
    crisisButton.textContent = state.showCrises ? "危機期間を非表示" : "危機期間を表示";
    crisisButton.setAttribute("aria-pressed", String(!state.showCrises));
  }

  function safeFilename(extension) {
    return "sp500-nikkei-comparison-" + String(state.payload.latestCommonMonth).slice(0, 7) + "." + extension;
  }

  function downloadBlob(blob, filename) {
    var link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(function () { URL.revokeObjectURL(link.href); }, 1000);
  }

  function exportPng() {
    if (!state.chart) return;
    var link = document.createElement("a");
    link.download = safeFilename("png");
    link.href = state.chart.toBase64Image("image/png", 1);
    link.click();
  }

  function svgPolyline(points, xScale, yScale) {
    var segments = [];
    var current = [];
    points.forEach(function (point) {
      if (point.y == null) {
        if (current.length) segments.push(current.join(" "));
        current = [];
      } else {
        current.push(xScale(point.x).toFixed(2) + "," + yScale(point.y).toFixed(2));
      }
    });
    if (current.length) segments.push(current.join(" "));
    return segments;
  }

  function exportSvg() {
    var rows = visibleRows();
    var definitions = state.payload.seriesDefinitions.filter(effectiveVisible);
    var datasets = buildDatasets(rows).filter(function (dataset) {
      return definitions.some(function (definition) { return definition.id === dataset.id; });
    });
    var width = 1400;
    var height = 820;
    var area = { left: 92, right: 1348, top: 105, bottom: 690 };
    var values = [];
    datasets.forEach(function (dataset) { dataset.data.forEach(function (point) { if (point.y != null) values.push(point.y); }); });
    var maxY = Math.max(100, Math.max.apply(null, values) * 1.08);
    var minX = rows[0].x;
    var maxX = rows[rows.length - 1].x;
    var xScale = function (value) { return area.left + (value - minX) / Math.max(0.001, maxX - minX) * (area.right - area.left); };
    var yScale = function (value) { return area.bottom - value / maxY * (area.bottom - area.top); };
    var svg = [];
    svg.push("<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"" + width + "\" height=\"" + height + "\" viewBox=\"0 0 " + width + " " + height + "\">");
    svg.push("<rect width=\"100%\" height=\"100%\" fill=\"white\"/>");
    svg.push("<text x=\"70\" y=\"48\" font-family=\"Meiryo,sans-serif\" font-size=\"25\" font-weight=\"700\" fill=\"#102033\">S&amp;P 500・日経平均：市場価格、実質価格、推計理論価値</text>");
    svg.push("<text x=\"70\" y=\"76\" font-family=\"Meiryo,sans-serif\" font-size=\"14\" fill=\"#526476\">基準日=100 / 通常の線形軸 / " + escapeHtml(formatDate(rows[0].date)) + "～" + escapeHtml(formatDate(rows[rows.length - 1].date)) + "</text>");
    if (state.showCrises) {
      (state.payload.crises || []).forEach(function (crisis) {
        var start = decimalYear(crisis.startDate);
        var end = decimalYear(crisis.endDate);
        if (end < minX || start > maxX) return;
        var left = xScale(Math.max(start, minX));
        var right = xScale(Math.min(end, maxX));
        svg.push("<rect x=\"" + left.toFixed(2) + "\" y=\"" + area.top + "\" width=\"" + Math.max(3, right - left).toFixed(2) + "\" height=\"" + (area.bottom - area.top) + "\" fill=\"" + crisis.color + "\"/>");
      });
    }
    for (var grid = 0; grid <= 5; grid += 1) {
      var gridValue = maxY * grid / 5;
      var y = yScale(gridValue);
      svg.push("<line x1=\"" + area.left + "\" y1=\"" + y + "\" x2=\"" + area.right + "\" y2=\"" + y + "\" stroke=\"#d5dde5\"/>");
      svg.push("<text x=\"" + (area.left - 12) + "\" y=\"" + (y + 5) + "\" text-anchor=\"end\" font-family=\"Meiryo,sans-serif\" font-size=\"13\" fill=\"#526476\">" + Math.round(gridValue).toLocaleString("ja-JP") + "</text>");
    }
    datasets.forEach(function (dataset) {
      var definition = definitionForDataset(dataset);
      var dash = dashFor(definition).join(" ");
      svgPolyline(dataset.data, xScale, yScale).forEach(function (points) {
        svg.push("<polyline points=\"" + points + "\" fill=\"none\" stroke=\"" + definition.color + "\" stroke-width=\"3\"" + (dash ? " stroke-dasharray=\"" + dash + "\"" : "") + "/>");
      });
    });
    svg.push("<line x1=\"" + area.left + "\" y1=\"" + area.bottom + "\" x2=\"" + area.right + "\" y2=\"" + area.bottom + "\" stroke=\"#526476\" stroke-width=\"1.4\"/>");
    svg.push("<line x1=\"" + area.left + "\" y1=\"" + area.top + "\" x2=\"" + area.left + "\" y2=\"" + area.bottom + "\" stroke=\"#526476\" stroke-width=\"1.4\"/>");
    definitions.forEach(function (definition, index) {
      var x = 78 + (index % 3) * 435;
      var y = 735 + Math.floor(index / 3) * 34;
      var dash = dashFor(definition).join(" ");
      svg.push("<line x1=\"" + x + "\" y1=\"" + y + "\" x2=\"" + (x + 46) + "\" y2=\"" + y + "\" stroke=\"" + definition.color + "\" stroke-width=\"4\"" + (dash ? " stroke-dasharray=\"" + dash + "\"" : "") + "/>");
      svg.push("<text x=\"" + (x + 58) + "\" y=\"" + (y + 5) + "\" font-family=\"Meiryo,sans-serif\" font-size=\"14\" font-weight=\"700\" fill=\"#24384c\">" + escapeHtml(definition.shortName) + "</text>");
    });
    svg.push("</svg>");
    downloadBlob(new Blob([svg.join("")], { type: "image/svg+xml;charset=utf-8" }), safeFilename("svg"));
  }

  var COMMON_CSV_COLUMNS = ["date", "usCpi", "japanCpi", "usdjpyJpyPerUsd", "nikkeiJpy"];
  var SERIES_CSV_COLUMNS = {
    sp500Nominal: ["sp500Nominal", "sp500NominalNormalized"],
    sp500Real: ["sp500Real", "sp500RealNormalized"],
    sp500TheoreticalReal: ["sp500EarningsPower", "sp500LatestEarnings", "sp500TheoreticalAtLatestEarnings", "sp500TheoreticalNominal", "sp500TheoreticalLow", "sp500TheoreticalHigh", "sp500TheoreticalReal", "sp500TheoreticalRealNormalized", "sp500FairPe", "sp500RiskFreePct", "sp500ErpPct", "sp500NominalGrowthPct", "sp500MarketPremiumPct"],
    nikkeiUsd: ["nikkeiUsd", "nikkeiUsdNormalized"],
    nikkeiRealUsd: ["nikkeiRealJpy", "nikkeiRealUsd", "nikkeiRealUsdNormalized"],
    nikkeiTheoreticalUsd: ["nikkeiIndexWeightPe", "nikkeiIndexEps", "nikkeiEarningsPower", "nikkeiLatestEarnings", "nikkeiLatestEarningsDate", "nikkeiTheoreticalAtLatestEarningsJpy", "nikkeiTheoreticalJpy", "nikkeiTheoreticalLowJpy", "nikkeiTheoreticalHighJpy", "nikkeiTheoreticalUsd", "nikkeiTheoreticalUsdNormalized", "nikkeiFairPe", "nikkeiRiskFreePct", "nikkeiErpPct", "nikkeiNominalGrowthPct", "nikkeiMarketPremiumPct"],
  };

  function csvValue(value) {
    if (value == null) return "";
    var text = String(value);
    return /[",\n]/.test(text) ? '"' + text.replace(/"/g, '""') + '"' : text;
  }

  function exportCsv() {
    var visibleOnly = byId("gcCsvVisibleOnly").checked;
    var definitions = visibleOnly ? state.payload.seriesDefinitions.filter(effectiveVisible) : state.payload.seriesDefinitions;
    var columns = COMMON_CSV_COLUMNS.slice();
    definitions.forEach(function (definition) {
      (SERIES_CSV_COLUMNS[definition.id] || []).forEach(function (column) {
        if (columns.indexOf(column) < 0) columns.push(column);
      });
    });
    var rows = visibleRows();
    var csv = [columns.join(",")].concat(rows.map(function (row) {
      return columns.map(function (column) { return csvValue(row[column]); }).join(",");
    })).join("\r\n");
    downloadBlob(new Blob(["\ufeff" + csv], { type: "text/csv;charset=utf-8" }), safeFilename("csv"));
  }

  function bindEvents() {
    document.querySelectorAll("[data-gc-range]").forEach(function (button) {
      button.addEventListener("click", function () {
        state.range = button.dataset.gcRange;
        updateControls();
        writeUrlState();
        renderChart();
      });
    });
    ["gcCustomStart", "gcCustomEnd"].forEach(function (id) {
      byId(id).addEventListener("change", function () {
        writeUrlState();
        renderChart();
      });
    });
    byId("gcNormalization").addEventListener("change", function () {
      state.normalization = this.value;
      writeUrlState();
      renderChart();
    });
    byId("gcRefreshData").addEventListener("click", function () {
      var mainRefresh = byId("refreshButton");
      if (mainRefresh && !mainRefresh.disabled) mainRefresh.click();
    });
    byId("gcToggleSpNominal").addEventListener("click", function () {
      state.showSp500Nominal = !state.showSp500Nominal;
      updateControls();
      writeUrlState();
      renderChart();
    });
    byId("gcToggleTheoretical").addEventListener("click", function () {
      state.showTheoreticalValueSeries = !state.showTheoreticalValueSeries;
      updateControls();
      writeUrlState();
      renderChart();
    });
    byId("gcToggleCrises").addEventListener("click", function () {
      state.showCrises = !state.showCrises;
      updateControls();
      writeUrlState();
      renderChart();
    });
    byId("gcExportPng").addEventListener("click", exportPng);
    byId("gcExportSvg").addEventListener("click", exportSvg);
    byId("gcExportCsv").addEventListener("click", exportCsv);
    window.addEventListener("resize", function () {
      window.clearTimeout(state.resizeTimer);
      state.resizeTimer = window.setTimeout(renderChart, 180);
    });
    window.addEventListener("monitor:data-updated", function () { loadComparison(true); });
  }

  async function loadComparison(isRefresh) {
    var status = byId("gcLoadStatus");
    if (!status) return;
    status.textContent = isRefresh ? "更新後データを再読込中" : "月次データを読込中";
    status.className = "gc-load-status loading";
    try {
      var response = await fetch(DATA_URL + "?ts=" + Date.now(), { cache: "no-store" });
      if (!response.ok) throw new Error("HTTP " + response.status);
      var payload = await response.json();
      if (!Array.isArray(payload.seriesDefinitions) || payload.seriesDefinitions.length !== 6) {
        throw new Error("6系列データの形式が不正です");
      }
      state.payload = payload;
      payload.seriesDefinitions.forEach(function (definition) {
        if (state.legendVisible[definition.id] == null) state.legendVisible[definition.id] = true;
      });
      var first = payload.points[0].date.slice(0, 7);
      var last = payload.points[payload.points.length - 1].date.slice(0, 7);
      if (!byId("gcCustomStart").value) byId("gcCustomStart").value = first;
      if (!byId("gcCustomEnd").value) byId("gcCustomEnd").value = last;
      renderMetadata();
      renderCoverage();
      renderSources();
      updateControls();
      renderChart();
      var availableSeries = payload.seriesDefinitions.filter(function (definition) {
        return payload.points.some(function (point) { return point[definition.normalizedField] != null; });
      }).length;
      status.textContent = availableSeries === 6
        ? "6系列すべてを表示。理論価値は利益還元モデルの推計です"
        : "実データ" + availableSeries + "系列を表示。理論価値は80%カバー率を満たす期間だけ表示";
      status.className = "gc-load-status ready";
      if (window.lucide) window.lucide.createIcons();
    } catch (error) {
      status.textContent = "チャートデータを読み込めませんでした：" + error.message;
      status.className = "gc-load-status error";
    }
  }

  function init() {
    if (!byId("global-comparison")) return;
    readUrlState();
    bindEvents();
    updateControls();
    loadComparison(false);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
}());
