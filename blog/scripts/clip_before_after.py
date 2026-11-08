"""A 25-30 s social clip: the Figure 16 games side by side (the original Power, and the Power with Claude's plan with
no limit, against round_36a on the same seed). Not published with the page; the clip goes to the private videos folder.

    python blog/scripts/clip_before_after.py [--seed 8600024] [--speed 10]
"""
import argparse
import os
import subprocess

import gen_sharks_games as G                                              # sets up paths
from aflsim.games.afl8.render.replay import animate                        # noqa: E402
from aflsim.value.function import ValueFunction                            # noqa: E402

OUT = os.path.join(G._paths.HOME, "videos", "afl8")
FONT = "C\\:/Windows/Fonts/arialbd.ttf"


def render(power, seed, name, path, speed, vf):
    vals = []
    ep = G.play(power, seed, lambda game, state: vals.append([float(state["time"]), float(vf.of_state(state))]), "frames")
    animate(ep, speed=speed, save=path, name_a=name, name_b="Sharks (round_36a)", values=vals,
            goal_hold_s=0.8, behind_hold_s=0.3, fulltime_hold_s=2.5)
    return ep["stats"]["score_A"], ep["stats"]["score_B"]


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--seed", type=int, default=8600024); ap.add_argument("--speed", type=float, default=10.0)
    a = ap.parse_args()
    vf = ValueFunction(G.MODEL); vf.model.eval()
    b = os.path.join(OUT, "clip_before_%d.mp4" % a.seed); f = os.path.join(OUT, "clip_after_%d.mp4" % a.seed)
    sb = render(G.v2.POWER, a.seed, "Power", b, a.speed, vf); print("before", sb, flush=True)
    sa = render(G.PLAN, a.seed, "Power + Claude's plan", f, a.speed, vf); print("after", sa, flush=True)
    out = os.path.join(OUT, "clip_before_after_%d.mp4" % a.seed)
    lab = ("drawtext=fontfile='%s':text='%s':fontcolor=white:fontsize=46:x=(w-text_w)/2:y=22:box=1:boxcolor=0x000000AA:boxborderw=14")
    fc = ("[0:v]tpad=stop_mode=clone:stop_duration=6,scale=-2:720,%s[l];"
          "[1:v]tpad=stop_mode=clone:stop_duration=6,scale=-2:720,%s[r];"
          "[l][r]hstack=inputs=2:shortest=0[v0];[v0]trim=duration=%.1f,pad=ceil(iw/2)*2:ceil(ih/2)*2[v]") % (
        lab % (FONT, "BEFORE\\: the original Power"), lab % (FONT, "AFTER\\: with Claude’s plan"), 30.0)
    subprocess.run(["ffmpeg", "-y", "-i", b, "-i", f, "-filter_complex", fc, "-map", "[v]", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-crf", "20", "-movflags", "+faststart", out], check=True)
    print("clip", out, os.path.getsize(out) // 1024, "KB")


if __name__ == "__main__":
    main()
