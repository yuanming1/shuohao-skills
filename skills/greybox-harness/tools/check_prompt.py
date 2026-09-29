#!/usr/bin/env python3
"""prompt 出门前的自检 —— 拿它和**场景文件**对，而不是和它自己对。

分三组查:

  结构    章节齐不齐、分镜段和白模镜头对不对得上、硬切次数、台词语速、图片槽位
  颗粒度  每一镜有没有写到「能被否定」的密度、有没有不可证伪的形容词、
          负面约束覆盖了几类
  三层一致  白模说的和 prompt 说的有没有打架 —— 需要 `-- export` 出来的白模事实

用法:
  python3 tools/check_prompt.py <prompt.txt> <scene.py>
  python3 tools/check_prompt.py <prompt.txt> <scene.py> --facts facts.json   # 带三层核对

  # facts.json 这么来:
  blender -b --python scene.py -- export facts.json
"""
import argparse, ast, json, pathlib, re, sys

REQUIRED = ["【参考素材分工", "【画质与质感", "【身份锁定", "【本条剧本",
            "【声音／台词／旁白", "【负面约束"]
BOARD_START, BOARD_END = "【本条剧本", "【声音／台词／旁白"
MAX_CPS = 5.0                    # 实测:5.8 字/秒有三段物理上念不完

SIZE_WORDS = ["大全景", "中远景", "中近景", "全景", "远景", "特写", "近景", "中景", "过肩", "插镜"]
PLACE_WORDS = ["画面左", "画面右", "画面中", "前景", "后景", "背景", "左侧", "右侧",
               "中部", "靠里", "靠外", "身后", "身前", "对面"]
MOVE_WORDS = ["横移", "推进", "拉远", "横摇", "升降", "跟拍", "环绕", "变焦", "缓推", "短跟"]
FIXED_CLAIM = ["固定机位", "不推进", "不拉远", "不横摇", "不跟拍"]
NEG_GROUPS = ["结构类", "白模类", "空间类", "道具类", "表演类", "文字类", "画质类"]
# 不可证伪的形容词 —— 写了等于没写，模型无法据此判断对错
VAGUE = ["高级感", "高级", "质感好", "精致", "氛围感", "大片感", "唯美", "有格调",
         "美美的", "好看", "舒服的", "恰到好处", "若隐若现", "呼之欲出", "极具", "满满的"]
# 景别是按**人在画幅里的高度**定义的，不是按随便哪个元素。
# 一个 1.7m 的人整个装进画面 = 全景;齐腰 ≈ 200%;齐胸 ≈ 350%;只剩脸 ≈ 600%+。
# (第一版拿门洞当主体算，门洞占高 220% 被判成「特写」，整列全是假警报。)
LADDER = [(1.15, "全景"), (2.6, "中景"), (5.0, "近景"), (99.0, "特写")]
ORDER = ["全景", "中景", "近景", "特写"]
ALIAS = {"大全景": "全景", "远景": "全景", "中远景": "全景", "中近景": "近景",
         "过肩": "中景", "插镜": "特写"}


def size_of(h):
    return next(name for lim, name in LADDER if h <= lim)


def shots_from_scene(path):
    src = pathlib.Path(path).read_text(encoding="utf-8")
    m = re.search(r"^SHOTS\s*=\s*\[(.*?)^\]", src, re.S | re.M)
    if not m:
        sys.exit(f"{path} 里找不到 SHOTS = [...]")
    return ast.literal_eval("[" + m.group(1) + "]")


def syllables(line):
    n = 0
    for num in re.findall(r"\d+", line):
        n += min(len(num) + 1, 6)
        line = line.replace(num, "", 1)
    return n + len(re.sub(r"[，。、？！?!,.:：;；\s\"'“”‘’]", "", line))


def board_lines(txt):
    if BOARD_START not in txt:
        return []
    b = txt[txt.index(BOARD_START):]
    b = b[:b.index(BOARD_END)] if BOARD_END in b else b
    out = []
    for l in b.split("\n"):
        m = re.match(r"^[　\s]*(\d+\.\d)[–\-~](\d+\.\d)[　\s]+(.*)$", l)
        if m:
            out.append((float(m.group(1)), float(m.group(2)), m.group(3), l))
    return out


