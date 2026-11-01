import { Browser, sleep } from "file:///C:/Users/yonat/.qoder/skills/design-taste-frontend/scripts/lib/cdp.mjs";

const url = "http://localhost:3001";
const b = await Browser.launch({ width: 1440, height: 900 });
const p = await b.newPage({ width: 1440, height: 900 });
await p.goto(url, { settleMs: 8000 });

// seed a return visit so the delta banner renders
await p.eval(() => localStorage.setItem("bmkgintel.last-visit", String(Date.now() - 2 * 3600 * 1000)));
await p.goto(url, { settleMs: 8000 });

const state = () =>
  p.eval(() => ({
    banner: document.querySelector(".deltabanner")?.textContent?.trim() ?? null,
    posture: document.querySelector(".posture")?.textContent?.trim() ?? null,
    drawer: !!document.querySelector(".drawer"),
    esc: document.querySelector(".esc-level")?.textContent?.trim() ?? null,
    seqLabel: [...document.querySelectorAll(".layerchk")].find((l) => l.textContent.includes("Sequences"))?.textContent?.trim() ?? null,
    seqLegend: [...document.querySelectorAll(".legend-item")].some((l) => l.textContent.includes("Aftershock")),
    ranked: document.querySelector(".panel-head, .section-head, .ph-count")?.textContent ?? null,
    plotted: document.querySelector(".map-title .count")?.textContent?.trim() ?? null,
    evRows: document.querySelectorAll(".evrow").length,
    detail: !!document.querySelector(".rail-detail"),
  }));

console.log("loaded", JSON.stringify(await state()));

// posture opens briefing
await p.eval(() => document.querySelector(".posture")?.click());
await sleep(2500);
console.log("posture-click", JSON.stringify(await state()));
await p.eval(() => window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" })));
await sleep(600);
console.log("briefing-closed", JSON.stringify(await state()));

// sequences toggle
await p.eval(() => {
  const label = [...document.querySelectorAll(".layerchk")].find((l) => l.textContent.includes("Sequences"));
  label?.querySelector("input")?.click();
});
await sleep(700);
console.log("seq-off", JSON.stringify(await state()));
await p.eval(() => {
  const label = [...document.querySelectorAll(".layerchk")].find((l) => l.textContent.includes("Sequences"));
  label?.querySelector("input")?.click();
});
await sleep(700);

// banner dismiss
await p.eval(() => {
  const btn = [...document.querySelectorAll(".deltabanner button")].find((x) => x.textContent.trim() === "Dismiss");
  btn?.click();
});
await sleep(400);
console.log("banner-dismissed", JSON.stringify(await state()));

// tsunami filter empties watch (regression check)
await p.eval(() => {
  const k = [...document.querySelectorAll(".kpi")].find((x) => x.textContent.includes("Tsunami"));
  k?.click();
});
await sleep(700);
console.log("tsunami-filter", JSON.stringify(await state()));
await p.eval(() => {
  const k = [...document.querySelectorAll(".kpi")].find((x) => x.textContent.includes("Tsunami"));
  k?.click();
});
await sleep(700);

// select an event -> detail rail
await p.eval(() => document.querySelector(".evrow")?.click());
await sleep(2500);
console.log("selected", JSON.stringify(await state()));

console.log("console-errors", JSON.stringify(p.consoleErrors));
await b.close();
console.log("done");
