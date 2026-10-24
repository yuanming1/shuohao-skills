import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import { reviewBoards, gateChecks, parseModes, renderReview } from './enhance.mjs';
import { board, enhanced, compositionEnhanced, prompt } from '../examples/storyboards.mjs';

let count = 0;
function test(name, run) {
  try { run(); count++; }
  catch (error) { throw new Error(`${name}: ${error.message}`, { cause: error }); }
}
const requiredModes = 'performance,camera';
const modes = `${requiredModes},effects`;
const segment = (value) => value.episodes[0].segments[0];
const first = (value) => segment(value).cuts[0];
const mutate = (change) => { const value = board(); change(value); return value; };
const hasGate = (result, gate) => gateChecks(result).find((item) => item.id === gate).issues.length > 0;
const review = (change, selected = modes) => reviewBoards(board(), mutate(change), selected);
const addReason = (cut) => { cut.note += '增强依据：本镜原有反应缺乏触发，细化视线以明确注意力变化。'; };

test('独立案例完整通过，保护输入且所有方向有实际修改', () => {
  const original = board();
  const revised = enhanced();
  const oldSnapshot = JSON.stringify(original);
  const newSnapshot = JSON.stringify(revised);
  const result = reviewBoards(original, revised, modes);
  assert.deepEqual(result.violations, []);
  assert.deepEqual(result.attention, []);
  assert.equal(JSON.stringify(original), oldSnapshot);
  assert.equal(JSON.stringify(revised), newSnapshot);
  assert.deepEqual(result.impact.spatial, ['E01-01/f3']);
});

test('保留原稿也是合法选择，不强制增加增强说明', () => {
  const result = reviewBoards(board(), board(), requiredModes);
  assert.deepEqual(result.violations, []);
  assert.deepEqual(result.attention, []);
  assert.equal(result.changes.length, 0);
});

test('多镜构图示例同步三镜，保留原合同且允许全组固定摄影', () => {
  const original = board();
  const snapshot = structuredClone(original);
  const revised = compositionEnhanced();
  const result = reviewBoards(original, revised, modes);
  assert.deepEqual(result.violations, []);
  assert.deepEqual(result.attention, []);
  assert.deepEqual(original, snapshot);
  assert.deepEqual(result.impact.spatial, ['E01-01/f1', 'E01-01/f2', 'E01-01/f3']);
  assert.ok(segment(revised).cuts.every((cut) => cut.camera === 'Static Shot'));
  assert.equal(segment(revised).cuts[2].size, 'wide');
  for (const [index, cut] of segment(revised).cuts.entries()) {
    assert.ok(cut.note.startsWith(segment(original).cuts[index].note));
  }
});

for (const [name, change] of [
  ['时长', (value) => { first(value).seconds = 3; }],
  ['节拍', (value) => { first(value).beats = [1, 2]; }],
  ['人物引用', (value) => { first(value).characters = ['C01']; }],
  ['道具引用', (value) => { first(value).props = []; }],
  ['场次', (value) => { segment(value).sceneIndex = 2; }],
  ['开场站位', (value) => { segment(value).blocking = '人物换位。'; }],
  ['段号', (value) => { segment(value).id = 'E01-02'; }],
  ['镜头数量', (value) => { segment(value).cuts.pop(); }],
  ['镜头顺序', (value) => { segment(value).cuts.reverse(); }],
  ['新增能力字段', (value) => { segment(value).abilities = ['fire']; }],
  ['未知字段', (value) => { value.custom = { reserved: true }; }],
  ['段级配乐', (value) => { segment(value).music = '强鼓点'; }],
]) test(`保护${name}`, () => assert.ok(hasGate(review(change), 'G02')));

test('未知既有数据保持，不能为了增强删除', () => {
  const original = board(); original.custom = { values: ['opaque'] };
  const revised = structuredClone(original);
  assert.deepEqual(reviewBoards(original, revised, modes).violations, []);
  delete revised.custom;
  assert.ok(hasGate(reviewBoards(original, revised, modes), 'G02'));
});

for (const field of ['size', 'camera', 'lens', 'cameraPosition', 'composition', 'focus', 'stability']) {
  test(`两项必选范围允许摄影修改 ${field}，保留材料与同步检查`, () => {
    const result = review((value) => {
      first(value)[field] = field === 'size' ? 'close' : field === 'camera' ? 'Push In' : field === 'stability' ? 'handheld' : '新的摄影安排';
    }, requiredModes);
    assert.ok(!hasGate(result, 'G03'));
    assert.ok(hasGate(result, 'G04'));
    assert.ok(hasGate(result, 'G06'));
  });
}

