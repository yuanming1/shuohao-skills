import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import { reviewBoards, gateChecks, parseModes, renderReview } from './enhance.mjs';
import { board, enhanced, compositionEnhanced, prompt, compressedBoard, completedBoard, promptForCuts, completionBodies } from '../examples/storyboards.mjs';

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
const sourceScript = () => ({ source: '雪站回灯', episodes: [{ ep: 1, targetSeconds: 14, scenes: [{
  sceneId: 'S01', characters: ['C01', 'C02'], props: ['P01'], flow: [
    { speaker: 'C02', line: '先稳住。' }, { speaker: 'C01', line: '我来。' },
    { action: '原有环纹依次亮起并闭合，灯芯随后发光。' }, { action: '灯照亮石路，师父沿路望去。' },
  ],
}] }] });

function refinementCase() {
  const scriptBefore = sourceScript();
  const script = structuredClone(scriptBefore);
  script.episodes[0].scenes[0].flow.splice(2, 1,
    { action: '原有环纹沿边缘依次亮起并闭合，灯芯尚暗。' }, { action: '闭合环纹之后，灯芯发光。' });
  const after = completedBoard();
  const cuts = segment(after).cuts;
  const core = structuredClone(cuts[2]);
  cuts[2].seconds = 2;
  cuts[2].shot = '固定镜头，年轻学徒保持稳住的右掌，原有环纹依次亮起并闭合，灯芯尚暗。';
  cuts[2].note = '起始：手稳、灯暗；动作：环纹依次亮起并闭合；结束：环纹闭合、灯芯未亮；接镜：下一镜呈现灯芯发光。增强依据：把原唤灯动作细分，避免环纹与灯芯同时亮起。';
  core.beats = [4, 4]; core.seconds = 2;
  core.frame = '中景，岑雪右掌稳在已经闭合的环纹上方，灯芯尚暗，罗衡在后方原位。';
  core.shot = '固定镜头，原环纹已经闭合，灯芯随后发光，年轻学徒继续悬掌，两人原位。';
  core.note = '起始：环纹已闭合、灯芯未亮；动作：灯芯发光；结束：灯芯持续发光；接镜：下一镜确认照明结果。增强依据：补全既定点灯的后半阶段，不新增能力与结果。';
  cuts[3].beats = [5, 5];
  cuts.splice(3, 0, core);
  segment(after).h3Prompt = promptForCuts(cuts, [completionBodies[0], completionBodies[1],
    'Static Shot. The existing ring lights progressively and closes while the core remains dark. The already steady palm stays above it.',
    'Static Shot. With the existing ring already closed, the core now lights up. Both people remain in place and the steady palm stays raised.', completionBodies[3]]);
  return { scriptBefore, script, after };
}

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
  ['节拍', (value) => { first(value).beats = [1, 2]; }],
  ['新增人物身份', (value) => { first(value).characters = ['C99']; }],
  ['新增道具身份', (value) => { first(value).props = ['P99']; }],
  ['场次', (value) => { segment(value).sceneIndex = 2; }],
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
test('可以补全缺失的必要摄影字段并同步正文', () => {
  const original = board(); delete first(original).focus;
  const revised = structuredClone(original); first(revised).focus = '锁定灯芯'; addReason(first(revised));
  segment(revised).h3Prompt = prompt('The focus retains the apprentice and the lamp core.');
  assert.deepEqual(reviewBoards(original, revised, requiredModes).violations, []);
  assert.deepEqual(reviewBoards(original, revised, requiredModes).attention, []);
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
  assert.match(text, /须说明省略与人物表现已经充分/);
});
test('提示词含围栏时报告保留原文', () => {
  const text = renderReview(review((value) => { first(value).note += '\n```text\n原有备注\n```'; }));
  assert.match(text, /````text/);
});

test('补全性格表现时允许拆镜和延长，保留原故事与对白', () => {
  const original = compressedBoard();
  const revised = completedBoard();
  const saved = structuredClone(original);
  const result = reviewBoards(original, revised, requiredModes);
  assert.deepEqual(result.violations, []);
  assert.deepEqual(result.attention, []);
  assert.deepEqual(original, saved);
  assert.equal(segment(original).cuts.length, 3);
  assert.equal(segment(revised).cuts.length, 4);
  assert.equal(segment(revised).cuts.reduce((total, cut) => total + cut.seconds, 0), 14);
  assert.match(segment(revised).h3Prompt.split('\n')[0], /Picture 4 \(from Shot 4\) aligns with the 10\.00-second/);
  assert.match(segment(revised).h3Prompt, /\[Shot 2\] At 00:02\.000, <Picture 2>/);
  assert.equal(result.impact.frames.length, 4);
});

