"""示例场景 · 精品店(街边店面 + 店内柜台)

一条 16 秒、7 镜 6 切的购买段落，覆盖这套管线里最容易翻车的几件事:

  · 一个**连续空间里的两个子区域**(店外 / 店内)，靠一次硬切连起来
  · **洞口必须是真的洞** —— 橱窗壁龛和入口都留空，不放板子
  · **手要在道具上** —— 两个插镜(包装、支付)的道具位置从手的实测坐标取
  · **一件道具只许移动一次**，而且要卡在某个时间点之后
  · **同一个角色的三组走位**互不干扰(橱窗前 / 门口 / 柜台前)

跑法:
  blender -b --python scene.py -- audit        # 送模版明度自检:谁和谁会糊在一起
  blender -b --python scene.py -- probe
  blender -b --python scene.py -- project
  blender -b --python scene.py -- export facts.json   # 白模事实 → 给 check_prompt 对账
  blender -b --python scene.py -- blockers
  blender -b --python scene.py -- plan        out
  blender -b --python scene.py -- review      out
  blender -b --python scene.py -- review_anim out/review
  blender -b --python scene.py -- anim        out/model
"""
import sys, os, pathlib
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "blockout"))
import rig
from rig import box, cyl, cam
import human
from human import mannequin

ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
MODE = ARGS[0] if ARGS else "review"
OUT  = ARGS[1] if len(ARGS) > 1 else "/tmp/boutique"

S = rig.new_scene()
P = rig.palette()

# ── 坐标:X 左右(她 -X → +X)、Y 纵深(广场 0~4 / 立面 4.0 / 店内 4.0~9.0)、Z 高 ──
# 机位一律正对立面(视线沿 +Y)，+X 才等于「画面右」。
GLASS_Y, ZC = 4.0, 3.4
box("广场铺地", 0.0, 1.0, -0.05, 20.0, 8.0, 0.1, P["FLOOR"], role="shell")
box("店内地面", 0.0, 6.5, -0.05, 10.0, 5.0, 0.1, P["FLOOR"], role="shell")
box("店内天花", 0.0, 6.5, ZC + 0.05, 10.0, 5.0, 0.1, P["WALL"], role="shell")
box("店内_左墙", -5.0, 6.5, ZC / 2, 0.1, 5.0, ZC, P["WALL"], role="shell")
box("店内_右墙",  5.0, 6.5, ZC / 2, 0.1, 5.0, ZC, P["WALL"], role="shell")
box("店内_后墙",  0.0, 9.0, ZC / 2, 10.0, 0.1, ZC, P["WALL"], role="shell")
box("塔楼", 0.0, 5.2, 8.0, 18.0, 3.0, 8.6, P["DARK"], role="shell")   # 露天:头顶不是天花板

# ── 立面:洞口留空。放一块「半透明玻璃」的话，Workbench 里它就是一堵实心墙 ──
WIN_X0, WIN_X1, WIN_Z0, WIN_Z1 = -2.10, -1.05, 0.55, 2.95   # 竖长条橱窗壁龛
DR_X0,  DR_X1,  DR_Z1          = -0.35,  1.45, 2.70          # 入口门洞
box("立面_最左",   (-8.0 + WIN_X0) / 2, GLASS_Y, 1.70, WIN_X0 + 8.0, 0.12, ZC, P["WALL"], role="shell")
box("橱窗_下墙",   (WIN_X0 + WIN_X1) / 2, GLASS_Y, WIN_Z0 / 2, WIN_X1 - WIN_X0, 0.12, WIN_Z0, P["WALL"], role="shell")
box("橱窗_上梁",   (WIN_X0 + WIN_X1) / 2, GLASS_Y, (WIN_Z1 + ZC) / 2, WIN_X1 - WIN_X0, 0.12, ZC - WIN_Z1, P["WALL"], role="shell")
box("立面_窗门之间", (WIN_X1 + DR_X0) / 2, GLASS_Y, 1.70, DR_X0 - WIN_X1, 0.12, ZC, P["WALL"], role="shell")
box("入口_门楣",   (DR_X0 + DR_X1) / 2, GLASS_Y, (DR_Z1 + ZC) / 2, DR_X1 - DR_X0, 0.12, ZC - DR_Z1, P["WALL"], role="shell")
box("入口_门框左", DR_X0, GLASS_Y, DR_Z1 / 2, 0.10, 0.16, DR_Z1, P["DARK"], role="furniture")
box("入口_门框右", DR_X1, GLASS_Y, DR_Z1 / 2, 0.10, 0.16, DR_Z1, P["DARK"], role="furniture")
box("立面_最右",   (DR_X1 + 8.0) / 2, GLASS_Y, 1.70, 8.0 - DR_X1, 0.12, ZC, P["WALL"], role="shell")
# 竖向肋 —— 不是装饰，是纵深的刻度尺。空立面在透视里读不出远近。
for i in range(34):
    px = -8.0 + 0.5 + i * 0.46
    if WIN_X0 - 0.15 < px < WIN_X1 + 0.15 or DR_X0 - 0.15 < px < DR_X1 + 0.15:
        continue
    box(f"竖肋{i}", px, GLASS_Y - 0.09, 1.70, 0.09, 0.10, ZC, P["RELIEF"], role="shell")

