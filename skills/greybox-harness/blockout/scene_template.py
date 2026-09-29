"""场景模板 —— 复制这个文件开新场景，从上往下填。

命名建议 `scXX_<空间>.py`。一个文件只装一个物理空间的:几何、机位、时间轴。
不要在这里写任何美术描述(材质、颜色、光)——那些属于 prompt 和空镜参考图。

跑法(六个模式，从便宜到贵，**按顺序走**):
  blender -b --python scene.py -- probe            # 读人体关节的实测世界坐标
  blender -b --python scene.py -- project          # 每个元素在画面的位置/占幅/距离
  blender -b --python scene.py -- blockers         # 谁挡住了谁
  blender -b --python scene.py -- plan   /tmp/x    # 俯视平面图 + 视锥
  blender -b --python scene.py -- review /tmp/x    # 审片静帧(彩色描边，给人看)
  blender -b --python scene.py -- review_anim /tmp/x   # 审片视频 → 人 confirm
  blender -b --python scene.py -- anim   /tmp/x    # 送模视频(平光灰模) → 喂生成模型
"""
import sys, os, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rig
from rig import box, cyl, cam
import human
from human import mannequin

ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
MODE = ARGS[0] if ARGS else "review"
OUT  = ARGS[1] if len(ARGS) > 1 else "/tmp/scene"

S = rig.new_scene()
P = rig.palette()

# ─────────────────────────────────────────────────────────────
# 1. 坐标约定 —— 先定好，后面全靠它
# ─────────────────────────────────────────────────────────────
# 建议:X = 画面左右(人物行进方向取 +X)、Y = 纵深、Z = 高。
# **机位要正对主墙(视线沿 +Y)**，这样 +X 才等于「画面右」。
# 镜头一斜，沿 +Y 更远的东西会绕到画面左边去 —— 匹配剪的方向锁就守不住了。
X0, X1, Y0, Y1, ZC = -6.0, 6.0, 0.0, 8.0, 3.0

# ─────────────────────────────────────────────────────────────
# 2. 房间外壳
# ─────────────────────────────────────────────────────────────
rig.room(S, P, X0, X1, Y0, Y1, ZC, panel=True)
# 露天场景就别用 room()，手工铺地 + 立面，头顶留空。

# **要看穿的地方必须是真的洞。** 门洞、橱窗、电梯口一律用「分段的墙 + 留空」建，
# 不要放一块半透明板 —— Workbench 里没有透明，放了就是一堵实心墙。
# DR_X0, DR_X1, DR_Z1 = -0.8, 0.8, 2.2
# box("墙_左", (X0 + DR_X0) / 2, Y1, ZC / 2, DR_X0 - X0, 0.12, ZC, P["WALL"], role="shell")
# box("墙_右", (DR_X1 + X1) / 2, Y1, ZC / 2, X1 - DR_X1, 0.12, ZC, P["WALL"], role="shell")
# box("门楣",  (DR_X0 + DR_X1) / 2, Y1, (DR_Z1 + ZC) / 2, DR_X1 - DR_X0, 0.12, ZC - DR_Z1, P["WALL"], role="shell")

# 大面积空墙在透视里是一整片灰 —— 排一列等间距竖肋当刻度尺，纵深立刻读得出来。
# for i in range(20):
#     box(f"肋{i}", X0 + 0.5 + i * 0.6, Y1 - 0.1, ZC / 2, 0.07, 0.12, ZC, P["WALL"], role="shell")

# ─────────────────────────────────────────────────────────────
# 3. 家具 —— 只做「影响这是什么房间」的那几件
# ─────────────────────────────────────────────────────────────
# rig.desk("桌", 0.0, 4.0, P, w=1.6, d=0.75)
# rig.chair("椅", 0.0, 3.2, P, face=90)        # face 是**坐着的人面朝哪**，不是椅子朝向
# rig.monitor("屏", 0.0, 4.3, P, yaw=math.radians(25))   # 屏幕转开，任何机位都拍不到正面

