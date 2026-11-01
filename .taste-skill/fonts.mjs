import { Browser } from "file:///C:/Users/yonat/.qoder/skills/design-taste-frontend/scripts/lib/cdp.mjs";

const b = await Browser.launch({ width: 1440, height: 900 });
const p = await b.newPage({ width: 1440, height: 900 });
await p.goto("http://localhost:3001", { settleMs: 6000 });
const hits = await p.eval(() => {
  const out = [];
  for (const e of document.querySelectorAll("body, body *")) {
    const f = getComputedStyle(e).fontFamily;
    if (/Helvetica|Arial/.test(f)) {
      out.push({ tag: e.tagName, cls: e.className?.toString().slice(0, 60), f: f.slice(0, 50), text: (e.textContent || "").trim().slice(0, 40) });
    }
  }
  return out.slice(0, 20);
});
console.log(JSON.stringify(hits, null, 2));
await b.close();
