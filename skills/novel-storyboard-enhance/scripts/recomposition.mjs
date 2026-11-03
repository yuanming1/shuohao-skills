/** 增强中的镜头重排：保护既有事件覆盖与对白，允许重新分镜、分时和续段调度。 */
import { isDeepStrictEqual } from 'node:util';
import { displayCut, h3Problems, h3Signature } from './protocol.mjs';
import { scriptContext } from './story-contract.mjs';

const CUT_EDITABLE = new Set(['beats', 'seconds', 'characters', 'props', 'frame', 'shot', 'note', 'sfx',
  'size', 'camera', 'lens', 'cameraPosition', 'composition', 'eyeline', 'focus', 'stability', 'lighting']);
const SEG_EDITABLE = new Set(['id', 'cuts', 'blocking', 'h3Prompt', 'soundscape']);
const omit = (value, keys) => Object.fromEntries(Object.entries(value).filter(([key]) => !keys.has(key)));

export function hasCompositionChanges(before, after) {
  const shape = (board) => board.episodes.map((episode) => [episode.ep, episode.segments.map((segment) =>
    [segment.id, segment.sceneIndex, segment.blocking, segment.cuts.map((cut) =>
      [cut.beats, cut.seconds, cut.characters, cut.props])])]);
  return !isDeepStrictEqual(shape(before), shape(after));
}

function records(episode) {
  return episode.segments.flatMap((segment) => segment.cuts.map((cut, ci) => {
    const keys = [];
    for (let beat = cut.beats[0]; beat <= cut.beats[1]; beat++) keys.push(`${segment.sceneIndex}/${beat}`);
    return { segment, cut, keys, label: displayCut(segment, ci) };
  }));
}