class Report:
    def __init__(self): self.fail = 0; self.warn = 0
    def ok(self, m):   print(f"  ✓ {m}")
    def no(self, m):   self.fail += 1; print(f"  ✗ {m}")
    def hm(self, m):   self.warn += 1; print(f"  ! {m}")


def check_structure(r, txt, shots, lines):
    print("\n── 结构 ──")
    for k in REQUIRED:
        (r.ok if k in txt else r.no)(k + "】")
    if "【画质与质感" in txt and "【参考素材分工" in txt:
        good = txt.index("【参考素材分工") < txt.index("【画质与质感")
        (r.ok if good else r.no)("【画质与质感】排在【参考素材分工】之后"
                                 + ("" if good else " —— 往后挪权重会被稀释"))
    (r.ok if len(lines) == len(shots) else r.no)(f"分镜 {len(lines)} 段 / 白模 {len(shots)} 镜")
    for i, (sid, cam, t0, t1, _g, _d) in enumerate(shots):
        if i >= len(lines):
            r.no(f"{sid} {cam} 白模 {t0}–{t1}，分镜里缺这一段"); continue
        p0, p1 = lines[i][0], lines[i][1]
        bad = abs(p0 - t0) > 0.05 or abs(p1 - t1) > 0.05
        (r.no if bad else r.ok)(f"{sid} {cam:<14} 白模 {t0:5.1f}–{t1:5.1f}  分镜 {p0:5.1f}–{p1:5.1f}")
    hard = sum(l[3].count("硬切") for l in lines)
    (r.ok if hard == len(shots) - 1 else r.no)(
        f"分镜正文里「硬切」{hard} 次 / 应为 {len(shots) - 1} 次")

    said = [s for s in dict.fromkeys(re.findall(r"\*\*[\"“]([^\"”]+)[\"”]\*\*", txt))
            if syllables(s) > 2]
    for s in said:
        n = syllables(s)
        span = next((l[1] - l[0] for l in lines if s in l[3]), None)
        if span:
            cps = n / span
            (r.no if cps > MAX_CPS else r.ok)(f"台词「{s}」 {n} 音节 / {span:.1f}s = {cps:.1f} 字每秒")
        else:
            r.hm(f"台词「{s}」找不到它落在哪一段，语速没法算")
    if not said:
        r.ok("本条无台词")

    nums = sorted({int(x) for x in re.findall(r"@图片(\d+)", txt)})
    (r.ok if nums == list(range(1, len(nums) + 1)) else r.no)(f"图片槽位 @图片{nums or '（无）'}")


def check_granularity(r, txt, lines):
    print("\n── 颗粒度 ──")
    for t0, t1, body, raw in lines:
        miss = []
        if not any(w in body for w in SIZE_WORDS):  miss.append("景别")
        if not any(w in body for w in PLACE_WORDS): miss.append("画面方位")
        if len(re.sub(r"[^一-鿿]", "", body)) < 40: miss.append("信息量(中文<40字)")
        tag = f"{t0:5.1f}–{t1:5.1f}"
        if miss:
            r.no(f"{tag} 缺 {'、'.join(miss)} —— 模型只能靠猜")
        else:
            r.ok(f"{tag} 景别、方位、动作都写到了")

    # 「…」里的多半是「不要这么写」的反例，扫描前先剥掉，否则自己的说明文字会被误判
    scan = re.sub(r"「[^」]*」", "", txt)
    hits = [v for v in VAGUE if v in scan]
    if hits:
        r.hm(f"出现不可证伪的形容词: {'、'.join(hits)} —— 模型无法据此判断对错，换成能被否定的描述")
    else:
        r.ok("没有不可证伪的形容词")

    miss = [g for g in NEG_GROUPS if g not in txt]
    (r.ok if not miss else r.hm)(
        "负面约束七类齐全" if not miss else f"负面约束缺这几类: {'、'.join(miss)}")

    # 自相矛盾:声明了固定机位，分镜里又写了运镜
    claim = [c for c in FIXED_CLAIM if c in txt]
    if claim:
        for t0, t1, body, _ in lines:
            for w in MOVE_WORDS:
                for m in re.finditer(w, body):
                    if not re.search(r"[不禁别勿]{1}.{0,3}$", body[:m.start()]):
                        r.no(f"{t0:5.1f}–{t1:5.1f} 写了「{w}」，但全片声明了「{claim[0]}」—— 自相矛盾")
                    break
    wardrobe = re.search(r"服化道.*?\n(.*?)\n\n", txt, re.S)
    if wardrobe:
        n = len(re.findall(r"[;；]", wardrobe.group(1))) + 1
        (r.ok if n >= 6 else r.hm)(f"服化道 {n} 项" + ("" if n >= 6 else " —— 少于 6 项通常不够锁住一个人"))