# 橱窗壁龛:只做背板和两侧收口，中间空着，从街上能看进去
WIN_CX, WIN_BACK = (WIN_X0 + WIN_X1) / 2, GLASS_Y + 0.85
box("橱窗_背板", WIN_CX, WIN_BACK, (WIN_Z0 + WIN_Z1) / 2, WIN_X1 - WIN_X0, 0.10, WIN_Z1 - WIN_Z0, P["WALL"], role="shell")
for sx, tag in ((WIN_X0, "左"), (WIN_X1, "右")):
    box(f"橱窗_侧{tag}", sx, (GLASS_Y + WIN_BACK) / 2, (WIN_Z0 + WIN_Z1) / 2, 0.08,
        WIN_BACK - GLASS_Y, WIN_Z1 - WIN_Z0, P["RELIEF"], role="shell")
box("橱窗_台座", WIN_CX, GLASS_Y + 0.42, 0.43, 0.68, 0.50, 0.86, P["WOOD"], role="furniture")
box("陈列品",    WIN_CX, GLASS_Y + 0.42, 0.99, 0.40, 0.20, 0.26, P["PROP"], role="prop")
box("陈列品_提手", WIN_CX, GLASS_Y + 0.42, 1.19, 0.20, 0.04, 0.14, P["PROP"], role="prop")

# ── 店内:柜台横隔两人 ──
CT_X, CT_Y = 0.30, 6.40
box("柜台_体", CT_X, CT_Y, 0.52, 2.60, 0.72, 1.04, P["WOOD"], role="furniture")
box("柜台_面", CT_X, CT_Y, 1.06, 2.72, 0.82, 0.05, P["RELIEF"], role="furniture")
TERM = (CT_X + 0.10, CT_Y - 0.28, 1.14)      # 「在两人之间」但要放在她手够得到的一侧
box("支付终端", *TERM, 0.16, 0.12, 0.12, P["PROP"], role="prop")
box("背柜", CT_X, 8.30, 1.10, 3.60, 0.42, 2.20, P["WOOD"], role="furniture")
for i, x in enumerate((-1.05, 0.30, 1.65)):
    box(f"背柜_格{i}", x, 8.28, 1.45, 0.90, 0.06, 0.55, P["SCRN"], role="screen")
box("包装台", CT_X + 1.45, CT_Y + 1.15, 1.06, 0.70, 0.70, 0.05, P["WOOD"], role="furniture")
for i, (x, y) in enumerate(((-2.40, 5.30), (2.30, 5.20))):
    box(f"陈列桌{i}", x, y, 0.62, 0.90, 0.90, 0.06, P["WOOD"], role="furniture")

# ── 人物:三组走位。主体是「陈列品」，所以看橱窗那一组不能站在它正前方 ──
WIN_POS = (0.05, 2.85)
LEAD_CT = (CT_X + 0.00, CT_Y - 0.68)        # 两人都贴到柜台边，否则手够不到台面
CLERK   = (CT_X - 0.10, CT_Y + 0.78)
FIG = {
    "WINDOW":  mannequin("LEAD_窗", WIN_POS, 138, "stand", P, height=1.66),
    "DOOR":    mannequin("LEAD_门", (0.45, 3.55), 90, "stand_reach_r", P, height=1.66),
    "COUNTER": (mannequin("LEAD_台", LEAD_CT, 90, "stand_reach_r", P, height=1.66)
                + mannequin("CLERK", CLERK, -90, "stand_reach_r", P, height=1.70, lead=False)),
}

# ── 道具跟着手走。硬填坐标的下场:手在这儿、道具在那儿，隔着半米对空气比划 ──
CLERK_H, LEAD_H = human.hand("CLERK", "R"), human.hand("LEAD_台", "R")
CT_FRONT, CT_BACK = CT_Y - 0.32, CT_Y + 0.32


