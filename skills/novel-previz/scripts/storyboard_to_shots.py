#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""storyboard_to_shots.py —— novel-storyboard 分镜 → greybox-harness 白模场景 的确定性适配器

用法:
  python3 storyboard_to_shots.py analyze     --storyboard S.json --out DIR [--ep 1] [--segment E01-01]
  python3 storyboard_to_shots.py export-grid --storyboard S.json --out DIR [--frames DIR] [--segment E01-01]
  python3 storyboard_to_shots.py init-config --storyboard S.json --script J.json [--art A.json] --out DIR [--force]
  python3 storyboard_to_shots.py export      --storyboard S.json --script J.json --config C.json
                                              [--art A.json] [--outline O.json] --out DIR
                                              [--ep 1] [--segment E01-01] [--blockout DIR]
  python3 storyboard_to_shots.py validate    --storyboard S.json --segment E01-01
                                              [--scene-py FILE | --out DIR]
  python3 storyboard_to_shots.py selftest

原则:
  · 机械转换全部交给程序:段号/切序/起止秒/镜号/机位标识/人物道具关联,零 agent。
  · 空间事实(房间/站位/机位)来自可复用的场景配置;配置缺项只出骨架和缺项清单,绝不编造。
  · 秒是唯一真相,帧按 greybox-harness rig.render_anim 的公式逐字复刻换算(int(round(t*24)))。
  · 生成物可被 harness 的 verify_cuts / slice_shots / check_prompt 原样解析。

