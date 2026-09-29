"""可摆姿势的人体代理 —— 用 Blender 自带 Rigify 的人体骨架当骨,沿骨摆胶囊体当肉。

为什么不用圆柱堆:实测 实测,三个圆柱摞起来在白模里根本认不出是人，
用户看不清、四个人形也分不出谁是谁(在一个工位场景上实测过)。
为什么不下开源模型:Rigify 是 Blender 自带的，无需下载、无授权问题、headless 能跑，
而且骨架给的是解剖学正确的关节位置，摆姿势就是转骨头 —— 全程可脚本化。

做法:
  ① 生成 metarig(159 骨) → ② 缩放到目标身高 → ③ 在 POSE 模式转指定骨头
  ④ 读出姿势后每根骨的世界坐标 → ⑤ 沿骨建胶囊 → ⑥ 删掉骨架

用法:
  from human import mannequin
  objs = mannequin("LEAD", (x, y), yaw_deg, "sit_phone", P, height=1.62)
"""
import bpy, math, addon_utils
from mathutils import Vector, Matrix

try:                                    # headless 下 rigify 的偏好项注册会抛 KeyError，
    addon_utils.enable("rigify", default_set=False, persistent=False)   # 但操作符照样可用
except Exception:
    pass

# 每段骨对应的「肉」半径(米，按 1.70m 身高标定，会随 height 等比缩放)
LIMB = {
    "spine":       0.105, "spine.001": 0.115, "spine.002": 0.120, "spine.003": 0.115,
    "spine.004":   0.055, "spine.005": 0.050,
    "shoulder.L":  0.050, "shoulder.R": 0.050,
    "upper_arm.L": 0.048, "upper_arm.R": 0.048,
    "forearm.L":   0.040, "forearm.R":  0.040,
    "hand.L":      0.032, "hand.R":     0.032,
    "thigh.L":     0.075, "thigh.R":    0.075,
    "shin.L":      0.055, "shin.R":     0.055,
    "foot.L":      0.042, "foot.R":     0.042,
}
HEAD_BONE, HEAD_R = "spine.006", 0.098

# 姿势 = {骨名: (绕X, 绕Y, 绕Z) 角度}。只列需要偏离静止姿的骨头。
# metarig 静止姿是两臂侧张的 T 字 —— 每个姿势都要先把胳膊放到身侧，再叠具体动作。
# 实测(实测):手臂绕局部 Z 转上下、绕局部 X 转前后；左右两侧 Z 符号相反。
# X 为正 = 往身体前方伸(朝脸的方向)。修朝向公式时这里也跟着翻过一次符号。
ARMS_DOWN = {
    "upper_arm.L": (-0, 0, -62), "upper_arm.R": (-0, 0, 62),
    "forearm.L": (-0, 0, -16), "forearm.R": (-0, 0, 16),
}

def _p(**kw):
    """在「胳膊放下」的基础上叠加动作。"""
    d = dict(ARMS_DOWN); d.update(kw); return d

