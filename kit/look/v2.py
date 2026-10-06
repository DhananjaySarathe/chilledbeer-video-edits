"""Look v2: a scene-referred grade for talking heads (opt-in: grade.py --v2).

Order of operations (every frame; the per-shot numbers are measured once per shot by `analyse`):

  per shot, in linear light (BT.1886 decode of the Rec.709 footage); measured on the YuNet face box (cheeks + forehead)
    1. black trim   a soft flare offset so the shot's 0.5th-percentile black lands on the look's black target
    2. white balance temperature + tint from the skin, not grey-world (warm lamps and wood would drag it): half of the
                    face's hue error and half of its chroma error, never pushing the room's bright neutrals past neutral
    3. exposure     the face's mean luma lands on the look's skin target
    4. skin rotation what the white balance left of the hue error, as a skin-only hue rotation (applied in step 9)
  the look (fixed per look, the same for every shot)
    5. light        (linear) portrait background: masked defocus, -0.5 stop and calmer colour through a heavily
                    feathered matte; a soft key on the face; an elliptical vignette centred on the face
    6. halation     (linear, before the curve) a red-weighted glow around bright edges, gain-normalised
    7. saturation   (linear) subtractive: n * (rgb / n) ** gamma, n = max(R, G, B); at reduced strength on skin
    8. tone curve   darktable-style generalised log-logistic sigmoid, per channel, on inset/rotated primaries (the
                    "smooth" preset) so warm lamps roll off toward white instead of clipping into orange blobs
    9. skin         (display Y'CbCr) hue compression toward the skin line (+ the shot's rotation) and a soft-knee
                    chroma compressor
   10. split tone   warm highlights / cool shadows, ~1-2 % chroma, skin spared in the shadows
  texture, at output resolution
   11. local contrast (band-pass, background/clothes up, skin a little down), fine sharpening on the person
   12. grain      mono, midtone-weighted (4Y(1-Y)), new per frame (seeded by the frame index), half on skin
   13. dither     +-0.5 LSB before the 8-bit quantisation (no banding in dim backgrounds and vignettes)

Everything is float32 numpy/OpenCV and deterministic. Parameters: V2 (defaults = "natural"), each look's "v2" dict in
looks.LOOKS and each room's "v2" dict in looks.ROOMS; `params(look, room, reel)` merges them.
"""
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import faces as FC  # noqa: E402

LUMA = np.array([0.2126, 0.7152, 0.0722], np.float32)
GREY = 0.1845
SKIN_LINE = 123.0

# ------------------------------------------------------------------------------------------------------------ parameters
V2 = {
    # per-shot targets (what `analyse` solves the black trim, white balance and exposure for)
    "skin_y": 0.505,           # face mean luma Y' (scopes: 0.40-0.55; frames vary about +-0.04 around the shot). The creator
                               # chose halfway between v2's first grade and the old engine: brighter on phones. 0.505 measures
                               # ~0.535 on the shelf frames (v2 first ~0.50, old ~0.58); the paper room sets its own 0.55
    "black": 0.022,            # 0.5th-percentile Y' of the frame (scopes: >= 0.01-0.02, not milky either)
    "skin_c": 0.25,            # face chroma 2|CbCr| the temperature leans toward (scopes: 0.20-0.32)
    "hue_k": 0.5,              # how much of the skin-hue error the white balance corrects (a skin rotation does the rest)
    "chroma_k": 0.5,           # how much of the skin-chroma error the temperature corrects (the knee does the rest)
    "wb_max": [0.35, 0.15],    # |temperature|, |tint| limits in stops
    "neutral_keep": 0.6,       # the room's bright neutrals keep at least this much of their cast (warm walls stay warm)
    # light (linear, spatial)
    "bg_stops": -0.5, "bg_sat": 0.85, "bg_blur": 0.0, "bg_feather": 0.035,   # needs a matte; feather: sigma / frame height
    "key": 0.12, "fall": 0.08,  # stops of soft key on the face's camera-left side / falloff on the far cheek
    "vignette": -0.3,          # stops at the corners, elliptical, centred on the face
    "halation": 0.6,           # x the utility-dctls weights (R 2^-3, G 2^-4.4, B 2^-5.8), radius 0.3 % of the width
    # colour (per pixel)
    "sat": 1.0,                # plain linear saturation (moody/film calm the whole room)
    "sat_skin": 0.3,           # fraction of that desaturation that reaches skin (1.0 greyed the face in moody)
    "subsat": 1.15,            # subtractive saturation gamma
    "subsat_skin": 0.4,        # fraction of it on skin
    "contrast": 1.4, "skew": -0.1, "white": 1.6,                # the sigmoid (contrast at mid grey 0.1845; white = its
                                                                # asymptote in display linear: 1.6 puts source white at ~0.93)
    "inset": [0.10, 0.10, 0.15], "rotate": [2.0, -1.0, -3.0], "purity": 0.0,
    "hue_pull": 0.35, "hue_sigma": 25.0,                        # skin hue compression: ~5 deg max pull at ~18 deg off
    "knee": 0.27, "ratio": 2.0, "knee_w": 0.06,                 # skin chroma soft knee (2|CbCr|), width of the soft zone
    "split_hi": [0.016, 140.0], "split_sh": [0.010, 320.0],    # chroma 2|CbCr|, hue in BT.709 CbCr degrees
    "lift": 0.0,               # shadow lift in Y' (Reels: 0.02)
    "bw": None,                # [r, g, b] mono mix in linear (noir)
    # texture
    "local": 0.15, "local_skin": -0.06, "local_sigma": 0.015,   # band-pass contrast, sigma / frame height
    "sharpen": 0.22,
    "grain": 0.008, "grain_skin": 0.5, "grain_size": 0.7,       # sigma in Y' at mid grey, x on skin, px at 1080p
    "dither": True,
}