退出码: 0 全过 / 1 对账门违规 / 2 配置或宫格素材缺项(完整段照常生成) / 3 输入、模板或用法错误
"""
import argparse
import ast
import copy
import json
import math
import os
import re
import sys
import tempfile

# ─────────────────────────────── 常量 ───────────────────────────────

FPS = 24

SIZE_ZH = {
    "extreme-wide": "大远景",
    "wide": "全景",
    "medium": "中景",
    "close": "特写",
    "extreme-close": "大特写",
}

# novel-storyboard 的 H3 官方运镜词表(20 个),逐字对齐 scripts/novel-storyboard.mjs 的 CAMERA_MOVES
CAMERA_ENUM = [
    "Static Shot", "Push In", "Pull Out", "Zoom In", "Zoom Out",
    "Pan Left", "Pan Right", "Truck Left", "Truck Right",
    "Tilt Up", "Tilt Down", "Pedestal Up", "Pedestal Down",
    "Arc Shot", "Tracking Shot", "Shake Slightly", "Shake Strongly",
    "POV", "Roll Clockwise", "Roll Counterclockwise",
]

# 运镜三档:A=白模直接可表达;B=可近似(config.approxZoom 打开才启用,永远同时进降级清单);
#           C=白模表达不了 → 静态渲染 + 降级清单。挪一行即换档。
MOVE_TABLE = {
    "Static Shot":      ("A", None),
    "Push In":          ("A", "push"),
    "Pull Out":         ("A", "pull"),
    "Truck Left":       ("A", "truck_l"),
    "Truck Right":      ("A", "truck_r"),
    "Pedestal Up":      ("A", "ped_up"),
    "Pedestal Down":    ("A", "ped_down"),
    "Zoom In":          ("B", "zoom_in"),
    "Zoom Out":         ("B", "zoom_out"),
    "POV":              ("B", "pov"),
    "Pan Left":         ("C", None),
    "Pan Right":        ("C", None),
    "Tilt Up":          ("C", None),
    "Tilt Down":        ("C", None),
    "Arc Shot":         ("C", None),
    "Tracking Shot":    ("C", None),
    "Shake Slightly":   ("C", None),
    "Shake Strongly":   ("C", None),
    "Roll Clockwise":   ("C", None),
    "Roll Counterclockwise": ("C", None),
}

# blockout/human.py POSES 的镜像。姿态名错了 harness 会静默变 T-pose,所以这里必须拦。
POSES = [
    "stand", "sit", "sit_phone", "sit_side_phone", "sit_type",
    "recline", "recline_phone", "stand_hold", "stand_reach_r", "stand_reach_l",
    "walk_r", "walk_l", "walk_bag_r", "walk_bag_reach_l",
]
SIT_POSES = {"sit", "sit_phone", "sit_side_phone", "sit_type"}

PALETTE_KEYS = ["WALL", "WOOD", "FLOOR", "DARK", "RELIEF", "SCRN", "GLASS", "BODY", "EXTRA", "PROP"]
VALID_ROLES = ["shell", "furniture", "screen", "prop"]
FURNITURE_KINDS = ["desk", "chair", "monitor", "window", "box", "cyl"]

# 内置机位预设:dist=与主体的距离(m),eye=机高(m),lookZ=注视高度(m)。
# eye/lookZ 按主体身高 ÷1.68 缩放,1.5m 的演员拍特写不会框到肩膀。
BUILTIN_PRESETS = {
    "extreme-wide":   {"dist": 6.5, "eye": 1.70, "lookZ": 1.00},
    "wide":           {"dist": 4.5, "eye": 1.60, "lookZ": 1.10},
    "medium":         {"dist": 2.4, "eye": 1.55, "lookZ": 1.25},
    "close":          {"dist": 1.2, "eye": 1.55, "lookZ": 1.48},
    "extreme-close":  {"dist": 0.6, "eye": 1.50, "lookZ": 1.52},
}

DEFAULT_PARAMS = {"maxSegmentSeconds": 15, "minCutSeconds": 2, "maxCutSeconds": 5}

# 与 greybox-harness/tools/verify_cuts.py 的 shots_from_scene 逐字同款(selftest 里有同步检查)。
RE_SHOTS_STR = r"^SHOTS\s*=\s*\[(.*?)^\]"
RE_SHOTS = re.compile(RE_SHOTS_STR, re.S | re.M)

RE_LENS = re.compile(r"(\d+(?:\.\d+)?)\s*mm", re.I)

HERE = os.path.dirname(os.path.abspath(__file__))


# ─────────────────────────────── 小工具 ───────────────────────────────

def fnum(v):
    """数字 → 稳定的 Python 字面量。int 保持 int,浮点 round 到 3 位。"""
    if isinstance(v, bool):
        raise ValueError("布尔不是数字")
    if isinstance(v, int):
        return str(v)
    return repr(round(float(v), 3))


def pystr(s):
    """字符串 → repr(),ast.literal_eval 安全,CJK 保持原样。"""
    return repr(str(s))


def tup(vals):
    values = [fnum(v) for v in vals]
    return "(" + ", ".join(values) + ("," if len(values) == 1 else "") + ")"


def load_json(path, label):
    import io
    try:
        with io.open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except OSError as e:
        fail(3, f"读不到{label}: {path} ({e})")
    except json.JSONDecodeError as e:
        fail(3, f"{label}不是合法 JSON: {path} (第{e.lineno}行 {e.msg})")


def sha12(path):
    import hashlib
    import io
    h = hashlib.sha256()
    with io.open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()[:12]


def fail(code, msg):
    print(f"✗ {msg}", file=sys.stderr)
    sys.exit(code)


def write_text(path, text):
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    pending = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='\n',
                                         dir=parent, prefix='.previz-', suffix='.tmp', delete=False) as f:
            pending = f.name
            f.write(text)
        os.replace(pending, path)
    finally:
        if pending and os.path.exists(pending):
            os.unlink(pending)


def output_path(out_dir, *parts):
    root = os.path.realpath(out_dir)
    target = os.path.realpath(os.path.join(root, *parts))
    if os.path.commonpath([root, target]) != root or target == root:
        fail(3, f'输出路径越界: {target}')
    return target


def invalidate_scene(out_dir, segment):
    scene = output_path(out_dir, segment, 'scene.py')
    stale = output_path(out_dir, segment, 'scene.py.stale')
    if os.path.isfile(scene):
        os.replace(scene, stale)  # 保留最近一次版本，但不再暴露可执行 scene.py。


def publish_plans(plans, gates, out_dir):
    failed = [g['id'] for g in gates if not g['ok']]
    for plan in plans:
        sid = plan['seg_id']
        if failed:
            plan['complete'] = False
            plan['missing'].append({'scene': plan['scene_id'], 'item': sid, 'field': 'validation',
                                    'reason': '本批次对账门违规，未发布可执行文件: ' + ', '.join(failed)})
        if plan['complete']:
            plan['file'] = output_path(out_dir, sid, 'scene.py')
            write_text(plan['file'], plan['text'])
            todo = output_path(out_dir, sid, 'scene.py.todo')
            if os.path.isfile(todo):
                os.unlink(todo)
        else:
            plan['file'] = output_path(out_dir, sid, 'scene.py.todo')
            lines = [f'{sid} 未生成可执行场景。补齐配置或修正违规后重新导出。', '']
            lines.extend(f"- {m['item']}.{m['field']}  {m['reason']}" for m in plan['missing'])
            write_text(plan['file'], '\n'.join(lines) + '\n')


def cumulative(seconds_list):
    """切镜秒数 → 每镜 (t0, t1)。生成与对账共用这一个函数,永不各算各的。"""
    out = []
    t = 0.0
    for s in seconds_list:
        out.append((t, t + float(s)))
        t += float(s)
    return out


def parse_lens(text):
    m = RE_LENS.search(str(text or ""))
    if not m:
        return None
    v = float(m.group(1))
    return int(v) if v == int(v) else round(v, 1)


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


# ─────────────────────────────── 解析 ───────────────────────────────

def scene_of_segment(script_ep, seg, seg_label):
    idx = seg.get("sceneIndex")
    scenes = script_ep.get("scenes") or []
    if not isinstance(idx, int) or idx < 1 or idx > len(scenes):
        return None
    return scenes[idx - 1].get("sceneId")


def preset_for(cfg, size):
    over = (cfg.get("camPresets") or {}).get(size) or {}
    base = BUILTIN_PRESETS[size]
    return {k: over.get(k, base[k]) for k in ("dist", "eye", "lookZ")}


def anchor_or_none(scene_cfg, cid):
    a = (scene_cfg.get("anchors") or {}).get(cid)
    if not a or a.get("pos") is None or a.get("face") is None:
        return None
    return a


def numeric_vector(value, size, *, positive=False):
    return (isinstance(value, (list, tuple)) and len(value) == size
            and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                    and math.isfinite(v) and (not positive or v > 0) for v in value))


def prop_missing_fields(p):
    if not isinstance(p, dict):
        return ['配置']
    missing = []
    if p.get('hand') is None and p.get('pos') is None:
        missing.append('hand|pos')
    if p.get('dims') is None:
        missing.append('dims')
    if p.get('hand') is not None and p.get('fallback') is None:
        missing.append('fallback')
    return missing


def prop_errors(p):
    if not isinstance(p, dict):
        return [] if p is None else ['配置必须是对象或 null']
    problems = []
    hand, pos = p.get('hand'), p.get('pos')
    shape = p.get('shape') or 'box'
    if hand is not None and pos is not None:
        problems.append('必须且只能给 hand 或 pos 之一')
    if hand is not None:
        if not isinstance(hand, str) or not re.fullmatch(r'[^:]+:[RL]', hand):
            problems.append('hand 必须是角色编号:R 或角色编号:L')
        if p.get('fallback') is not None and not numeric_vector(p['fallback'], 3):
            problems.append('fallback 必须是三个有限数值')
    if pos is not None and not numeric_vector(pos, 2):
        problems.append('pos 必须是两个有限数值')
    if shape not in ('box', 'cyl'):
        problems.append('shape 必须是 box 或 cyl')
    if p.get('dims') is not None and not numeric_vector(p['dims'], 2 if shape == 'cyl' else 3, positive=True):
        problems.append('dims 必须与 shape 对应且全部为正数')
    if p.get('offset') is not None and not numeric_vector(p['offset'], 3):
        problems.append('offset 必须是三个有限数值')
    z = p.get('z')
    if pos is not None and z is not None and z != 'floor' and not numeric_vector([z], 1):
        problems.append('z 必须是 floor 或有限数值')
    if p.get('mat') is not None and p['mat'] not in PALETTE_KEYS:
        problems.append('mat 不在调色板')
    if p.get('role') is not None and p['role'] not in VALID_ROLES:
        problems.append('role 无效')
    return problems


def prop_ready(p):
    return not prop_missing_fields(p) and not prop_errors(p)


def prop_center_z(p):
    z = p.get('z') if p.get('z') is not None else 'floor'
    dims = p.get("dims") or [0, 0, 0]
    if z == "floor":
        return (dims[2] / 2.0) if (p.get('shape') or 'box') == "box" else (dims[1] / 2.0)
    return float(z)


def resolve_move(cam_move, seconds, loc, look, approx_zoom):
    """运镜枚举 → (MOVES 值或 None, 降级条目或 None)。loc/look 为生成期元组(挂手道具用 fallback 估计)。"""
    if cam_move not in MOVE_TABLE:
        return None, None
    tier, act = MOVE_TABLE[cam_move]
    if tier == "A":
        if act == "push":
            return clamp(0.12 * seconds, 0.25, 0.8), None
        if act == "pull":
            return -clamp(0.12 * seconds, 0.25, 0.8), None
        if act in ("truck_l", "truck_r"):
            dx, dy = look[0] - loc[0], look[1] - loc[1]
            n = math.hypot(dx, dy) or 1.0
            fx, fy = dx / n, dy / n
            rx, ry = fy, -fx          # 画面右 = 前向 × 世界上轴
            s = 0.5 if act == "truck_r" else -0.5
            return (round(rx * s, 3), round(ry * s, 3), 0.0), None
        if act == "ped_up":
            return (0.0, 0.0, 0.3), None
        if act == "ped_down":
            return (0.0, 0.0, -0.3), None
        return None, None              # Static Shot
    if tier == "B":
        if not approx_zoom:
            return None, {"action": "static", "camera": cam_move}
        if act in ("zoom_in", "zoom_out"):
            mag = clamp(0.12 * seconds, 0.25, 0.8)
            v = mag if act == "zoom_in" else -mag
            return v, {"action": "zoom", "camera": cam_move}
        if act == "pov":
            return None, {"action": "pov", "camera": cam_move}
    return None, {"action": "static", "camera": cam_move}


def unverified_content(seg):
    warnings = []
    if seg.get('blocking'):
        warnings.append({'segment': seg.get('id'), 'cut': None, 'fields': ['blocking'],
                         'reason': '段级站位描述未解析；人物位置与朝向仅来自场景配置。'})
    ignored = ('cameraPosition', 'composition', 'eyeline', 'focus', 'stability',
               'frame', 'shot', 'note', 'lighting')
    for index, cut in enumerate(seg.get('cuts') or [], 1):
        fields = [field for field in ignored if cut.get(field)]
        if fields:
            warnings.append({'segment': seg.get('id'), 'cut': f"{seg.get('id')}-f{index}",
                             'fields': fields,
                             'reason': '未按这些描述还原或验证具体机位、构图、表演、道具状态及动作承接；仅生成预设机位和静态人物。'})
    return warnings


def resolve_segment(seg, script_ep, cfg, names):
    """一段 → 生成计划。names: {charId: 显示名, sceneId: 场景名, propId: 显示名}。"""
    seg_id = seg.get("id", "?")
    scene_id = scene_of_segment(script_ep, seg, seg_id)
    plan = {
        "seg": seg, "seg_id": seg_id, "scene_id": scene_id,
        "scene_name": names["scenes"].get(scene_id, ""),
        "complete": False, "missing": [], "warnings": [],
        "degradations": [], "lens_fallback": [],
        "shots": [], "cams": [], "figs": [], "moves": {},
        "subj": {}, "subj_chars": {}, "ignore_by_sid": {},
        "geo_lines": [], "fig_lines": [], "prop_lines": [],
        "cam_lines": [], "shots_lines": [], "marks": [], "probe_tags": [],
        "ignore_names": [], "text": None, "file": None,
    }
    plan['warnings'] = unverified_content(seg)
    cuts = seg.get("cuts") or []
    times = cumulative([c.get("seconds", 0) for c in cuts])

    scene_cfg = (cfg.get("scenes") or {}).get(scene_id) if scene_id else None
    if scene_cfg is None:
        plan["missing"].append({"scene": scene_id, "item": f"scenes.{scene_id}",
                                "field": "-", "reason": "场景配置缺失(先跑 init-config)"})
        return plan

    default_lens = cfg.get("defaultLens")
    approx = bool(cfg.get("approxZoom"))

    # 空镜需要 sceneAnchor
    has_empty = any((not c.get("characters")) and (not c.get("props")) for c in cuts)
    sa = scene_cfg.get("sceneAnchor")
    if has_empty and (not sa or sa.get("pos") is None or sa.get("face") is None):
        plan["missing"].append({"scene": scene_id, "item": f"scenes.{scene_id}.sceneAnchor",
                                "field": "pos/face", "reason": "本段含空镜,需要场景锚点"})

    # 场景壳
    geo = build_geometry_lines(scene_id, scene_cfg)
    if geo is None:
        plan["missing"].append({"scene": scene_id, "item": f"scenes.{scene_id}.room",
                                "field": "room/floor",
                                "reason": "室内填 room;外景改 openAir:true 并填 floor"})
        geo = []
    plan["geo_lines"] = geo

    anchors = scene_cfg.get("anchors") or {}
    props = scene_cfg.get("props") or {}

    # ── 逐切解析 ──
    for k, cut in enumerate(cuts, 1):
        sid = f"{seg_id}-f{k}"
        chars = cut.get("characters") or []
        pids = cut.get("props") or []
        size = cut.get("size")
        fig_key = "_".join(sorted(chars)) if chars else "_"
        cam_name = f"S{k}_{SIZE_ZH.get(size, '?')}"

        # 所有被引用道具都检查，不能只检查道具作为主体的镜头。
        props_ok = True
        for pid in pids:
            prop = props.get(pid)
            missing_fields = prop_missing_fields(prop)
            if missing_fields:
                plan['missing'].append({'scene': scene_id, 'item': f'scenes.{scene_id}.props.{pid}',
                                        'field': '/'.join(missing_fields),
                                        'reason': f'{sid} 引用的道具配置未填完整'})
            if not prop_ready(prop):
                props_ok = False
        if not props_ok:
            continue

        # 主体
        subject = None
        if chars:
            pts = []
            ok_chars = True
            for c in chars:
                a = anchor_or_none(scene_cfg, c)
                if a is None:
                    plan["missing"].append({"scene": scene_id, "item": f"scenes.{scene_id}.anchors.{c}",
                                            "field": "pos/face", "reason": f"{names['chars'].get(c, c)} 的站位未填"})
                    ok_chars = False
                else:
                    pts.append((a["pos"][0], a["pos"][1]))
            if not ok_chars:
                continue
            primary = chars[0]
            pa = anchors[primary]
            height = pa.get("height") if pa.get("height") is not None else 1.68
            base = (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
            az = math.radians(pa["face"])
            span = 0.0
            if len(pts) >= 2:
                span = max(math.hypot(a[0] - b[0], a[1] - b[1])
                           for i, a in enumerate(pts) for b in pts[i + 1:])
            subject = {"kind": "char", "primary": primary, "height": height,
                       "base": base, "az": az, "span": span}
        elif pids:
            pid = pids[0]
            p = props.get(pid)
            if p is None:
                plan["missing"].append({"scene": scene_id, "item": f"scenes.{scene_id}.props.{pid}",
                                        "field": "-", "reason": "道具不在配置里"})
                continue
            if p.get("hand"):
                if p.get("fallback") is None:
                    plan["missing"].append({"scene": scene_id, "item": f"scenes.{scene_id}.props.{pid}",
                                            "field": "fallback", "reason": "挂手道具必须有 fallback 坐标"})
                    continue
                owner, _, side = str(p["hand"]).partition(":")
                oa = anchor_or_none(scene_cfg, owner)
                az = math.radians(oa["face"]) if oa else 0.0
                off = p.get("offset") or [0, 0, 0]
                fb = p["fallback"]
                est = (fb[0] + off[0], fb[1] + off[1], fb[2] + off[2])
                subject = {"kind": "handprop", "pid": pid, "var": f"{pid}_POS", "side": side or "R",
                           "owner": owner, "az": az, "base": est, "span": 0.0, "est": est}
            elif p.get("pos") is not None:
                z = prop_center_z(p)
                base = (p["pos"][0], p["pos"][1], z)
                sa2 = scene_cfg.get("sceneAnchor") or {}
                sap = sa2.get("pos")
                if sap:
                    dx, dy = sap[0] - base[0], sap[1] - base[1]
                    az = math.atan2(dy, dx) if math.hypot(dx, dy) >= 0.1 else 0.0
                else:
                    az = 0.0
                subject = {"kind": "posprop", "pid": pid, "az": az, "base": base, "span": 0.0}
            else:
                plan["missing"].append({"scene": scene_id, "item": f"scenes.{scene_id}.props.{pid}",
                                        "field": "hand|pos", "reason": "道具未指定挂手或坐标"})
                continue
        else:
            if sa and sa.get("pos") is not None and sa.get("face") is not None:
                base = (sa["pos"][0], sa["pos"][1], sa.get("lookZ", 1.2))
                subject = {"kind": "empty", "az": math.radians(sa.get("face", 0)),
                           "base": base, "span": 0.0}
            else:
                continue                     # 空镜缺锚点已在上面记过 missing

        # 机位
        preset = preset_for(cfg, size) if size in BUILTIN_PRESETS else None
        if preset is None:
            continue                         # cam-enum / size 问题时门会拦
        dist_eff = preset["dist"] + max(0.0, subject["span"] - 0.8) * 0.9
        if subject["kind"] == "char":
            hs = subject["height"] / 1.68
            loc = (subject["base"][0] + dist_eff * math.cos(subject["az"]),
                   subject["base"][1] + dist_eff * math.sin(subject["az"]),
                   preset["eye"] * hs)
            look = (subject["base"][0], subject["base"][1], preset["lookZ"] * hs)
        elif subject["kind"] == "handprop":
            loc = (subject["est"][0] + dist_eff * math.cos(subject["az"]),
                   subject["est"][1] + dist_eff * math.sin(subject["az"]),
                   subject["est"][2] + 0.08)
            look = subject["est"]
        else:
            b = subject["base"]
            loc = (b[0] + dist_eff * math.cos(subject["az"]),
                   b[1] + dist_eff * math.sin(subject["az"]), preset["eye"])
            look = (b[0], b[1], preset["lookZ"])

        lens = parse_lens(cut.get("lens"))
        lens_src = "lens"
        if lens is None:
            lens = default_lens
            lens_src = "default"
            if lens is None:
                plan["missing"].append({"scene": scene_id, "item": "defaultLens",
                                        "field": "-", "reason": f"{sid} 的 lens 解析不出焦距且无兜底"})
                continue
            plan["lens_fallback"].append(sid)

        # POV(B 档)覆盖机位几何
        cam_move = cut.get("camera")
        tier, act = MOVE_TABLE.get(cam_move, (None, None))
        pov_used = False
        if act == "pov" and approx and subject["kind"] == "char":
            pov_used = True
            hs = subject["height"] / 1.68
            px, py = subject["base"]
            loc = (px + 0.05 * math.cos(subject["az"]), py + 0.05 * math.sin(subject["az"]),
                   0.93 * subject["height"])
            look = (px + 2.0 * math.cos(subject["az"]), py + 2.0 * math.sin(subject["az"]),
                    0.93 * subject["height"])

        move_val, degr = resolve_move(cam_move, cut.get("seconds", 0), loc, look, approx)
        if pov_used:
            move_val, degr = None, {"action": "pov", "camera": cam_move}
        elif degr is not None and degr["action"] == "pov":
            # POV 近似只对人物主体成立;道具/空镜 POV 老老实实降级为静态
            degr = {"action": "static", "camera": cam_move}
        if move_val is not None:
            plan["moves"][sid] = move_val
        if degr is not None:
            plan["degradations"].append({"segment": seg_id, "cut": sid, **degr})

        note = str(cut.get("shot") or cut.get("frame") or "")
        if degr is not None:
            tag = "运镜近似" if degr["action"] in ("zoom", "pov") else "运镜降级"
            approx_txt = {"zoom": "推近", "pov": "眼点静态"}[degr["action"]] if degr["action"] != "static" else "静态"
            note = f"{note}［{tag}：{cam_move}→{approx_txt}］"

        t0, t1 = times[k - 1]
        plan["shots"].append((sid, cam_name, t0, t1, fig_key, note))
        plan["cams"].append({
            "name": cam_name, "sid": sid, "loc": loc, "look": look, "lens": lens,
            "subject": subject, "dist_eff": dist_eff, "size": size,
            "lens_src": lens_src, "runtime": subject["kind"] == "handprop",
        })
        # SUBJ(遮挡扫描的主体点)与主体标记(自己的躯干不算遮挡)
        if subject["kind"] == "char":
            plan["subj"][sid] = (subject["base"][0], subject["base"][1],
                                 round(0.84 * subject["height"], 3))
            plan["subj_chars"][sid] = (subject["primary"], fig_key)
        elif subject["kind"] == "handprop":
            plan["subj"][sid] = f"{subject['pid']}_POS"      # 运行期变量
            plan["subj_chars"][sid] = (str(subject.get("owner") or ""), fig_key) \
                if subject.get("owner") else None
        else:
            plan["subj"][sid] = subject["base"]
            plan["subj_chars"][sid] = None

    # ── FIG / 道具 / MARKS / 遮挡忽略 ──
    build_figs(plan, scene_cfg, names)
    build_props(plan, scene_cfg, names)
    build_marks(plan, scene_cfg, names)
    build_ignore(plan)

    plan["complete"] = (not plan["missing"]) and len(plan["shots"]) == len(cuts)
    return plan


def build_geometry_lines(scene_id, scene_cfg):
    """场景壳 → rig 调用行。返回 None 表示 room/floor 缺。"""
    lines = [f"# ── 场景几何 {scene_id} 开始 ──"]
    open_air = bool(scene_cfg.get("openAir"))
    if not open_air:
        r = scene_cfg.get("room")
        if not r:
            return None
        panel = r.get("panel", True)
        lines.append(f"rig.room(S, P, {fnum(r['x0'])}, {fnum(r['x1'])}, "
                     f"{fnum(r['y0'])}, {fnum(r['y1'])}, {fnum(r['zc'])}, panel={bool(panel)})")
    else:
        fl = scene_cfg.get("floor")
        if not fl:
            return None
        lines.append(f"box({pystr('地面_' + scene_id)}, {fnum(fl['cx'])}, {fnum(fl['cy'])}, -0.05, "
                     f"{fnum(fl['sx'])}, {fnum(fl['sy'])}, 0.1, P[{pystr(fl.get('mat', 'FLOOR'))}], role=\"shell\")")
    for sp in scene_cfg.get("setPieces") or []:
        emit_piece(lines, sp)
    for fu in scene_cfg.get("furniture") or []:
        emit_furniture(lines, fu)
    lines.append("# ── 场景几何 结束 ──")
    return lines


def emit_piece(lines, sp):
    name = sp.get("name") or sp.get("tag") or "体块"
    common = f"P[{pystr(sp.get('mat', 'WALL'))}]"
    if sp.get("kind") == "cyl":
        lines.append(f"cyl({pystr(name)}, {fnum(sp['cx'])}, {fnum(sp['cy'])}, {fnum(sp['cz'])}, "
                     f"{fnum(sp['r'])}, {fnum(sp['h'])}, {common}, role={pystr(sp.get('role', 'shell'))})")
    else:
        yaw = f", yaw={fnum(sp['yaw'])}" if sp.get("yaw") else ""
        lines.append(f"box({pystr(name)}, {fnum(sp['cx'])}, {fnum(sp['cy'])}, {fnum(sp['cz'])}, "
                     f"{fnum(sp['sx'])}, {fnum(sp['sy'])}, {fnum(sp['sz'])}, {common}{yaw}, "
                     f"role={pystr(sp.get('role', 'shell'))})")


def emit_furniture(lines, fu):
    kind = fu.get("kind")
    tag = pystr(fu.get("tag") or kind)
    if kind == "desk":
        lines.append(f"rig.desk({tag}, {fnum(fu['x'])}, {fnum(fu['y'])}, P, w={fnum(fu.get('w', 1.55))}, "
                     f"d={fnum(fu.get('d', 0.72))}, yaw={fnum(fu.get('yaw', 0))}, "
                     f"top={fnum(fu.get('top', 0.74))}, thick={fnum(fu.get('thick', 0.04))})")
    elif kind == "chair":
        lines.append(f"rig.chair({tag}, {fnum(fu['x'])}, {fnum(fu['y'])}, P, face={fnum(fu.get('face', 90))}, "
                     f"seat={fnum(fu.get('seat', 0.46))}, w={fnum(fu.get('w', 0.48))})")
    elif kind == "monitor":
        lines.append(f"rig.monitor({tag}, {fnum(fu['x'])}, {fnum(fu['y'])}, P, yaw={fnum(fu.get('yaw', 0))}, "
                     f"w={fnum(fu.get('w', 0.52))}, h={fnum(fu.get('h', 0.32))}, deskz={fnum(fu.get('deskz', 0.74))})")
    elif kind == "window":
        mul = tup(fu.get('mullions') or [])
        lines.append(f"rig.window(P, {fnum(fu['wallX'])}, {fnum(fu['y0'])}, {fnum(fu['y1'])}, "
                     f"{fnum(fu['sill'])}, {fnum(fu['head'])}, {fnum(fu['zc'])}, mullions={mul}, "
                     f"depth_axis={pystr(fu.get('depth_axis', 'x'))})")
    elif kind == "box":
        emit_piece(lines, {**fu, "name": fu.get("tag") or "家具"})
    elif kind == "cyl":
        emit_piece(lines, {**fu, "name": fu.get("tag") or "家具", "kind": "cyl"})


def build_figs(plan, scene_cfg, names):
    """每组独立 mannequin(绝不共享对象列表——hide_render 的循环后到者会覆盖)。"""
    scene_id = plan["scene_id"]
    groups = []
    for s in plan["shots"]:
        if s[4] not in groups:
            groups.append(s[4])
    anchors = scene_cfg.get("anchors") or {}
    char_groups = {}
    for g in sorted(groups):
        if g == "_":
            continue
        for c in g.split("_"):
            char_groups.setdefault(c, []).append(g)

    def tag_for(c, g):
        lst = char_groups[c]
        i = lst.index(g) + 1
        return c if i == 1 else f"{c}_g{i}"

    lines = []
    probe_tags = []
    for g in groups:
        if g == "_":
            lines.append(f'    "_": [],')
            continue
        calls = []
        for c in sorted(g.split("_")):
            a = anchor_or_none(scene_cfg, c)
            if a is None:
                continue                     # missing 已记录
            pose = a.get("pose") or "stand"
            height = a.get("height") if a.get("height") is not None else 1.68
            tag = tag_for(c, g)
            kw = f"height={fnum(height)}"
            if a.get("lead") is False:
                kw += ", lead=False"
            if a.get("seatZ") is not None:
                kw += f", seat_z={fnum(a['seatZ'])}"
            call = f'mannequin({pystr(tag)}, {tup(a["pos"])}, {fnum(a["face"])}, {pystr(pose)}, P, {kw})'
            calls.append((tag, call))
            probe_tags.append(tag)
        if not calls:
            lines.append(f'    {pystr(g)}: [],')
            continue
        if len(calls) == 1:
            lines.append(f"    {pystr(g)}: {calls[0][1]},")
        else:
            lines.append(f"    {pystr(g)}: ({calls[0][1]}")
            for _, call in calls[1:-1]:
                lines.append(f"                + {call}")
            lines.append(f"                + {calls[-1][1]}),")
    plan["fig_lines"] = lines
    plan["probe_tags"] = probe_tags
    plan["fig_groups"] = groups
    plan["char_groups"] = char_groups
    plan["tag_for"] = tag_for


def build_props(plan, scene_cfg, names):
    """道具永远是场景几何(不进 FIG)。挂手道具从 human.hand() 实测,失败用 fallback。"""
    lines = []
    plan["hand_vars"] = []
    for pid in sorted(scene_cfg.get("props") or {}):
        p = scene_cfg["props"][pid]
        if not prop_ready(p):
            continue  # 未被本段引用的未填道具不参与生成；引用缺项已记录。
        name = p.get("name") or pid
        dims = p.get("dims") or [0, 0, 0]
        mat = f"P[{pystr((p.get('mat') or 'PROP'))}]"
        role = pystr((p.get('role') or 'prop'))
        if p.get("hand"):
            if p.get("fallback") is None:
                continue                     # 缺 fallback 已进缺项清单,别在这里崩
            owner, _, side = str(p["hand"]).partition(":")
            off = p.get("offset") or [0, 0, 0]
            fb = p["fallback"]
            fb_lit = tup([fb[0] + off[0], fb[1] + off[1], fb[2] + off[2]])
            var_h, var_p = f"{pid}_H", f"{pid}_POS"
            plan["hand_vars"].append(var_p)
            lines.append(f'{var_h} = human.hand({pystr(owner)}, {pystr(side or "R")})')
            lines.append(f"{var_p} = ({var_h}.x + {fnum(off[0])}, {var_h}.y + {fnum(off[1])}, "
                         f"{var_h}.z + {fnum(off[2])}) if {var_h} else {fb_lit}")
            if (p.get('shape') or 'box') == "cyl":
                lines.append(f"cyl({pystr(name)}, *{var_p}, {fnum(dims[0])}, {fnum(dims[1])}, {mat}, role={role})")
            else:
                lines.append(f"box({pystr(name)}, *{var_p}, {fnum(dims[0])}, {fnum(dims[1])}, "
                             f"{fnum(dims[2])}, {mat}, role={role})")
            plan["ignore_names"].append(name)
        elif p.get("pos") is not None:
            z = prop_center_z(p)
            if (p.get('shape') or 'box') == "cyl":
                lines.append(f"cyl({pystr(name)}, {fnum(p['pos'][0])}, {fnum(p['pos'][1])}, {fnum(z)}, "
                             f"{fnum(dims[0])}, {fnum(dims[1])}, {mat}, role={role})")
            else:
                lines.append(f"box({pystr(name)}, {fnum(p['pos'][0])}, {fnum(p['pos'][1])}, {fnum(z)}, "
                             f"{fnum(dims[0])}, {fnum(dims[1])}, {fnum(dims[2])}, {mat}, role={role})")
            plan["ignore_names"].append(name)
    plan["prop_lines"] = lines


def build_ignore(plan):
    """每镜的遮挡忽略表:主体自己的身体部件 + 场景道具。
    不排掉的话每一镜都会报「主体挡住主体」的假警报,真警报被淹。"""
    prop_names = tuple(plan["ignore_names"])
    for sid, info in plan["subj_chars"].items():
        parts = list(prop_names)
        if info:
            cid, group = info
            tag_for = plan.get("tag_for")
            if cid and tag_for and group in plan.get("char_groups", {}).get(cid, []):
                parts.append(tag_for(cid, group))
        plan["ignore_by_sid"][sid] = tuple(parts)


def build_marks(plan, scene_cfg, names):
    """project/export 模式的 MARKS:人/道具/陈设三类(景别按人算,这是 check_prompt 的口径)。"""
    marks = []
    for cid in sorted(scene_cfg.get("anchors") or {}):
        a = scene_cfg["anchors"][cid]
        if a.get("pos") is None:
            continue
        h = a.get("height") if a.get("height") is not None else 1.68
        disp = names["chars"].get(cid, cid)
        marks.append((disp, tup([a["pos"][0], a["pos"][1], round(h * 0.54, 3)]),
                      tup([0.46, 0.42, h]), "person"))
    for pid in sorted(scene_cfg.get("props") or {}):
        p = scene_cfg["props"][pid]
        if not prop_ready(p):
            continue
        dimensions = p['dims']
        if (p.get('shape') or 'box') == 'cyl':
            dimensions = [dimensions[0] * 2, dimensions[0] * 2, dimensions[1]]
        dims = tup(dimensions)
        disp = p.get("name") or pid
        if p.get("hand"):
            marks.append((disp, f"{pid}_POS", dims, "prop"))
        elif p.get("pos") is not None:
            z = prop_center_z(p)
            marks.append((disp, tup([p["pos"][0], p["pos"][1], z]), dims, "prop"))
    for fu in scene_cfg.get("furniture") or []:
        kind = fu.get("kind")
        if kind == "desk":
            marks.append((fu.get("tag") or "桌", tup([fu["x"], fu["y"], fu.get("top", 0.74) - 0.38]),
                          tup([fu.get("w", 1.55), fu.get("d", 0.72), 0.76]), "set"))
        elif kind == "chair":
            marks.append((fu.get("tag") or "椅", tup([fu["x"], fu["y"], 0.45]),
                          tup([0.5, 0.5, 0.9]), "set"))
        elif kind == "monitor":
            marks.append((fu.get("tag") or "屏", tup([fu["x"], fu["y"], fu.get("deskz", 0.74) + fu.get("h", 0.32) / 2]),
                          tup([fu.get("w", 0.52), 0.08, fu.get("h", 0.32)]), "set"))
        elif kind == "box":
            marks.append((fu.get("tag") or "家具", tup([fu["cx"], fu["cy"], fu["cz"]]),
                          tup([fu["sx"], fu["sy"], fu["sz"]]), "set"))
        elif kind == "cyl":
            marks.append((fu.get("tag") or "家具", tup([fu["cx"], fu["cy"], fu["cz"]]),
                          tup([fu["r"] * 2, fu["r"] * 2, fu["h"]]), "set"))
    for sp in scene_cfg.get("setPieces") or []:
        if sp.get("kind") == "cyl":
            marks.append((sp.get("name") or "体块", tup([sp["cx"], sp["cy"], sp["cz"]]),
                          tup([sp["r"] * 2, sp["r"] * 2, sp["h"]]), "set"))
        else:
            marks.append((sp.get("name") or "体块", tup([sp["cx"], sp["cy"], sp["cz"]]),
                          tup([sp["sx"], sp["sy"], sp["sz"]]), "set"))
    plan["marks"] = marks


# ─────────────────────────────── 代码生成 ───────────────────────────────

def emit_scene(plan, blockout_path, cmd_line, prov):
    seg = plan["seg"]
    cuts = seg.get("cuts") or []
    times = cumulative([c.get("seconds", 0) for c in cuts])
    total = round(times[-1][1], 3) if times else 0.0
    sid, scene_id, scene_name = plan["seg_id"], plan["scene_id"], plan["scene_name"]

    degr_txt = "".join(
        f"\n  降级  {d['cut']}  {d['camera']} → "
        f"{'静态' if d['action'] == 'static' else ('推近近似变焦' if d['action'] == 'zoom' else '眼点静态近似POV')}"
        for d in plan["degradations"]) or "\n  降级  (无)"

    L = []
    L.append(f'"""{sid} · {scene_id} {scene_name} · {len(cuts)} 切 / {fnum(total)}s')
    L.append(f'')
    L.append(f'novel-previz 从分镜确定性生成——别手挥机位,改场景配置再重新生成。')
    L.append(f'手改过本文件后请跑 validate 复检。')
    L.append(f'')
    L.append('能力边界：这是按原时间轴生成的基础白模，不代表原分镜动作和构图已经验证。')
    for warning in plan['warnings']:
        label = warning['cut'] or sid
        fields = ', '.join(warning['fields'])
        L.append(f'  未预演 {label}: {fields}；{warning["reason"]}')
    L.append('')
    L.append(f'provenance:')
    L.append(f'  storyboard  {prov["sb_name"]}  sha256:{prov["sb_sha"]}')
    L.append(f'  script      {prov["sc_name"]}  sha256:{prov["sc_sha"]}')
    L.append(f'  config      {prov["cfg_name"]}  sha256:{prov["cfg_sha"]}')
    L.append(f'  命令        {cmd_line}')
    L.append(f'跑法:')
    L.append(f'  blender -b --python-exit-code 1 --python scene.py -- audit')
    L.append(f'  blender -b --python-exit-code 1 --python scene.py -- probe')
    L.append(f'  blender -b --python-exit-code 1 --python scene.py -- project')
    L.append(f'  blender -b --python-exit-code 1 --python scene.py -- export facts.json')
    L.append(f'  blender -b --python-exit-code 1 --python scene.py -- blockers')
    L.append(f'  blender -b --python-exit-code 1 --python scene.py -- plan        out')
    L.append(f'  blender -b --python-exit-code 1 --python scene.py -- review      out')
    L.append(f'  blender -b --python-exit-code 1 --python scene.py -- review_anim out/review')
    L.append(f'  blender -b --python-exit-code 1 --python scene.py -- anim        out/model')
    L.append(f'"""')
    # repr 转义 Windows 路径和自由文本，避免文档字符串中的反斜杠破坏语法。
    L = [pystr('\n'.join([L[0][3:], *L[1:-1]]))]
    L.append(f'import sys, os, pathlib')
    L.append(f'sys.path.insert(0, r"{blockout_path}")')
    L.append(f'import rig')
    L.append(f'from rig import box, cyl, cam')
    L.append(f'import human')
    L.append(f'from human import mannequin')
    L.append(f'')
    L.append(f'ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []')
    L.append(f'MODE = ARGS[0] if ARGS else "review"')
    L.append(f'OUT  = ARGS[1] if len(ARGS) > 1 else "out"')
    L.append(f'')
    L.append(f'S = rig.new_scene()')
    L.append(f'P = rig.palette()')
    L.append(f'')
    L.extend(plan["geo_lines"])
    L.append(f'')
    L.append(f'# ── 人物:组键=本镜在场人物(跨组同角色独立建,tag 唯一) ──')
    L.append(f'FIG = {{')
    L.extend(plan["fig_lines"])
    L.append(f'}}')
    L.append(f'')
    if plan["prop_lines"]:
        L.append(f'# ── 道具:挂手的从 human.hand() 实测,失败用 fallback ──')
        L.extend(plan["prop_lines"])
        L.append(f'')
    L.append(f'# ── 机位:焦距优先取分镜 lens,机高/注视高度按主体身高缩放 ──')
    L.append(f'CAMS = {{')
    for c in plan["cams"]:
        if c["runtime"]:
            b = c["subject"]["est"]
            dx = round(c["loc"][0] - b[0], 3)
            dy = round(c["loc"][1] - b[1], 3)
            loc_lit = f'({c["subject"]["var"]}[0] + {fnum(dx)}, {c["subject"]["var"]}[1] + {fnum(dy)}, ' \
                      f'{c["subject"]["var"]}[2] + {fnum(c["loc"][2] - b[2])})'
            look_lit = c["subject"]["var"]
        else:
            loc_lit = tup([round(v, 3) for v in c["loc"]])
            look_lit = tup([round(v, 3) for v in c["look"]])
        az_deg = round(math.degrees(math.atan2(c["loc"][1] - c["look"][1],
                                               c["loc"][0] - c["look"][0]))) % 360
        src = "lens" if c["lens_src"] == "lens" else "defaultLens"
        span_txt = f" · span {c['subject']['span']:.2f}m" if c["subject"]["span"] else ""
        L.append(f' "{c["name"]}": ({loc_lit}, {look_lit}, {fnum(c["lens"])}),'
                 f'   # {c["sid"]} · {c["size"]}{span_txt} · d={c["dist_eff"]:.2f} · {src}')
    L.append(f'}}')
    L.append(f'for n, (loc, look, lens) in CAMS.items():')
    L.append(f'    cam(S, n, loc, look, lens)')
    L.append(f'')
    L.append(f'# 时间轴——这张表是唯一真相:prompt 的时间码、切片边界、切点核验全从它取。')
    L.append(f'SHOTS = [')
    for s in plan["shots"]:
        L.append(f'    ({pystr(s[0])}, {pystr(s[1])}, {fnum(round(s[2], 3))}, '
                 f'{fnum(round(s[3], 3))}, {pystr(s[4])}, {pystr(s[5])}),')
    L.append(f']')
    if plan["moves"]:
        parts = []
        for s, v in plan["moves"].items():
            lit = fnum(v) if isinstance(v, (int, float)) else tup(v)
            parts.append(f"{pystr(s)}: {lit}")
        body = ", ".join(parts)
        L.append(f'MOVES = {{{body}}}     # 数字 = 沿视线推拉;三元组 = 任意平移')
    else:
        L.append(f'MOVES = {{}}     # 数字 = 沿视线推拉;三元组 = 任意平移')
    track_degr = any(d["camera"] == "Tracking Shot" for d in plan["degradations"])
    L.append(f'WALKS = {{}}' + ("     # 走位戏需手填(Tracking Shot 已降级为静态)" if track_degr else ""))
    L.append(f'')
    L.extend(emit_dispatch(plan, sid, scene_id, scene_name, total))
    return "\n".join(L) + "\n"


