"""Named looks for talking-head footage: light + colour + finish, chosen per scene (kit/refs/SCENES.md §6).

A look has three parts:
  light   tone targets (where the clip's measured black point, skin and wall land) and the face key / falloff / vignette.
          This is what makes a scene dim or bright: "moody" pulls the room down far more than the face (a lamp-lit
          room); "bright" lifts everything and opens the shadows.
  colour  per-pixel colour work, baked into a 3D LUT (.cube, also usable in Resolve / Premiere): exposure and white
          balance in linear light, an optional AgX filmic tone curve (Sobotka's AgX, after MrLixm/AgXc), contrast,
          split toning, saturation in OKLab with skin protected, green control, fade, black and white mixes.
  finish  spatial: halation (warm glow around highlights), grain, sharpening.

"natural" is the approved preset_paper_studio grade (identical to kit/look/grade.py's original constants).

    python3 kit/look/looks.py sheet <clip|image> <seconds> out.jpg [--looks=natural,cinematic,...]   # every look on one frame
    python3 kit/look/looks.py bake <look> out.cube [--size=33]                                     # export a look as a LUT
    python3 kit/look/looks.py bake <look> out.cube --v2 [--room=shelf] [--size=65]                 # look v2's colour as a LUT
    python3 kit/look/looks.py match <reference.jpg> <clip> <seconds> <name>                         # a look from a reference frame
    python3 kit/look/looks.py switches visual_plan.json edl.json looks.json                         # plan looks -> grade.py --looks
"""
import json
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from look import luma, skin_weight, smoothstep  # noqa: E402

LUTS = HERE / "luts"

