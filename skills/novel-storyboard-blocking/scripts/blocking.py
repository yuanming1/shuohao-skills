#!/usr/bin/env python3
"""独立的站位宫格导出器：读取现有分镜或交接包，不改写输入，不调用模型。"""
import argparse
from decimal import Decimal, InvalidOperation
import json
import math
from pathlib import Path
import re
from string import Template
import sys

from planning import make_planning, prompt_values


HERE = Path(__file__).resolve().parent
MODE = 'locked-blocking-grid'
ASPECTS = ('source', '16:9', '9:16', '1:1')
SIZES = {'extreme-wide': 'EXTREME WIDE', 'wide': 'WIDE', 'medium': 'MEDIUM',
         'close': 'CLOSE', 'extreme-close': 'EXTREME CLOSE'}
SUFFIXES = {'.png', '.jpg', '.jpeg', '.webp'}
FILES = ('grid-input.json', 'grid-prompt.txt', 'grid-brief.md', 'grid.todo')


def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def seconds(value):
    if isinstance(value, bool):
        raise ValueError('秒数不能是布尔值')
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f'无效秒数：{value!r}') from exc
    if not result.is_finite():
        raise ValueError('秒数必须有限')
    return result


def timecode(value):
    value = seconds(value)
    minutes = int(value // 60)
    integer, _, fraction = format(value - minutes * 60, 'f').partition('.')
    return f'{minutes:02d}:{int(integer):02d}.' + fraction.ljust(3, '0')


def check_id(sid):
    if not isinstance(sid, str) or not re.fullmatch(r'E[0-9]{2,}-[0-9]{2,}', sid):
        raise ValueError(f'无效段号：{sid!r}')
    return sid


def selected_segments(board, ep=None, segment=None):
    if not isinstance(board, dict) or not isinstance(board.get('episodes'), list):
        raise ValueError('分镜需要 episodes 数组；格式变化时先更新本扩展的输入适配')
    selected, seen = [], set()
    for episode in board['episodes']:
        for item in episode['segments']:
            sid = check_id(item.get('id'))
            if sid in seen:
                raise ValueError(f'重复段号：{sid}')
            seen.add(sid)
            if (ep is None or episode['ep'] == ep) and (segment is None or sid == segment):
                selected.append(item)
    if not selected:
        raise ValueError('没有匹配的分段')
    return selected


def locate_frame(root, sid, index):
    if root is None:
        return None, None
    shot = f'{sid}-f{index}'
    matches = set()
    for directory, names in ((root, {shot}), (root / sid, {shot, f'f{index}'})):
        if directory.is_dir():
            matches.update(path.resolve() for path in directory.iterdir()
                           if path.is_file() and path.stem in names and path.suffix.lower() in SUFFIXES)
    if len(matches) > 1:
        return None, f'{shot} 匹配到多个参考图版本，请指定唯一版本'
    if not matches:
        return None, None
    path = next(iter(matches))
    if path.stat().st_size == 0:
        return None, f'{shot} 参考图片为空文件'
    return str(path), None


def make_package(segment, frames=None, aspect='source'):
    sid = check_id(segment.get('id'))
    cuts = segment.get('cuts')
    if not isinstance(cuts, list) or not cuts:
        raise ValueError(f'{sid} 缺少非空 cuts 数组')
    planning, missing = make_planning(segment)
    panels, current = [], Decimal(0)
    for index, cut in enumerate(cuts, 1):
        duration = seconds(cut.get('seconds'))
        if duration <= 0:
            raise ValueError(f'{sid}-f{index} 时长必须大于零')
        reference, problem = locate_frame(frames, sid, index)
        if problem:
            missing.append(problem)
        end = current + duration
        panels.append({'shot': f'{sid}-f{index}', 'time': [str(current), str(end)],
                       'size': cut.get('size'), 'frame': cut.get('frame'), 'reference': reference})
        current = end
    columns = min(4, math.ceil(math.sqrt(len(panels))))
    package = {'mode': MODE, 'segment': sid,
               'layout': {'columns': columns, 'rows': math.ceil(len(panels) / columns), 'aspect': aspect},
               'panels': panels, 'planning': planning}
    missing.extend(validate_package(package))
    return package, list(dict.fromkeys(missing))


def five_fields(value):
    if isinstance(value, dict):
        return len(value) <= 5 and all(five_fields(item) for item in value.values())
    if isinstance(value, list):
        return all(five_fields(item) for item in value)
    return True


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def validate_package(package):
    if not isinstance(package, dict) or package.get('mode') != MODE:
        raise ValueError(f'交接包 mode 必须为 {MODE}')
    if set(package) != {'mode', 'segment', 'layout', 'panels', 'planning'} or not five_fields(package):
        raise ValueError('交接包字段不符合五字段契约')
    sid = check_id(package['segment'])
    panels, planning, layout = package['panels'], package['planning'], package['layout']
    if not isinstance(panels, list) or not panels:
        raise ValueError('交接包需要非空 panels')
    columns = min(4, math.ceil(math.sqrt(len(panels))))
    if layout != {'columns': columns, 'rows': math.ceil(len(panels) / columns), 'aspect': layout.get('aspect')} or layout.get('aspect') not in ASPECTS:
        raise ValueError('宫格布局必须与原镜头数量及支持的画幅一致')
    if not isinstance(planning, dict) or set(planning) != {'opening', 'shots'} or not isinstance(planning['shots'], list):
        raise ValueError('planning 需要 opening 与 shots')
    if len(planning['shots']) != len(panels):
        raise ValueError('空间安排与分镜格数不一致')
    missing = [] if len(panels) >= 2 else [f'{sid} 只有一个镜头，请直接复核原关键帧，无需制作宫格']
    # 将交接包映射回已有字段，统一执行缺项检查，避免两种输入要求漂移。
    mapped = {'id': sid, 'blocking': planning['opening'], 'cuts': []}
    current = Decimal(0)
    for index, (panel, shot) in enumerate(zip(panels, planning['shots']), 1):
        expected = f'{sid}-f{index}'
        if set(panel) != {'shot', 'time', 'size', 'frame', 'reference'} or set(shot) != {'shot', 'view', 'continuity', 'action'}:
            raise ValueError(f'{expected} 交接字段不完整或包含未知字段')
        if panel['shot'] != expected or shot['shot'] != expected:
            raise ValueError('镜号或空间安排顺序与原切序不一致')
        if not isinstance(panel['time'], list) or len(panel['time']) != 2:
            raise ValueError(f'{expected} 缺少起止时间')
        start, end = map(seconds, panel['time'])
        if start != current or end <= start:
            raise ValueError(f'{expected} 时间轴不连续或时长无效')
        current = end
        if panel['size'] not in SIZES:
            missing.append(f'{expected} 缺少有效景别')
        if not nonempty(panel['frame']):
            missing.append(f'{expected} 缺少 frame 切点画面描述，不能拿视频动作正文代替')
        if panel['reference'] is not None and not nonempty(panel['reference']):
            missing.append(f'{expected} 参考图片路径无效；没有图片应使用 null')
        view = shot['view']
        if not isinstance(view, dict) or set(view) != {'position', 'composition', 'eyeline'}:
            raise ValueError(f'{expected} 缺少完整 view 结构')
        # 仅在内存中适配已有上游字段；不新增或输出另一套 storyboard schema。
        cut = {'cameraPosition': view['position'], 'composition': view['composition'],
               'eyeline': view['eyeline'], 'note': shot['continuity'], 'shot': shot['action']}
        mapped['cuts'].append(cut)
    _, problems = make_planning(mapped)
    return missing + problems


def render_prompt(package):
    missing = validate_package(package)
    if missing:
        raise ValueError('交接材料待补：' + '；'.join(missing))
    panels, layout = package['panels'], package['layout']
    count, columns, rows = len(panels), layout['columns'], layout['rows']
    aspect = layout['aspect']
    if aspect == 'source':
        aspect = ('match each supplied source frame, keeping its orientation and framing'
                  if any(panel['reference'] for panel in panels) else
                  'use the project aspect ratio if specified, otherwise one consistent ratio; no source-image ratio has been verified')
    order = [f'Row {row + 1}, left to right: panels ' + ', '.join(
        str(index) for index in range(row * columns + 1, min((row + 1) * columns, count) + 1)) + '.'
        for row in range(rows)]
    timecodes, descriptions, references = [], [], []
    for index, panel in enumerate(panels, 1):
        start, end = map(timecode, panel['time'])
        timecodes.append(f"Panel {index} / {panel['shot']}: {start}-{end}; start-state time {start}.")
        descriptions.append(f"{index}. {panel['shot']} [{start}-{end}] {SIZES[panel['size']]}. Source start-state description: {panel['frame']}")
        reference = panel['reference'] or 'No image reference supplied; use the locked start-state description.'
        references.append(f'Panel {index}: {reference}')
    if not any(panel['reference'] for panel in panels):
        references.insert(0, 'TEXT-ONLY INPUT: no image references supplied; do not claim to have inspected images.')
    empty = rows * columns - count
    values = {'panel_count': count, 'columns': columns, 'rows': rows, 'aspect': aspect,
              'row_order': '\n'.join(order), 'empty_cells': f'Leave the final {empty} unused cells blank.' if empty else 'There are no unused cells.',
              'title': package['segment'], 'duration': panels[-1]['time'][1],
              'timecodes': '\n'.join(timecodes), 'panels': '\n'.join(descriptions), 'references': '\n'.join(references)}
    values.update(prompt_values(package['planning']))
    template = Template((HERE.parent / 'references/locked-blocking-grid-template.txt').read_text(encoding='utf-8'))
    placeholders = {match.group('named') or match.group('braced')
                    for match in Template.pattern.finditer(template.template)
                    if match.group('named') or match.group('braced')}
    if placeholders != set(values):
        raise ValueError('站位宫格模板缺少必要插槽或包含未知插槽')
    return template.substitute(values)


def render_brief(package):
    lines = [f"# {package['segment']} · 站位与分镜宫格", '',
             '交付为完整出图提示词；没有生成图片，未验证空间、动作语义或实际视频节奏。', '',
             '## 开场空间安排', '', package['planning']['opening'], '', '## 逐镜对应', '']
    for panel, shot in zip(package['panels'], package['planning']['shots']):
        start, end = map(timecode, panel['time'])
        lines.extend([f"### {panel['shot']} · {start}–{end}", '',
                      f"机位：{shot['view']['position']}", f"构图：{shot['view']['composition']}",
                      f"视线：{shot['view']['eyeline']}", f"切点画面：{panel['frame']}",
                      f"视频动作：{shot['action']}", f"承接安排：{shot['continuity']}",
                      f"参考图片：{panel['reference'] or '未附图片，依据原分镜描述'}", ''])
    lines.extend(['## 同步到视频生成', '',
                  '- 先在分镜源文件同步 blocking、逐镜机位与 cut.note；frame 写切点可见状态，shot 和 h3Prompt 写动作及终态。',
                  '- 关键帧出图直接消费 frame，不会自动读取本交接包；Seedance 消费 blocking、构图字段与 shot；H3 使用单独编写的 h3Prompt，必须同步修改。',
                  '- 已有关键帧受到站位修改影响时需重新生成并复核。正式投产使用独立干净关键帧，本宫格不参与参考图编号。',
                  '- 左图只代表开场。后续走位使用带镜号的路径或状态小图；发现冲突先回到源文件修正，再重新导出。',
                  '- 字段齐备不代表内容一致；需对照剧本与实际图片复核人物位置、遮挡、接触关系及跨段衔接。', ''])
    return '\n'.join(lines)


def export(args):
    source = (args.storyboard or args.plan).resolve()
    data = load_json(source)
    if args.plan:
        if args.segment or args.ep is not None or args.frames:
            raise ValueError('--plan 已确定分段和参考图片，不接受 --segment、--ep 或 --frames')
        packages = [data]
        sid = check_id(data.get('segment'))
        segments = None
        selected = [sid]
    else:
        segments = selected_segments(data, args.ep, args.segment)
        selected = [item['id'] for item in segments]
    root = args.out.resolve() / '_blocking-grid'
    targets = [root / sid / (name + suffix) for sid in selected for name in FILES for suffix in ('', '.stale')]
    targets.extend(root / (name + suffix) for name in ('index.json',) for suffix in ('', '.stale'))
    # 不能覆盖输入；也不能把输入引用的关键帧移走。
    if source in [path.resolve() for path in targets]:
        raise ValueError('输出路径不能覆盖输入交接包或分镜，请选择其他 --out')
    for target in targets:
        if not target.name.endswith('.stale') and target.exists():
            target.replace(target.with_name(target.name + '.stale'))
    if args.frames is not None and not args.frames.is_dir():
        raise ValueError('--frames 必须是存在的图片目录；没有图片请省略')
    results = []
    for index, sid in enumerate(selected):
        if segments is not None:
            package, missing = make_package(segments[index], args.frames, args.aspect or 'source')
        else:
            package = packages[index]
            if args.aspect:
                package['layout']['aspect'] = args.aspect
            missing = validate_package(package)
            for panel in package['panels']:
                if panel['reference']:
                    path = Path(panel['reference'])
                    path = (source.parent / path).resolve() if not path.is_absolute() else path.resolve()
                    if not path.is_file() or path.stat().st_size == 0:
                        missing.append(f"{panel['shot']} 指定的参考图片不存在或为空")
                    panel['reference'] = str(path)
        directory = root / sid
        directory.mkdir(parents=True, exist_ok=True)
        if missing:
            (directory / 'grid.todo').write_text('\n'.join([f'{sid} 站位宫格待补', *missing]) + '\n', encoding='utf-8')
            results.append({'segment': sid, 'status': 'pending', 'notes': missing})
        else:
            prompt = render_prompt(package)
            (directory / 'grid-input.json').write_text(json.dumps(package, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            (directory / 'grid-prompt.txt').write_text(prompt, encoding='utf-8')
            (directory / 'grid-brief.md').write_text(render_brief(package), encoding='utf-8')
            results.append({'segment': sid, 'status': 'ready', 'notes': ['提示词就绪，尚未出图或验证空间与动作语义。']})
    report = {'segments': results, 'limitations': ['不改写分镜、关键帧或视频提示词；需先按技能工作流同步上游。',
              '仅检查材料齐备和时间轴，不证明几何、轴线、图像或动作连续性。']}
    root.mkdir(parents=True, exist_ok=True)
    (root / 'index.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    for result in results:
        print(f"{result['segment']}：{result['status']}")
        for note in result['notes']:
            print('  ' + note)
    print(f'交付目录：{root}')
    return 2 if any(result['status'] == 'pending' for result in results) else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    command = commands.add_parser('export', help='导出站位＋分镜宫格的完整出图提示词')
    inputs = command.add_mutually_exclusive_group(required=True)
    inputs.add_argument('--storyboard', type=Path, help='已同步空间安排的上游分镜')
    inputs.add_argument('--plan', type=Path, help='本技能已有的五字段交接包，可独立重导出')
    command.add_argument('--out', type=Path, required=True)
    command.add_argument('--segment')
    command.add_argument('--ep', type=int)
    command.add_argument('--frames', type=Path)
    command.add_argument('--aspect', choices=ASPECTS)
    args = parser.parse_args(argv)
    try:
        return export(args)
    except (ValueError, OSError, KeyError, TypeError, AttributeError) as exc:
        print(f'输入或导出错误：{exc}', file=sys.stderr)
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