def check_layers(r, txt, shots, lines, facts):
    print("\n── 三层一致 ──")
    if "位置与朝向" in txt and ("长相" in txt or "光" in txt):
        r.ok("写了冲突规则(位置与朝向 vs 长相与光)")
    else:
        r.no("没写冲突规则 —— 白模、prompt、资产图打架时模型不知道听谁的")

    for n in sorted({int(x) for x in re.findall(r"@图片(\d+)", txt)}):
        decl = re.search(rf"@图片{n}\s*是(.{{0,160}})", txt, re.S)
        body = decl.group(1) if decl else ""
        if not decl:
            r.no(f"@图片{n} 被引用但没有声明它是什么")
        elif not re.search(r"不要|不取|只取|以它为准", body):
            r.hm(f"@图片{n} 声明里没写「只取什么 / 不取什么」—— 背景和排版会被一起抄走")
        else:
            r.ok(f"@图片{n} 声明了取舍边界")

    if not facts:
        r.hm("没给 --facts，跳过「白模事实 vs 分镜」的对账。"
             "先跑: blender -b --python scene.py -- export facts.json")
        return

    by_id = {f["id"]: f for f in facts["shots"]}
    for i, (sid, cam, *_rest) in enumerate(shots):
        if i >= len(lines) or sid not in by_id:
            continue
        f, body = by_id[sid], lines[i][2]
        if not f["marks"]:
            continue
        people = {k: v for k, v in f["marks"].items() if v.get("kind") == "person"}
        props = {k: v for k, v in f["marks"].items() if v.get("kind") == "prop"}
        big_prop = max((v["w"] for v in props.values()), default=0)
        said = [w for w in SIZE_WORDS if w in body]
        if people and said:
            dom, mk = max(people.items(), key=lambda kv: kv[1]["h"])
            want = size_of(mk["h"])
            got = ALIAS.get(said[0], said[0])
            gap = abs(ORDER.index(got) - ORDER.index(want)) if got in ORDER else 0
            if big_prop > 0.18:
                r.ok(f"{sid} 是插镜(道具占宽 {big_prop*100:.0f}%)，景别按道具算，跳过人体核对")
            elif gap >= 2:
                r.no(f"{sid} 分镜写「{said[0]}」，但白模里 {dom} 占高 {mk['h']*100:.0f}% = {want}"
                     f" —— 差了两档，八成有一边写错了")
            elif gap == 1:
                r.hm(f"{sid} 分镜写「{said[0]}」，白模算出来是 {want}"
                     f"({dom} 占高 {mk['h']*100:.0f}%) —— 差一档，确认一下")
            else:
                r.ok(f"{sid} 景别「{said[0]}」与白模一致({dom} 占高 {mk['h']*100:.0f}%)")
        side = lambda x: "画面左" if x < -0.25 else ("画面右" if x > 0.25 else "画面中")
        facts_txt = " / ".join(f"{k}→{side(v['x'])}"
                               for k, v in sorted(f["marks"].items(),
                                                  key=lambda kv: -kv[1]["h"])[:3])
        print(f"      白模事实 {sid}: {facts_txt}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("prompt")
    ap.add_argument("scene")
    ap.add_argument("--facts", help="`-- export` 导出的白模事实 JSON")
    a = ap.parse_args()

    txt = pathlib.Path(a.prompt).read_text(encoding="utf-8")
    shots = shots_from_scene(a.scene)
    lines = board_lines(txt)
    facts = json.loads(pathlib.Path(a.facts).read_text(encoding="utf-8")) if a.facts else None

    r = Report()
    check_structure(r, txt, shots, lines)
    check_granularity(r, txt, lines)
    check_layers(r, txt, shots, lines, facts)

    print(f"\n共 {len(txt)} 字。", end=" ")
    print("⚠ 超过 8000 字 —— 靠前的章节权重会被稀释，考虑拆条。" if len(txt) > 8000 else "")
    print(f"→ {r.fail} 项不通过，{r.warn} 项提醒")
    return 1 if r.fail else 0


if __name__ == "__main__":
    sys.exit(main())
