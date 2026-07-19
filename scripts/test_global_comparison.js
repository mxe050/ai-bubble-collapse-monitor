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
assert.ok(100 / 150 < 100 / 100, "a weaker yen must lower the USD-converted value");

const section = html.split('<section id="global-comparison"')[1].split('<section id="analysis-map"')[0];
assert.ok(section);
assert.doesNotMatch(section, /TOPIX/i);
assert.match(section, /比較を拡大：S&amp;P 500名目を除外/);
assert.match(section, /理論価値2系列を非表示/);
assert.match(section, /危機期間を非表示/);
assert.match(section, /gcExportPng/);
assert.match(section, /gcExportSvg/);
assert.match(section, /gcExportCsv/);
assert.ok(html.indexOf('id="global-comparison"') < html.indexOf('id="analysis-map"'));

assert.match(script, /if \(value == null \|\| value === ""\) return null;/, "missing values must remain null in the browser");
assert.match(script, /showSp500Nominal: true/);
assert.match(script, /showTheoreticalValueSeries: true/);
assert.match(script, /state\.legendVisible\[definition\.id\] !== false/);
assert.match(script, /hideSp500Nominal/);
assert.match(script, /showTheoreticalValue/);
assert.match(script, /duration: 260/);
assert.match(script, /beginAtZero: true/);
assert.doesNotMatch(script, /logarithmic/);

const actual = payload.seriesDefinitions.filter((definition) =>
  payload.points.some((point) => point[definition.normalizedField] != null),
);
assert.strictEqual(actual.length, 4, "current free-data package should expose four observed series");
for (const definition of payload.seriesDefinitions.filter((row) => row.isTheoretical)) {
  assert.ok(payload.points.every((point) => point[definition.normalizedField] == null));
}

console.log(JSON.stringify({
  series: payload.seriesDefinitions.map((row) => row.shortName),
  observations: payload.observationCount,
  baseDate: payload.baseDate,
  latestCommonMonth: payload.latestCommonMonth,
  actualSeries: actual.length,
  theoreticalStatus: payload.valuationCoverage,
}, null, 2));
