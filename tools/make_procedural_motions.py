"""Make the missing motions from the existing artwork, by code (no image generator).

    python tools/make_procedural_motions.py            # all
    python tools/make_procedural_motions.py 摇头 说话   # some

Body motions are affine transforms around the feet (256, 470): turn, squash and
stretch, lift. Faces are redrawn in place: the eyes and mouth of 待机/01 are painted
over with the surrounding skin and new shapes are drawn (happy arcs, half-closed
lids, an open mouth). Small effects (heart, stars, z) are drawn on top. Every frame
is a whole picture: nothing is cross-faded, so there is no ghosting.

Not made here (they need new drawing, ANIMATION_BRIEF.md): 入睡, 起床, 待机 redraw.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ART = Path(__file__).resolve().parents[1] / "src" / "meihua" / "assets" / "xiaogua"
PIVOT = (256.0, 470.0)
INK = (38, 52, 24, 255)                  # the eyes' dark green-black
PINK = (239, 160, 168, 255)
BLUSH = (240, 170, 160)
STAR = (246, 215, 122, 255)
Z_INK = (110, 128, 96, 255)
LEFT_EYE, RIGHT_EYE = (216.5, 274.5), (305.5, 274.5)     # centres in 待机/01
# 睡着/01's closed eyes, measured there and taken back to 待机's size (÷ SLEEP_SCALE around the feet)
SLEEP_EYES = ((209.5, 262.0), (303.0, 265.0))
SLEEP_EYE = (31, 30, 10, 170, 5.6)                       # box w, h, arc from/to degrees, stroke
MOUTH = (261.0, 293.0)
CHEEKS = ((186.0, 292.0), (336.0, 292.0))
SS = 4                                    # supersampling for smooth strokes


def load(name: str) -> Image.Image:
    return Image.open(ART / name).convert("RGBA")


IDLE = None


def idle() -> Image.Image:
    global IDLE
    if IDLE is None:
        IDLE = load("待机/01.png")
    return IDLE.copy()


# ---------------------------------------------------------------- body motion

def move(image: Image.Image, angle: float = 0.0, sx: float = 1.0, sy: float = 1.0, dy: float = 0.0) -> Image.Image:
    """Turn by `angle` degrees (clockwise), scale, then lift by -dy, all around the feet."""
    px, py = PIVOT
    t = math.radians(angle)
    cos, sin = math.cos(t), math.sin(t)
    # output p -> input q = P + S^-1 R(-t) (p - P - (0, dy))
    a, b = cos / sx, sin / sx
    d, e = -sin / sy, cos / sy
    c = px - a * px - b * (py + dy)
    f = py - d * px - e * (py + dy)
    return image.transform(image.size, Image.AFFINE, (a, b, c, d, e, f), resample=Image.BICUBIC)


def settle(image: Image.Image) -> Image.Image:
    """Put the feet back: lowest point on y=470, feet centred on x=256 (after a turn)."""
    alpha = np.asarray(image.getchannel("A")) >= 96
    bottom = int(np.nonzero(alpha.any(axis=1))[0].max())
    xs = np.nonzero(alpha[bottom - 40: bottom + 1].any(axis=0))[0]
    feet_x = (xs.min() + xs.max()) / 2
    out = Image.new("RGBA", image.size, (0, 0, 0, 0))
    out.alpha_composite(image, (round(256 - feet_x), 470 - bottom))
    return out


def turn(image: Image.Image, angle: float) -> Image.Image:
    """Lean the body (a head tilt or shake) around its middle, then stand it back on its feet."""
    if not angle:
        return image
    global PIVOT
    keep, PIVOT = PIVOT, (256.0, 300.0)
    try:
        return settle(move(image, angle))
    finally:
        PIVOT = keep


# ---------------------------------------------------------------- face

def _patch(image: Image.Image, boxes: list[tuple[float, float, float, float]]) -> Image.Image:
    """Paint over the given boxes with the skin around them (normalized blur fill)."""
    rgba = np.asarray(image).astype(np.float32)
    mask = Image.new("L", image.size, 0)
    draw = ImageDraw.Draw(mask)
    for x0, y0, x1, y1 in boxes:
        draw.rounded_rectangle((x0, y0, x1, y1), radius=6, fill=255)
    m = np.asarray(mask.filter(ImageFilter.MaxFilter(5))).astype(np.float32) / 255.0
    keep = 1.0 - m
    filled = np.empty_like(rgba)
    weight = Image.fromarray((keep * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(9))
    w = np.asarray(weight).astype(np.float32) / 255.0 + 1e-4
    for ch in range(3):
        layer = Image.fromarray((rgba[..., ch] * keep).astype(np.uint8)).filter(ImageFilter.GaussianBlur(9))
        filled[..., ch] = np.asarray(layer).astype(np.float32) / w
    filled[..., 3] = rgba[..., 3]
    soft = np.asarray(mask.filter(ImageFilter.GaussianBlur(1.5))).astype(np.float32)[..., None] / 255.0
    out = rgba * (1 - soft) + filled * soft
    out[..., 3] = rgba[..., 3]
    # a little grain so the patch is not flatter than the paper texture around it
    rng = np.random.default_rng(7)
    grain = rng.normal(0, 2.0, out.shape[:2])[..., None] * soft
    out[..., :3] = np.clip(out[..., :3] + grain, 0, 255)
    return Image.fromarray(out.astype(np.uint8), "RGBA")


def clear_eyes(image: Image.Image) -> Image.Image:
    return _patch(image, [(207, 259, 227, 290), (295, 259, 316, 290)])


def clear_mouth(image: Image.Image) -> Image.Image:
    return _patch(image, [(243, 284, 279, 302)])


class Pen:
    """Draw on a 4x layer, then shrink onto the frame: smooth, slightly soft strokes like the art."""

    def __init__(self, size=(512, 512)):
        self.layer = Image.new("RGBA", (size[0] * SS, size[1] * SS), (0, 0, 0, 0))
        self.draw = ImageDraw.Draw(self.layer)

    @staticmethod
    def _s(points):
        return [(x * SS, y * SS) for x, y in points]

    def arc(self, centre, w, h, start, end, width=3.6, fill=INK):
        x, y = centre
        box = [(x - w / 2) * SS, (y - h / 2) * SS, (x + w / 2) * SS, (y + h / 2) * SS]
        self.draw.arc(box, start, end, fill=fill, width=round(width * SS))

    def ellipse(self, centre, w, h, fill=INK, outline=None, width=0):
        x, y = centre
        box = [(x - w / 2) * SS, (y - h / 2) * SS, (x + w / 2) * SS, (y + h / 2) * SS]
        self.draw.ellipse(box, fill=fill, outline=outline, width=round(width * SS))

    def line(self, points, width=3.4, fill=INK):
        self.draw.line(self._s(points), fill=fill, width=round(width * SS), joint="curve")
        for x, y in points[::max(1, len(points) - 1)]:
            r = width / 2
            self.ellipse((x, y), 2 * r, 2 * r, fill=fill)

    def polygon(self, points, fill):
        self.draw.polygon(self._s(points), fill=fill)

    def onto(self, image: Image.Image) -> Image.Image:
        small = self.layer.resize(image.size, Image.LANCZOS)
        out = image.copy()
        out.alpha_composite(small)
        return out


def eyes(pen: Pen, kind: str):
    for cx, cy in (LEFT_EYE, RIGHT_EYE):
        if kind == "open":
            pen.ellipse((cx, cy), 14, 24)
            pen.ellipse((cx + 2.5, cy - 5.5), 4.5, 5.5, fill=(255, 255, 255, 235))
        elif kind == "happy":                     # ^ ^
            pen.arc((cx, cy + 4), 19, 14, 200, 340, width=3.8)
        elif kind == "closed":                    # sleepy lines, curved down
            pen.arc((cx, cy - 2), 18, 10, 20, 160, width=3.6)
        elif kind == "half":                      # heavy lids: lower half of the eye under a flat lid
            pen.draw.pieslice([(cx - 7) * SS, (cy - 8) * SS, (cx + 7) * SS, (cy + 12) * SS], 0, 180, fill=INK)
            pen.line([(cx - 9, cy + 1), (cx + 9, cy + 1)], width=3.2)
        elif kind == "squint":                    # nearly shut
            pen.line([(cx - 8, cy + 4), (cx + 8, cy + 4)], width=3.4)
    if kind == "asleep":                          # 睡着's eyes (bigger, bolder arcs), in 待机/01's frame
        for centre in SLEEP_EYES:
            pen.arc(centre, *SLEEP_EYE)


def mouth(pen: Pen, kind: str):
    x, y = MOUTH
    if kind == "smile":
        pen.arc((x, y - 4), 26, 16, 25, 155, width=3.4)
    elif kind == "small":
        pen.ellipse((x, y), 10, 8)
    elif kind == "mid":
        pen.ellipse((x, y + 1), 15, 12)
        pen.ellipse((x, y + 4), 9, 4.5, fill=PINK)
    elif kind == "big":
        pen.ellipse((x, y + 2), 19, 16)
        pen.ellipse((x, y + 6), 12, 6, fill=PINK)
    elif kind == "o":
        pen.ellipse((x, y + 1), 11, 12)
        pen.ellipse((x, y + 3), 6, 4, fill=PINK)
    elif kind == "wavy":                          # worried
        pts = [(x - 12 + i, y + 1.5 * math.sin(i / 3.2)) for i in range(0, 25, 2)]
        pen.line(pts, width=3.2)
    elif kind == "yawn":
        pen.ellipse((x, y + 4), 15, 22)
        pen.ellipse((x, y + 10), 9, 7, fill=PINK)


def brows(pen: Pen, kind: str):
    (lx, ly), (rx, ry) = LEFT_EYE, RIGHT_EYE
    if kind == "worried":                         # inner ends up
        pen.line([(lx - 9, ly - 17), (lx + 7, ly - 21)], width=2.8, fill=(70, 88, 52, 220))
        pen.line([(rx - 7, ry - 21), (rx + 9, ry - 17)], width=2.8, fill=(70, 88, 52, 220))
    elif kind == "raised":                        # one brow up, curious
        pen.arc((rx, ry - 20), 16, 8, 200, 340, width=2.8, fill=(70, 88, 52, 220))


def blush(image: Image.Image, strength: float) -> Image.Image:
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    for x, y in CHEEKS:
        draw.ellipse((x - 17, y - 11, x + 17, y + 11), fill=BLUSH + (int(110 * strength),))
    layer = layer.filter(ImageFilter.GaussianBlur(5))
    alpha = np.asarray(layer.getchannel("A")).astype(np.float32) * (np.asarray(image.getchannel("A")) / 255.0)
    layer.putalpha(Image.fromarray(alpha.astype(np.uint8)))
    out = image.copy()
    out.alpha_composite(layer)
    return out


def face(image: Image.Image, eye: str | None = None, mouth_kind: str | None = None, brow: str | None = None,
         cheeks: float = 0.0) -> Image.Image:
    """Redraw parts of 待机/01's face (before any transform, so the face moves with the body)."""
    if eye:
        image = clear_eyes(image)
    if mouth_kind:
        image = clear_mouth(image)
    if cheeks:
        image = blush(image, cheeks)
    pen = Pen(image.size)
    if eye:
        eyes(pen, eye)
    if mouth_kind:
        mouth(pen, mouth_kind)
    if brow:
        brows(pen, brow)
    return pen.onto(image)


