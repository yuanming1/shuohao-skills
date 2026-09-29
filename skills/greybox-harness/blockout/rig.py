"""白模通用件 —— 所有场景文件都从这里 import，不要复制粘贴场景之间的公共代码。

第一个场景从建到能用迭代了七八轮，踩过的坑全部固化在这里:
  1. primitive_cube_add(size=1) 的半边长是 0.5,scale 直接就是边长,别再除 2。
  2. 白模只是图纸:小道具不给造型(会被当成家具设计抄走)、光不给方向(会被一并抄走)。
     层次靠材质明度差,不靠打光。造型/材质/光全部交给空镜参考图。
  3. 圆柱没有朝向 —— 必须给肩宽板和朝向楔子,否则模型让人物面向镜头,人物关系全错。
  4. 屏幕类物件要在几何上转开角度,「禁止屏幕出现文字」这种否定句无效。
  5. 每个镜头一台独立相机副本,同一机位被多镜复用时运镜关键帧才不会互相污染。
  6. 布尔属性的关键帧默认 CONSTANT 插值;Blender 5 的 Action 没有 .fcurves。
  7. 切片必须按镜头边界自动取,手填帧数会切在镜头中间(实测 事故)。
"""
import bpy, math, os, importlib.util
from mathutils import Vector


# ─────────────────────────── 场景初始化 ───────────────────────────
def new_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    S = bpy.context.scene
    S.render.engine = 'BLENDER_EEVEE'
    S.render.resolution_x, S.render.resolution_y = 1280, 720
    S.render.fps = 24
    S.render.image_settings.file_format = 'PNG'
    S.view_settings.view_transform = 'Standard'
    w = bpy.data.worlds.new("W"); S.world = w; w.use_nodes = True
    bg = w.node_tree.nodes["Background"]
    bg.inputs[0].default_value = (0.85, 0.86, 0.88, 1)
    bg.inputs[1].default_value = 0.85          # 平光:无方向、只靠材质明度分层
    return S


def mat(name, rgb, rough=0.85):
    m = bpy.data.materials.new(name); m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*rgb, 1)
    b.inputs["Roughness"].default_value = rough
    return m


# 明度层级 —— 实测 重排:原来墙 0.66 / 人 0.56 / 地 0.40，人夹在墙和地中间，
# 谁也分不开(实测:人眼根本找不到人在哪)。现在让人成为画面里最深的东西:
#   窗/屏 0.88 > 墙 0.74 > 木家具 0.60 > 深家具 0.52 > 地 0.44 > 配角 0.36 > 关键道具 0.26 > 主角 0.18
# 主角比配角再深一档，一眼能认出谁是谁。
def palette():
    return dict(
        WALL  = mat("wall",  (0.74,) * 3),
        WOOD  = mat("wood",  (0.60, 0.58, 0.55)),
        FLOOR = mat("floor", (0.44, 0.45, 0.47)),
        DARK  = mat("dark",  (0.52, 0.51, 0.49)),   # 深色家具:比木桌深一档能分出椅子，但仍远浅于人
        RELIEF= mat("relief",(0.66, 0.66, 0.65)),   # 墙上的凸出物:壁柱、竖肋、瓷砖缝、台度。
                                                    # 和 WALL 差 0.08 —— 审片版靠描边就能分开,
                                                    # 但送模版只有明度,不给这一档就会糊成一整片墙。
        SCRN  = mat("scrn",  (0.88, 0.89, 0.90), 0.35),
        GLASS = mat("glass", (0.92, 0.94, 0.96)),
        BODY  = mat("body",  (0.18, 0.18, 0.19)),   # 主角
        EXTRA = mat("extra", (0.36, 0.36, 0.37)),   # 配角
        PROP  = mat("prop",  (0.26, 0.26, 0.27)),   # 「这一镜要拍的那件东西」——手机/工作本之类，
                                                    # 不给这一档的话它会和家具同色，插镜就白拍了
    )


