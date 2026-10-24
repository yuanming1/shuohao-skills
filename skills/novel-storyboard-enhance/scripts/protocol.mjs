#!/usr/bin/env node
/** 本目录自带的输入与 H3 保护规则；没有跨技能运行依赖。 */
import { isDeepStrictEqual } from 'node:util';

const own = (value, key) => Object.hasOwn(value, key);
const plain = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);
const escapePart = (value) => String(value).replaceAll('~', '~0').replaceAll('/', '~1');
const H3_FIELDS = /^(?:integrated_multimodal_description:|overall_soundscape:|non_diegetic_music:|整体视听描述：|整体音景：|非叙事配乐：)/gm;
const SHOT_MARK = /^\[(?:Shot|镜头)\s+\d+\]/gm;
const BOUND_TOKENS = /<d>[\s\S]*?<\/d>|<Picture\s+\d+>|<图\s*\d+>|@(?:Image\s*\d+|图片\s*\d+|\[图片\d+\])|\(S\d+(?:,\s*S\d+)*\)|\b\d{2}:\d{2}\.\d{3}\b/g;
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

export function differences(before, after, at = '', result = []) {
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

export function h3Signature(text) {
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

export function displayCut(segment, index) {
  return `${segment.id}/f${index + 1}`;
}

export function h3Problems(segment) {
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

