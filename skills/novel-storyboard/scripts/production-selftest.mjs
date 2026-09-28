import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { productionProblems, reviewTemplate } from './production-review.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const load = (path) => JSON.parse(readFileSync(join(here, path), 'utf8'));
const board = load('../examples/渡口-storyboard.json');
const ctx = { script: load('../../novel-script/examples/渡口-script.json') };
for (const episode of board.episodes) {
  for (const segment of episode.segments) {
    for (const cut of segment.cuts) cut.note = '测试夹具中的承接安排；不构成真实画面验收。';
  }
}
const image = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j4WQAAAAASUVORK5CYII=', 'base64');
const options = { readImage: () => image };
const template = reviewTemplate(board, ctx, { ...options, model: 'h3' });
const approved = structuredClone(template);
for (const cut of approved.cuts) {
  cut.verdict = 'pass';
  cut.evidence = '单元测试模拟人工已核对状态与前切；不是实际素材的通过记录。';
}
let passed = 0;
const check = (condition, message) => { assert.ok(condition, message); passed += 1; };
const problems = (review, input = board, context = ctx, config = options) => productionProblems(input, context, review, config);
const rejects = (mutate, message) => {
  const changed = structuredClone(approved);
  mutate(changed);
  check(problems(changed).length > 0, message);
};
check(Object.keys(template).length <= 5, '审核顶层不超过五字段');
check(template.cuts.every((cut) => Object.keys(cut).length <= 5), '逐切记录不超过五字段');
check(template.segments.every((segment) => Object.keys(segment).length <= 5), '实际提交项不超过五字段');
check(template.cuts.every((cut) => cut.verdict === 'pending' && cut.evidence === ''), '底稿不自动批准');
check(problems(template).length > 0, '待审核不能投产');
check(problems(null).length > 0, '缺审核不能投产');
check(problems([]).length > 0, '数组不是审核对象');
check(problems(approved).length === 0, '模拟完整记录且版本相同可放行');
rejects((review) => { review.model = ''; }, '未确认模型被拦');
rejects((review) => { review.model = 'seedance-2'; }, '跨模型不能原样标为已适配');
rejects((review) => { review.fingerprint = 'old'; }, '旧指纹被拦');
rejects((review) => { review.segments.pop(); }, '漏段被拦');
rejects((review) => { review.segments.push(review.segments[0]); }, '多段被拦');
rejects((review) => { review.segments.reverse(); }, '错序被拦');
rejects((review) => { review.segments[0].seconds -= 1; }, '静默截短被拦');
rejects((review) => { review.segments[0].seconds += 1; }, '未重排直接加长也被拦');
rejects((review) => { review.segments[0].seconds = String(review.segments[0].seconds); }, '提交秒数必须为数值');
rejects((review) => { review.cuts.pop(); }, '漏评被拦');
rejects((review) => { review.cuts[1] = review.cuts[0]; }, '重复评审不能占位');
rejects((review) => { review.cuts[0].verdict = 'fail'; }, '失败评审被拦');
rejects((review) => { review.cuts[0].evidence = '  '; }, '空依据被拦');
rejects((review) => { review.cuts[0].evidence = 12; }, '依据必须为文本');
rejects((review) => { review.cuts = null; }, '损坏审核清单被拦');
check(problems(approved, board, ctx, { readImage: () => null }).length > 0, '缺图被拦');
check(problems(approved, board, ctx, { readImage: () => Buffer.alloc(0) }).length > 0, '空图文件被拦');
check(problems(approved, board, ctx, { readImage: () => Buffer.from('changed') }).some((message) => message.includes('过期')), '换图使审核失效');
const changedBoard = structuredClone(board);
changedBoard.episodes[0].segments[0].cuts[0].frame += ' changed';
check(problems(approved, changedBoard).some((message) => message.includes('过期')), '改分镜文字使审核失效');
for (const field of ['script', 'outline', 'cast', 'art']) {
  const changedCtx = structuredClone(ctx);
  changedCtx[field] = { source: 'changed' };
  check(problems(approved, board, changedCtx).some((message) => message.includes('过期')), `改 ${field} 使审核失效`);
}
const missingNote = structuredClone(board);
delete missingNote.episodes[0].segments[0].cuts[0].note;
const noteReview = { ...approved, fingerprint: reviewTemplate(missingNote, ctx, options).fingerprint };
check(problems(noteReview, missingNote).some((message) => message.includes('缺少动作承接')), '即使新指纹和通过记录也不能省承接安排');
const fractional = structuredClone(board);
fractional.episodes[0].segments[0].cuts = [{ seconds: 3, note: 'test' }, { seconds: 3, note: 'test' }, { seconds: 3.6, note: 'test' }];
const fractionalReview = reviewTemplate(fractional, ctx, { ...options, model: 'h3' });
check(fractionalReview.segments[0].seconds === 9.6, '保留小数秒不向下取整');
fractionalReview.segments[0].seconds = 9;
check(problems(fractionalReview, fractional).some((message) => message.includes('9.6s')), '回归：9.6 秒不能下单 9 秒');
const relocated = reviewTemplate(board, ctx, { ...options, dir: 'another', model: 'h3' });
check(relocated.fingerprint === template.fingerprint, '相同内容整体搬目录不导致过期');

