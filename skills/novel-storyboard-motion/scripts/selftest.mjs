import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import { reviewBoards, renderReview, gateChecks } from './motion.mjs';

let count = 0;
function test(name, run) {
  try { run(); count++; }
  catch (error) { throw new Error(`${name}: ${error.message}`, { cause: error }); }
}
const prompt = (first = 'A offers the radio.', second = 'B switches it on.') =>
  'Reference alignment stays unchanged.\n\nintegrated_multimodal_description:\n'
  + `[Shot 1] <Picture 1> (S1) ${first} <d>[Chinese] 修好了，路上慢点。</d>\n`
  + `[Shot 2] At 00:04.000, <Picture 2> (S2) ${second} <d>[Chinese] 谢谢。</d>\n\n`
  + 'overall_soundscape: Handle rustle.\n\nnon_diegetic_music: N/A';
const cut = (frame, shot, beat) => ({ seconds: 4, beats: [beat, beat], frame, shot,
  note: '起始：保持当前持物；动作：完成本镜事件；结束：记录动作终态；接镜：继续既定状态。' });
const board = () => ({
  source: '末班修理铺',
  episodes: [{ ep: 1, segments: [{ id: 'E01-01', sceneIndex: 1, h3Prompt: prompt(), cuts: [
    cut('许宁持有收音机。', '修理师递出收音机。', 1),
    cut('陈卓左手持有收音机。', '司机按下开关。', 2),
  ] }, { id: 'E01-02', sceneIndex: 1,
    h3Prompt: 'For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.\n\nintegrated_multimodal_description:\n[Shot 1] <Picture 1> At a static shot, the driver pushes the hinged door outward.\n\noverall_soundscape: Hinge creak.\n\nnon_diegetic_music: N/A',
    cuts: [cut('司机在门侧。', '司机推门。', 3)] }] }],
});
const mutate = (change) => { const value = board(); change(value); return value; };
const segment = (value) => value.episodes[0].segments[0];
const first = (value) => segment(value).cuts[0];

test('相同数据仍要求语义复核', () => {
  const result = reviewBoards(board(), board());
  assert.equal(result.changes.length, 0);
  assert.match(renderReview(result), /不代表原稿动作已经正确/);
});
test('同步正文与 H3 可以修订，输入保持不变', () => {
  const original = board();
  const snapshot = JSON.stringify(original);
  const revised = structuredClone(original);
  first(revised).shot = '司机接过重量后，修理师松手。';
  segment(revised).h3Prompt = prompt('The driver takes the weight before the repairer releases.');
  const result = reviewBoards(original, revised);
  assert.deepEqual(result.violations, []);
  assert.equal(result.changes.length, 2);
  assert.equal(JSON.stringify(original), snapshot);
});
test('备注与声音可补充', () => {
  const revised = mutate((value) => { first(value).note = '起始：持有；动作：递交；结束：接住；接镜：保持。'; first(value).sfx = '提手轻响'; segment(value).soundscape = '室内底噪'; });
  assert.equal(reviewBoards(board(), revised).violations.length, 0);
});
test('切点描述变化列出关键帧', () => {
  const result = reviewBoards(board(), mutate((value) => { first(value).frame = '左手尚未接触提手。'; }));
  assert.deepEqual(result.frames, ['E01-01/f1']);
  assert.ok(result.attention.some((item) => item.includes('H3 未变')));
});
test('跨段边界加入连读范围', () => {
  const result = reviewBoards(board(), mutate((value) => { segment(value).cuts[1].note += '接镜保持左手持有。'; }));
  assert.deepEqual(result.neighbors, ['E01-01/f1', 'E01-01/f2', 'E01-02/f1']);
});
for (const [name, change] of [
  ['时长', (value) => { first(value).seconds = 5; }],
  ['节拍', (value) => { first(value).beats = [1, 2]; }],
  ['镜号', (value) => { segment(value).id = 'E01-03'; }],
  ['段落数量', (value) => { value.episodes[0].segments.pop(); }],
  ['镜头数量', (value) => { segment(value).cuts.pop(); }],
  ['未知字段增加', (value) => { first(value).newMotion = 'reserved'; }],
  ['场次', (value) => { segment(value).sceneIndex = 2; }],
]) test(`保护${name}`, () => assert.ok(reviewBoards(board(), mutate(change)).violations.length));

