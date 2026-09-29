#!/usr/bin/env python3
"""把白模里的物体投影到每个机位的画面上，算出它在画面的哪个位置、多大、离镜头多远。

为什么要有这个:prompt 里的空间描述如果由人手写，就会出现 实测 这一天的两次错误——
「我以为视线不挡，实际穿过她的脑袋」「我以为她逆光成剪影，实际灰度 171 对 185」。
白模里坐标和机位都是已知的，投影算出来的数字不会骗人，直接拿去写进 prompt。

用法(在 Blender 里跑，因为要读场景):
  blender -b --python <scene>.py -- project
输出每个镜头一段，形如:
  S1  A_中景  35mm
     LEAD        画面 x=-0.42 y=-0.05  占宽 18% 高 41%  距 3.6m   → 画面左侧中部
     手机        画面 x=-0.11 y=-0.38  占宽  3% 高  2%  距 3.9m   → 画面中部偏下
"""
import math
from mathutils import Vector


def _cam_basis(loc, look):
    f = (Vector(look) - Vector(loc)).normalized()          # 视线方向
    up0 = Vector((0, 0, 1))
    r = f.cross(up0)
    if r.length < 1e-6:                                     # 正上/正下看时退化
        r = Vector((1, 0, 0))
    r.normalize()
    u = r.cross(f).normalized()
    return f, r, u


def project(loc, look, lens, pt, *, sensor=36.0):
    """返回 (x, y, depth)。x/y 是相对半幅的归一化坐标:
    x=-1 画面最左、+1 最右;y=-1 最下、+1 最上;超出 ±1 就是出画。"""
    f, r, u = _cam_basis(loc, look)
    v = Vector(pt) - Vector(loc)
    d = v.dot(f)
    if d <= 1e-4:
        return None, None, d                                # 在镜头背后
    half_w = sensor / 2 / lens * d                          # 该深度处的半幅宽(米)
    half_h = half_w * 9 / 16
    return v.dot(r) / half_w, v.dot(u) / half_h, d


def size_on_screen(loc, look, lens, pt, dims, *, sensor=36.0):
    """物体占画幅的比例(宽, 高)，dims=(sx, sy, sz) 用外接盒近似。"""
    f, r, u = _cam_basis(loc, look)
    d = (Vector(pt) - Vector(loc)).dot(f)
    if d <= 1e-4:
        return 0.0, 0.0
    half_w = sensor / 2 / lens * d
    half_h = half_w * 9 / 16
    # 外接盒在右向/上向上的投影范围
    ex = sum(abs(c * a) for c, a in zip(r, (dims[0] / 2, dims[1] / 2, dims[2] / 2)))
    ez = sum(abs(c * a) for c, a in zip(u, (dims[0] / 2, dims[1] / 2, dims[2] / 2)))
    return ex / half_w, ez / half_h


def where(x, y):
    """把归一化坐标翻译成中文方位，直接能写进 prompt。"""
    if x is None:
        return "在镜头背后"
    h = "画面左" if x < -0.33 else ("画面右" if x > 0.33 else "画面中")
    v = "偏下" if y < -0.33 else ("偏上" if y > 0.33 else "中部")
    edge = "" if abs(x) <= 1 and abs(y) <= 1 else "（出画）"
    return f"{h}{v}{edge}"


def occludes(loc, look, lens, blocker_pt, blocker_r, target_pt, *, sensor=36.0):
    """blocker 会不会挡住 target —— 三维垂距判定。
    实测 教训:只在某个 y 平面上比 x/z 会漏掉纵深，算出「不挡」实际穿过脑袋。"""
    f, _, _ = _cam_basis(loc, look)
    bv = Vector(blocker_pt) - Vector(loc)
    tv = Vector(target_pt) - Vector(loc)
    bd, td = bv.dot(f), tv.dot(f)
    if bd <= 0 or bd >= td:
        return False, 0.0                                   # 不在镜头与目标之间
    axis = (tv.normalized())
    perp = (bv - axis * bv.dot(axis)).length
    return perp < blocker_r, perp