def _on_counter(h, fallback):
    return fallback if h is None else (h.x, min(max(h.y, CT_FRONT), CT_BACK), 1.20)


BAG_BEFORE = _on_counter(CLERK_H, (CT_X - 0.55, CT_Y + 0.26, 1.20))   # 付款前:店员侧
BAG_AFTER  = (CT_X + 0.60, CT_Y - 0.28, 1.20)                          # 付款后:她右手边
box("礼袋", *BAG_BEFORE, 0.42, 0.14, 0.32, P["PROP"], role="prop")
PHONE = (LEAD_H.x, LEAD_H.y, LEAD_H.z + 0.03) if LEAD_H else (CT_X + 0.10, CT_Y - 0.16, 1.24)
box("手机", *PHONE, 0.075, 0.15, 0.012, P["PROP"], role="prop")

# ── 机位:焦距按「目标画幅宽」反算，不看渲染图调 ──
EYE = 1.50
CAMS = {
 "A_橱窗中景": (( 0.80, 0.75, 1.58), (-1.10, 3.55, 1.14), 45),
 "B_入口中景": ((-1.85, 2.25, 1.55), ( 0.55, 3.90, 1.35), 40),
 "C_柜台中景": (( 2.85, 5.05, EYE),  (-0.15, 6.55, 1.15), 40),
 # 台面在 1.09 —— 平视会贴着台面，插镜要从上方俯下来
 "D_包装手部": ((BAG_BEFORE[0] + 0.86, BAG_BEFORE[1] - 1.02, 1.78), (BAG_BEFORE[0], BAG_BEFORE[1], 1.18), 38),
 "E_店员过肩": ((CLERK[0] - 0.42, CLERK[1] + 0.62, 1.58), (LEAD_CT[0], LEAD_CT[1] + 0.10, 1.30), 46),
 "F_终端特写": ((TERM[0] + 0.62, TERM[1] - 0.58, 1.62), (TERM[0], TERM[1] + 0.02, 1.16), 55),
 "G_柜台横向": (( 3.30, 6.05, 1.42), (CT_X - 0.30, CT_Y, 1.16), 48),
}
for n, (loc, look, lens) in CAMS.items():
    cam(S, n, loc, look, lens)

SHOTS = [
    ("S1", "A_橱窗中景",  0.0,  3.2, "WINDOW",  "视线落在橱窗里那件东西，短吸气"),
    ("S2", "B_入口中景",  3.2,  5.0, "DOOR",    "移开视线，主动推门进入"),
    ("S3", "C_柜台中景",  5.0,  7.4, "COUNTER", "商品进入防尘袋，店员系上丝带"),
    ("S4", "D_包装手部",  7.4,  9.2, "COUNTER", "防尘袋放进礼袋、扶正提手；礼袋仍在店员侧"),
    ("S5", "E_店员过肩",  9.2, 11.6, "COUNTER", "店员过肩报价，她短停"),
    ("S6", "F_终端特写", 11.6, 13.2, "COUNTER", "手机贴近终端，提示音后手先松开"),
    ("S7", "G_柜台横向", 13.2, 16.0, "COUNTER", "确认付款后，礼袋才被推过柜台中线"),
]
MOVES = {"S5": 0.14, "S7": -0.18}     # 数字 = 沿视线推拉;三元组 = 任意平移
WALKS = {}

if MODE == "audit":
    import bpy
    rig.audit_model_pass(bpy.data.objects)     # 送模版明度自检
elif MODE == "probe":
    import bpy
    print("── 人体关节实测 ──")
    for n in ("LEAD_窗_头", "LEAD_台_头", "LEAD_台_hand.R", "CLERK_头", "CLERK_hand.R"):
        o = bpy.data.objects.get(n)
        if o:
            c = o.matrix_world.translation
            print(f"  {n:<16} ({c.x:+.2f},{c.y:+.2f},{c.z:+.2f})")
    print(f"  柜台面 z=1.09   礼袋(前) {tuple(round(v, 2) for v in BAG_BEFORE)}")
    print(f"  终端 {TERM}   手机 {tuple(round(v, 2) for v in PHONE)}")
