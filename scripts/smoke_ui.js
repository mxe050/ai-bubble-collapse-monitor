const fs = require("fs");
const vm = require("vm");
const assert = require("assert");

class FakeClassList {
  constructor() { this.values = new Set(); }
  add(...names) { names.forEach((name) => this.values.add(name)); }
  remove(...names) { names.forEach((name) => this.values.delete(name)); }
  toggle(name, force) {
    if (force === undefined) force = !this.values.has(name);
    if (force) this.values.add(name); else this.values.delete(name);
    return force;
  }
}

class FakeElement {
  constructor(id = "") {
    this.id = id;
    this.textContent = "";
    this.innerHTML = "";
    this.value = "";
    this.checked = false;
    this.disabled = false;
    this.className = "";
    this.href = "";
    this.dataset = {};
    this.style = {};
    this.classList = new FakeClassList();
    this.listeners = {};
    this.hidden = false;
  }
  addEventListener(type, listener) {
    if (!this.listeners[type]) this.listeners[type] = [];
    this.listeners[type].push(listener);
  }
  async click() {
    for (const listener of this.listeners.click || []) await listener.call(this, { preventDefault() {} });
  }
  querySelector() { return new FakeElement(); }
  getContext() { return this; }
  setAttribute(name, value) { this[name] = value; }
  scrollIntoView() {}
}