# ─────────────────────────────────────────────────────────────
# 4. 人物 —— 每一组走位建一个，用 FIG 的 key 区分
# ─────────────────────────────────────────────────────────────
LEAD_POS = (0.0, 2.6)
LEAD = mannequin("LEAD", LEAD_POS, 90, "stand", P, height=1.66)
# 坐姿必须给 seat_z=，否则人浮在半空:
# LEAD = mannequin("LEAD", (0, 3.2), 90, "sit_phone", P, height=1.66, seat_z=0.52)
FIG = {"A": LEAD}

# ─────────────────────────────────────────────────────────────
# 5. 道具 —— 建完人再放，坐标从**手的实测世界坐标**取，不要硬填
# ─────────────────────────────────────────────────────────────
# h = human.hand("LEAD", "R")
# PROP = box("道具", h.x, h.y, h.z - 0.2, 0.3, 0.15, 0.3, P["PROP"], role="prop")

# 走位戏:把人和他手上的道具挂到同一个手柄上，整组平移
# G_A = rig.group(LEAD + [PROP], "A")

# ─────────────────────────────────────────────────────────────
# 6. 机位 —— 焦距用公式反算，不要看渲染图调
#    焦距 = 36mm ÷ 目标画幅宽(米) × 距离(米)
# ─────────────────────────────────────────────────────────────
CAMS = {
    "A_中景": ((0.0, 0.6, 1.52), (0.0, 3.4, 1.30), 35),
}
for n, (loc, look, lens) in CAMS.items():
    cam(S, n, loc, look, lens)

# ─────────────────────────────────────────────────────────────
# 7. 时间轴 —— (镜号, 机位名, 起秒, 止秒, 人物组key, 这一镜在演什么)
#    这张表是**唯一真相**:prompt 的时间码、切片边界、切点核验全都从它取。
# ─────────────────────────────────────────────────────────────
SHOTS = [
    ("S1", "A_中景", 0.0, 4.0, "A", "这一镜在演什么"),
]
MOVES = {}    # {镜号: 米数(沿视线推拉) 或 (dx,dy,dz)(任意平移，横移用这个)}
WALKS = {}    # {镜号: (手柄, (x0,y0), (x1,y1))}

# ─────────────────────────────────────────────────────────────
# 8. 六个模式 —— 直接抄，不用改
# ─────────────────────────────────────────────────────────────
if MODE == "probe":
    import bpy
    print("── 人体关节实测 ──")
    for n in ("LEAD_头", "LEAD_hand.R", "LEAD_hand.L", "LEAD_foot.L"):
        o = bpy.data.objects.get(n)
        if o:
            c = o.matrix_world.translation
            print(f"  {n:<16} ({c.x:+.2f},{c.y:+.2f},{c.z:+.2f})")
elif MODE == "blockers":
    import bpy, project
    SUBJ = {"S1": (LEAD_POS[0], LEAD_POS[1], 1.40)}      # 每一镜真正要拍的那个点
    for sid, cname, t0, t1, _g, txt in SHOTS:
        loc, look, lens = CAMS[cname]
        hs = project.blockers(loc, look, lens, SUBJ[sid], bpy.data.objects)
        print(f"{sid} {cname} → {txt[:22]}")
        print("   通畅" if not hs else "")
        for gap, name, d, r in hs:
            print(f"   {'✗挡' if gap < 0 else ' 擦边'} {name:<18} 距{d:4.2f}m 离轴{gap + r:5.2f}m")
elif MODE == "project":
    import project
    MARKS = {   # {显示名: (坐标, (宽,深,高))} —— 输出可以直接抄进 prompt 当空间描述
        "LEAD": ((LEAD_POS[0], LEAD_POS[1], 0.90), (0.46, 0.42, 1.66)),
    }
    print(project.report(SHOTS, CAMS, MARKS))
elif MODE == "review":
    rig.use_review_pass(S, note="场景名 · 一句话")
    rig.render_stills(S, CAMS, OUT, FIG, SHOTS)          # 后两个参数别省，否则所有人物组同时入画
elif MODE == "plan":
    rig.render_plan(S, CAMS, OUT + "/平面图.png", size=14.0, center=(0.0, 3.0))
elif MODE == "review_anim":
    rig.use_review_pass(S, note="场景名 · 一句话")
    rig.render_anim(S, SHOTS, CAMS, OUT, FIG, MOVES, WALKS)
elif MODE == "anim":
    rig.render_anim(S, SHOTS, CAMS, OUT, FIG, MOVES, WALKS)
