// 자막 PNG 생성 — 브랜드 타이포로 렌더해서 ffmpeg가 오버레이한다 (폰트 이슈 없음).
import { chromium } from "playwright";
import { readFileSync, mkdirSync } from "node:fs";

const plan = JSON.parse(readFileSync("plan.json", "utf8"));
mkdirSync("subs", { recursive: true });

// pos: "bottom"(기본) | "top" — 하단에 대시보드 드로어가 뜨는 장면은 위로 올린다
const html = (text, pos = "bottom") => `<!doctype html><meta charset="utf-8"><style>
  * { margin:0; box-sizing:border-box }
  html,body { width:1600px; height:900px; background:transparent; overflow:hidden }
  body { display:flex; justify-content:center;
         align-items:${pos === "top" ? "flex-start" : "flex-end"};
         padding-${pos === "top" ? "top" : "bottom"}:${pos === "top" ? 30 : 54}px;
         font-family:-apple-system,"Apple SD Gothic Neo",sans-serif }
  .bar {
    max-width:1180px; background:rgba(255,255,255,.97); color:#17211b;
    border:1px solid #d5ddd6; border-left:5px solid #0a9e74; border-radius:12px;
    padding:16px 30px; font-size:31px; font-weight:750; letter-spacing:-.01em;
    line-height:1.45; text-align:center; box-shadow:0 12px 40px rgba(23,33,27,.18);
  }
</style><div class="bar">${text}</div>`;

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1600, height: 900 } });
let n = 0;
for (const scene of plan.scenes) {
  for (let i = 0; i < (scene.subs || []).length; i++) {
    const [, , text, pos] = scene.subs[i];
    await page.setContent(html(text, pos));
    await page.waitForTimeout(150);
    await page.screenshot({ path: `subs/${scene.id}-${i}.png`, omitBackground: true });
    n++;
  }
}
await browser.close();
console.log(`✓ 자막 ${n}장`);