POSES = {
    "stand": _p(),
    # 坐:大腿抬平、小腿垂下、脚放平；上身略前倾
    "sit": _p(**{
        "thigh.L": (-88, 0, 0), "thigh.R": (-88, 0, 0),
        "shin.L": (85, 0, 0),   "shin.R": (85, 0, 0),
        "foot.L": (5, 0, 0),    "foot.R": (5, 0, 0),
        "spine": (6, 0, 0),
    }),
    # 坐着看手机:在 sit 基础上，两臂前抬、小臂内收到身前中线
    "sit_phone": _p(**{
        "thigh.L": (-88, 0, 0), "thigh.R": (-88, 0, 0),
        "shin.L": (85, 0, 0),   "shin.R": (85, 0, 0),
        "foot.L": (5, 0, 0),    "foot.R": (5, 0, 0),
        "spine": (10, 0, 0), "spine.003": (8, 0, 0), "spine.006": (14, 0, 0),  # 略低头看手机
        # 手臂参数是扫出来的:X 控制前伸(到桌沿)、Z 控制抬高。前倾越多手反而越低，
        # 所以 spine 只给 10 度;这套骨架手最高到 0.68，剩下的靠把椅面抬到 0.52 补。
        "upper_arm.L": (50, 0, -64), "upper_arm.R": (50, 0, 64),
        "forearm.L": (44, 0, -20),   "forearm.R": (44, 0, 20),
    }),
    # 侧身靠椅背看手机 —— 人在工位上刷手机本来就会转个身、往椅背一靠。
    # 这个姿态解开了「拍脸要从桌子那边来、躲桌子就只剩后脑」的死结:
    # 身体侧对桌子，手肘搭在桌上，从走道拍能同时拿到脸和手。
    "sit_side_phone": _p(**{
        "thigh.L": (-88, 0, 0), "thigh.R": (-88, 0, 0),
        "shin.L": (80, 0, 0),   "shin.R": (88, 0, 0),      # 两腿略错开，坐姿更松
        "foot.L": (5, 0, 0),    "foot.R": (5, 0, 0),
        "spine": (-6, 0, 0), "spine.003": (4, 0, 0),        # 往椅背靠，不前倾
        "spine.006": (16, 0, 0),                            # 只低头看手机
        # 扫出来的:手停在桌面上方约 17cm —— 小臂搭在桌沿、手里举着手机的自然高度
        "upper_arm.L": (38, 0, -44), "upper_arm.R": (54, 0, 44),
        "forearm.L": (52, 0, -26),   "forearm.R": (52, 0, 22),
    }),
    # 坐着敲键盘:两臂前伸、小臂略抬
    "sit_type": _p(**{
        "thigh.L": (-88, 0, 0), "thigh.R": (-88, 0, 0),
        "shin.L": (85, 0, 0),   "shin.R": (85, 0, 0),
        "foot.L": (5, 0, 0),    "foot.R": (5, 0, 0),
        "spine": (8, 0, 0),
        "upper_arm.L": (20, 0, -56), "upper_arm.R": (20, 0, 56),
        "forearm.L": (46, 0, -26),   "forearm.R": (46, 0, 26),
    }),
    # 斜靠床头半躺 —— 上身后仰约 40 度、膝盖弯起，手在身前
    "recline": _p(**{
        "spine": (-30, 0, 0), "spine.001": (-8, 0, 0), "spine.003": (6, 0, 0),
        "spine.006": (10, 0, 0),
        "thigh.L": (-72, 0, 6), "thigh.R": (-72, 0, -6),
        "shin.L": (62, 0, 0),   "shin.R": (58, 0, 0),
        "foot.L": (8, 0, 0),    "foot.R": (8, 0, 0),
        "upper_arm.L": (30, 0, -50), "upper_arm.R": (34, 0, 50),
        "forearm.L": (48, 0, -28),   "forearm.R": (52, 0, 26),
    }),
    # 斜靠床头 + 举着手机看
    "recline_phone": _p(**{
        "spine": (-26, 0, 0), "spine.001": (-6, 0, 0), "spine.003": (8, 0, 0),
        "spine.006": (18, 0, 0),                        # 低头看手机
        "thigh.L": (-72, 0, 6), "thigh.R": (-72, 0, -6),
        "shin.L": (62, 0, 0),   "shin.R": (58, 0, 0),
        "foot.L": (8, 0, 0),    "foot.R": (8, 0, 0),
        "upper_arm.L": (40, 0, -46), "upper_arm.R": (44, 0, 46),
        "forearm.L": (62, 0, -30),   "forearm.R": (66, 0, 28),
    }),
    # 站着抱东西在怀里
    "stand_hold": _p(**{
        "upper_arm.L": (30, 0, -56), "upper_arm.R": (30, 0, 56),
        "forearm.L": (76, 0, -40),   "forearm.R": (76, 0, 40),
    }),
    # 站着，一只手向前伸(指屏幕/按键)
    "stand_reach_r": _p(**{
        "upper_arm.R": (56, 0, 34), "forearm.R": (18, 0, 14),
    }),
    # 左手伸出去按门禁 —— 右手全程拎纸袋(HAND-R 不许换手)，所以按键只能用左手
    "stand_reach_l": _p(**{
        "upper_arm.L": (58, 0, -30), "forearm.L": (16, 0, -12),
    }),
    # 走路。腿 X 负 = 往前迈(和 sit 的 thigh -88 同向)，shin X 正 = 屈膝。
    # 手臂和腿反向摆，白模里一眼就能看出「这个人在走」而不是「站着不动被推着平移」。
    "walk_r": _p(**{                                   # 右脚在前
        "thigh.R": (-20, 0, 0), "shin.R": (6, 0, 0),  "foot.R": (4, 0, 0),
        "thigh.L": (14, 0, 0),  "shin.L": (26, 0, 0), "foot.L": (16, 0, 0),
        "upper_arm.L": (22, 0, -58), "upper_arm.R": (-16, 0, 66),
        "forearm.L": (26, 0, -18),   "forearm.R": (10, 0, 14),
        "spine": (3, 0, 0),
    }),
    "walk_l": _p(**{                                   # 左脚在前
        "thigh.L": (-20, 0, 0), "shin.L": (6, 0, 0),  "foot.L": (4, 0, 0),
        "thigh.R": (14, 0, 0),  "shin.R": (26, 0, 0), "foot.R": (16, 0, 0),
        "upper_arm.R": (22, 0, 58), "upper_arm.L": (-16, 0, -66),
        "forearm.R": (26, 0, 18),   "forearm.L": (10, 0, -14),
        "spine": (3, 0, 0),
    }),
    # 走路 + 右手拎袋:右臂基本垂直放下、略往后，袋子挂在手下面
    "walk_bag_r": _p(**{
        "thigh.R": (-18, 0, 0), "shin.R": (6, 0, 0),  "foot.R": (4, 0, 0),
        "thigh.L": (13, 0, 0),  "shin.L": (24, 0, 0), "foot.L": (15, 0, 0),
        "upper_arm.L": (24, 0, -56), "forearm.L": (28, 0, -18),
        "upper_arm.R": (-10, 0, 74), "forearm.R": (-2, 0, 6),   # 提袋的胳膊被袋子坠直
        "spine": (2, 0, 0),
    }),
    # 右手拎袋 + 左手抬起去刷门禁 —— 一边走一边够，不停步(03-05B 是短跟不切镜)
    "walk_bag_reach_l": _p(**{
        "thigh.R": (-14, 0, 0), "shin.R": (6, 0, 0),  "foot.R": (4, 0, 0),
        "thigh.L": (10, 0, 0),  "shin.L": (20, 0, 0), "foot.L": (13, 0, 0),
        "upper_arm.L": (62, 0, -26), "forearm.L": (14, 0, -10),
        "upper_arm.R": (-10, 0, 74), "forearm.R": (-2, 0, 6),
        "spine": (2, 0, 0),
    }),
}


