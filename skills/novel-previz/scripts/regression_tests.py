# 回归测试：导出安全、缺项处理、能力边界，以及可选 Blender 实际执行。
import ast
import contextlib
import copy
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def quiet_export(adapter, directory, sb, script, cfg, extra=None):
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return adapter._export_to(str(directory), sb, script, cfg, extra)


def run_regressions(m, t, blender=None):
    print('── 适配回归测试 ──')
    base = Path(m.HERE).parent
    header = (base / 'SKILL.md').read_text(encoding='utf-8').split('---', 2)[1].strip().splitlines()
    t.check('技能说明采用有效的缩进块格式',
            header[0] == 'name: novel-previz' and header[1] == 'description: |'
            and all(line.startswith('  ') for line in header[2:]))
    for values in ([], [0], [0, 1]):
        t.check(f'元组字面量 {values}', ast.literal_eval(m.tup(values)) == tuple(values))

    sb = m.load_json(m._fixture('synthetic/synthetic-storyboard.json'), '合成分镜')
    script = m.load_json(m._fixture('synthetic/synthetic-script.json'), '合成剧本')
    cfg = m.load_json(m._fixture('synthetic/synthetic-config.json'), '合成配置')
    # 一个人物和一个道具同框，不经过原先的纯道具主体分支。
    single = copy.deepcopy(sb)
    single['episodes'][0]['segments'] = single['episodes'][0]['segments'][:1]
    segment = single['episodes'][0]['segments'][0]
    segment['cuts'] = segment['cuts'][:1]
    segment['cuts'][0]['props'] = ['Q01']
    for label, prop in [('整个占位', None),
                        ('空对象', {}),
                        ('全部未填', {'hand': None, 'pos': None, 'dims': None}),
                        ('缺少尺寸', {'pos': [0, 2], 'dims': None}),
                        ('缺少挂手兜底', {'hand': 'K01:R', 'dims': [0.1, 0.2, 0.3]})]:
        partial = copy.deepcopy(cfg)
        partial['scenes']['SY1']['props']['Q01'] = prop
        with tempfile.TemporaryDirectory() as tmp:
            code, out = quiet_export(m, tmp, single, script, partial)
            report = json.loads(out['_report/report.json'])
            t.check(f'同框道具{label}进入待补', code == 2 and bool(report['missing'])
                    and 'E01-01/scene.py' not in out and 'E01-01/scene.py.todo' in out, f'code={code}')

    for label, changes in [('箱体尺寸错误', {'dims': [1, 2]}),
                           ('尺寸不是正数', {'dims': [0, 1, 1]}),
                           ('挂手方向错误', {'hand': 'K01:wrong'})]:
        invalid = copy.deepcopy(cfg)
        invalid['scenes']['SY1']['props']['Q01'].update(changes)
        with tempfile.TemporaryDirectory() as tmp:
            code, out = quiet_export(m, tmp, single, script, invalid)
            t.check(f'{label}拒绝发布', code == 1 and 'E01-01/scene.py' not in out, f'code={code}')

    # 骨架里的可选 null 采用文档默认值，而不是生成 P[None] 等运行期错误。
    defaults = copy.deepcopy(cfg)
    defaults['scenes']['SY1']['props']['Q01'] = {
        'pos': [0, 2], 'dims': [0.1, 0.2, 0.3], 'shape': None, 'mat': None, 'role': None}
    with tempfile.TemporaryDirectory() as tmp:
        code, out = quiet_export(m, tmp, single, script, defaults)
        text = out.get('E01-01/scene.py', '')
        t.check('可选空值采用道具默认值', code == 0 and "P['PROP']" in text
                and 'None' not in '\n'.join(line for line in text.splitlines() if line.startswith('box(')))

    with tempfile.TemporaryDirectory() as tmp:
        quiet_export(m, tmp, sb, script, cfg)
        original = (Path(tmp) / 'E01-01/scene.py').read_text(encoding='utf-8')
        partial = copy.deepcopy(cfg)
        partial['scenes']['SY1']['anchors']['K01']['pos'] = None
        code, out = quiet_export(m, tmp, sb, script, partial)
        t.check('完整转缺项不保留旧可执行文件', code == 2 and 'E01-01/scene.py' not in out
                and 'E01-01/scene.py.todo' in out)
        t.check('旧版本保留为非执行备份', out.get('E01-01/scene.py.stale') == original)
        code, out = quiet_export(m, tmp, sb, script, cfg)
        t.check('补齐后清除旧待办', code == 0 and 'E01-01/scene.py' in out
                and 'E01-01/scene.py.todo' not in out)
        broken = copy.deepcopy(cfg)
        broken['scenes']['SY1']['anchors']['K01']['pose'] = 'invalid_pose'
        code, out = quiet_export(m, tmp, sb, script, broken)
        t.check('门违规不发布任何本批次脚本', code == 1 and not any(name.endswith('/scene.py') for name in out))
        report = json.loads(out['_report/report.json'])
        t.check('门违规报告不宣称生成完成', not any(p['complete'] for p in report['generated']))

    with tempfile.TemporaryDirectory() as tmp:
        quiet_export(m, tmp, sb, script, cfg)
        original = (Path(tmp) / 'E01-04/scene.py').read_text(encoding='utf-8')
        partial = copy.deepcopy(cfg)
        partial['scenes']['SY1']['anchors']['K01']['pos'] = None
        code, out = quiet_export(m, tmp, sb, script, partial, {'segment': 'E01-01'})
        t.check('局部重导出不影响其他段落', code == 2 and out.get('E01-04/scene.py') == original)

    with tempfile.TemporaryDirectory() as tmp:
        described = copy.deepcopy(single)
        seg = described['episodes'][0]['segments'][0]
        seg['blocking'] = '人物移动到门口'
        seg['cuts'][0]['cameraPosition'] = '背后俯视 60 度'
        seg['cuts'][0]['composition'] = '画面左侧三分之一'
        seg['cuts'][0]['note'] = '放下道具后离开'
        code, out = quiet_export(m, tmp, described, script, cfg)
        report = json.loads(out['_report/report.json'])
        fields = {field for w in report['unverified'] for field in w['fields']}
        t.check('不支持的构图动作逐项进入报告', code == 0
                and {'blocking', 'cameraPosition', 'composition', 'note'} <= fields
                and report['summary']['unverified'] == len(report['unverified']))
        t.check('报告新增对象遵守五字段限制', len(report) <= 5 and len(report['summary']) <= 5
                and all(len(w) <= 5 for w in report['unverified']))
        t.check('生成脚本明确标注未预演', '能力边界' in out['E01-01/scene.py']
                and 'cameraPosition' in out['E01-01/scene.py'])

    for selection in ({'segment': 'E99-99'}, {'ep': 99}):
        with tempfile.TemporaryDirectory() as tmp:
            try:
                quiet_export(m, tmp, sb, script, cfg, selection)
                code = 0
            except SystemExit as exc:
                code = exc.code
            t.check(f'空选择不误报成功 {selection}', code == 3)

    # 真实 CLI 参数包含 Windows 反斜杠，不能只测 --memory 的短命令。
    with tempfile.TemporaryDirectory() as tmp:
        command = [sys.executable, '-X', 'utf8', str(base / 'scripts/storyboard_to_shots.py'),
                   'export', '--storyboard', str(Path(m._fixture('synthetic/synthetic-storyboard.json'))),
                   '--script', str(Path(m._fixture('synthetic/synthetic-script.json'))),
                   '--config', str(Path(m._fixture('synthetic/synthetic-config.json'))), '--out', tmp]
        result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8',
                                errors='replace', timeout=30)
        t.check('真实路径命令行导出可解析脚本', result.returncode == 0,
                (result.stdout + result.stderr)[-1200:] if result.returncode else '')

    if blender:
        run_blender_smoke(m, t, blender, sb, script, cfg)
    else:
        print('  ! 未执行 Blender 检查；添加 selftest --blender blender 可运行实际场景和静帧测试。')