def emit_dispatch(plan, sid, scene_id, scene_name, total):
    L = []
    L.append(f'if MODE == "audit":')
    L.append(f'    import bpy')
    L.append(f'    rig.audit_model_pass(bpy.data.objects)          # 送模版明度自检')
    L.append(f'elif MODE == "probe":')
    L.append(f'    import bpy')
    L.append(f'    print("── 人体关节实测 ──")')
    if plan["probe_tags"]:
        names = []
        for t in plan["probe_tags"]:
            names.extend([f"{t}_头", f"{t}_hand.R", f"{t}_hand.L"])
        L.append(f'    for n in ({", ".join(pystr(n) for n in names)}):')
        L.append(f'        o = bpy.data.objects.get(n)')
        L.append(f'        if o:')
        L.append(f'            c = o.matrix_world.translation')
        L.append(f'            print(f"  {{n:<16}} ({{c.x:+.2f}},{{c.y:+.2f}},{{c.z:+.2f}})")')
    else:
        L.append(f'    print("  (本段无人物)")')
    for var_p in plan.get("hand_vars") or []:
        L.append(f'    print("  {var_p}", tuple(round(v, 2) for v in {var_p}))')
    L.append(f'elif MODE == "blockers":')
    L.append(f'    import bpy, project')
    subj_items = []
    for s in plan["shots"]:
        v = plan["subj"].get(s[0])
        if v is None:
            v = tup([0, 0, 1.4])
        subj_items.append(f'{pystr(s[0])}: ' + (v if isinstance(v, str) else tup([round(x, 3) for x in v])))
    L.append(f'    SUBJ = {{' + ", ".join(subj_items) + "}")
    ig_items = ", ".join(
        f"{pystr(sid)}: (" + ", ".join(pystr(n) for n in names) + ")"
        for sid, names in plan["ignore_by_sid"].items())
    L.append(f'    IGNORE = {{{ig_items}}}      # 主体自己的部件和道具不算遮挡')
    L.append(f'    for sid_, cname, t0, t1, _g, txt in SHOTS:')
    L.append(f'        loc, look, lens = CAMS[cname]')
    L.append(f'        hs = project.blockers(loc, look, lens, SUBJ[sid_], bpy.data.objects,')
    L.append(f'                              ignore=IGNORE.get(sid_, ()))')
    L.append(f'        print(f"{{sid_}} {{cname}} → {{txt[:24]}}")')
    L.append(f'        if not hs:')
    L.append(f'            print("   通畅")')
    L.append(f'        for gap, name, d, r in hs:')
    hit_line = "{'✗挡' if gap < 0 else ' 擦边'} {name:<16} 距{d:4.2f}m 离轴{gap + r:5.2f}m"
    L.append(f'            print(f"   {hit_line}")')
    L.append(f'elif MODE in ("project", "export"):')
    L.append(f'    import project')
    L.append(f'    # 第三项是类别:景别按**人**在画幅里的高度定义,拿门洞或柜台去算只会得到胡话。')
    L.append(f'    MARKS = {{')
    for disp, pos, dims, kind in plan["marks"]:
        pos_lit = pos if isinstance(pos, str) else pos
        L.append(f'        {pystr(disp)}: ({pos_lit}, {dims}, {pystr(kind)}),')
    L.append(f'    }}')
    L.append(f'    if MODE == "export":')
    L.append(f'        # 白模事实导出,给 check_prompt.py 拿它和 prompt 对账。')
    L.append(f'        import json')
    L.append(f'        out = []')
    L.append(f'        for sid_, cname, t0, t1, _g, txt in SHOTS:')
    L.append(f'            loc, look, lens = CAMS[cname]')
    L.append(f'            marks = {{}}')
    L.append(f'            for name, mk in MARKS.items():')
    L.append(f'                pt, dims = mk[0], mk[1]')
    L.append(f'                kind = mk[2] if len(mk) > 2 else "set"')
    L.append(f'                x, y, d = project.project(loc, look, lens, pt)')
    L.append(f'                if x is None or abs(x) > 1.6 or abs(y) > 1.6:')
    L.append(f'                    continue')
    L.append(f'                w, h = project.size_on_screen(loc, look, lens, pt, dims)')
    L.append(f'                marks[name] = {{"x": round(x, 3), "y": round(y, 3), "kind": kind,')
    L.append(f'                               "w": round(w, 3), "h": round(h, 3), "d": round(d, 2)}}')
    L.append(f'            out.append({{"id": sid_, "cam": cname, "t0": t0, "t1": t1,')
    L.append(f'                        "lens": lens, "note": txt, "marks": marks}})')
    L.append(f'        pathlib.Path(OUT).write_text(')
    L.append(f'            json.dumps({{"shots": out}}, ensure_ascii=False, indent=1), encoding="utf-8")')
    L.append(f'        print(f"EXPORT_DONE {{OUT}}  {{len(out)}} 镜")')
    L.append(f'    else:')
    L.append(f'        print(project.report(SHOTS, CAMS, MARKS))')
    L.append(f'elif MODE == "review":')
    L.append(f'    rig.use_review_pass(S, note={pystr(f"{sid} · {scene_id} {scene_name} · {len(plan["shots"])} 切 {fnum(total)}s")})')
    L.append(f'    rig.render_stills(S, CAMS, OUT, FIG, SHOTS)')
    L.append(f'elif MODE == "plan":')
    L.append(f'    rig.render_plan(S, CAMS, OUT + "/plan.png", size=14.0, center={plan.get("plan_center", "(0.0, 3.0)")})')
    L.append(f'elif MODE == "review_anim":')
    L.append(f'    rig.use_review_pass(S, note={pystr(f"{sid} · {scene_id} {scene_name}")})')
    L.append(f'    rig.render_anim(S, SHOTS, CAMS, OUT, FIG, MOVES, WALKS)')
    L.append(f'elif MODE == "anim":')
    L.append(f'    rig.render_anim(S, SHOTS, CAMS, OUT, FIG, MOVES, WALKS)')
    return L


