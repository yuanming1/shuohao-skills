#!/usr/bin/env node
/** 比较增强前后分镜，或校验后原位更新；程序门不代替语义与成片复核。 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { isDeepStrictEqual } from 'node:util';
import { validateBoard, differences, h3Signature, h3Problems, displayCut } from './protocol.mjs';
import { hasCompositionChanges, reviewComposition } from './recomposition.mjs';

const REQUIRED_MODES = ['performance', 'camera'];
const MODES = [...REQUIRED_MODES, 'effects'];
const COMMON = new Set(['frame', 'shot', 'note', 'sfx']);
const CAMERA = new Set(['size', 'camera', 'lens', 'cameraPosition', 'composition', 'focus', 'stability']);
const ADDABLE = new Set([...COMMON, ...CAMERA, 'eyeline', 'lighting', 'soundscape']);
const SIZES = ['extreme-wide', 'wide', 'medium', 'close', 'extreme-close'];
const MOVES = ['Static Shot', 'Push In', 'Pull Out', 'Zoom In/Out', 'Pan Left/Right',
  'Truck Left/Right', 'Tilt Up/Down', 'Pedestal Up/Down', 'Arc Shot', 'Tracking Shot',
  'Shake Slightly/Strongly', 'POV', 'Roll Clockwise/Counterclockwise'];
const STABILITY = ['stable', 'slight-shake', 'handheld'];
const GATES = [
  ['G01', '输入与镜头骨架'], ['G02', '故事覆盖、资产与未知数据保护'],
  ['G03', '增强范围与字段合法性'], ['G04', '正文与增强依据'],
  ['G05', 'H3 结构与绑定保护'], ['G06', '逐镜同步提醒'],
];

export function parseModes(value) {
  if (typeof value !== 'string') throw new Error('必须通过 --modes 同时指定 performance,camera；effects 可选');
  const selected = value.split(',').map((item) => item.trim());
  if (!selected.length || selected.some((item) => !MODES.includes(item))
    || new Set(selected).size !== selected.length) throw new Error('增强范围无效或重复；示例：--modes performance,camera');
  const missing = REQUIRED_MODES.filter((mode) => !selected.includes(mode));
  if (missing.length) throw new Error(`缺少必选增强方向：${missing.join('、')}；必须同时选择 performance,camera，effects 可选`);
  return selected;
}

function partsOf(prompt) {
  if (typeof prompt !== 'string') return { shots: [], sound: '' };
  const text = prompt.replaceAll('\r\n', '\n');
  const boundary = text.search(/^(?:overall_soundscape:|整体音景：)/m);
  const description = boundary < 0 ? text : text.slice(0, boundary);
  const markers = [...description.matchAll(/^\[(?:Shot|镜头)\s+\d+\]/gm)];
  const shots = markers.map((marker, index) => description.slice(marker.index, markers[index + 1]?.index ?? description.length).trim());
  const soundHeader = text.match(/^(?:overall_soundscape:|整体音景：)/m);
  const soundRest = soundHeader ? text.slice(soundHeader.index + soundHeader[0].length) : '';
  const musicIndex = soundRest.search(/^(?:non_diegetic_music:|非叙事配乐：)/m);
  const sound = soundRest.slice(0, musicIndex < 0 ? soundRest.length : musicIndex).trim();
  return { shots, sound };
}

function noteIssues(note) {
  return ['起始', '动作', '结束', '接镜', '增强依据'].filter((tag) => {
    const match = typeof note === 'string' && note.match(new RegExp(`${tag}[：:]\\s*([^；;\\n]*?)(?=[；;\\n]|(?:起始|动作|结束|接镜|增强依据)[：:]|$)`));
    return !match || !match[1].trim();
  });
}

function addImpact(impact, kind, label) {
  if (!impact[kind].includes(label)) impact[kind].push(label);
}

export function reviewBoards(before, after, modesText, context = {}) {
  const modes = parseModes(modesText);
  validateBoard(before);
  validateBoard(after);
  const changes = differences(before, after);
  if (hasCompositionChanges(before, after) || context.script || context.scriptBefore) {
    const result = reviewComposition(before, after, {
      camera: CAMERA, sizes: SIZES, moves: MOVES, stability: STABILITY, noteIssues,
    }, context);
    return { changes, ...result, modes };
  }
  const violations = [];
  const attention = new Set();
  const activeCuts = new Set();
  const changedFields = new Map();
  const changedSegments = new Map();
  const impact = { frames: [], spatial: [], continuity: [], neighbors: [] };
  for (const change of changes) {
    const cutMatch = change.path.match(/^\/episodes\/(\d+)\/segments\/(\d+)\/cuts\/(\d+)\/([^/]+)$/);
    const segMatch = change.path.match(/^\/episodes\/(\d+)\/segments\/(\d+)\/(h3Prompt|soundscape)$/);
    if (!cutMatch && !segMatch) {
      violations.push(`[G02] 受保护字段发生变化：${change.path}`);
      continue;
    }
    const match = cutMatch ?? segMatch;
    const ei = Number(match[1]);
    const si = Number(match[2]);
    const oldSegment = before.episodes[ei].segments[si];
    const newSegment = after.episodes[ei]?.segments?.[si];
    if (!newSegment || oldSegment.id !== newSegment.id) {
      violations.push(`[G02] 段落身份或结构发生变化：${change.path}`);
      continue;
    }
    const field = cutMatch ? match[4] : match[3];
    if (cutMatch && !COMMON.has(field) && !CAMERA.has(field) && !['eyeline', 'lighting'].includes(field)) {
      violations.push(`[G02] 受保护字段发生变化：${change.path}`);
      continue;
    }
    const permitted = !cutMatch || COMMON.has(field)
      || (CAMERA.has(field) && modes.includes('camera'))
      || (field === 'eyeline' && (modes.includes('performance') || modes.includes('camera')))
      || (field === 'lighting' && (modes.includes('effects') || modes.includes('camera')));
    if (!permitted) {
      violations.push(`[G03] 所选增强范围不允许修改 ${change.path}`);
      continue;
    }
    if (typeof change.after !== 'string' || !change.after.trim()
      || (change.before === undefined && !ADDABLE.has(field))
      || (change.before !== undefined && typeof change.before !== 'string')) {
      violations.push(`[G03] 画面、动作、摄影和声音字段可补齐，修改后必须为非空文字：${change.path}`);
      continue;
    }
    if ((field === 'size' && !SIZES.includes(change.after))
      || (field === 'camera' && !MOVES.includes(change.after))
      || (field === 'stability' && !STABILITY.includes(change.after))) {
      violations.push(`[G03] 字段枚举不合法：${change.path}`);
    }
    changedSegments.set(`${ei}/${si}`, [oldSegment, newSegment]);
    if (cutMatch) {
      const ci = Number(match[3]);
      const label = displayCut(oldSegment, ci);
      activeCuts.add(label);
      if (!changedFields.has(label)) changedFields.set(label, new Set());
      changedFields.get(label).add(field);
      if (!['note', 'sfx'].includes(field)) addImpact(impact, 'frames', label);
      if (CAMERA.has(field)) addImpact(impact, 'spatial', label);
      if (field !== 'note') addImpact(impact, 'continuity', label);
      const sequence = before.episodes[ei].segments.flatMap((seg) => seg.cuts.map((_, i) => displayCut(seg, i)));
      const position = sequence.indexOf(label);
      sequence.slice(Math.max(0, position - 1), position + 2).forEach((item) => addImpact(impact, 'neighbors', item));
    } else {
      if (field === 'soundscape') oldSegment.cuts.forEach((_, ci) => {
        const label = displayCut(oldSegment, ci);
        activeCuts.add(label);
        addImpact(impact, 'continuity', label);
      });
      if (field === 'h3Prompt' && !isDeepStrictEqual(h3Signature(change.before), h3Signature(change.after))) {
        violations.push(`[G05] H3 对齐行、镜头与切点、图片、台词、说话人标记、字段标题或配乐发生变化：${oldSegment.id}`);
      }
    }
  }
  for (const [oldSegment, newSegment] of changedSegments.values()) {
    const oldH3 = partsOf(oldSegment.h3Prompt);
    const newH3 = partsOf(newSegment.h3Prompt);
    oldSegment.cuts.forEach((_, ci) => {
      const label = displayCut(oldSegment, ci);
      const fields = changedFields.get(label) ?? new Set();
      const visualChanged = [...fields].some((field) => !['note', 'sfx'].includes(field));
      const h3Changed = oldH3.shots[ci] !== newH3.shots[ci];
      if (h3Changed) {
        activeCuts.add(label);
        addImpact(impact, 'frames', label);
        addImpact(impact, 'continuity', label);
        const episode = before.episodes.find((item) => item.segments.includes(oldSegment));
        const sequence = episode.segments.flatMap((seg) => seg.cuts.map((_, i) => displayCut(seg, i)));
        const position = sequence.indexOf(label);
        sequence.slice(Math.max(0, position - 1), position + 2).forEach((item) => addImpact(impact, 'neighbors', item));
      }
      if (visualChanged && !h3Changed) attention.add(`[G06] ${label}：画面或摄影文字已变，对应 H3 镜头未变；需核对同步。`);
      if (h3Changed && !visualChanged) attention.add(`[G06] ${label}：H3 镜头已变，关键帧、镜头正文和摄影字段未变；需核对另一消费端。`);
      if (fields.has('sfx') && oldH3.sound === newH3.sound && !h3Changed) attention.add(`[G06] ${label}：音效已变，H3 镜头及声景未变。`);
    });
    const seedSoundChanged = oldSegment.soundscape !== newSegment.soundscape
      || oldSegment.cuts.some((_, ci) => changedFields.get(displayCut(oldSegment, ci))?.has('sfx'));
    if (oldH3.sound !== newH3.sound) oldSegment.cuts.forEach((_, ci) => {
      const label = displayCut(oldSegment, ci);
      activeCuts.add(label);
      addImpact(impact, 'continuity', label);
    });
    if (oldH3.sound !== newH3.sound && !seedSoundChanged) attention.add(`[G06] ${oldSegment.id}：H3 声景已变，Seedance 声景及逐镜音效未变。`);
    if (oldSegment.soundscape !== newSegment.soundscape && oldH3.sound === newH3.sound) attention.add(`[G06] ${oldSegment.id}：Seedance 声景已变，H3 声景未变。`);
  }
  after.episodes.forEach((episode) => episode.segments.forEach((segment) => {
    h3Problems(segment).forEach((issue) => violations.push(`[G05] ${segment.id}：${issue}`));
    segment.cuts.forEach((cut, ci) => {
      const label = displayCut(segment, ci);
      for (const field of ['frame', 'shot']) {
        if (typeof cut[field] !== 'string' || !cut[field].trim()) violations.push(`[G04] ${label} 缺少非空 ${field}`);
      }
      if (activeCuts.has(label)) {
        noteIssues(cut.note).forEach((tag) => violations.push(`[G04] ${label} 缺少有内容的“${tag}：”说明`));
        const fields = changedFields.get(label) ?? new Set();
        if ([...fields].some((field) => CAMERA.has(field))) {
          for (const field of [...CAMERA, 'eyeline']) {
            if (typeof cut[field] !== 'string' || !cut[field].trim()) violations.push(`[G04] ${label} 摄影资料缺少 ${field}`);
          }
        }
      }
    });
  }));
  return { changes, violations, attention: [...attention], modes, impact };
}

export function gateChecks(result) {
  return GATES.map(([id, name]) => ({ id, name,
    issues: [...result.violations, ...result.attention].filter((item) => item.startsWith(`[${id}]`)) }));
}

function fenced(value) {
  const text = value === undefined ? '（字段原来不存在）' : typeof value === 'string' ? value : JSON.stringify(value, null, 2);
  const fence = '`'.repeat(Math.max(3, ...(text.match(/`+/g) ?? []).map((run) => run.length + 1)));
  return `${fence}text\n${text}\n${fence}`;
}

export function renderReview(result) {
  const list = (items) => items.join('、') || '未检测到';
  const lines = ['# 分镜表现增强对比 · v2', '', `增强范围：${result.modes.join('、')}；修改字段：${result.changes.length}。`, '',
    '本报告检查修改范围与协议结构。程序通过不证明剧情、表演、空间、动作或成片成立。', '',
    '## 程序检测门', '', '| 编号 | 检测内容 | 结果 |', '|---|---|---|',
    ...gateChecks(result).map((gate) => `| ${gate.id} | ${gate.name} | ${gate.issues.length ? (gate.id === 'G06' ? '待核对' : '未通过') : '通过'} |`), '',
    'G01 输入失败时停止比较并返回 1；G04 只检查材料存在，G06 只标记可能的漏同步。', '',
    '## 问题与同步提醒', '',
    ...[...result.violations, ...result.attention].map((issue) => `- ${issue}`),
    ...(!result.violations.length && !result.attention.length ? ['未发现程序可确定的问题；仍需完成下列语义复核。'] : []), '',
    '## 待完成的语义复核', '',
    '- 剧情与收益：有何具体改善，是否改变人物意图、能力、对白或事件结果？',
    '- 表演与可见性（必选）：检查上游省略是否丢失进入、移动、操作或关键反应；把已有性格与意图落实到可见行动、节奏和对人的回应。缺失过程是否已经补入正文，景别、时长、口型和连续状态是否支持？',
    '- 摄影与空间（必选）：把整组观看过程对应到镜号，判断原组合怎样引导注意力；有疑点的相关镜头比较具体选择与取舍，再核对逐镜观察任务和构图配合。修改前后注意对象、关系理解或情绪发展有什么差别？机位、轴线、遮挡、路径、参考图片及原对白绑定是否相容？',
    '- 特效与连续状态：来源、变化、结果、消散是否成立，手部占用、支撑与声源是否继承？',
    '- 消费端与素材：frame、shot、摄影字段、H3 和声音是否一致，哪些图片及导出包需更新？', '',
    '以上项目均待 Agent 按镜头组及具体镜号填写通过、不适用或未解决及其依据；程序不自动划分镜头组或填写通过。',
    '增强说明应记录各组镜号范围、对应镜号的观看过程、原组合判断、选定调整及前后表达差别，并区分仅供上下文读取的镜号。全组保留时说明各镜怎样配合；局部改善如实限定收益，逐镜结论可引用具体整组依据。',
    '脚本可以整理原文和已作出的判断，不得按未修改状态自动生成保留成立的结论。仅复述原动作并附通用理由不足以证明评估完成；缺少判断的镜头标为待评估。镜号覆盖和报告行数只证明材料覆盖。',
    '表演与摄影必须覆盖评估范围，未修改也需说明保留理由；必要的补演、拆并镜、时长重分或续段站位调整应在本次完成并同步。上游写了省略、镜头原本存在或程序门通过，都不是保留理由。未选择特效时仅特效增强可整项标为不适用，连续状态仍须复核。缺少实际补全、整组复核或任一必选方向的逐镜评估时为部分完成。', '',
    '## 受影响材料', '',
    `需核对或重出关键帧：${list(result.impact.frames)}。`, '',
    `需复核空间：${list(result.impact.spatial)}。`, '',
    `需复核动作与连续状态：${list(result.impact.continuity)}。`, '',
    `前后镜头影响提示：${list(result.impact.neighbors)}。此处不是完整镜头组；按连续表达单元连读，状态来源更早或影响更远时继续追查。`, '',
    'H3、shot 或声景改变后重新核对视频导出包。旧图片和视频不会随文字自动更新。', '',
    '## 字段对比', ''];
  for (const change of result.changes) lines.push(`### ${change.path}`, '', '原稿：', '', fenced(change.before), '', '修订：', '', fenced(change.after), '');
  if (!result.changes.length) lines.push('两份数据相同；须说明省略与人物表现已经充分的具体依据，才能认定无需增强。', '');
  return lines.join('\n');
}

function parseArgs(argv) {
  const command = argv[0];
  if (!['review', 'apply'].includes(command)) throw new Error('命令格式：apply --file storyboard.json --modes performance,camera；标准输入提供 {before, after}，或使用 review --before 原稿.json --after 修订稿.json');
  const options = {};
  const allowed = command === 'apply' ? ['--file', '--modes', '--out', '--script'] : ['--before', '--after', '--modes', '--out', '--script', '--script-before'];
  for (let i = 1; i < argv.length; i += 2) {
    const key = argv[i];
    if (!allowed.includes(key) || Object.hasOwn(options, key)
      || !argv[i + 1] || argv[i + 1].startsWith('--')) throw new Error(`无效或重复参数：${key}`);
    options[key] = argv[i + 1];
  }
  if (command === 'apply') {
    if (!options['--file']) throw new Error('apply 必须提供 --file');
  } else if (!options['--before'] || !options['--after']) throw new Error('必须提供 --before 和 --after');
  parseModes(options['--modes']);
  return options;
}

function applyInPlace(options) {
  const target = fs.realpathSync(options['--file']);
  const parse = (text) => JSON.parse(text.replace(/^\uFEFF/, ''));
  const input = parse(fs.readFileSync(0, 'utf8'));
  if (!input || typeof input !== 'object' || Array.isArray(input)
    || !Object.hasOwn(input, 'before') || !Object.hasOwn(input, 'after')) {
    throw new Error('标准输入必须提供 {before, after}：修改前完整对象与内存修订后的完整对象');
  }
  const current = fs.readFileSync(target, 'utf8');
  if (!isDeepStrictEqual(parse(current), input.before)) throw new Error('storyboard 已变化，未写入；请重新读取当前文件后修订');
  const scriptText = options['--script'] ? fs.readFileSync(options['--script'], 'utf8') : undefined;
  const context = { script: scriptText === undefined ? undefined : parse(scriptText), scriptBefore: input.scriptBefore };
  const result = reviewBoards(input.before, input.after, options['--modes'], context);
  const report = renderReview(result);
  const code = result.violations.length || result.attention.some((item) => item.startsWith('[G06]')) ? 2 : 0;
  if (options['--out']) {
    const out = path.resolve(options['--out']);
    const outStat = fs.existsSync(out) ? fs.statSync(out) : null;
    for (const inputPath of [target, options['--script']].filter(Boolean)) {
      const protectedPath = fs.realpathSync(inputPath);
      const protectedStat = fs.statSync(protectedPath);
      if (out === protectedPath || (outStat && (fs.realpathSync(out) === protectedPath
        || (outStat.dev === protectedStat.dev && outStat.ino === protectedStat.ino)))) throw new Error('报告路径不能覆盖 storyboard 或正式剧本');
    }
    fs.writeFileSync(out, report, 'utf8');
    process.stdout.write(`对比报告：${out}\n`);
  } else process.stdout.write(report);
  if (code) {
    process.stderr.write('检查未通过或同步待核对，storyboard 未写入。\n');
    return code;
  }
  if (fs.readFileSync(target, 'utf8') !== current) throw new Error('storyboard 在检查期间变化，未写入；请重新读取后修订');
  if (scriptText !== undefined && fs.readFileSync(options['--script'], 'utf8') !== scriptText) throw new Error('剧本在检查期间变化，未写入；请重新读取后修订');
  if (!isDeepStrictEqual(input.before, input.after)) fs.writeFileSync(target, JSON.stringify(input.after, null, 2) + '\n', 'utf8');
  process.stdout.write(`已原位更新：${target}\n`);
  return 0;
}

export function main(argv = process.argv.slice(2)) {
  if (argv.length === 1 && ['--help', '-h'].includes(argv[0])) {
    process.stdout.write('apply --file storyboard.json --modes performance,camera [--script 正式剧本.json] [--out 对比.md]\n标准输入：{before, after}；展开剧本动作时另提供 scriptBefore 修改前剧本对象，--script 指向已同步的正式剧本。校验通过后更新原文件，不产生版本 JSON。\nreview --before 原稿.json --after 修订稿.json --modes performance,camera [--script 正式剧本.json] [--script-before 修改前剧本.json] [--out 对比.md]\nreview 保留只读比较，报告拒绝覆盖。performance 与 camera 必选；effects 可选。\n返回码：0 程序门通过，2 程序门失败或同步待核对（apply 不写入），1 输入错误。\n');
    return 0;
  }
  const options = parseArgs(argv);
  if (argv[0] === 'apply') return applyInPlace(options);
  const beforePath = fs.realpathSync(options['--before']);
  const afterPath = fs.realpathSync(options['--after']);
  if (beforePath === afterPath) throw new Error('原稿与增强稿必须是两个独立文件');
  if (path.dirname(beforePath) !== path.dirname(afterPath)) throw new Error('两份分镜应在同一目录，以保留素材相对路径的基准');
  const read = (file) => JSON.parse(fs.readFileSync(file, 'utf8').replace(/^\uFEFF/, ''));
  const result = reviewBoards(read(beforePath), read(afterPath), options['--modes'], {
    script: options['--script'] ? read(options['--script']) : undefined,
    scriptBefore: options['--script-before'] ? read(options['--script-before']) : undefined,
  });
  const report = renderReview(result);
  if (options['--out']) {
    fs.writeFileSync(options['--out'], report, { encoding: 'utf8', flag: 'wx' });
    process.stdout.write(`对比报告：${path.resolve(options['--out'])}\n`);
  } else process.stdout.write(report);
  return result.violations.length || result.attention.some((item) => item.startsWith('[G06]')) ? 2 : 0;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try { process.exitCode = main(); }
  catch (error) { process.stderr.write(`${error.message}\n`); process.exitCode = 1; }
}