test('表演可以修改已有视线并同步', () => {
  const result = review((value) => {
    first(value).eyeline = '提醒之后看向师父'; addReason(first(value));
    segment(value).h3Prompt = prompt('After the reminder she looks toward the mentor.');
  }, requiredModes);
  assert.deepEqual(result.violations, []);
  assert.deepEqual(result.attention, []);
});

for (const [field, invalid] of [['camera', 'Dolly Arc Combo'], ['size', 'portrait'], ['stability', 'floating']]) {
  test(`拒绝无效枚举 ${field}`, () => assert.ok(hasGate(review((value) => { first(value)[field] = invalid; }), 'G03')));
}
for (const invalid of ['', null, 1]) {
  test(`拒绝空值或错误类型 ${invalid}`, () => assert.ok(hasGate(review((value) => { first(value).shot = invalid; }), 'G03')));
}
test('不能删除正文', () => assert.ok(hasGate(review((value) => { delete first(value).shot; }), 'G03')));
test('不能补造缺失的必要摄影字段', () => {
  const original = board(); delete first(original).focus;
  const revised = structuredClone(original); first(revised).focus = '锁定灯芯'; addReason(first(revised));
  assert.ok(hasGate(reviewBoards(original, revised, requiredModes), 'G03'));
});
test('摄影变动时暴露原稿缺少的其他摄影资料', () => {
  const original = board(); delete first(original).lens;
  const revised = structuredClone(original); first(revised).camera = 'Push In'; addReason(first(revised));
  assert.ok(hasGate(reviewBoards(original, revised, requiredModes), 'G04'));
});
test('两项必选范围允许补充已同步的摄影受光说明', () => {
  const result = review((value) => {
    first(value).lighting = '既有灯芯照亮石面'; addReason(first(value));
    segment(value).h3Prompt = prompt('The existing light falls on the nearby stone.');
  }, requiredModes);
  assert.deepEqual(result.violations, []);
  assert.deepEqual(result.attention, []);
});

for (const tag of ['起始', '动作', '结束', '接镜', '增强依据']) {
  test(`受影响切缺少 ${tag} 不通过材料门`, () => {
    const revised = enhanced();
    first(revised).note = first(revised).note.replace(new RegExp(`${tag}：[^；;\\n]*`), '');
    assert.ok(hasGate(reviewBoards(board(), revised, modes), 'G04'));
  });
}
test('空标签不能代替实际依据', () => assert.ok(hasGate(review((value) => {
  first(value).note = '起始： ；动作： ；结束： ；接镜： ；增强依据： ；';
}), 'G04')));
test('没有改动的其他切不强制重写备注', () => {
  const result = review((value) => { addReason(first(value)); });
  assert.deepEqual(result.violations, []);
});
test('只改 H3 时也需要对应切的依据', () => assert.ok(hasGate(review((value) => {
  segment(value).h3Prompt = prompt('She returns her gaze to the lamp.');
}), 'G04')));
test('只改段级声音时所有切也需复核材料', () => assert.ok(hasGate(review((value) => {
  segment(value).soundscape = '灯鸣持续';
}), 'G04')));

for (const [name, from, to] of [
  ['对齐首行', 'How the reference pictures align', 'Other reference alignment'],
  ['台词', '先稳住。', '别害怕。'], ['说话人', '(S1)', '(S3)'],
  ['图片', '<Picture 1>', '<Picture 3>'], ['切点', '00:04.000', '00:03.000'],
  ['字段顺序', 'overall_soundscape:', 'other_soundscape:'],
  ['配乐', 'non_diegetic_music: N/A', 'non_diegetic_music: Drums'],
]) test(`保护 H3 ${name}`, () => assert.ok(hasGate(review((value) => {
  segment(value).h3Prompt = prompt().replace(from, to);
}), 'G05')));
test('台词不能移动到另一切', () => assert.ok(hasGate(review((value) => {
  segment(value).h3Prompt = prompt().replace('<d>[Chinese] 先稳住。</d>', '').replace('<Picture 2>', '<Picture 2> <d>[Chinese] 先稳住。</d>');
}), 'G05')));
test('台词不能移到音景里', () => assert.ok(hasGate(review((value) => {
  segment(value).h3Prompt = prompt().replace('<d>[Chinese] 我来。</d>', '').replace('overall_soundscape:', 'overall_soundscape: <d>[Chinese] 我来。</d>');
}), 'G05')));
test('中文 H3 同样支持同步与保护', () => {
  const original = board();
  segment(original).h3Prompt = '原对齐行。\n整体视听描述：\n[镜头 1] <Picture 1> 保持悬掌。\n[镜头 2] 于 00:04.000，<Picture 2> 环纹亮起。\n[镜头 3] 于 00:08.000，<Picture 3> 灯芯持续发光。\n整体音景：门廊外风声。\n非叙事配乐：无';
  const revised = structuredClone(original);
  first(revised).shot = '固定镜头，提醒之后把目光移回灯沿。'; addReason(first(revised));
  segment(revised).h3Prompt = segment(revised).h3Prompt.replace('保持悬掌。', '保持悬掌，提醒之后看回灯沿。');
  assert.deepEqual(reviewBoards(original, revised, requiredModes).attention, []);
  assert.deepEqual(reviewBoards(original, revised, requiredModes).violations, []);
});