const indexSource = fs.readFileSync("index.html", "utf8");
const appSource = fs.readFileSync("app.js", "utf8");
const chartVendorSource = fs.readFileSync("vendor/chart.umd.min.js", "utf8");
const lucideVendorSource = fs.readFileSync("vendor/lucide.min.js", "utf8");
assert.match(indexSource, /Option-Adjusted Spread/);
assert.match(indexSource, /新規借入で実際に支払う金利そのものでも、倒産確率そのものでもありません/);
assert.match(indexSource, /VIX上昇に加え、OASが拡大/);
assert.match(indexSource, /SOXで最適化した予測値ではありません/);
assert.match(indexSource, /1社で比率が12.5ポイント/);
assert.match(indexSource, /一人の論者の入力を再現した参考シナリオ/);
assert.match(indexSource, /逆DCFとは/);
assert.match(indexSource, /研究結果の当てはめには限界があります/);
assert.match(indexSource, /1957年3月4日以降とは、データの性格が異なります/);
assert.match(indexSource, /青線はMoney Strategistが公表した正式なS&amp;P 500予測線ではありません/);
assert.match(indexSource, /左軸は米国株の名目価格指数を0から描く実数（線形）目盛/);
assert.match(appSource, /type: "linear",\s*beginAtZero: true/);
assert.match(appSource, /米国株の名目価格指数（実数、配当なし）/);
assert.match(appSource, /yCpi/);
assert.match(indexSource, /米国CPI-Uは橙/);
assert.match(indexSource, /<h2 id="beginnerGuideHeading">本日のまとめ<\/h2>/);
assert.match(indexSource, /id="dailySummaryList"/);
assert.match(indexSource, /直近2回の決算だけでつくる「冷静な株価」/);
assert.doesNotMatch(indexSource, /参考資料の2026年7月18日付「市況展望」の着眼点を、別の日にも再現できるよう定量化しました。/);
assert.match(appSource, /cycle: \{ min: 2026\.00, max: 2028\.99 \}/);
assert.match(indexSource, /CPI 333.952は、平均価格333.952ドルという意味ではありません/);
assert.match(indexSource, /data-ms-range="cycle"/);
assert.match(indexSource, /次回大統領選までの「値動きを確認する日」/);
assert.match(appSource, /典型的な180日ロックアップ/);
assert.doesNotMatch(appSource, /type: "logarithmic"/);
assert.match(indexSource, /未上場AI企業で株式の現金化が進んだ。次に見るのは価格・供給・業績/);
assert.match(indexSource, /数字を足さない/);
assert.match(indexSource, /異なる条件の取引額を、一つの売り圧力に見せない/);
assert.match(indexSource, /評価額比1.32%は規模感の参考/);
assert.match(indexSource, /買い手側の上限であり、実際の成立額ではありません/);
assert.match(indexSource, /Anthropicは6月1日、OpenAIは6月8日/);
assert.match(indexSource, /一般IPO 1,948社/);
assert.match(indexSource, /－12%/);
assert.match(indexSource, /未上場株の「提示価格」は、そのまま市場価格ではない/);
assert.match(indexSource, /各社の次回取引価格、売却希望額、買い手の引受余力、IPO時の既存株主売出を個別に追います。/);
assert.doesNotMatch(indexSource, /職員はすでに株を売っている/);
assert.doesNotMatch(indexSource, /両社の職員・元職員は累計約140億ドルを現金化/);
assert.match(indexSource, /Margin Debt \/ GDP/);
assert.match(indexSource, /燃料、引き金、巻き戻し/);
assert.match(indexSource, /ニフティ・フィフティ/);
assert.match(indexSource, /ITバブル、住宅・信用バブル、VIXショック前/);
assert.match(appSource, /event\.chartLabel/);
assert.match(indexSource, /FINRA配布Excelを直接取得/);
assert.match(indexSource, /FINRA信用買い残は「米国の一般個人の借金総額」ではない/);
assert.match(indexSource, /全会員会社が一律に残高を報告する意味ではありません/);
assert.match(indexSource, /総額から利用者数や平均借入額は逆算できない/);
assert.match(indexSource, /ヘッジや複合戦略も混ざり得る/);
assert.match(indexSource, /FRBは家計調査から2022年のmargin loansを約1,794億ドル/);
assert.match(indexSource, /元データが画面の数字になるまで/);
assert.match(indexSource, /主要データごとの取得経路/);
assert.match(indexSource, /FREDのCSVを系列IDごとに直接取得/);
assert.match(indexSource, /SEC EDGAR submissions JSON/);
assert.match(indexSource, /半導体株の反発だけでは、構造的な底を証明しない/);
assert.match(indexSource, /1\.1228兆ウォン/);
assert.match(indexSource, /昨日との比較/);
assert.match(indexSource, /1週間前との比較/);
assert.match(indexSource, /1か月前との比較/);
assert.match(indexSource, /S&amp;P 500 ÷ 金/);
assert.match(indexSource, /金27%、米国債22%/);
assert.match(indexSource, /動画の結論を崩壊スコアへ直接加点しません/);
assert.match(indexSource, /src="vendor\/chart\.umd\.min\.js"/);
assert.match(indexSource, /src="vendor\/lucide\.min\.js"/);
assert.match(indexSource, /class="purchasing-power-chart-stage"/);
assert.doesNotMatch(indexSource, /cdn\.jsdelivr\.net\/npm\/chart\.js/);
assert.match(chartVendorSource, /Chart\.js v4\.4\.9/);
assert.match(lucideVendorSource, /lucide v0\.468\.0/);
assert.match(indexSource, /なぜ「Margin Debt \/ GDP」を調べるのか/);
assert.match(indexSource, /担保が不足すると、待ちたくても売らなければならない/);
assert.match(indexSource, /返済能力そのものではなく長期比較のための物差し/);
assert.match(indexSource, /CAPE Ratio.*過去10年の物価調整後利益の平均/);
assert.match(indexSource, /設備投資額を表すCapExとは別物/);
assert.match(indexSource, /略語・専門用語ガイド/);
assert.match(indexSource, /景気循環調整後の株価収益率/);
assert.match(indexSource, /Capital Expenditure/);
assert.match(indexSource, /フリーキャッシュフロー/);
assert.match(indexSource, /将来現金の割引現在価値/);
assert.match(indexSource, /米国株の30日予想変動率/);
assert.match(indexSource, /低格付け社債の信用スプレッド/);
assert.match(indexSource, /米機関投資家の四半期保有報告/);
assert.match(indexSource, /米国IPOの登録届出書/);
assert.match(indexSource, /CSV \/ JSON \/ XML/);
assert.match(indexSource, /北米証券の識別コード/);
assert.match(indexSource, /JST・日本標準時/);
assert.match(indexSource, /本日のマーケットサマリー/);
assert.match(indexSource, /日本、米国、欧州、中国、世界全体/);
assert.match(indexSource, /regionalMarketCards/);
assert.ok(indexSource.indexOf('id="market-summary"') < indexSource.indexOf('id="beginner-guide"'));
assert.match(indexSource, /どこを見れば、何が分かるか/);
assert.match(indexSource, /currentSectionLabel/);
assert.match(indexSource, /暴落前に重なる4条件を、現在のデータへ置き換える/);
assert.match(indexSource, /すべての暴落に必ず同じ形でそろうと証明された法則ではありません/);
assert.match(indexSource, /動画の「40%超」と基準日は一致しません/);
assert.match(indexSource, /同じ借り手の「追証までの余裕」ではありません/);
assert.match(indexSource, /代表性のある投資家調査、予測市場、ポジション統計は示していません/);
assert.match(indexSource, /CAPE 42から21への低下は価格約50%下/);
assert.match(indexSource, /FSB・プライベートクレジット脆弱性報告/);
assert.match(indexSource, /最近のAI相場を見てから、突然始めた現金化ではない/);
assert.match(indexSource, /一次資料で確認できること/);
assert.doesNotMatch(indexSource, /動画群/);
const requiredUiIds = [
  "dotcomDividendCase",
  "dotcomComparisonCards",
  "dotcomStressWarning",
];
requiredUiIds.forEach((id) => {
  assert.match(indexSource, new RegExp(`\\bid="${id}"`), `index.html should define #${id}`);
});
const ids = [...indexSource.matchAll(/\bid="([^"]+)"/g)].map((match) => match[1]);
const elements = new Map([...new Set([...ids, ...requiredUiIds])].map((id) => [id, new FakeElement(id)]));
const filters = ["all", "overseas-ai", "japan-ai", "japan-diversified"].map((value) => {
  const element = new FakeElement();
  element.dataset.companyFilter = value;
  return element;
});
const scenarios = ["mild", "standard", "severe"].map((value) => {
  const element = new FakeElement();
  element.value = value;
  element.checked = value === "standard";
  return element;
});
const snapshotButtons = [1, 7, 30].map((value) => {
  const element = new FakeElement();
  element.dataset.compareDays = String(value);
  return element;
});
const moneyRangeButtons = ["all", "postwar", "modern", "current", "cycle"].map((value) => {
  const element = new FakeElement();
  element.dataset.msRange = value;
  return element;
});