const completedReview = (change) => {
  const revised = completedBoard();
  change(revised);
  return reviewBoards(compressedBoard(), revised, requiredModes);
};
test('默认允许短切与长镜头混排并同步切点', () => {
  const revised = completedBoard();
  const cuts = segment(revised).cuts;
  [1, 1, 6, 0.5].forEach((seconds, index) => { cuts[index].seconds = seconds; });
  segment(revised).h3Prompt = promptForCuts(cuts, completionBodies);
  const result = reviewBoards(compressedBoard(), revised, requiredModes);
  assert.deepEqual(result.violations, []);
  assert.deepEqual(result.attention, []);
});
for (const params of [{ minCutSeconds: 2 }, { maxCutSeconds: 5 }]) {
  test(`重排遵守显式镜长约束 ${JSON.stringify(params)}`, () => {
    const original = compressedBoard(); original.params = params;
    const revised = completedBoard(); revised.params = structuredClone(params);
    const cuts = segment(revised).cuts;
    [1, 1, 6, 0.5].forEach((seconds, index) => { cuts[index].seconds = seconds; });
    segment(revised).h3Prompt = promptForCuts(cuts, completionBodies);
    assert.ok(hasGate(reviewBoards(original, revised, requiredModes), 'G03'));
  });
}
test('允许合并观察阶段并重新分配原节拍', () => {
  const revised = completedBoard();
  const merged = structuredClone(first(revised));
  merged.beats = [1, 2]; merged.seconds = 5;
  merged.shot += segment(revised).cuts[1].shot;
  segment(revised).cuts.splice(0, 2, merged);
  segment(revised).h3Prompt = promptForCuts(segment(revised).cuts,
    [completionBodies[0] + ' ' + completionBodies[1], ...completionBodies.slice(2)]);
  const result = reviewBoards(compressedBoard(), revised, requiredModes);
  assert.deepEqual(result.violations, []);
  assert.deepEqual(result.attention, []);
});
test('允许跨生成段补全，续段开场与图片编号同步', () => {
  const revised = completedBoard();
  const head = segment(revised);
  const tail = structuredClone(head);
  head.cuts = head.cuts.slice(0, 2);
  head.h3Prompt = promptForCuts(head.cuts, completionBodies.slice(0, 2));
  tail.id = 'E01-02'; tail.cuts = tail.cuts.slice(2);
  tail.blocking = '两人原位，学徒右掌已经稳在灯沿上方，灯暗；从此前已完成的回答承接。';
  tail.h3Prompt = promptForCuts(tail.cuts, completionBodies.slice(2));
  revised.episodes[0].segments.push(tail);
  const result = reviewBoards(compressedBoard(), revised, requiredModes);
  assert.deepEqual(result.violations, []);
  assert.deepEqual(result.attention, []);
  assert.ok(result.impact.frames.includes('E01-02/f1'));
});
for (const [name, change, gate] of [
  ['丢失原有事件', (value) => { segment(value).cuts.pop(); }, 'G02'],
  ['重复认领节拍', (value) => { segment(value).cuts[1].beats = [1, 2]; }, 'G02'],
  ['改变事件顺序', (value) => { segment(value).cuts.reverse(); }, 'G02'],
  ['增加人物身份', (value) => { first(value).characters.push('C99'); }, 'G02'],
  ['增加道具身份', (value) => { first(value).props.push('P99'); }, 'G02'],
  ['改写对白', (value) => { segment(value).h3Prompt = segment(value).h3Prompt.replace('我来。', '我不会。'); }, 'G05'],
  ['改变说话人', (value) => { segment(value).h3Prompt = segment(value).h3Prompt.replace('(S2)', '(S1)'); }, 'G05'],
  ['未更新首行', (value) => { segment(value).h3Prompt = segment(value).h3Prompt.replace(/^.*\n/, segment(compressedBoard()).h3Prompt.split('\n')[0] + '\n'); }, 'G05'],
  ['未更新切点', (value) => { segment(value).h3Prompt = segment(value).h3Prompt.replace('At 00:02.000,', 'At 00:04.000,'); }, 'G05'],
  ['混入错误图片绑定', (value) => { segment(value).h3Prompt = segment(value).h3Prompt.replace('<Picture 1>', '<Picture 1> <Picture 9>'); }, 'G05'],
  ['单镜超过单段上限', (value) => { first(value).seconds = 16; }, 'G03'],
  ['超过单段时长', (value) => { first(value).seconds = 4; }, 'G03'],
  ['丢失补全依据', (value) => { first(value).note = '这里只写修改完成。'; }, 'G04'],
  ['改动未知数据', (value) => { first(value).unrecognized = 'new'; }, 'G02'],
]) test(`重排仍拒绝：${name}`, () => assert.ok(hasGate(completedReview(change), gate)));