test('未知既有字段原样保留', () => {
  const original = board(); original.custom = { opaque: ['keep'] };
  const revised = structuredClone(original); first(revised).note += '补充承重安排。';
  assert.deepEqual(reviewBoards(original, revised).violations, []);
  revised.custom.opaque[0] = 'changed';
  assert.ok(reviewBoards(original, revised).violations.length);
});
for (const replacement of ['', null, 42]) test(`拒绝正文值 ${replacement}`, () => {
  assert.ok(reviewBoards(board(), mutate((value) => { first(value).shot = replacement; })).violations.length);
});
test('正文不允许删除', () => {
  assert.ok(reviewBoards(board(), mutate((value) => { delete first(value).shot; })).violations.length);
});
test('不能冒充补齐原来缺失的协议正文', () => {
  const original = board(); delete segment(original).h3Prompt;
  const revised = structuredClone(original); segment(revised).h3Prompt = prompt();
  assert.ok(reviewBoards(original, revised).violations.length);
});
for (const [name, from, to] of [
  ['对齐行', 'Reference alignment stays unchanged.', 'Other alignment.'],
  ['切点', '00:04.000', '00:03.000'],
  ['图片绑定', '<Picture 1>', '<Picture 3>'],
  ['台词', '修好了，路上慢点。', '修好了。'],
  ['说话人标记', '(S1)', '(S2)'],
  ['字段标题', 'overall_soundscape:', 'soundscape:'],
  ['配乐', 'non_diegetic_music: N/A', 'non_diegetic_music: Drums'],
  ['镜头标记', '[Shot 2]', '[Shot 3]'],
]) test(`保护 H3 ${name}`, () => {
  assert.ok(reviewBoards(board(), mutate((value) => { segment(value).h3Prompt = prompt().replace(from, to); })).violations.length);
});
test('台词不能换镜头，即使总台词列表不变', () => {
  const revised = mutate((value) => { segment(value).h3Prompt = prompt().replace(' <d>[Chinese] 修好了，路上慢点。</d>', '').replace('<Picture 2>', '<Picture 2> <d>[Chinese] 修好了，路上慢点。</d>'); });
  assert.ok(reviewBoards(board(), revised).violations.length);
});
test('台词不能移到最后一镜之外的声景字段', () => {
  const revised = mutate((value) => { segment(value).h3Prompt = prompt().replace(' <d>[Chinese] 谢谢。</d>', '').replace('overall_soundscape:', 'overall_soundscape: <d>[Chinese] 谢谢。</d>'); });
  assert.ok(reviewBoards(board(), revised).violations.length);
});
test('中文 H3 同样保护配乐和标记', () => {
  const original = board();
  segment(original).h3Prompt = '参考图与目标视频的对齐——保持原文。\n整体视听描述：\n[镜头 1] <Picture 1> 递交。\n[镜头 2] 于 00:04.000，<Picture 2> 按键。\n整体音景：室内底噪\n非叙事配乐：无';
  const revised = structuredClone(original);
  segment(revised).h3Prompt = segment(revised).h3Prompt.replace('递交。', '接住重量后松手。');
  assert.deepEqual(reviewBoards(original, revised).violations, []);
  segment(revised).h3Prompt = segment(revised).h3Prompt.replace('非叙事配乐：无', '非叙事配乐：鼓声');
  assert.ok(reviewBoards(original, revised).violations.length);
});
test('空分镜不是合法的已完成任务', () => assert.throws(() => reviewBoards({ episodes: [] }, board()), /非空/));
test('段号不能重复', () => assert.throws(() => reviewBoards(board(), mutate((value) => { value.episodes[0].segments[1].id = 'E01-01'; })), /唯一/));
test('Markdown 代码围栏保留原始提示词', () => {
  const result = reviewBoards(board(), mutate((value) => { first(value).note = '```text\n保留备注\n```'; }));
  assert.match(renderReview(result), /````text\n```text/);
});
test('报告逐项列出六道程序门', () => {
  const result = reviewBoards(board(), board());
  assert.deepEqual(gateChecks(result).map((gate) => gate.id), ['G01', 'G02', 'G03', 'G04', 'G05', 'G06']);
  assert.ok(gateChecks(result).every((gate) => gate.issues.length === 0));
  assert.match(renderReview(result), /G04.*正文与逐切编排材料.*通过/);
});
for (const field of ['frame', 'shot']) test(`两稿都缺 ${field} 也不能通过`, () => {
  const original = board(); delete first(original)[field];
  assert.ok(reviewBoards(original, structuredClone(original)).violations.some((item) => item.startsWith('[G04]')));
});
for (const tag of ['起始', '动作', '结束', '接镜']) test(`编排缺少 ${tag} 时材料门失败`, () => {
  const revised = mutate((value) => { first(value).note = first(value).note.replace(new RegExp(`${tag}：[^；。]+[；。]?`), ''); });
  assert.ok(reviewBoards(board(), revised).violations.some((item) => item.startsWith('[G04]')));
});
test('四段标签只有空内容也不能通过', () => {
  const revised = mutate((value) => { first(value).note = '起始：；动作：；结束：；接镜：'; });
  assert.equal(reviewBoards(board(), revised).violations.filter((item) => item.startsWith('[G04]')).length, 4);
});
test('不能把下一个标签当作上一段内容', () => {
  const revised = mutate((value) => { first(value).note = '起始：动作：结束：接镜：保持。'; });
  assert.equal(reviewBoards(board(), revised).violations.filter((item) => item.startsWith('[G04]')).length, 3);
});
test('支持英文冒号的四段说明', () => {
  const revised = mutate((value) => { first(value).note = first(value).note.replaceAll('：', ':'); });
  assert.deepEqual(reviewBoards(board(), revised).violations, []);
});
test('两稿都缺 H3 时不能通过', () => {
  const original = board(); delete segment(original).h3Prompt;
  assert.ok(reviewBoards(original, structuredClone(original)).violations.some((item) => item.startsWith('[G05]')));
});
test('原来缺少 note 时可以补齐', () => {
  const original = board(); delete first(original).note;
  const revised = structuredClone(original); first(revised).note = first(board()).note;
  assert.deepEqual(reviewBoards(original, revised).violations, []);
});
test('H3 声景不能掩盖镜头块缺失', () => {
  const original = mutate((value) => { segment(value).h3Prompt = prompt().replace(/^\[Shot 2\].*\n/m, ''); });
  assert.ok(reviewBoards(original, structuredClone(original)).violations.some((item) => item.includes('镜头块数量')));
});
test('未修改的原始错误切点也能检出', () => {
  const original = mutate((value) => { segment(value).h3Prompt = prompt().replace('00:04.000', '00:03.000'); });
  assert.ok(reviewBoards(original, structuredClone(original)).violations.some((item) => item.includes('切点开头')));
});
test('未修改的原始缺失图片绑定也能检出', () => {
  const original = mutate((value) => { segment(value).h3Prompt = prompt().replace('<Picture 2>', ''); });
  assert.ok(reviewBoards(original, structuredClone(original)).violations.some((item) => item.includes('对应图片绑定')));
});
test('未修改的原始缺失字段标题也能检出', () => {
  const original = mutate((value) => { segment(value).h3Prompt = prompt().replace('overall_soundscape:', ''); });
  assert.ok(reviewBoards(original, structuredClone(original)).violations.some((item) => item.includes('三个字段')));
});
test('未修改的原始台词标签不闭合也能检出', () => {
  const original = mutate((value) => { segment(value).h3Prompt = prompt().replace('</d>', ''); });
  assert.ok(reviewBoards(original, structuredClone(original)).violations.some((item) => item.includes('未正确闭合')));
});
test('台词放在第一个镜头块之前也能检出', () => {
  const original = mutate((value) => { segment(value).h3Prompt = prompt().replace('integrated_multimodal_description:', 'integrated_multimodal_description:\n<d>[Chinese] 原文位置错误。</d>'); });
  assert.ok(reviewBoards(original, structuredClone(original)).violations.some((item) => item.includes('台词标签必须位于镜头描述')));
});
test('段级音景单独修改也提示漏同步', () => {
  const result = reviewBoards(board(), mutate((value) => { segment(value).soundscape = '只有提手摩擦声。'; }));
  assert.ok(gateChecks(result).find((gate) => gate.id === 'G06').issues.length);
});
test('只改一镜时不要求重写无关镜头的旧备注', () => {
  const original = board(); delete segment(original).cuts[1].note;
  const revised = structuredClone(original); first(revised).note += '补充承重依据。';
  assert.deepEqual(reviewBoards(original, revised).violations, []);
});

const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'novel-motion-'));
try {
  const cli = path.join(path.dirname(fileURLToPath(import.meta.url)), 'motion.mjs');
  const before = path.join(temp, 'before.json');
  const after = path.join(temp, 'after.json');
  const report = path.join(temp, 'review.md');
  const originalBytes = JSON.stringify(board());
  fs.writeFileSync(before, originalBytes);
  fs.writeFileSync(after, JSON.stringify(mutate((value) => { first(value).note += '补充动作说明。'; })));
  const run = (...args) => spawnSync(process.execPath, [cli, ...args], { encoding: 'utf8' });
  test('CLI 写入报告并保持输入字节不变', () => {
    const result = run('review', '--before', before, '--after', after, '--out', report);
    assert.equal(result.status, 0, result.stderr);
    assert.equal(fs.readFileSync(before, 'utf8'), originalBytes);
    assert.match(fs.readFileSync(report, 'utf8'), /补充动作说明/);
  });
  test('CLI 不覆盖已有报告', () => {
    const bytes = fs.readFileSync(report, 'utf8');
    assert.equal(run('review', '--before', before, '--after', after, '--out', report).status, 1);
    assert.equal(fs.readFileSync(report, 'utf8'), bytes);
  });
  test('CLI 不覆盖原稿', () => {
    assert.equal(run('review', '--before', before, '--after', after, '--out', before).status, 1);
    assert.equal(fs.readFileSync(before, 'utf8'), originalBytes);
  });
  test('CLI 拒绝相同输入文件', () => assert.equal(run('review', '--before', before, '--after', before).status, 1));
  test('CLI 拒绝缺失和未知参数', () => {
    assert.equal(run('review', '--before', before).status, 1);
    assert.equal(run('review', '--before', before, '--after', after, '--force', 'yes').status, 1);
  });
  test('CLI 同步待核对返回 2', () => {
    fs.writeFileSync(after, JSON.stringify(mutate((value) => { first(value).shot = '接住后松手。'; })));
    assert.equal(run('review', '--before', before, '--after', after).status, 2);
  });
  test('CLI 材料门失败返回 2 并定位镜头', () => {
    fs.writeFileSync(after, JSON.stringify(mutate((value) => { first(value).note = '只有一句泛泛备注。'; })));
    const result = run('review', '--before', before, '--after', after);
    assert.equal(result.status, 2);
    assert.match(result.stdout, /G04.*E01-01\/f1/);
  });
  test('CLI 拒绝错误 JSON', () => {
    fs.writeFileSync(after, '{bad');
    assert.equal(run('review', '--before', before, '--after', after).status, 1);
  });
  test('CLI 正常支持 UTF-8 BOM', () => {
    fs.writeFileSync(after, '\uFEFF' + originalBytes);
    assert.equal(run('review', '--before', before, '--after', after).status, 0);
  });
  test('CLI 拒绝改变相对素材路径基准', () => {
    const other = path.join(temp, 'other'); fs.mkdirSync(other);
    const moved = path.join(other, 'after.json'); fs.writeFileSync(moved, originalBytes);
    assert.equal(run('review', '--before', before, '--after', moved).status, 1);
  });
  const applyDir = path.join(temp, 'in-place'); fs.mkdirSync(applyDir);
  const target = path.join(applyDir, 'storyboard.json');
  const applyReport = path.join(applyDir, 'motion-review.md');
  const reset = () => fs.writeFileSync(target, originalBytes);
  const revised = () => mutate((value) => {
    first(value).shot = '修理师继续托住收音机，司机接住重量后才松手。';
    segment(value).h3Prompt = prompt('A supports the radio until B takes its weight, then releases it.');
  });
  const apply = (before, after, ...extra) => spawnSync(process.execPath,
    [cli, 'apply', '--file', target, ...extra],
    { input: JSON.stringify({ before, after }), encoding: 'utf8' });
  test('apply 原位更新同一文件，不产生阶段 JSON', () => {
    reset(); const result = apply(board(), revised());
    assert.equal(result.status, 0, result.stderr);
    assert.deepEqual(JSON.parse(fs.readFileSync(target, 'utf8')), revised());
    assert.deepEqual(fs.readdirSync(applyDir), ['storyboard.json']);
    assert.match(result.stdout, /G06/);
  });
  test('apply 继承已更新内容，并覆盖指定的既有报告', () => {
    const current = JSON.parse(fs.readFileSync(target, 'utf8'));
    const next = structuredClone(current); first(next).note += '下一镜继续保持新持有关系。';
    fs.writeFileSync(applyReport, 'old report');
    assert.equal(apply(current, next, '--out', applyReport).status, 0);
    assert.deepEqual(JSON.parse(fs.readFileSync(target, 'utf8')), next);
    assert.match(fs.readFileSync(applyReport, 'utf8'), /新持有关系/);
    assert.deepEqual(fs.readdirSync(applyDir).sort(), ['motion-review.md', 'storyboard.json']);
  });
  test('apply 过期输入不能覆盖新的内容', () => {
    const saved = fs.readFileSync(target, 'utf8');
    const result = apply(board(), revised());
    assert.equal(result.status, 1);
    assert.match(result.stderr, /已变化/);
    assert.equal(fs.readFileSync(target, 'utf8'), saved);
  });
  for (const [label, candidate] of [
    ['时长被改', mutate((value) => { first(value).seconds += 1; })],
    ['H3 未同步', mutate((value) => { first(value).shot = '接住重量后松手。'; })],
    ['台词被改', mutate((value) => { segment(value).h3Prompt = prompt().replace('谢谢。', '多谢。'); })],
  ]) {
    test(`apply 检查失败保留原文件：${label}`, () => {
      reset(); assert.equal(apply(board(), candidate).status, 2);
      assert.equal(fs.readFileSync(target, 'utf8'), originalBytes);
    });
  }
  test('apply 无变化时保留原格式和 BOM', () => {
    const bytes = '\uFEFF'+JSON.stringify(board(), null, 4);
    fs.writeFileSync(target, bytes);
    assert.equal(apply(board(), board()).status, 0);
    assert.equal(fs.readFileSync(target, 'utf8'), bytes);
  });
  test('apply 禁止报告写到 storyboard 路径', () => {
    reset(); assert.equal(apply(board(), revised(), '--out', target).status, 1);
    assert.equal(fs.readFileSync(target, 'utf8'), originalBytes);
  });
  test('apply 报告写入失败不修改 storyboard', () => {
    reset(); assert.equal(apply(board(), revised(), '--out', path.join(applyDir, 'missing', 'report.md')).status, 1);
    assert.equal(fs.readFileSync(target, 'utf8'), originalBytes);
  });
  test('apply 报告硬链接不能覆盖 storyboard', () => {
    reset(); const alias = path.join(applyDir, 'alias.md'); fs.linkSync(target, alias);
    assert.equal(apply(board(), revised(), '--out', alias).status, 1);
    assert.equal(fs.readFileSync(target, 'utf8'), originalBytes);
  });
  for (const input of ['', '{bad', '{}', JSON.stringify({ before: board() })]) {
    test(`apply 拒绝无效标准输入 ${input.length}`, () => {
      reset();
      const result = spawnSync(process.execPath, [cli, 'apply', '--file', target], { input, encoding: 'utf8' });
      assert.equal(result.status, 1);
      assert.equal(fs.readFileSync(target, 'utf8'), originalBytes);
    });
  }
  test('apply 拒绝旧参数或缺少目标路径', () => {
    assert.equal(run('apply', '--before', before, '--after', after).status, 1);
    assert.equal(run('apply').status, 1);
  });
} finally {
  const resolved = fs.realpathSync(temp);
  assert.equal(path.dirname(resolved), fs.realpathSync(os.tmpdir()));
  assert.ok(path.basename(resolved).startsWith('novel-motion-'));
  fs.rmSync(resolved, { recursive: true, force: true });
}

console.log(`novel-storyboard-motion: ${count} tests passed`);
