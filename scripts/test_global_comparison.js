const fs = require("fs");
const assert = require("assert");

const payload = JSON.parse(fs.readFileSync("data/global-market-value-comparison.json", "utf8"));
const html = fs.readFileSync("index.html", "utf8");
const script = fs.readFileSync("global-comparison.js", "utf8");

assert.strictEqual(payload.seriesDefinitions.length, 6);
assert.strictEqual(payload.seriesDefinitions.filter((row) => row.market === "S&P 500").length, 3);
assert.strictEqual(payload.seriesDefinitions.filter((row) => row.market === "Nikkei 225").length, 3);
assert.strictEqual(payload.seriesDefinitions.filter((row) => row.isTheoretical).length, 2);
assert.strictEqual(payload.axis.type, "linear");
assert.strictEqual(payload.axis.min, 0);
assert.strictEqual(payload.axis.secondAxis, false);
assert.strictEqual(payload.exchangeRate.direction, "JPY_PER_USD");
assert.strictEqual(new Set(payload.seriesDefinitions.map((row) => row.color)).size, 6);
assert.ok(payload.seriesDefinitions.every((row) => /^#[0-9A-F]{6}$/i.test(row.color)));
assert.ok(100 / 150 < 100 / 100, "a weaker yen must lower USD-converted value");

const section = html.split('<section id="global-comparison"')[1].split('<section id="analysis-map"')[0];
assert.ok(section);
assert.doesNotMatch(section, /TOPIX/i);
assert.match(section, /全体表示：S&amp;P 500名目を戻す/);
assert.match(section, /理論価値2系列を非表示/);
assert.match(section, /危機期間を非表示/);
assert.match(section, /gcRefreshData/);
assert.match(section, /gcSourceList/);
assert.match(section, /gcExportPng/);
assert.match(section, /gcExportSvg/);
assert.match(section, /gcExportCsv/);
assert.match(section, /gcSpModelStatus/);
assert.match(section, /gcNkModelStatus/);
assert.match(section, /平準化EPS/);
assert.match(section, /gcSpLatestEarningsValue/);
assert.match(section, /gcNkLatestEarningsValue/);
assert.match(section, /感応度レンジ/);
assert.ok(html.indexOf('id="global-comparison"') < html.indexOf('id="analysis-map"'));

assert.match(script, /if \(value == null \|\| value === ""\) return null;/, "missing values must remain null");
assert.match(script, /showSp500Nominal: false/);
assert.match(script, /showTheoreticalValueSeries: true/);
assert.match(script, /state\.legendVisible\[definition\.id\] !== false/);
assert.match(script, /normalizationAnchorField/);
assert.match(script, /hideSp500Nominal/);
assert.match(script, /showTheoreticalValue/);
assert.match(script, /duration: 260/);
assert.match(script, /beginAtZero: true/);
assert.doesNotMatch(script, /logarithmic/);

assert.match(script, /gcEndLabels/);
assert.match(script, /lineWidthFor/);
assert.match(script, /markerStepFor/);
assert.match(script, /showSp500Nominal/);
const actual = payload.seriesDefinitions.filter((definition) =>
  payload.points.some((point) => point[definition.normalizedField] != null),
);
assert.strictEqual(actual.length, 6, "all observed and theoretical series should be available");
for (const definition of payload.seriesDefinitions.filter((row) => row.isTheoretical)) {
  assert.ok(payload.points.some((point) => point[definition.normalizedField] != null));
}

for (const model of [payload.theoreticalModels.sp500, payload.theoreticalModels.nikkei225]) {
  assert.strictEqual(model.status, "available");
  assert.strictEqual(model.methodId, "capitalized-normalized-earnings-v1");
  assert.ok(model.latest.latestEarnings > 0);
  assert.ok(model.latest.latestEarningsValue > 0);
  assert.ok(model.latest.low <= model.latest.central);
  assert.ok(model.latest.central <= model.latest.high);
}

console.log(JSON.stringify({
  series: payload.seriesDefinitions.map((row) => row.shortName),
  observations: payload.observationCount,
  baseDate: payload.baseDate,
  latestCommonMonth: payload.latestCommonMonth,
  actualSeries: actual.length,
  theoreticalStatus: payload.theoreticalModels,
}, null, 2));
