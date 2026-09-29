"""预演方式初筛：只分析分镜，不修改时间轴，也不触发渲染或出图。"""
import math
import re


METHOD_LABELS = {
    'greybox': '白模预演',
    'grid': '宫格预览',
    'none': '不额外预演',
}
SCOPE_LABELS = {**METHOD_LABELS, 'review': '已有关键帧复核'}

SPATIAL_MOVES = {'Truck Left', 'Truck Right', 'Pedestal Up', 'Pedestal Down',
                 'Arc Shot', 'Tracking Shot', 'POV'}
SPATIAL_CUES = ('遮挡', '挡住', '穿过', '绕过', '绕到', '越轴', '视线交叉',
                '从左向右', '从右向左', '左右穿插', '前后交错', '过肩')
DETAIL_CUES = ('微表情', '眼神', '泪水', '眼泪', '嘴角', '字迹', '签名', '印章',
               '伤口', '指尖', '戒指', '身份揭示', '首次亮相', '铭牌', '编号')
ACTION_CUES = ('交接', '递给', '接过', '松手', '放下', '拿起', '转身', '走到',
               '跑向', '起身', '坐下', '追逐', '打斗', '搏斗', '翻滚')
SEQUENCE_CUES = ('正反打', '反应', '揭示', '发现', '对视', '交接')
TEXT_FIELDS = ('frame', 'shot', 'note', 'cameraPosition', 'composition', 'focus')

LIMITATIONS = [
    '这是结构与有限文字线索的规则初筛，不是完整剧情理解；有歧义或漏识别时需要人工复核。',
    '选择方式不等于执行：分析不生成图片、不启动 Blender、不调用模型，也不覆盖正式分镜。',
    '白模检查空间与机位，当前适配器不会自动还原文字中的精确构图、复杂动作或道具交接。',
    '宫格检查画面顺序和视觉衔接，已有单张关键帧用于复核局部画面；两者都不能证明动作连续或真实播放节奏。',
    '格数按实际检查范围确定，原镜号和时长保持不变；预演宫格不能直接替换正式独立关键帧。',
]


def text_of(cut):
    return '；'.join(value for field in TEXT_FIELDS
                    if isinstance((value := cut.get(field)), str) and value.strip())


def cue_hits(text, terms):
    # 只排除紧邻关键词的简单否定，不声称完成了自然语言语义判定。
    hits = []
    for term in terms:
        for match in re.finditer(re.escape(term), text):
            prefix = text[max(0, match.start() - 12):match.start()]
            if not re.search(r'(?:没有|无需|无须|避免|禁止|不要|并未|并不|不可|不能|不|无|未)(?:发生|出现|被|任何|再|再度)?\s*$', prefix):
                hits.append(term)
                break
    return hits


def selected_segments(storyboard, ep=None, segment=None):
    if not isinstance(storyboard, dict) or not isinstance(storyboard.get('episodes'), list):
        raise ValueError('分镜必须包含 episodes 数组')
    result, seen = [], set()
    for episode in storyboard['episodes']:
        if not isinstance(episode, dict) or not isinstance(episode.get('segments'), list):
            raise ValueError('每集必须包含 segments 数组')
        if ep is not None and episode.get('ep') != ep:
            continue
        for item in episode['segments']:
            if not isinstance(item, dict):
                raise ValueError('分镜段必须是对象')
            sid = item.get('id')
            if segment is not None and sid != segment:
                continue
            if not isinstance(sid, str) or not sid.strip() or sid in seen:
                raise ValueError('所选段号必须是非空且不重复的字符串')
            seen.add(sid)
            cuts = item.get('cuts')
            if not isinstance(cuts, list) or not cuts:
                raise ValueError(f'{sid} 必须至少包含一个分镜')
            for index, cut in enumerate(cuts, 1):
                if not isinstance(cut, dict):
                    raise ValueError(f'{sid}-f{index} 必须是对象')
                seconds = cut.get('seconds')
                if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or seconds <= 0:
                    raise ValueError(f'{sid}-f{index} seconds 必须是正的有限数值')
                for field in ('characters', 'props'):
                    values = cut.get(field, [])
                    if not isinstance(values, list) or any(not isinstance(v, str) for v in values):
                        raise ValueError(f'{sid}-f{index} {field} 必须是字符串数组')
                for field in ('camera', 'size', *TEXT_FIELDS):
                    if cut.get(field) is not None and not isinstance(cut[field], str):
                        raise ValueError(f'{sid}-f{index} {field} 必须是字符串')
            result.append(item)
    if not result:
        raise ValueError('没有匹配的分镜段，请检查 --ep / --segment')
    return result