global.document = {
  documentElement: new FakeElement("root"),
  getElementById(id) { return elements.get(id) || null; },
  querySelectorAll(selector) {
    if (selector === ".company-filter-button") return filters;
    if (selector === ".snapshot-compare-button") return snapshotButtons;
    if (selector === ".ms-range-button") return moneyRangeButtons;
    if (selector === 'input[name="nikkeiScenario"]') return scenarios;
    return [];
  },
};
global.window = global;
global.window.innerWidth = 1280;
global.window.lucide = null;
const renderedCharts = [];
class FakeChart {
  constructor(target, config) {
    this.target = target;
    this.config = config;
    this.data = config.data;
    renderedCharts.push(this);
  }
  destroy() {}
}
global.Chart = FakeChart;
global.window.Chart = FakeChart;
global.getComputedStyle = () => ({ getPropertyValue: () => "#647386" });
const storage = new Map();
global.localStorage = {
  getItem(key) { return storage.has(key) ? storage.get(key) : null; },
  setItem(key, value) { storage.set(key, String(value)); },
};
const payload = JSON.parse(fs.readFileSync("data/latest.json", "utf8"));
const moneyPayload = JSON.parse(fs.readFileSync("data/money-strategist-history.json", "utf8"));
const marginPayload = JSON.parse(fs.readFileSync("data/margin-debt-history.json", "utf8"));
const globalComparisonPayload = JSON.parse(fs.readFileSync("data/global-market-value-comparison.json", "utf8"));
const snapshotIndexPayload = JSON.parse(fs.readFileSync("data/history/index.json", "utf8"));
const marketSummaryPayload = JSON.parse(fs.readFileSync("data/market-summary.json", "utf8"));
const snapshotPayloads = Object.fromEntries((snapshotIndexPayload.snapshots || []).map((entry) => [
  entry.file,
  JSON.parse(fs.readFileSync("data/history/" + entry.file, "utf8")),
]));
global.fetch = async (url) => ({
  ok: true,
  status: 200,
  json: async () => {
    const requested = String(url);
    if (requested.includes("data/history/index.json")) return snapshotIndexPayload;
    if (requested.includes("data/market-summary.json")) return marketSummaryPayload;
    const snapshotMatch = requested.match(/data\/history\/([^?]+)/);
    if (snapshotMatch && snapshotPayloads[snapshotMatch[1]]) return snapshotPayloads[snapshotMatch[1]];
    if (requested.includes("money-strategist-history")) return moneyPayload;
    if (requested.includes("margin-debt-history")) return marginPayload;
    if (requested.includes("global-market-value-comparison")) return globalComparisonPayload;
    return payload;
  },
});