# ─────────────────────────────── 对账门 ───────────────────────────────

GATE_DEFS = []          # (id, label)


def gate(gid, label):
    def deco(fn):
        GATE_DEFS.append((gid, label, fn))
        return fn
    return deco


def collect_missing(plans):
    seen = []
    for p in plans:
        for m in p["missing"]:
            if m not in seen:
                seen.append(m)
    return seen


def run_gates(sb, script, cfg, plans, params):
    """返回 [{id,label,ok,warn,detail}];ok=False 计入退出码 1。"""
    results = []
    ctx = {"sb": sb, "script": script, "cfg": cfg, "plans": plans, "params": params}

    def add(gid, label, ok, detail, warn=False):
        results.append({"id": gid, "label": label, "ok": bool(ok) if ok is not None else None,
                        "warn": warn, "detail": detail})

    for gid, label, fn in GATE_DEFS:
        try:
            problems, warn_detail = fn(ctx)
        except Exception as e:                      # 门自身崩了也算失败,不能静默
            add(gid, label, False, f"门执行异常: {e}")
            continue
        if problems:
            add(gid, label, False, "; ".join(problems[:6]))
        elif warn_detail:
            add(gid, label, True, warn_detail, warn=True)
        else:
            add(gid, label, True, "通过")
    return results


