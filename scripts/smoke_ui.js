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
  }
  addEventListener() {}
  querySelector() { return new FakeElement(); }
  setAttribute(name, value) { this[name] = value; }
  scrollIntoView() {}
}

const indexSource = fs.readFileSync("index.html", "utf8");
const appSource = fs.readFileSync("app.js", "utf8");
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
assert.match(indexSource, /縦軸は実数（線形）です/);
assert.match(appSource, /type: "linear",\s*beginAtZero: true/);
assert.match(appSource, /名目価格指数（実数、配当なし）/);
assert.doesNotMatch(appSource, /type: "logarithmic"/);
assert.match(indexSource, /66億ドル ÷ 5,000億ドル/);
assert.match(indexSource, /＝ 1.32%/);
assert.match(indexSource, /＝ 1.43～1.71%/);
assert.match(indexSource, /両社の職員・元職員は累計約140億ドルを現金化/);
assert.match(indexSource, /Anthropicは6月1日、OpenAIは6月8日/);
assert.match(indexSource, /一般IPO 1,948社/);
assert.match(indexSource, /－12%/);
assert.match(indexSource, /売却＝弱気ではない/);
assert.match(indexSource, /未上場株の「提示価格」は、そのまま市場価格ではない/);
assert.match(indexSource, /後期の流動化・将来供給を監視する段階/);
const ids = [...indexSource.matchAll(/\bid="([^"]+)"/g)].map((match) => match[1]);
const elements = new Map(ids.map((id) => [id, new FakeElement(id)]));
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

global.document = {
  documentElement: new FakeElement("root"),
  getElementById(id) { return elements.get(id) || null; },
  querySelectorAll(selector) {
    if (selector === ".company-filter-button") return filters;
    if (selector === 'input[name="nikkeiScenario"]') return scenarios;
    return [];
  },
};
global.window = global;
global.window.innerWidth = 1280;
global.window.lucide = null;
global.getComputedStyle = () => ({ getPropertyValue: () => "#647386" });
const storage = new Map();
global.localStorage = {
  getItem(key) { return storage.has(key) ? storage.get(key) : null; },
  setItem(key, value) { storage.set(key, String(value)); },
};
const payload = JSON.parse(fs.readFileSync("data/latest.json", "utf8"));
const moneyPayload = JSON.parse(fs.readFileSync("data/money-strategist-history.json", "utf8"));
global.fetch = async (url) => ({
  ok: true,
  status: 200,
  json: async () => String(url).includes("money-strategist-history") ? moneyPayload : payload,
});

vm.runInThisContext(appSource, { filename: "app.js" });

setTimeout(() => {
  if (elements.get("dataHealth").textContent === "読込失敗") console.error("UI load error:", elements.get("uncertaintySummary").textContent);
  assert.notStrictEqual(elements.get("dataHealth").textContent, "読込失敗");
  assert.notStrictEqual(elements.get("headlineConclusion").textContent, "");
  assert.notStrictEqual(elements.get("japanTransmissionStatus").textContent, "計算中");
  assert.notStrictEqual(elements.get("nikkeiZone").textContent, "―");
  assert.match(elements.get("companyRows").innerHTML, /トヨタ自動車/);
  assert.match(elements.get("companyRows").innerHTML, /本田技研工業/);
  assert.match(elements.get("dotcomComparisonRows").innerHTML, /トヨタ自動車/);
  assert.match(elements.get("dotcomComparisonRows").innerHTML, /ソニーグループ/);
  assert.match(elements.get("dotcomComparisonRows").innerHTML, /本田技研工業/);
  assert.match(elements.get("dotcomKeyFinding").innerHTML, /最大下落中央値/);
  assert.match(elements.get("dotcomWindowBasis").innerHTML, /2000-03-10/);
  assert.notStrictEqual(elements.get("sakakibaraStage").textContent, "計算中");
  assert.match(elements.get("sakakibaraNtLatest").textContent, /倍/);
  assert.match(elements.get("sakFairRange").textContent, /円/);
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
