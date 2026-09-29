#!/usr/bin/env python3
"""按镜头边界从全场白模里切片 —— 边界从场景文件自动取，杜绝手填帧数切错。

一条生成最长吃 30 秒参考视频(实测)，所以长场景必须拆。**拆点只能落在镜头边界上。**

实测教训:手工切 264 帧(11.0s)，而那一镜到 10.5s 就结束了，
后半秒切进了下一镜 —— 成片最后半秒在执行一次没写进 prompt 的换镜，
出现了一个没有头的躯干。

用法:
  python3 tools/slice_shots.py <全场.mp4> <scene.py> <起镜号> <止镜号> <输出.mp4>
  python3 tools/slice_shots.py out/model.mp4 scene.py S1 S4 out/part1.mp4

不带镜号跑的话，只打印时间轴，不切:
  python3 tools/slice_shots.py <全场.mp4> <scene.py>
"""
import ast, pathlib, re, subprocess, sys


def shots_from_scene(path):
    src = pathlib.Path(path).read_text(encoding="utf-8")
    m = re.search(r"^SHOTS\s*=\s*\[(.*?)^\]", src, re.S | re.M)
    if not m:
        sys.exit(f"{path} 里找不到 SHOTS = [...]")
    return ast.literal_eval("[" + m.group(1) + "]")


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    src, scene = sys.argv[1], sys.argv[2]
    shots = shots_from_scene(scene)
    ids = [s[0] for s in shots]

    if len(sys.argv) < 6:
        print(f"{'镜号':<6}{'机位':<16}{'起':>7}{'止':>8}{'时长':>7}  说明")
        for sid, cam, t0, t1, _g, txt in shots:
            print(f"{sid:<6}{cam:<16}{t0:7.1f}{t1:8.1f}{t1 - t0:7.1f}  {txt[:30]}")
        print(f"\n全场 {shots[-1][3]:.1f}s / {len(shots)} 镜。"
              f"\n切片:python3 tools/slice_shots.py {src} {scene} {ids[0]} {ids[-1]} out.mp4")
        return

    a, b, dst = sys.argv[3], sys.argv[4], sys.argv[5]
    if a not in ids or b not in ids:
        sys.exit(f"镜号不在时间轴里。可用: {' '.join(ids)}")
    t0 = shots[ids.index(a)][2]
    t1 = shots[ids.index(b)][3]          # 止镜号的「止」，正好落在镜头边界上
    subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t0:.4f}", "-i", src,
                    "-t", f"{t1 - t0:.4f}", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-crf", "18", dst, "-y"], check=True)
    n = ids.index(b) - ids.index(a) + 1
    print(f"{a}→{b}  {t0:.2f}s → {t1:.2f}s  时长 {t1 - t0:.2f}s  {n} 个镜头  → {dst}")
    if t1 - t0 > 30:
        print("⚠ 超过 30 秒 —— 实测参考视频通道的硬上限就是 30 秒，会被打回。再拆。")


if __name__ == "__main__":
    main()
