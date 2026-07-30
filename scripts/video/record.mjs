// Solply 영상 촬영기 — 대본(docs/video-script.md)의 장면을 라이브 화면에서 녹화한다.
// 사용: node record.mjs clip0a clip3a ...   (클립 단위로 재촬영 가능)

import { chromium } from "playwright";
import { rename } from "node:fs/promises";

const API = "https://solply-api-965647250280.us-central1.run.app";
const SIZE = { width: 1600, height: 900 };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

let browser;

async function clip(name, { role = null, zoom = null } = {}, run) {
  const context = await browser.newContext({
    viewport: SIZE,
    recordVideo: { dir: "clips", size: SIZE },
    deviceScaleFactor: 1,
  });
  if (role) await context.addInitScript((r) => localStorage.setItem("solply.role", r), role);
  if (zoom) await context.addInitScript((z) => {
    document.addEventListener("DOMContentLoaded", () => { document.body.style.zoom = z; });
  }, zoom);
  const page = await context.newPage();
  try {
    await run(page, context);
  } finally {
    const video = page.video();
    await context.close();
    if (video) {
      const p = await video.path();
      await rename(p, `clips/${name}.webm`);
      console.log(`✓ ${name}.webm`);
    }
  }
}

// ── 헬퍼 ─────────────────────────────────────────────────────────────

async function smoothScroll(page, px, ms) {
  await page.evaluate(async ({ px, ms }) => {
    const steps = Math.max(1, Math.floor(ms / 16));
    const per = px / steps;
    for (let i = 0; i < steps; i++) {
      window.scrollBy(0, per);
      await new Promise((r) => requestAnimationFrame(r));
      await new Promise((r) => setTimeout(r, Math.max(0, ms / steps - 16)));
    }
  }, { px, ms });
}

async function glow(page, selector, seconds = 2.5) {
  await page.evaluate(({ selector, seconds }) => {
    const el = document.querySelector(selector);
    if (!el) return;
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    el.style.transition = "box-shadow .4s";
    el.style.boxShadow = "0 0 0 3px rgba(10,158,116,.9), 0 0 26px rgba(10,158,116,.5)";
    el.style.borderRadius = getComputedStyle(el).borderRadius || "8px";
    setTimeout(() => { el.style.boxShadow = ""; }, seconds * 1000);
  }, { selector, seconds });
}

async function glowByText(page, cssScope, text, seconds = 3) {
  await page.evaluate(({ cssScope, text, seconds }) => {
    const els = [...document.querySelectorAll(cssScope)];
    const el = els.find((e) => e.textContent.includes(text));
    if (!el) return false;
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    el.style.transition = "box-shadow .4s";
    el.style.boxShadow = "0 0 0 3px rgba(10,158,116,.9), 0 0 26px rgba(10,158,116,.5)";
    setTimeout(() => { el.style.boxShadow = ""; }, seconds * 1000);
    return true;
  }, { cssScope, text, seconds });
}

async function openDashboard(page, waitSel = "#feed li, #invoices tr") {
  await page.goto(API + "/", { waitUntil: "domcontentloaded" });
  await page.waitForSelector(waitSel, { timeout: 30000 }).catch(() => {});
  await sleep(2500); // 데이터 로드 안정화
}

// ── 장면 0 — 오프닝: 쌓인 기록 ───────────────────────────────────────

async function clip0a() {
  await clip("clip0a", { role: "admin" }, async (page) => {
    await openDashboard(page, "#feed li");
    await sleep(2000);
    await smoothScroll(page, 1800, 12000);   // 실행 로그를 천천히 훑는다
    await sleep(1500);
  });
}

async function clip0b() {
  await clip("clip0b", { role: "hq" }, async (page) => {
    await openDashboard(page);
    await page.evaluate(() => document.querySelector("#trades")?.scrollIntoView({ behavior: "smooth", block: "start" }));
    await sleep(2500);
    await smoothScroll(page, 900, 7000);     // 직거래 기록 훑기
    await sleep(1500);
  });
}

// ── 장면 3 — 손님 클릭 → 에이전트 상거래 ────────────────────────────

