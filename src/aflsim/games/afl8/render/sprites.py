"""Pixel-art sprites for the retro replay: players, the ball, coach portraits and grass. Pure numpy RGBA arrays."""
from __future__ import annotations

import os

import numpy as np

SKIN = (241, 194, 125, 255); HAIR = (62, 39, 35, 255); BOOT = (20, 20, 20, 255); SHORT = (250, 250, 250, 255); CLEAR = (0, 0, 0, 0)
BALL_RED = (198, 40, 40, 255); BALL_DARK = (120, 20, 20, 255); LACE = (255, 240, 200, 255)


def _hex(c):
    c = c.lstrip("#")
    return (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16), 255)


def player_sprite(colour: str, frame: int = 0, facing: int = 1, role: str = "") -> np.ndarray:
    """A 12 x 16 pixel footballer in a jumper of the team colour with a white sash; frame 0/1 = run cycle; facing 1 = right."""
    jumper = _hex(colour); dark = tuple(max(0, v - 60) for v in jumper[:3]) + (255,)
    p = np.zeros((16, 12, 4), dtype=np.uint8)

    def put(y, x0, x1, c):
        p[y, x0:x1] = c

    put(0, 4, 8, HAIR); put(1, 3, 9, HAIR)
    put(2, 3, 9, SKIN); put(3, 3, 9, SKIN); p[3, 4] = (30, 30, 30, 255); p[3, 7] = (30, 30, 30, 255)
    put(4, 4, 8, SKIN)
    put(5, 2, 10, jumper); put(6, 1, 11, jumper); put(7, 1, 11, jumper); put(8, 2, 10, jumper); put(9, 2, 10, jumper)
    for y in range(5, 10):                                          # diagonal sash
        x = 3 + (y - 5)
        p[y, x] = SHORT; p[y, min(x + 1, 11)] = SHORT
    p[6, 0] = SKIN; p[6, 11] = SKIN; p[7, 0] = SKIN; p[7, 11] = SKIN     # arms
    put(10, 3, 9, SHORT); put(11, 3, 9, SHORT)
    if frame == 0:
        put(12, 3, 5, SKIN); put(12, 7, 9, SKIN); put(13, 3, 5, SKIN); put(13, 7, 9, SKIN); put(14, 3, 5, BOOT); put(14, 7, 9, BOOT)
    else:
        put(12, 2, 4, SKIN); put(12, 8, 10, SKIN); put(13, 1, 3, SKIN); put(13, 9, 11, SKIN); put(14, 0, 2, BOOT); put(14, 10, 12, BOOT)
    put(15, 3, 9, dark)                                             # shadow line
    if role == "midfielder":
        p[8, 5:7] = dark                                            # a small marking so roles are told apart at a glance
    elif role == "defender":
        p[9, 4:8] = dark
    if facing < 0:
        p = p[:, ::-1]
    return p


def ball_sprite(angle_deg: float = 0.0, size: int = 14) -> np.ndarray:
    """A red oval football with a lace, rotated by angle (pixel-art: drawn on a grid, then rotated with nearest sampling)."""
    n = size
    yy, xx = np.mgrid[0:n, 0:n]
    cx = cy = (n - 1) / 2
    a, b = n * 0.46, n * 0.27
    th = np.deg2rad(angle_deg)
    xr = (xx - cx) * np.cos(th) + (yy - cy) * np.sin(th)
    yr = -(xx - cx) * np.sin(th) + (yy - cy) * np.cos(th)
    inside = (xr / a) ** 2 + (yr / b) ** 2 <= 1.0
    edge = (xr / a) ** 2 + (yr / b) ** 2 > 0.72
    lace = inside & (np.abs(yr) < 0.9) & (np.abs(xr) < a * 0.45)
    img = np.zeros((n, n, 4), dtype=np.uint8)
    img[inside] = BALL_RED; img[inside & edge] = BALL_DARK; img[lace] = LACE
    return img


