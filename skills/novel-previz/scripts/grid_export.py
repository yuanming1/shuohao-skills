"""锁定分镜宫格交付：依据原分镜、可选参考图片生成完整提示词，不调用图像模型。"""
from decimal import Decimal
import hashlib
import json
import math
import os
from pathlib import Path
import re
from string import Template

from previs_analysis import analyze_storyboard, selected_segments

TEMPLATE_NAME = 'locked-grid-template.txt'
FILES = ('grid-input.json', 'grid-prompt.txt', 'grid-brief.md', 'grid.todo')
IMAGE_SUFFIXES = {'.png', '.jpg', '.jpeg', '.webp'}
SIZE_LABELS = {'extreme-wide': 'EXTREME WIDE', 'wide': 'WIDE', 'medium': 'MEDIUM',
               'close': 'CLOSE', 'extreme-close': 'EXTREME CLOSE'}


def template_source(skill_dir, builder=None):
    skill_dir = Path(skill_dir)
    if builder:
        candidates = [(Path(builder), '指定的 storyboard-builder')]
    else:
        home = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex')))
        candidates = [(skill_dir.parent / 'storyboard-builder', '仓库 storyboard-builder'),
                      (home / 'skills/storyboard-builder', '已注册 storyboard-builder')]
    for root, origin in candidates:
        template = root / 'references' / TEMPLATE_NAME
        if (root / 'SKILL.md').is_file() and template.is_file():
            path = template.resolve()
            break
    else:
        if builder:
            raise ValueError('指定的 storyboard-builder 缺少 SKILL.md 或锁定分镜模板')
        path = (skill_dir / 'references' / TEMPLATE_NAME).resolve()
        origin = '预演技能内化模板（独立使用回退）'
    content = path.read_text(encoding='utf-8')
    required = {'panel_count', 'columns', 'rows', 'aspect', 'row_order', 'empty_cells',
                'title', 'duration', 'timecodes', 'panels', 'references'}
    found = {match.group('named') or match.group('braced')
             for match in Template.pattern.finditer(content)
             if match.group('named') or match.group('braced')}
    if found != required:
        raise ValueError('锁定分镜模板缺少必要字段或包含未知字段，不发布宫格提示词')
    return content, {'path': str(path), 'sha256': hashlib.sha256(content.encode('utf-8')).hexdigest(),
                     'origin': origin}


def locate_frame(root, shot):
    if root is None:
        return None, None
    root = Path(root)
    segment = shot.rsplit('-f', 1)[0]
    matches = set()
    for directory in (root, root / segment):
        if directory.is_dir():
            for candidate in directory.iterdir():
                if candidate.is_file() and candidate.stem == shot and candidate.suffix.lower() in IMAGE_SUFFIXES:
                    matches.add(candidate.resolve())
    if not matches:
        return None, None
    if len(matches) > 1:
        return None, f'{shot} 匹配到多张图片，请保留明确的唯一版本'
    path = next(iter(matches))
    if path.stat().st_size == 0:
        return None, f'{shot} 图片为空文件'
    return str(path), None


def make_package(segment, frames=None, aspect='source'):
    sid = segment['id']
    panels, missing = [], []
    current = Decimal('0')
    for index, cut in enumerate(segment['cuts'], 1):
        shot = f'{sid}-f{index}'
        end = current + Decimal(str(cut['seconds']))
        frame = cut.get('frame')
        if not isinstance(frame, str) or not frame.strip():
            missing.append(f'{shot} 缺少原 cut.frame，不能用动作正文代替切点状态')
        size = cut.get('size')
        if size not in SIZE_LABELS:
            missing.append(f'{shot} 缺少有效景别，不擅自重新设计镜头')
        reference, problem = locate_frame(frames, shot)
        if problem:
            missing.append(problem)
        panels.append({'shot': shot, 'time': [str(current), str(end)], 'size': size,
                       'frame': frame, 'reference': reference})
        current = end
    if len(panels) < 2:
        missing.append(f'{sid} 只有一个镜头，复核原画面描述及可用关键帧，不额外制作宫格')
    columns = min(4, max(1, math.ceil(math.sqrt(len(panels)))))
    package = {'mode': 'locked-storyboard', 'segment': sid,
               'layout': {'columns': columns, 'rows': math.ceil(len(panels) / columns), 'aspect': aspect},
               'panels': panels}
    return package, missing