async function clip3a() {
  await clip("clip3a", {}, async (page) => {
    await page.goto(API + "/shop", { waitUntil: "domcontentloaded" });
    await page.waitForSelector(".good button", { timeout: 30000 });
    await sleep(2500);
    // 품절 버튼이 있으면 잠깐 비춰준다
    const soldOut = page.locator("button[data-sku]:disabled").first();
    if (await soldOut.count()) {
      await soldOut.scrollIntoViewIfNeeded();
      await glow(page, "button[data-sku]:disabled", 2.5);
      await sleep(3000);
    }
    // C지점(마지막 섹션) 닭 구매 2번 — 안전선 아래로 내려 조달을 유발한다
    for (let i = 0; i < 2; i++) {
      const btn = page.locator(".shop-store").last().locator("button[data-sku]:not(:disabled)").first();
      await btn.scrollIntoViewIfNeeded();
      await sleep(800);
      await btn.click();
      await page.waitForSelector(".toast", { timeout: 15000 }).catch(() => {});
      await sleep(2600);
    }
    await sleep(2000);
  });
}

async function clip3b() {
  await clip("clip3b", { role: "admin" }, async (page) => {
    await openDashboard(page, "#feed li");
    await sleep(2000);
    // 틱을 당긴다 — 운영에선 Cloud Scheduler 몫
    fetch(API + "/api/ticks/run", { method: "POST" }).catch(() => {});
    // 피드에 조달 연쇄가 차오르는 걸 기다리며 녹화 (SSE 실시간 갱신)
    const t0 = Date.now();
    let seenQuote = false;
    while (Date.now() - t0 < 150000) {
      const txt = await page.evaluate(() => document.querySelector("#feed")?.textContent || "");
      if (!seenQuote && txt.includes("시세 데이터 구매")) {
        seenQuote = true;
        await glowByText(page, "#feed li", "시세 데이터 구매", 4);
      }
      if (txt.includes("tick.completed")) break;
      await sleep(1500);
    }
    await sleep(2000);
    if (seenQuote) { await glowByText(page, "#feed li", "시세 데이터 구매", 4); await sleep(4000); }
    console.log("  quote seen:", seenQuote);
  });
}

async function clip3c() {
  await clip("clip3c", { role: "hq", zoom: 1.25 }, async (page) => {
    await openDashboard(page);
    await page.evaluate(() => document.querySelector("#trades")?.scrollIntoView({ behavior: "smooth", block: "start" }));
    await sleep(2000);
    await glowByText(page, "#trades .row", "판단 근거", 5);
    await sleep(6000);
  });
}

async function clip3d() {
  await clip("clip3d", {}, async (page) => {
    await page.goto(API + "/shop", { waitUntil: "domcontentloaded" });
    await page.waitForSelector(".good", { timeout: 30000 });
    await page.evaluate(() => document.querySelectorAll(".shop-store")[2]?.scrollIntoView({ behavior: "smooth", block: "center" }));
    await sleep(5000);
  });
}

// ── 장면 1 — 정상 결제 (demo Job 실행 후) ───────────────────────────

async function expandById(page, invoiceId) {
  const row = page.locator(`#invoices tr[data-inv="${invoiceId}"]`).first();
  if (!(await row.count())) { console.log(`  ! ${invoiceId} 행 없음`); return null; }
  await row.scrollIntoViewIfNeeded();
  await page.evaluate(() => window.scrollBy(0, -160)); // 펼쳐질 자리를 화면에 확보
  await sleep(1000);
  await row.click();
  await sleep(3000); // 타임라인 fetch
  return row;
}

async function clip1() {
  await clip("clip1", { role: "hq" }, async (page) => {
    await openDashboard(page, "#invoices tr");
    // 경제 루프가 방금 정산한 건 — 402 왕복이 한 줄기로 보인다
    const row = await expandById(page, "INV-0730-C07") || await expandById(page, "INV-0730-C06");
    if (!row) { await sleep(3000); return; }
    await sleep(4000);
    await smoothScroll(page, 320, 3500);
    await sleep(2500);
  });
}

async function clip1b() { // Solana Explorer 실제 트랜잭션
  await clip("clip1b", { role: "hq" }, async (page) => {
    const res = await fetch(API + "/api/events?limit=60").then((r) => r.json());
    const tx = res.events.find((e) => e.payload?.tx)?.payload.tx;
    await page.goto(`https://explorer.solana.com/tx/${tx}?cluster=devnet`, { waitUntil: "domcontentloaded" });
    await sleep(7000);
    await smoothScroll(page, 400, 3000);
    await sleep(2000);
  });
}

// ── 장면 2 — 검수 분쟁 협상 (B지점 시점) ────────────────────────────