# ---------------------------------------------------------------------------------------------------------------- looks
LOOKS = {
    "natural": {  # preset_paper_studio v2 (2026-10-04): warm cream wall, lit face; the warmth now spares skin (scopes:
                  # skin saturation 0.149 in v1, which read slightly orange)
        "light": {"black": 0.03, "skin": 0.50, "wall": 0.87, "key": 0.20, "fall": 0.08, "vignette": 0.16, "key_warm": 0.006},
        "colour": {"mode": "paper", "skin_keep": 0.75, "skin_sat": 0.94},
        "finish": {"halation": 0.0, "grain": 0.010, "sharpen": 0.45},
        "use": "default for talking; the identity of the channel",
        "v2": {},     # look v2 (grade.py --v2): the defaults in kit/look/v2.py V2 are this look
    },
    "natural_v1": {  # the original how-i-edit grade, kept for comparison
        "light": {"black": 0.03, "skin": 0.50, "wall": 0.87, "key": 0.20, "fall": 0.08, "vignette": 0.16},
        "colour": {"mode": "paper"},
        "finish": {"halation": 0.0, "grain": 0.010, "sharpen": 0.45},
        "use": "reference only",
    },
    "bright": {  # airy morning light: lifted shadows, low contrast, clean warm-neutral highlights
        "light": {"black": 0.055, "skin": 0.56, "wall": 0.93, "key": 0.14, "fall": 0.04, "vignette": 0.06, "key_warm": 0.004},
        "colour": {"exposure": 0.0, "temp": 0.008, "tint": 0.0, "contrast": 0.95, "sat": 1.02, "skin_sat": 0.9,
                   "hi_tint": [0.008, 0.006, -0.004], "sh_tint": [0.0, 0.004, 0.008]},
        "finish": {"halation": 0.0, "grain": 0.006, "sharpen": 0.4},
        "use": "payoffs, good news, results, the end card lead-in",
        "v2": {"skin_y": 0.55, "black": 0.035, "contrast": 1.25, "skew": 0.0, "white": 1.8, "bg_stops": -0.25, "vignette": -0.15,
               "key": 0.08, "fall": 0.04, "subsat": 1.08, "split_hi": [0.012, 135.0], "split_sh": [0.005, 300.0], "halation": 0.3,
               "local": 0.10, "grain": 0.006},
    },
    "cinematic": {  # film S-curve, darker room, shaped face light, warm-yellow skin against cool-teal shadows, halation
        "light": {"black": 0.022, "skin": 0.46, "wall": 0.62, "key": 0.24, "fall": 0.14, "vignette": 0.32, "key_skin": 0.7},
        "colour": {"temp": 0.006, "curve": [[0, 0], [0.06, 0.028], [0.25, 0.205], [0.45, 0.45], [0.7, 0.745], [0.88, 0.885], [1, 0.95]],
                   "sat": 1.06, "skin_sat": 1.0, "hi_tint": [0.010, 0.003, -0.010], "sh_tint": [-0.012, 0.002, 0.016], "green_sat": 0.75, "hi_desat": 0.3,
                   "neutral_tint": [-0.012, -0.024], "tint": 0.006},
        "finish": {"halation": 0.08, "grain": 0.016, "sharpen": 0.4},
        "use": "hooks, big claims, the launch film, cold opens",
        "v2": {"skin_y": 0.47, "black": 0.016, "contrast": 1.6, "skew": -0.15, "white": 1.4, "bg_stops": -0.8, "bg_sat": 0.8,
               "vignette": -0.45, "key": 0.2, "fall": 0.16, "subsat": 1.22, "split_hi": [0.022, 140.0], "split_sh": [0.018, 300.0],
               "halation": 1.0, "local": 0.18, "grain": 0.011},
    },
    "moody": {  # dim, lamp-lit: the room falls away, the face keeps a warm pool of light, desaturated, deep (not crushed) shadows
        "light": {"black": 0.016, "skin": 0.40, "wall": 0.28, "key": 0.30, "fall": 0.18, "vignette": 0.50, "key_skin": 0.75},
        "colour": {"temp": 0.012, "curve": [[0, 0], [0.05, 0.022], [0.2, 0.15], [0.4, 0.40], [0.65, 0.665], [1, 0.9]],
                   "sat": 0.86, "skin_sat": 0.95, "hi_tint": [0.012, 0.003, -0.010], "sh_tint": [-0.006, 0.0, 0.012], "green_sat": 0.7, "hi_desat": 0.25,
                   "neutral_tint": [-0.006, -0.010], "tint": 0.006},
        "finish": {"halation": 0.06, "grain": 0.020, "sharpen": 0.35},
        "use": "setbacks, consequences, confessions, 'it all went wrong' beats",
        "v2": {"skin_y": 0.44, "black": 0.014, "contrast": 1.55, "skew": -0.1, "white": 1.3, "bg_stops": -1.2, "bg_sat": 0.7,
               "vignette": -0.6, "key": 0.35, "fall": 0.2, "sat": 0.88, "subsat": 1.12, "split_hi": [0.018, 140.0],
               "split_sh": [0.012, 310.0], "halation": 0.8, "local": 0.12, "grain": 0.012},
    },
    "film": {  # vintage stock: faded blacks, warm-yellow highlights, green-cyan shadows, halation, visible grain
        "light": {"black": 0.085, "skin": 0.48, "wall": 0.78, "key": 0.18, "fall": 0.08, "vignette": 0.28},
        "colour": {"temp": 0.02, "tint": -0.004, "curve": [[0, 0], [0.1, 0.1], [0.5, 0.52], [0.85, 0.845], [1, 0.93]],
                   "sat": 0.82, "skin_sat": 0.92, "hi_tint": [0.018, 0.016, -0.03], "sh_tint": [-0.012, 0.014, 0.002], "green_sat": 0.8, "hi_desat": 0.25,
                   "neutral_tint": [0.004, 0.012]},
        "finish": {"halation": 0.18, "grain": 0.032, "sharpen": 0.25},
        "use": "flashbacks, 'how it started', nostalgia, behind-the-scenes",
        "v2": {"skin_y": 0.50, "contrast": 1.3, "white": 1.15, "lift": 0.05, "sat": 0.88, "subsat": 1.05, "split_hi": [0.03, 150.0],
               "split_sh": [0.022, 250.0], "halation": 1.6, "grain": 0.016, "grain_size": 0.9, "vignette": -0.35, "bg_stops": -0.4},
    },
    "noir": {  # black and white: red-filter mix (skin glows), strong S-curve, deep vignette, grain
        "light": {"black": 0.02, "skin": 0.48, "wall": 0.70, "key": 0.24, "fall": 0.18, "vignette": 0.42},
        "colour": {"bw": [0.42, 0.48, 0.10], "curve": [[0, 0], [0.08, 0.03], [0.5, 0.5], [0.85, 0.9], [1, 0.97]], "tone": [0.008, 0.004, -0.006]},
        "finish": {"halation": 0.0, "grain": 0.026, "sharpen": 0.4},
        "use": "rare: one dramatic line, a quote, a 'serious' aside",
        "v2": {"bw": [0.42, 0.48, 0.10], "skin_y": 0.51, "contrast": 1.7, "vignette": -0.5, "bg_stops": -0.6, "split_hi": [0.008, 140.0],
               "split_sh": [0.004, 330.0], "halation": 0.0, "grain": 0.014},
    },
}

