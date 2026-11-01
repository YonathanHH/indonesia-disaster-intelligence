import { mkdirSync } from "node:fs";
import { Browser, sleep } from "file:///C:/Users/yonat/.qoder/skills/design-taste-frontend/scripts/lib/cdp.mjs";

const out = "C:/Users/yonat/Documents/Personal_Project/bmkgintel/.taste-skill/features";
mkdirSync(out, { recursive: true });
const url = "http://localhost:3001";

const read = () => ({
  posture: document.querySelector(".posture")?.textContent?.trim() ?? null,
  trend: document.querySelector(".trend")?.getAttribute("aria-label") ?? null,
  bars: document.querySelectorAll(".tbar").length,
  seqToggle: [...document.querySelectorAll(".layerchk")].map((l) => l.textContent?.trim()),
  legend: [...document.querySelectorAll(".legend-item")].map((l) => l.textContent?.trim()),
  banner: document.querySelector(".deltabanner")?.textContent?.trim() ?? null,
  deltaItems: [...document.querySelectorAll(".delta-item")].map((d) => d.textContent?.trim()),
});

const b = await Browser.launch({ width: 1440, height: 900 });

const desk = await b.newPage({ width: 1440, height: 900 });
await desk.goto(url, { settleMs: 8000 });
await desk.screenshot({ path: `${out}/desk-initial.png`, format: "png" });
console.log("desk initial", JSON.stringify(await desk.eval(read)));

// simulate a return visit two hours later
await desk.eval(() => localStorage.setItem("bmkgintel.last-visit", String(Date.now() - 2 * 3600 * 1000)));
await desk.goto(url, { settleMs: 8000 });
await desk.screenshot({ path: `${out}/desk-return.png`, format: "png" });
console.log("desk return", JSON.stringify(await desk.eval(read)));

// zoom into a sequence mainshock to inspect the cluster layer
await desk.eval(() => {
  const b = [...document.querySelectorAll("button")].find((x) => x.textContent.trim() === "Dismiss");
  if (b) b.click();
  const row = [...document.querySelectorAll(".evrow")].find((x) => x.textContent.includes("Tanggamus"));
  if (row) row.click();
});
await sleep(3500);
await desk.screenshot({ path: `${out}/desk-sequence.png`, format: "png" });

const tab = await b.newPage({ width: 768, height: 1024 });
await tab.send("Page.addScriptToEvaluateOnNewDocument", {
  source: `
    window.__an = [];
    const of = window.fetch;
    window.fetch = async (...args) => {
      const u = typeof args[0] === "string" ? args[0] : args[0].url;
      const r = await of(...args);
      if (u.includes("/analytics")) {
        const c = r.clone();
        c.json().then((j) => window.__an.push({ u, total: j.total_events, rows: j.daily_counts_14d })).catch(() => {});
      }
      return r;
    };
  `,
});
await tab.goto(url, { settleMs: 7000 });
await tab.screenshot({ path: `${out}/tablet.png`, format: "png", fullPage: true });
console.log("tablet", JSON.stringify({ ...(await tab.eval(read)), calls: await tab.eval(() => window.__an) }));

const mob = await b.newPage({ width: 390, height: 844, mobile: true });
await mob.goto(url, { settleMs: 4000 });
await mob.eval(() => localStorage.setItem("bmkgintel.last-visit", String(Date.now() - 2 * 3600 * 1000)));
await mob.goto(url, { settleMs: 7000 });
await mob.screenshot({ path: `${out}/mobile-return.png`, format: "png" });
await mob.screenshot({ path: `${out}/mobile-return-full.png`, format: "png", fullPage: true });
const m = await mob.eval(() => ({
  ...(() => ({
    posture: document.querySelector(".posture")?.textContent?.trim() ?? null,
    trend: document.querySelector(".trend")?.getAttribute("aria-label") ?? null,
    banner: document.querySelector(".deltabanner")?.textContent?.trim() ?? null,
  }))(),
  scroll: document.documentElement.scrollWidth,
  client: document.documentElement.clientWidth,
}));
console.log("mobile", JSON.stringify(m));

await b.close();
console.log("done");
