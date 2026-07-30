(function () {
  "use strict";

  var DATA_URL = "data/global-market-value-comparison.json";
  var state = {
    valuationChart: null,
    payload: null,
    chart: null,
    range: "all",
    normalization: "fixed",
    showSp500Nominal: false,
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

  function compactChartMode() {
    return window.matchMedia && window.matchMedia("(max-width: 699px)").matches;
  }

  function chartAnimationDuration() {
    return window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 260;
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
    state.showSp500Nominal = params.get("showSp500Nominal") === "true";
    if (params.get("hideSp500Nominal") === "true") state.showSp500Nominal = false;
    state.showTheoreticalValueSeries = params.get("showTheoreticalValue") !== "false";
    state.showCrises = params.get("showComparisonCrises") !== "false";
    var range = params.get("comparisonRange");
    if (["all", "30", "20", "10", "5", "future", "custom"].indexOf(range) >= 0) state.range = range;
    var normalization = params.get("comparisonNormalization");
    if (["fixed", "visible"].indexOf(normalization) >= 0) state.normalization = normalization;
    if (params.get("comparisonStart") && byId("gcCustomStart")) byId("gcCustomStart").value = params.get("comparisonStart");
    if (params.get("comparisonEnd") && byId("gcCustomEnd")) byId("gcCustomEnd").value = params.get("comparisonEnd");
  }

  function writeUrlState() {
    var url = new URL(window.location.href);
    url.searchParams.delete("hideSp500Nominal");
    if (state.showSp500Nominal) url.searchParams.set("showSp500Nominal", "true");
    else url.searchParams.delete("showSp500Nominal");
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
    if (state.range === "future") return { start: subtractYears(last, 5), end: last };
    if (state.range !== "all") return { start: subtractYears(last, Number(state.range)), end: last };
    return { start: first, end: last };
  }

  function visibleRows() {
    var bounds = rangeBounds();
    return (state.payload.points || []).filter(function (row) {
      return row.date >= bounds.start && row.date <= bounds.end;
    });
  }

  function chartMaxX(rows) {
    if (state.range === "future") return 2028 + 11 / 12;
    return rows.length ? rows[rows.length - 1].x : null;
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

  function lineWidthFor(definition) {
    if (definition.isTheoretical) return 4.6;
    if (definition.lineStyle === "dashed") return 3.4;
    return 4.2;
  }

  function markerStepFor(pointCount) {
    if (pointCount > 360) return 24;
    if (pointCount > 180) return 12;
    if (pointCount > 72) return 6;
    if (pointCount > 36) return 3;
    return 1;
  }

  function endLabelFor(id) {
    return {
      sp500Nominal: "S&P名目", sp500Real: "S&P実質", sp500TheoreticalReal: "S&P理論",
      nikkeiUsd: "日経USD", nikkeiRealUsd: "日経実質", nikkeiTheoreticalUsd: "日経理論",
    }[id] || id;
  }

  function buildDatasets(rows) {
    return state.payload.seriesDefinitions.map(function (definition) {
      var values = normalizedValues(rows, definition);
      var available = values.some(function (value) { return value != null; });
      var markerStep = markerStepFor(rows.length);
      var lineWidth = lineWidthFor(definition);
      return {
        id: definition.id,
        label: definition.shortName + (definition.isTheoretical && !available ? "（算出不可）" : ""),
        data: rows.map(function (row, index) {
          return { x: row.x, y: values[index], sourceRow: row };
        }),
        borderColor: definition.color,
        backgroundColor: "transparent",
        borderWidth: lineWidth,
        hoverBorderWidth: lineWidth + 1.4,
        borderDash: dashFor(definition),
        borderCapStyle: "round",
        borderJoinStyle: "round",
        pointStyle: pointStyleFor(definition),
        pointRadius: definition.isTheoretical ? function (context) {
          var last = context.dataIndex === values.length - 1;
          return last || context.dataIndex % markerStep === 0 ? 4.2 : 0;
        } : 0,
        pointBackgroundColor: definition.color,
        pointBorderColor: "#ffffff",
        pointBorderWidth: 1.5,
        pointHoverRadius: 7,
        pointHoverBorderWidth: 2,
        pointHitRadius: 11,
        fill: false,
        order: definition.isTheoretical ? 0 : (definition.lineStyle === "dashed" ? 1 : 2),
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

  var futureWindowPlugin = {
    id: "gcFutureWindow",
    beforeDatasetsDraw: function (chart) {
      if (state.range !== "future" || !state.payload) return;
      var area = chart.chartArea;
      var scale = chart.scales.x;
      var points = state.payload.points || [];
      if (!area || !scale || !points.length) return;
      var latestX = points[points.length - 1].x;
      var left = Math.max(area.left, Math.min(area.right, scale.getPixelForValue(latestX)));
      var context = chart.ctx;
      context.save();
      context.fillStyle = "rgba(42, 113, 131, 0.07)";
      context.fillRect(left, area.top, Math.max(0, area.right - left), area.bottom - area.top);
      context.setLineDash([7, 5]);
      context.strokeStyle = "#2a7183";
      context.lineWidth = 1.5;
      context.beginPath();
      context.moveTo(left, area.top);
      context.lineTo(left, area.bottom);
      context.stroke();
      context.restore();
    },
    afterDatasetsDraw: function (chart) {
      if (state.range !== "future" || !state.payload) return;
      var area = chart.chartArea;
      var scale = chart.scales.x;
      var points = state.payload.points || [];
      if (!area || !scale || !points.length) return;
      var latestX = points[points.length - 1].x;
      var left = Math.max(area.left, Math.min(area.right, scale.getPixelForValue(latestX)));
      var context = chart.ctx;
      context.save();
      context.fillStyle = "#1e6070";
      context.font = "800 11px Meiryo, sans-serif";
      context.textAlign = "left";
      context.fillText("将来：価格を予言せず、予定と監視条件を確認", Math.min(left + 8, area.right - 230), area.top + 34);
      context.restore();
    },
  };

  var endLabelPlugin = {
    id: "gcEndLabels",
    afterDatasetsDraw: function (chart) {
      var area = chart.chartArea;
      if (!area || !state.payload) return;
      var labels = [];
      chart.data.datasets.forEach(function (dataset, datasetIndex) {
        if (!chart.isDatasetVisible(datasetIndex)) return;
        var meta = chart.getDatasetMeta(datasetIndex);
        var pointIndex = -1;
        for (var index = dataset.data.length - 1; index >= 0; index -= 1) {
          if (dataset.data[index].y != null && meta.data[index]) {
            pointIndex = index;
            break;
          }
        }
        if (pointIndex < 0) return;
        labels.push({
          y: meta.data[pointIndex].y,
          color: dataset.borderColor,
          text: endLabelFor(dataset.id),
        });
      });
      if (!labels.length) return;
      labels.sort(function (a, b) { return a.y - b.y; });
      var minimumY = area.top + 10;
      var maximumY = area.bottom - 10;
      var gap = window.innerWidth < 700 ? 16 : 18;
      labels.forEach(function (label, index) {
        label.labelY = Math.max(label.y, index ? labels[index - 1].labelY + gap : minimumY);
      });
      if (labels[labels.length - 1].labelY > maximumY) {
        var shift = labels[labels.length - 1].labelY - maximumY;
        labels.forEach(function (label) { label.labelY -= shift; });
      }
      for (var reverse = labels.length - 2; reverse >= 0; reverse -= 1) {
        labels[reverse].labelY = Math.min(labels[reverse].labelY, labels[reverse + 1].labelY - gap);
      }
      if (labels[0].labelY < minimumY) {
        var correction = minimumY - labels[0].labelY;
        labels.forEach(function (label) { label.labelY += correction; });
      }
      var context = chart.ctx;
      context.save();
      context.font = (window.innerWidth < 700 ? "700 10px" : "700 11px") + " Meiryo, sans-serif";
      context.textBaseline = "middle";
      labels.forEach(function (label) {
        var labelX = area.right + 12;
        var width = context.measureText(label.text).width;
        context.fillStyle = "rgba(255,255,255,0.94)";
        context.fillRect(labelX - 4, label.labelY - 8, width + 8, 16);
        context.strokeStyle = label.color;
        context.lineWidth = 3;
        context.beginPath();
        context.moveTo(area.right + 2, label.y);
        context.lineTo(labelX - 6, label.labelY);
        context.stroke();
        context.fillStyle = label.color;
        context.fillText(label.text, labelX, label.labelY);
      });
      context.restore();
    },
  };
  var premiumZonePlugin = {
    id: "gcPremiumZones",
    beforeDatasetsDraw: function (chart) {
      var area = chart.chartArea;
      var scale = chart.scales.y;
      if (!area || !scale) return;
      var zeroY = Math.max(area.top, Math.min(area.bottom, scale.getPixelForValue(0)));
      var context = chart.ctx;
      context.save();
      context.fillStyle = "rgba(192, 57, 43, 0.055)";
      context.fillRect(area.left, area.top, area.right - area.left, Math.max(0, zeroY - area.top));
      context.fillStyle = "rgba(34, 139, 94, 0.055)";
      context.fillRect(area.left, zeroY, area.right - area.left, Math.max(0, area.bottom - zeroY));
      context.strokeStyle = "#526476";
      context.lineWidth = 2;
      context.beginPath();
      context.moveTo(area.left, zeroY);
      context.lineTo(area.right, zeroY);
      context.stroke();
      context.fillStyle = "#34475c";
      context.font = "800 11px Meiryo, sans-serif";
      context.textAlign = "left";
      context.fillText("0%＝成長込み理論中心値", area.left + 8, zeroY - 7);
      context.restore();
    },
  };

  var premiumEndLabelPlugin = {
    id: "gcPremiumEndLabels",
    afterDatasetsDraw: function (chart) {
      var area = chart.chartArea;
      if (!area) return;
      var context = chart.ctx;
      context.save();
      context.font = (window.innerWidth < 700 ? "800 10px" : "800 12px") + " Meiryo, sans-serif";
      context.textBaseline = "middle";
      chart.data.datasets.forEach(function (dataset, datasetIndex) {
        var meta = chart.getDatasetMeta(datasetIndex);
        if (dataset.showEndLabel === false) return;
        var index = dataset.data.length - 1;
        while (index >= 0 && dataset.data[index].y == null) index -= 1;
        if (index < 0 || !meta.data[index]) return;
        var point = meta.data[index];
        var label = dataset.shortLabel + " " + (dataset.data[index].y >= 0 ? "+" : "") + formatNumber(dataset.data[index].y, 1) + "%";
        var x = area.right + 10;
        context.strokeStyle = dataset.borderColor;
        context.lineWidth = 3;
        context.beginPath();
        context.moveTo(area.right + 2, point.y);
        context.lineTo(x - 5, point.y);
        context.stroke();
        context.fillStyle = "rgba(255,255,255,0.95)";
        context.fillRect(x - 3, point.y - 9, context.measureText(label).width + 7, 18);
        context.fillStyle = dataset.borderColor;
        context.fillText(label, x, point.y);
      });
      context.restore();
    },
  };

  function renderValuationChart(rows) {
    var canvas = byId("valuationExcessChart");
    if (!canvas || !rows.length) return;
    var compact = compactChartMode();
    if (state.valuationChart) state.valuationChart.destroy();
    var proxy = state.payload.theoreticalModels
      && state.payload.theoreticalModels.nikkei225
      && state.payload.theoreticalModels.nikkei225.historicalRelativeProxy;
    var proxyEnd = proxy && proxy.displayEndDate ? proxy.displayEndDate : "0000-00-00";
    var datasets = [
      { id: "sp500Premium", label: "S&P 500・現行モデル中心値からの上乗せ", shortLabel: "S&P", field: "sp500MarketPremiumPct", color: "#0057B8", width: 4.2, dash: [] },
      { id: "nikkeiHistoricalPremium", label: "日経平均・1985～公式モデル前（実質大企業利益proxy）", shortLabel: "日経歴史proxy", field: "nikkeiHistoricalPremiumProxyPct", color: "#9A6700", width: 3.5, dash: [10, 6], showEndLabel: false },
      { id: "nikkeiPremium", label: "日経平均・現行モデル中心値からの上乗せ", shortLabel: "日経現行", field: "nikkeiMarketPremiumPct", color: "#D83B2D", width: 4.2, dash: [] },
    ].map(function (definition) {
      return {
        id: definition.id,
        label: definition.label,
        shortLabel: definition.shortLabel,
        showEndLabel: definition.showEndLabel !== false,
        data: rows.map(function (row) {
          var value = finite(row[definition.field]);
          if (definition.id === "nikkeiHistoricalPremium" && row.date > proxyEnd) value = null;
          return { x: row.x, y: value, sourceRow: row };
        }),
        borderColor: definition.color,
        backgroundColor: "transparent",
        borderWidth: definition.width,
        hoverBorderWidth: definition.width + 1.3,
        borderDash: definition.dash,
        borderCapStyle: "round",
        borderJoinStyle: "round",
        pointRadius: 0,
        pointHoverRadius: 6,
        pointHitRadius: 10,
        tension: 0,
        spanGaps: false,
        parsing: false,
      };
    });
    state.valuationChart = new window.Chart(canvas, {
      type: "line",
      data: { datasets: datasets },
      plugins: compact ? [whiteBackgroundPlugin, premiumZonePlugin, crisisPlugin, futureWindowPlugin] : [whiteBackgroundPlugin, premiumZonePlugin, crisisPlugin, futureWindowPlugin, premiumEndLabelPlugin],
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: chartAnimationDuration() },
        interaction: { mode: "nearest", intersect: false, axis: "x" },
        layout: { padding: { top: compact ? 2 : 8, right: compact ? 8 : 126, bottom: 4, left: compact ? 0 : 4 } },
        scales: {
          x: {
            type: "linear",
            min: rows[0].x,
            max: chartMaxX(rows),
            grid: { display: false },
            ticks: { maxTicksLimit: window.innerWidth < 700 ? 6 : 11, callback: function (value) { return String(Math.round(value)); }, color: "#526476", font: { family: "Meiryo, sans-serif", size: window.innerWidth < 700 ? 11 : 13, weight: "700" } },
            title: { display: !compact, text: "年（月次）", color: "#34475c", font: { weight: "700" } },
          },
          y: {
            type: "linear",
            beginAtZero: true,
            grid: { color: "rgba(71, 85, 105, 0.11)", lineWidth: 1 },
            ticks: { color: "#526476", callback: function (value) { return (value > 0 ? "+" : "") + formatNumber(value, 0) + "%"; }, font: { family: "Meiryo, sans-serif", size: window.innerWidth < 700 ? 11 : 13, weight: "700" } },
            title: { display: !compact, text: "市場価格のモデル超過率", color: "#34475c", font: { weight: "800" } },
          },
        },
        plugins: {
          title: { display: !compact, text: "市場価格は、企業利益と持続可能な成長で説明できる水準を何％上回るか", color: "#102033", font: { family: "Meiryo, sans-serif", size: 18, weight: "800" }, padding: { bottom: 12 } },
          legend: { position: "bottom", labels: { boxWidth: compact ? 26 : 48, boxHeight: 5, padding: compact ? 10 : 18, color: "#24384c", font: { family: "Meiryo, sans-serif", size: compact ? 10 : 13, weight: "800" } } },
          tooltip: {
            backgroundColor: "rgba(16, 32, 51, 0.96)",
            titleFont: { family: "Meiryo, sans-serif", weight: "700" },
            bodyFont: { family: "Meiryo, sans-serif", size: 12 },
            padding: 12,
            callbacks: {
              title: function (items) { return items.length ? formatDate(items[0].raw.sourceRow.date) : ""; },
              label: function (context) { return context.dataset.label + "：" + (context.parsed.y >= 0 ? "+" : "") + formatNumber(context.parsed.y, 1) + "%"; },
              afterLabel: function (context) {
                var row = context.raw.sourceRow;
                if (context.dataset.id === "nikkeiHistoricalPremium") {
                  return [
                    "日経平均 " + formatNumber(row.nikkeiJpy, 0) + "円 / 歴史proxy " + formatNumber(row.nikkeiHistoricalFairValueProxyJpy, 0) + "円",
                    "実質大企業利益の5年中央値 " + formatNumber(row.nikkeiMacroProfitPowerRaw, 0),
                    "1985～86年の株価対実質利益を100とした相対比較（公式EPSではありません）",
                  ];
                }
                var isSp = context.dataset.id === "sp500Premium";
                return "成長率前提 " + formatNumber(row[isSp ? "sp500NominalGrowthPct" : "nikkeiNominalGrowthPct"], 2) + "% / 公正PER " + formatNumber(row[isSp ? "sp500FairPe" : "nikkeiFairPe"], 1) + "倍";
              },
              footer: function (items) {
                return items.some(function (item) { return item.dataset.id === "nikkeiHistoricalPremium"; })
                  ? "歴史proxyは方向と規模の比較用。現行モデルと同じ精度ではありません"
                  : "0%は割安・割高の事実ではなく、本サイトの基準モデル中心値です";
              },
            },
          },
        },
      },
    });
  }


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
    var compact = compactChartMode();
    renderValuationChart(rows);
    if (state.chart) state.chart.destroy();
    state.chart = new window.Chart(canvas, {
      type: "line",
      data: { datasets: buildDatasets(rows) },
      plugins: compact ? [whiteBackgroundPlugin, crisisPlugin, futureWindowPlugin] : [whiteBackgroundPlugin, crisisPlugin, futureWindowPlugin, endLabelPlugin],
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: chartAnimationDuration() },
        interaction: { mode: "nearest", intersect: false, axis: "x" },
        layout: { padding: { top: compact ? 2 : 8, right: compact ? 8 : 108, bottom: 4, left: compact ? 0 : 4 } },
        scales: {
          x: {
            type: "linear",
            min: rows[0].x,
            max: chartMaxX(rows),
            grid: { display: false },
            ticks: {
              maxTicksLimit: window.innerWidth < 700 ? 6 : 11,
              callback: function (value) { return String(Math.round(value)); },
              color: "#526476",
              font: { family: "Meiryo, sans-serif", size: window.innerWidth < 700 ? 11 : 13, weight: "700" },
            },
            title: { display: !compact, text: "年（月次）", color: "#34475c", font: { weight: "700" } },
          },
          y: {
            type: "linear",
            beginAtZero: true,
            min: 0,
            grid: { color: "rgba(71, 85, 105, 0.11)", lineWidth: 1 },
            ticks: {
              color: "#526476",
              callback: function (value) { return Number(value).toLocaleString("ja-JP"); },
              font: { family: "Meiryo, sans-serif", size: window.innerWidth < 700 ? 11 : 13, weight: "700" },
            },
            title: { display: !compact, text: "基準日＝100（線形軸）", color: "#34475c", font: { weight: "700" } },
          },
        },
        plugins: {
          title: {
            display: !compact,
            text: "S&P 500・日経平均：市場価格、実質価格、推計理論価値（線形軸）",
            color: "#102033",
            font: { family: "Meiryo, sans-serif", size: window.innerWidth < 700 ? 14 : 18, weight: "800" },
            padding: { bottom: 12 },
          },
          legend: {
            display: true,
            position: "bottom",
            labels: {
              usePointStyle: false,
              boxWidth: compact ? 26 : 48,
              boxHeight: 5,
              padding: compact ? 10 : 18,
              color: "#24384c",
              font: { family: "Meiryo, sans-serif", size: window.innerWidth < 700 ? 11 : 13, weight: "800" },
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
    var actualRange = formatDate(rows[0].date) + "～" + formatDate(rows[rows.length - 1].date);
    byId("gcDisplayedRange").textContent = state.range === "future"
      ? actualRange + "（実績） / 将来監視窓は2028年12月まで" : actualRange;
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

  function renderValuationFocus() {
    var latestRow = (state.payload.points || []).slice().reverse().find(function (row) {
      return finite(row.sp500MarketPremiumPct) != null && finite(row.nikkeiMarketPremiumPct) != null;
    });
    if (!latestRow) return;
    [
      { id: "Sp", model: state.payload.theoreticalModels.sp500, premiumField: "sp500MarketPremiumPct", growthField: "sp500NominalGrowthPct", riskFreeField: "sp500RiskFreePct", erpField: "sp500ErpPct", creditField: "sp500CreditStressPct", realMarketField: "sp500Real", realTheoryField: "sp500TheoreticalReal", realPrefix: "", unit: "" },
      { id: "Nk", model: state.payload.theoreticalModels.nikkei225, premiumField: "nikkeiMarketPremiumPct", growthField: "nikkeiNominalGrowthPct", riskFreeField: "nikkeiRiskFreePct", erpField: "nikkeiErpPct", creditField: "nikkeiCreditStressPct", realMarketField: "nikkeiRealUsd", realTheoryField: "nikkeiTheoreticalUsd", realPrefix: "$", unit: "円" },
    ].forEach(function (item) {
      var latest = item.model.latest;
      var premium = finite(latestRow[item.premiumField]);
      var overHigh = latest && latest.high ? (latest.market / latest.high - 1) * 100 : null;
      var requiredReturn = [item.riskFreeField, item.erpField, item.creditField].reduce(function (sum, field) {
        return sum + (finite(latestRow[field]) || 0);
      }, 0);
      byId("gc" + item.id + "PremiumNow").textContent = (premium >= 0 ? "+" : "") + formatNumber(premium, 1) + "%";
      byId("gc" + item.id + "PremiumNow").className = "gc-premium-number " + (premium > 0 ? "above" : "below");
      byId("gc" + item.id + "MarketNow").textContent = formatNumber(latest.market, 0) + item.unit;
      byId("gc" + item.id + "CenterNow").textContent = formatNumber(latest.central, 0) + item.unit;
      byId("gc" + item.id + "RangeNow").textContent = formatNumber(latest.low, 0) + "～" + formatNumber(latest.high, 0) + item.unit;
      byId("gc" + item.id + "RealPairNow").textContent = item.realPrefix + formatNumber(latestRow[item.realMarketField], 2) + " / " + item.realPrefix + formatNumber(latestRow[item.realTheoryField], 2);
      byId("gc" + item.id + "GrowthNow").textContent = "名目成長 " + formatNumber(latestRow[item.growthField], 2) + "% / 要求収益率 " + formatNumber(requiredReturn, 2) + "%";
      byId("gc" + item.id + "AboveHigh").textContent = overHigh == null
        ? "楽観上限との比較は未算出"
        : overHigh > 0
          ? "楽観シナリオ上限も " + formatNumber(overHigh, 1) + "%上回る"
          : "中心値より高いが、楽観シナリオ上限より " + formatNumber(Math.abs(overHigh), 1) + "%低い";
      byId("gc" + item.id + "AboveHigh").className = "gc-range-judgment " + (overHigh > 0 ? "outside" : "inside");
    });
    byId("gcPremiumAsOf").textContent = formatDate(latestRow.date) + "時点";
  }

  function renderHistoricalProxySummary() {
    var model = state.payload.theoreticalModels && state.payload.theoreticalModels.nikkei225;
    var proxy = model && model.historicalRelativeProxy;
    var points = state.payload.points || [];
    if (!proxy || proxy.status !== "available") {
      byId("gcHistoryModelHandoff").textContent = "歴史proxyを算出できません";
      return;
    }
    function rowAt(month) {
      return points.find(function (row) { return String(row.date).slice(0, 7) === month; });
    }
    function signed(value) {
      var number = finite(value);
      return number == null ? "未算出" : (number >= 0 ? "+" : "") + formatNumber(number, 1) + "%";
    }
    var peak = rowAt("1989-12");
    var normalization = rowAt("1990-12");
    var overshoot = points.filter(function (row) {
      return row.date >= "1989-12-01" && row.date <= "1992-08-01" && finite(row.nikkeiHistoricalPremiumProxyPct) != null;
    }).reduce(function (lowest, row) {
      return !lowest || row.nikkeiHistoricalPremiumProxyPct < lowest.nikkeiHistoricalPremiumProxyPct ? row : lowest;
    }, null);
    byId("gcHistoryPeakPremium").textContent = signed(peak && peak.nikkeiHistoricalPremiumProxyPct);
    byId("gcHistoryNormalizationPremium").textContent = signed(normalization && normalization.nikkeiHistoricalPremiumProxyPct);
    byId("gcHistoryOvershootPremium").textContent = signed(overshoot && overshoot.nikkeiHistoricalPremiumProxyPct);
    byId("gcHistoryModelHandoff").textContent =
      formatDate(proxy.startDate) + "～" + formatDate(proxy.displayEndDate) + "：歴史proxy / "
      + formatDate(proxy.officialModelStartDate) + "以降：公式PER由来モデル";
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
    var maxX = chartMaxX(rows);
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
        svg.push("<polyline points=\"" + points + "\" fill=\"none\" stroke=\"" + definition.color + "\" stroke-width=\"" + lineWidthFor(definition) + "\" stroke-linecap=\"round\" stroke-linejoin=\"round\"" + (dash ? " stroke-dasharray=\"" + dash + "\"" : "") + "/>");
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
    nikkeiTheoreticalUsd: [
      "nikkeiIndexWeightPe", "nikkeiIndexEps", "nikkeiEarningsPower", "nikkeiLatestEarnings", "nikkeiLatestEarningsDate",
      "nikkeiTheoreticalAtLatestEarningsJpy", "nikkeiTheoreticalJpy", "nikkeiTheoreticalLowJpy", "nikkeiTheoreticalHighJpy",
      "nikkeiTheoreticalUsd", "nikkeiTheoreticalUsdNormalized", "nikkeiFairPe", "nikkeiRiskFreePct", "nikkeiErpPct", "nikkeiNominalGrowthPct", "nikkeiMarketPremiumPct",
      "nikkeiMacroProfitPowerRaw", "nikkeiMacroLatestProfitRaw", "nikkeiHistoricalFairValueProxyJpy", "nikkeiHistoricalFairValueProxyLowJpy", "nikkeiHistoricalFairValueProxyHighJpy", "nikkeiHistoricalPremiumProxyPct",
    ],
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
      window.__globalComparisonPayload = payload;
      payload.seriesDefinitions.forEach(function (definition) {
        if (state.legendVisible[definition.id] == null) state.legendVisible[definition.id] = true;
      });
      var first = payload.points[0].date.slice(0, 7);
      var last = payload.points[payload.points.length - 1].date.slice(0, 7);
      if (!byId("gcCustomStart").value) byId("gcCustomStart").value = first;
      if (!byId("gcCustomEnd").value) byId("gcCustomEnd").value = last;
      renderMetadata();
      renderCoverage();
      renderValuationFocus();
      renderSources();
      renderHistoricalProxySummary();
      updateControls();
      renderChart();
      var availableSeries = payload.seriesDefinitions.filter(function (definition) {
        return payload.points.some(function (point) { return point[definition.normalizedField] != null; });
      }).length;
      status.textContent = availableSeries === 6
        ? "現行モデル2系列・日経歴史proxy・補助チャートを表示しています"
        : "実データ" + availableSeries + "系列を表示。理論価値は80%カバー率を満たす期間だけ表示";
      status.className = "gc-load-status ready";
      window.dispatchEvent(new CustomEvent("monitor:global-comparison-ready", { detail: payload }));
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
