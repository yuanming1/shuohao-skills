"""自有故事与临时目录的回归测试，不依赖其他技能或生成服务。"""
import base64
import copy
from decimal import Decimal
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import blocking


SKILL = Path(__file__).resolve().parent.parent
FIXTURE = SKILL / 'examples/雨棚取件-plan.json'
PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aG5cAAAAASUVORK5CYII=')


def source_board(package):
    """内存中模拟当前上游字段供适配测试；不借用上游技能的故事夹具。"""
    cuts = []
    for panel, plan in zip(package['panels'], package['planning']['shots']):
        cut = {'seconds': float(Decimal(panel['time'][1]) - Decimal(panel['time'][0])),
               'size': panel['size'], 'frame': panel['frame'], 'note': plan['continuity'], 'shot': plan['action']}
        cut.update(cameraPosition=plan['view']['position'], composition=plan['view']['composition'], eyeline=plan['view']['eyeline'])
        cuts.append(cut)
    segment = {'id': package['segment'], 'blocking': package['planning']['opening'], 'cuts': cuts,
               'h3Prompt': 'EXISTING VIDEO PROMPT — must remain unchanged during export'}
    return {'source': '雨棚取件', 'episodes': [{'ep': 1, 'segments': [segment]}]}


class BlockingTests(unittest.TestCase):
    def setUp(self):
        self.package = blocking.load_json(FIXTURE)
        self.board = source_board(self.package)
        self.segment = self.board['episodes'][0]['segments'][0]
        self.temp = tempfile.TemporaryDirectory(prefix='novel-storyboard-blocking-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root / 'output'

    def cli(self, *args, script=None, command='export'):
        return subprocess.run([sys.executable, '-X', 'utf8', str(script or SKILL / 'scripts/blocking.py'),
                               command, *map(str, args)], capture_output=True, text=True, encoding='utf-8', timeout=30)

    def from_plan(self, *args):
        return self.cli('--plan', FIXTURE, '--out', self.output, *args)

    def write_board(self):
        path = self.root / 'source.json'
        path.write_text(json.dumps(self.board, ensure_ascii=False), encoding='utf-8')
        return path

    def write_plan(self):
        path = self.root / 'dispatch-plan.json'
        path.write_text(json.dumps(self.package, ensure_ascii=False), encoding='utf-8')
        return path

    def directory(self, sid='E01-01'):
        return self.output / '_blocking-grid' / sid

    def test_own_fixture_and_export_contract(self):
        self.assertTrue(blocking.five_fields(self.package))
        self.assertEqual(blocking.validate_package(self.package), [])
        prompt = blocking.render_prompt(self.package)
        self.assertIn(self.package['planning']['opening'], prompt)
        for panel, plan in zip(self.package['panels'], self.package['planning']['shots']):
            self.assertIn(panel['frame'], prompt)
            self.assertIn(plan['continuity'], prompt)
            self.assertIn(plan['action'], prompt)
            for value in plan['view'].values():
                self.assertIn(value, prompt)
        self.assertIn('00:03.250-00:07.250', prompt)
        self.assertIn('00:07.250-00:09.750', prompt)
        self.assertIn('final 1 unused cells blank', prompt)
        self.assertIn('TEXT-ONLY INPUT', prompt)

    def test_adapter_preserves_all_source_data(self):
        original = copy.deepcopy(self.board)
        package, missing = blocking.make_package(self.segment, aspect='16:9')
        self.assertEqual(missing, [])
        self.assertTrue(blocking.five_fields(package))
        self.assertEqual(package['panels'], self.package['panels'])
        self.assertEqual(package['planning'], self.package['planning'])
        self.assertEqual(self.board, original)

    def test_each_missing_source_field_blocks_delivery(self):
        for field in ('frame', 'shot', 'note', 'cameraPosition', 'composition', 'eyeline', 'size'):
            with self.subTest(field=field):
                segment = copy.deepcopy(self.segment)
                segment['cuts'][0].pop(field)
                _, missing = blocking.make_package(segment)
                self.assertTrue(missing)
        self.segment.pop('blocking')
        _, missing = blocking.make_package(self.segment)
        self.assertTrue(any('blocking' in item for item in missing))

    def test_empty_continuity_labels_do_not_count_as_planning(self):
        self.segment['cuts'][0]['note'] = '起始：；动作：；结束：；接镜：'
        _, missing = blocking.make_package(self.segment)
        self.assertTrue(any('起始、动作、结束、接镜' in item for item in missing))

    def test_decimal_timing_and_invalid_durations(self):
        self.segment['cuts'][0]['seconds'] = 2.2501
        self.segment['cuts'][1]['seconds'] = 4.125
        package, missing = blocking.make_package(self.segment)
        self.assertFalse(missing)
        self.assertEqual(package['panels'][1]['time'], ['2.2501', '6.3751'])
        self.assertEqual(blocking.timecode('2.2501'), '00:02.2501')
        for value in (0, -1, True, float('nan'), float('inf')):
            with self.subTest(value=value):
                self.segment['cuts'][0]['seconds'] = value
                with self.assertRaises(ValueError):
                    blocking.make_package(self.segment)

    def test_plan_shot_mapping_timing_and_field_limits(self):
        for change in ('shot', 'time', 'extra', 'layout'):
            with self.subTest(change=change):
                package = copy.deepcopy(self.package)
                if change == 'shot':
                    package['planning']['shots'][1]['shot'] = 'E01-01-f3'
                elif change == 'time':
                    package['panels'][1]['time'][0] = '4'
                elif change == 'extra':
                    package['reserved'] = 'unused'
                else:
                    package['layout']['rows'] = 3
                with self.assertRaises(ValueError):
                    blocking.render_prompt(package)

    def test_native_frames_partial_input_and_ambiguity(self):
        frames = self.root / 'frames'
        (frames / 'E01-01').mkdir(parents=True)
        (frames / 'E01-01/f1.png').write_bytes(PNG)
        package, missing = blocking.make_package(self.segment, frames)
        self.assertFalse(missing)
        self.assertEqual(package['panels'][0]['reference'], str((frames / 'E01-01/f1.png').resolve()))
        self.assertIsNone(package['panels'][1]['reference'])
        (frames / 'E01-01-f1.jpg').write_bytes(PNG)
        _, missing = blocking.make_package(self.segment, frames)
        self.assertTrue(any('多个' in item for item in missing))
        (frames / 'E01-01-f1.jpg').unlink()
        (frames / 'E01-01/f1.png').write_bytes(b'')
        _, missing = blocking.make_package(self.segment, frames)
        self.assertTrue(any('为空' in item for item in missing))

    def test_cli_exports_without_images_and_is_deterministic(self):
        before = FIXTURE.read_bytes()
        result = self.from_plan()
        self.assertEqual(result.returncode, 0, result.stderr)
        prompt = (self.directory() / 'grid-prompt.txt').read_bytes()
        report = blocking.load_json(self.output / '_blocking-grid/index.json')
        self.assertTrue(blocking.five_fields(report))
        self.assertEqual(report['segments'][0]['status'], 'ready')
        result = self.from_plan()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(prompt, (self.directory() / 'grid-prompt.txt').read_bytes())
        self.assertEqual(prompt, (self.directory() / 'grid-prompt.txt.stale').read_bytes())
        self.assertEqual(FIXTURE.read_bytes(), before)
        self.assertFalse(list(self.output.rglob('*.png')))

    def test_cli_source_to_pending_to_recovery(self):
        path = self.write_board()
        args = ('--storyboard', path, '--out', self.output)
        before = path.read_bytes()
        result = self.cli(*args)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(path.read_bytes(), before)
        saved = self.segment['cuts'][0].pop('shot')
        self.write_board()
        result = self.cli(*args)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertTrue((self.directory() / 'grid.todo').exists())
        self.assertFalse((self.directory() / 'grid-prompt.txt').exists())
        self.assertTrue((self.directory() / 'grid-prompt.txt.stale').exists())
        self.segment['cuts'][0]['shot'] = saved
        self.write_board()
        result = self.cli(*args)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.directory() / 'grid.todo').exists())

    def test_local_export_does_not_touch_unselected_segments(self):
        second = copy.deepcopy(self.segment)
        second['id'] = 'E01-02'
        second['blocking'] = second['blocking'].replace('E01-01-f', 'E01-02-f')
        self.board['episodes'][0]['segments'].append(second)
        path = self.write_board()
        args = ('--storyboard', path, '--out', self.output)
        self.assertEqual(self.cli(*args).returncode, 0)
        untouched = (self.directory('E01-02') / 'grid-prompt.txt').read_bytes()
        self.segment['cuts'][0].pop('note')
        self.write_board()
        self.assertEqual(self.cli(*args, '--segment', 'E01-01').returncode, 2)
        self.assertEqual((self.directory('E01-02') / 'grid-prompt.txt').read_bytes(), untouched)
        self.assertFalse((self.directory('E01-02') / 'grid-prompt.txt.stale').exists())

    def test_single_shot_is_pending(self):
        self.segment['cuts'] = self.segment['cuts'][:1]
        _, missing = blocking.make_package(self.segment)
        self.assertTrue(any('一个镜头' in item for item in missing))

    def test_missing_frames_directory_withdraws_previous_output(self):
        path = self.write_board()
        args = ('--storyboard', path, '--out', self.output)
        self.assertEqual(self.cli(*args).returncode, 0)
        result = self.cli(*args, '--frames', self.root / 'missing')
        self.assertEqual(result.returncode, 3)
        self.assertFalse((self.directory() / 'grid-prompt.txt').exists())

    def test_source_collision_is_rejected_before_mutation(self):
        self.assertEqual(self.from_plan().returncode, 0)
        path = self.directory() / 'grid-input.json'
        before = path.read_bytes()
        result = self.cli('--plan', path, '--out', self.output)
        self.assertEqual(result.returncode, 3)
        self.assertEqual(path.read_bytes(), before)
        self.assertTrue((self.directory() / 'grid-prompt.txt').exists())

    def test_plan_reference_paths_resolve_from_input_directory(self):
        (self.root / 'reference.png').write_bytes(PNG)
        self.package['panels'][0]['reference'] = 'reference.png'
        path = self.root / 'plan.json'
        path.write_text(json.dumps(self.package, ensure_ascii=False), encoding='utf-8')
        result = self.cli('--plan', path, '--out', self.output)
        self.assertEqual(result.returncode, 0, result.stderr)
        output = blocking.load_json(self.directory() / 'grid-input.json')
        self.assertEqual(output['panels'][0]['reference'], str((self.root / 'reference.png').resolve()))
        (self.root / 'reference.png').unlink()
        self.assertEqual(self.cli('--plan', path, '--out', self.output).returncode, 2)
        self.assertFalse((self.directory() / 'grid-prompt.txt').exists())

    def test_invalid_selection_ids_and_duplicate_segments(self):
        with self.assertRaises(ValueError):
            blocking.selected_segments(self.board, segment='E99-99')
        with self.assertRaises(ValueError):
            blocking.selected_segments(self.board, ep=99)
        self.board['episodes'][0]['segments'].append(copy.deepcopy(self.segment))
        with self.assertRaises(ValueError):
            blocking.selected_segments(self.board)
        self.segment['id'] = '../escape'
        with self.assertRaises(ValueError):
            blocking.make_package(self.segment)

    def test_dispatch_legend_and_routes_are_consumed_without_schema_changes(self):
        prompt = blocking.render_prompt(self.package)
        self.assertIn('蓝色人偶 = C01 快递员', prompt)
        self.assertIn('橙色人偶 = C02 店员', prompt)
        self.assertIn('从西侧入口沿柜台外侧通道走到柜台外侧停下', prompt)
        self.assertTrue(blocking.five_fields(self.package))
        self.assertEqual(set(self.package['planning']), {'opening', 'shots'})

    def test_missing_ambiguous_or_wrong_segment_dispatch_is_pending(self):
        opening = self.package['planning']['opening']
        for updated in (
            opening.split('【调度人偶对应】')[0],
            opening.replace('橙色人偶', '蓝色人偶'),
            opening.replace('- C02 店员', '- C01 店员'),
            opening.replace('E01-01-f1', 'E02-01-f1'),
            opening.replace('【调度路径参考】', '旧路径标题'),
        ):
            with self.subTest(opening=updated):
                self.package['planning']['opening'] = updated
                self.assertTrue(blocking.validate_package(self.package))
        self.package['planning']['opening'] = opening

    def test_source_character_ids_must_be_covered(self):
        self.segment['cuts'][0]['characters'] = ['C01', 'C02', 'C03']
        _, missing = blocking.make_package(self.segment)
        self.assertTrue(any('C03' in item for item in missing))

    def test_no_people_or_stationary_segment_needs_no_invented_mannequins_or_arrows(self):
        from dispatch import read_dispatch
        for text in (
            '原开场事实。\n【调度人偶对应】\n本段无人出场。\n【调度路径参考】\n本段无人物位移。',
            '原开场事实。\n【调度人偶对应】\n- C01 快递员：蓝色人偶\n【调度路径参考】\n本段无人物位移。',
        ):
            _, _, missing = read_dispatch(text, ['E01-01-f1', 'E01-01-f2'])
            self.assertEqual(missing, [])

    def test_sync_dispatch_roundtrip_preserves_opening_shots_and_unknown_data(self):
        from dispatch import base_opening
        self.segment['blocking'] = base_opening(self.segment['blocking'])
        self.segment['cuts'][0]['characters'] = ['C01', 'C02']
        self.segment['projectNote'] = '已有项目数据必须保留'
        original = copy.deepcopy(self.board)
        source, plan = self.write_board(), self.write_plan()
        result = self.cli('--storyboard', source, '--plan', plan, command='sync-dispatch')
        self.assertEqual(result.returncode, 0, result.stderr)
        updated = blocking.load_json(source)
        target = updated['episodes'][0]['segments'][0]
        self.assertEqual(target['blocking'], self.package['planning']['opening'])
        self.assertEqual(base_opening(target['blocking']), original['episodes'][0]['segments'][0]['blocking'])
        target['blocking'] = original['episodes'][0]['segments'][0]['blocking']
        self.assertEqual(updated, original)
        # 再次同步保持幂等，导出从正式 blocking 读取同一份映射和路径。
        before = source.read_bytes()
        self.assertEqual(self.cli('--storyboard', source, '--plan', plan, command='sync-dispatch').returncode, 0)
        self.assertEqual(source.read_bytes(), before)
        result = self.cli('--storyboard', source, '--out', self.output)
        self.assertEqual(result.returncode, 0, result.stderr)
        package = blocking.load_json(self.directory() / 'grid-input.json')
        self.assertEqual(package['planning']['opening'], self.package['planning']['opening'])
        self.assertFalse(list(source.parent.glob('source.json.*.tmp')))

    def test_sync_rejects_stale_or_changed_scene_contract_without_writing(self):
        source = self.write_board()
        before = source.read_bytes()
        for change in ('opening', 'frame', 'action', 'time'):
            with self.subTest(change=change):
                self.package = blocking.load_json(FIXTURE)
                if change == 'opening':
                    self.package['planning']['opening'] = self.package['planning']['opening'].replace('入口位于西侧', '入口位于东侧')
                elif change == 'frame':
                    self.package['panels'][0]['frame'] += '新增人物。'
                elif change == 'action':
                    self.package['planning']['shots'][0]['action'] += '新增移动。'
                else:
                    self.package['panels'][-1]['time'][1] = '10'
                result = self.cli('--storyboard', source, '--plan', self.write_plan(), command='sync-dispatch')
                self.assertEqual(result.returncode, 3, result.stderr)
                self.assertEqual(source.read_bytes(), before)

    def test_sync_pending_material_does_not_write(self):
        source = self.write_board()
        before = source.read_bytes()
        self.package['planning']['opening'] = '只有原开场，尚未分配人偶颜色。'
        result = self.cli('--storyboard', source, '--plan', self.write_plan(), command='sync-dispatch')
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(source.read_bytes(), before)

    def test_sync_checks_cross_segment_role_colors_and_names(self):
        second = copy.deepcopy(self.segment)
        second['id'] = 'E01-02'
        second['blocking'] = second['blocking'].replace('E01-01-f', 'E01-02-f').replace('蓝色人偶', '绿色人偶')
        self.board['episodes'][0]['segments'].append(second)
        source, plan = self.write_board(), self.write_plan()
        before = source.read_bytes()
        result = self.cli('--storyboard', source, '--plan', plan, command='sync-dispatch')
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertEqual(source.read_bytes(), before)

    def test_sync_rejects_missing_source_role_even_when_plan_has_no_character_field(self):
        self.segment['cuts'][0]['characters'] = ['C03']
        source, plan = self.write_board(), self.write_plan()
        before = source.read_bytes()
        result = self.cli('--storyboard', source, '--plan', plan, command='sync-dispatch')
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertEqual(source.read_bytes(), before)

    def test_export_with_conflicting_cross_segment_colors_is_pending(self):
        second = copy.deepcopy(self.segment)
        second['id'] = 'E01-02'
        second['blocking'] = second['blocking'].replace('E01-01-f', 'E01-02-f').replace('蓝色人偶', '绿色人偶')
        self.board['episodes'][0]['segments'].append(second)
        result = self.cli('--storyboard', self.write_board(), '--segment', 'E01-01', '--out', self.output)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertFalse((self.directory() / 'grid-prompt.txt').exists())
        self.assertTrue((self.directory() / 'grid.todo').exists())

    def test_sync_changes_only_target_segment(self):
        from dispatch import base_opening
        second = copy.deepcopy(self.segment)
        second['id'] = 'E01-02'
        second['blocking'] = base_opening(second['blocking'])
        self.board['episodes'][0]['segments'].append(second)
        original = copy.deepcopy(second)
        source = self.write_board()
        result = self.cli('--storyboard', source, '--plan', self.write_plan(), command='sync-dispatch')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(blocking.load_json(source)['episodes'][0]['segments'][1], original)

    def test_portable_without_sibling_skills(self):
        portable = self.root / 'standalone'
        shutil.copytree(SKILL, portable, ignore=shutil.ignore_patterns('__pycache__'))
        result = self.cli('--plan', portable / 'examples/雨棚取件-plan.json', '--out', self.output,
                          script=portable / 'scripts/blocking.py')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.directory() / 'grid-prompt.txt').read_text(encoding='utf-8'), blocking.render_prompt(self.package))
        # 模板缺少空间插槽时不能继续发布貌似完整的普通宫格。
        template = portable / 'references/locked-blocking-grid-template.txt'
        template.write_text(template.read_text(encoding='utf-8').replace('$opening', ''), encoding='utf-8')
        result = self.cli('--plan', portable / 'examples/雨棚取件-plan.json', '--out', self.output,
                          script=portable / 'scripts/blocking.py')
        self.assertEqual(result.returncode, 3)
        self.assertFalse((self.directory() / 'grid-prompt.txt').exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