test('对白不能借重排移到另一个事件', () => {
  const bodies = [...completionBodies];
  bodies[1] = bodies[1].replace(/The young apprentice.*?\./, 'The apprentice watches.');
  bodies[1] = bodies[1].replace('<d>[Chinese] 我来。</d>', '');
  bodies[3] += ' The young apprentice (S2) says <d>[Chinese] 我来。</d>.';
  const result = completedReview((value) => { segment(value).h3Prompt = promptForCuts(segment(value).cuts, bodies); });
  assert.ok(hasGate(result, 'G05'));
});
test('拆镜时未知数据随来源节拍保留', () => {
  const original = compressedBoard();
  first(original).tracking = { source: 'original' };
  const revised = completedBoard();
  segment(revised).cuts.slice(0, 2).forEach((cut) => { cut.tracking = { source: 'original' }; });
  assert.deepEqual(reviewBoards(original, revised, requiredModes).violations, []);
  delete segment(revised).cuts[1].tracking;
  assert.ok(hasGate(reviewBoards(original, revised, requiredModes), 'G02'));
});
test('重排也逐镜检查正文同步，其他镜的 H3 修改不能掩盖遗漏', () => {
  const result = completedReview((value) => {
    segment(value).h3Prompt = segment(value).h3Prompt.replace(completionBodies[3],
      'A static shot shows the lit lamp and the existing stone path.');
  });
  assert.ok(result.attention.some((issue) => issue.includes('E01-01/f4')));
});
test('重排也检查多行声景的后续行', () => {
  const original = compressedBoard();
  segment(original).h3Prompt = segment(original).h3Prompt.replace('Wind outside', '\nWind outside');
  const revised = completedBoard();
  segment(revised).h3Prompt = segment(revised).h3Prompt.replace('Wind outside', '\nWind outside')
    .replace('the existing lamp hums', '\nThe lamp hum grows');
  assert.ok(hasGate(reviewBoards(original, revised, requiredModes), 'G06'));
});