def hand(tag, side="R"):
    """读某只手的实际世界坐标 —— 道具跟着手走，别硬填坐标(铁律 6)。"""
    import bpy
    o = bpy.data.objects.get(f"{tag}_hand.{side}_j1") or bpy.data.objects.get(f"{tag}_hand.{side}")
    return None if o is None else o.matrix_world.translation.copy()


def _capsule(name, a, b, r, mat, role="lead"):
    """在 a、b 两点之间建一根胶囊(圆柱 + 两端球)。"""
    v = Vector(b) - Vector(a)
    L = v.length
    if L < 1e-4:
        return []
    mid = (Vector(a) + Vector(b)) / 2
    bpy.ops.mesh.primitive_cylinder_add(radius=r, depth=L, location=mid, vertices=12)
    cy = bpy.context.object; cy.name = name
    cy.rotation_mode = 'QUATERNION'
    cy.rotation_quaternion = v.to_track_quat('Z', 'Y')
    out = [cy]
    for i, p in enumerate((a, b)):
        bpy.ops.mesh.primitive_uv_sphere_add(radius=r, location=p, segments=12, ring_count=8)
        s = bpy.context.object; s.name = f"{name}_j{i}"
        out.append(s)
    import rig as _rig
    for o in out:
        o.data.materials.append(mat)
        _rig._tint(o, role)
    return out


