"""16-bit style sound: synthesised effects and a chiptune loop, mixed into a mono 16-bit WAV for a replay video.

Nothing is downloaded; every sound is built from square, triangle, sine and noise generators. The mixer places
each effect at the video time of its event (allowing for the freeze-frames the replay inserts) and lays a quiet
music loop underneath.
"""
from __future__ import annotations

import wave

import numpy as np

SR = 22050


def _env(n, attack=0.005, release=0.05, sr=SR):
    a = max(1, int(attack * sr)); r = max(1, int(release * sr))
    e = np.ones(n)
    e[:a] = np.linspace(0, 1, a)
    if r < n:
        e[-r:] = np.linspace(1, 0, r)
    return e


def square(freq, dur, vol=0.3, duty=0.5, sr=SR):
    t = np.arange(int(dur * sr)) / sr
    ph = (t * freq) % 1.0
    return vol * np.where(ph < duty, 1.0, -1.0) * _env(len(t), sr=sr)


def triangle(freq, dur, vol=0.3, sr=SR):
    t = np.arange(int(dur * sr)) / sr
    return vol * (2 * np.abs(2 * ((t * freq) % 1.0) - 1) - 1) * _env(len(t), sr=sr)


def sine(freq, dur, vol=0.3, sr=SR):
    t = np.arange(int(dur * sr)) / sr
    return vol * np.sin(2 * np.pi * freq * t) * _env(len(t), sr=sr)


def noise(dur, vol=0.3, sr=SR, seed=0, lowpass=None):
    rng = np.random.default_rng(seed)
    x = rng.uniform(-1, 1, int(dur * sr))
    if lowpass:
        k = max(1, int(sr / lowpass)); x = np.convolve(x, np.ones(k) / k, mode="same")
    return vol * x


def _crush(x, bits=8):
    """8-bit quantisation for the console feel."""
    q = 2 ** (bits - 1)
    return np.round(np.clip(x, -1, 1) * q) / q


# ----------------------------------------------------------------------------- the effects
def fx_kick():
    t = np.arange(int(0.18 * SR)) / SR
    sweep = np.sin(2 * np.pi * (90 - 300 * t) * t) * np.exp(-18 * t) * 0.9
    click = noise(0.02, 0.5, seed=1)
    out = sweep.copy(); out[:len(click)] += click
    return _crush(out)


def fx_handball():
    return _crush(noise(0.05, 0.25, seed=2, lowpass=3000) * np.exp(-60 * np.arange(int(0.05 * SR)) / SR))


def fx_tackle():
    t = np.arange(int(0.16 * SR)) / SR
    return _crush(noise(0.16, 0.6, seed=3, lowpass=400) * np.exp(-25 * t))


def fx_spoil():
    t = np.arange(int(0.10 * SR)) / SR
    return _crush(noise(0.10, 0.5, seed=4, lowpass=1500) * np.exp(-40 * t))


def fx_crowd(dur=0.8, vol=0.35, seed=5, swell=0.3):
    t = np.arange(int(dur * SR)) / SR
    env = np.minimum(t / max(swell, 0.01), 1.0) * np.exp(-2.5 * np.maximum(t - swell, 0))
    return _crush(noise(dur, vol, seed=seed, lowpass=900) * env)


def fx_mark():
    return fx_crowd(0.7, 0.3, seed=6, swell=0.15)


def fx_behind():
    out = fx_crowd(1.0, 0.3, seed=7, swell=0.3)
    n = square(330, 0.25, 0.18); out[:len(n)] += n
    return _crush(out)


def fx_goal():
    roar = fx_crowd(2.6, 0.55, seed=8, swell=0.4)
    fan = np.concatenate([square(f, d, 0.28) for f, d in ((523, 0.12), (659, 0.12), (784, 0.12), (1047, 0.36))])
    fan2 = np.concatenate([triangle(f / 2, d, 0.25) for f, d in ((523, 0.12), (659, 0.12), (784, 0.12), (1047, 0.36))])
    out = roar.copy(); out[:len(fan)] += fan + fan2[:len(fan)]
    return _crush(out)


def fx_siren(dur=2.2):
    t = np.arange(int(dur * SR)) / SR
    f = 420 + 12 * np.sin(2 * np.pi * 6 * t)
    ph = np.cumsum(f) / SR
    saw = 2 * (ph % 1.0) - 1
    return _crush(0.35 * saw * _env(len(t), 0.05, 0.3))


def fx_whistle():
    return _crush(np.concatenate([square(1900, 0.12, 0.22, 0.3), np.zeros(int(0.04 * SR)), square(1900, 0.2, 0.22, 0.3)]))


def fx_bounce():
    return _crush(sine(180, 0.12, 0.35))


# ----------------------------------------------------------------------------- the music loop
def music_loop(bpm=128, bars=8, vol=0.12, seed=11):
    """A chiptune loop: square lead on a pentatonic riff, triangle bass, noise hats. Deterministic for a seed."""
    rng = np.random.default_rng(seed)
    beat = 60.0 / bpm; step = beat / 2
    penta = [523, 587, 659, 784, 880, 1047, 1175, 1319]
    bass_root = [131, 131, 98, 110, 131, 131, 87, 98]
    n_steps = bars * 8
    out = np.zeros(int(n_steps * step * SR) + SR)
    pos = 0
    riff = [penta[i] for i in rng.integers(0, len(penta), 16)]
    for s in range(n_steps):
        i0 = int(pos * SR)
        if s % 2 == 0 or rng.random() < 0.6:
            f = riff[s % 16]
            note = square(f, step * 0.9, 0.22, 0.25); out[i0:i0 + len(note)] += note
        if s % 4 in (0, 2):
            b = triangle(bass_root[(s // 8) % 8], step * 1.8, 0.3); out[i0:i0 + len(b)] += b
        h = noise(0.03, 0.10 if s % 2 else 0.05, seed=s, lowpass=6000); out[i0:i0 + len(h)] += h
        pos += step
    loop = out[:int(n_steps * step * SR)]
    return _crush(vol * loop / max(np.max(np.abs(loop)), 1e-6))


EFFECTS = {
    "kick": fx_kick, "handball": fx_handball, "tackle": fx_tackle, "spoil": fx_spoil, "mark": fx_mark,
    "goal": fx_goal, "behind": fx_behind, "siren": fx_siren, "whistle": fx_whistle, "bounce": fx_bounce,
}


def mix(events, duration_s, music=True, music_vol=1.0, sr=SR):
    """events: [(time_s, effect_name)]. Returns a float array of `duration_s` seconds with the effects and the loop."""
    n = int(duration_s * sr) + sr
    out = np.zeros(n)
    if music:
        loop = music_loop() * music_vol
        reps = int(np.ceil(n / len(loop))) + 1
        out += np.tile(loop, reps)[:n]
    cache = {}
    for t, name in events:
        if name not in EFFECTS:
            continue
        if name not in cache:
            cache[name] = EFFECTS[name]()
        s = cache[name]; i0 = int(t * sr)
        if 0 <= i0 < n:
            seg = s[:n - i0]; out[i0:i0 + len(seg)] += seg
    out = np.tanh(out * 1.2) * 0.9                                   # soft limiter
    return out[:int(duration_s * sr)]


def write_wav(path, x, sr=SR):
    y = (np.clip(x, -1, 1) * 32767).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes(y.tobytes())
