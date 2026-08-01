import { chromium } from "playwright";
const b = await chromium.launch();
const page = await b.newPage({ viewport: { width: 1280, height: 720 } });
await page.goto(`file:///Users/taewoong/workplace/solply/docs/pitch.html`, { waitUntil: "networkidle" });
// 벡터 PDF (16:9)
await page.pdf({ path: "/Users/taewoong/Desktop/solply-video/Solply-소개서.pdf",
                 width: "13.333in", height: "7.5in", printBackground: true, pageRanges: "1-" });
// 새로 넣은 두 장 미리보기
const slides = await page.locator("section.slide").all();
console.log("슬라이드 수:", slides.length);
for (const [i, idx] of [9, 10].entries()) {
  await slides[idx].screenshot({ path: `qa/deck-new${i + 1}.png` });
}
await b.close();
