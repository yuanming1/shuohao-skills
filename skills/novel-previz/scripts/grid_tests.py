"""宫格交接回归测试：使用自有故事和临时图片，不调用生成服务。"""
import base64
import copy
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile

from analysis_tests import five_fields
from grid_export import make_package, render_prompt, template_source, timecode, TEMPLATE_NAME


def run_grid_tests(m, t):
    print('── 宫格技能衔接测试 ──')
    skill = Path(m.HERE).parent
    fixture = skill / 'examples/失物窗口-analysis-storyboard.json'
    sb = json.loads(fixture.read_text(encoding='utf-8'))
    segment = sb['episodes'][0]['segments'][1]
    template, metadata = template_source(skill)
    t.check('锁定模板可加载', 'LOCKED STORYBOARD MODE' in template)
    installed = skill.parent / 'storyboard-builder/references' / TEMPLATE_NAME
    if installed.exists():
        t.check('优先使用已安装的宫格技能模板', Path(metadata['path']) == installed.resolve())
        t.check('内化回退模板与宫格技能同步', installed.read_bytes() == (skill / 'references' / TEMPLATE_NAME).read_bytes())
    png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aG5cAAAAASUVORK5CYII=')
    with tempfile.TemporaryDirectory(prefix='previs-grid-') as tmp:
        root = Path(tmp)
        frames = root / 'frames'
        frames.mkdir()
        for seg in sb['episodes'][0]['segments']:
            for index, _ in enumerate(seg['cuts'], 1):
                (frames / f"{seg['id']}-f{index}.png").write_bytes(png)
        original = copy.deepcopy(segment)
        package, missing = make_package(segment, frames)
        prompt = render_prompt(package, template)
        t.check('既有关键帧完整时可交付', not missing)
        t.check('交接包每对象不超过五字段', five_fields(package))
        t.check('不重新拆镜或改秒数', segment == original and [p['time'] for p in package['panels']] == [['0', '3'], ['3', '7']])
        t.check('不均分为每格两秒', '00:00.000-00:03.000' in prompt and '00:03.000-00:07.000' in prompt)
        t.check('保留每格原描述与参考文件', all(p['frame'] in prompt and p['reference'] in prompt for p in package['panels']))
        t.check('完整提示词包含布局内容角色风格及渲染指令', all(v in prompt for v in
                ['LAYOUT:', 'THE 2 PANELS', 'CHARACTER AND PROP CONSISTENCY', 'INSIDE EACH PANEL', 'Render the COMPLETE']))
        t.check('不擅自裁剪为横屏', 'keeping their original orientation' in prompt)
        t.check('时间码不截断原有精度', timecode('3.2501') == '00:03.2501')

        command = [sys.executable, '-X', 'utf8', str(Path(m.HERE) / 'storyboard_to_shots.py'),
                   'export-grid', '--storyboard', str(fixture), '--frames', str(frames), '--out', str(root / 'output')]
        def run(extra=()):
            return subprocess.run(command + list(extra), capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30)
        def index():
            return json.loads((root / 'output/_grid/index.json').read_text(encoding='utf-8'))
        result = run()
        t.check('宫格导出 CLI 可运行', result.returncode == 0, result.stderr)
        report = index()
        statuses = {item['segment']: item['status'] for item in report['segments']}
        t.check('只处理推荐宫格的段落', statuses == {'E01-01': 'skipped', 'E01-02': 'ready', 'E01-03': 'skipped', 'E01-04': 'skipped', 'E01-05': 'ready'})
        t.check('宫格索引每对象不超过五字段', five_fields(report))
        directory = root / 'output/_grid/E01-02'
        text = (directory / 'grid-prompt.txt').read_text(encoding='utf-8')
        t.check('已产出完整提示词与可读交接说明', text == prompt and (directory / 'grid-brief.md').is_file())
        t.check('没有生成新图片或覆盖输入', not list((root / 'output').rglob('*.png'))
                and json.loads(fixture.read_text(encoding='utf-8')) == sb
                and (frames / 'E01-02-f1.png').read_bytes() == png)
        result = run()
        t.check('重复导出提示词确定', result.returncode == 0 and (directory / 'grid-prompt.txt').read_text(encoding='utf-8') == text)

        (frames / 'E01-02-f1.png').rename(frames / 'E01-02-f1.png.unavailable')
        result = run(['--segment', 'E01-02'])
        t.check('部分镜头无图仍可交付', result.returncode == 0
                and (directory / 'grid-prompt.txt').exists() and not (directory / 'grid.todo').exists())
        mixed = json.loads((directory / 'grid-input.json').read_text(encoding='utf-8'))
        mixed_prompt = (directory / 'grid-prompt.txt').read_text(encoding='utf-8')
        t.check('缺图记录 null 不伪造路径', mixed['panels'][0]['reference'] is None
                and mixed['panels'][1]['reference'] == str((frames / 'E01-02-f2.png').resolve())
                and 'E01-02-f1.png' not in mixed_prompt and 'No image reference supplied' in mixed_prompt)
        t.check('部分参考覆盖范围明确记录', '1/2' in index()['segments'][0]['notes'][0]
                and '未附图片' in (directory / 'grid-brief.md').read_text(encoding='utf-8'))
        t.check('旧提示词备份保留', (directory / 'grid-prompt.txt.stale').read_text(encoding='utf-8') == text)
        (frames / 'E01-02-f1.png.unavailable').rename(frames / 'E01-02-f1.png')
        result = run(['--segment', 'E01-02'])
        t.check('补图后自动恢复图像参考', result.returncode == 0 and (directory / 'grid-prompt.txt').exists()
                and not (directory / 'grid.todo').exists())
        (frames / 'E01-02-f1.jpg').write_bytes(b'duplicate fixture')
        result = run(['--segment', 'E01-02'])
        t.check('同镜多版本不擅自挑选', result.returncode == 2 and '多张' in (directory / 'grid.todo').read_text(encoding='utf-8'))
        (frames / 'E01-02-f1.jpg').rename(frames / 'duplicate.disabled')
        result = run(['--segment', 'E01-03'])
        t.check('单镜不重复制作宫格', result.returncode == 2 and not (root / 'output/_grid/E01-03/grid-prompt.txt').exists())


        # 显式来源必须真正参与提示词生成。
        builder = root / 'custom-builder'
        (builder / 'references').mkdir(parents=True)
        (builder / 'SKILL.md').write_text('# Local builder fixture', encoding='utf-8')
        template_path = builder / 'references' / TEMPLATE_NAME
        template_path.write_text(template + '\nCUSTOM-TEMPLATE-MARKER\n', encoding='utf-8')
        result = run(['--segment', 'E01-02', '--builder', str(builder)])
        t.check('指定宫格模板实际参与交付', result.returncode == 0
                and 'CUSTOM-TEMPLATE-MARKER' in (directory / 'grid-prompt.txt').read_text(encoding='utf-8')
                and Path(index()['template']['path']) == template_path.resolve())
        template_path.write_text('Incomplete template', encoding='utf-8')
        result = run(['--segment', 'E01-02', '--builder', str(builder)])
        t.check('模板字段错误撤下旧提示词并报错', result.returncode == 3
                and not (directory / 'grid-prompt.txt').exists())
        result = run(['--segment', 'E01-02', '--builder', str(root / 'absent')])
        t.check('显式模板不存在不静默回退', result.returncode == 3)

        no_frame = copy.deepcopy(segment)
        no_frame['cuts'][0].pop('frame')
        _, missing = make_package(no_frame, frames)
        t.check('缺少切点画面不能拿动作正文兜底', any('cut.frame' in note for note in missing))
        bad_size = copy.deepcopy(segment)
        bad_size['cuts'][0]['size'] = 'unknown'
        _, missing = make_package(bad_size, frames)
        t.check('未知景别不擅自重新设计', any('景别' in note for note in missing))
        (frames / 'E01-02-f1.png').write_bytes(b'')
        result = run(['--segment', 'E01-02'])
        t.check('空图片列为待补', result.returncode == 2 and '空文件' in (directory / 'grid.todo').read_text(encoding='utf-8'))
        (frames / 'E01-02-f1.png').write_bytes(png)
        result = run(['--segment', 'E01-02', '--aspect', '9:16'])
        t.check('只有明确指定时才覆盖画幅', result.returncode == 0
                and json.loads((directory / 'grid-input.json').read_text(encoding='utf-8'))['layout']['aspect'] == '9:16'
                and 'aspect ratio: 9:16' in (directory / 'grid-prompt.txt').read_text(encoding='utf-8'))

        unequal = copy.deepcopy(segment)
        unequal['cuts'][0]['seconds'] = 2.2501
        unequal['cuts'][1]['seconds'] = 4.125
        package, _ = make_package(unequal, frames)
        t.check('非等长小数切点精确保留', [panel['time'] for panel in package['panels']] == [['0', '2.2501'], ['2.2501', '6.3751']])
        for count, columns, rows in [(3, 2, 2), (5, 3, 2)]:
            many = copy.deepcopy(segment)
            many['cuts'] = [copy.deepcopy(segment['cuts'][0]) for _ in range(count)]
            for i in range(3, count + 1):
                (frames / f'E01-02-f{i}.png').write_bytes(png)
            package, missing = make_package(many, frames)
            text = render_prompt(package, template)
            t.check(f'{count} 镜的空格不编造剧情', not missing and len(package['panels']) == count
                    and package['layout']['columns'] == columns and package['layout']['rows'] == rows
                    and 'final 1 unused cells blank' in text)
        (frames / 'E01-02').mkdir()
        (frames / 'E01-02-f1.png').rename(frames / 'E01-02/E01-02-f1.png')
        result = run(['--segment', 'E01-02'])
        t.check('支持按段目录整理原图', result.returncode == 0)

        sibling = root / 'output/_grid/E01-05/grid-prompt.txt'
        previous = sibling.read_bytes()
        result = run(['--segment', 'E01-02'])
        t.check('局部导出不改其他段落交付', result.returncode == 0 and sibling.read_bytes() == previous)
        reduced = copy.deepcopy(sb)
        changed = reduced['episodes'][0]['segments'][1]
        changed['cuts'] = [copy.deepcopy(sb['episodes'][0]['segments'][0]['cuts'][0])]
        changed_input = root / 'changed-storyboard.json'
        changed_input.write_text(json.dumps(reduced, ensure_ascii=False), encoding='utf-8')
        result = run(['--storyboard', str(changed_input)])
        t.check('撤销宫格推荐时不遗留旧提示词', result.returncode == 0
                and not (directory / 'grid-prompt.txt').exists()
                and next(item['status'] for item in index()['segments'] if item['segment'] == 'E01-02') == 'skipped')

        # 没有任何图片时，仍能交付完整宫格图提示词。
        text_command = [sys.executable, '-X', 'utf8', str(Path(m.HERE) / 'storyboard_to_shots.py'),
                        'export-grid', '--storyboard', str(fixture), '--out', str(root / 'text-only')]
        def run_text(extra=()):
            return subprocess.run(text_command + list(extra), capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30)
        result = run_text()
        t.check('仅有分镜文件即可执行 CLI', result.returncode == 0, result.stderr)
        text_dir = root / 'text-only/_grid/E01-02'
        data = json.loads((text_dir / 'grid-input.json').read_text(encoding='utf-8'))
        text_prompt = (text_dir / 'grid-prompt.txt').read_text(encoding='utf-8')
        text_brief = (text_dir / 'grid-brief.md').read_text(encoding='utf-8')
        text_index = json.loads((root / 'text-only/_grid/index.json').read_text(encoding='utf-8'))
        t.check('纯文字交接遵守五字段且图片均为空', five_fields(data) and five_fields(text_index)
                and all(panel['reference'] is None for panel in data['panels']))
        t.check('纯文字提示词不假装已有图像', 'TEXT-ONLY INPUT' in text_prompt
                and 'supplied source frames, keeping' not in text_prompt
                and 'no source-image ratio has been verified' in text_prompt
                and ': None' not in text_prompt and ': None' not in text_brief
                and '未附参考图片' in text_brief)
        t.check('纯文字仍保留原描述切点景别及完整模板', all(panel['frame'] in text_prompt for panel in data['panels'])
                and '00:00.000-00:03.000' in text_prompt and '00:03.000-00:07.000' in text_prompt
                and 'MEDIUM' in text_prompt and 'CLOSE' in text_prompt and 'Render the COMPLETE' in text_prompt)
        result = run_text(['--segment', 'E01-02', '--aspect', '9:16'])
        t.check('无图时支持明确画幅', result.returncode == 0
                and 'aspect ratio: 9:16' in (text_dir / 'grid-prompt.txt').read_text(encoding='utf-8'))
        empty_frames = root / 'empty-frames'
        empty_frames.mkdir()
        result = run_text(['--frames', str(empty_frames)])
        t.check('空参考目录不阻断提示词', result.returncode == 0
                and (text_dir / 'grid-prompt.txt').read_text(encoding='utf-8') == text_prompt)
        result = run_text(['--frames', str(root / 'missing-directory')])
        t.check('显式无效目录报错且撤下旧提示词', result.returncode == 3
                and not (text_dir / 'grid-prompt.txt').exists())
        result = run_text(['--frames', str(fixture)])
        t.check('不把文件路径当作图片目录', result.returncode == 3)
        result = run_text(['--frames', str(frames)])
        t.check('有图无图转换前有图导出正常', result.returncode == 0)
        result = run_text()
        t.check('取消参考目录后不残留旧图片引用', result.returncode == 0
                and (text_dir / 'grid-prompt.txt').read_text(encoding='utf-8') == text_prompt
                and str(frames) not in (text_dir / 'grid-prompt.txt').read_text(encoding='utf-8'))
        missing_frame_sb = copy.deepcopy(sb)
        missing_frame_sb['episodes'][0]['segments'][1]['cuts'][0].pop('frame')
        missing_frame_file = root / 'no-frame-description.json'
        missing_frame_file.write_text(json.dumps(missing_frame_sb, ensure_ascii=False), encoding='utf-8')
        result = run_text(['--storyboard', str(missing_frame_file), '--segment', 'E01-02'])
        t.check('图片可选不等于画面描述可省略', result.returncode == 2
                and not (text_dir / 'grid-prompt.txt').exists() and (text_dir / 'grid.todo').exists())
        result = run_text(['--segment', 'E01-02'])
        t.check('补齐描述后无需图片即可恢复', result.returncode == 0 and not (text_dir / 'grid.todo').exists())

        # 脱离仓库与本机注册目录，完整 CLI 仍能使用内化模板。
        standalone = root / 'portable/novel-previz'
        shutil.copytree(skill, standalone, ignore=shutil.ignore_patterns('__pycache__'))
        env = dict(os.environ, CODEX_HOME=str(root / 'empty-codex-home'))
        portable_command = [sys.executable, '-X', 'utf8', str(standalone / 'scripts/storyboard_to_shots.py'),
                            'export-grid', '--storyboard', str(standalone / 'examples/失物窗口-analysis-storyboard.json'),
                            '--out', str(root / 'portable-output')]
        result = subprocess.run(portable_command, env=env, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30)
        portable_index = root / 'portable-output/_grid/index.json'
        report = json.loads(portable_index.read_text(encoding='utf-8')) if portable_index.exists() else {}
        t.check('单独复制后无宫格技能及图片也可导出', result.returncode == 0
                and '内化模板' in report.get('template', {}).get('origin', ''), result.stderr)
        portable_prompt = root / 'portable-output/_grid/E01-02/grid-prompt.txt'
        t.check('独立回退保留完整锁定提示词', portable_prompt.is_file()
                and '00:03.000-00:07.000' in portable_prompt.read_text(encoding='utf-8'))