def params(look: str = "natural", room: str | None = None, reel: bool = False) -> dict:
    """V2 defaults <- the look's "v2" dict <- the room's "v2"[look] dict (<- Reels adjustments)."""
    import looks as LK
    P = json.loads(json.dumps(V2))
    P.update(LK.LOOKS.get(look, {}).get("v2", {}))
    room = room or "paper"                         # no room = the channel's cream-wall studio (as in the old engine)
    if room in LK.ROOMS:
        R = LK.ROOMS[room].get("v2", {})
        P.update(R.get("*", {}))
        P.update(R.get(look, {}))
    if reel:                                       # same look; phones: lifted shadows, half grain, gentler gradients
        P["lift"] = max(P["lift"], 0.02)
        P["grain"] *= 0.5
        P["vignette"] *= 0.6
    P["_look"], P["_room"] = look, room
    return P


# ------------------------------------------------------------------------------------------------------------ colour maths
_DEC = (np.arange(256, dtype=np.float64) / 255) ** 2.4


def decode(x):
    return np.power(np.clip(x, 0, None), 2.4, dtype=np.float32)


def encode(x):
    return np.power(np.clip(x, 0, None), 1 / 2.4, dtype=np.float32)


def luma(rgb):
    return rgb[..., 0] * LUMA[0] + rgb[..., 1] * LUMA[1] + rgb[..., 2] * LUMA[2]


def ycc(rgb):
    y = luma(rgb)
    return y, (rgb[..., 2] - y) / 1.8556, (rgb[..., 0] - y) / 1.5748


def rgb_from_ycc(y, cb, cr):
    r = y + 1.5748 * cr
    b = y + 1.8556 * cb
    g = (y - 0.2126 * r - 0.0722 * b) / 0.7152
    return np.stack([r, g, b], -1)


def wb_gains(t: float, g: float) -> np.ndarray:
    """Temperature t (stops, + warmer: R up, B down) and tint g (stops, + magenta: G down), at constant luminance."""
    gains = np.array([2 ** (t / 2 + g / 3), 2 ** (-2 * g / 3), 2 ** (-t / 2 + g / 3)], np.float64)
    return (gains / (gains @ LUMA)).astype(np.float32)


# --- the sigmoid (generalised log-logistic; the maths of darktable's sigmoid module, reimplemented from its model):
#     y(x) = W * (x^n / (x^n + e))^p,  p = 5^-skew,  with y(grey) = grey and the log-log slope at grey = contrast * (1 - grey)
def sigmoid_params(contrast: float, skew: float, white: float = 1.0):
    p = 5.0 ** (-skew)
    q = (GREY / white) ** (1 / p)
    n = contrast * (1 - GREY) / (p * (1 - q))
    e = GREY ** n * ((white / GREY) ** (1 / p) - 1)
    return n, e, p, white


def sigmoid(x, sp):
    n, e, p, w = sp
    u = np.power(np.maximum(x, 0), n, dtype=np.float32)
    return (w * np.power(u / (u + e), p, dtype=np.float32)).astype(np.float32)


_XY = {"r": (0.64, 0.33), "g": (0.30, 0.60), "b": (0.15, 0.06)}
_WP = (0.3127, 0.3290)


def _primaries_matrix(xy):
    """RGB -> XYZ for primaries xy (3 x 2) and the D65 white."""
    P = np.array([[x / y, 1.0, (1 - x - y) / y] for x, y in xy]).T
    w = np.array([_WP[0] / _WP[1], 1.0, (1 - _WP[0] - _WP[1]) / _WP[1]])
    return P * np.linalg.solve(P, w)


def inset_matrix(inset, rotate) -> np.ndarray:
    """Columns = each Rec.709 primary moved toward white by `inset` and rotated by `rotate` degrees (around D65 in xy),
    expressed in Rec.709 RGB. Applied to RGB it desaturates (AgX-style), rows sum to 1 (white stays white)."""
    xy = []
    for k, (i, r) in zip("rgb", zip(inset, rotate)):
        d = np.array(_XY[k]) - _WP
        a = np.radians(r)
        d = np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]]) @ d * (1 - i)
        xy.append(_WP + d)
    m709 = _primaries_matrix([_XY[k] for k in "rgb"])
    return (np.linalg.inv(m709) @ _primaries_matrix(xy)).astype(np.float32)