# ---------------------------------------------------------------------------------------------------------------- rooms
# A look's tone targets assume the channel's room: a bright cream wall that must be tamed. Other rooms need other targets
# (the same "natural" on a mid-tone bookshelf would blow the shelves out). A room profile overrides the light targets per
# look, may adjust a look's colour stage, and sets the portrait background (needs a person matte, grade.py
# --matte): gain (separation: the room a little darker than the person), blur (sigma in px at 1080p: a big-sensor depth
# of field) and sat (calm, busy backgrounds).
ROOMS = {
    "paper": {  # the channel's cream-wall studio (kit/look/grade.py's default when no room is given). The old engine's
                # looks were tuned here, so it only carries look v2 settings: the bright cream wall is the channel's
                # identity, so v2 keeps it bright and warm (a dimmed, desaturated cream wall reads as dirty grey)
        "v2": {"*": {"bg_sat": 1.0, "neutral_keep": 0.85, "split_hi": [0.035, 150.0]},
               "natural": {"skin_y": 0.55, "bg_stops": 0.0, "vignette": -0.15, "white": 2.0},
               "bright": {"bg_stops": 0.0, "vignette": -0.1, "white": 2.2},
               "cinematic": {"bg_stops": -0.5, "bg_sat": 0.9}, "moody": {"bg_stops": -0.9, "bg_sat": 0.85}},
    },
    "shelf": {  # films/expensewaale (2026-10-04): bookshelves behind, background ~0.45 luma, as bright as the face.
                # Skin is on the skin line already (+0.7 deg on the face box); lifting the face lifts its chroma, so
                # skin saturation comes down (0.62), the warm paper tint is halved and the key carries no warm tint
        "colour": {"natural": {"sat": 1.0, "skin_sat": 0.62, "warm": 0.5}, "bright": {"skin_sat": 0.76}},
        "finish": {"sharpen": 0.22},                   # true 1080p (not upscaled): strong sharpening only shows HEVC blocks
        "light": {"natural": {"black": 0.012, "skin": 0.47, "wall": 0.52, "key": 0.20, "vignette": 0.14, "key_warm": 0.0},
                  "bright": {"black": 0.012, "skin": 0.51, "wall": 0.58, "key": 0.15, "vignette": 0.08, "key_warm": 0.0},
                  # dim looks bring the whole room down with the tone curve and put the face back with a strong, wide
                  # key (a lamp): no matte is involved in the darkening, so nothing can outline the hair
                  "cinematic": {"black": 0.02, "skin": 0.37, "wall": 0.39, "key": 0.34, "vignette": 0.30, "key_warm": 0.0, "key_skin": 0.5},
                  "moody": {"black": 0.014, "skin": 0.25, "wall": 0.27, "key": 0.65, "fall": 0.16, "vignette": 0.42, "key_warm": 0.0, "key_skin": 0.45}},
        "bg": {"natural": {"gain": 0.92, "blur": 5.0, "sat": 0.82}, "bright": {"gain": 1.0, "blur": 5.0, "sat": 0.88},
               "cinematic": {"gain": 1.0, "blur": 8.0, "sat": 0.8}, "moody": {"gain": 1.0, "blur": 9.0, "sat": 0.75}},
        # look v2 (grade.py --v2): exposure and white balance come from the face, so a room only sets the portrait
        # background (defocus sigma in px at 1080p; the dim and calm are the look's bg_stops / bg_sat). The shelves are
        # as bright as the face, so natural sets them back -0.7 stop (-0.5 left the face only ~0.08 above them)
        "v2": {"*": {"bg_blur": 5.0}, "natural": {"bg_stops": -0.7}, "cinematic": {"bg_blur": 8.0}, "moody": {"bg_blur": 9.0}},
    },
}


def look_for(name: str, room: str | None = None) -> dict:
    """The look with a room's overrides applied (light targets, colour additions, portrait background)."""
    L = json.loads(json.dumps(LOOKS[name]))
    if not room:
        return L
    R = ROOMS[room]
    L["light"].update(R.get("light", {}).get(name, {}))
    L["colour"].update(R.get("colour", {}).get(name, {}))
    L["finish"].update(R.get("finish", {}))
    bg = R.get("bg", {})
    L["bg"] = bg.get(name) or bg.get("natural")
    return L