def _all_cuts(sb):
    for ep in sb.get("episodes") or []:
        for seg in ep.get("segments") or []:
            for k, cut in enumerate(seg.get("cuts") or [], 1):
                yield ep.get("ep"), seg, k, cut


@gate("seg-seq", "段号连号")
def g_seg_seq(ctx):
    problems = []
    seen = set()
    for ep in ctx["sb"].get("episodes") or []:
        for i, seg in enumerate(ep.get("segments") or [], 1):
            sid = seg.get("id")
            want = f"E{ep.get('ep', 0):02d}-{i:02d}"
            if sid != want:
                problems.append(f"{sid} 应为 {want}")
            if sid in seen:
                problems.append(f"{sid} 重复")
            seen.add(sid)
    return problems, None


@gate("cut-seconds", "分镜时长")
def g_cut_seconds(ctx):
    p = ctx["params"]
    lo, hi = p["minCutSeconds"], p["maxCutSeconds"]
    problems = []
    for _ep, seg, k, cut in _all_cuts(ctx["sb"]):
        s = cut.get("seconds")
        if not isinstance(s, (int, float)) or isinstance(s, bool) or s < lo or s > hi:
            problems.append(f"{seg.get('id')}-f{k} seconds={s} 不在 [{lo}, {hi}]")
    return problems, None


@gate("seg-cap", "段长上限")
def g_seg_cap(ctx):
    cap = ctx["params"]["maxSegmentSeconds"]
    problems = []
    for ep in ctx["sb"].get("episodes") or []:
        for seg in ep.get("segments") or []:
            total = sum(c.get("seconds", 0) for c in seg.get("cuts") or [])
            if total > cap:
                problems.append(f"{seg.get('id')} 总长 {total}s > {cap}s")
    return problems, None


@gate("frames-24", "帧换算")
def g_frames(ctx):
    """逐字复刻 rig.render_anim:f0 = max(1, int(round((t0-base)*24)))。"""
    problems = []
    for ep in ctx["sb"].get("episodes") or []:
        for seg in ep.get("segments") or []:
            times = cumulative([c.get("seconds", 0) for c in seg.get("cuts") or []])
            if not times:
                continue
            base = times[0][0]
            for k, (t0, t1) in enumerate(times, 1):
                f0 = max(1, int(round((t0 - base) * FPS)))
                f1 = int(round((t1 - base) * FPS))
                if f1 <= f0:
                    problems.append(f"{seg.get('id')}-f{k} 取整后不足 1 帧(f0={f0}, f1={f1})")
                # 首镜 t0 被 rig 的 max(1,·) 钳到帧 1,这是设计不是漂移,跳过
                checks = [(t1, f1)] if k == 1 else [(t0, f0), (t1, f1)]
                for t, f in checks:
                    if abs(f / FPS - (t - base)) > 1.0 / FPS / 2 + 1e-9:
                        problems.append(f"{seg.get('id')}-f{k} 帧漂移超半帧(t={t}, f={f})")
            total = times[-1][1] - base
            if int(round(total * FPS)) < 1:
                problems.append(f"{seg.get('id')} 总帧数 < 1")
    return problems, None


@gate("cam-enum", "运镜/景别词表")
def g_cam_enum(ctx):
    problems = []
    for _ep, seg, k, cut in _all_cuts(ctx["sb"]):
        if cut.get("camera") not in CAMERA_ENUM:
            problems.append(f"{seg.get('id')}-f{k} camera={cut.get('camera')!r} 不在 20 词表")
        if cut.get("size") not in SIZE_ZH:
            problems.append(f"{seg.get('id')}-f{k} size={cut.get('size')!r} 不在 5 档景别")
    return problems, None


@gate("lens-parse", "焦距可得")
def g_lens(ctx):
    fallbacks, problems = 0, []
    default = (ctx["cfg"] or {}).get("defaultLens")
    for _ep, seg, k, cut in _all_cuts(ctx["sb"]):
        if parse_lens(cut.get("lens")) is None:
            if default is None:
                problems.append(f"{seg.get('id')}-f{k} lens 解析不出且配置无 defaultLens")
            else:
                fallbacks += 1
    warn = f"{fallbacks} 处用 defaultLens 兜底" if fallbacks else None
    return problems, warn


@gate("join-scene", "场次对接")
def g_join_scene(ctx):
    problems = []
    sb_eps = ctx["sb"].get("episodes") or []
    sc_by_ep = {ep.get("ep"): ep for ep in (ctx["script"] or {}).get("episodes") or []}
    for ep_sb in sb_eps:
        ep_sc = sc_by_ep.get(ep_sb.get("ep"))
        if ep_sc is None:
            problems.append(f"分镜第 {ep_sb.get('ep')} 集在剧本中不存在")
            continue
        scenes = ep_sc.get("scenes") or []
        for seg in ep_sb.get("segments") or []:
            idx = seg.get("sceneIndex")
            if not isinstance(idx, int) or idx < 1 or idx > len(scenes):
                problems.append(f"{seg.get('id')} sceneIndex={idx} 超出剧本场次")
                continue
            sid = scenes[idx - 1].get("sceneId")
            if ctx["cfg"] and sid not in (ctx["cfg"].get("scenes") or {}):
                problems.append(f"{seg.get('id')} → {sid} 不在场景配置里")
    return problems, None


@gate("join-cast", "人物道具对接")
def g_join_cast(ctx):
    """键都没有 = 配置与分镜彻底脱节(✗);键在但未填(null) = 待补,走缺项通道。"""
    problems = []
    for plan in ctx["plans"]:
        scene_cfg = (ctx["cfg"].get("scenes") or {}).get(plan["scene_id"]) or {}
        anchors = scene_cfg.get("anchors") or {}
        props = scene_cfg.get("props") or {}
        for k, cut in enumerate(plan["seg"].get("cuts") or [], 1):
            for c in cut.get("characters") or []:
                if c not in anchors:
                    problems.append(f"{plan['seg_id']}-f{k} 角色 {c} 不在配置 anchors")
            for p in cut.get("props") or []:
                if p not in props:
                    problems.append(f"{plan['seg_id']}-f{k} 道具 {p} 不在配置 props")
    return problems, None


@gate("pose-valid", "姿势合法")
def g_pose(ctx):
    problems = []
    for sid, scene in sorted((ctx["cfg"].get("scenes") or {}).items()):
        for cid, a in sorted((scene.get("anchors") or {}).items()):
            pose = a.get("pose")
            if pose is not None and pose not in POSES:
                problems.append(f"{sid}.{cid} pose={pose!r} 不在 human.POSES(会静默 T-pose)")
    return problems, None


@gate("seat-z", "坐姿椅面")
def g_seat_z(ctx):
    problems = []
    for sid, scene in sorted((ctx["cfg"].get("scenes") or {}).items()):
        for cid, a in sorted((scene.get("anchors") or {}).items()):
            if a.get("pose") in SIT_POSES and not isinstance(a.get("seatZ"), (int, float)):
                problems.append(f"{sid}.{cid} 坐姿 pose 需要 seatZ(数字),当前 {a.get('seatZ')!r}")
    return problems, None


def _check_furniture_one(sid, fu, problems):
    kind = fu.get("kind")
    if kind not in FURNITURE_KINDS:
        problems.append(f"{sid} furniture kind={kind!r} 不在 {FURNITURE_KINDS}")
        return
    if kind in ("desk", "chair", "monitor"):
        for f in ("x", "y"):
            if not isinstance(fu.get(f), (int, float)):
                problems.append(f"{sid} {kind} 缺 {f}")
    elif kind == "window":
        for f in ("wallX", "y0", "y1", "sill", "head", "zc"):
            if not isinstance(fu.get(f), (int, float)):
                problems.append(f"{sid} window 缺 {f}")
    else:
        for f in (("cx", "cy", "cz", "sx", "sy", "sz") if kind == "box" else ("cx", "cy", "cz", "r", "h")):
            if not isinstance(fu.get(f), (int, float)):
                problems.append(f"{sid} {kind} 缺 {f}")
    if kind in ("box", "cyl") or kind == "setpiece":
        if fu.get("mat") and fu["mat"] not in PALETTE_KEYS:
            problems.append(f"{sid} {kind} mat={fu['mat']!r} 不在调色板")
        if fu.get("role") and fu["role"] not in VALID_ROLES:
            problems.append(f"{sid} {kind} role={fu['role']!r} 无效")


@gate("furniture-args", "家具参数")
def g_furniture(ctx):
    problems = []
    for sid, scene in sorted((ctx["cfg"].get("scenes") or {}).items()):
        for fu in scene.get("furniture") or []:
            _check_furniture_one(f"{sid}.furniture", fu, problems)
        for sp in scene.get("setPieces") or []:
            kind = sp.get("kind", "box")
            _check_furniture_one(f"{sid}.setPieces", {**sp, "kind": ("box" if kind != "cyl" else "cyl")}, problems)
            if sp.get("mat") and sp["mat"] not in PALETTE_KEYS:
                problems[-1:-1] = []
    return problems, None


@gate("prop-attach", "道具挂接")
def g_prop(ctx):
    problems = []
    for sid, scene in sorted((ctx['cfg'].get('scenes') or {}).items()):
        anchors = scene.get('anchors') or {}
        for pid, prop in sorted((scene.get('props') or {}).items()):
            problems.extend(f'{sid}.{pid} {msg}' for msg in prop_errors(prop))
            if isinstance(prop, dict) and prop.get('hand'):
                owner = str(prop['hand']).partition(':')[0]
                if owner not in anchors:
                    problems.append(f'{sid}.{pid} 挂接对象 {owner} 无锚点')
    return problems, None


@gate("preset-valid", "机位预设")
def g_preset(ctx):
    problems = []
    for size, pr in sorted((ctx["cfg"].get("camPresets") or {}).items()):
        if size not in BUILTIN_PRESETS:
            problems.append(f"camPresets 键 {size!r} 不在五种景别")
            continue
        for f in ("dist", "eye", "lookZ"):
            v = pr.get(f, BUILTIN_PRESETS[size][f])
            if not isinstance(v, (int, float)) or (f == "dist" and v <= 0):
                problems.append(f"camPresets.{size}.{f}={v!r} 无效")
    return problems, None


def _extract_dict_keys(text, varname):
    m = re.search(rf"^{varname}\s*=\s*\{{(.*?)^\}}", text, re.S | re.M)
    if not m:
        return None
    return re.findall(r'[\'"]([^\'"]+)[\'"]\s*:', m.group(1))


@gate("geo-reuse", "场景复用")
def g_geo_reuse(ctx):
    problems = []
    blocks = {}
    for p in ctx["plans"]:
        if not p["complete"] or not p["text"]:
            continue
        m = re.search(r"# ── 场景几何 (\S+) 开始 ──\n(.*?)# ── 场景几何 结束 ──",
                      p["text"], re.S)
        if not m:
            problems.append(f"{p['seg_id']} 找不到场景几何标记")
            continue
        sid, block = m.group(1), m.group(2)
        if sid in blocks and blocks[sid] != block:
            problems.append(f"场景 {sid} 在不同段的几何块不一致")
        blocks[sid] = block
    return problems, None