# 审片版的语义配色 —— 按「这是什么」上色，不是按明度。
# 送模版(EEVEE 平光)看不到这些颜色，它只看材质明度层级。
ROLE_COLOR = {
    "lead":      (1.00, 0.42, 0.06),   # 主角:高饱和橙 —— 必须和家具木色拉开
    "extra":     (0.20, 0.48, 0.92),   # 配角:高饱和蓝
    "prop":      (0.90, 0.25, 0.25),   # 这一镜要拍的那件东西:红
    "furniture": (0.70, 0.69, 0.66),   # 家具:去饱和的暖灰(饱和木色会和主角撞)
    "screen":    (0.86, 0.92, 0.98),   # 屏幕/玻璃:冷白
    "shell":     (0.80, 0.80, 0.82),   # 墙、地、天花:中性灰
}


def _tint(o, role):
    o.color = (*ROLE_COLOR.get(role, ROLE_COLOR["shell"]), 1.0)
    o["role"] = role


# ─────────────────────────── 建体块 ───────────────────────────
def box(name, cx, cy, cz, sx, sy, sz, m, yaw=0.0, role="shell"):
    bpy.ops.mesh.primitive_cube_add(size=1, location=(cx, cy, cz))
    o = bpy.context.object; o.name = name
    o.scale = (sx, sy, sz)                     # size=1 的立方体半边长 0.5 → scale 就是边长
    o.rotation_euler = (0, 0, yaw)
    o.data.materials.append(m)
    _tint(o, role)
    return o


def cyl(name, cx, cy, cz, r, h, m, role="shell"):
    bpy.ops.mesh.primitive_cylinder_add(radius=r, depth=h, location=(cx, cy, cz))
    o = bpy.context.object; o.name = name
    o.data.materials.append(m)
    _tint(o, role)
    return o


def room(S, P, x0, x1, y0, y1, zc, *, panel=True):
    """房间外壳。返回 (中心X, 宽)。panel=True 时天花给一块发光天棚。"""
    cx, w, d = (x0 + x1) / 2, x1 - x0, y1 - y0
    cy = (y0 + y1) / 2
    box("地面", cx, cy, -0.05, w, d, 0.1, P["FLOOR"], role="shell")
    box("天花", cx, cy, zc + 0.05, w, d, 0.1, P["WALL"], role="shell")
    if panel:
        box("发光天棚", cx, cy, zc - 0.03, w * 0.55, d * 0.5, 0.06,
            mat("panel", (0.95, 0.95, 0.94), 0.3))
    box("墙_后", cx, y1 + 0.05, zc / 2, w, 0.1, zc, P["WALL"], role="shell")
    box("墙_前", cx, y0 - 0.05, zc / 2, w, 0.1, zc, P["WALL"])
    box("墙_左", x0 - 0.05, cy, zc / 2, 0.1, d, zc, P["WALL"])
    box("墙_右", x1 + 0.05, cy, zc / 2, 0.1, d, zc, P["WALL"])
    return cx, w


def window(P, wall_x, y0, y1, sill, head, zc, *, mullions=(), depth_axis='x'):
    """带台度墙和吊顶横梁的横向窗 —— 不是通高玻璃幕墙(很多实拍空镜其实是这种横向窗，不是幕墙)。"""
    cy, dy = (y0 + y1) / 2, y1 - y0
    box("窗_台度墙", wall_x, cy, sill / 2, 0.1, dy, sill, P["WALL"])
    box("窗_吊顶梁", wall_x, cy, (head + zc) / 2, 0.1, dy, zc - head, P["WALL"])
    box("窗_玻璃", wall_x, cy, (sill + head) / 2, 0.06, dy - 0.1, head - sill, P["GLASS"], role="screen")
    for i, y in enumerate(mullions):
        box(f"窗框{i}", wall_x + 0.03, y, (sill + head) / 2, 0.1, 0.09, head - sill, P["WALL"])


# ─────────────────────── 常用家具构件 ───────────────────────
# 只做椅子/显示器/桌子这三样 —— 出现频率最高，也最影响「这是不是一间办公室」的判断。
# 其余家具维持体块，白模不需要把所有东西都做出来。