# ---------------------------------------------------------------- effects

def heart(image: Image.Image, centre, size: float) -> Image.Image:
    pen = Pen(image.size)
    x, y = centre
    r = size / 4
    pen.ellipse((x - r, y - r / 2), 2 * r + 1, 2 * r + 1, fill=PINK)
    pen.ellipse((x + r, y - r / 2), 2 * r + 1, 2 * r + 1, fill=PINK)
    pen.polygon([(x - 2 * r, y - r / 4), (x + 2 * r, y - r / 4), (x, y + 1.7 * r)], fill=PINK)
    return pen.onto(image)


def star(pen: Pen, centre, size: float):
    x, y = centre
    points = []
    for i in range(10):
        radius = size / 2 if i % 2 == 0 else size / 4.5
        angle = -math.pi / 2 + i * math.pi / 5
        points.append((x + radius * math.cos(angle), y + radius * math.sin(angle)))
    pen.polygon(points, fill=STAR)


def stars(image: Image.Image, spots) -> Image.Image:
    pen = Pen(image.size)
    for centre, size in spots:
        star(pen, centre, size)
    return pen.onto(image)


def zees(image: Image.Image, spots) -> Image.Image:
    pen = Pen(image.size)
    for (x, y), size in spots:
        s = size
        pen.line([(x - s / 2, y - s / 2), (x + s / 2, y - s / 2), (x - s / 2, y + s / 2), (x + s / 2, y + s / 2)],
                 width=max(2.4, s / 6), fill=Z_INK)
    return pen.onto(image)