test('另一镜的 H3 修改不能掩盖本镜漏同步', () => {
  const result = review((value) => {
    first(value).shot = '固定镜头，先看师父再回看灯沿。';
    segment(value).h3Prompt = prompt(undefined, 'The lamp glow reaches the existing stone surface.');
  });
  assert.ok(result.attention.some((item) => item.includes('E01-01/f1')));
});
test('H3 单边改变也会提醒另一消费端', () => assert.ok(hasGate(review((value) => {
  segment(value).h3Prompt = prompt('She returns her gaze to the lamp.');
}), 'G06')));
test('只有备注变化不会要求正文机械改写', () => assert.ok(!hasGate(review((value) => { addReason(first(value)); }), 'G06')));
test('补音效但 H3 没变会提醒', () => assert.ok(hasGate(review((value) => { first(value).sfx = '灯鸣'; }), 'G06')));
test('H3 声景单边改变会提醒', () => assert.ok(hasGate(review((value) => {
  segment(value).h3Prompt = prompt().replace('Wind outside', 'Soft wind outside');
}), 'G06')));
test('多行 H3 声景的后续行也被核对', () => {
  const original = board(); segment(original).h3Prompt = prompt().replace('Wind outside', '\nWind outside')
    .replace('; the existing lamp hums', ';\nthe existing lamp hums');
  const revised = structuredClone(original); segment(revised).h3Prompt = segment(revised).h3Prompt.replace('the existing lamp hums', 'the lamp hum grows');
  assert.ok(hasGate(reviewBoards(original, revised, modes), 'G06'));
});
test('两端声景同步后不再提示单边改动', () => {
  const result = review((value) => {
    segment(value).soundscape = '门廊外风声，灯芯亮起后灯鸣持续。';
    segment(value).h3Prompt = prompt().replace('Wind outside', 'Steady wind outside');
    segment(value).cuts.forEach(addReason);
  }, modes);
  assert.deepEqual(result.violations, []);
  assert.deepEqual(result.attention, []);
});
test('H3 修改跨段边界列出相邻切', () => {
  const original = board();
  const next = structuredClone(segment(original)); next.id = 'E01-02'; original.episodes[0].segments.push(next);
  const revised = structuredClone(original);
  segment(revised).h3Prompt = prompt(undefined, undefined, 'A slower pull out reveals the lit path.');
  const result = reviewBoards(original, revised, requiredModes);
  assert.ok(result.impact.neighbors.includes('E01-02/f1'));
});

for (const invalid of [undefined, '', 'all', 'performance,performance', 'camera,']) {
  test(`范围无效 ${invalid}`, () => assert.throws(() => parseModes(invalid)));
}
for (const selected of ['performance', 'camera', 'effects', 'performance,effects', 'camera,effects']) {
  test(`缺少必选方向时拒绝比较 ${selected}`, () => {
    assert.throws(() => reviewBoards(board(), board(), selected), /缺少必选增强方向/);
  });
}
test('表演与摄影可独立于可选特效完成比较', () => {
  const original = board();
  const revised = enhanced();
  segment(revised).cuts[1] = structuredClone(segment(original).cuts[1]);
  segment(revised).h3Prompt = segment(revised).h3Prompt.replace(
    /^\[Shot 2\].*$/m, segment(original).h3Prompt.match(/^\[Shot 2\].*$/m)[0]);
  const result = reviewBoards(original, revised, requiredModes);
  assert.deepEqual(result.modes, ['performance', 'camera']);
  assert.deepEqual(result.violations, []);
  assert.deepEqual(result.attention, []);
  assert.ok(result.changes.some((change) => change.path.endsWith('/eyeline')));
  assert.ok(result.changes.some((change) => change.path.endsWith('/camera')));
  assert.deepEqual(segment(revised).cuts[1], segment(original).cuts[1]);
});
test('必选范围允许不同顺序和空格', () => {
  assert.deepEqual(parseModes(' camera, performance '), ['camera', 'performance']);
  assert.deepEqual(parseModes('effects, camera, performance'), ['effects', 'camera', 'performance']);
});
test('空输入不算通过', () => assert.throws(() => reviewBoards({ episodes: [] }, board(), modes), /G01/));
test('重复段号不算通过', () => {
  const value = board(); value.episodes[0].segments.push(structuredClone(segment(value)));
  assert.throws(() => reviewBoards(value, value, modes), /唯一/);
});
test('报告不把结构通过当成表演通过', () => {
  const text = renderReview(reviewBoards(board(), board(), modes));
  assert.match(text, /不证明剧情/);
  assert.match(text, /待完成的语义复核/);
  assert.match(text, /没有要求为了增强而改写/);
});
test('提示词含围栏时报告保留原文', () => {
  const text = renderReview(review((value) => { first(value).note += '\n```text\n原有备注\n```'; }));
  assert.match(text, /````text/);
});

