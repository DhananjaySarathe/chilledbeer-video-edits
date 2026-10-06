"""kit/hf/kinetic.js: the springs, curves, staggers and the *stress* parser, run in node (no browser)."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

KINETIC = Path(__file__).resolve().parents[1] / "kit/hf/kinetic.js"
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="needs node")

HARNESS = """
globalThis.window = globalThis; globalThis.HF = { kit: () => {}, C: {} };
require(%s);
globalThis.document = { createElement: () => ({ style: {}, children: [], append(...c) { this.children.push(...c); } }) };
const K = { tl: { fromTo() {}, to() {}, set() {} }, Q: (t) => t, fps: 30, width: 1080, words_: [], sfx() {},
            el: () => document.createElement("div") };
const out = { springs: {}, parse: {} };
for (const [n, s] of Object.entries(HF.SPRING)) {
  const r = HF.spring(s);
  out.springs[n] = { duration: r.duration, land: r.land, overshoot: r.overshoot, e0: r.ease(0), e1: r.ease(1),
                     monotone: [...Array(101).keys()].every((i) => i === 0 || r.ease(i / 100) >= r.ease((i - 1) / 100) - 1e-9) };
}
out.curves = Object.fromEntries(Object.entries(HF.E).map(([n, e]) => [n, [0, 0.5, 1].map((p) => e(p))]));
out.stagger = [HF.stagger(10), HF.stagger(1), HF.stagger(3, 0.1)];
for (const text of ["Most people spend *4 hours* editing", "The *whole* system", "a *lone word", "two | *lines* here"])
  out.parse[text] = HF.kinetic(K, null, { text, at: 0.5, style: "slam" }).words.map((w) => [w.text, w.stress, w.br]);
console.log(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def k():
    r = subprocess.run(["node", "-e", HARNESS % json.dumps(str(KINETIC))], capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


def test_springs_end_exactly_at_rest(k):
    for name, s in k["springs"].items():
        assert s["e0"] == 0 and s["e1"] == 1, name
        assert 0 < s["land"] <= s["duration"] < 1.5, name


def test_no_bounce_springs_never_overshoot(k):
    for name in ("ui", "soft"):
        assert k["springs"][name]["overshoot"] < 1e-6 and k["springs"][name]["monotone"]


def test_bouncy_springs_stay_tasteful(k):
    """Momentum springs overshoot a little (Apple-style), far from Remotion's default 16 %."""
    assert 0.005 < k["springs"]["snappy"]["overshoot"] < 0.03
    assert 0.03 < k["springs"]["thrown"]["overshoot"] < 0.08


def test_curves_start_at_0_and_end_at_1(k):
    for name, (a, mid, b) in k["curves"].items():
        assert a == 0 and b == 1 and 0 < mid < 1, name
    assert k["curves"]["in"][1] > 0.9 and k["curves"]["out"][1] < 0.1      # expo out is fast early, the exit late


def test_stagger_is_capped(k):
    ten, one, three = k["stagger"]
    assert ten[0] == 0 and abs(ten[-1] - 0.5) < 1e-9 and one == [0]
    assert three == pytest.approx([0, 0.1, 0.2])


def test_stress_spans_and_line_breaks(k):
    p = k["parse"]
    assert [w[0] for w in p["Most people spend *4 hours* editing"] if w[1]] == ["4", "hours"]
    assert p["The *whole* system"] == [["The", False, False], ["whole", True, False], ["system", False, False]]
    assert [w[0] for w in p["a *lone word"] if w[1]] == ["lone"]
    assert p["two | *lines* here"][1] == ["lines", True, True]
