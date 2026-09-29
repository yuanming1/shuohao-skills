"""预演方式分析回归：只使用本技能自有故事，不依赖 Blender。"""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from previs_analysis import analyze_storyboard, markdown_report, cue_hits, SPATIAL_CUES


def five_fields(value):
    if isinstance(value, dict):
        return len(value) <= 5 and all(five_fields(v) for v in value.values())
    if isinstance(value, list):
        return all(five_fields(v) for v in value)
    return True


def run_analysis_tests(m, t):
    print('── 预演方式分析测试 ──')
    source = Path(m.HERE).parent / 'examples/失物窗口-analysis-storyboard.json'
    storyboard = json.loads(source.read_text(encoding='utf-8'))
    original = copy.deepcopy(storyboard)
    report = analyze_storyboard(storyboard, m.MOVE_TABLE)
    items = report['segments']
    expected = [['none'], ['grid'], ['none'], ['greybox'], ['greybox', 'grid']]
    for item, methods in zip(items, expected):
        t.check(f"{item['segment']} 选择 {methods}", item['methods'] == methods, str(item['methods']))
    t.check('分析不修改分镜与秒数', storyboard == original)
    t.check('独立关键帧不再是预演方式', all('keyframes' not in item['methods'] for item in items))
    t.check('细节提示指向原画面复核', items[2]['scope'] == {'review': ['E01-03-f1']}
            and any('退回原分镜' in reason for reason in items[2]['reasons']))
    t.check('分析输出每对象不超过五字段', five_fields(report))
    t.check('样例每对象不超过五字段', five_fields(storyboard))
    t.check('输出具有具体镜号范围', items[-1]['scope'] == {
        'greybox': ['E01-05-f1'], 'grid': ['E01-05-f1', 'E01-05-f2'], 'review': ['E01-05-f2']})
    t.check('跟拍推荐同时提示降级', any('Tracking Shot' in v and '降级' in v for v in items[-1]['limits']))
    t.check('交接不误报为可自动预演', any('递给' in v and '不自动生成' in v for v in items[-1]['limits']))
    t.check('简单否定不触发遮挡判断', cue_hits('没有遮挡，不要越轴，避免挡住主体', SPATIAL_CUES) == [])
    t.check('实际空间线索仍可识别', cue_hits('门框遮挡主体', SPATIAL_CUES) == ['遮挡'])

    repeated = copy.deepcopy(storyboard)
    repeated['episodes'][0]['segments'] = repeated['episodes'][0]['segments'][:1]
    repeated['episodes'][0]['segments'][0]['cuts'] *= 2
    result = analyze_storyboard(repeated, m.MOVE_TABLE)
    t.check('不因镜头数大于一就强制宫格', result['segments'][0]['methods'] == ['none'])
    repeated['episodes'][0]['segments'][0]['blocking'] = '门框挡住人物，需要检查遮挡。'
    result = analyze_storyboard(repeated, m.MOVE_TABLE)
    t.check('段级空间问题覆盖本段', result['segments'][0]['scope']['greybox'] == ['E01-01-f1', 'E01-01-f2'])
    single_action = copy.deepcopy(repeated)
    single_action['episodes'][0]['segments'][0]['cuts'] = single_action['episodes'][0]['segments'][0]['cuts'][:1]
    single_action['episodes'][0]['segments'][0]['blocking'] = '人物拿起凭条后放下。'
    result = analyze_storyboard(single_action, m.MOVE_TABLE)
    t.check('单镜动作只复核已有关键帧', result['segments'][0]['methods'] == ['none']
            and result['segments'][0]['scope']['review'] == ['E01-01-f1']
            and any('不自动生成' in value for value in result['segments'][0]['limits']))
    filtered = analyze_storyboard(storyboard, m.MOVE_TABLE, segment='E01-03')
    t.check('按段筛选', len(filtered['segments']) == 1 and filtered['segments'][0]['segment'] == 'E01-03')
    markdown = markdown_report(report)
    t.check('报告展示依据范围与后续处理', all(v in markdown for v in ['判断依据', '检查范围', '注意事项', '后续处理', '规则初筛']))
    t.check('不强制十五格或固定两秒', '十五格' not in markdown and all(
        len(item['scope'].get('grid', [])) <= len(seg['cuts'])
        for item, seg in zip(items, storyboard['episodes'][0]['segments'])))

    for seconds in (0, -1, True, float('nan'), float('inf')):
        bad = copy.deepcopy(storyboard)
        bad['episodes'][0]['segments'][0]['cuts'][0]['seconds'] = seconds
        try:
            analyze_storyboard(bad, m.MOVE_TABLE)
            rejected = False
        except ValueError:
            rejected = True
        t.check(f'拒绝无效秒数 {seconds}', rejected)
    for kwargs in ({'segment': 'E99-99'}, {'ep': 99}):
        try:
            analyze_storyboard(storyboard, m.MOVE_TABLE, **kwargs)
            rejected = False
        except ValueError:
            rejected = True
        t.check(f'拒绝空选择 {kwargs}', rejected)

    with tempfile.TemporaryDirectory(prefix='previs-analysis-') as tmp:
        command = [sys.executable, '-X', 'utf8', str(Path(m.HERE) / 'storyboard_to_shots.py'),
                   'analyze', '--storyboard', str(source), '--out', tmp]
        result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', timeout=30)
        t.check('分析 CLI 无需场景配置和 Blender', result.returncode == 0, result.stderr)
        files = {p.relative_to(tmp).as_posix() for p in Path(tmp).rglob('*') if p.is_file()}
        t.check('分析只生成 JSON 和 Markdown', files == {'_analysis/analysis.json', '_analysis/analysis.md'})
        if result.returncode == 0:
            saved = json.loads((Path(tmp) / '_analysis/analysis.json').read_text(encoding='utf-8'))
            t.check('CLI 与内存规则一致', saved == report)
            first = (Path(tmp) / '_analysis/analysis.json').read_bytes()
            subprocess.run(command, capture_output=True, timeout=30)
            t.check('重复分析结果确定', first == (Path(tmp) / '_analysis/analysis.json').read_bytes())

        existing_scene = Path(tmp) / 'E01-01/scene.py'
        existing_report = Path(tmp) / '_report/report.json'
        existing_scene.parent.mkdir(parents=True, exist_ok=True)
        existing_report.parent.mkdir(parents=True, exist_ok=True)
        existing_scene.write_text('# existing scene', encoding='utf-8')
        existing_report.write_text('existing export report', encoding='utf-8')
        result = subprocess.run(command, capture_output=True, timeout=30)
        t.check('分析不会覆盖已有白模导出', result.returncode == 0
                and existing_scene.read_text(encoding='utf-8') == '# existing scene'
                and existing_report.read_text(encoding='utf-8') == 'existing export report')