def analyze_segment(segment, move_table):
    sid = segment['id']
    cuts = segment['cuts']
    scope = {'greybox': [], 'grid': [], 'review': []}
    reasons, limits = [], []
    ids = [f'{sid}-f{i}' for i in range(1, len(cuts) + 1)]
    scene_text = segment.get('blocking') or ''
    if not isinstance(scene_text, str):
        raise ValueError(f'{sid} blocking 必须是字符串')
    spatial = cue_hits(scene_text, SPATIAL_CUES)
    scene_actions = cue_hits(scene_text, ACTION_CUES)
    actions = scene_actions[:]
    if spatial:
        scope['greybox'].extend(ids)
        reasons.append('段级站位包含空间检查线索：' + '、'.join(spatial) + '。')
    signatures = set()
    sequence = []
    for cut, shot_id in zip(cuts, ids):
        text = text_of(cut)
        camera = cut.get('camera')
        chars = cut.get('characters', [])
        signatures.add((cut.get('size'), tuple(sorted(set(chars))), cut.get('cameraPosition')))
        geometry = cue_hits(text, SPATIAL_CUES)
        detail = cue_hits(text, DETAIL_CUES)
        action = cue_hits(text, ACTION_CUES)
        sequence.extend(cue_hits(text, SEQUENCE_CUES))
        actions.extend(action)
        if camera in SPATIAL_MOVES or geometry or len(set(chars)) >= 3:
            scope['greybox'].append(shot_id)
            clues = geometry + ([f'运镜 {camera}'] if camera in SPATIAL_MOVES else [])
            if len(set(chars)) >= 3:
                clues.append(f'{len(set(chars))} 人同框')
            reasons.append(f'{shot_id}：' + '、'.join(clues) + '；优先检查空间、机位和遮挡。')
        if detail or cut.get('size') == 'extreme-close' or (cut.get('size') == 'close' and cut.get('props')):
            scope['review'].append(shot_id)
            clues = detail or ['道具特写或大特写']
            reasons.append(f'{shot_id}：' + '、'.join(clues) + '；复核已有关键帧的细节，发现问题退回原分镜修正，不新增关键帧预演。')
        if (action or scene_actions) and len(cuts) == 1:
            scope['review'].append(shot_id)
            reasons.append(f'{shot_id}：复核已有切点画面；动作过程另行检查，不重复生成关键帧。')
        if not camera or not cut.get('size'):
            limits.append(f'{shot_id} 缺少运镜或景别，方式初筛依据不完整。')
        elif camera not in move_table:
            limits.append(f'{shot_id} 运镜 {camera} 不在白模映射表中，不得直接承诺执行。')
    if len(cuts) > 1 and (len(signatures) > 1 or sequence or actions):
        scope['grid'] = ids[:]
        reasons.append('多个镜头存在景别、主体、机位变化或动作/反应线索；并排检查镜头顺序与画面承接。')
    for method in scope:
        scope[method] = [shot_id for shot_id in ids if shot_id in scope[method]]
    if scope['greybox']:
        limits.append('白模需要首次场景配置；文字中的站位和具体机位仍需核对，不会由初筛自动变成坐标。')
        for cut, shot_id in zip(cuts, ids):
            camera = cut.get('camera')
            if shot_id in scope['greybox'] and camera in move_table and move_table[camera][0] != 'A':
                limits.append(f'{shot_id} 的 {camera} 在当前白模适配中会降级或近似，不能据此验证完整运镜。')
    if actions:
        limits.append('动作线索：' + '、'.join(dict.fromkeys(actions)) + '。当前白模适配不自动生成这些动作，宫格也只能展示关键状态；动作连续性需要另行复核。')
    if scope['grid'] and scope['greybox']:
        limits.append('空间检查可以先白模、后抽帧拼宫格；若检查角色外观与视觉效果，可以依据原分镜描述生成宫格提示词，已有关键帧图片仅作为可选参考，不另建独立关键帧预演。')
    scope = {method: values for method, values in scope.items() if values}
    methods = [method for method in scope if method != 'review'] or ['none']
    if methods == ['none']:
        reasons.append('当前字段未触发额外白模或宫格需求；已有关键帧的复核提示不属于新增预演，也不代表镜头已经验证无误。')
    return {'segment': sid, 'methods': methods, 'reasons': reasons, 'scope': scope, 'limits': limits}


def analyze_storyboard(storyboard, move_table, ep=None, segment=None):
    return {'segments': [analyze_segment(item, move_table)
                         for item in selected_segments(storyboard, ep, segment)],
            'limitations': LIMITATIONS[:]}


def markdown_report(report):
    lines = ['# 预演方式分析', '', '**规则初筛建议，不等于已执行或已验证。**', '']
    for item in report['segments']:
        methods = ' + '.join(METHOD_LABELS[m] for m in item['methods'])
        lines.extend([f"## {item['segment']}：{methods}", '', '### 检查范围', ''])
        for method, shots in item['scope'].items():
            lines.append(f'- {SCOPE_LABELS[method]}：' + '、'.join(shots))
        if not item['scope']:
            lines.append('- 不新增预演材料，继续原分镜流程。')
        lines.extend(['', '### 判断依据', ''])
        lines.extend('- ' + reason for reason in item['reasons'])
        if item['limits']:
            lines.extend(['', '### 注意事项', ''])
            lines.extend('- ' + limit for limit in item['limits'])
        lines.extend(['', '### 后续处理', ''])
        if 'greybox' in item['methods']:
            lines.append('- 白模：准备场景配置，再运行 init-config / export；仍按整段导出，scope 仅表示重点检查镜头；先审查静帧，确认后才渲染视频。')
        if 'grid' in item['methods']:
            lines.append('- 宫格：运行 export-grid，依据原分镜画面描述导出 storyboard-builder 锁定分镜模式的完整提示词与交接包；已有图片可通过 --frames 附加，没有图片也能导出，不会重新拆镜。')
        if item['scope'].get('review'):
            lines.append('- 已有关键帧：只复核报告列出的原画面；有问题退回分镜环节修正，不新建预演图片。')
        if item['methods'] == ['none']:
            lines.append('- 暂不额外预演；出现明确疑点时，再指定相应检查。')
        lines.append('')
    lines.extend(['## 全局边界', ''])
    lines.extend('- ' + limitation for limitation in report['limitations'])
    return '\n'.join(lines) + '\n'
