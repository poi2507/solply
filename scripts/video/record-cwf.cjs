// Colosseum(9/14~) 데모 영상 촬영기 — 라이브 화면을 녹화한다. 8월 영상(record.mjs)과 별개.
// 사용 (scripts/video/cwf 에서):  NODE_PATH=$(npm root -g) node ../record-cwf.cjs clipA clipB …
//
// 주의: solply-demo Job은 쓰지 않는다 — DB를 리셋해 대회 기간 실사용 기록이 사라진다.
// clipB는 실제 주문을 한 건 넣는다 (데모 지갑, devnet). /proof엔 팀 테스트 주문으로 집계된다.

const { chromium } = require("playwright");
const { renameSync, mkdirSync } = require("node:fs");

const API = "https://solply-api-965647250280.us-central1.run.app";
const SIZE = { width: 1600, height: 900 };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
mkdirSync("clips", { recursive: true });

let browser;
const marks = {};

async function clip(name, { role = null } = {}, run) {
  const context = await browser.newContext({
    viewport: SIZE, recordVideo: { dir: "clips", size: SIZE }, deviceScaleFactor: 1,
    timezoneId: "Asia/Seoul", locale: "en-US",
  });
  await context.addInitScript((r) => {
    try {
      localStorage.setItem("solply.lang", "en");
      if (r) localStorage.setItem("solply.role", r);
    } catch { /* 첫 페이지 전엔 저장소가 없을 수 있다 */ }
  }, role);
  const page = await context.newPage();
  const t0 = Date.now();
  const mark = (label) => { (marks[name] ||= []).push([label, ((Date.now() - t0) / 1000).toFixed(1)]); };
  try {
    await run(page, mark);
  } finally {
    const video = page.video();
    await context.close();
    if (video) { renameSync(await video.path(), `clips/${name}.webm`); console.log(`✓ ${name}.webm`, JSON.stringify(marks[name] || [])); }
  }
}

async function smoothScroll(page, px, ms) {
  await page.evaluate(async ({ px, ms }) => {
    const steps = Math.max(1, Math.floor(ms / 16));
    for (let i = 0; i < steps; i++) {
      window.scrollBy(0, px / steps);
      await new Promise((r) => setTimeout(r, ms / steps));
    }
  }, { px, ms });
}

async function scrollTo(page, selector, block = "start") {
  await page.evaluate(({ selector, block }) =>
    document.querySelector(selector)?.scrollIntoView({ behavior: "smooth", block }), { selector, block });
}

async function glow(page, selector, seconds = 3) {
  await page.evaluate(({ selector, seconds }) => {
    const el = document.querySelector(selector);
    if (!el) return;
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    el.style.transition = "box-shadow .4s";
    el.style.boxShadow = "0 0 0 3px rgba(10,158,116,.9), 0 0 26px rgba(10,158,116,.5)";
    setTimeout(() => { el.style.boxShadow = ""; }, seconds * 1000);
  }, { selector, seconds });
}

async function glowText(page, scope, text, seconds = 3) {
  return page.evaluate(({ scope, text, seconds }) => {
    const el = [...document.querySelectorAll(scope)].find((e) => e.textContent.includes(text));
    if (!el) return false;
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    el.style.transition = "box-shadow .4s";
    el.style.boxShadow = "0 0 0 3px rgba(10,158,116,.9), 0 0 26px rgba(10,158,116,.5)";
    setTimeout(() => { el.style.boxShadow = ""; }, seconds * 1000);
    return true;
  }, { scope, text, seconds });
}

// ── 장면 ────────────────────────────────────────────────────────────

// s1 — 본사 대시보드 전경: 지표 → 자금 흐름 → 청구서
async function clipA() {
  await clip("clipA", { role: "hq" }, async (page, mark) => {
    await page.goto(API + "/?lang=en", { waitUntil: "domcontentloaded" });
    await page.waitForSelector("#metrics .metric, #metrics div", { timeout: 60000 }).catch(() => {});
    await sleep(2500); mark("loaded");
    await smoothScroll(page, 520, 7000);
    await sleep(1500);
    await smoothScroll(page, 520, 7000);
    await sleep(2000); mark("end");
  });
}