def chair(tag, x, y, P, *, face=90.0, seat=0.46, w=0.48):
    """座面 + 靠背 + 中柱 + 五星脚。

    face 是**坐在上面那个人面朝的方向**(度，0=+X，90=+Y)，不是椅子自身的朝向 ——
    靠背永远放在这个方向的反面。实测 踩过:参数写成「椅子朝向」，结果靠背
    立在人和桌子中间。
    """
    F = P["DARK"]
    a = math.radians(face)
    bx, by = x - math.cos(a) * w * 0.46, y - math.sin(a) * w * 0.46   # 靠背在人背后
    o = [box(f"{tag}_座", x, y, seat, w, w, 0.07, F, a, role="furniture"),
         box(f"{tag}_背", bx, by, seat + 0.30, w, 0.06, 0.54, F, a - math.pi / 2, role="furniture"),
         cyl(f"{tag}_柱", x, y, seat / 2, 0.035, seat, F, role="furniture")]
    for i in range(5):
        t = a + i * (2 * math.pi / 5)
        o.append(box(f"{tag}_脚{i}", x + math.cos(t) * 0.16, y + math.sin(t) * 0.16,
                     0.03, 0.28, 0.045, 0.045, F, t, role="furniture"))
    return o


def monitor(tag, x, y, P, *, yaw=0.0, w=0.52, h=0.32, deskz=0.74):
    """屏面 + 颈 + 底座。"""
    F, SC = P["DARK"], P["SCRN"]
    return [box(f"{tag}_屏", x, y, deskz + 0.10 + h / 2, w, 0.03, h, SC, yaw, role="screen"),
            box(f"{tag}_颈", x, y, deskz + 0.055, 0.05, 0.05, 0.11, F, yaw, role="furniture"),
            box(f"{tag}_座", x, y + 0.04, deskz + 0.012, 0.20, 0.14, 0.024, F, yaw, role="furniture")]


def desk(tag, x, y, P, *, w=1.55, d=0.72, yaw=0.0, top=0.74, thick=0.04):
    """台面 + 四条桌腿。之前是台面加一个实心块，人坐进去看着像陷在桌子里。"""
    F = P["WOOD"]
    o = [box(f"{tag}_面", x, y, top, w, d, thick, F, yaw, role="furniture")]
    for i, (sx, sy) in enumerate(((-1, -1), (1, -1), (-1, 1), (1, 1))):
        lx = sx * (w / 2 - 0.06); ly = sy * (d / 2 - 0.06)
        rx = x + lx * math.cos(yaw) - ly * math.sin(yaw)
        ry = y + lx * math.sin(yaw) + ly * math.cos(yaw)
        o.append(box(f"{tag}_腿{i}", rx, ry, (top - thick) / 2, 0.05, 0.05, top - thick,
                     P["DARK"], yaw, role="furniture"))
    return o


# ─────────────────────── 人物代理(带朝向) ───────────────────────
def figure(tag, x, y, face, P, *, seated=False, lead=True, boxy=False):
    """圆柱没有朝向 —— 必须补肩宽板和朝向楔子。
    实测:只给圆柱，模型让人物直接面向镜头，角色之间的关系全错。"""
    yaw = math.atan2(face[1] - y, face[0] - x) - math.pi / 2   # 肩板宽边垂直于朝向
    B = P["BODY"] if lead else P["EXTRA"]   # 主角最深、配角次深，一眼分得出谁是谁
    R = "lead" if lead else "extra"
    # 主角躯干用圆柱、配角用方块 —— 剪影就不一样，比「深一点浅一点」可靠得多。
    # prompt 里可以写死:唯一一个圆柱躯干的人是主角。
    trunk = box if boxy else None
    if seated:
        objs = [box(f"{tag}_大腿", x, y - 0.26, 0.52, 0.36, 0.52, 0.16, B, role=R),
                (box(f"{tag}_躯干", x, y, 0.88, 0.40, 0.36, 0.64, B, yaw, role=R) if boxy
                 else cyl(f"{tag}_躯干", x, y, 0.88, 0.21, 0.64, B, role=R)),
                (box(f"{tag}_头", x, y, 1.31, 0.21, 0.21, 0.24, B, yaw, role=R) if boxy
                 else cyl(f"{tag}_头", x, y, 1.31, 0.115, 0.24, B, role=R))]
        zs, zn, hz = 1.14, 1.29, 1.29
    else:
        objs = [cyl(f"{tag}_腿", x, y, 0.41, 0.15, 0.82, B, role=R),
                (box(f"{tag}_躯干", x, y, 1.15, 0.34, 0.30, 0.66, B, yaw, role=R) if boxy
                 else cyl(f"{tag}_躯干", x, y, 1.15, 0.17, 0.66, B, role=R)),
                (box(f"{tag}_头", x, y, 1.60, 0.19, 0.19, 0.23, B, yaw, role=R) if boxy
                 else cyl(f"{tag}_头", x, y, 1.60, 0.105, 0.23, B, role=R))]
        zs, zn, hz = 1.42, 1.58, 1.58
    objs.append(box(f"{tag}_肩", x, y, zs, 0.46, 0.20, 0.10, B, yaw, role=R))
    nx, ny = math.cos(yaw + math.pi / 2), math.sin(yaw + math.pi / 2)
    objs.append(box(f"{tag}_朝向", x + nx * 0.17, y + ny * 0.17, zn, 0.10, 0.21, 0.10, B, yaw, role=R))
    return objs


