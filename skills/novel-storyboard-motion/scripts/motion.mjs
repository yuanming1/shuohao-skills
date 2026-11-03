#!/usr/bin/env node
/** 分镜保护性对比与校验后原位更新；不判断动作语义，不导入其他技能。 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { isDeepStrictEqual } from 'node:util';

const own = (value, key) => Object.hasOwn(value, key);
const plain = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);
const escapePart = (value) => String(value).replaceAll('~', '~0').replaceAll('/', '~1');
const CUT_TEXT = /^\/episodes\/\d+\/segments\/\d+\/cuts\/\d+\/(frame|shot|note|sfx)$/;
const SEGMENT_TEXT = /^\/episodes\/\d+\/segments\/\d+\/(h3Prompt|soundscape)$/;
const ADDABLE = /\/(note|sfx|soundscape)$/;
const H3_FIELDS = /^(?:integrated_multimodal_description:|overall_soundscape:|non_diegetic_music:|整体视听描述：|整体音景：|非叙事配乐：)/gm;
const SHOT_MARK = /^\[(?:Shot|镜头)\s+\d+\]/gm;
const BOUND_TOKENS = /<d>[\s\S]*?<\/d>|<Picture\s+\d+>|<图\s*\d+>|@(?:Image\s*\d+|图片\s*\d+|\[图片\d+\])|\(S\d+(?:,\s*S\d+)*\)|\b\d{2}:\d{2}\.\d{3}\b/g;
const GATES = [
  ['G01', '输入与镜头骨架'],
  ['G02', '镜头合同保护'],
  ['G03', '修改字段合法性'],
  ['G04', '正文与逐切编排材料'],
  ['G05', 'H3 结构与绑定保护'],
  ['G06', '单边修改与同步提醒'],
];

export function validateBoard(board) {
  if (!plain(board) || !Array.isArray(board.episodes) || !board.episodes.length) {
    throw new Error('[G01] 分镜需要非空 episodes 数组');
  }
  const ids = new Set();
  board.episodes.forEach((episode, ei) => {
    if (!plain(episode) || !Number.isInteger(episode.ep) || episode.ep < 1
      || !Array.isArray(episode.segments) || !episode.segments.length) {
      throw new Error(`[G01] episodes/${ei} 需要正整数 ep 和非空 segments`);
    }
    episode.segments.forEach((segment, si) => {
      if (!plain(segment) || typeof segment.id !== 'string' || !segment.id.trim()
        || !Array.isArray(segment.cuts) || !segment.cuts.length || ids.has(segment.id)) {
        throw new Error(`[G01] episodes/${ei}/segments/${si} 需要唯一段号和非空 cuts`);
      }
      ids.add(segment.id);
      segment.cuts.forEach((cut, ci) => {
        if (!plain(cut) || !Number.isFinite(cut.seconds) || cut.seconds <= 0
          || !Array.isArray(cut.beats) || cut.beats.length !== 2
          || !cut.beats.every(Number.isInteger) || cut.beats[0] < 1 || cut.beats[1] < cut.beats[0]) {
          throw new Error(`[G01] ${segment.id}/f${ci + 1} 需要正数 seconds 和有效 beats 区间`);
        }
      });
    });
  });
}

function differences(before, after, at = '', result = []) {
  if (isDeepStrictEqual(before, after)) return result;
  if (Array.isArray(before) && Array.isArray(after) && before.length === after.length) {
    before.forEach((value, index) => differences(value, after[index], `${at}/${index}`, result));
  } else if (plain(before) && plain(after)) {
    for (const key of new Set([...Object.keys(before), ...Object.keys(after)])) {
      const next = `${at}/${escapePart(key)}`;
      if (!own(before, key) || !own(after, key)) {
        result.push({ path: next, before: before[key], after: after[key] });
      } else differences(before[key], after[key], next, result);
    }
  } else result.push({ path: at || '/', before, after });
  return result;
}

function h3Signature(text) {
  // 按镜头保留绑定，避免台词或图片在镜头间挪动后总列表仍然相同。
  const normalized = text.replaceAll('\r\n', '\n');
  const fields = [...normalized.matchAll(H3_FIELDS)];
  const description = fields.length >= 2
    ? normalized.slice(fields[0].index + fields[0][0].length, fields[1].index)
    : normalized;
  const positions = [...description.matchAll(SHOT_MARK)];
  const blocks = positions.map((match, index) => {
    const end = positions[index + 1]?.index ?? description.length;
    return [match[0], description.slice(match.index, end).match(BOUND_TOKENS) ?? []];
  });
  const music = normalized.match(/^(?:non_diegetic_music:|非叙事配乐：)[\s\S]*$/m)?.[0] ?? '';
  return [normalized.split('\n')[0], fields.map((match) => match[0]), blocks, music];
}

function displayCut(segment, index) {
  return `${segment.id}/f${index + 1}`;
}

function h3Problems(segment) {
  const text = segment.h3Prompt;
  if (typeof text !== 'string' || !text.trim()) return ['缺少非空 h3Prompt'];
  const normalized = text.replaceAll('\r\n', '\n');
  const fields = [...normalized.matchAll(H3_FIELDS)];
  const expected = fields[0]?.[0] === '整体视听描述：'
    ? ['整体视听描述：', '整体音景：', '非叙事配乐：']
    : ['integrated_multimodal_description:', 'overall_soundscape:', 'non_diegetic_music:'];
  if (!isDeepStrictEqual(fields.map((match) => match[0]), expected)) {
    return ['H3 三个字段必须各出现一次，语言一致且顺序为描述、音景、配乐'];
  }
  const issues = [];
  const start = fields[0].index + fields[0][0].length;
  const end = fields[1].index;
  const description = normalized.slice(start, end);
  const positions = [...description.matchAll(SHOT_MARK)];
  if (positions.length !== segment.cuts.length) issues.push('H3 镜头块数量与 cuts 数量不一致');
  const zh = expected[0] === '整体视听描述：';
  let elapsed = 0;
  segment.cuts.forEach((cut, index) => {
    const marker = positions[index];
    const expectedMarker = zh ? `[镜头 ${index + 1}]` : `[Shot ${index + 1}]`;
    if (marker?.[0] !== expectedMarker) issues.push(`缺少顺序正确的 ${expectedMarker}`);
    if (marker) {
      const block = description.slice(marker.index, positions[index + 1]?.index ?? description.length);
      if (!block.includes(`<Picture ${index + 1}>`) && !block.includes(`<图 ${index + 1}>`)) {
        issues.push(`${expectedMarker} 缺少对应图片绑定`);
      }
      if (index > 0) {
        const millis = Math.round(elapsed * 1000);
        const timestamp = `${String(Math.floor(millis / 60000)).padStart(2, '0')}:${String(Math.floor(millis / 1000) % 60).padStart(2, '0')}.${String(millis % 1000).padStart(3, '0')}`;
        const cutPrefix = `${expectedMarker} ${zh ? '于' : 'At'} ${timestamp}${zh ? '，' : ','}`;
        if (!block.startsWith(cutPrefix)) issues.push(`${expectedMarker} 切点开头应为 ${cutPrefix}`);
      }
    }
    elapsed += cut.seconds;
  });
  const dialogueCount = (normalized.match(/<d>/g) ?? []).length;
  if (dialogueCount !== (normalized.match(/<\/d>/g) ?? []).length
    || dialogueCount !== (normalized.match(/<d>[\s\S]*?<\/d>/g) ?? []).length) {
    issues.push('H3 台词标签未正确闭合');
  }
  if (/<\/?d>/.test(normalized.slice(0, start) + description.slice(0, positions[0]?.index ?? description.length) + normalized.slice(end))) {
    issues.push('H3 台词标签必须位于镜头描述中');
  }
  return issues;
}

export function gateChecks(result) {
  return GATES.map(([id, name]) => ({
    id, name,
    issues: [...result.violations, ...result.attention].filter((item) => item.startsWith(`[${id}]`)),
  }));
}

export function reviewBoards(before, after) {
  validateBoard(before);
  validateBoard(after);
  const changes = differences(before, after);
  const violations = [];
  const attention = new Set();
  const frames = new Set();
  const neighbors = new Set();
  const activeCuts = new Set();
  for (const change of changes) {
    const allowed = CUT_TEXT.test(change.path) || SEGMENT_TEXT.test(change.path);
    if (!allowed) {
      violations.push(`[G02] 受保护字段发生变化：${change.path}`);
      continue;
    }
    if (typeof change.after !== 'string' || !change.after.trim()
      || (change.before === undefined && !ADDABLE.test(change.path))
      || (change.before !== undefined && typeof change.before !== 'string')) {
      violations.push(`[G03] 正文只能改为非空字符串，缺失时仅可补充 note、sfx、soundscape：${change.path}`);
      continue;
    }
    const parts = change.path.split('/');
    const ei = Number(parts[2]);
    const si = Number(parts[4]);
    const oldSegment = before.episodes[ei].segments[si];
    const newSegment = after.episodes[ei].segments[si];
    if (change.path.endsWith('/h3Prompt')) {
      if (!isDeepStrictEqual(h3Signature(change.before), h3Signature(change.after))) {
        violations.push(`[G05] H3 对齐、镜头标记、切点、图片、台词、说话人标记、标题或配乐发生变化：${oldSegment.id}`);
      }
      attention.add(`${oldSegment.id}：H3 已改写，核对各镜头与 shot、frame 及声音一致，并更新视频导出包。`);
    }
    if (CUT_TEXT.test(change.path)) {
      const ci = Number(parts[6]);
      const label = displayCut(oldSegment, ci);
      const field = parts[7];
      activeCuts.add(label);
      if (field === 'frame') frames.add(label);
      if (['frame', 'shot', 'sfx'].includes(field)) {
        if (oldSegment.h3Prompt === newSegment.h3Prompt) {
          attention.add(`[G06] ${label}：${field} 已变，H3 未变；需核对是否漏同步，缺少 H3 时不能声称已同步。`);
        }
        attention.add(`${label}：核对 frame、shot、H3 和动作声音；相关视频导出包需更新。`);
      }
      const sequence = before.episodes[ei].segments.flatMap((seg) =>
        seg.cuts.map((_, index) => displayCut(seg, index)));
      const position = sequence.indexOf(label);
      sequence.slice(Math.max(0, position - 1), position + 2).forEach((item) => neighbors.add(item));
    }
    if (change.path.endsWith('/soundscape')) {
      attention.add(`${oldSegment.id}：段级音景已改，核对 H3 声景和每切动作，更新视频导出包。`);
      if (oldSegment.h3Prompt === newSegment.h3Prompt) {
        attention.add(`[G06] ${oldSegment.id}：soundscape 已变，H3 未变；需核对声景是否漏同步。`);
      }
    }
    if (SEGMENT_TEXT.test(change.path)) {
      oldSegment.cuts.forEach((_, index) => activeCuts.add(displayCut(oldSegment, index)));
    }
  }
  after.episodes.forEach((episode) => episode.segments.forEach((segment) => {
    h3Problems(segment).forEach((issue) => violations.push(`[G05] ${segment.id}：${issue}`));
    segment.cuts.forEach((cut, index) => {
      const label = displayCut(segment, index);
      for (const field of ['frame', 'shot']) {
        if (typeof cut[field] !== 'string' || !cut[field].trim()) violations.push(`[G04] ${label} 缺少非空 ${field}`);
      }
      if (!changes.length || activeCuts.has(label)) {
        for (const tag of ['起始', '动作', '结束', '接镜']) {
          const match = typeof cut.note === 'string' && cut.note.match(new RegExp(`${tag}[：:]\\s*([^；;\\n]*?)(?=[；;\\n]|(?:起始|动作|结束|接镜)[：:]|$)`));
          if (!match || !match[1].trim()) violations.push(`[G04] ${label} 缺少有内容的“${tag}：”编排说明`);
        }
      }
    });
  }));
  return { changes, violations, attention: [...attention], frames: [...frames], neighbors: [...neighbors] };
}

function fenced(value) {
  const text = value === undefined ? '（字段原来不存在）' : typeof value === 'string' ? value : JSON.stringify(value, null, 2);
  const runs = text.match(/`+/g) ?? [];
  const fence = '`'.repeat(Math.max(3, ...runs.map((run) => run.length + 1)));
  return `${fence}text\n${text}\n${fence}`;
}

export function renderReview(result) {
  const lines = ['# 分镜动作修订对比', '',
    `修改字段：${result.changes.length}；保护性问题：${result.violations.length}。`, '',
    '本报告只比较数据和可检查的协议内容。叙事、情绪、表演和身体动作的跨镜、跨段承接需联合复核；物理合理性、时长可行性和成片效果仍需结合剧本与实际素材判断。', '',
    '## 程序检测门', '',
    '| 编号 | 检测内容 | 结果 |', '|---|---|---|',
    ...gateChecks(result).map((gate) => `| ${gate.id} | ${gate.name} | ${gate.issues.length ? (gate.id === 'G06' ? '待核对' : '未通过') : '通过'} |`), '',
    'G01 失败时停止读取并返回输入错误。G04 的四段标签只检查材料齐备，G06 只提示可能的漏同步；均不能证明动作语义成立。', '',
    '## 保护性检查', '',
    ...(result.violations.length ? result.violations.map((item) => `- ${item}`) : ['受保护结构与可检查的 H3 内容未发生变化。']), '',
    '## 提示词与声音复核', '',
    ...(result.attention.length ? result.attention.map((item) => `- ${item}`) : ['没有检测到相关正文变动；这不代表原稿动作已经正确。']), '',
    '## 关键帧与相邻镜头', '',
    `切点描述已改，需核对或重出关键帧：${result.frames.join('、') || '未检测到'}。`, '',
    `连读范围：${result.neighbors.join('、') || '未检测到'}。跨场或时间省略按故事判断，状态影响更远时继续追查。`, '',
    '已有图片、宫格和视频不会随文本自动更新。H3 或动作正文改变后，应重新核对并导出受影响材料。', '',
    '## 字段对比', ''];
  for (const change of result.changes) {
    lines.push(`### ${change.path}`, '', '原稿：', '', fenced(change.before), '', '修订：', '', fenced(change.after), '');
  }
  if (!result.changes.length) lines.push('两份数据相同。', '');
  return lines.join('\n');
}

function parseArgs(argv) {
  const command = argv[0];
  if (!['review', 'apply'].includes(command)) throw new Error('命令格式：apply --file storyboard.json；标准输入提供 {before, after}，或使用 review --before 原稿.json --after 修订稿.json');
  const options = {};
  const allowed = command === 'apply' ? ['--file', '--out'] : ['--before', '--after', '--out'];
  for (let i = 1; i < argv.length; i += 2) {
    const key = argv[i];
    if (!allowed.includes(key) || own(options, key)
      || !argv[i + 1] || argv[i + 1].startsWith('--')) throw new Error(`无效或重复参数：${key}`);
    options[key] = argv[i + 1];
  }
  if (command === 'apply') {
    if (!options['--file']) throw new Error('apply 必须提供 --file');
  } else if (!options['--before'] || !options['--after']) throw new Error('必须提供 --before 和 --after');
  return options;
}

function applyInPlace(options) {
  const target = fs.realpathSync(options['--file']);
  const parse = (text) => JSON.parse(text.replace(/^\uFEFF/, ''));
  const input = parse(fs.readFileSync(0, 'utf8'));
  if (!plain(input) || !own(input, 'before') || !own(input, 'after')) {
    throw new Error('标准输入必须提供 {before, after}：修改前完整对象与内存修订后的完整对象');
  }
  const current = fs.readFileSync(target, 'utf8');
  if (!isDeepStrictEqual(parse(current), input.before)) throw new Error('storyboard 已变化，未写入；请重新读取当前文件后修订');
  const result = reviewBoards(input.before, input.after);
  const report = renderReview(result);
  const code = result.violations.length || result.attention.some((item) => item.startsWith('[G06]')) ? 2 : 0;
  if (options['--out']) {
    const out = path.resolve(options['--out']);
    const targetStat = fs.statSync(target);
    const outStat = fs.existsSync(out) ? fs.statSync(out) : null;
    if (out === target || (outStat && (fs.realpathSync(out) === target
      || (outStat.dev === targetStat.dev && outStat.ino === targetStat.ino)))) throw new Error('报告路径不能覆盖 storyboard');
    fs.writeFileSync(out, report, 'utf8');
    process.stdout.write(`对比报告：${out}\n`);
  } else process.stdout.write(report);
  if (code) {
    process.stderr.write('检查未通过或同步待核对，storyboard 未写入。\n');
    return code;
  }
  if (fs.readFileSync(target, 'utf8') !== current) throw new Error('storyboard 在检查期间变化，未写入；请重新读取后修订');
  if (!isDeepStrictEqual(input.before, input.after)) fs.writeFileSync(target, JSON.stringify(input.after, null, 2) + '\n', 'utf8');
  process.stdout.write(`已原位更新：${target}\n`);
  return 0;
}

export function main(argv = process.argv.slice(2)) {
  if (argv.length === 1 && ['--help', '-h'].includes(argv[0])) {
    process.stdout.write('apply --file storyboard.json [--out motion-review.md]\n标准输入：{before, after}，校验通过后更新原文件，不产生版本 JSON；--out 更新指定报告，否则打印报告。\nreview --before 原稿.json --after 修订稿.json [--out motion-review.md]\nreview 保留只读比较，报告拒绝覆盖。\n返回码：0 保护性检查通过，2 保护性问题或同步待核对（apply 不写入），1 输入错误。\n');
    return 0;
  }
  const options = parseArgs(argv);
  if (argv[0] === 'apply') return applyInPlace(options);
  const beforePath = fs.realpathSync(options['--before']);
  const afterPath = fs.realpathSync(options['--after']);
  if (beforePath === afterPath) throw new Error('原稿和修订稿必须是两个独立文件');
  if (path.dirname(beforePath) !== path.dirname(afterPath)) {
    throw new Error('原稿与修订稿应放在同一目录，保留相对素材路径的基准');
  }
  const read = (file) => JSON.parse(fs.readFileSync(file, 'utf8').replace(/^\uFEFF/, ''));
  const result = reviewBoards(read(beforePath), read(afterPath));
  const report = renderReview(result);
  if (options['--out']) {
    fs.writeFileSync(options['--out'], report, { encoding: 'utf8', flag: 'wx' });
    process.stdout.write(`对比报告：${path.resolve(options['--out'])}\n`);
  } else process.stdout.write(report);
  // 未同步提示属于人工核对事项，不伪装成确定的语义错误。
  const pendingSync = result.attention.some((item) => item.startsWith('[G06]'));
  return result.violations.length || pendingSync ? 2 : 0;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try { process.exitCode = main(); }
  catch (error) { process.stderr.write(`${error.message}\n`); process.exitCode = 1; }
}