test('正式剧本允许恢复旧分镜漏登记的在场人物和道具', () => {
  const original = compressedBoard();
  segment(original).cuts.forEach((cut) => { cut.characters = ['C01']; cut.props = []; });
  const revised = completedBoard();
  assert.ok(hasGate(reviewBoards(original, revised, requiredModes), 'G02'));
  const result = reviewBoards(original, revised, requiredModes, { script: sourceScript() });
  assert.deepEqual(result.violations, []);
  assert.deepEqual(result.attention, []);
});
test('正式剧本核对精确台词节拍，不只依靠旧镜的大区间', () => {
  const revised = completedBoard();
  const bodies = [...completionBodies];
  bodies[0] = bodies[0].replace('(S1) says <d>[Chinese] 先稳住。</d>', 'waits');
  bodies[1] = 'The older mentor (S1) says <d>[Chinese] 先稳住。</d>. ' + bodies[1];
  segment(revised).h3Prompt = promptForCuts(segment(revised).cuts, bodies);
  assert.ok(hasGate(reviewBoards(compressedBoard(), revised, requiredModes, { script: sourceScript() }), 'G05'));
});
test('补演后仍检查剧本单集预算', () => {
  const script = sourceScript(); script.episodes[0].targetSeconds = 12;
  assert.ok(hasGate(reviewBoards(compressedBoard(), completedBoard(), requiredModes, { script }), 'G03'));
});
test('单一动作可以细分剧本节拍并追溯到原事件', () => {
  const sample = refinementCase();
  const result = reviewBoards(compressedBoard(), sample.after, requiredModes, sample);
  assert.deepEqual(result.violations, []);
  assert.deepEqual(result.attention, []);
  assert.equal(segment(sample.after).cuts.length, 5);
});
test('动作细分必须提供修改前剧本，不能只改节拍数字', () => {
  const sample = refinementCase();
  assert.throws(() => reviewBoards(compressedBoard(), sample.after, requiredModes, { script: sample.script }), /G02/);
});
for (const [label, change] of [
  ['对白', (script) => { script.episodes[0].scenes[0].flow[0].line = '换我来。'; }],
  ['人物身份', (script) => { script.episodes[0].scenes[0].characters.push('C99'); }],
  ['时长目标', (script) => { script.episodes[0].targetSeconds = 80; }],
]) test(`动作细分不能顺带改写${label}`, () => {
  const sample = refinementCase(); change(sample.script);
  assert.throws(() => reviewBoards(compressedBoard(), sample.after, requiredModes, sample), /G02/);
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
  const applyDir = path.join(folder, 'in-place'); fs.mkdirSync(applyDir);
  const target = path.join(applyDir, 'storyboard.json');
  const applyReport = path.join(applyDir, 'enhance-review.md');
  const reset = () => fs.writeFileSync(target, JSON.stringify(board()));
  const apply = (before, after, ...extra) => spawnSync(process.execPath,
    [cli, 'apply', '--file', target, '--modes', modes, ...extra],
    { input: JSON.stringify({ before, after }), encoding: 'utf8' });
  test('apply 校验后原位写入完整修订，不产生阶段 JSON', () => {
    reset();
    const result = apply(board(), enhanced());
    assert.equal(result.status, 0, result.stderr);
    assert.deepEqual(JSON.parse(fs.readFileSync(target, 'utf8')), enhanced());
    assert.deepEqual(fs.readdirSync(applyDir), ['storyboard.json']);
    assert.match(result.stdout, /G06/);
  });
  test('apply 原位落实补演、拆镜和新时长', () => {
    fs.writeFileSync(target, JSON.stringify(compressedBoard()));
    const result = apply(compressedBoard(), completedBoard());
    assert.equal(result.status, 0, result.stderr);
    assert.deepEqual(JSON.parse(fs.readFileSync(target, 'utf8')), completedBoard());
    assert.deepEqual(fs.readdirSync(applyDir), ['storyboard.json']);
    fs.writeFileSync(target, JSON.stringify(enhanced()));
  });
  test('apply 对照已同步剧本落实动作细分，并保护剧本免被报告覆盖', () => {
    const sample = refinementCase();
    const scriptFile = path.join(applyDir, 'script.json');
    const sourceBytes = JSON.stringify(sample.script);
    fs.writeFileSync(scriptFile, sourceBytes);
    fs.writeFileSync(target, JSON.stringify(compressedBoard()));
    const invoke = (...extra) => spawnSync(process.execPath,
      [cli, 'apply', '--file', target, '--script', scriptFile, '--modes', requiredModes, ...extra],
      { input: JSON.stringify({ before: compressedBoard(), after: sample.after, scriptBefore: sample.scriptBefore }), encoding: 'utf8' });
    assert.equal(invoke('--out', scriptFile).status, 1);
    assert.equal(fs.readFileSync(scriptFile, 'utf8'), sourceBytes);
    const result = invoke();
    assert.equal(result.status, 0, result.stderr);
    assert.deepEqual(JSON.parse(fs.readFileSync(target, 'utf8')), sample.after);
    fs.unlinkSync(scriptFile);
    fs.writeFileSync(target, JSON.stringify(enhanced()));
  });
  test('apply 连续处理同一文件并更新既有报告', () => {
    const firstVersion = JSON.parse(fs.readFileSync(target, 'utf8'));
    const next = structuredClone(firstVersion); first(next).note += '继续保持前镜已建立的视线。';
    fs.writeFileSync(applyReport, 'old report');
    assert.equal(apply(firstVersion, next, '--out', applyReport).status, 0);
    assert.deepEqual(JSON.parse(fs.readFileSync(target, 'utf8')), next);
    assert.match(fs.readFileSync(applyReport, 'utf8'), /继续保持/);
    assert.deepEqual(fs.readdirSync(applyDir).sort(), ['enhance-review.md', 'storyboard.json']);
  });
  test('apply 拒绝过期基线，保留磁盘上的最新修订', () => {
    const saved = fs.readFileSync(target, 'utf8');
    const result = apply(board(), enhanced());
    assert.equal(result.status, 1);
    assert.match(result.stderr, /已变化/);
    assert.equal(fs.readFileSync(target, 'utf8'), saved);
  });
  for (const [label, candidate] of [
    ['时长改变但未更新切点', mutate((value) => { first(value).seconds += 1; })],
    ['正文单边改动', mutate((value) => { first(value).shot += '她的视线回到灯沿。'; addReason(first(value)); })],
    ['H3 台词改变', mutate((value) => { segment(value).h3Prompt = prompt().replace('我来。', '我先来。'); })],
  ]) {
    test(`apply 不写入：${label}`, () => {
      reset(); const saved = fs.readFileSync(target, 'utf8');
      assert.equal(apply(board(), candidate).status, 2);
      assert.equal(fs.readFileSync(target, 'utf8'), saved);
    });
  }
  test('apply 不变内容保留原字节及 BOM', () => {
    const bytes = '\uFEFF' + JSON.stringify(board(), null, 4);
    fs.writeFileSync(target, bytes);
    assert.equal(apply(board(), board()).status, 0);
    assert.equal(fs.readFileSync(target, 'utf8'), bytes);
  });
  test('apply 报告不能覆盖正式分镜', () => {
    reset(); const saved = fs.readFileSync(target, 'utf8');
    assert.equal(apply(board(), enhanced(), '--out', target).status, 1);
    assert.equal(fs.readFileSync(target, 'utf8'), saved);
  });
  test('apply 报告写入失败时不改分镜', () => {
    reset(); const saved = fs.readFileSync(target, 'utf8');
    assert.equal(apply(board(), enhanced(), '--out', path.join(applyDir, 'missing', 'report.md')).status, 1);
    assert.equal(fs.readFileSync(target, 'utf8'), saved);
  });
  test('apply 报告硬链接也不能覆盖正式分镜', () => {
    reset(); const saved = fs.readFileSync(target, 'utf8');
    const alias = path.join(applyDir, 'alias.md'); fs.linkSync(target, alias);
    assert.equal(apply(board(), enhanced(), '--out', alias).status, 1);
    assert.equal(fs.readFileSync(target, 'utf8'), saved);
  });
  for (const input of ['', '{bad', '{}', JSON.stringify({ before: board() })]) {
    test(`apply 拒绝不完整标准输入 ${input.length}`, () => {
      reset(); const saved = fs.readFileSync(target, 'utf8');
      const result = spawnSync(process.execPath, [cli, 'apply', '--file', target, '--modes', modes], { input, encoding: 'utf8' });
      assert.equal(result.status, 1);
      assert.equal(fs.readFileSync(target, 'utf8'), saved);
    });
  }
  test('apply 仍要求表演与摄影两个方向', () => {
    reset(); const saved = fs.readFileSync(target, 'utf8');
    const result = spawnSync(process.execPath, [cli, 'apply', '--file', target, '--modes', 'performance'],
      { input: JSON.stringify({ before: board(), after: enhanced() }), encoding: 'utf8' });
    assert.equal(result.status, 1);
    assert.equal(fs.readFileSync(target, 'utf8'), saved);
  });
  test('apply 不接受旧 review 参数或缺少正式文件参数', () => {
    assert.equal(run('apply', '--before', beforePath, '--after', afterPath, '--modes', modes).status, 1);
    assert.equal(run('apply', '--modes', modes).status, 1);
  });
} finally {
  const resolved = fs.realpathSync(folder);
  assert.equal(path.dirname(resolved), fs.realpathSync(os.tmpdir()));
  assert.ok(path.basename(resolved).startsWith('storyboard-enhance-'));
  fs.rmSync(resolved, { recursive: true, force: true });
}

process.stdout.write(`novel-storyboard-enhance: ${count} tests passed\n`);
