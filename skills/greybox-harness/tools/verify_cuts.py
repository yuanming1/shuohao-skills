#!/usr/bin/env python3
"""把成片的实际切点和白模时间轴对一遍。

为什么要有这个:白模这套管线的核心主张就是「切点可控」。
不量它，就只能凭印象说「感觉对上了」。

**切点数据必须从场景文件的 SHOTS 里取，不能从 prompt 里取。**
prompt 的时间码本来就是照着 SHOTS 抄的 —— 拿它验 prompt 是循环验证，
什么错都发现不了(这个错我犯过一次)。

用法:
  python3 tools/verify_cuts.py <成片.mp4> <scene.py> [--tol 0.15] [--thr 0.28]
"""
import argparse, ast, pathlib, re, subprocess, sys


def shots_from_scene(path):
    """从场景文件里抠出 SHOTS 表。不 import 它 —— 那需要 Blender。"""
    src = pathlib.Path(path).read_text(encoding="utf-8")
    m = re.search(r"^SHOTS\s*=\s*\[(.*?)^\]", src, re.S | re.M)
    if not m:
        sys.exit(f"{path} 里找不到 SHOTS = [...]")
    return ast.literal_eval("[" + m.group(1) + "]")


def detect_cuts(video, thr, merge=0.25):
    r = subprocess.run(
        ["ffmpeg", "-i", str(video), "-filter:v", f"select='gt(scene,{thr})',showinfo",
         "-f", "null", "-"], capture_output=True, text=True)
    raw = sorted(float(x) for x in re.findall(r"pts_time:([\d.]+)", r.stderr))
    out = []
    for c in raw:                       # 一次换镜常报好几帧，合并掉
        if not out or c - out[-1] > merge:
            out.append(c)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("scene")
    ap.add_argument("--tol", type=float, default=0.15, help="允许的偏差(秒)")
    ap.add_argument("--thr", type=float, default=0.28, help="ffmpeg 场景检测阈值")
    a = ap.parse_args()

    shots = shots_from_scene(a.scene)
    want = [s[2] for s in shots[1:]]                     # 每一镜的起点就是一次切
    thr = a.thr
    got = detect_cuts(a.video, thr)
    # 0.28 是给实拍片调的。平光灰模帧间差太小，同样的换镜在灰模上只有实拍的几分之一，
    # 这个阈值会漏掉大半 —— 别把「读不出来」当成「模型没切」。
    if len(got) < len(want):
        for t in (0.15, 0.08):
            g2 = detect_cuts(a.video, t)
            if len(g2) >= len(want):
                print(f"⚠ 阈值 {a.thr} 只读到 {len(got)} 个切点(应有 {len(want)} 个)，"
                      f"降到 {t} 才读全。\n"
                      f"  灰模帧间差小，需要低阈值;**反过来把低阈值用在实拍片上，"
                      f"会把摇晃、光变、快速动作全判成切点。**\n"
                      f"  如果你验的是成片而不是白模，那就不要采信这次降阈值的结果 ——"
                      f"高阈值下真的少切了。\n")
                got, thr = g2, t
                break

    print(f"白模 {len(shots)} 镜 / 应有 {len(want)} 次硬切  (检测阈值 {thr})")
    print(f"成片检测到 {len(got)} 次换镜: {[round(c, 2) for c in got]}\n")
    print(f"{'镜号':<6}{'应切':>8}{'实切':>9}{'偏差':>9}")
    hit = 0
    for (sid, _cam, t0, _t1, _g, _txt), w in zip(shots[1:], want):
        if not got:
            print(f"{sid:<6}{w:8.2f}{'—':>9}{'—':>9}  ✗ 没检测到任何切点")
            continue
        n = min(got, key=lambda c: abs(c - w))
        d = abs(n - w)
        ok = d <= a.tol
        hit += ok
        print(f"{sid:<6}{w:8.2f}{n:9.2f}{d:8.2f}s  {'✓' if ok else '✗'}")

    extra = [c for c in got if not want or min(abs(c - w) for w in want) > 0.3]
    print(f"\n多余切点: {[round(c, 2) for c in extra] or '无'}")
    print(f"命中 {hit}/{len(want)}，多余 {len(extra)}")
    ok = hit == len(want) and not extra
    print("→", "切点完全复现" if ok else "切点没对齐 —— 先看长镜头(超过 6 秒的一镜模型爱自己加切)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