def timecode(seconds):
    value = Decimal(seconds)
    minutes = int(value // 60)
    secs = value - minutes * 60
    integer, dot, fraction = format(secs, 'f').partition('.')
    return f'{minutes:02d}:{int(integer):02d}.' + fraction.ljust(3, '0')


def reference_summary(package):
    total = len(package['panels'])
    count = sum(bool(panel['reference']) for panel in package['panels'])
    if count == 0:
        return '未附参考图片；全部镜头依据原分镜画面描述，外观一致性尚未经过图像验证。'
    if count == total:
        return f'已附 {count} 张可选关键帧参考；仅确认文件存在，未验证图像内容。'
    return f'已附 {count}/{total} 张可选关键帧参考；其余镜头依据原画面描述，不编造参考图片。'


def render_prompt(package, template):
    if package['mode'] != 'locked-storyboard':
        raise ValueError('宫格交接包不是锁定分镜模式')
    panels = package['panels']
    count = len(panels)
    columns, rows = package['layout']['columns'], package['layout']['rows']
    aspect = package['layout']['aspect']
    if aspect == 'source':
        if any(panel['reference'] for panel in panels):
            aspect = 'match the supplied source frames, keeping their original orientation and framing'
        else:
            aspect = 'use the project aspect ratio if specified; otherwise use one consistent ratio across panels (no source-image ratio has been verified)'
    order = []
    for row in range(rows):
        indices = list(range(row * columns + 1, min((row + 1) * columns, count) + 1))
        order.append(f'Row {row + 1}, left to right: panels ' + ', '.join(map(str, indices)) + '.')
    ranges, descriptions, references = [], [], []
    for index, panel in enumerate(panels, 1):
        start, end = map(timecode, panel['time'])
        shot = panel['shot']
        ranges.append(f'Panel {index} / {shot}: {start}-{end}; start-state time {start}.')
        descriptions.append(f"{index}. {shot} [{start}-{end}] {SIZE_LABELS[panel['size']]}. Source start-state description: {panel['frame']}")
        reference = panel['reference'] or 'No image reference supplied; use this panel start-state description.'
        references.append(f'Panel {index} / {shot}: {reference}')
    if not any(panel['reference'] for panel in panels):
        references.insert(0, 'TEXT-ONLY INPUT: no image references supplied. Generate the sheet from the locked storyboard descriptions; do not claim to have seen source images.')
    empty = rows * columns - count
    values = {'panel_count': count, 'columns': columns, 'rows': rows, 'aspect': aspect,
              'row_order': '\n'.join(order), 'empty_cells': f'Leave the final {empty} unused cells blank, outside the story sequence.' if empty else 'There are no unused cells.',
              'title': package['segment'], 'duration': panels[-1]['time'][1],
              'timecodes': '\n'.join(ranges), 'panels': '\n'.join(descriptions), 'references': '\n'.join(references)}
    try:
        return Template(template).substitute(values)
    except (KeyError, ValueError) as exc:
        raise ValueError(f'宫格模板字段不兼容: {exc}') from exc


def render_brief(package, source):
    lines = [f"# {package['segment']} · storyboard-builder 宫格交接", '',
             '输入模式：locked-storyboard。读取同目录 grid-input.json，交付内容为 grid-prompt.txt。',
             '原分镜画面描述是必需输入，实际参考图片可选；交付的是宫格图提示词，不是视频提示词。',
             reference_summary(package),
             '', f"模板来源：{source['origin']}", f"模板文件：{source['path']}",
             f"模板校验值：{source['sha256']}", '', '## 已锁定的输入', '']
    for panel in package['panels']:
        start, end = map(timecode, panel['time'])
        reference = panel['reference'] or '未附图片，依据原分镜画面描述'
        lines.append(f"- {panel['shot']}：{start}–{end}；参考图：{reference}")
    lines.extend(['', '## 交付要求', '',
                  '- 使用 storyboard-builder 的锁定分镜模式，不套用自由创作模式的固定格数、均分秒数或强制景别交替。',
                  '- 保留原镜号、顺序、景别、切点状态及时间范围；不增删剧情，不改写正式分镜。',
                  '- 可以直接提交完整提示词出图；如果附有参考图片，再一起提交，文件路径不会自动上传。',
                  '- 角色图或场景图也可在实际出图时由用户另外附加；本命令只自动匹配按原镜号命名的关键帧。',
                  '- 可以让 Agent 使用已安装的 storyboard-builder 审阅或润色该提示词，但不得改变锁定字段。',
                  '', '## 提示词交付附注', '',
                  '- 视觉选择：以原画面描述为准；有参考图时沿用其已明确外观，没有图片时不声称已验证角色、场景或画风一致性。',
                  '- 风险：小格中的文字、面部和持物细节最容易失真；生成后对照原分镜及可用参考图片复核。',
                  '- 分辨率：在工具允许的范围内选择足够高的分辨率；不能保证模型逐像素复现参考图。',
                  '- 此次只生成交接包与提示词，没有出图，也不生产一套新的独立关键帧；宫格不得直接替换正式独立关键帧。', ''])
    return '\n'.join(lines)


def export_grid(adapter, args):
    storyboard = adapter.load_json(args.storyboard, '分镜')
    selected = selected_segments(storyboard, args.ep, args.segment)
    analysis = analyze_storyboard(storyboard, adapter.MOVE_TABLE, args.ep, args.segment)
    recommendations = {item['segment']: item for item in analysis['segments']}
    root = adapter.output_path(args.out, '_grid')
    all_paths = []
    for segment in selected:
        sid = segment['id']
        if not re.fullmatch(r'E[0-9]{2,}-[0-9]{2,}', sid):
            raise ValueError(f'段号不能作为安全输出目录: {sid!r}')
        all_paths.extend(adapter.output_path(root, sid, filename + suffix)
                         for filename in FILES for suffix in ('', '.stale'))
    all_paths.extend(adapter.output_path(root, name) for name in ('index.json', 'index.json.stale'))
    if os.path.realpath(args.storyboard) in all_paths:
        raise ValueError('宫格输出不能覆盖输入分镜')
    # 先撤下所选段的旧交付，输入或模板错误、参考变化、取消推荐时不能误使用旧提示词。
    for segment in selected:
        for filename in FILES:
            old = adapter.output_path(root, segment['id'], filename)
            stale = adapter.output_path(root, segment['id'], filename + '.stale')
            if os.path.isfile(old):
                os.replace(old, stale)
    index = adapter.output_path(root, 'index.json')
    if os.path.isfile(index):
        os.replace(index, adapter.output_path(root, 'index.json.stale'))
    if args.frames is not None and not Path(args.frames).is_dir():
        raise ValueError('指定的 --frames 必须是存在的目录；没有参考图时请省略该参数')
    template, source = template_source(Path(adapter.HERE).parent, args.builder)
    results = []
    for segment in selected:
        sid = segment['id']
        if args.segment is None and 'grid' not in recommendations[sid]['methods']:
            results.append({'segment': sid, 'status': 'skipped', 'files': {},
                            'notes': ['当前分析不推荐额外宫格；继续原分镜流程，不生成新的提示词。']})
            continue
        package, missing = make_package(segment, args.frames, args.aspect)
        if missing:
            todo = adapter.output_path(root, sid, 'grid.todo')
            adapter.write_text(todo, '\n'.join([f'{sid} 宫格交付待补：', *missing]) + '\n')
            results.append({'segment': sid, 'status': 'pending', 'files': {'todo': todo}, 'notes': missing})
            continue
        prompt = render_prompt(package, template)
        files = {key: adapter.output_path(root, sid, filename) for key, filename in
                 (('input', 'grid-input.json'), ('brief', 'grid-brief.md'), ('prompt', 'grid-prompt.txt'))}
        adapter.write_text(files['input'], json.dumps(package, ensure_ascii=False, indent=2) + '\n')
        adapter.write_text(files['brief'], render_brief(package, source))
        adapter.write_text(files['prompt'], prompt)
        results.append({'segment': sid, 'status': 'ready', 'files': files,
                        'notes': [reference_summary(package), '提示词准备完成，尚未出图。']})
    report = {'segments': results, 'template': source,
              'limitations': ['参考图片可选；没有图片的镜头依据原画面描述，不代表已经确认外观。',
                              '存在的图片仅检查唯一文件与非空；没有验证图像内容、真实画幅和视觉连续性。',
                              '本命令不调用图像模型，不生成新关键帧，不修改原分镜。']}
    adapter.write_text(index, json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    for item in results:
        print(f"{item['segment']}：{item['status']}")
        for note in item['notes']:
            print('  ' + note)
    print(f'宫格交付索引：{index}')
    return 2 if any(item['status'] == 'pending' for item in results) else 0