def mannequin(tag, xy, yaw_deg, pose, P, *, height=1.68, lead=True, seat_z=None, collection=None):
    """在 (x, y) 建一个摆好姿势的人体代理，yaw_deg 是朝向(0 = 面朝 +X，逆时针为正)。
    seat_z 给了就是坐姿:摆完姿势后按「大腿根应该落在椅面上」把整个人垂直放下去。
    只转大腿骨是不够的 —— 骨架原点还在地面，骻部会停在站立高度，人就浮在半空
    (实测 实测,坐着的人悬在桌面高度)。
    返回建出来的所有物件，交给 rig.render_anim 做按镜可见性切换。"""
    mat = P["BODY"] if lead else P["EXTRA"]
    role = "lead" if lead else "extra"
    prev = set(bpy.data.objects)

    bpy.ops.object.armature_human_metarig_add()
    arm = bpy.context.object
    s = height / 1.98                      # metarig 默认头顶约 1.98m
    arm.scale = (s, s, s)
    arm.location = (xy[0], xy[1], 0.0)
    # metarig 静止时面朝 -Y(即 -90°)，要面朝 yaw_deg 就得转 yaw_deg-(-90)=yaw_deg+90。
    # 之前写成 -90，人整个转反了 180°:她背对桌子坐着，前倾反而把头往后送。
    arm.rotation_euler = (0, 0, math.radians(yaw_deg + 90))

    bpy.ops.object.mode_set(mode='POSE')
    for bname, rot in POSES.get(pose, {}).items():
        pb = arm.pose.bones.get(bname)
        if not pb:
            continue
        pb.rotation_mode = 'XYZ'
        pb.rotation_euler = tuple(math.radians(a) for a in rot)
    bpy.ops.object.mode_set(mode='OBJECT')
    bpy.context.view_layer.update()

    if seat_z is not None:                 # 坐姿:把大腿根对到椅面高度
        hip = arm.pose.bones.get("thigh.L")
        if hip:
            cur = (arm.matrix_world @ hip.head).z
            arm.location.z += seat_z - cur
            bpy.context.view_layer.update()

    M = arm.matrix_world
    objs = []
    for bname, r in LIMB.items():
        pb = arm.pose.bones.get(bname)
        if not pb:
            continue
        objs += _capsule(f"{tag}_{bname}", M @ pb.head, M @ pb.tail, r * s, mat, role)
    hb = arm.pose.bones.get(HEAD_BONE)
    if hb:
        c = M @ ((hb.head + hb.tail) / 2)
        bpy.ops.mesh.primitive_uv_sphere_add(radius=HEAD_R * s, location=c, segments=16, ring_count=10)
        h = bpy.context.object; h.name = f"{tag}_头"
        h.scale = (0.92, 1.05, 1.12)
        h.data.materials.append(mat)
        import rig as _rig; _rig._tint(h, role)
        objs.append(h)
        # 朝向楔子:鼻子 —— 光有身体还是看不出面朝哪(实测教训:没有鼻锥，模型直接让人物转脸对镜头)
        fwd = Vector((math.cos(math.radians(yaw_deg)), math.sin(math.radians(yaw_deg)), 0))
        bpy.ops.mesh.primitive_cone_add(radius1=0.035 * s, depth=0.09 * s,
                                        location=c + fwd * (HEAD_R * s * 0.95), vertices=8)
        n = bpy.context.object; n.name = f"{tag}_鼻"
        n.rotation_mode = 'QUATERNION'
        n.rotation_quaternion = fwd.to_track_quat('Z', 'Y')
        n.data.materials.append(mat)
        _rig._tint(n, role)
        objs.append(n)

    bpy.data.objects.remove(arm, do_unlink=True)      # 骨架只是脚手架，建完就拆
    return [o for o in bpy.data.objects if o in set(objs) or o not in prev and o in objs] or objs