// s2·s3 — 손님 주문: Store B에서 치킨 → 데모 지갑 결제 → 주문 페이지에서 에이전트 조달까지
async function clipB() {
  await clip("clipB", {}, async (page, mark) => {
    await page.goto(API + "/shop", { waitUntil: "domcontentloaded" });
    await page.waitForSelector(".sf-tab", { timeout: 60000 });
    await sleep(2500); mark("menu");
    await page.click('.sf-tab[data-store="store-b"]');
    await sleep(2000);
    await glowText(page, ".sf-item", "Seoul Fried Chicken", 3);
    await sleep(1500);
    await page.click('.sf-item [data-inc="SFC-FRIED"]');
    await sleep(2000); mark("in cart");
    await glow(page, "#cart-pay", 2);
    await sleep(1200);
    await page.click("#cart-pay"); mark("pay clicked");
    await page.waitForURL(/\/shop\/orders\//, { timeout: 120000 });
    mark("order page");
    console.log("order:", page.url());
    // 에이전트 조달이 끝날 때까지 — 주문 페이지가 스스로 갱신한다
    const t = Date.now();
    while (Date.now() - t < 150000) {
      const done = await page.evaluate(() => /Procurement finished|did not finish|failed/i.test(
        document.querySelector(".sf-steps")?.textContent || ""));
      if (done) break;
      await sleep(2000);
    }
    mark("agent done");
    await glowText(page, ".sf-steps li", "Store agent", 4);
    await sleep(4500);
    await scrollTo(page, "#live", "start");
    await sleep(6000); mark("end");
  });
}

// s4 — 공개 증빙의 판단 주체 (Jev / Gemini)
async function clipC() {
  await clip("clipC", {}, async (page, mark) => {
    await page.goto(API + "/proof", { waitUntil: "domcontentloaded" });
    await page.waitForSelector(".pf-dec li", { timeout: 60000 });
    await sleep(1500);
    const secs = await page.$$(".pf-sec");
    await secs[secs.length - 1].scrollIntoViewIfNeeded();
    await page.evaluate(() => [...document.querySelectorAll(".pf-sec")].at(-1).scrollIntoView({ behavior: "smooth", block: "start" }));
    await sleep(3000); mark("decisions");
    await glowText(page, ".pf-dec li", "Jev · System One", 4);
    await sleep(5000);
    await glowText(page, ".pf-dec li", "→ Gemini", 4);
    await sleep(6000); mark("end");
  });
}

// s5 — 점주가 정하는 한도 (지점 B 정책 화면)
async function clipD() {
  await clip("clipD", { role: "store-b" }, async (page, mark) => {
    await page.goto(API + "/?lang=en", { waitUntil: "domcontentloaded" });
    await page.waitForSelector("#policy-form", { timeout: 60000 });
    await sleep(2000);
    await scrollTo(page, "#policy", "start");
    await sleep(2500); mark("policy");
    await glow(page, 'input[name="auto_pay_limit_usdc"]', 3);
    await sleep(3500);
    await glow(page, 'input[name="min_reserve_usdc"]', 3);
    await sleep(3500);
    await glow(page, 'input[name="fast_decision_min_confidence_pct"]', 4);
    await sleep(5000); mark("end");
  });
}

// s6 — 공개 증빙: 원장 → Solana Explorer
async function clipE() {
  await clip("clipE", {}, async (page, mark) => {
    await page.goto(API + "/proof", { waitUntil: "domcontentloaded" });
    await page.waitForSelector("table.pf tbody tr", { timeout: 60000 });
    await sleep(3500); mark("top");
    await scrollTo(page, "table.pf", "center");
    await sleep(2500);
    await glow(page, "table.pf tbody tr", 4);
    await sleep(4000); mark("ledger");
    const href = await page.getAttribute("table.pf tbody tr td a[href*='explorer']", "href");
    if (href) {
      await page.goto(href, { waitUntil: "domcontentloaded" });
      await sleep(12000); mark("explorer");
    }
  });
}

// s7 — 오픈소스 solply-guard
async function clipF() {
  await clip("clipF", {}, async (page, mark) => {
    await page.goto("https://github.com/poi2507/solply/tree/main/packages/solply-guard", { waitUntil: "domcontentloaded" });
    await sleep(4000); mark("loaded");
    await page.evaluate(() => document.querySelector("article")?.scrollIntoView({ behavior: "smooth", block: "start" }));
    await sleep(3000);
    await smoothScroll(page, 700, 8000);
    await sleep(2500); mark("end");
  });
}

const CLIPS = { clipA, clipB, clipC, clipD, clipE, clipF };
(async () => {
  const targets = process.argv.slice(2);
  if (!targets.length || targets.some((t) => !CLIPS[t])) {
    console.log("usage: node record-cwf.cjs <clip…>  available:", Object.keys(CLIPS).join(" "));
    process.exit(1);
  }
  browser = await chromium.launch();
  for (const t of targets) {
    console.log(`▶ ${t}`);
    try { await CLIPS[t](); } catch (e) { console.error(`✗ ${t}:`, e.message); }
  }
  await browser.close();
})();
