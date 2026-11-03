"""调度人偶与路径约定；复用 blocking 文本，不扩展分镜或交接包结构。"""
import re


CAST_HEADER = '【调度人偶对应】'
PATH_HEADER = '【调度路径参考】'
USE_HEADER = '【调度参考用途】'
NO_CAST = '本段无人出场。'
NO_PATH = '本段无人物位移。'
USE_TEXT = ('本段附有调度宫格时，按上述颜色人偶对应实际角色，参考相应镜号的站位、朝向和人物移动路径完成调度；'
            '路径只在对应镜头发生，已完成的移动不重演。人偶颜色仅用于识别角色，'
            '实际人物的脸、服装和外貌沿用角色设定；图中箭头、标签及宫格边框不进入成片。'
            '尚未提交该图时，以本段文字调度为准，不声称已参考图片。')


def base_opening(opening):
    """调度约定追加在原开场关系之后，原场景及 staging 文字保持原样。"""
    return opening.split(CAST_HEADER, 1)[0].rstrip()


def read_dispatch(opening, shot_ids=None):
    if not isinstance(opening, str):
        return [], '', ['缺少 blocking 中的调度人偶对应与路径参考']
    if opening.count(CAST_HEADER) != 1 or opening.count(PATH_HEADER) != 1:
        return [], '', ['blocking 需要唯一的【调度人偶对应】与【调度路径参考】，先写回正式分镜']
    before, cast = opening.split(CAST_HEADER, 1)
    if PATH_HEADER not in cast or PATH_HEADER in before:
        return [], '', ['调度人偶对应必须在调度路径参考之前']
    cast, routes = cast.split(PATH_HEADER, 1)
    routes = routes.split(USE_HEADER, 1)[0].strip()
    bindings, missing, ids, colors = [], [], set(), set()
    if cast.strip() != NO_CAST:
        for line in cast.strip().splitlines():
            match = re.fullmatch(r'\s*[-*]\s+(C[0-9]+)\s+([^：:\n]+?)\s*[：:]\s*([\u4e00-\u9fff]+色)人偶[。.]?\s*', line)
            if not match:
                missing.append('人偶对应每行应为“- C01 角色名：蓝色人偶”，颜色使用中文色名')
                continue
            identity, name, color = match.groups()
            if identity in ids or color in colors:
                missing.append('同一段每个角色只能对应一种颜色，不同角色不能共用颜色')
            ids.add(identity)
            colors.add(color)
            bindings.append((identity, name.strip(), color))
        if not bindings:
            missing.append('调度人偶对应不能为空；无人段写“本段无人出场。”')
    if not routes:
        missing.append('调度路径参考不能为空；没有人物位移时明确写“本段无人物位移。”')
    elif shot_ids is not None and routes != NO_PATH:
        supplied = set(re.findall(r'E[0-9]{2,}-[0-9]{2,}-f[0-9]+', routes))
        if supplied != set(shot_ids):
            missing.append('调度路径参考需按本段原镜号逐镜说明移动或保持，不引用其他段的路径')
    return bindings, routes, list(dict.fromkeys(missing))


def with_dispatch_use(opening):
    """统一用途说明，更新时替换旧说明，避免重复追加。"""
    return opening.split(USE_HEADER, 1)[0].rstrip() + '\n' + USE_HEADER + '\n' + USE_TEXT


def check_characters(segment, bindings):
    expected = {identity for cut in segment['cuts'] for identity in cut.get('characters', [])}
    covered = {identity for identity, _, _ in bindings}
    absent = sorted(expected - covered)
    return ['调度人偶对应缺少分镜角色：' + '、'.join(absent)] if absent else []


def check_consistency(board, selected, opening):
    """写回时检查已有角色的颜色，不根据角色外貌或服装推断颜色。"""
    bindings, _, missing = read_dispatch(opening)
    if missing:
        raise ValueError('；'.join(missing))
    by_id = {identity: (name, color) for identity, name, color in bindings}
    by_color = {color: identity for identity, _, color in bindings}
    for episode in board['episodes']:
        for segment in episode['segments']:
            if segment is selected or CAST_HEADER not in segment.get('blocking', ''):
                continue
            previous, _, problems = read_dispatch(segment['blocking'])
            if problems:
                raise ValueError(f"{segment['id']} 已有调度对应待修正：" + '；'.join(problems))
            for identity, name, color in previous:
                if identity in by_id and by_id[identity] != (name, color):
                    raise ValueError(f'{identity} 的角色名或人偶颜色与其他段不一致')
                if color in by_color and by_color[color] != identity:
                    raise ValueError(f'{color}人偶已在其他段代表不同角色')
