import { mkdirSync } from "node:fs";
import { Browser, sleep } from "file:///C:/Users/yonat/.qoder/skills/design-taste-frontend/scripts/lib/cdp.mjs";

const out = "C:/Users/yonat/Documents/Personal_Project/bmkgintel/.taste-skill/after/shots";
mkdirSync(out, { recursive: true });
const url = "http://localhost:3001";

const b = await Browser.launch({ width: 1440, height: 900 });

// desktop: initial, selected event, briefing
const desk = await b.newPage({ width: 1440, height: 900 });
await desk.goto(url, { settleMs: 7000 });
await desk.screenshot({ path: `${out}/desk-initial.png`, format: "png" });
await desk.eval(() => {
  const row = document.querySelector(".evrow");
  if (row) row.click();
});
await sleep(2200);
await desk.screenshot({ path: `${out}/desk-detail.png`, format: "png" });
await desk.eval(() => {
  const b = [...document.querySelectorAll("button")].find((x) => x.textContent.trim() === "Briefing");
  if (b) b.click();
});
await sleep(2500);
await desk.screenshot({ path: `${out}/desk-briefing.png`, format: "png" });

// tablet
const tab = await b.newPage({ width: 768, height: 1024 });
await tab.goto(url, { settleMs: 6000 });
await tab.screenshot({ path: `${out}/tablet.png`, format: "png", fullPage: true });
await tab.eval(() => {
  const row = document.querySelector(".evrow");
  if (row) row.click();
});
await sleep(1800);
await tab.screenshot({ path: `${out}/tablet-detail.png`, format: "png" });

// mobile
const mob = await b.newPage({ width: 390, height: 844, mobile: true });
await mob.goto(url, { settleMs: 6000 });
await mob.screenshot({ path: `${out}/mobile.png`, format: "png" });
await mob.screenshot({ path: `${out}/mobile-full.png`, format: "png", fullPage: true });
await mob.eval(() => {
  const row = document.querySelector(".evrow");
  if (row) row.click();
});
await sleep(1800);
await mob.screenshot({ path: `${out}/mobile-detail.png`, format: "png" });
const overflow = await mob.eval(() => ({
  scroll: document.documentElement.scrollWidth,
  client: document.documentElement.clientWidth,
  fonts: [...new Set([...document.querySelectorAll("body *")].map((e) => getComputedStyle(e).fontFamily))],
}));
console.log("mobile", JSON.stringify(overflow));

await b.close();
console.log("done");