vm.runInThisContext(appSource, { filename: "app.js" });

setTimeout(async () => {
  if (elements.get("dataHealth").textContent === "読込失敗") console.error("UI load error:", elements.get("uncertaintySummary").textContent);
  assert.notStrictEqual(elements.get("dataHealth").textContent, "読込失敗");
  assert.notStrictEqual(elements.get("headlineConclusion").textContent, "");
  assert.match(elements.get("dailySummaryLead").textContent, /パニック崩壊は未確認/);
  assert.strictEqual((elements.get("dailySummaryList").innerHTML.match(/<li>/g) || []).length, 10);
  assert.match(elements.get("dailySummaryList").innerHTML, /S&amp;P 500|S&P 500/);
  assert.match(elements.get("dailySummaryList").innerHTML, /キオクシア/);
  assert.match(elements.get("regionalMarketCards").innerHTML, /日本/);
  assert.match(elements.get("regionalMarketCards").innerHTML, /EU・欧州/);
  assert.match(elements.get("regionalMarketCards").innerHTML, /オールカントリー/);
  assert.notStrictEqual(elements.get("japanTransmissionStatus").textContent, "計算中");
  assert.notStrictEqual(elements.get("nikkeiZone").textContent, "―");
  assert.match(elements.get("companyRows").innerHTML, /トヨタ自動車/);
  assert.match(elements.get("companyRows").innerHTML, /本田技研工業/);
  assert.match(elements.get("dotcomComparisonRows").innerHTML, /トヨタ自動車/);
  assert.match(elements.get("dotcomComparisonRows").innerHTML, /ソニーグループ/);
  assert.match(elements.get("dotcomComparisonRows").innerHTML, /本田技研工業/);
  assert.match(elements.get("dotcomKeyFinding").innerHTML, /最大下落中央値/);
  assert.match(elements.get("dotcomWindowBasis").innerHTML, /2000-03-10/);
  const dotcomComparisonData = payload.market && payload.market.dotComComparison;
  assert.ok(dotcomComparisonData, "dotcom comparison data should be present");
  const dividendContinuityCase = dotcomComparisonData.dividendContinuityCase || {};
  const dividendEvidence = dividendContinuityCase.selectionEvidence || {};
  const dividendStress = dividendContinuityCase.stressScenario || {};
  const expectedPpihName = "\u30d1\u30f3\u30fb\u30d1\u30b7\u30d5\u30a3\u30c3\u30af\u30fb\u30a4\u30f3\u30bf\u30fc\u30ca\u30b7\u30e7\u30ca\u30eb\u30db\u30fc\u30eb\u30c7\u30a3\u30f3\u30b0\u30b9";
  const expectedPrimeMarket = "\u6771\u8a3c\u30d7\u30e9\u30a4\u30e0";
  assert.strictEqual(dividendContinuityCase.name, expectedPpihName);
  assert.strictEqual(Number(dividendEvidence.dividendFiscalYearCount), 22);
  assert.ok(Number.isFinite(Number(dividendStress.currentClose)), "PPIH current close should be numeric");
  assert.ok(Number.isFinite(Number(dividendStress.stressPrice)), "PPIH stress price should be numeric");
  const formatDotcomSmokeQuote = (value, unit) => {
    const numeric = Number(value);
    const formatted = Math.abs(numeric) < 1000 && Math.abs(numeric % 1) > 0.001
      ? new Intl.NumberFormat("ja-JP", { maximumFractionDigits: 1 }).format(numeric)
      : new Intl.NumberFormat("ja-JP", { maximumFractionDigits: 0 }).format(Math.round(numeric));
    return formatted + (unit === "\u5186" ? "\u5186" : " pt");
  };
  const dividendCaseMarkup = elements.get("dotcomDividendCase").innerHTML + " " + elements.get("dotcomDividendCase").textContent;
  assert.ok(dividendCaseMarkup.includes(expectedPpihName));
  assert.ok(dividendCaseMarkup.includes(expectedPrimeMarket));
  assert.match(dividendCaseMarkup, /22\u671f\u3067\u7121\u914d\u306a\u3057/);
  assert.match(dividendCaseMarkup, /22\u671f\u9023\u7d9a\u5897\u914d/);
  assert.match(dividendCaseMarkup, /\u53d6\u5f97\u3067\u304d\u305f\u76f4\u8fd1\u7d42\u5024/);
  assert.ok(dividendCaseMarkup.includes(formatDotcomSmokeQuote(dividendStress.currentClose, dividendStress.quoteUnit)));
  assert.match(dividendCaseMarkup, /\u6a5f\u68b0\u7684\u30b9\u30c8\u30ec\u30b9\u63db\u7b97\u5024/);
  assert.ok(dividendCaseMarkup.includes(formatDotcomSmokeQuote(dividendStress.stressPrice, dividendStress.quoteUnit)));
  assert.match(dividendCaseMarkup, /dotcom-nonforecast/);
  const stressWarningMarkup = elements.get("dotcomStressWarning").textContent + " " + elements.get("dotcomStressWarning").innerHTML;
  assert.match(stressWarningMarkup, /\u4e88\u6e2c\u682a\u4fa1/);
  assert.match(stressWarningMarkup, /\u76ee\u6a19\u682a\u4fa1/);
  assert.match(stressWarningMarkup, /\u9069\u6b63\u5024/);
  assert.match(stressWarningMarkup, /\u5e95\u5024/);
  assert.match(stressWarningMarkup, /\u5d29\u58ca\u30b9\u30b3\u30a2.*\u52a0\u7b97\u3057\u306a\u3044/);
  const dotcomCardMarkup = elements.get("dotcomComparisonCards").innerHTML;
  assert.strictEqual((dotcomCardMarkup.match(/<article class=['"]dotcom-company-card\b/g) || []).length, 12);
  assert.strictEqual((elements.get("dotcomComparisonRows").innerHTML.match(/<tr\b/g) || []).length, 12);
  assert.notStrictEqual(elements.get("sakakibaraStage").textContent, "計算中");
  assert.match(elements.get("sakakibaraNtLatest").textContent, /倍/);
  assert.match(elements.get("sakFairRange").textContent, /円/);
  assert.match(elements.get("sakKioxiaCalmPrice").textContent, /￥17,911/);
  assert.match(elements.get("sakKioxiaCalmRange").textContent, /￥14,329.*￥21,494/);
  assert.match(elements.get("sakKioxiaCalmFormula").textContent, /2\.34兆円/);
  assert.match(elements.get("sakKioxiaCalmGap").textContent, /約2\.21倍/);
  assert.match(elements.get("sakKioxiaCalmInterpretation").textContent, /目標株価、底値ではありません/);
  assert.match(elements.get("sakKioxiaQ3Source").href, /2757397/);
  assert.match(elements.get("sakKioxiaFySource").href, /2815552/);
  assert.match(elements.get("enAiProxyRows").innerHTML, /トヨタ自動車/);
  assert.match(elements.get("enAiProxyInterpretation").textContent, /代理上位/);
  assert.match(elements.get("marketPathLabel").textContent, /正常化|パニック|分岐|歪み/);
  assert.match(elements.get("marketPathIndex").textContent, /[+−-]?\d|未確認/);
  assert.match(elements.get("marketPathNormalizationComponents").innerHTML, /NT倍率/);
  assert.match(elements.get("marketPathPanicComponents").innerHTML, /VIX|予想変動率/);
  assert.match(elements.get("marketPathInterpretation").innerHTML, /パニック|約6万円/);
  assert.match(elements.get("thresholdVixBasis").textContent, /標本内P/);
  assert.match(elements.get("thresholdOasBasis").textContent, /標本内P/);
  assert.match(elements.get("thresholdVixBasis").textContent, /20年/);
  assert.match(elements.get("thresholdOasBasis").textContent, /直近3年/);
  assert.match(elements.get("thresholdOasBasis").textContent, /標本上限超過/);
  assert.match(elements.get("thresholdBasketBasis").textContent, /1社=12\.5ポイント/);
  assert.match(elements.get("msCurrentLevel").textContent, /pt/);
  assert.match(elements.get("msMidtermMean").textContent, /17\.5/);
  assert.match(elements.get("msTop10Weight").textContent, /36\.4/);
  assert.match(elements.get("msNyFedProbability").textContent, /16\.1/);
  assert.match(elements.get("msChartLimit").textContent, /正式予測線ではない/);
  assert.match(elements.get("msCpiLatest").textContent, /333.952/);
  assert.match(elements.get("msCpiMultiple").textContent, /倍/);
  assert.match(elements.get("msStockMultiple").textContent, /倍/);
  assert.match(elements.get("msRealStockMultiple").textContent, /倍/);
  assert.match(elements.get("msCalendarSummary").innerHTML, /2026年/);
  assert.match(elements.get("msCalendarSummary").innerHTML, /2028年/);
  await moneyRangeButtons.find((button) => button.dataset.msRange === "cycle").click();
  const cycleChart = [...renderedCharts].reverse().find((chart) => chart.target.id === "moneyStrategistChart");
  assert.ok(cycleChart, "cycle chart should be constructed");
  assert.strictEqual(cycleChart.config.options.scales.x.min, 2026);
  assert.strictEqual(cycleChart.config.options.scales.x.ticks.callback(2026), "2026");
  assert.match(elements.get("marginDebtLatest").textContent, /兆/);
  assert.match(elements.get("marginDebtRatio").textContent, /%/);
  assert.match(elements.get("crashLensValuationStatus").textContent, /CAPE Ratio 41\.64/);
  assert.match(elements.get("crashLensValuationStatus").textContent, /上位10社 36\.4%/);
  assert.match(elements.get("crashLensLeverageStatus").textContent, /信用買い残/);
  assert.match(elements.get("crashLensLeverageStatus").textContent, /GDP比/);
  assert.match(elements.get("crashLensConfirmationStatus").textContent, /崩壊確認/);
  assert.match(elements.get("crashLensConfirmationStatus").textContent, /ゲートA/);
  assert.notStrictEqual(elements.get("marginDebtStatus").textContent, "計算中");
  assert.match(elements.get("marginDebtEventList").innerHTML, /2000年3月/);
  assert.match(elements.get("marginDebtSourceRegime").innerHTML, /FINRA・報告対象会員会社集計/);
  assert.match(elements.get("marginDebtRawInput").textContent, /百万ドル/);
  assert.match(elements.get("marginGdpRawInput").textContent, /十億ドル/);
  assert.match(elements.get("marginWorkedFormula").textContent, /× 1,000/);
  assert.match(elements.get("marginWorkedFormula").textContent, /%/);
  assert.match(elements.get("sourceStatusList").innerHTML, /最終取得/);
  assert.match(elements.get("sourceStatusList").innerHTML, /対象:/);
  assert.notStrictEqual(elements.get("bottomBusinessConclusion").textContent, "価格反発と事業面の裏付けを分けて判定しています。");
  assert.match(elements.get("ppStatus").textContent, /名目|判定/);
  assert.match(elements.get("ppGold").textContent, /\$/);
  assert.match(elements.get("ppPolicySpread").textContent, /ポイント/);
  assert.match(elements.get("berkshireNetSellerQuarters").textContent, /14四半期連続/);
  assert.match(elements.get("berkshireCumulativeNetSales").textContent, /\$194\.8B/);
  assert.match(elements.get("berkshireAcceleration").textContent, /2024年/);
  assert.match(elements.get("berkshireNetSellingTimeline").innerHTML, /2022年10–12月期/);
  assert.match(elements.get("berkshireNetSellingTimeline").innerHTML, /2026年1–3月期/);
  assert.match(elements.get("berkshireContextCaution").textContent, /AIバブル崩壊を予測/);
  assert.match(elements.get("berkshireContextCaution").textContent, /崩壊スコアへ加えません/);
  assert.match(elements.get("berkshireContextCaution").textContent, /Finance Bureau/);
  assert.match(elements.get("berkshireScopeNote").textContent, /\$397\.4B/);
  assert.match(elements.get("berkshireCommentatorSource").textContent, /Finance Bureauの解説/);
  assert.match(elements.get("berkshireCommentatorSource").href, /Y8fJNR_xsnI/);
  assert.match(elements.get("berkshireContextSources").innerHTML, /Finance Bureau/);
  const purchasingPowerRender = renderedCharts.find((chart) => chart.target.id === "purchasingPowerChart");
  assert.ok(purchasingPowerRender, "purchasing power chart should be constructed");
  assert.strictEqual(purchasingPowerRender.data.labels.length, 252);
  assert.strictEqual(purchasingPowerRender.data.datasets.length, 3);
  purchasingPowerRender.data.datasets.forEach((dataset) => assert.strictEqual(dataset.data.length, 252));
  assert.strictEqual(snapshotButtons[0].disabled, true);
  assert.strictEqual(snapshotButtons[1].disabled, false);
  assert.strictEqual(snapshotButtons[2].disabled, true);
  await snapshotButtons[1].click();
  assert.match(elements.get("snapshotComparisonHeading").textContent, /1週間前.*2026-07-22/);
  assert.match(elements.get("snapshotComparisonGrid").innerHTML, /S&amp;P 500|S&P 500/);
  assert.match(elements.get("snapshotComparisonNote").textContent, /当時公表値/);
  console.log(JSON.stringify({
    headline: elements.get("headlineConclusion").textContent,
    transmission: elements.get("japanTransmissionStatus").textContent,
    nikkeiZone: elements.get("nikkeiZone").textContent,
    dotcomRows: (elements.get("dotcomComparisonRows").innerHTML.match(/<tr/g) || []).length,
    sakakibara: elements.get("sakakibaraStage").textContent,
    ntRatio: elements.get("sakakibaraNtLatest").textContent,
    marketPath: elements.get("marketPathLabel").textContent,
    marketPathIndex: elements.get("marketPathIndex").textContent,
    panicScore: elements.get("marketPathPanicScore").textContent,
    enAiRows: (elements.get("enAiProxyRows").innerHTML.match(/<tr/g) || []).length,
    moneyStrategist: elements.get("msCurrentLevel").textContent,
    health: elements.get("dataHealth").textContent,
  }, null, 2));
}, 50);
