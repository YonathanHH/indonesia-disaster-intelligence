import { Browser, sleep } from "file:///C:/Users/yonat/.qoder/skills/design-taste-frontend/scripts/lib/cdp.mjs";

const url = "http://localhost:3001";
const hook = {
  source: `
    window.__an = [];
    const of = window.fetch;
    window.fetch = async (...args) => {
      const u = typeof args[0] === "string" ? args[0] : args[0].url;
      const r = await of(...args);
      if (u.includes("/analytics")) {
        const c = r.clone();
        c.json().then((j) => window.__an.push({ u, status: r.status, total: j.total_events, rows: j.daily_counts_14d })).catch((e) => window.__an.push({ u, status: r.status, err: String(e) }));
      }
      return r;
    };
  `,
};

const b = await Browser.launch({ width: 1440, height: 900 });
const desk = await b.newPage({ width: 1440, height: 900 });
await desk.goto(url, { settleMs: 8000 });
await desk.eval(() => localStorage.setItem("bmkgintel.last-visit", String(Date.now() - 2 * 3600 * 1000)));
await desk.goto(url, { settleMs: 8000 });
await desk.eval(() => {
  const row = [...document.querySelectorAll(".evrow")].find((x) => x.textContent.includes("Tanggamus"));
  if (row) row.click();
});
await sleep(3000);

const tab = await b.newPage({ width: 768, height: 1024 });
await tab.send("Page.addScriptToEvaluateOnNewDocument", hook);
await tab.goto(url, { settleMs: 10000 });
console.log("tablet", JSON.stringify(await tab.eval(() => ({
  calls: window.__an,
  trend: document.querySelector(".trend")?.getAttribute("aria-label") ?? null,
}))));
console.log("desk errors", JSON.stringify(await desk.eval(() => window.__err ?? null)));
await b.close();
console.log("done");
