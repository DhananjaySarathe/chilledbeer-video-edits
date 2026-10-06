// Render HTML scene pages to video files in parallel with the installed Google Chrome.
// One page per Chrome process: tabs inside one Chrome are throttled, while separate processes
// scaled 5.7x on the owner's 8 performance cores (138 fps at 1080x1920, measured 2026-09-26).
//
// stdin: {"chrome", "ffmpeg", "workers", "width"?, "height"?, "scale"?,
//         "scenes": [{"id", "html", "frames", "fps", "alpha", "out", "from"?, "to"?, "check_at"?, "enc"?}]}
// width/height default to the 1080x1920 short; scale is the device pixel ratio; enc overrides the ffmpeg encoder args.
// A scene may be a frame range [from, to) of a longer scene (frames are independent, so ranges render in parallel).
// stdout: {"scenes": [{"id", "frames", "captured", "ms", "errors", "overflow", "out"}], "ms"}
// stderr: one progress line per scene.
//
// Nothing may hang: every scene has a time limit, a dead ffmpeg ends the scene, and a crashed Chrome is relaunched.
import puppeteer from "puppeteer-core";
import { spawn } from "node:child_process";
// stdin is read asynchronously: readFileSync(0) throws EAGAIN on a pipe once the payload outgrows one read
const chunks = [];
for await (const c of process.stdin) chunks.push(c);
const job = JSON.parse(Buffer.concat(chunks).toString("utf8"));
const ARGS = ["--hide-scrollbars", "--force-color-profile=srgb", "--font-render-hinting=none",
  "--disable-background-timer-throttling", "--disable-renderer-backgrounding", "--disable-backgrounding-occluded-windows",
  "--allow-file-access-from-files"];
const size = (s) => (s.to ?? s.frames) - (s.from ?? 0);
const log = (msg) => process.stderr.write(msg + "\n");

class Timeout extends Error {}
const withTimeout = (promise, ms, what) => {
  let timer;
  return Promise.race([promise, new Promise((_, reject) => { timer = setTimeout(() => reject(new Timeout(what)), ms); })])
    .finally(() => clearTimeout(timer));
};

async function renderScene(page, s) {
  const t0 = performance.now();
  const errors = [];
  const onError = (e) => errors.push(String(e && e.message ? e.message : e));
  const onConsole = (m) => { if (m.type() === "error") errors.push(m.text()); };
  page.on("pageerror", onError);
  page.on("console", onConsole);
  let captured = 0, overflow = [], out = null, ff = null;
  try {
    await page.goto("file://" + s.html, { waitUntil: "load", timeout: 20000 });
    await withTimeout(page.evaluate(() => window.__ready()), 20000, "page did not get ready");
    out = await page.evaluate(() => (window.__out ? window.__out() : null));
    const enc = s.enc || (s.alpha ? ["-c:v", "qtrle", "-pix_fmt", "argb"] : ["-c:v", "qtrle", "-pix_fmt", "rgb24"]);
    ff = spawn(job.ffmpeg, ["-v", "error", "-y", "-f", "image2pipe", "-framerate", String(s.fps), "-c:v", "png",
      "-i", "-", ...enc, s.out], { stdio: ["pipe", "ignore", "pipe"] });
    let ffErr = "", ffDead = false;
    ff.stderr.on("data", (d) => { ffErr += d; });
    ff.stdin.on("error", () => { ffDead = true; });
    const closed = new Promise((resolve) => ff.on("close", (code) => { ffDead = true; resolve(code); }));
    let prev = null;
    const first = s.from ?? 0, last = s.to ?? s.frames;
    for (let f = first; f < last; f++) {
      if (ffDead) throw new Error("ffmpeg stopped: " + ffErr.trim().slice(-300));
      const t = (f * 1000) / s.fps;
      let buf = prev;
      if (!prev || await page.evaluate((a, b) => window.__changes(a, b), ((f - 1) * 1000) / s.fps, t)) {
        await page.evaluate((x) => window.__seek(x), t);
        buf = await page.screenshot({ type: "png", omitBackground: !!s.alpha, optimizeForSpeed: true });
        captured++;
      }
      prev = buf;
      if (!ff.stdin.write(buf)) await Promise.race([new Promise((resolve) => ff.stdin.once("drain", resolve)), closed]);
    }
    if (s.check_at != null) {
      await page.evaluate((x) => window.__seek(x), s.check_at);
      overflow = await page.evaluate(() => window.__overflow());
    }
    ff.stdin.end();
    const code = await withTimeout(closed, 30000, "ffmpeg did not finish");
    if (code !== 0) errors.push("ffmpeg: " + ffErr.trim().slice(-500));
  } catch (e) {
    errors.push(String(e && e.message ? e.message : e));
    if (ff && ff.exitCode === null) ff.kill("SIGKILL");
    if (e instanceof Timeout) throw Object.assign(e, { result: { id: s.id, frames: size(s), captured, errors, overflow, out } });
  } finally {
    page.off("pageerror", onError);
    page.off("console", onConsole);
  }
  return { id: s.id, frames: size(s), captured, ms: Math.round(performance.now() - t0), errors, overflow, out };
}

const launch = () => puppeteer.launch({ executablePath: job.chrome, headless: true, args: ARGS, protocolTimeout: 60000 });

async function freshPage(browser) {
  const page = await browser.newPage();
  await page.setViewport({ width: job.width || 1080, height: job.height || 1920, deviceScaleFactor: job.scale || 1 });
  return page;
}

async function worker(queue, results) {
  let browser = await launch();
  let page = await freshPage(browser);
  try {
    for (let s = queue.shift(); s; s = queue.shift()) {
      const limit = 30000 + size(s) * 1500;             // generous: normal frames take 40-150 ms
      let r;
      try {
        r = await withTimeout(renderScene(page, s), limit, `scene ${s.id} took longer than ${Math.round(limit / 1000)} s`);
      } catch (e) {
        r = e.result || { id: s.id, frames: size(s), captured: 0, errors: [], overflow: [], out: null };
        r.errors = [...new Set([...(r.errors || []), String(e.message || e)])];
        r.ms = limit;
        await browser.close().catch(() => {});        // a stuck page: start this worker afresh
        browser = await launch();
        page = await freshPage(browser);
      }
      results.push(r);
      log(`${r.errors.length ? "FAIL" : "ok  "} ${r.id} ${r.captured}/${r.frames} frames ${r.ms} ms`);
      if (!browser.connected) {                       // Chrome crashed: relaunch for the next scene
        browser = await launch();
        page = await freshPage(browser);
      }
    }
  } finally {
    await browser.close().catch(() => {});
  }
}

const start = performance.now();
const queue = [...job.scenes].sort((a, b) => size(b) - size(a));   // biggest first balances the pool
const n = Math.max(1, Math.min(job.workers || 8, queue.length));
const results = [];
await Promise.all(Array.from({ length: n }, () => worker(queue, results)));
// exit only once stdout has drained: a piped write over 64 KB is otherwise cut off
process.stdout.write(JSON.stringify({ scenes: results, ms: Math.round(performance.now() - start) }), () => process.exit(0));