@gate("cams-closure", "机位闭合")
def g_cams(ctx):
    problems = []
    for p in ctx["plans"]:
        if not p["text"]:
            continue
        keys = _extract_dict_keys(p["text"], "CAMS")
        if keys is None:
            problems.append(f"{p['seg_id']} 抠不出 CAMS")
            continue
        for s in p["shots"]:
            if s[1] not in keys:
                problems.append(f"{p['seg_id']} SHOTS 用到机位 {s[1]!r} 但 CAMS 没有")
    return problems, None


@gate("fig-closure", "人物组闭合")
def g_fig(ctx):
    problems = []
    for p in ctx["plans"]:
        if not p["text"]:
            continue
        keys = _extract_dict_keys(p["text"], "FIG") or []
        for s in p["shots"]:
            if s[4] not in keys:
                problems.append(f"{p['seg_id']} SHOTS 用到人物组 {s[4]!r} 但 FIG 只有 "
                                f"{'、'.join(keys) or '(空)'}")
    return problems, None


@gate("shots-roundtrip", "时间轴回读")
def g_roundtrip(ctx):
    """用 harness 工具的同款正则重抠 SHOTS,和分镜累加对账。"""
    problems = []
    for p in ctx["plans"]:
        if not p["text"]:
            continue
        m = RE_SHOTS.search(p["text"])
        if not m:
            problems.append(f"{p['seg_id']} 的 SHOTS 抠不出来(tools 也会失败)")
            continue
        try:
            got = ast.literal_eval("[" + m.group(1) + "]")
        except (ValueError, SyntaxError) as e:
            problems.append(f"{p['seg_id']} SHOTS 不是纯字面量: {e}")
            continue
        want = cumulative([c.get("seconds", 0) for c in p["seg"].get("cuts") or []])
        if len(got) != len(want):
            problems.append(f"{p['seg_id']} 镜数 {len(got)} ≠ 分镜 {len(want)}")
            continue
        for k, (row, (t0, t1)) in enumerate(zip(got, want), 1):
            if len(row) != 6:
                problems.append(f"{p['seg_id']}-f{k} 不是 6 元组")
                continue
            if row[0] != f"{p['seg_id']}-f{k}":
                problems.append(f"{p['seg_id']}-f{k} 镜号 {row[0]!r} 错序")
            if abs(row[2] - t0) > 5e-4 or abs(row[3] - t1) > 5e-4:
                problems.append(f"{p['seg_id']}-f{k} 时间 {row[2]}–{row[3]} ≠ 累加 {t0:.3f}–{t1:.3f}")
    return problems, None


@gate("py-syntax", "语法可解析")
def g_syntax(ctx):
    problems = []
    for p in ctx["plans"]:
        if not p["text"]:
            continue
        try:
            ast.parse(p["text"])
        except SyntaxError as e:
            problems.append(f"{p['seg_id']} 第 {e.lineno} 行语法错误: {e.msg}")
    return problems, None


# ─────────────────────────────── 命令 ───────────────────────────────

def iter_selected_segments(sb, args):
    for ep in sb.get("episodes") or []:
        if getattr(args, "ep", None) is not None and ep.get("ep") != args.ep:
            continue
        for seg in ep.get("segments") or []:
            if getattr(args, "segment", None) and seg.get("id") != args.segment:
                continue
            yield ep, seg


def build_names(sb, script, art, outline):
    names = {"chars": {}, "scenes": {}, "props": {}}
    if outline:
        for c in outline.get("characters") or []:
            names["chars"].setdefault(c.get("id"), c.get("name") or c.get("id"))
        for s in outline.get("scenes") or []:
            names["scenes"].setdefault(s.get("id"), s.get("name") or s.get("id"))
    if art:
        for s in art.get("scenes") or []:
            names["scenes"][s.get("id")] = s.get("name") or s.get("id")
        for p in art.get("props") or []:
            names["props"].setdefault(p.get("id"), p.get("name") or p.get("id"))
    return names


def probe_blockout(args):
    if getattr(args, "blockout", None):
        p = os.path.abspath(args.blockout)
    else:
        p = os.path.normpath(os.path.join(HERE, "..", "..", "greybox-harness", "blockout"))
    return p.replace("\\", "/")


def cmd_line_str(argv):
    return "python3 " + " ".join(argv)


def core_export(sb, script, cfg, art, outline, out_dir, args, argv, src_paths):
    params = dict(DEFAULT_PARAMS)
    params.update((sb.get("params") or {}))
    names = build_names(sb, script, art, outline)
    script_eps = {ep.get("ep"): ep for ep in (script.get("episodes") or [])}
    blockout = probe_blockout(args)
    cmd = cmd_line_str(argv)
    prov_names = {"sb_name": os.path.basename(src_paths["sb"]),
                  "sc_name": os.path.basename(src_paths["sc"]),
                  "cfg_name": os.path.basename(src_paths["cfg"]),
                  "sb_sha": src_paths["sb_sha"], "sc_sha": src_paths["sc_sha"],
                  "cfg_sha": src_paths["cfg_sha"]}

    selected = list(iter_selected_segments(sb, args))
    if not selected:
        fail(3, '没有匹配的分镜段，请检查 --ep / --segment')
    for _ep, seg in selected:
        if not re.fullmatch(r'E[0-9]{2,}-[0-9]{2,}', str(seg.get('id', ''))):
            fail(3, f"段号不能作为安全输出目录: {seg.get('id')!r}")
        for filename in ('scene.py', 'scene.py.todo', 'scene.py.stale'):
            output_path(out_dir, seg['id'], filename)
    # 先失效旧产物，即使随后生成或校验失败，也不能误执行旧版本。
    for _ep, seg in selected:
        invalidate_scene(out_dir, seg['id'])
    report_path = output_path(out_dir, '_report', 'report.json')
    report_stale = output_path(out_dir, '_report', 'report.json.stale')
    if os.path.isfile(report_path):
        os.replace(report_path, report_stale)

    plans = []
    for ep, seg in selected:
        plan = resolve_segment(seg, script_eps.get(ep.get("ep"), {}), cfg, names)
        # plan 模式中心
        scene_cfg = (cfg.get("scenes") or {}).get(plan["scene_id"]) or {}
        if scene_cfg.get("room"):
            r = scene_cfg["room"]
            plan["plan_center"] = tup([(r["x0"] + r["x1"]) / 2.0, (r["y0"] + r["y1"]) / 2.0])
        elif scene_cfg.get("floor"):
            f = scene_cfg["floor"]
            plan["plan_center"] = tup([f["cx"], f["cy"]])
        if plan['complete']:
            plan['text'] = emit_scene(plan, blockout, cmd, prov_names)
        plans.append(plan)

    gates = run_gates(sb, script, cfg, plans, params)
    publish_plans(plans, gates, out_dir)
    missing = collect_missing(plans)
    report = {
        "generated": [{"segment": p["seg_id"], "scene": p["scene_id"], "file": p["file"],
                       "complete": p["complete"],
                       "cuts": len(p["seg"].get("cuts") or []),
                       "seconds": round(sum(c.get("seconds", 0) for c in p["seg"].get("cuts") or []), 3),
                       "degradations": p["degradations"], "missing": p["missing"]}
                      for p in plans],
        "gates": gates,
        "unverified": [w for p in plans for w in p['warnings']],
        "missing": missing,
        "summary": {
            "segments": f"{sum(1 for p in plans if p['complete'])}/{len(plans)}",
            "degradations": sum(len(p["degradations"]) for p in plans),
            "missing": len(missing),
            "lensFallback": sum(len(p["lens_fallback"]) for p in plans),
            'unverified': sum(len(p['warnings']) for p in plans),
        },
    }
    write_text(os.path.join(out_dir, "_report", "report.json"),
               json.dumps(report, ensure_ascii=False, indent=1))

    # 控制台
    for p in plans:
        secs = round(sum(c.get("seconds", 0) for c in p["seg"].get("cuts") or []), 3)
        head = (f"段 {p['seg_id']} · {p['scene_id']} {p['scene_name']} · "
                f"{len(p['seg'].get('cuts') or [])} 切 / {fnum(secs)}s")
        if p["complete"]:
            print(f"{head} ✓")
        else:
            print(f"{head} 待补 {len(p['missing'])} 项（scene.py.todo）")
            for m in p["missing"]:
                print(f"    待补 {m['item']}.{m['field']} —— {m['reason']}")
    print('能力边界：这里只检查转换结构与时间轴，不验证原分镜的构图、动作或表演。')
    print(f"未预演 {report['summary']['unverified']} 项，逐段逐切详情见报告 unverified。")
    print("── 对账门 ──")
    n_ok = sum(1 for g in gates if g["ok"] and not g["warn"])
    n_warn = sum(1 for g in gates if g["warn"])
    n_bad = sum(1 for g in gates if not g["ok"])
    for g in gates:
        mark = "✓" if g["ok"] and not g["warn"] else ("!" if g["warn"] else "✗")
        print(f"  {mark} {g['id']:<15} {g['label']} —— {g['detail']}")
    s = report["summary"]
    print(f"汇总：段 {s['segments']} · 门 {n_ok}✓/{n_warn}!/{n_bad}✗ · "
          f"降级 {s['degradations']} · 待补 {s['missing']} · 焦距兜底 {s['lensFallback']}")
    print(f"报告：{os.path.join(out_dir, '_report', 'report.json')}")

    if n_bad:
        return 1
    if missing or any(not p["complete"] for p in plans):
        return 2
    return 0