def _cache(P):
    key = json.dumps({k: P[k] for k in ("contrast", "skew", "white", "inset", "rotate", "purity")}, sort_keys=True)
    if key not in _C:
        m_in = inset_matrix(P["inset"], P["rotate"])
        m_out = np.linalg.inv(inset_matrix([i * P["purity"] for i in P["inset"]], [0, 0, 0])) if P["purity"] else np.eye(3)
        _C[key] = (m_in, m_out.astype(np.float32), sigmoid_params(P["contrast"], P["skew"], P["white"]))
    return _C[key]


_C = {}


def _mat(x, m):
    """x (..., 3) @ m.T, fast for images (cv2.transform)."""
    if x.ndim == 3 and x.dtype == np.float32:
        return cv2.transform(x, m.astype(np.float32))
    return (x @ m.T).astype(np.float32)


_LUT_N, _UMAX = 16384, 2.0


def _tone_lut(P):
    """The per-channel curve as a table on u = sqrt(x) (fine steps in the shadows), x up to 4.0 (display-linear inputs
    above that are deep in the shoulder). Without purity recovery the display encode is folded in."""
    key = ("tlut", json.dumps({k: P[k] for k in ("contrast", "skew", "white", "purity")}, sort_keys=True))
    if key not in _C:
        u = np.linspace(0, _UMAX, _LUT_N, dtype=np.float32)
        y = sigmoid(u * u, sigmoid_params(P["contrast"], P["skew"], P["white"]))
        _C[key] = encode(np.clip(y, 0, 1)) if not P["purity"] else y
    return _C[key]


def tone(lin, P):
    """Linear -> display Y' (0..1): inset/rotated primaries -> the sigmoid per channel (by table) -> [purity] -> encode."""
    m_in, m_out, _ = _cache(P)
    x = np.maximum(_mat(lin, m_in), 0)
    i = np.minimum(np.sqrt(x) * np.float32((_LUT_N - 1) / _UMAX) + np.float32(0.5), _LUT_N - 1).astype(np.int32)
    y = _tone_lut(P)[i]
    if P["purity"]:
        return encode(np.clip(_mat(y, m_out), 0, 1))
    return y


def subtractive_sat(lin, gamma, skin_w=None, skin_frac=0.4):
    """out = n * (rgb / n) ** gamma, n = max(R, G, B) (in linear; never brighter than the brightest channel), written as
    rgb * (rgb / n) ** (gamma - 1) on OpenCV planes; on skin only `skin_frac` of the effect stays."""
    if gamma == 1.0:
        return lin
    k = None if skin_w is None else (1 - (1 - skin_frac) * skin_w).astype(np.float32)
    if lin.ndim != 3:                                                 # samples (N, 3): plain numpy
        n = np.maximum(lin.max(-1, keepdims=True), 1e-6)
        f = np.power(lin / n + 1e-7, gamma - 1, dtype=np.float32)
        return (lin * f if k is None else lin * (1 + (f - 1) * k[..., None])).astype(np.float32)
    p = cv2.split(np.ascontiguousarray(lin, dtype=np.float32))
    n = np.maximum(cv2.max(cv2.max(p[0], p[1]), p[2]), np.float32(1e-6))
    out = []
    for c in p:
        f = cv2.exp(cv2.log(cv2.divide(c, n) + np.float32(1e-7)) * np.float32(gamma - 1))
        out.append(c * f if k is None else c * (1 + (f - 1) * k))
    return cv2.merge(out)


def _skin_secondary(rgb, P, w=None):
    """Display RGB: pull hues within ~+-25 deg toward the skin line (compression, so variation within the face survives)
    and soft-knee the chroma of skin hues above `knee` (2|CbCr|). `w` (0..1) limits it spatially."""
    y, cb, cr = ycc(rgb)
    c = 2 * np.hypot(cb, cr)
    h = np.degrees(np.arctan2(cr, cb))
    d = (h - SKIN_LINE + 180) % 360 - 180
    s = P["hue_sigma"]
    member = np.exp(-(d / (1.6 * s)) ** 2) * np.clip((c - 0.07) / 0.08, 0, 1) * np.clip((y - 0.04) / 0.08, 0, 1)
    if w is not None:
        member = member * w
    d2 = d - P["hue_pull"] * d * np.exp(-(d / s) ** 2) * member + P.get("skin_rot", 0.0) * member
    k, ratio, kw = P["knee"], P["ratio"], P["knee_w"]
    over = c - (k - kw / 2)                                       # soft knee (quadratic over the knee width)
    cc = np.where(over <= 0, c, np.where(over < kw, c - (1 - 1 / ratio) * over ** 2 / (2 * kw), k + (c - k) / ratio))
    cc = c + (cc - c) * member
    a = np.radians(SKIN_LINE + d2)
    rr = cc / 2
    return rgb_from_ycc(y, rr * np.cos(a), rr * np.sin(a)).astype(np.float32)


def skin_secondary(rgb, P, w=None):
    """_skin_secondary on the pixels the spatial weight touches (usually the face and hands: a few % of the frame)."""
    if w is None or rgb.ndim != 3:
        return _skin_secondary(rgb, P, w)
    m = w > 0.004
    if m.all():
        return _skin_secondary(rgb, P, w)
    out = rgb.copy()
    if m.any():
        out[m] = _skin_secondary(rgb[m], P, w[m])
    return out