const root = mkdtempSync(join(tmpdir(), 'novel-production-test-'));
const cli = join(here, 'novel-storyboard.mjs');
const boardPath = join(root, 'board.json');
const scriptPath = join(root, 'script.json');
const reviewPath = join(root, 'review.json');
const run = (command, args = []) => spawnSync(process.execPath, [cli, command, boardPath, '--script', scriptPath, ...args], { cwd: root, encoding: 'utf8' });
try {
  writeFileSync(boardPath, JSON.stringify(board));
  writeFileSync(scriptPath, JSON.stringify(ctx.script));
  let result = run('export');
  check(result.status !== 0 && result.stderr.includes('缺少逐切审核'), 'CLI 默认没有审核不能导出');
  check(!existsSync(join(root, 'manifest.json')), '失败不写产物');
  result = run('export', ['--draft']);
  check(result.status === 0 && result.stdout.includes('草稿'), 'CLI 草稿允许缺图');
  check(readFileSync(join(root, 'E01-01/prompt.md'), 'utf8').includes('不可直接投产'), '草稿文件自带警告');
  result = run('review-template', ['--model', 'h3']);
  check(result.status === 0, 'CLI 可生成缺图时的待审底稿');
  const pending = JSON.parse(result.stdout);
  writeFileSync(reviewPath, JSON.stringify(pending));
  result = run('export', ['--review', reviewPath]);
  check(result.status !== 0 && result.stderr.includes('缺少非空分镜图'), 'CLI 缺图不投产');
  result = run('export', ['--draft', '--review', reviewPath]);
  check(result.status !== 0 && result.stderr.includes('不能同时使用'), '草稿与审核参数互斥');
  for (const cut of template.cuts) {
    const path = join(root, `${cut.id}.png`);
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(path, image);
  }
  writeFileSync(reviewPath, JSON.stringify(approved));
  result = run('export', ['--review', reviewPath]);
  check(result.status === 0 && result.stdout.includes('输入版本检查通过'), 'CLI 放行完整模拟审核');
  check(!readFileSync(join(root, 'E01-01/prompt.md'), 'utf8').includes('草稿：'), '正式导出替换草稿警告');
  writeFileSync(join(root, 'E01-01/f1.png'), Buffer.from('changed'));
  result = run('export', ['--review', reviewPath]);
  check(result.status !== 0 && result.stderr.includes('过期'), 'CLI 换图后拒绝旧审核');
  const invalid = structuredClone(board);
  invalid.episodes[0].segments[0].h3Prompt = '';
  writeFileSync(boardPath, JSON.stringify(invalid));
  result = run('export', ['--draft']);
  check(result.status !== 0 && result.stderr.includes('结构校验未通过'), '草稿也不能跳过结构校验');
} finally {
  assert.equal(dirname(realpathSync(root)), realpathSync(resolve(tmpdir())));
  assert.ok(root.includes('novel-production-test-'));
  rmSync(root, { recursive: true, force: true });
}
console.log(`✓ ${passed} 项投产审核自测全部通过（不等于视觉语义验收）`);
