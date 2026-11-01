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
        c.json().then((j) => window.__an.push({
          u, status: r.status, total: j.total_events,
          days: j.daily_counts_14d && j.daily_counts_14d.length,
          today: j.daily_counts_14d && j.daily_counts_14d.at(-1),
          has: !!(j.daily_counts_14d && j.daily_counts_14d.length),
        })).catch((e) => window.__an.push({ u, status: r.status, err: String(e) }));
      }
      return r;
    };
  `,
};

const b = await Browser.launch({ width: 1440, height: 900 });
for (const [label, w, h] of [["desk", 1440, 900], ["tablet", 768, 1024]]) {
  const p = await b.newPage({ width: w, height: h });
  await p.send("Page.addScriptToEvaluateOnNewDocument", hook);
  await p.goto(url, { settleMs: 10000 });
  const out = await p.eval(() => ({
    calls: window.__an,
    trend: document.querySelector(".trend")?.getAttribute("aria-label") ?? null,
    errors: window.__err ?? null,
  }));
  console.log(label, JSON.stringify(out));
}
await b.close();
console.log("done");