def cmd_analyze(args, argv):
    from previs_analysis import analyze_storyboard, markdown_report, METHOD_LABELS
    storyboard = load_json(args.storyboard, '分镜')
    try:
        report = analyze_storyboard(storyboard, MOVE_TABLE, args.ep, args.segment)
    except ValueError as exc:
        fail(3, str(exc))
    directory = output_path(args.out, '_analysis')
    json_path = output_path(directory, 'analysis.json')
    md_path = output_path(directory, 'analysis.md')
    if os.path.realpath(args.storyboard) in (json_path, md_path):
        fail(3, '分析输出不能覆盖输入分镜')
    write_text(json_path, json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    write_text(md_path, markdown_report(report))
    for item in report['segments']:
        modes = ' + '.join(METHOD_LABELS[method] for method in item['methods'])
        print(f"{item['segment']}：{modes}")
    print('这是规则初筛，不代表已经执行预演；范围、依据和限制见报告。')
    print(f'分析报告：{md_path}')
    print(f'结构化结果：{json_path}')


def cmd_export_grid(args, argv):
    from grid_export import export_grid
    try:
        code = export_grid(sys.modules[__name__], args)
    except (ValueError, OSError) as exc:
        fail(3, str(exc))
    sys.exit(code)


def cmd_export(args, argv):
    sb = load_json(args.storyboard, "分镜")
    script = load_json(args.script, "剧本")
    cfg = load_json(args.config, "场景配置")
    if cfg.get("version") != 1:
        fail(3, f"场景配置 version={cfg.get('version')!r},只支持 1")
    art = load_json(args.art, "美术设定") if args.art else None
    outline = load_json(args.outline, "人物表") if args.outline else None
    out_dir = os.path.abspath(args.out)
    src_paths = {"sb": args.storyboard, "sc": args.script, "cfg": args.config,
                 "sb_sha": sha12(args.storyboard), "sc_sha": sha12(args.script),
                 "cfg_sha": sha12(args.config)}
    code = core_export(sb, script, cfg, art, outline, out_dir, args, argv, src_paths)
    sys.exit(code)


def cmd_init_config(args, argv):
    sb = load_json(args.storyboard, "分镜")
    script = load_json(args.script, "剧本")
    art = load_json(args.art, "美术设定") if args.art else None
    out_path = os.path.join(os.path.abspath(args.out), "scene-config.json")
    if os.path.exists(out_path) and not args.force:
        fail(3, f"{out_path} 已存在;覆盖请加 --force")
    names = build_names(sb, script, art, None)
    script_eps = {ep.get("ep"): ep for ep in (script.get("episodes") or [])}
    used = {}                      # sceneId → {"chars": set, "props": set, "empty": bool}
    for ep, seg in iter_selected_segments(sb, args):
        sid = scene_of_segment(script_eps.get(ep.get("ep"), {}), seg, seg.get("id"))
        if sid is None:
            continue
        u = used.setdefault(sid, {"chars": set(), "props": set(), "empty": False})
        for cut in seg.get("cuts") or []:
            u["chars"].update(cut.get("characters") or [])
            u["props"].update(cut.get("props") or [])
            if not cut.get("characters") and not cut.get("props"):
                u["empty"] = True

    scenes, missing = {}, []
    for sid in sorted(used):
        u = used[sid]
        anchors = {}
        for cid in sorted(u["chars"]):
            anchors[cid] = {"pos": None, "face": None, "pose": None, "height": None,
                            "lead": None, "seatZ": None}
            missing.append({"scene": sid, "item": f"scenes.{sid}.anchors.{cid}",
                            "field": "pos/face",
                            "reason": f"{names['chars'].get(cid, cid)} 的站位/朝向未填"})
        props = {}
        for pid in sorted(u["props"]):
            props[pid] = {"hand": None, "pos": None, "fallback": None, "offset": None,
                          "z": None, "shape": None, "dims": None, "mat": None,
                          "role": None, "name": names["props"].get(pid, pid)}
            missing.append({"scene": sid, "item": f"scenes.{sid}.props.{pid}",
                            "field": "hand|pos",
                            "reason": f"{names['props'].get(pid, pid)} 挂手或落点未填(dims 也要给)"})
        scene_entry = {
            "name": names["scenes"].get(sid, ""),
            "openAir": False,
            "room": None, "floor": None, "setPieces": [], "furniture": [],
            "sceneAnchor": None,
            "anchors": anchors, "props": props,
        }
        if u["empty"]:
            missing.append({"scene": sid, "item": f"scenes.{sid}.sceneAnchor",
                            "field": "pos/face", "reason": "本场景有空镜切,需要场景锚点"})
        scenes[sid] = scene_entry
        missing.append({"scene": sid, "item": f"scenes.{sid}.room",
                        "field": "room/floor",
                        "reason": "室内填 room;外景改 openAir:true 并填 floor"})

    cfg = {"version": 1, "drama": sb.get("source", ""), "defaultLens": 35,
           "approxZoom": False, "camPresets": None, "scenes": scenes, "missing": missing}
    write_text(out_path, json.dumps(cfg, ensure_ascii=False, indent=1) + "\n")
    n = len(missing)
    print(f"已生成 {out_path}")
    print(f"待补 {n} 项:")
    for m in missing:
        print(f"  - {m['item']}.{m['field']}  {m['reason']}")
    print("填写说明见 references/scene-config.md;补完跑 export。")
    sys.exit(0)


def cmd_validate(args, argv):
    sb = load_json(args.storyboard, "分镜")
    seg = None
    for ep in sb.get("episodes") or []:
        for s in ep.get("segments") or []:
            if s.get("id") == args.segment:
                seg = s
    if seg is None:
        fail(3, f"分镜里没有段 {args.segment}")
    if args.scene_py:
        path = args.scene_py
    else:
        path = os.path.join(os.path.abspath(args.out), args.segment, "scene.py")
    if not os.path.exists(path):
        fail(3, f"找不到 {path}(用 --scene-py 指路径,或先 export)")
    import io
    with io.open(path, "r", encoding="utf-8") as f:
        text = f.read()

    problems = []
    m = RE_SHOTS.search(text)
    if not m:
        fail(1, f"{path} 里抠不出 SHOTS(正则与 tools 同款)")
    try:
        got = ast.literal_eval("[" + m.group(1) + "]")
    except (ValueError, SyntaxError) as e:
        fail(1, f"SHOTS 不是纯字面量: {e}")
    want = cumulative([c.get("seconds", 0) for c in seg.get("cuts") or []])
    if len(got) != len(want):
        problems.append(f"镜数 {len(got)} ≠ 分镜 {len(want)}")
    else:
        for k, (row, (t0, t1)) in enumerate(zip(got, want), 1):
            if len(row) != 6:
                problems.append(f"f{k} 不是 6 元组")
                continue
            if row[0] != f"{args.segment}-f{k}":
                problems.append(f"f{k} 镜号 {row[0]!r} 与切序不符")
            if abs(row[2] - t0) > 5e-4 or abs(row[3] - t1) > 5e-4:
                problems.append(f"f{k} 时间 {row[2]}–{row[3]} 漂移(分镜累加 {t0:.3f}–{t1:.3f})")
    cam_keys = _extract_dict_keys(text, "CAMS") or []
    for row in got:
        if len(row) == 6 and row[1] not in cam_keys:
            problems.append(f"{row[0]} 机位 {row[1]!r} 不在 CAMS")
    fig_keys = _extract_dict_keys(text, "FIG") or []
    for row in got:
        if len(row) == 6 and row[4] not in fig_keys:
            problems.append(f"{row[0]} 人物组 {row[4]!r} 不在 FIG")
    try:
        ast.parse(text)
    except SyntaxError as e:
        problems.append(f"第 {e.lineno} 行语法错误: {e.msg}")

    if problems:
        print(f"✗ {args.segment} 漂移 {len(problems)} 处:")
        for p in problems:
            print(f"  ✗ {p}")
        sys.exit(1)
    print(f"✓ {args.segment} · {len(got)} 镜 · 时间轴及引用对账一致，不代表构图和动作已验证({path})")
    sys.exit(0)


# ─────────────────────────────── 自测 ───────────────────────────────

def _fixture(rel):
    return os.path.normpath(os.path.join(HERE, "..", "references", "test-fixtures", rel))


class T:
    def __init__(self):
        self.n_pass = 0
        self.n_fail = 0

    def check(self, name, cond, detail=""):
        if cond:
            self.n_pass += 1
            print(f"  ✓ {name}")
        else:
            self.n_fail += 1
            print(f"  ✗ {name} {detail}")


def _export_to(tmp, sb, script, cfg, extra=None):
    """内存对象直接走核心导出,返回 (退出码, 输出目录内容 dict)。"""
    import argparse as _ap
    args = _ap.Namespace(**{'ep': None, 'segment': None, 'blockout': None, **(extra or {})})
    argv = ["export", "--memory"]
    src = {"sb": "mem-storyboard.json", "sc": "mem-script.json", "cfg": "mem-config.json",
           "sb_sha": "0" * 12, "sc_sha": "0" * 12, "cfg_sha": "0" * 12}
    code = core_export(sb, script, cfg, None, None, tmp, args, argv, src)
    out = {}
    for root, _dirs, files in os.walk(tmp):
        for f in files:
            p = os.path.join(root, f)
            rel = os.path.relpath(p, tmp).replace("\\", "/")
            with open(p, "r", encoding="utf-8") as fh:
                out[rel] = fh.read()
    return code, out


def _gate_of(tmp_summary, gid):
    for g in tmp_summary:
        if g["id"] == gid:
            return g
    return None


def cmd_selftest(args, argv):
    t = T()
    print("── 夹具加载 ──")
    sb_syn = load_json(_fixture("synthetic/synthetic-storyboard.json"), "合成分镜")
    sc_syn = load_json(_fixture("synthetic/synthetic-script.json"), "合成剧本")
    cfg_syn = load_json(_fixture("synthetic/synthetic-config.json"), "合成配置")
    cfg_part = load_json(_fixture("synthetic/synthetic-config.partial.json"), "合成配置(部分)")
    t.check("夹具齐全", True)

    print("── 全枚举覆盖 + 快乐路径 ──")
    with tempfile.TemporaryDirectory() as tmp:
        code, out = _export_to(tmp, sb_syn, sc_syn, cfg_syn)
        rep = json.loads(out["_report/report.json"])
        gates = rep["gates"]
        bad = [g for g in gates if not g["ok"]]
        t.check("全部门通过", not bad, str([g["id"] for g in bad]))
        t.check("退出码 0", code == 0, f"code={code}")
        t.check("4 段全出 scene.py", all(f"E01-0{i}/scene.py" in out for i in range(1, 5)))
        used_moves = set()
        for f, text in out.items():
            if not f.endswith("scene.py"):
                continue
            m = re.search(r"^MOVES = \{(.*)\}", text, re.M)      # MOVES 恒为单行
            if m and m.group(1).strip():
                used_moves.update(re.findall(r"'([^']+)':", m.group(1)))
        degr_n = rep["summary"]["degradations"]
        # A 档 7 词:Static 无 MOVES;Push/Pull/Truck×2/Pedestal×2 = 6 个 MOVES
        t.check("A 档 6 个 MOVES", len(used_moves) == 6, f"{sorted(used_moves)}")
        # C 档 10 词全降级 + 默认关闭的 B 档 3 词 = 13
        t.check("C+B 默认降级 13", degr_n == 13, f"degr={degr_n}")

    print("── 幂等 ──")
    with tempfile.TemporaryDirectory() as tmp1, tempfile.TemporaryDirectory() as tmp2:
        _export_to(tmp1, sb_syn, sc_syn, cfg_syn)
        _export_to(tmp2, sb_syn, sc_syn, cfg_syn)
        def snap(d):
            # 只比 scene.py:report.json 嵌着输出目录绝对路径,天然随环境变
            files = ["E01-01/scene.py", "E01-02/scene.py",
                     "E01-03/scene.py", "E01-04/scene.py"]
            out = {}
            for rel in files:
                with open(os.path.join(d, rel), encoding="utf-8") as fh:
                    out[rel] = fh.read()
            return out
        t.check("两跑字节一致", snap(tmp1) == snap(tmp2))

    print("── geo-reuse 正例 ──")
    with tempfile.TemporaryDirectory() as tmp:
        _export_to(tmp, sb_syn, sc_syn, cfg_syn)
        def geo(rel):
            m = re.search(r"# ── 场景几何 (\S+) 开始 ──\n(.*?)# ── 场景几何 结束 ──",
                          open(os.path.join(tmp, rel), encoding="utf-8").read(), re.S)
            return m.group(2) if m else None
        t.check("SY1 三段几何一致",
                geo("E01-01/scene.py") == geo("E01-02/scene.py") == geo("E01-03/scene.py"))

    print("── 逐门击穿 ──")
    def break_gate(name, mutate_sb=None, mutate_cfg=None, expect="✗"):
        with tempfile.TemporaryDirectory() as tmp:
            sb = copy.deepcopy(sb_syn)
            cfg = copy.deepcopy(cfg_syn)
            if mutate_sb:
                res = mutate_sb(sb)
                sb = res if isinstance(res, dict) else sb
            if mutate_cfg:
                res = mutate_cfg(cfg)
                cfg = res if isinstance(res, dict) else cfg
            _, out = _export_to(tmp, sb, sc_syn, cfg)
            rep = json.loads(out["_report/report.json"])
            g = _gate_of(rep["gates"], name)
            t.check(f"击穿 {name}", g is not None and not g["ok"],
                    f"detail={g['detail'] if g else 'missing'}")

    break_gate("seg-seq", mutate_sb=lambda sb: sb["episodes"][0]["segments"][1].__setitem__("id", "E01-09"))
    break_gate("cut-seconds", mutate_sb=lambda sb: sb["episodes"][0]["segments"][0]["cuts"][0].__setitem__("seconds", 6))
    break_gate("seg-cap", mutate_sb=lambda sb: [c.__setitem__("seconds", 5) for c in sb["episodes"][0]["segments"][0]["cuts"]])
    break_gate("cam-enum", mutate_sb=lambda sb: sb["episodes"][0]["segments"][0]["cuts"][0].__setitem__("camera", "Crash Zoom"))
    break_gate("join-scene", mutate_sb=lambda sb: sb["episodes"][0]["segments"][0].__setitem__("sceneIndex", 99))
    break_gate("join-cast", mutate_sb=lambda sb: sb["episodes"][0]["segments"][0]["cuts"][0]["characters"].append("K99"))
    break_gate("pose-valid", mutate_cfg=lambda c: c["scenes"]["SY1"]["anchors"]["K01"].__setitem__("pose", "sit_cross"))
    break_gate("seat-z", mutate_cfg=lambda c: [c["scenes"]["SY1"]["anchors"]["K02"].__setitem__(k, v) for k, v in
                                               (("pose", "sit"), ("seatZ", None))])
    break_gate("furniture-args", mutate_cfg=lambda c: c["scenes"]["SY1"]["furniture"][0].__setitem__("kind", "sofa"))
    break_gate('prop-attach', mutate_cfg=lambda c: c['scenes']['SY1']['props']['Q01'].__setitem__('hand', 'K01:invalid'))
    break_gate("preset-valid", mutate_cfg=lambda c: c.__setitem__("camPresets", {"macro": {"dist": 1}}))

    # frames-24:直接构造 0.02s 切(会被 cut-seconds 先拦,所以手工调 params 放宽)
    def frames_break(sb):
        sb["params"] = {"minCutSeconds": 0.01, "maxCutSeconds": 5, "maxSegmentSeconds": 15}
        for c in sb["episodes"][0]["segments"][0]["cuts"]:
            c["seconds"] = 0.02
        return sb
    break_gate("frames-24", mutate_sb=frames_break)

    # lens-parse:去掉 defaultLens 且造一个解析不出的 lens
    def lens_break(sb):
        sb["episodes"][0]["segments"][0]["cuts"][0]["lens"] = "变焦"
        return sb
    with tempfile.TemporaryDirectory() as tmp:
        sb = lens_break(copy.deepcopy(sb_syn))
        cfg = copy.deepcopy(cfg_syn)
        _, out = _export_to(tmp, sb, sc_syn, cfg)
        rep = json.loads(out["_report/report.json"])
        g = _gate_of(rep["gates"], "lens-parse")
        t.check("lens-parse 兜底计 ⚠", g["ok"] and g["warn"], g["detail"])
        cfg.pop("defaultLens")
        _, out = _export_to(tmp, sb, sc_syn, cfg)
        rep = json.loads(out["_report/report.json"])
        g = _gate_of(rep["gates"], "lens-parse")
        t.check("击穿 lens-parse(无兜底)", not g["ok"], g["detail"])

    # geo-reuse:两段同场景几何不同 → 手工改一份配置里 SY1 的 room 再跑(同 config 不可能不一致,
    # 所以直接验证 emit 的标记存在 + 手改生成物后 geo 不再可比——用语法门替代路径)
    # 这里改为验证标记存在:
    with tempfile.TemporaryDirectory() as tmp:
        _, out = _export_to(tmp, sb_syn, sc_syn, cfg_syn)
        t.check("几何标记存在", "# ── 场景几何 SY1 开始 ──" in out["E01-01/scene.py"])

    # cams/fig closure + roundtrip + syntax:改生成物验证 validate 与门
    with tempfile.TemporaryDirectory() as tmp:
        _export_to(tmp, sb_syn, sc_syn, cfg_syn)
        p = os.path.join(tmp, "E01-01", "scene.py")
        text = open(p, encoding="utf-8").read()
        bad_cam = text.replace("'S2_特写'", "'S2_特写X'", 1)
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write(bad_cam)
        argv_v = ["validate", "--storyboard", _fixture("synthetic/synthetic-storyboard.json"),
                  "--segment", "E01-01", "--scene-py", p]
        r = _run_cli(argv_v)
        t.check("validate 抓机位漂移", r == 1, f"rc={r}")

    with tempfile.TemporaryDirectory() as tmp:
        _export_to(tmp, sb_syn, sc_syn, cfg_syn)
        p = os.path.join(tmp, "E01-01", "scene.py")
        text = open(p, encoding="utf-8").read()
        m = re.search(r"\('E01-01-f1'.*?\),", text)
        shifted = text.replace(m.group(0), m.group(0).replace(", 2.0,", ", 2.5,"), 1)
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write(shifted)
        argv_v = ["validate", "--storyboard", _fixture("synthetic/synthetic-storyboard.json"),
                  "--segment", "E01-01", "--scene-py", p]
        r = _run_cli(argv_v)
        t.check("validate 抓时间漂移", r == 1, f"rc={r}")

    with tempfile.TemporaryDirectory() as tmp:
        _export_to(tmp, sb_syn, sc_syn, cfg_syn)
        p = os.path.join(tmp, "E01-01", "scene.py")
        text = open(p, encoding="utf-8").read()
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write(text + "\nthis is ( not python")
        argv_v = ["validate", "--storyboard", _fixture("synthetic/synthetic-storyboard.json"),
                  "--segment", "E01-01", "--scene-py", p]
        r = _run_cli(argv_v)
        t.check("validate 抓语法漂移", r == 1, f"rc={r}")

    print("── 部分配置 → .todo + exit 2 ──")
    with tempfile.TemporaryDirectory() as tmp:
        code, out = _export_to(tmp, sb_syn, sc_syn, cfg_part)
        t.check("退出码 2", code == 2, f"code={code}")
        t.check("SY2 段出 .todo", "E01-04/scene.py.todo" in out)
        t.check("SY1 段照常出 scene.py", "E01-01/scene.py" in out)

    print("── 空镜 / 道具特写 / 挂手 ──")
    with tempfile.TemporaryDirectory() as tmp:
        _, out = _export_to(tmp, sb_syn, sc_syn, cfg_syn)
        s3 = out["E01-03/scene.py"]
        t.check('空镜组 FIG["_"]', '"_": [],' in s3)
        t.check("空镜走 sceneAnchor", "S6_大远景" in s3)
        s1 = out["E01-01/scene.py"]
        t.check("挂手道具走 human.hand", "Q01_H = human.hand(" in s1)
        t.check("挂手道具带 fallback", "if Q01_H else" in s1)
        t.check("道具特写机位引用运行期 POS", "Q01_POS[0] + " in s1)
        t.check("跨组角色 tag 唯一", "'K01_g2'" in out["E01-02/scene.py"] or "'K01_g2'" in s1)

    print("── 20 运镜 × 5 景别覆盖 ──")
    seen_cams, seen_sizes = set(), set()
    for _ep, _seg, _k, cut in _all_cuts(sb_syn):
        seen_cams.add(cut.get("camera"))
        seen_sizes.add(cut.get("size"))
    t.check("20 运镜全覆盖", len(seen_cams) == 20, str(20 - len(seen_cams)))
    t.check("5 景别全覆盖", seen_sizes == set(SIZE_ZH), str(seen_sizes))

    print("── init-config ──")
    with tempfile.TemporaryDirectory() as tmp:
        argv_i = ["init-config", "--storyboard", _fixture("synthetic/synthetic-storyboard.json"),
                  "--script", _fixture("synthetic/synthetic-script.json"), "--out", tmp]
        r = _run_cli(argv_i)
        t.check("init 退出 0", r == 0)
        cfg_path = os.path.join(tmp, "scene-config.json")
        cfg0 = json.load(open(cfg_path, encoding="utf-8"))
        t.check("两个场景骨架", set(cfg0["scenes"]) == {"SY1", "SY2"})
        t.check("锚点键齐", set(cfg0["scenes"]["SY1"]["anchors"]) == {"K01", "K02"})
        t.check("缺项非空", len(cfg0["missing"]) > 0)
        r2 = _run_cli(argv_i)
        t.check("拒绝覆盖", r2 == 3, f"rc={r2}")

    print("── 与 harness 的同步检查 ──")
    human_py = os.path.normpath(os.path.join(HERE, "..", "..", "greybox-harness", "blockout", "human.py"))
    verify_py = os.path.normpath(os.path.join(HERE, "..", "..", "greybox-harness", "tools", "verify_cuts.py"))
    if os.path.exists(human_py):
        import io
        tree = ast.parse(io.open(human_py, encoding="utf-8").read())
        poses = None
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "POSES" for t in node.targets) \
                    and isinstance(node.value, ast.Dict):
                # 值是 _p(...) 调用求不了值,只取键(姿态名)
                poses = {k.value for k in node.value.keys if isinstance(k, ast.Constant)}
        if poses is not None:
            t.check("POSES 与 human.py 同步", poses == set(POSES),
                    str(poses ^ set(POSES)) if poses != set(POSES) else "")
        else:
            print("  ! POSES 结构变化,请人工核对(human.py 没抠到 dict)")
    else:
        print("  ! 找不到 greybox-harness,跳过 POSES 同步检查")
    if os.path.exists(verify_py):
        import io
        src = io.open(verify_py, encoding="utf-8").read()
        t.check("SHOTS 正则与 verify_cuts 同步", RE_SHOTS_STR in src)
    else:
        print("  ! 找不到 verify_cuts.py,跳过正则同步检查")

    print("── 上游真实夹具(渡口 ep1) ──")
    sb_dk = load_json(_fixture("upstream/渡口-storyboard.json"), "渡口分镜")
    sc_dk = load_json(_fixture("upstream/渡口-script.json"), "渡口剧本")
    with tempfile.TemporaryDirectory() as tmp:
        cfg_dk = load_json(_fixture("upstream/渡口-scene-config.json"), "渡口配置")
        code, out = _export_to(tmp, sb_dk, sc_dk, cfg_dk)
        rep = json.loads(out["_report/report.json"])
        bad = [g["id"] for g in rep["gates"] if not g["ok"]]
        t.check("渡口 10 段全绿", code == 0 and not bad, f"code={code} bad={bad}")
        t.check("10 个 scene.py", sum(1 for f in out if f.endswith("/scene.py")) == 10)

    from analysis_tests import run_analysis_tests
    run_analysis_tests(sys.modules[__name__], t)

    from grid_tests import run_grid_tests
    run_grid_tests(sys.modules[__name__], t)

    from regression_tests import run_regressions
    run_regressions(sys.modules[__name__], t, getattr(args, 'blender', None))

    print(f"\n自测：{t.n_pass} 通过 · {t.n_fail} 失败")
    sys.exit(1 if t.n_fail else 0)