async function clip2() { // 검수 불일치 → 차감 협상 (B지점 시점)
  await clip("clip2", { role: "store-b" }, async (page) => {
    await openDashboard(page, "#invoices tr");
    if (!(await expandById(page, "INV-0729-B01"))) { await sleep(3000); return; }
    await sleep(3000);
    await glowByText(page, ".tl-step, .tl-body, li", "불일치", 4);
    await sleep(4500);
    await smoothScroll(page, 300, 4000);      // 차감 제안 → 본사 심사 → 재발행 → 결제
    await sleep(5000);
  });
}

async function clip2b() { // 본사 심사 근거 (협상 기록 패널)
  await clip("clip2b", { role: "hq", zoom: 1.25 }, async (page) => {
    await openDashboard(page);
    await glowByText(page, "#negotiations .row", "차감", 5);
    await sleep(7000);
  });
}

// ── 장면 4 — 자율성의 경계 ──────────────────────────────────────────

async function clip4a() { // C지점 잔액 부족 → 유예 제안 → 본사 수락 → 예약 → 실행
  await clip("clip4a", { role: "store-c" }, async (page) => {
    await openDashboard(page, "#invoices tr");
    if (!(await expandById(page, "INV-0729-C01"))) { await sleep(3000); return; }
    await sleep(3000);
    await glowByText(page, ".tl-step, .tl-body, li", "유예", 4);
    await sleep(5000);
    await smoothScroll(page, 300, 3500);
    await sleep(3500);
  });
}

async function clip4a2() { // 분할 역제안 (멀티턴 협상) — 본사 심사 근거
  await clip("clip4a2", { role: "hq", zoom: 1.25 }, async (page) => {
    await openDashboard(page);
    await glowByText(page, "#negotiations .row", "역제안", 5);
    await sleep(7000);
  });
}

async function clip4b() { // 발주 없는 품목 청구 → 거부 (A지점 시점)
  await clip("clip4b", { role: "store-a" }, async (page) => {
    await openDashboard(page, "#invoices tr");
    if (!(await expandById(page, "INV-0729-A02"))) { await sleep(3000); return; }
    await sleep(3000);
    await glowByText(page, ".tl-step, .tl-body, li", "거부", 4);
    await sleep(6000);
  });
}

async function clip4c() { // 어시스턴트 대화
  await clip("clip4c", { role: "hq" }, async (page) => {
    await openDashboard(page);
    await page.click("#chat-fab");
    await sleep(1200);
    await page.locator("#chat-input").pressSequentially("오늘 정산 상황 요약해줘", { delay: 70 });
    await sleep(600);
    await page.locator("#chat-form button[type=submit]").click();
    // 답변(마지막 bot 메시지)이 늘어날 때까지 대기
    const before = await page.locator("#chat-log li").count();
    const t0 = Date.now();
    while (Date.now() - t0 < 60000) {
      if ((await page.locator("#chat-log li").count()) > before + 0 &&
          (await page.locator("#chat-log li.bot").count()) >= 2) break;
      await sleep(1200);
    }
    await sleep(5000);
  });
}

// ── 장면 5 — 마무리 ────────────────────────────────────────────────

async function clip5a() { // 신용점수 + 지갑
  await clip("clip5a", { role: "hq" }, async (page) => {
    await openDashboard(page, "#stores");
    await page.evaluate(() => document.querySelector("#stores")?.scrollIntoView({ behavior: "smooth", block: "center" }));
    await sleep(5000);
  });
}

async function clip5b() {
  await clip("clip5b", { role: "admin" }, async (page) => {
    await openDashboard(page, "#wallets");
    await page.evaluate(() => document.querySelector("#wallets")?.scrollIntoView({ behavior: "smooth", block: "center" }));
    await sleep(5000);
  });
}

// ── 실행 ────────────────────────────────────────────────────────────

const CLIPS = {
  clip0a, clip0b, clip1, clip1b, clip2, clip2b,
  clip3a, clip3b, clip3c, clip3d,
  clip4a, clip4a2, clip4b, clip4c, clip5a, clip5b,
};

const targets = process.argv.slice(2);
if (!targets.length || targets.some((t) => !CLIPS[t])) {
  console.log("사용법: node record.mjs <클립…>  가능:", Object.keys(CLIPS).join(" "));
  process.exit(1);
}

browser = await chromium.launch();
for (const t of targets) {
  console.log(`▶ ${t}`);
  try { await CLIPS[t](); } catch (e) { console.error(`✗ ${t}:`, e.message); }
}
await browser.close();