def lying(tag, x, y, z, face, P):
    """躺着的人(床上)——用一块长板加头,朝向楔子指向脸朝的方向。"""
    yaw = math.atan2(face[1] - y, face[0] - x)
    B = P["BODY"]
    return [box(f"{tag}_身", x, y, z + 0.12, 1.55, 0.45, 0.24, B, yaw),
            cyl(f"{tag}_头", x + math.cos(yaw) * 0.85, y + math.sin(yaw) * 0.85, z + 0.20, 0.11, 0.22, B)]


# ─────────────────────────── 机位 ───────────────────────────
def cam(S, name, loc, look, lens):
    c = bpy.data.cameras.new(name); c.lens = lens
    o = bpy.data.objects.new(name, c); S.collection.objects.link(o)
    o.location = Vector(loc)
    o.rotation_euler = (Vector(look) - Vector(loc)).to_track_quat('-Z', 'Y').to_euler()
    return o


# ─────────────────────── 双通道渲染 ───────────────────────
# 送模版(EEVEE 平光)是已验证有效的变量(P1a/P1b/P2 三条都这么出的)，一个字不改。
# 审片版(Workbench)只给人看 —— 描边、空腔、投影、按语义上色、烧镜号。

def audit_model_pass(objs, *, quiet=False):
    """列出送模版里明度相同、会糊在一起的物件。

    **这是双通道最容易骗人的地方。** 审片版靠描边 + 语义配色分层，
    所以两个明度一样的东西在审片版上泾渭分明;送模版只有明度，它们就是一片。
    实测:一个 role="furniture" 的展陈台座用了 P["WALL"] 的材质，
    审片版上台座清清楚楚，送模版里它和背后那面墙完全融成一片 —— 模型根本拿不到它。

    结论:**「几何一致」不等于「信息一致」。** 建完场景跑一遍这个，
    凡是 role 不同却共用同一份材质的，都要换掉。
    """
    import collections
    by_mat = collections.defaultdict(set)
    for o in objs:
        if o.type != 'MESH' or not o.data.materials:
            continue
        by_mat[o.data.materials[0].name].add((o.get("role", "?"), o.name))
    bad = []
    for m, items in by_mat.items():
        roles = {r for r, _ in items}
        if len(roles) > 1:
            bad.append((m, sorted(roles), sorted(n for _, n in items)[:4]))
    if not quiet:
        if not bad:
            print("送模版明度自检:通过 —— 没有 role 不同却共用材质的物件")
        for m, roles, sample in bad:
            print(f"⚠ 材质「{m}」被这些 role 共用: {roles}")
            print(f"   例如: {', '.join(sample)}")
            print(f"   → 审片版分得开，送模版会糊在一起。")
            print(f"     只有当这两类**在同一个画面里相邻**时才要改;隔着半个房间的可以放过。")
    return bad


def use_model_pass(S):
    """送给 Seedance 的那一版:平光灰模，无描边、无颜色、无文字。"""
    S.render.engine = 'BLENDER_EEVEE'
    S.render.use_stamp = False
    return S