# ---------------------------------------------------------------------------------------------------------------- colour math
def decode(v):                      # Rec.709 / BT.1886 display -> linear light
    return np.power(np.clip(v, 0, 1), 2.4)


def encode(v):
    return np.power(np.clip(v, 0, 1), 1 / 2.4)


_M1 = np.array([[0.4122214708, 0.5363325363, 0.0514459929], [0.2119034982, 0.6806995451, 0.1073969566], [0.0883024619, 0.2817188376, 0.6299787005]])
_M2 = np.array([[0.2104542553, 0.7936177850, -0.0040720468], [1.9779984951, -2.4285922050, 0.4505937099], [0.0259040371, 0.7827717662, -0.8086757660]])


def oklab(lin):                     # linear sRGB -> OKLab (Björn Ottosson)
    lms = np.cbrt(np.maximum(lin @ _M1.T, 0))
    return lms @ _M2.T


def oklab_inv(lab):
    lms = lab @ np.linalg.inv(_M2).T
    return np.maximum(lms ** 3 @ np.linalg.inv(_M1).T, 0)


# AgX (Troy Sobotka), the minimal form used by MrLixm/AgXc and Blender: inset matrix, log2 encoding, sigmoid, outset
_AGX = np.array([[0.842479062253094, 0.0784335999999992, 0.0792237451477643],
                 [0.0423282422610123, 0.878468636469772, 0.0791661274605434],
                 [0.0423756549057051, 0.0784336, 0.879142973793104]])
_AGX_INV = np.linalg.inv(_AGX)
_EV0, _EV1 = -12.47393, 4.026069


def agx(lin):
    """scene-linear Rec.709 -> display-encoded Rec.709 (filmic: soft highlight roll-off, smooth saturation)."""
    v = np.maximum(lin, 1e-10) @ _AGX.T
    v = (np.clip(np.log2(v), _EV0, _EV1) - _EV0) / (_EV1 - _EV0)
    x2 = v * v; x4 = x2 * x2
    v = 15.5 * x4 * x2 - 40.14 * x4 * v + 31.96 * x4 - 6.868 * x2 * v + 0.4298 * x2 + 0.1191 * v - 0.00232
    v = v @ _AGX_INV.T                                              # display-encoded (~2.2): re-express as our 2.4 encoding
    return encode(np.power(np.clip(v, 0, 1), 2.2))


def lum(v):
    return v[..., 0] * 0.2126 + v[..., 1] * 0.7152 + v[..., 2] * 0.0722


def curve(y, pts):
    """Monotone cubic (Fritsch-Carlson) through [(in, out), ...] control points: a film S-curve on display luminance."""
    xs = np.array([p[0] for p in pts], float); ys = np.array([p[1] for p in pts], float)
    h = np.diff(xs); d = np.diff(ys) / h
    m = np.zeros(len(xs)); m[0], m[-1] = d[0], d[-1]
    for i in range(1, len(xs) - 1):
        m[i] = 0 if d[i - 1] * d[i] <= 0 else 3 * (h[i - 1] + h[i]) / ((2 * h[i] + h[i - 1]) / d[i - 1] + (h[i] + 2 * h[i - 1]) / d[i])
    yi = np.clip(y, 0, 1)
    i = np.clip(np.searchsorted(xs, yi) - 1, 0, len(xs) - 2)
    t = (yi - xs[i]) / h[i]
    t2, t3 = t * t, t * t * t
    return (2 * t3 - 3 * t2 + 1) * ys[i] + (t3 - 2 * t2 + t) * h[i] * m[i] + (-2 * t3 + 3 * t2) * ys[i + 1] + (t3 - t2) * h[i] * m[i + 1]