def _run_cli(argv):
    """子进程跑 CLI,拿真实退出码。"""
    import subprocess
    exe = sys.executable or "python3"
    r = subprocess.run([exe, "-X", "utf8", os.path.abspath(__file__)] + argv,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode


# ─────────────────────────────── 入口 ───────────────────────────────

class _Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_help(sys.stderr)
        fail(3, f"参数错误: {message}")


def build_parser():
    p = _Parser(prog="storyboard_to_shots.py",
                description='预演方式分析，以及分镜到白模场景的确定性转换')
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser('analyze', help='分析白模或宫格需求，并列出已有关键帧复核提示；不触发生成')
    sp.add_argument('--storyboard', required=True, help='已确认分镜 JSON')
    sp.add_argument('--out', required=True, help='输出 _analysis/analysis.json 和 analysis.md')
    sp.add_argument('--ep', type=int)
    sp.add_argument('--segment')
    sp.set_defaults(fn=cmd_analyze)

    sp = sub.add_parser('export-grid', help='依据原分镜与可选图片，导出锁定分镜宫格提示词')
    sp.add_argument('--storyboard', required=True)
    sp.add_argument('--frames', help='可选关键帧目录，文件名为 E01-01-f1.png 等；省略时依据分镜描述导出')
    sp.add_argument('--out', required=True)
    sp.add_argument('--ep', type=int)
    sp.add_argument('--segment', help='明确指定段号时覆盖方式初筛，但仍要求至少两个镜头')
    sp.add_argument('--aspect', choices=('source', '16:9', '9:16', '1:1'), default='source')
    sp.add_argument('--builder', help='可选的 storyboard-builder 技能目录；缺省自动查找并可使用内化模板')
    sp.set_defaults(fn=cmd_export_grid)

    sp = sub.add_parser("init-config", help="从分镜+剧本生成待填场景配置骨架")
    sp.add_argument("--storyboard", required=True, help="storyboard.json 路径")
    sp.add_argument("--script", required=True, help="script.json 路径")
    sp.add_argument("--art", help="art.json(可选,带场景/道具名)")
    sp.add_argument("--out", required=True, help="输出目录(生成 scene-config.json)")
    sp.add_argument("--force", action="store_true", help="覆盖已有配置")
    sp.add_argument("--ep", type=int, help="只处理某一集")
    sp.add_argument("--segment", help="只处理某一段")
    sp.set_defaults(fn=cmd_init_config)

    sp = sub.add_parser("export", help="按段生成 scene.py + 对账报告")
    sp.add_argument("--storyboard", required=True)
    sp.add_argument("--script", required=True)
    sp.add_argument("--config", required=True)
    sp.add_argument("--art")
    sp.add_argument("--outline")
    sp.add_argument("--out", required=True)
    sp.add_argument("--ep", type=int)
    sp.add_argument("--segment")
    sp.add_argument("--blockout", help="greybox-harness/blockout 路径(默认自动探测)")
    sp.set_defaults(fn=cmd_export)

    sp = sub.add_parser("validate", help="复检生成物是否仍与分镜对账(人改后用)")
    sp.add_argument("--storyboard", required=True)
    sp.add_argument("--segment", required=True)
    sp.add_argument("--scene-py", help="scene.py 路径")
    sp.add_argument("--out", help="export 输出目录(默认从中找 <段号>/scene.py)")
    sp.set_defaults(fn=cmd_validate)

    sp = sub.add_parser("selftest", help="自测(不调模型,不花额度)")
    sp.add_argument('--blender', metavar='EXECUTABLE', help='额外执行 Blender 场景构建、构图计算和审片静帧测试')
    sp.set_defaults(fn=cmd_selftest)
    return p


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    args = parser.parse_args(argv)
    args.fn(args, argv)


if __name__ == "__main__":
    main()