def pixelate(path: str, n: int = 24) -> np.ndarray | None:
    """Load an image, crop to a square, downsample to n x n blocks (nearest) and return RGBA; None if it cannot be read."""
    try:
        from PIL import Image
        im = Image.open(path).convert("RGBA")
    except Exception:
        return None
    w, h = im.size; s = min(w, h)
    im = im.crop(((w - s) // 2, (h - s) // 2, (w - s) // 2 + s, (h - s) // 2 + s)).resize((n, n), Image.BILINEAR)
    arr = np.asarray(im).copy()
    arr[..., :3] = (arr[..., :3] // 16) * 16                        # posterise a little for the 16-bit look
    return arr


def coach_sprite(colour: str, face: np.ndarray | None = None, mouth_open: bool = False) -> np.ndarray:
    """A 24 x 32 coach: a pixelated photo (or a drawn face) on a body in the team colour. The drawn mouth animates."""
    jumper = _hex(colour)
    p = np.zeros((32, 24, 4), dtype=np.uint8)
    if face is not None:
        f = face if face.shape[0] == 20 else _resize_nearest(face, 20)
        p[0:20, 2:22] = f
    else:
        p[1:4, 7:17] = HAIR; p[4:16, 6:18] = SKIN; p[4:8, 5:19] = HAIR; p[6:16, 6:18] = SKIN
        p[9, 9] = (30, 30, 30, 255); p[9, 14] = (30, 30, 30, 255)
        if mouth_open:
            p[12:15, 10:14] = (90, 40, 40, 255)
        else:
            p[13, 9:15] = (110, 60, 60, 255)
    p[20:32, 2:22] = jumper; p[20:24, 10:14] = SHORT                # body and collar
    p[16:20, 10:14] = SKIN if face is None else p[16:20, 10:14]     # neck for the drawn face
    return p


def _resize_nearest(img: np.ndarray, n: int) -> np.ndarray:
    ys = (np.arange(n) * img.shape[0] / n).astype(int); xs = (np.arange(n) * img.shape[1] / n).astype(int)
    return img[ys][:, xs]


def grass(width_px: int = 640, height_px: int = 460, seed: int = 0) -> np.ndarray:
    """Mown stripes with a little pixel noise."""
    rng = np.random.default_rng(seed)
    img = np.zeros((height_px, width_px, 3), dtype=np.uint8)
    stripe = 32
    for x0 in range(0, width_px, stripe):
        base = (52, 130, 60) if (x0 // stripe) % 2 == 0 else (44, 116, 52)
        img[:, x0:x0 + stripe] = base
    noise = rng.integers(-6, 7, size=(height_px // 4, width_px // 4, 1))
    noise = np.repeat(np.repeat(noise, 4, axis=0), 4, axis=1)[:height_px, :width_px]
    img = np.clip(img.astype(int) + noise, 0, 255).astype(np.uint8)
    return img


def face_for_pack(pack_summary: dict | None, n: int = 20) -> np.ndarray | None:
    """face.png / face.jpg next to a team pack's team.json, pixelated; None if there is none."""
    if not pack_summary or not pack_summary.get("path"):
        return None
    folder = os.path.dirname(pack_summary["path"])
    for name in ("face.png", "face.jpg", "face.jpeg"):
        f = os.path.join(folder, name)
        if os.path.exists(f):
            return pixelate(f, n)
    return None


def crowd(width_px: int = 1024, height_px: int = 160, seed: int = 1, bright: bool = False) -> np.ndarray:
    """A grandstand of pixel people: rows of 2 x 3 blocks in jumper colours over dark seating. bright=True is the goal flicker."""
    rng = np.random.default_rng(seed + (7 if bright else 0))
    img = np.zeros((height_px, width_px, 3), dtype=np.uint8)
    img[:] = (24, 22, 30)
    palette = np.array([(229, 57, 53), (30, 136, 229), (240, 240, 240), (255, 214, 0), (60, 60, 70), (120, 40, 140), (40, 140, 90), (250, 190, 130), (90, 60, 40)], dtype=np.uint8)
    rows = height_px // 6
    for r in range(rows):
        y0 = r * 6 + (r % 2) * 1
        for x0 in range(0, width_px, 4):
            if rng.random() < 0.12:
                continue                                              # an empty seat
            c = palette[rng.integers(0, len(palette))]
            if bright and rng.random() < 0.5:
                c = np.minimum(c.astype(int) + 70, 255).astype(np.uint8)
            img[y0:y0 + 3, x0:x0 + 3] = c                             # body
            img[max(y0 - 1, 0):y0 + 1, x0 + 1:x0 + 3] = (238, 190, 140) if rng.random() < 0.7 else (110, 70, 40)   # head
    return img