def colour_op(rgb, c):
    """The look's colour work on display-referred RGB in 0..1 (shape ..., 3). Pure per-pixel, so it bakes into a LUT."""
    x = rgb.astype(np.float64)
    if "wb" in c:                                                   # a room's camera cast, at constant luminance
        g = np.array(c["wb"], float)
        x = x * (g / (g @ np.array([0.2126, 0.7152, 0.0722])))
    if c.get("mode") == "paper":                                    # natural: exactly kit/look/grade.py's colour stage
        yo = lum(x)
        hi = smoothstep(0.55, 1.0, yo)[..., None]
        mid = (smoothstep(0.15, 0.5, yo) * (1 - 0.4 * smoothstep(0.85, 1.0, yo)))[..., None]
        sw = skin_weight(np.clip(x, 0, 1))[..., None]
        keep = 1 - c.get("skin_keep", 0.0) * sw                             # v2: the warm tint spares skin (wall stays cream)
        x = x + (hi * np.array([0.018, 0.008, -0.016]) + mid * np.array([0.013, 0.005, -0.012])) * keep * c.get("warm", 1.0)
        base = c.get("sat", 1.10)                                           # rooms may lower the overall saturation
        k = base + (c.get("skin_sat", 1.0) - base) * skin_weight(np.clip(x, 0, 1))[..., None]
        yo = lum(x)[..., None]
        return np.clip(yo + (x - yo) * k, 0, 1)
    if c.get("bw"):
        y = x @ np.array(c["bw"])
        x = np.stack([y, y, y], -1)
    lin = decode(x) * 2.0 ** c.get("exposure", 0.0)
    t, g = c.get("temp", 0.0), c.get("tint", 0.0)
    gains = np.array([1 + t, 1 - g, 1 - t])
    lin = lin * (gains / (gains @ np.array([0.2126, 0.7152, 0.0722])))       # white balance at constant luminance
    x = agx(lin * 1.6) if c.get("agx") else encode(lin)                     # AgX expects scene exposure (~mid grey 0.18)
    if "curve" in c:                                                        # film S-curve on luminance (hue kept)
        y = lum(x)
        x = x * (curve(y, c["curve"]) / np.maximum(y, 1e-5))[..., None]
    if c.get("hi_desat"):                                                   # highlights lose saturation, like film
        y = lum(np.clip(x, 0, 1))[..., None]
        k = c["hi_desat"] * smoothstep(0.6, 1.0, y)
        x = y + (x - y) * (1 - k)
    ct = c.get("contrast", 1.0)
    if ct != 1.0:                                                           # contrast around mid grey, soft at the ends
        y = lum(x)
        yc = 0.5 + (y - 0.5) * ct
        x = x * (np.clip(yc, 0, 1) / np.maximum(y, 1e-5))[..., None]
    y = lum(np.clip(x, 0, 1))[..., None]
    if "sh_tint" in c:
        x = x + (1 - smoothstep(0.05, 0.5, y)) * np.array(c["sh_tint"])
    if "hi_tint" in c:
        x = x + smoothstep(0.45, 1.0, y) * np.array(c["hi_tint"])
    if "tone" in c:
        x = x + np.array(c["tone"])
    if not c.get("bw"):
        lab = oklab(decode(np.clip(x, 0, 1)))
        C, h = np.hypot(lab[..., 1], lab[..., 2]), np.degrees(np.arctan2(lab[..., 2], lab[..., 1]))
        skin = np.exp(-((((h - 58 + 180) % 360) - 180) / 22) ** 2) * smoothstep(0.02, 0.06, C)   # skin hue ~58 deg in OKLab
        green = np.exp(-((((h - 140 + 180) % 360) - 180) / 30) ** 2)
        s = c.get("sat", 1.0) + (c.get("skin_sat", 1.0) - c.get("sat", 1.0)) * skin
        s = s * (1 + (c.get("green_sat", 1.0) - 1) * green)
        lab[..., 1] *= s; lab[..., 2] *= s
        if "neutral_tint" in c:                                             # tint only the low-chroma colours (walls, greys):
            w = (1 - smoothstep(0.015, 0.06, C)) * smoothstep(0.08, 0.3, lab[..., 0])   # skin keeps its colour
            lab[..., 1] += w * c["neutral_tint"][0]; lab[..., 2] += w * c["neutral_tint"][1]
        x = encode(oklab_inv(lab))
    if "white" in c:                                                        # film: highlights never reach paper white
        w = c["white"]
        x = np.where(x > 0.7, 0.7 + (w - 0.7) * (1 - np.exp(-(x - 0.7) / (w - 0.7))), x)
    return np.clip(x, 0, 1)