def blockers(loc, look, lens, target, objs, *, sensor=36.0, top=6, ignore=()):
    """扫描场景，列出挡在机位和主体之间的物件 —— 别再靠看渲染图猜「那堵灰墙是什么」。

    垂距要**横竖分开量**。实测 教训:用 max(dims)/2 当外接球半径，
    一根 0.14×0.14×3.4 的门柱半径算出 1.7m，横向离轴 0.76m 也报「挡住」;
    一张 2.72m 宽、5cm 厚的柜台面同理。结果四个机位被误判成废片，其实全都通畅。
    现在:横向比 max(dx,dy)/2、竖向比 dz/2，两个方向都进去了才算挡。
    """
    f, r_ax, u_ax = _cam_basis(loc, look)
    tv = Vector(target) - Vector(loc)
    td = tv.dot(f)
    axis = tv.normalized()
    # 大平面本来就该在画面里，按名字滤掉。
    # ignore= 用来排除「这一镜的主体本身」和它手上那件小道具 —— 它们当然在视线上，
    # 不排掉的话每一镜都会报一条假警报，真警报就被淹了。
    SHELL = ("地面", "天花", "墙_", "发光天棚") + tuple(ignore)
    hits = []
    for o in objs:
        if o.type != 'MESH' or any(k in o.name for k in SHELL):
            continue
        c = o.matrix_world.translation
        dx, dy, dz = o.dimensions
        rh, rv = max(dx, dy) / 2, dz / 2
        bv = Vector(c) - Vector(loc)
        bd = bv.dot(f)
        if bd <= 0.05 or bd >= td - 0.02:
            continue
        foot = Vector(loc) + axis * bv.dot(axis)     # 视线上离它最近的那一点
        off = Vector(c) - foot
        oh = math.hypot(off.x, off.y)                # 水平错开多少
        ov = abs(off.z)                              # 竖向错开多少
        if oh < rh and ov < rv:                      # 横竖都进去了才算挡
            hits.append((max(oh - rh, ov - rv), o.name, bd, max(rh, rv)))
    hits.sort()
    return hits[:top]


def report(shots, cams, marks):
    """shots: [(镜号, 机位名, 起, 止, 组, 说明)]
    cams:   {机位名: (loc, look, lens)}
    marks:  {显示名: (坐标, (sx,sy,sz))} 或 {显示名: (坐标, (sx,sy,sz), 类别)}
            类别取 "person" / "prop" / "set"，只有 export 用得到，report 忽略它。"""
    out = []
    for sid, cname, t0, t1, _pos, txt in shots:
        loc, look, lens = cams[cname]
        out.append(f"{sid}  {cname}  {lens}mm  {t0:.1f}–{t1:.1f}s  {txt[:26]}")
        for name, mk in marks.items():
            pt, dims = mk[0], mk[1]
            x, y, d = project(loc, look, lens, pt)
            if x is None:
                continue
            w, h = size_on_screen(loc, look, lens, pt, dims)
            if abs(x) > 1.6 or abs(y) > 1.6:
                continue                                    # 离画面太远，不用写进 prompt
            # size_on_screen 返回的是「半外接尺寸 ÷ 半幅」，这个比值本身就等于占全幅的比例。
            # 之前打印成 w*50，等于把所有占幅数字砍了一半 —— 焦距是照着这些数字反算的，
            # 所以「手机只占 9%」那次判断其实偏保守了一倍(实测 查 V2 时发现)。
            out.append(f"   {name:<10} x={x:+.2f} y={y:+.2f}  占宽{w*100:4.0f}% 高{h*100:4.0f}%  "
                       f"距{d:4.1f}m  → {where(x, y)}")
    return "\n".join(out)
