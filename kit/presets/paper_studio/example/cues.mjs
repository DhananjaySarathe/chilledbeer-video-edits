// The composition's sound cues (sfx() calls), read from the built page in headless Chrome.
//   node cues.mjs <index.html> <cues.json>      (build.py --cues passes the film's temp paths)
import puppeteer from "puppeteer-core";
import fs from "node:fs";
import path from "node:path";
const browser = await puppeteer.launch({ executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", headless: true, args: ["--allow-file-access-from-files"] });
const page = await browser.newPage();
const errs = [];
page.on("pageerror", (e) => errs.push(String(e.message || e)));
const [src = "index.html", out = "cues.json"] = process.argv.slice(2);
await page.goto("file://" + path.resolve(src), { waitUntil: "domcontentloaded" });
await page.waitForFunction(() => window.__CUES && window.__CUES.length > 0, { timeout: 30000 });
const cues = await page.evaluate(() => window.__CUES);
fs.writeFileSync(out, JSON.stringify(cues.sort((a, b) => a.at - b.at), null, 0));
console.log(cues.length, "cues", errs.length ? "ERRORS: " + [...new Set(errs)].join(" | ") : "");
await browser.close();