def split_tone(rgb, P, skin_w=None):
    y = luma(rgb)
    (ah, hh), (as_, hs) = P["split_hi"], P["split_sh"]
    hi = np.clip((y - 0.45) / 0.5, 0, 1) ** 2
    sh = np.clip(y / 0.06, 0, 1) * np.clip(1 - y / 0.42, 0, 1) ** 2        # zero at black: blacks stay neutral
    if skin_w is not None:
        sh = sh * (1 - skin_w)                                                # no teal skin shadows
    dcb = (hi * ah * np.cos(np.radians(hh)) + sh * as_ * np.cos(np.radians(hs))) / 2
    dcr = (hi * ah * np.sin(np.radians(hh)) + sh * as_ * np.sin(np.radians(hs))) / 2
    return np.stack([rgb[..., 0] + 1.5748 * dcr, rgb[..., 1] - (0.2126 * 1.5748 * dcr + 0.0722 * 1.8556 * dcb) / 0.7152,
                     rgb[..., 2] + 1.8556 * dcb], -1).astype(np.float32)


def colour(lin, P, skin_w=None):
    """The per-pixel part of the look: linear (after the light) -> display RGB 0..1."""
    if P.get("bw"):
        m = lin @ np.array(P["bw"], np.float32)
        lin = np.repeat(m[..., None], 3, -1)
    elif P["sat"] != 1.0:
        yl = luma(lin)[..., None]
        s = P["sat"] if skin_w is None else (P["sat"] + (1 - P["sat"]) * (1 - P["sat_skin"]) * skin_w)[..., None]
        lin = yl + (lin - yl) * s
    if not P.get("bw"):
        lin = subtractive_sat(np.maximum(lin, 0), P["subsat"], skin_w if skin_w is not None else np.zeros(lin.shape[:-1], np.float32), P["subsat_skin"])
    out = tone(lin, P)
    if not P.get("bw"):
        out = skin_secondary(out, P, skin_w)
        out = split_tone(out, P, skin_w)
    else:
        out = split_tone(out, P)
    if P["lift"]:
        y = luma(out)
        out = out + (P["lift"] * np.clip(1 - y / 0.35, 0, 1) ** 2)[..., None]
    return out


# ------------------------------------------------------------------------------------------------------------ per shot
def black_trim(lin, f):
    """Flare offset in linear: f > 0 removes a veil (soft: lin^2 / (lin + f), never negative), f < 0 lifts."""
    if f == 0:
        return lin
    if f > 0:
        return (lin * lin / (lin + f)).astype(np.float32)
    return (lin - f).astype(np.float32)


def balance_lin(lin, bal):
    lin = black_trim(lin, bal.get("flare", 0.0))
    return lin * (wb_gains(*bal["wb"]) * np.float32(2.0 ** bal["ev"]))


_OFF = np.array([0, 256, 512], np.int16)


def balance_u8(img_u8, bal):
    """decode + black trim + white balance + exposure of an 8-bit frame in one table lookup (per channel, 256 entries)."""
    key = ("bal", json.dumps([bal.get("flare", 0.0), bal["wb"], bal["ev"]]))
    if key not in _C:
        t = balance_lin(np.repeat(_DEC.astype(np.float32)[:, None], 3, 1), bal)       # 256 x 3
        _C[key] = np.ascontiguousarray(t.T).reshape(-1)
    return _C[key][img_u8.astype(np.int16) + _OFF]


def _skin_stats(rgb):
    y, cb, cr = ycc(rgb)
    mcb, mcr = float(np.median(cb)), float(np.median(cr))
    return float(np.mean(y)), float(np.degrees(np.arctan2(mcr, mcb))), 2 * float(np.hypot(mcb, mcr))