def use_review_pass(S, note=""):
    """给人 confirm 的那一版。Workbench 不在 engine 枚举里但可以直接赋值(实测)。"""
    S.render.engine = 'BLENDER_WORKBENCH'
    sd = S.display.shading
    sd.light = 'STUDIO'; sd.studio_light = 'basic.sl'
    sd.color_type = 'OBJECT'                       # 用 box()/cyl() 里 role= 写进去的 object.color
    sd.show_object_outline = True
    sd.object_outline_color = (0.05, 0.05, 0.07)
    sd.show_cavity = True; sd.cavity_type = 'BOTH'
    sd.curvature_ridge_factor = 1.6
    sd.curvature_valley_factor = 1.6
    # 阴影只用来把体块从背景里托出来。0.35 在小房间可以，
    # 到了空旷的门厅/通道会投出一整块近黑的斜楔，看着像一堵墙(在一个空旷门厅上实测)。
    sd.show_shadows = True; sd.shadow_intensity = 0.22
    r = S.render
    r.use_stamp = True                             # 烧字只在审片版开 —— 送模版绝不能出现文字
    for a in ("use_stamp_date", "use_stamp_time", "use_stamp_render_time", "use_stamp_frame",
              "use_stamp_scene", "use_stamp_camera", "use_stamp_filename",
              "use_stamp_lens", "use_stamp_memory", "use_stamp_hostname",
              "use_stamp_sequencer_strip", "use_stamp_frame_range"):
        if hasattr(r, a):
            setattr(r, a, False)
    r.use_stamp_marker = bool(S.timeline_markers)  # 静帧没有 marker，开了会烧出「Marker <none>」
    r.use_stamp_note = bool(note); r.stamp_note_text = note
    r.stamp_font_size = 26
    r.stamp_foreground = (1, 1, 1, 1)
    r.stamp_background = (0, 0, 0, 0.55)
    return S


# ─────────────────────── 平面图 ───────────────────────

def render_plan(S, cams, out, *, size=12.0, height=14.0, center=(0.0, 3.0)):
    """俯视正交图:房间 + 每个机位的位置和视锥楔形。一张图看完整场调度，越轴一眼可见。
    视锥用临时面片画，渲完删掉，不污染场景。"""
    tmp = []
    m = mat("frustum", (0.95, 0.30, 0.20), 0.9)
    for name, (loc, look, lens) in cams.items():
        f = (Vector(look) - Vector(loc)); f.z = 0
        if f.length < 1e-4:
            continue
        f.normalize()
        half = math.atan(18.0 / lens)              # 半水平视角
        reach = 3.2
        L = Vector((f.x * math.cos(half) - f.y * math.sin(half),
                    f.x * math.sin(half) + f.y * math.cos(half), 0)) * reach
        R = Vector((f.x * math.cos(-half) - f.y * math.sin(-half),
                    f.x * math.sin(-half) + f.y * math.cos(-half), 0)) * reach
        base = Vector((loc[0], loc[1], 0.02))
        me = bpy.data.meshes.new(f"fr_{name}")
        me.from_pydata([base, base + L, base + R], [], [(0, 1, 2)])
        me.update()
        o = bpy.data.objects.new(f"fr_{name}", me); S.collection.objects.link(o)
        o.data.materials.append(m); _tint(o, "prop")
        tmp.append(o)
        tmp.append(cyl(f"cam_{name}", loc[0], loc[1], 0.08, 0.09, 0.16, m, role="prop"))

    c = bpy.data.cameras.new("PLAN"); c.type = 'ORTHO'; c.ortho_scale = size
    po = bpy.data.objects.new("PLAN", c); S.collection.objects.link(po)
    po.location = (center[0], center[1], height)
    po.rotation_euler = (0, 0, 0)                  # 正下方俯视
    # 从上往下看，天花板会把整个房间盖住 —— 渲平面图时先藏掉屋顶
    hidden = [o for o in bpy.data.objects
              if any(k in o.name for k in ("天花", "发光天棚", "吸顶灯", "轨道射灯"))]
    for o in hidden:
        o.hide_render = True

    prev_cam, prev_res = S.camera, S.render.resolution_y
    S.camera = po; S.render.resolution_y = S.render.resolution_x
    use_review_pass(S, note="平面图:红色楔形=机位视锥")
    S.render.filepath = out
    bpy.ops.render.render(write_still=True)
    S.camera = prev_cam; S.render.resolution_y = prev_res
    for o in hidden:
        o.hide_render = False
    for o in tmp + [po]:
        bpy.data.objects.remove(o, do_unlink=True)
    print(f"PLAN_DONE {out}  {len(cams)} 个机位")


