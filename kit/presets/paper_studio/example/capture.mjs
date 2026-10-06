// Web references for the video (light mode, to sit on the paper design): sharp screenshots (2x) of public pages, top view + a tall strip for scroll moves.
//   node capture.mjs            -> assets/web/<name>.png and <name>_tall.png
import puppeteer from "puppeteer-core";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
// source material: kept in the film's own assets/web (build.py stages it into the HyperFrames project)
process.chdir(path.dirname(fileURLToPath(import.meta.url)));

const PAGES = [
  ["hyperframes_repo", "https://github.com/heygen-com/hyperframes", "light"],
  ["hyperframes_catalog", "https://hyperframes.heygen.com/catalog", "light"],
  ["awesome_list", "https://github.com/zhuyansen/awesome-claude-video-skills", "light"],
  ["ncs", "https://ncs.io/", "light"],
];
fs.mkdirSync("assets/web", { recursive: true });
const browser = await puppeteer.launch({ executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", headless: true,
  args: ["--hide-scrollbars", "--force-color-profile=srgb", "--lang=en-US"] });
for (const [name, url, scheme] of PAGES) {
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 900, deviceScaleFactor: 2 });
  await page.emulateMediaFeatures([{ name: "prefers-color-scheme", value: scheme }]);
  try {
    await page.goto(url, { waitUntil: "networkidle2", timeout: 45000 });
  } catch (e) { console.log(name, "load:", e.message); }
  await new Promise((r) => setTimeout(r, 2500));
  // decline / close cookie or consent banners if any (privacy-preserving choice)
  await page.evaluate(() => {
    const words = ["reject", "decline", "necessary only", "only necessary", "close"];
    for (const b of document.querySelectorAll("button, a")) {
      const t = (b.innerText || "").trim().toLowerCase();
      if (t && t.length < 30 && words.some((w) => t.includes(w)) && /cookie|consent|privacy/i.test(b.closest("div,section,dialog")?.innerText || "")) { b.click(); break; }
    }
  });
  await new Promise((r) => setTimeout(r, 800));
  await page.screenshot({ path: `assets/web/${name}.png` });
  const h = await page.evaluate(() => Math.min(document.documentElement.scrollHeight, 4200));
  await page.setViewport({ width: 1440, height: h, deviceScaleFactor: 2 });
  await new Promise((r) => setTimeout(r, 1200));
  await page.screenshot({ path: `assets/web/${name}_tall.png` });
  console.log(name, "ok", h);
  await page.close();
}
await browser.close();