def analyse(frames, P) -> dict:
    """The per-shot balance from sampled frames: frames = [(display RGB float 0..1 HxWx3, face dict or None[, matte]), ...].
    Returns {flare, wb: [t, g], ev, skin_rot, skin_cb, skin_cr, skin_sd, src: {...}, out: {...}} (measured, deterministic).

    exposure    the face's mean Y' (through the whole look, with the light it gets from the key and vignette) -> skin_y
    wb          tint + temperature: `hue_k` of the face's hue error and `chroma_k` of its chroma error (chroma measured
                on the balance alone), never pushing the room's bright neutrals past neutral (no lilac walls)
    skin_rot    the rest of the hue error, as a skin-only hue rotation (a per-shot skin secondary)
    flare       the shot's black: the darkest pixels (with the vignette / background dim they get) -> P["black"]"""
    skin, neut, dark, dark_id, fgs, blacks = [], [], [], [], [], []
    for k, fr in enumerate(frames):
        img, face = fr[0], fr[1]
        matte = fr[2] if len(fr) > 2 else None
        H, W = img.shape[:2]
        y = img @ LUMA
        blacks.append(float(np.percentile(y, 0.5)))
        m4 = cv2.resize(matte, (W // LS, H // LS), interpolation=cv2.INTER_AREA) if matte is not None else None
        stops, _ = light_field(face, W, H, P, m4)
        gain = cv2.resize(np.exp2(stops), (W // 2, H // 2), interpolation=cv2.INTER_LINEAR)
        half = cv2.resize(img, (W // 2, H // 2), interpolation=cv2.INTER_AREA)
        if matte is not None and P["bg_blur"] > 0:                    # the portrait defocus fills the room's dark gaps
            half = encode(defocus(decode(half), cv2.resize(matte, (W // 2, H // 2), interpolation=cv2.INTER_AREA), P["bg_blur"] * H / 1080 / 2))
        yh = half @ LUMA
        sel = yh <= np.percentile(yh, 1.5)
        dark.append(np.concatenate([half[sel], gain[sel][:, None]], 1))
        dark_id.append(np.full(int(sel.sum()), k))
        if face is not None:
            px = FC.skin_pixels(img, face)
            skin.append(px)
            reg = cv2.resize(FC.skin_region((H, W), face).astype(np.uint8), (W // LS, H // LS), interpolation=cv2.INTER_NEAREST).astype(bool)
            fgs.append(float(np.mean(np.exp2(stops[reg]))) if reg.any() else 1.0)
            x0, y0, w, h = face["box"]
            q = img[::8, ::8].reshape(-1, 3)
            yy, xx = np.mgrid[0:H:8, 0:W:8]
            far = ((np.abs(xx - x0 - w / 2) > 0.8 * w) | (np.abs(yy - y0 - h / 2) > 0.8 * h)).ravel()
            qy, qcb, qcr = ycc(q)
            neut.append(q[far & (qy > 0.45) & (qy < 0.97) & (2 * np.hypot(qcb, qcr) < 0.15)])
    skin = np.concatenate(skin) if skin else np.zeros((0, 3), np.float32)
    if len(skin) > 20000:
        skin = skin[np.linspace(0, len(skin) - 1, 20000).astype(int)]
    black_src = float(np.median(blacks))
    if len(skin) < 200:                                               # no face: neutral balance
        return {"flare": 0.0, "wb": [0.0, 0.0], "ev": 0.0, "skin_rot": 0.0, "skin_cb": -0.06, "skin_cr": 0.09, "skin_sd": 0.03,
                "src": {"black": black_src}, "out": {}, "faces": 0}
    fg = np.float32(np.mean(fgs))                                     # mean light gain the face gets (key, vignette)
    _, cb_s, cr_s = ycc(skin)
    lin_skin = decode(skin)
    ones = np.ones(len(skin), np.float32)
    neut = np.concatenate(neut) if neut else np.zeros((0, 3), np.float32)
    lin_neut = decode(neut)
    dark, dark_id = np.concatenate(dark), np.concatenate(dark_id)
    lin_dark, dark_gain = decode(dark[:, :3]), dark[:, 3:].astype(np.float32)
    zeros_d = np.zeros(len(dark), np.float32)

    def run(t, g, ev, flare, rot=0.0):
        lin = black_trim(lin_skin, flare) * (wb_gains(t, g) * np.float32(2.0 ** ev) * fg)
        return colour(lin, dict(P, skin_rot=rot), ones)

    def neutral(t, g, flare, lin=lin_skin):                           # the balance alone, before the look
        return encode(black_trim(lin, flare) * wb_gains(t, g))

    def solve_ev(t, g, flare, rot=0.0):
        lo, hi = -2.5, 2.5
        for _ in range(24):
            mid = (lo + hi) / 2
            if _skin_stats(run(t, g, mid, flare, rot))[0] < P["skin_y"]:
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2

    def black_out(t, g, ev, flare):                                    # median over frames of each frame's 0.5th pct
        lin = black_trim(lin_dark, flare) * (wb_gains(t, g) * np.float32(2.0 ** ev)) * dark_gain
        y = colour(lin, P, zeros_d) @ LUMA
        return float(np.median([np.quantile(y[dark_id == k], 1 / 3) for k in np.unique(dark_id)]))

    def solve_flare(t, g, ev):
        bl = black_src ** 2.4
        lo, hi = -1.0 * bl, 1.5 * bl                                   # gentle: at most a 1.5x black veil removed
        for _ in range(20):
            mid = (lo + hi) / 2
            if black_out(t, g, ev, mid) > P["black"]:
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2

    flare, t, g, rot = 0.0, 0.0, 0.0, 0.0
    ev = solve_ev(t, g, flare)
    flare = solve_flare(t, g, ev)
    ev = solve_ev(t, g, flare)
    # white balance: the hue through the whole look, the chroma on the balance alone (the look's own saturation must
    # not be undone by cooling the room)
    h0 = _skin_stats(run(t, g, ev, flare))[1]
    c0 = _skin_stats(neutral(t, g, flare))[2]
    c_goal = c0 + P["chroma_k"] * (P["skin_c"] - c0)
    h_goal = h0 + P["hue_k"] * (SKIN_LINE - h0)
    tmax, gmax = P["wb_max"]

    def hc(t, g, ev):
        return _skin_stats(run(t, g, ev, flare))[1], _skin_stats(neutral(t, g, flare))[2]
    for _ in range(6):                                                 # Newton on (temperature, tint)
        ev = solve_ev(t, g, flare)
        h, c = hc(t, g, ev)
        F = np.array([h - h_goal, (c - c_goal) * 100])
        if abs(F[0]) < 0.05 and abs(F[1]) < 0.05:
            break
        J = np.zeros((2, 2))
        for j, (dt, dg) in enumerate(((0.01, 0), (0, 0.01))):
            h2, c2 = hc(t + dt, g + dg, ev)
            J[:, j] = [(h2 - h) / 0.01, (c2 - c) * 100 / 0.01]
        step = np.linalg.lstsq(J, -F, rcond=None)[0]
        t, g = float(np.clip(t + step[0], -tmax, tmax)), float(np.clip(g + step[1], -gmax, gmax))
    # the room's bright neutrals (walls, white clothes) may lose their cast but never cross neutral into a new one
    neut_note = None
    if len(neut) > 200:
        def cast(t, g):
            _, ncb, ncr = ycc(neutral(t, g, flare, lin_neut))
            return np.array([np.median(ncb), np.median(ncr)])
        v0 = cast(0.0, 0.0)
        u = v0 / max(np.hypot(*v0), 1e-6)

        def bad(s):                                                    # keep >= 60 % of the cast, add no new one
            v = cast(t * s, g * s)
            along, across = v @ u, abs(v[0] * u[1] - v[1] * u[0])
            return along < P["neutral_keep"] * float(np.hypot(*v0)) or across > 0.006
        if bad(1.0):
            lo, hi = 0.0, 1.0
            for _ in range(16):
                mid = (lo + hi) / 2
                lo, hi = (lo, mid) if bad(mid) else (mid, hi)
            t, g = t * lo, g * lo
            neut_note = round(lo, 3)
        nv = cast(t, g)
        neut_out = {"cast_src": [round(float(x), 4) for x in v0], "cast_out": [round(float(x), 4) for x in nv]}
    else:
        neut_out = {}
    # what the white balance left: a skin-only hue rotation (the secondary), so every shot's face sits on the line
    ev = solve_ev(t, g, flare)
    for _ in range(4):
        h = _skin_stats(run(t, g, ev, flare, rot))[1]
        h2 = _skin_stats(run(t, g, ev, flare, rot + 1.0))[1]
        rot = float(np.clip(rot + (SKIN_LINE - h) / max(h2 - h, 0.2), -12, 12))
        ev = solve_ev(t, g, flare, rot)
    flare = solve_flare(t, g, ev)
    ev = solve_ev(t, g, flare, rot)
    yo, ho, co = _skin_stats(run(t, g, ev, flare, rot))
    ys = skin @ LUMA
    return {"flare": round(flare, 7), "wb": [round(t, 4), round(g, 4)], "ev": round(ev, 4), "skin_rot": round(rot, 2),
            "skin_cb": round(float(np.median(cb_s)), 4), "skin_cr": round(float(np.median(cr_s)), 4),
            "skin_sd": round(float(max(0.012, 1.4826 * np.median(np.abs(cr_s - np.median(cr_s))))), 4),
            "src": {"black": round(black_src, 4), "skin_y": round(float(ys.mean()), 4), **dict(zip(("skin_hue", "skin_c"), [round(v, 2) for v in _skin_stats(skin)[1:]]))},
            "out": {"skin_y": round(yo, 4), "skin_hue": round(ho, 2), "skin_c": round(co, 4), "black": round(black_out(t, g, ev, flare), 4),
                    "skin_c_balanced": round(_skin_stats(neutral(t, g, flare))[2], 4), "face_gain": round(float(fg), 3),
                    "wb_scaled": neut_note, **neut_out},
            "faces": sum(1 for fr in frames if fr[1] is not None)}


# ------------------------------------------------------------------------------------------------------------ per frame
LS = 4                                                                 # smooth fields are computed at 1/4 size


def _grid(W, H):
    key = ("grid", W, H)
    if key not in _C:
        yy, xx = (np.mgrid[0:H // LS, 0:W // LS].astype(np.float32) + 0.5) * LS
        _C[key] = (yy, xx)
    return _C[key]


def light_field(face, W, H, P, matte4=None):
    """Exposure (stops) at 1/4 size: vignette centred on the face, a soft key / far-side falloff, the background set
    back through a heavily feathered matte. Also returns the soft person field (1 = person) used for bg saturation."""
    yy, xx = _grid(W, H)
    x, y, w, h = face["box"] if face else (W * 0.42, H * 0.2, W * 0.16, H * 0.3)
    cx, cy, hw = x + w / 2, y + h / 2, w / FC.WK
    a, b = max(cx, W - cx), max(cy, H - cy)
    r = np.sqrt(((xx - cx) / a) ** 2 + ((yy - cy) / b) ** 2)
    rc = np.mean([np.hypot((px - cx) / a, (py - cy) / b) for px in (0, W) for py in (0, H)])
    t = np.clip((r - 0.35 * rc) / (0.65 * rc), 0, 1)
    stops = P["vignette"] * t * t * (3 - 2 * t)
    key = np.exp(-(((xx - (cx - 0.30 * hw)) / (1.05 * hw)) ** 2 + ((yy - (cy - 0.05 * hw)) / (1.25 * hw)) ** 2))
    far = np.exp(-(((xx - (cx + 0.55 * hw)) / (0.55 * hw)) ** 2 + ((yy - cy) / (1.0 * hw)) ** 2))
    person = None
    if matte4 is not None:
        sg = P["bg_feather"] * H / LS
        # eroded by ~1 sigma before the blur: the room right at the silhouette is already ~85 % set back (a wider
        # field drew a light rim around the head on plain walls), and the person's own edges fall off like real light
        er = cv2.erode(matte4, np.ones((3, 3), np.uint8), iterations=max(1, int(round(sg))))
        person = np.clip(cv2.GaussianBlur(er, (0, 0), sg) * 1.1, 0, 1)
        key = key * (0.3 + 0.7 * cv2.GaussianBlur(matte4, (0, 0), 3))
        stops = stops + P["bg_stops"] * (1 - person)
    stops = stops + P["key"] * key - P["fall"] * far
    return stops.astype(np.float32), person


def skin_map(src4, bal, prior=None):
    """Skin weight at 1/4 size from the source colours: near this shot's measured face CbCr (an adaptive classifier, so
    tan books and wood only count where the matte says person)."""
    y, cb, cr = ycc(src4)
    sd = max(0.025, 2.0 * bal.get("skin_sd", 0.03))
    w = np.exp(-(((cb - bal.get("skin_cb", -0.06)) / (1.3 * sd)) ** 2 + ((cr - bal.get("skin_cr", 0.09)) / sd) ** 2) / 2)
    w = np.clip((w - 0.15) / 0.5, 0, 1)                                 # flat top: the whole face counts as skin
    w = w * np.clip((y - 0.06) / 0.08, 0, 1) * np.clip((0.97 - y) / 0.08, 0, 1)
    if prior is not None:
        w = w * prior
    return cv2.GaussianBlur(w.astype(np.float32), (0, 0), 1.0)


def defocus(lin, matte, sigma, composite=True):
    """The room behind the person defocused: a normalised (masked) blur, so the person never bleeds into the room;
    composited with a slightly eroded matte so the rim of room the matte includes around hair is defocused too."""
    b = 1 - matte
    bl = cv2.GaussianBlur(lin * b[..., None], (0, 0), sigma) / (cv2.GaussianBlur(b, (0, 0), sigma)[..., None] + 1e-3)
    if not composite:
        return bl
    me = cv2.GaussianBlur(cv2.erode(matte, np.ones((3, 3), np.uint8)), (0, 0), 1.0)[..., None]
    return (lin * me + bl * (1 - me)).astype(np.float32)


def halation(lin, amount, W):
    if amount <= 0:
        return lin
    wts = np.array([2 ** -3, 2 ** -4.4, 2 ** -5.8], np.float32) * amount
    hl = (lin[..., 0] + np.float32(0.1) * (lin[..., 1] + lin[..., 2])) * np.float32(1 / 1.2)
    sg = 0.003 * W
    small = cv2.resize(hl, (lin.shape[1] // 2, lin.shape[0] // 2), interpolation=cv2.INTER_AREA)
    glow = cv2.resize(cv2.GaussianBlur(small, (0, 0), sg / 2), (lin.shape[1], lin.shape[0]), interpolation=cv2.INTER_LINEAR)
    return cv2.merge([cv2.addWeighted(c, float(1 / (1 + w)), glow, float(w / (1 + w)), 0) for c, w in zip(cv2.split(lin), wts)])


def _grain_norm(size):
    key = ("gn", round(size, 3))
    if key not in _C:
        n = np.random.default_rng(0).standard_normal((512, 512)).astype(np.float32)
        _C[key] = 1.0 / float(cv2.GaussianBlur(n, (0, 0), size)[16:-16, 16:-16].std())
    return _C[key]


def grade(img_u8: np.ndarray, bal: dict, P: dict, face=None, matte=None, idx: int = 0, out_u8: bool = True):
    """One frame (HxWx3 uint8 display RGB) -> graded uint8 (or float32 display if out_u8=False).
    bal = analyse(...) for this frame's shot; face = faces.detect/from_track dict; matte = person matte float HxW 0..1."""
    H, W = img_u8.shape[:2]
    P = dict(P, skin_rot=bal.get("skin_rot", 0.0))
    src4 = cv2.resize(img_u8, (W // LS, H // LS), interpolation=cv2.INTER_AREA).astype(np.float32) / 255
    lin = balance_u8(img_u8, bal)
    m4 = cv2.resize(matte, (W // LS, H // LS), interpolation=cv2.INTER_AREA) if matte is not None else None
    # portrait defocus (linear light, so lamps bloom like a lens): a normalised masked blur, composited with an
    # eroded matte so the rim of room the matte includes around hair is defocused too
    if matte is not None and P["bg_blur"] > 0:
        h2, w2 = H // 2, W // 2
        bl = defocus(cv2.resize(lin, (w2, h2), interpolation=cv2.INTER_AREA), cv2.resize(matte, (w2, h2), interpolation=cv2.INTER_AREA),
                     P["bg_blur"] * H / 1080 / 2, composite=False)
        m2 = cv2.resize(matte, (w2, h2), interpolation=cv2.INTER_AREA)
        me = cv2.resize(cv2.GaussianBlur(cv2.erode(m2, np.ones((3, 3), np.uint8)), (0, 0), 1.0), (W, H), interpolation=cv2.INTER_LINEAR)[..., None]
        lin = lin * me + cv2.resize(bl, (W, H), interpolation=cv2.INTER_LINEAR) * (1 - me)
    stops, person = light_field(face, W, H, P, m4)
    gain = cv2.resize(np.exp2(stops), (W, H), interpolation=cv2.INTER_LINEAR)
    lin = cv2.multiply(lin, cv2.merge([gain, gain, gain]))
    if person is not None and P["bg_sat"] != 1.0:
        sat = cv2.resize(P["bg_sat"] + (1 - P["bg_sat"]) * person, (W, H), interpolation=cv2.INTER_LINEAR)[..., None]
        yl = luma(lin)[..., None]
        lin -= yl
        lin *= sat
        lin += yl
    lin = halation(lin, P["halation"], W)
    prior4 = cv2.GaussianBlur(m4, (0, 0), 2) if m4 is not None else None
    sk = cv2.resize(skin_map(src4, bal, prior4), (W, H), interpolation=cv2.INTER_LINEAR)
    out = colour(lin, P, sk)
    # texture: band-pass local contrast (fine skin texture untouched), then fine sharpening (person only if defocused)
    y = luma(out)
    delta = np.zeros_like(y)
    if P["local"] or P["local_skin"]:
        y4 = cv2.resize(y, (W // LS, H // LS), interpolation=cv2.INTER_AREA)
        big = cv2.resize(cv2.GaussianBlur(y4, (0, 0), P["local_sigma"] * H / LS), (W, H), interpolation=cv2.INTER_LINEAR)
        band = cv2.GaussianBlur(y, (0, 0), 2.0 * H / 1080) - big
        band = np.float32(0.05) * np.tanh(band * np.float32(20))            # soft cap: texture, not halos at hair/wall edges
        delta += (P["local"] + (P["local_skin"] - P["local"]) * sk) * band
    if P["sharpen"]:
        det = y - cv2.GaussianBlur(y, (0, 0), 1.3 * H / 1080)
        det = np.float32(0.04) * np.tanh(det * np.float32(25))               # strong edges are not sharpened further
        if matte is not None and P["bg_blur"] > 0:
            det = det * (0.3 + 0.7 * matte)
        delta += P["sharpen"] * det
    if P["local"] or P["local_skin"] or P["sharpen"]:
        # darkening is soft-limited to 35 % of the pixel's own level: dark gaps between bright books get detail, not
        # holes (an additive unsharp pins them at 0, which reads as crushed black)
        a = 0.35 * np.maximum(y, 1e-4)
        delta = np.where(delta < 0, -a * (1 - np.exp(delta / a)), delta)
        out = cv2.add(out, cv2.merge([delta, delta, delta]))
    rng = np.random.default_rng(1_000_003 + idx)
    if P["grain"]:
        n = cv2.GaussianBlur(rng.standard_normal((H, W), dtype=np.float32), (0, 0), P["grain_size"] * H / 1080)
        yc = np.clip(y, 0, 1)
        amp = P["grain"] * _grain_norm(P["grain_size"] * H / 1080) * 4 * yc * (1 - yc) * (1 - (1 - P["grain_skin"]) * sk)
        n *= amp
        out = cv2.add(out, cv2.merge([n, n, n]))
    np.clip(out, 0, 1, out=out)
    return quantise(out, idx, P["dither"]) if out_u8 else out


def quantise(out, idx=0, dither=True):
    """Display float -> uint8 with +-0.5 LSB of uniform dither (seeded by the frame index): no banding in dim gradients."""
    d = np.random.default_rng(2_000_003 + idx).random(out.shape, dtype=np.float32) - np.float32(0.5) if dither else np.float32(0)
    return np.clip(out * np.float32(255) + np.float32(0.5) + d, 0, 255).astype(np.uint8)


def bake(look: str, room: str | None = None, size: int = 65) -> np.ndarray:
    """The per-pixel part of a v2 look (saturation, sigmoid on inset primaries, skin hue/chroma compression, split tone)
    as a size^3 LUT indexed lut[r, g, b], for Resolve / Premiere / ffmpeg lut3d. Its input is footage already balanced
    per shot (exposure, white balance); the light (background, key, vignette), halation, texture and grain are spatial
    and stay in grade.py, and the subtractive saturation runs at full strength on skin (no spatial skin weight)."""
    P = params(look, room)
    g = np.linspace(0, 1, size, dtype=np.float32)
    r, gg, b = np.meshgrid(g, g, g, indexing="ij")
    rgb = np.stack([r, gg, b], -1).reshape(-1, 3)
    out = colour(decode(rgb), P, None)
    return np.clip(out, 0, 1).reshape(size, size, size, 3).astype(np.float32)