# ---------------------------------------------------------------- the motions

def shake():
    worried = face(idle(), mouth_kind="wavy", brow="worried")
    angles = [0, 0, -7, 0, 7, 0, -4, 4, 0, 0]
    frames = [idle()] + [turn(worried, a) for a in angles[1:-1]] + [idle()]
    return frames, {"frame_ms": 90, "playback": "forward", "kind": "once"}


def tilt():
    plans = [(0, None, None), (2.5, None, None), (5, None, None), (7, "o", None), (9, "o", "raised"), (10, "o", "raised")]
    frames = [turn(face(idle(), mouth_kind=m, brow=b) if (m or b) else idle(), a) for a, m, b in plans]
    return frames, {"frame_ms": 100, "playback": "forward", "kind": "hold"}


def talk():
    plans = [("smile", 1.0), ("small", 1.004), ("mid", 1.008), ("big", 1.012),
             ("mid", 1.009), ("small", 1.005), ("mid", 1.007), ("o", 1.002)]
    frames = [idle() if m == "smile" else move(face(idle(), mouth_kind=m), sy=sy) for m, sy in plans]
    return frames, {"frame_ms": 90, "playback": "pingpong", "kind": "loop"}


def patted():
    happy = face(idle(), eye="happy", cheeks=0.6)
    happier = face(idle(), eye="happy", cheeks=1.0)
    frames = [
        idle(),
        happy,
        move(happier, sx=1.015, sy=0.97),
        heart(move(happier, sx=1.022, sy=0.955), (256, 50), 40),
        heart(move(happier, sx=1.01, sy=0.98), (264, 40), 48),
        heart(move(happier, sx=0.99, sy=1.02), (272, 30), 40),
        heart(move(happy, sx=0.997, sy=1.006), (280, 22), 28),
        happy,
        face(idle(), cheeks=0.4),
    ]
    return frames, {"frame_ms": 90, "playback": "forward", "kind": "once"}


