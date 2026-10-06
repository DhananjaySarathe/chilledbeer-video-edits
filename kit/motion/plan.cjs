// node kit/motion/plan.cjs in.json [out.json] — run the camera director (kit/hf/motion.js) outside the page.
// in.json = the HF.motion.direct() options (or {plan: P} to only re-sample a plan); out = the plan + `windows` (the frames
// that need motion blur, with their sub-frame matrices) for kit/motion/camera.py. motion.js is a browser script, so it
// runs in a sandbox context here (the same file, byte for byte, as the page inlines).
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const ctx = vm.createContext({ console });
vm.runInContext(fs.readFileSync(path.join(__dirname, "../hf/motion.js"), "utf8"), ctx, { filename: "motion.js" });
const MO = ctx.HF.motion;
const [inp, outp] = process.argv.slice(2);
if (!inp) { console.error("usage: node kit/motion/plan.cjs in.json [out.json]"); process.exit(2); }
const o = JSON.parse(fs.readFileSync(inp, "utf8"));
const P = o.plan || MO.direct(o);
P.windows = MO.windows(P, o.blurMax ? { max: o.blurMax } : undefined);
const s = JSON.stringify(P);
if (outp) fs.writeFileSync(outp, s); else process.stdout.write(s);