elif MODE == "blockers":
    import bpy, project
    SUBJ = {"S1": (WIN_CX, GLASS_Y + 0.42, 1.06), "S2": (0.55, GLASS_Y, 1.60),
            "S3": (CT_X, CT_Y, 1.15), "S4": (BAG_BEFORE[0], BAG_BEFORE[1], 1.14),
            "S5": (LEAD_CT[0], LEAD_CT[1], 1.40), "S6": TERM, "S7": (CT_X, CT_Y, 1.16)}
    for sid, cname, t0, t1, _g, txt in SHOTS:
        loc, look, lens = CAMS[cname]
        # 主体本身和主体手上的小道具要排掉，否则每一镜都报一条假警报
        hs = project.blockers(loc, look, lens, SUBJ[sid], bpy.data.objects,
                              ignore=("手机", "礼袋", "支付终端", "陈列品"))
        print(f"{sid} {cname} → {txt[:24]}")
        if not hs:
            print("   通畅")
        for gap, name, d, r in hs:
            print(f"   {'✗挡' if gap < 0 else ' 擦边'} {name:<16} 距{d:4.2f}m 离轴{gap + r:5.2f}m")
elif MODE in ("project", "export"):
    import project
    # 第三项是类别:景别是按**人**在画幅里的高度定义的，
    # 拿门洞或柜台去算景别只会得到胡话(实测:门洞占高 220% 被判成「特写」)。
    MARKS = {"陈列品":  ((WIN_CX, GLASS_Y + 0.42, 1.06), (0.40, 0.20, 0.40), "prop"),
             "橱窗洞口": ((WIN_CX, GLASS_Y, (WIN_Z0 + WIN_Z1) / 2), (WIN_X1 - WIN_X0, 0.06, WIN_Z1 - WIN_Z0), "set"),
             "入口门洞": (((DR_X0 + DR_X1) / 2, GLASS_Y, DR_Z1 / 2), (DR_X1 - DR_X0, 0.06, DR_Z1), "set"),
             "LEAD(窗)": ((WIN_POS[0], WIN_POS[1], 1.00), (0.46, 0.42, 1.66), "person"),
             "LEAD(台)": ((LEAD_CT[0], LEAD_CT[1], 1.00), (0.46, 0.42, 1.66), "person"),
             "CLERK":   ((CLERK[0], CLERK[1], 1.00), (0.46, 0.42, 1.70), "person"),
             "柜台面":   ((CT_X, CT_Y, 1.06), (2.72, 0.82, 0.05), "set"),
             "支付终端": (TERM, (0.16, 0.12, 0.12), "prop"),
             "手机":    (PHONE, (0.075, 0.15, 0.012), "prop"),
             "礼袋":    (BAG_BEFORE, (0.42, 0.14, 0.32), "prop")}
    if MODE == "export":
        # 把「白模事实」导出去，让 check_prompt.py 拿它和 prompt 对账。
        # 人眼对不了这种事:prompt 写「她在画面左侧」，而白模算出来 x=+0.6 是右侧。
        import json
        out = []
        for sid, cname, t0, t1, _g, txt in SHOTS:
            loc, look, lens = CAMS[cname]
            marks = {}
            for name, mk in MARKS.items():
                pt, dims = mk[0], mk[1]
                kind = mk[2] if len(mk) > 2 else "set"
                x, y, d = project.project(loc, look, lens, pt)
                if x is None or abs(x) > 1.6 or abs(y) > 1.6:
                    continue
                w, h = project.size_on_screen(loc, look, lens, pt, dims)
                marks[name] = {"x": round(x, 3), "y": round(y, 3), "kind": kind,
                               "w": round(w, 3), "h": round(h, 3), "d": round(d, 2)}
            out.append({"id": sid, "cam": cname, "t0": t0, "t1": t1,
                        "lens": lens, "note": txt, "marks": marks})
        pathlib.Path(OUT).write_text(
            json.dumps({"shots": out}, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"EXPORT_DONE {OUT}  {len(out)} 镜")
    else:
        print(project.report(SHOTS, CAMS, MARKS))
elif MODE == "review":
    rig.use_review_pass(S, note="示例 · 精品店 街边店面与柜台")
    rig.render_stills(S, CAMS, OUT, FIG, SHOTS)
elif MODE == "plan":
    rig.render_plan(S, CAMS, OUT + "/plan.png", size=13.0, center=(0.0, 4.2))
elif MODE == "review_anim":
    rig.use_review_pass(S, note="示例 · 精品店 街边店面与柜台")
    rig.render_anim(S, SHOTS, CAMS, OUT, FIG, MOVES, WALKS)
elif MODE == "anim":
    rig.render_anim(S, SHOTS, CAMS, OUT, FIG, MOVES, WALKS)
