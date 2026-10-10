"""独立站位宫格扩展的源数据交接；仅检查材料齐备，不证明连续性。"""
import re


def make_planning(segment):
    sid = segment['id']
    missing = []

    def required(value, location):
        if not isinstance(value, str) or not value.strip():
            missing.append(f'{location} 缺失，先回到分镜补齐空间与逐镜动作安排')
            return ''
        return value

    opening = required(segment.get('blocking'), f'{sid} blocking 开场空间关系')
    shots = []
    for index, cut in enumerate(segment['cuts'], 1):
        shot = f'{sid}-f{index}'
        view = {key: required(cut.get(field), f'{shot} {field}') for key, field in
                (('position', 'cameraPosition'), ('composition', 'composition'), ('eyeline', 'eyeline'))}
        note = required(cut.get('note'), f'{shot} cut.note 承接安排')
        if note:
            labels = list(re.finditer(r'(起始|动作|结束|接镜)\s*[:：]', note))
            supplied = {match[1] for i, match in enumerate(labels)
                        if note[match.end():labels[i + 1].start() if i + 1 < len(labels) else len(note)]
                        .strip(' \t\r\n；;。')}
            absent = [label for label in ('起始', '动作', '结束', '接镜') if label not in supplied]
            if absent:
                missing.append(f'{shot} cut.note 缺少非空的 {"、".join(absent)} 说明；标签齐全也仍需语义复核')
        shots.append({'shot': shot, 'view': view, 'continuity': note,
                      'action': required(cut.get('shot'), f'{shot} shot 视频动作正文')})
    return {'opening': opening, 'shots': shots}, missing


def prompt_values(planning):
    descriptions = []
    for shot in planning['shots']:
        view = shot['view']
        descriptions.append(
            f"{shot['shot']}\n"
            f"Camera position: {view['position']}\n"
            f"Composition: {view['composition']}\n"
            f"Eyeline: {view['eyeline']}\n"
            f"Continuity plan (start / action / end / transition): {shot['continuity']}\n"
            f"Video action, for path annotations only, not the still-panel state: {shot['action']}")
    return {'opening': planning['opening'], 'spatial_shots': '\n\n'.join(descriptions)}