def drowsy():
    half = face(idle(), eye="half")
    squint = face(idle(), eye="squint")
    closed = face(idle(), eye="closed")
    frames = [
        half,
        move(half, sy=0.995),
        move(squint, sy=0.99),
        zees(move(squint, sy=0.986), [((338, 92), 14)]),
        zees(move(closed, sy=0.982), [((342, 84), 15)]),
        zees(move(closed, sy=0.98), [((346, 74), 16), ((370, 54), 11)]),
        zees(move(closed, sy=0.979), [((350, 64), 17), ((376, 42), 12)]),
        zees(move(closed, sy=0.978), [((354, 56), 18), ((382, 32), 13)]),
    ]
    return frames, {"frame_ms": 140, "playback": "pingpong", "kind": "loop"}


def cheer():
    source = [load(f"加油/{i:02d}.png") for i in range(1, 13)]
    lifts = [0, 0, -10, -22, -28, -26, -16, -5, 0, 0, 0, 0]       # low: the ground shadow is drawn in
    squash = {1: (1.03, 0.96), 8: (1.035, 0.955), 9: (1.01, 0.99)}
    spots = {3: [((140, 120), 34)], 4: [((136, 108), 40), ((380, 96), 32)], 5: [((126, 96), 44), ((388, 84), 38), ((262, 30), 28)],
             6: [((120, 92), 36), ((396, 78), 42), ((262, 22), 30)], 7: [((400, 88), 30), ((118, 102), 26)]}
    frames = []
    for i, frame in enumerate(source):
        sx, sy = squash.get(i, (1.0, 1.0))
        out = move(frame, sx=sx, sy=sy, dy=lifts[i])
        if i in spots:
            out = stars(out, spots[i])
        frames.append(out)
    return frames, {"frame_ms": 80, "playback": "forward", "kind": "once"}


