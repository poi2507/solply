import { chromium } from "playwright";
const b = await chromium.launch();
const page = await b.newPage({ viewport: { width: 1280, height: 720 }, deviceScaleFactor: 2 });
await page.goto("file:///Users/taewoong/workplace/solply/docs/pitch.html", { waitUntil: "networkidle" });
await page.waitForTimeout(1500);
const slides = await page.locator("section.slide").all();
console.log("슬라이드", slides.length, "장");
// 넘침 검사 — 내용이 720px를 넘는 슬라이드
const over = await page.evaluate(() => [...document.querySelectorAll("section.slide")]
  .map((s, i) => ({ i: i + 1, over: s.scrollHeight - s.clientHeight }))
  .filter(x => x.over > 2));
console.log("내용 넘침:", over.length ? over.map(o => `${o.i}장 +${o.over}px`).join(", ") : "없음 ✓");
for (const i of [4, 5, 10, 11, 13]) await slides[i].screenshot({ path: `qa/dk${i}.png` });
await page.pdf({ path: "/Users/taewoong/Desktop/solply-video/Solply-소개서.pdf",
                 width: "13.333in", height: "7.5in", printBackground: true });
await b.close();