function spoken(episode) {
  const result = [];
  for (const segment of episode.segments) {
    const blocks = h3Signature(segment.h3Prompt)[2];
    blocks.forEach(([, tokens], ci) => {
      let speaker = '';
      for (const token of tokens) {
        if (/^\(S\d/.test(token)) speaker = token;
        if (token.startsWith('<d>') && segment.cuts[ci]) {
          result.push({ text: token, speaker, scene: segment.sceneIndex, beats: segment.cuts[ci].beats });
        }
      }
    });
  }
  return result;
}

function shotBodies(segment) {
  const text = String(segment.h3Prompt ?? '').replaceAll('\r\n', '\n');
  const end = text.search(/^(?:overall_soundscape:|整体音景：)/m);
  const description = end < 0 ? text : text.slice(0, end);
  const markers = [...description.matchAll(/^\[(?:Shot|镜头)\s+\d+\]/gm)];
  return markers.map((marker, index) => description.slice(marker.index, markers[index + 1]?.index ?? description.length)
    .replace(/^\[(?:Shot|镜头)\s+\d+\]\s*(?:(?:At|于)\s+\d{2}:\d{2}\.\d{3}[,，]\s*)?/, '')
    .replace(/<(?:Picture|图)\s*\d+>/g, '<Picture>').trim());
}

function soundOf(segment) {
  const text = String(segment.h3Prompt ?? '').replaceAll('\r\n', '\n');
  const header = text.match(/^(?:overall_soundscape:|整体音景：)/m);
  if (!header) return '';
  const rest = text.slice(header.index + header[0].length);
  const end = rest.search(/^(?:non_diegetic_music:|非叙事配乐：)/m);
  return rest.slice(0, end < 0 ? undefined : end).trim();
}

export function alignmentLine(cuts, zh = false) {
  if (cuts.length === 1) return zh ? '目标视频在 0.00 秒处完全参照图 1（来自镜头 1）。'
    : 'For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.';
  let elapsed = 0;
  const parts = cuts.map((cut, index) => {
    const time = (Math.round(elapsed * 10) / 10).toFixed(2);
    elapsed += cut.seconds;
    return zh ? `图 ${index + 1}（来自镜头 ${index + 1}）对齐目标视频 ${time} 秒处`
      : `Picture ${index + 1} (from Shot ${index + 1}) aligns with the ${time}-second mark of the target video`;
  });
  return zh ? `参考图与目标视频的对齐——${parts.join('；')}。`
    : `How the reference pictures align with the target video — ${parts.join('; ')}.`;
}

export function reviewComposition(before, after, rules, context = {}) {
  const violations = [];
  const attention = [];
  const impact = { frames: [], spatial: [], continuity: [], neighbors: [] };
  const fail = (gate, message) => violations.push(`[${gate}] ${message}`);
  const sameMeta = (oldValue, newValue, ignored, label) => {
    if (!isDeepStrictEqual(omit(oldValue, ignored), omit(newValue, ignored))) {
      fail('G02', `${label} 的场次、配乐、全局设定或未知字段发生变化`);
    }
  };
  sameMeta(before, after, new Set(['episodes']), '顶层');
  if (before.episodes.length !== after.episodes.length) fail('G02', '增强不能增加或删除集数');
  const params = after.params ?? {};
  const min = params.minCutSeconds;
  const max = params.maxCutSeconds;
  const cap = params.maxSegmentSeconds ?? 15;
  after.episodes.forEach((episode, ei) => {
    const oldEpisode = before.episodes[ei];
    if (!oldEpisode) return;
    sameMeta(oldEpisode, episode, new Set(['segments']), `第${episode.ep}集`);
    const oldRecords = records(oldEpisode);
    const newRecords = records(episode);
    const sequence = newRecords.map((item) => item.label);
    const oldKeys = oldRecords.flatMap((item) => item.keys);
    const newKeys = newRecords.flatMap((item) => item.keys);
    const story = scriptContext(context.script, context.scriptBefore, episode.ep, oldKeys);
    if (!isDeepStrictEqual(story?.expected ?? oldKeys, newKeys) || new Set(newKeys).size !== newKeys.length) {
      fail('G02', `第${episode.ep}集重排后须保持原场次和节拍顺序、恰好覆盖一次；不得删除、重复或新增剧情节拍`);
    }
    const originalLookup = new Map(oldRecords.flatMap((item) => item.keys.map((key) => [key, item])));
    const lookup = story ? new Map([...story.bridge].map(([key, source]) => [key, originalLookup.get(source)])) : originalLookup;
    const oldSpeech = spoken(oldEpisode);
    const newSpeech = spoken(episode);
    const voice = (items) => items.map(({ text, speaker, scene }) => [text, speaker, scene]);
    if (!isDeepStrictEqual(voice(oldSpeech), voice(newSpeech))) {
      fail('G05', `第${episode.ep}集对白原文、说话人、场次或发声顺序发生变化`);
    } else oldSpeech.forEach((line, index) => {
      const next = newSpeech[index];
      const origin = [];
      for (let beat = next.beats[0]; beat <= next.beats[1]; beat++) {
        origin.push(Number((story?.bridge.get(`${next.scene}/${beat}`) ?? `${next.scene}/${beat}`).split('/')[1]));
      }
      if (!origin.some((beat) => beat >= line.beats[0] && beat <= line.beats[1])) {
        fail('G05', `第${episode.ep}集对白移到了原节拍范围之外：${line.text}`);
      }
    });
    const sceneAssets = new Map();
    oldRecords.forEach(({ segment, cut }) => {
      if (!sceneAssets.has(segment.sceneIndex)) sceneAssets.set(segment.sceneIndex, { characters: new Set(), props: new Set() });
      const assets = sceneAssets.get(segment.sceneIndex);
      for (const kind of ['characters', 'props']) (cut[kind] ?? []).forEach((id) => assets[kind].add(id));
    });
    story?.episode.scenes.forEach((scene, index) => {
      const assets = sceneAssets.get(index + 1);
      if (assets) for (const kind of ['characters', 'props']) (scene[kind] ?? []).forEach((id) => assets[kind].add(id));
    });
    if (story && Number.isFinite(story.episode.targetSeconds)) {
      const duration = newRecords.reduce((total, item) => total + item.cut.seconds, 0);
      const target = story.episode.targetSeconds;
      const tolerance = params.tolerance ?? 0.15;
      if (duration < target * (1 - tolerance) - 1e-9 || duration > target * (1 + tolerance) + 1e-9) {
        fail('G03', `第${episode.ep}集 ${duration} 秒不在正式剧本 ${target} 秒目标的容差内，须重新分配预算`);
      }
    }
    episode.segments.forEach((segment, si) => {
      if (segment.id !== `E${String(episode.ep).padStart(2, '0')}-${String(si + 1).padStart(2, '0')}`) {
        fail('G02', `重排后段号须连续并属于本集：${segment.id}`);
      }
      const selected = newRecords.filter((item) => item.segment === segment);
      const sources = [...new Set(selected.flatMap((item) => item.keys.map((key) => lookup.get(key)?.segment)).filter(Boolean))];
      for (const source of sources) {
        sameMeta(source, segment, SEG_EDITABLE, segment.id);
        const oldH3 = h3Signature(source.h3Prompt);
        const newH3 = h3Signature(segment.h3Prompt);
        if (!isDeepStrictEqual(oldH3[1], newH3[1]) || oldH3[3] !== newH3[3]) {
          fail('G05', `${segment.id} 重排不能改变 H3 提示词语言、字段标题或配乐`);
        }
        const seedSoundChanged = source.soundscape !== segment.soundscape
          || selected.some((item) => item.keys.some((key) => lookup.get(key)?.cut.sfx !== item.cut.sfx));
        const soundChanged = soundOf(source) !== soundOf(segment);
        if (seedSoundChanged !== soundChanged) attention.push(`[G06] ${segment.id}：重排后的声音仅有一端变化，须核对 H3 与 Seedance 声景及音效。`);
      }
      if (typeof segment.blocking !== 'string' || !segment.blocking.trim()) fail('G04', `${segment.id} 缺少本段开场站位`);
      for (const field of ['soundscape']) if (segment[field] !== undefined && (typeof segment[field] !== 'string' || !segment[field].trim())) {
        fail('G03', `${segment.id} 的 ${field} 必须为非空文字`);
      }
      const duration = segment.cuts.reduce((total, cut) => total + cut.seconds, 0);
      if (duration > cap + 1e-9) fail('G03', `${segment.id} 超过项目单段上限 ${cap} 秒，须重新分段`);
      h3Problems(segment).forEach((issue) => fail('G05', `${segment.id}：${issue}`));
      h3Signature(segment.h3Prompt)[2].forEach(([, tokens], index) => {
        const pictures = tokens.filter((token) => /^<(?:Picture|图)\s*\d+>$/.test(token));
        if (pictures.length !== 1 || !new RegExp(`^<(?:Picture|图)\\s*${index + 1}>$`).test(pictures[0])) {
          fail('G05', `${segment.id}/f${index + 1} 须且仅须绑定本镜对应的图片编号`);
        }
      });
      const text = String(segment.h3Prompt ?? '').replaceAll('\r\n', '\n');
      if (text.split('\n')[0] !== alignmentLine(segment.cuts, text.includes('整体视听描述：'))) {
        fail('G05', `${segment.id} 必须按新切数和时长重新生成 H3 对齐首行`);
      }
      for (const item of selected) {
        const { cut, keys, label } = item;
        const originals = [...new Set(keys.map((key) => lookup.get(key)).filter(Boolean))];
        if (story) {
          const lines = story.episode.scenes[segment.sceneIndex - 1]?.flow.slice(cut.beats[0] - 1, cut.beats[1])
            .filter((beat) => typeof beat.line === 'string').map((beat) => beat.line) ?? [];
          const actual = h3Signature(segment.h3Prompt)[2][segment.cuts.indexOf(cut)]?.[1]
            .filter((token) => token.startsWith('<d>')).map((token) => token.replace(/^<d>(?:\[Chinese\]\s*)?/, '').replace(/<\/d>$/, '')) ?? [];
          if (!isDeepStrictEqual(lines, actual)) fail('G05', `${label} 的逐句对白与正式剧本认领节拍不一致`);
        }
        originals.forEach((source) => sameMeta(source.cut, cut, CUT_EDITABLE, label));
        for (const field of ['characters', 'props']) {
          if (!Array.isArray(cut[field]) || cut[field].some((id) => !sceneAssets.get(segment.sceneIndex)?.[field].has(id))
            || new Set(cut[field]).size !== cut[field].length) fail('G02', `${label} 的 ${field} 只能引用原场次已有资产，且不得重复`);
        }
        if (!Number.isFinite(cut.seconds) || cut.seconds <= 0 || cut.seconds > cap
          || (min != null && cut.seconds < min) || (max != null && cut.seconds > max)) {
          fail('G03', `${label} 须为正有限秒数，且符合单段上限与项目显式镜长范围`);
        }
        for (const field of ['frame', 'shot', 'note', ...rules.camera, 'eyeline']) {
          if (typeof cut[field] !== 'string' || !cut[field].trim()) fail('G04', `${label} 缺少非空 ${field}`);
        }
        for (const field of ['sfx', 'lighting']) if (cut[field] !== undefined && (typeof cut[field] !== 'string' || !cut[field].trim())) {
          fail('G03', `${label} 的 ${field} 必须为非空文字`);
        }
        if (!rules.sizes.includes(cut.size) || !rules.moves.includes(cut.camera) || !rules.stability.includes(cut.stability)) {
          fail('G03', `${label} 景别、运镜或稳定性枚举不合法`);
        }
        const old = originals.length === 1 ? originals[0] : null;
        const same = old && old.segment.id === segment.id && old.label === label
          && isDeepStrictEqual(old.cut, cut) && old.segment.h3Prompt === segment.h3Prompt && old.segment.blocking === segment.blocking;
        if (!same) {
          rules.noteIssues(cut.note).forEach((tag) => fail('G04', `${label} 缺少有内容的“${tag}：”说明`));
          for (const kind of ['frames', 'spatial', 'continuity']) impact[kind].push(label);
          const position = sequence.indexOf(label);
          sequence.slice(Math.max(0, position - 1), position + 2).forEach((neighbor) => {
            if (!impact.neighbors.includes(neighbor)) impact.neighbors.push(neighbor);
          });
          const bodyChanged = !old || ['frame', 'shot', ...rules.camera, 'eyeline', 'lighting'].some((field) => !isDeepStrictEqual(old.cut[field], cut[field]));
          const oldBlock = old && shotBodies(old.segment)[Number(old.label.split('/f')[1]) - 1];
          const newBlock = shotBodies(segment)[segment.cuts.indexOf(cut)];
          // 去除重排生成的镜号、切点和图片编号，再核对实际正文是否单边改动。
          if (bodyChanged && old && oldBlock === newBlock) {
            attention.push(`[G06] ${label}：分镜正文已变，H3 仍为旧稿，须同步。`);
          }
          if (!bodyChanged && old && oldBlock !== newBlock) {
            attention.push(`[G06] ${label}：H3 正文已变但画面和动作仍为原文，须核对另一消费端。`);
          }
          if (old && old.segment.blocking !== segment.blocking && old.segment.h3Prompt === segment.h3Prompt) {
            attention.push(`[G06] ${label}：段级站位已变，H3 仍为旧稿，须核对调度同步。`);
          }
        }
      }
    });
  });
  return { violations, attention, impact };
}