const folder = fs.mkdtempSync(path.join(os.tmpdir(), 'storyboard-enhance-'));
const cli = fileURLToPath(new URL('./enhance.mjs', import.meta.url));
const beforePath = path.join(folder, 'before.json');
const afterPath = path.join(folder, 'after.json');
const outPath = path.join(folder, 'review.md');
const writeBoards = () => { fs.writeFileSync(beforePath, JSON.stringify(board())); fs.writeFileSync(afterPath, JSON.stringify(enhanced())); };
const run = (...args) => spawnSync(process.execPath, [cli, ...args], { encoding: 'utf8' });
const args = ['review', '--before', beforePath, '--after', afterPath, '--modes', modes];
try {
  writeBoards();
  test('命令报告写入且输入只读', () => {
    const original = fs.readFileSync(beforePath, 'utf8');
    const revised = fs.readFileSync(afterPath, 'utf8');
    const result = run(...args, '--out', outPath);
    assert.equal(result.status, 0, result.stderr);
    assert.ok(fs.readFileSync(outPath, 'utf8').includes('G06'));
    assert.equal(fs.readFileSync(beforePath, 'utf8'), original);
    assert.equal(fs.readFileSync(afterPath, 'utf8'), revised);
  });
  test('拒绝覆盖既有报告', () => {
    const saved = fs.readFileSync(outPath, 'utf8');
    assert.equal(run(...args, '--out', outPath).status, 1);
    assert.equal(fs.readFileSync(outPath, 'utf8'), saved);
  });
  test('拒绝用输入文件作为报告覆盖目标', () => {
    const saved = fs.readFileSync(beforePath, 'utf8');
    assert.equal(run(...args, '--out', beforePath).status, 1);
    assert.equal(fs.readFileSync(beforePath, 'utf8'), saved);
  });
  test('只读体检也需两个独立文件', () => assert.equal(run('review', '--before', beforePath, '--after', beforePath, '--modes', requiredModes).status, 1));
  test('保护相对素材路径基准', () => {
    const nested = path.join(folder, 'other'); fs.mkdirSync(nested);
    const elsewhere = path.join(nested, 'after.json'); fs.copyFileSync(afterPath, elsewhere);
    assert.equal(run('review', '--before', beforePath, '--after', elsewhere, '--modes', modes).status, 1);
  });
  test('同步未处理时命令返回 2', () => {
    fs.writeFileSync(afterPath, JSON.stringify(mutate((value) => { first(value).shot += '学徒看回灯沿。'; addReason(first(value)); })));
    assert.equal(run(...args).status, 2);
  });
  test('JSON 输入错误返回 1', () => { fs.writeFileSync(afterPath, '{broken'); assert.equal(run(...args).status, 1); writeBoards(); });
  test('BOM 输入可读', () => { fs.writeFileSync(afterPath, '\uFEFF' + JSON.stringify(enhanced())); assert.equal(run(...args).status, 0); });
  test('拒绝缺少方向参数', () => assert.equal(run(...args.slice(0, -2)).status, 1));
  for (const selected of ['performance', 'camera', 'effects', 'performance,effects', 'camera,effects']) {
    test(`命令拒绝缺少必选方向且不创建报告 ${selected}`, () => {
      const rejectedPath = path.join(folder, `rejected-${selected}.md`);
      const result = run(...args.slice(0, -1), selected, '--out', rejectedPath);
      assert.equal(result.status, 1);
      assert.match(result.stderr, /缺少必选增强方向/);
      assert.ok(!fs.existsSync(rejectedPath));
    });
  }
  test('命令允许不选择特效', () => {
    fs.writeFileSync(afterPath, JSON.stringify(board()));
    const result = run(...args.slice(0, -1), requiredModes);
    assert.equal(result.status, 0, result.stderr);
    writeBoards();
  });
  test('拒绝重复参数', () => assert.equal(run(...args, '--modes', 'camera').status, 1));
  test('帮助可读', () => assert.equal(run('--help').status, 0));
} finally {
  fs.rmSync(folder, { recursive: true, force: true });
}

process.stdout.write(`novel-storyboard-enhance: ${count} tests passed\n`);
