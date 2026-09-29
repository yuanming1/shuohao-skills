#!/usr/bin/env python3
"""抽帧拼接触表 —— 白模审片和成片核验都用它。

按镜头边界抽帧:给了场景文件就每一镜抽两帧(入点后 0.3s、出点前 0.3s)，
这样一眼能看出「这一镜开头和结尾各是什么」，比等间隔抽帧有用得多。

**不要给它加 autocontrast。** 白模原图反差本来就小(实测人物 171 / 墙 185)，
拉完会变成黑白对立 —— 我因此两次把正常曝光误判成「逆光剪影」。

用法:
  python3 tools/contact_sheet.py <video.mp4> -o sheet.png [--scene scene.py] [--cols 3]
  python3 tools/contact_sheet.py <video.mp4> -o sheet.png --at 0.5 3.2 7.0
"""
import argparse, ast, pathlib, re, subprocess, sys, tempfile


def shots_from_scene(path):
    src = pathlib.Path(path).read_text(encoding="utf-8")
    m = re.search(r"^SHOTS\s*=\s*\[(.*?)^\]", src, re.S | re.M)
    return ast.literal_eval("[" + m.group(1) + "]") if m else None


def duration(v):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", str(v)], capture_output=True, text=True)
    return float(r.stdout.strip())


def grab(v, t, dst):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(t), "-i", str(v),
                    "-frames:v", "1", str(dst)], check=True)


def load_font(size=16):
    """找一个带中日韩字形的字体。PIL 自带的位图字体只有 ASCII，
    镜号里但凡有中文就会渲成一排方块 —— 标签看不懂，接触表就白做了。"""
    from PIL import ImageFont
    for p in ("/System/Library/Fonts/PingFang.ttc",                       # macOS
              "/System/Library/Fonts/Hiragino Sans GB.ttc",
              "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",   # Linux
              "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
              "C:/Windows/Fonts/msyh.ttc"):                               # Windows
        if pathlib.Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except OSError:
                pass
    return ImageFont.load_default()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--scene", help="场景文件:按镜头边界抽帧并标上镜号")
    ap.add_argument("--at", nargs="*", type=float, help="手动指定秒数")
    ap.add_argument("--cols", type=int, default=3)
    ap.add_argument("--width", type=int, default=560)
    a = ap.parse_args()

    from PIL import Image, ImageDraw          # 只有这一步需要 Pillow
    font = load_font(16)

    dur = duration(a.video)
    if a.at:
        marks = [(f"{t:.1f}s", t) for t in a.at if t < dur]
    elif a.scene and (shots := shots_from_scene(a.scene)):
        marks = []
        for sid, cam, t0, t1, _g, _d in shots:
            marks.append((f"{sid} {cam} 入", min(t0 + 0.3, dur - 0.05)))
            marks.append((f"{sid} {cam} 出", min(t1 - 0.3, dur - 0.05)))
    else:
        n = 9
        marks = [(f"{dur * i / n:.1f}s", dur * i / n) for i in range(n)]

    ims = []
    with tempfile.TemporaryDirectory() as td:
        for i, (label, t) in enumerate(marks):
            p = pathlib.Path(td) / f"{i:03d}.png"
            grab(a.video, t, p)
            if not p.exists():
                continue
            im = Image.open(p).convert("RGB")
            im = im.resize((a.width, int(a.width * im.height / im.width)))
            d = ImageDraw.Draw(im)
            box = d.textbbox((6, 5), label, font=font)
            d.rectangle([0, 0, box[2] + 8, box[3] + 5], fill=(0, 0, 0))
            d.text((6, 5), label, fill=(255, 255, 255), font=font)
            ims.append(im)

    if not ims:
        sys.exit("一帧都没抽出来")
    cols = a.cols
    rows = (len(ims) + cols - 1) // cols
    w, h = ims[0].size
    sheet = Image.new("RGB", (w * cols, h * rows), "white")
    for i, im in enumerate(ims):
        sheet.paste(im, ((i % cols) * w, (i // cols) * h))
    sheet.save(a.out)
    print(f"{len(ims)} 帧 → {a.out}")


if __name__ == "__main__":
    main()