# ---------------------------------------------------------------------------------------------------------------- LUTs
def bake(name: str, size: int = 33, colour: dict | None = None, tag: str = "") -> np.ndarray:
    """The look's colour stage as a size^3 LUT, indexed lut[r, g, b] -> rgb (cached in kit/look/luts/<name>.npy).
    `colour` replaces the look's own colour spec (a room's version), cached under <name>_<tag>."""
    LUTS.mkdir(exist_ok=True)
    colour = colour or LOOKS[name]["colour"]
    name = f"{name}_{tag}" if tag else name
    cache = LUTS / f"{name}_{size}.npy"
    spec = json.dumps(colour, sort_keys=True)
    meta = LUTS / f"{name}_{size}.json"
    if cache.exists() and meta.exists() and meta.read_text() == spec:
        return np.load(cache)
    g = np.linspace(0, 1, size)
    r, gg, b = np.meshgrid(g, g, g, indexing="ij")
    lut = colour_op(np.stack([r, gg, b], -1), colour).astype(np.float32)
    np.save(cache, lut)
    meta.write_text(spec)
    return lut


def write_cube(lut: np.ndarray, path: Path, title: str):
    n = lut.shape[0]
    with open(path, "w") as f:
        f.write(f'TITLE "{title}"\nLUT_3D_SIZE {n}\nDOMAIN_MIN 0 0 0\nDOMAIN_MAX 1 1 1\n')
        for b in range(n):                       # .cube order: red fastest, then green, then blue
            for gg in range(n):
                for r in range(n):
                    v = lut[r, gg, b]
                    f.write(f"{v[0]:.6f} {v[1]:.6f} {v[2]:.6f}\n")


def apply_lut(img: np.ndarray, lut: np.ndarray) -> np.ndarray:
    """Trilinear lookup of float32 HxWx3 (0..1) through lut[r, g, b]."""
    n = lut.shape[0]
    s = np.clip(img, 0, 1) * (n - 1)
    i0 = np.minimum(s.astype(np.int32), n - 2)
    f = s - i0
    r0, g0, b0 = i0[..., 0], i0[..., 1], i0[..., 2]
    fr, fg, fb = f[..., 0:1], f[..., 1:2], f[..., 2:3]
    c = lambda dr, dg, db: lut[r0 + dr, g0 + dg, b0 + db]
    c00 = c(0, 0, 0) * (1 - fr) + c(1, 0, 0) * fr
    c01 = c(0, 0, 1) * (1 - fr) + c(1, 0, 1) * fr
    c10 = c(0, 1, 0) * (1 - fr) + c(1, 1, 0) * fr
    c11 = c(0, 1, 1) * (1 - fr) + c(1, 1, 1) * fr
    return ((c00 * (1 - fg) + c10 * fg) * (1 - fb) + (c01 * (1 - fg) + c11 * fg) * fb).astype(np.float32)


