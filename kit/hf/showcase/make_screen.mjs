// A sample "screen recording" for the showcase: the HyperFrames repo page, light mode, 1920x1080, a slow scroll.
//   node make_screen.mjs  -> assets/screen.mp4 (real recordings come from OBS / QuickTime instead)
import puppeteer from "puppeteer-core";
const browser = await puppeteer.launch({ executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", headless: true,
  args: ["--hide-scrollbars", "--force-color-profile=srgb", "--lang=en-US", "--window-size=1920,1080"] });
const page = await browser.newPage();
await page.setViewport({ width: 1920, height: 1080, deviceScaleFactor: 1 });
await page.emulateMediaFeatures([{ name: "prefers-color-scheme", value: "light" }]);
await page.goto("https://github.com/heygen-com/hyperframes", { waitUntil: "networkidle2", timeout: 60000 });
await new Promise((r) => setTimeout(r, 2500));
const rec = await page.screencast({ path: "assets/screen.webm" });
await new Promise((r) => setTimeout(r, 6000));                       // 6 s still (annotations)
await page.evaluate(() => new Promise((res) => { const t0 = performance.now(), d = 4000, y0 = scrollY, y1 = 760;
  const f = (now) => { const p = Math.min(1, (now - t0) / d), e = p < .5 ? 2 * p * p : 1 - Math.pow(-2 * p + 2, 2) / 2; scrollTo(0, y0 + (y1 - y0) * e); p < 1 ? requestAnimationFrame(f) : res(); }; requestAnimationFrame(f); }));
await new Promise((r) => setTimeout(r, 5500));                       // 5.5 s still after the scroll
await Promise.race([rec.stop(), new Promise((r) => setTimeout(r, 8000))]);   // stop() can hang after the file is complete
await browser.close();
console.log("assets/screen.webm");
process.exit(0);