# ─────────────────────── 渲染:静帧 / 全场序列 ───────────────────────
def render_stills(S, cams, out, figs=None, shots=None):
    """审片静帧。给了 figs+shots 就按时间轴逐镜渲 —— 每张只显示该镜用到的那组人。

    实测 事故:静帧不做可见性切换，三组人形同时出现在同一张图里
    (同一个角色的两个走位版本同时入画)，四个机位因此被判成废片，
    实际上几何是对的。**只要场景里有多于一组人物，静帧就必须按镜渲。**
    """
    if figs and shots:
        for sid, cname, _t0, _t1, key, _txt in shots:
            for k, objs in figs.items():
                for ob in objs:
                    ob.hide_render = (k != key)
            S.camera = bpy.data.objects[cname]
            S.render.filepath = f"{out}/{sid}_{cname}.png"
            bpy.ops.render.render(write_still=True)
    else:
        for n in cams:
            S.camera = bpy.data.objects[n]
            S.render.filepath = f"{out}/{n}.png"
            bpy.ops.render.render(write_still=True)
    print("STILLS_DONE")


def group(objs, name, at=(0.0, 0.0, 0.0)):
    """把一组物件挂到一个空物体上，整组当一个东西平移 —— 走位戏要用。
    道具(纸袋、手机)也挂到同一个手柄上，人走它就跟着走。"""
    e = bpy.data.objects.new(f"手柄_{name}", None)
    bpy.context.scene.collection.objects.link(e)
    e.location = at
    bpy.context.view_layer.update()
    for o in objs:
        o.parent = e
        o.matrix_parent_inverse = e.matrix_world.inverted()
    return e


def render_anim(S, shots, cams, out, figs, moves=None, walks=None):
    """shots: [(镜号, 机位名, 起秒, 止秒, 人物组key, 说明)]
    figs:  {人物组key: [物件...]}  每帧只显示当前镜头指定的那一组
    moves: {镜号: 米数 或 (dx,dy,dz)}  数字=沿视线推拉(正推近)、三元组=任意平移(横移用这个)
    walks: {镜号: (手柄空物体, (x0,y0), (x1,y1))}  这一镜里整组人从哪走到哪"""
    moves = moves or {}
    walks = walks or {}
    miss = sorted({s[1] for s in shots} - set(cams))
    if miss:
        raise SystemExit(f"时间轴用到但没定义的机位: {miss}")
    # 用 LINEAR:运镜和走位要匀速滑过去。布尔属性(hide_render)不吃这个设置，
    # 它天生就是 CONSTANT，所以人物切换仍然是硬切 —— 之前全局设成 CONSTANT，
    # 运镜其实是一下跳过去的，不是滑过去的。
    bpy.context.preferences.edit.keyframe_new_interpolation_type = 'LINEAR'
    fps = S.render.fps
    total = shots[-1][3] - shots[0][2]
    S.frame_start, S.frame_end = 1, int(round(total * fps))
    base = shots[0][2]
    for sid, camname, t0, t1, pos, _ in shots:
        f0, f1 = max(1, int(round((t0 - base) * fps))), int(round((t1 - base) * fps))
        src = bpy.data.objects[camname]
        o = src.copy(); o.data = src.data.copy(); o.name = f"{camname}#{sid}"
        S.collection.objects.link(o)
        d = moves.get(sid)
        if d:
            loc, look, _ = cams[camname]
            # 数字 = 沿视线推拉;三元组 = 任意平移(横移、升降)
            v = (Vector(look) - Vector(loc)).normalized() * d if isinstance(d, (int, float)) \
                else Vector(d)
            o.location = Vector(loc);     o.keyframe_insert("location", frame=f0)
            o.location = Vector(loc) + v; o.keyframe_insert("location", frame=f1)
        w = walks.get(sid)
        if w:
            handle, p0, p1 = w
            handle.location = (p0[0], p0[1], handle.location.z)
            handle.keyframe_insert("location", frame=f0)
            handle.location = (p1[0], p1[1], handle.location.z)
            handle.keyframe_insert("location", frame=f1)
        S.timeline_markers.new(f"m_{sid}", frame=f0).camera = o
        for key, objs in figs.items():
            for ob in objs:
                ob.hide_render = (key != pos)
                ob.keyframe_insert("hide_render", frame=f0)
                ob.keyframe_insert("hide_render", frame=max(f0, f1 - 1))
    S.render.filepath = out + "/f_"
    bpy.ops.render.render(animation=True)
    print(f"ANIM_DONE frames={S.frame_end} total={total:.1f}s shots={len(shots)}")


def load_timeline(path):
    sp = importlib.util.spec_from_file_location("tl", path)
    m = importlib.util.module_from_spec(sp); sp.loader.exec_module(m)
    return m