# ---------------------------------------------------------------------------------------------------------------- finish
def halation(img: np.ndarray, amount: float) -> np.ndarray:
    """Film halation: light from the brightest areas bleeds back warm-red around them (computed at 1/4 size)."""
    if amount <= 0:
        return img
    H, W = img.shape[:2]
    y = lum(img)
    hot = np.clip((y - 0.62) / 0.38, 0, 1).astype(np.float32)
    small = cv2.resize(hot, (W // 4, H // 4), interpolation=cv2.INTER_AREA)
    glow = cv2.resize(cv2.GaussianBlur(small, (0, 0), 6) * 0.6 + cv2.GaussianBlur(small, (0, 0), 16) * 0.4, (W, H), interpolation=cv2.INTER_LINEAR)
    return np.clip(img + amount * glow[..., None] * np.array([1.0, 0.38, 0.14], np.float32), 0, 1)


# ---------------------------------------------------------------------------------------------------------------- reference matching
def match_look(ref_img: np.ndarray, src_img: np.ndarray, strength: float = 0.7) -> dict:
    """A colour transform that moves the source frame's palette toward a reference frame: the linear Monge-Kantorovich
    mapping (Pitie & Kokaram 2007) between the two colour distributions, in OKLab. Returned as a look 'colour' spec
    holding the 3x3 map and offsets (baked into a LUT like any other look)."""
    def stats(img):
        lab = oklab(decode(cv2.resize(img, (320, 180)).reshape(-1, 3)))
        return lab.mean(0), np.cov(lab.T) + np.eye(3) * 1e-6
    mu_s, cs = stats(src_img)
    mu_r, cr = stats(ref_img)

    def sqrtm(m):
        w, v = np.linalg.eigh(m)
        return v @ np.diag(np.sqrt(np.maximum(w, 1e-12))) @ v.T
    cs_h = sqrtm(cs)
    cs_hi = np.linalg.inv(cs_h)
    T = cs_hi @ sqrtm(cs_h @ cr @ cs_h) @ cs_hi
    T = np.eye(3) + strength * (T - np.eye(3))
    mu = mu_s + strength * (mu_r - mu_s)
    return {"mkl": {"T": T.tolist(), "mu_s": mu_s.tolist(), "mu": mu.tolist()}}


def _mkl_op(rgb, m):
    lab = oklab(decode(rgb))
    lab = (lab - np.array(m["mu_s"])) @ np.array(m["T"]).T + np.array(m["mu"])
    return encode(oklab_inv(lab))


_colour_op_base = colour_op


def colour_op(rgb, c):  # noqa: F811  (extends the base op with reference-matched looks)
    if "mkl" in c:
        return np.clip(_mkl_op(np.clip(rgb, 0, 1), c["mkl"]), 0, 1)
    return _colour_op_base(rgb, c)


def register_custom():
    """Looks saved by `match` (kit/look/luts/custom_<name>.json) become available by name."""
    for f in LUTS.glob("custom_*.json"):
        LOOKS[f.stem[7:]] = json.loads(f.read_text())


register_custom()


# ---------------------------------------------------------------------------------------------------------------- CLI
def frame_rgb(src: str, t: float) -> np.ndarray:
    if src.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
        return cv2.cvtColor(cv2.imread(src), cv2.COLOR_BGR2RGB).astype(np.float32) / 255
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", src, "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True, check=True).stdout
    return cv2.cvtColor(cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB).astype(np.float32) / 255


def main():
    cmd = sys.argv[1]
    if cmd == "bake":
        name, out = sys.argv[2], Path(sys.argv[3])
        size = int(next((a.split("=")[1] for a in sys.argv if a.startswith("--size=")), 33))
        if "--v2" in sys.argv:                                               # look v2's per-pixel colour (see v2.bake)
            import v2
            room = next((a.split("=")[1] for a in sys.argv if a.startswith("--room=")), None)
            write_cube(v2.bake(name, room, size), out, f"look v2 {name}" + (f" ({room})" if room else ""))
            print(f"{out}: look v2 {name} as a {size}^3 LUT (input: balanced Rec.709; no light, texture or skin protection)")
            return
        write_cube(bake(name, size), out, f"paper_studio {name}")
        print(f"{out}: {name} as a {size}^3 LUT")
    elif cmd == "switches":                                                  # visual plan -> grade.py --looks file
        plan, edl, out = json.load(open(sys.argv[2])), json.load(open(sys.argv[3])), Path(sys.argv[4])
        words = {w["i"]: w["t"] for w in edl["words"]}
        cuts = sorted({round(p["out_a"], 3) for p in edl["pieces"]})
        sw, cur = [{"t": 0.0, "look": "natural"}], "natural"
        for p in plan["passages"]:
            look = p.get("look", "natural")
            if look == cur:
                continue
            if look not in LOOKS:
                raise SystemExit(f"{p.get('id')}: unknown look {look!r}")
            t = words[p["words"][0]] if "words" in p else float(p["t"][0])
            if "look_at" in p:                                              # a word index: the motivated moment (lights dim on "gone")
                t = words[p["look_at"]]
            near = min(cuts, key=lambda c: abs(c - t))
            fade = float(p.get("look_fade", 0.0 if abs(near - t) < 0.25 else 0.9))
            sw.append({"t": round(near if fade == 0 else t, 3), "look": look, "fade": fade})
            cur = look
        out.write_text(json.dumps(sw, indent=1))
        print(f"{out}: {len(sw)} look switches")
    elif cmd == "match":
        ref, src, t, name = sys.argv[2], sys.argv[3], float(sys.argv[4]), sys.argv[5]
        strength = float(next((a.split("=")[1] for a in sys.argv if a.startswith("--strength=")), 0.7))
        look = {"light": dict(LOOKS["natural"]["light"]), "colour": match_look(frame_rgb(ref, 0), frame_rgb(src, t), strength),
                "finish": dict(LOOKS["natural"]["finish"]), "use": f"matched to {Path(ref).name}"}
        LUTS.mkdir(exist_ok=True)
        (LUTS / f"custom_{name}.json").write_text(json.dumps(look, indent=1))
        print(f"look '{name}' saved (kit/look/luts/custom_{name}.json)")
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
