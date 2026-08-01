import { chromium } from "playwright";
const API = "https://solply-api-965647250280.us-central1.run.app";
const b = await chromium.launch();
const sleep = (ms) => new Promise(r => setTimeout(r, ms));

async function page(role, w = 1600, h = 1000) {
  const ctx = await b.newContext({ viewport: { width: w, height: h }, deviceScaleFactor: 2, timezoneId: "Asia/Seoul" });
  if (role) await ctx.addInitScript((r) => localStorage.setItem("solply.role", r), role);
  const p = await ctx.newPage();
  await p.goto(API + "/", { waitUntil: "domcontentloaded" });
  await p.waitForSelector("#invoices tr[data-inv], #feed li .t", { timeout: 40000 }).catch(() => {});
  await sleep(3500);
  return p;
}

// ① 본사 대시보드 전경 — 지표 + 가맹점 카드
let p = await page("hq");
await p.screenshot({ path: "shots/01-dashboard.png", clip: { x: 180, y: 0, width: 1240, height: 700 } });
console.log("✓ 01 대시보드");

// ② 청구서 타임라인 — 협상 과정
const row = p.locator('#invoices tr[data-inv]').filter({ hasText: "→" }).first();
if (await row.count()) { await row.scrollIntoViewIfNeeded(); await sleep(600); await row.click(); await sleep(3000);
  const det = p.locator("tr.detail").first();
  await det.screenshot({ path: "shots/02-timeline.png" }); console.log("✓ 02 협상 타임라인");
} else { console.log("! 정정된 청구서 없음"); }

// ③ 직거래 카드 — 판단 근거(pay.sh)
await p.evaluate(() => document.querySelector("#trades")?.scrollIntoView({ block: "start" }));
await sleep(1200);
await p.locator("#trades").screenshot({ path: "shots/03-trades.png" });
console.log("✓ 03 직거래");
await p.context().close();

// ④ 실행 로그 — 한국어 라벨 + tx
p = await page("admin");
await p.evaluate(() => document.querySelector("#feed")?.scrollIntoView({ block: "start" }));
await sleep(1200);
await p.locator("#feed").screenshot({ path: "shots/04-log.png" });
console.log("✓ 04 실행 로그");
await p.context().close();

// ⑤ 손님 페이지
const ctx = await b.newContext({ viewport: { width: 1400, height: 900 }, deviceScaleFactor: 2 });
const sp = await ctx.newPage();
await sp.goto(API + "/shop", { waitUntil: "domcontentloaded" });
await sp.waitForSelector(".good", { timeout: 30000 }); await sleep(2500);
await sp.screenshot({ path: "shots/05-shop.png", clip: { x: 0, y: 0, width: 1400, height: 760 } });
console.log("✓ 05 손님 페이지");
await ctx.close();
await b.close();
