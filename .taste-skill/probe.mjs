import { Browser, sleep } from "file:///C:/Users/yonat/.qoder/skills/design-taste-frontend/scripts/lib/cdp.mjs";

const b = await Browser.launch({ width: 390, height: 844 });
const p = await b.newPage({ width: 390, height: 844, mobile: true });
await p.goto("http://localhost:3001", { settleMs: 7000 });

const cities = await p.eval(() =>
  [...document.querySelectorAll(".citymark")].map((e) => {
    const r = e.getBoundingClientRect();
    return {
      t: e.textContent,
      d: getComputedStyle(e).display,
      z: getComputedStyle(e).zIndex,
      x: Math.round(r.x),
      y: Math.round(r.y),
    };
  })
);
console.log("cities", JSON.stringify(cities));

// click the Tsunami alerts KPI (0) and inspect the honest empty state
const clicked = await p.eval(() => {
  const k = [...document.querySelectorAll(".kpi")].find((e) => e.textContent.includes("Tsunami"));
  if (k) k.click();
  return !!k;
});
await sleep(800);
const state = await p.eval(() => ({
  finding: document.querySelector(".finding")?.textContent,
  count: document.querySelector(".panelhead .count")?.textContent,
  empty: document.querySelector(".emptystate")?.textContent,
  kpiOn: document.querySelector(".kpi.on")?.textContent,
}));
console.log("after tsunami filter", clicked, JSON.stringify(state));
await p.screenshot({ path: "C:/Users/yonat/Documents/Personal_Project/bmkgintel/.taste-skill/after/shots/mobile-empty-filter.png", format: "png", fullPage: true });

await b.close();