def run_blender_smoke(m, t, executable, sb, script, cfg):
    print('── Blender 实际执行测试 ──')
    blender = shutil.which(executable)
    if not blender:
        t.check('Blender 可执行文件存在', False, executable)
        return
    with tempfile.TemporaryDirectory(prefix='novel-previz-blender-') as tmp:
        code, out = quiet_export(m, tmp, sb, script, cfg)
        if code != 0:
            t.check('Blender 测试输入可导出', False, f'code={code}')
            return
        scenes = sorted(Path(tmp).glob('E*/scene.py'))
        for scene in scenes:
            for mode in ('audit', 'project'):
                command = [blender, '-b', '--python-exit-code', '1', '--python', str(scene), '--', mode]
                try:
                    result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8',
                                            errors='replace', timeout=90)
                    passed = result.returncode == 0
                    if mode == 'project':
                        passed = passed and f'{scene.parent.name}-f1' in result.stdout
                    detail = (result.stdout + result.stderr)[-1800:] if not passed else ''
                    t.check(f'Blender {scene.parent.name} {mode}', passed, detail)
                    if passed and 'KeyError' in result.stderr and 'rigify' in result.stderr:
                        print('  ! Rigify 注册有非致命偏好设置报错；本次模式继续完成。')
                except (OSError, subprocess.TimeoutExpired) as exc:
                    t.check(f'Blender {scene.parent.name} {mode}', False, str(exc))
        scene = scenes[0]
        review_dir = Path(tmp) / 'review'
        command = [blender, '-b', '--python-exit-code', '1', '--python', str(scene),
                   '--', 'review', str(review_dir)]
        try:
            result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8',
                                    errors='replace', timeout=120)
            images = list(review_dir.glob('*.png'))
            expected = len(sb['episodes'][0]['segments'][0]['cuts'])
            passed = result.returncode == 0 and 'STILLS_DONE' in result.stdout and len(images) == expected
            t.check('Blender 审片静帧逐镜生成', passed,
                    (result.stdout + result.stderr)[-1800:] if not passed else '')
            t.check('审片图片具有有效 PNG 文件头', bool(images) and all(
                image.read_bytes().startswith(bytes([137, 80, 78, 71, 13, 10, 26, 10])) for image in images))
        except (OSError, subprocess.TimeoutExpired) as exc:
            t.check('Blender 审片静帧逐镜生成', False, str(exc))