def entrance():
    wave = [load(f"招手/{i:02d}.png") for i in (4, 7, 10, 13)]
    happy = face(idle(), eye="happy")
    frames = [                                   # grows out of the ground, pops up, lands, waves
        move(idle(), sx=0.22, sy=0.22),
        move(happy, sx=0.5, sy=0.55),
        move(happy, sx=0.86, sy=0.95, dy=-14),
        move(happy, sx=1.0, sy=1.03, dy=-30),
        move(idle(), sx=1.04, sy=0.95),
        move(idle(), sx=0.99, sy=1.02),
        *wave,
        idle(),
    ]
    return frames, {"frame_ms": 80, "playback": "forward", "kind": "once"}


def split_idle() -> tuple[Image.Image, Image.Image]:
    """待机/01 -> (body, ground shadow). The shadow is the cream patch under the feet (g-b below 32);
    the feet themselves are green (g-b 37-50)."""
    image = idle()
    rgba = np.asarray(image).astype(np.int16)
    g_b = rgba[..., 1] - rgba[..., 2]
    rows = np.arange(512)[:, None]
    core = ((rgba[..., 3] >= 110) & (g_b >= 32)) | ((rows < 425) & (rgba[..., 3] > 0))
    mask = Image.fromarray((core * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(3))
    mask = np.asarray(mask.filter(ImageFilter.GaussianBlur(0.7))).astype(np.float32) / 255.0
    mask = np.maximum(mask, (rows < 425).astype(np.float32))
    base = np.asarray(image).astype(np.float32)
    body, shadow = base.copy(), base.copy()
    body[..., 3] *= mask
    shadow[..., 3] *= 1.0 - mask
    return (Image.fromarray(body.astype(np.uint8), "RGBA"), Image.fromarray(shadow.astype(np.uint8), "RGBA"))


def shade(shadow: Image.Image, size: float, strength: float) -> Image.Image:
    """The ground shadow shrunk around its own centre and faded (the body is higher up)."""
    if strength <= 0:
        return Image.new("RGBA", shadow.size, (0, 0, 0, 0))
    global PIVOT
    keep, PIVOT = PIVOT, (256.0, 452.0)
    try:
        out = move(shadow, sx=size, sy=size)
    finally:
        PIVOT = keep
    alpha = np.asarray(out.getchannel("A")).astype(np.float32) * strength
    out.putalpha(Image.fromarray(alpha.astype(np.uint8)))
    return out


def body_face(eye: str | None, mouth_kind: str | None) -> Image.Image:
    """The body layer with a different face (the face is redrawn before splitting off the shadow)."""
    global IDLE
    keep = IDLE
    try:
        IDLE = face(idle(), eye=eye, mouth_kind=mouth_kind) if (eye or mouth_kind) else idle()
        return split_idle()[0]
    finally:
        IDLE = keep


HANG_LIFT = 44                            # how high the body hangs while dragged


def _on(shadow_layer: Image.Image, body: Image.Image) -> Image.Image:
    out = shadow_layer.copy()
    out.alpha_composite(body)
    return out


def lift():
    """Picked up: the body rises and stretches a little; the shadow stays down, shrinks and fades."""
    _, shadow = split_idle()
    plain, surprised, happy = body_face(None, None), body_face(None, "o"), body_face("happy", "smile")
    steps = [  # (body, lift, sx, sy, shadow size, shadow strength)
        (plain, 0, 1.0, 1.0, 1.0, 1.0),
        (surprised, 6, 0.99, 1.02, 0.96, 0.85),
        (surprised, 16, 0.98, 1.04, 0.9, 0.6),
        (happy, 28, 0.982, 1.035, 0.84, 0.35),
        (happy, 38, 0.985, 1.03, 0.8, 0.12),
        (happy, HANG_LIFT, 0.985, 1.03, 0.78, 0.0),
    ]
    frames = [_on(shade(shadow, size, strength), move(body, sx=sx, sy=sy, dy=-up))
              for body, up, sx, sy, size, strength in steps]
    frames[0] = idle()
    return frames, {"frame_ms": 60, "playback": "forward", "kind": "once"}


def hang():
    """Dangling while dragged: no shadow (the swing is drawn live by the pet), a slow stretch in and out."""
    happy = body_face("happy", "smile")
    stretches = [1.03, 1.034, 1.038, 1.041, 1.043, 1.044]
    frames = [move(happy, sx=1.0 - (sy - 1.0) * 0.5, sy=sy, dy=-HANG_LIFT) for sy in stretches]
    return frames, {"frame_ms": 120, "playback": "pingpong", "kind": "loop"}


def landing():
    """Let go: from the first hang frame down onto the shadow coming back, squash, spring back."""
    _, shadow = split_idle()
    happy = body_face("happy", "smile")
    frames = [hang()[0][0]]
    for up, size, strength in ((28, 0.86, 0.35), (12, 0.94, 0.75)):
        frames.append(_on(shade(shadow, size, strength), move(happy, sx=0.985, sy=1.03, dy=-up)))
    frames += [move(idle(), sx=1.04, sy=0.93), move(idle(), sx=0.985, sy=1.025),
               move(idle(), sx=1.004, sy=0.996), idle()]
    return frames, {"frame_ms": 70, "playback": "forward", "kind": "once"}


# 睡着 is 待机 shrunk around the feet (the sprout's top goes from y=72 to y=115), eyes shut, on a cushion.
SLEEP_SCALE = (470 - 115) / (470 - 72)


def cushion() -> Image.Image:
    """睡着/01's cushion on its own: its cream pixels below the belly (the green feet and body are left out;
    whatever cream of the body is left sits under the body layer drawn on top)."""
    sleep = load("睡着/01.png")
    rgba = np.asarray(sleep).astype(np.float32)
    warm = rgba[..., 0] - rgba[..., 1]            # the cushion is warm (red above green by 16-22); the body is not
    rows = np.arange(512)[:, None]
    keep = np.clip((warm - 6.0) / 8.0, 0.0, 1.0) * (rows > 330)
    rgba[..., 3] *= keep
    seat = Image.fromarray(rgba.astype(np.uint8), "RGBA")
    # Where the feet sat the cushion was never drawn: fill those holes with its own blurred colour.
    alpha = seat.getchannel("A")
    closed = alpha.filter(ImageFilter.MaxFilter(31)).filter(ImageFilter.MinFilter(31))
    weight = np.asarray(alpha.filter(ImageFilter.GaussianBlur(14))).astype(np.float32)[..., None] + 1e-3
    colour = np.asarray(Image.fromarray((rgba[..., :3] * (rgba[..., 3:] / 255.0)).astype(np.uint8))
                        .filter(ImageFilter.GaussianBlur(14))).astype(np.float32) * 255.0 / weight
    fill = np.dstack([np.clip(colour, 0, 255), np.asarray(closed)]).astype(np.uint8)
    out = Image.fromarray(fill, "RGBA")
    out.alpha_composite(seat)
    return out


def puff(layer: Image.Image, size: float, strength: float) -> Image.Image:
    """The cushion growing out of the ground and fading in, around its own middle."""
    if strength <= 0:
        return Image.new("RGBA", layer.size, (0, 0, 0, 0))
    global PIVOT
    keep, PIVOT = PIVOT, (256.0, 420.0)
    try:
        out = move(layer, sx=size, sy=size) if size != 1.0 else layer.copy()
    finally:
        PIVOT = keep
    alpha = np.asarray(out.getchannel("A")).astype(np.float32) * strength
    out.putalpha(Image.fromarray(alpha.astype(np.uint8)))
    return out


def _bed(shadow: Image.Image, seat: Image.Image, body: Image.Image, scale: float, stretch: float,
         shadow_strength: float, seat_size: float, seat_strength: float) -> Image.Image:
    """One frame between standing and sleeping: ground shadow, cushion, then the body at `scale`
    (`stretch` > 1 is taller and thinner: a stretch or a yawn)."""
    out = shade(shadow, 1.0, shadow_strength)
    out.alpha_composite(puff(seat, seat_size, seat_strength))
    out.alpha_composite(move(body, sx=scale / math.sqrt(stretch), sy=scale * stretch))
    return out


def sleep_in():
    """待机 -> 睡着/01: a yawn, eyes close, the body sinks to the sleeping size while the ground shadow
    fades and the cushion puffs up under it. The last frame is 睡着/01 itself."""
    _, shadow = split_idle()
    seat = cushion()
    shut = body_face("asleep", None)
    frames = [
        face(idle(), eye="half"),
        move(face(idle(), eye="squint", mouth_kind="o"), sx=0.99, sy=1.02),          # yawn
        zees(move(face(idle(), eye="closed", mouth_kind="o"), sx=0.985, sy=1.03), [((338, 92), 14)]),
        zees(move(face(idle(), eye="closed"), sx=1.01, sy=0.975), [((344, 80), 15)]),  # breathe out
    ]
    for scale, shadow_strength, seat_size, seat_strength in ((0.97, 0.75, 0.86, 0.3), (0.94, 0.45, 0.93, 0.6),
                                                             (0.91, 0.15, 0.98, 0.88), (SLEEP_SCALE, 0.0, 1.0, 1.0)):
        frames.append(_bed(shadow, seat, shut, scale, 1.0, shadow_strength, seat_size, seat_strength))
    frames[4] = zees(frames[4], [((350, 70), 15)])
    frames.append(load("睡着/01.png"))
    return frames, {"frame_ms": 120, "playback": "forward", "kind": "once"}


def wake_up():
    """睡着/01 -> 待机: eyes crack open, a yawn and a stretch up off the cushion, a little bounce."""
    _, shadow = split_idle()
    seat = cushion()
    squint = body_face("squint", None)
    yawn, half = body_face("closed", "o"), body_face("half", None)
    frames = [load("睡着/01.png"),
              _bed(shadow, seat, squint, SLEEP_SCALE, 1.0, 0.0, 1.0, 1.0)]
    for body, scale, stretch, shadow_strength, seat_size, seat_strength in (
            (yawn, 0.92, 1.05, 0.25, 0.98, 0.75), (yawn, 0.96, 1.075, 0.6, 0.93, 0.4),
            (half, 1.0, 1.035, 0.9, 0.88, 0.1)):
        frames.append(_bed(shadow, seat, body, scale, stretch, shadow_strength, seat_size, seat_strength))
    frames += [move(idle(), sx=1.03, sy=0.96), move(idle(), sx=0.99, sy=1.012), idle()]
    return frames, {"frame_ms": 90, "playback": "forward", "kind": "once"}


MAKERS = {"提起": lift, "悬空": hang, "摇头": shake, "歪头": tilt, "说话": talk, "被摸头": patted, "犯困": drowsy,
          "欢呼": cheer, "登场": entrance, "落地": landing, "入睡": sleep_in, "起床": wake_up}


def write(name: str) -> Path:
    frames, meta = MAKERS[name]()
    folder = ART / name
    folder.mkdir(exist_ok=True)
    for old in folder.glob("*.png"):
        old.unlink()
    for i, frame in enumerate(frames, 1):
        frame.save(folder / f"{i:02d}.png", optimize=True)
    meta["source"] = "procedural: tools/make_procedural_motions.py"
    (folder / "motion.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return folder


def main(names: list[str]) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    for name in names or list(MAKERS):
        print(name, "->", write(name))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
