/** 从正式剧本取得事实边界；动作可以细分，原对白与非动作事实保持。 */
import { isDeepStrictEqual } from 'node:util';

const omit = (value, field) => Object.fromEntries(Object.entries(value).filter(([key]) => key !== field));
const action = (item) => item && typeof item.action === 'string' && item.action.trim()
  && Object.keys(item).length === 1;

function actionBridge(before, after) {
  if (!Array.isArray(before) || !Array.isArray(after)) throw new Error('[G01] 剧本场次缺少 flow');
  const lengths = Array.from({ length: before.length + 1 }, () => new Uint32Array(after.length + 1));
  for (let i = before.length - 1; i >= 0; i--) for (let j = after.length - 1; j >= 0; j--) {
    lengths[i][j] = isDeepStrictEqual(before[i], after[j]) ? lengths[i + 1][j + 1] + 1
      : Math.max(lengths[i + 1][j], lengths[i][j + 1]);
  }
  const anchors = [];
  let i = 0; let j = 0;
  while (i < before.length && j < after.length) {
    if (isDeepStrictEqual(before[i], after[j])) { anchors.push([i++, j++]); }
    else if (lengths[i + 1][j] >= lengths[i][j + 1]) i++;
    else j++;
  }
  anchors.push([before.length, after.length]);
  const bridge = new Map();
  let oldStart = 0; let newStart = 0;
  for (const [oldEnd, newEnd] of anchors) {
    const oldBlock = before.slice(oldStart, oldEnd);
    const newBlock = after.slice(newStart, newEnd);
    if (oldBlock.length || newBlock.length) {
      if (!oldBlock.length || !newBlock.length || !oldBlock.every(action) || !newBlock.every(action)
        || (oldBlock.length !== 1 && oldBlock.length !== newBlock.length)) {
        throw new Error('[G02] 剧本修订仅允许展开原动作；不能新增或删除事件、改对白，或以不明确映射替换多个事件');
      }
      newBlock.forEach((_, offset) => bridge.set(newStart + offset + 1,
        oldStart + (oldBlock.length === 1 ? 0 : offset) + 1));
    }
    if (oldEnd < before.length) bridge.set(newEnd + 1, oldEnd + 1);
    oldStart = oldEnd + 1; newStart = newEnd + 1;
  }
  return bridge;
}

export function scriptContext(script, previous, ep, oldKeys) {
  if (!script) {
    if (previous) throw new Error('[G01] 提供 scriptBefore 时还须通过 --script 指定已同步的正式剧本');
    return null;
  }
  if (!Array.isArray(script.episodes) || !script.episodes.length) throw new Error('[G01] 剧本缺少 episodes');
  if (previous && (!Array.isArray(previous.episodes)
    || !isDeepStrictEqual(omit(previous, 'episodes'), omit(script, 'episodes'))
    || !isDeepStrictEqual(previous.episodes.map((item) => item.ep), script.episodes.map((item) => item.ep)))) {
    throw new Error('[G02] 展开动作不能改变剧本全局设定、集数或集序');
  }
  const current = script.episodes.find((item) => item.ep === ep);
  const original = (previous ?? script).episodes.find((item) => item.ep === ep);
  if (!current || !original || !Array.isArray(current.scenes) || !Array.isArray(original.scenes)) {
    throw new Error(`[G01] 剧本缺少第${ep}集或 scenes`);
  }
  if (!isDeepStrictEqual(omit(original, 'scenes'), omit(current, 'scenes')) || original.scenes.length !== current.scenes.length) {
    throw new Error(`[G02] 第${ep}集只能展开动作，不改变场次、钩子、结果或时长目标`);
  }
  const expected = [];
  const beforeKeys = [];
  const bridge = new Map();
  current.scenes.forEach((scene, index) => {
    const oldScene = original.scenes[index];
    if (!isDeepStrictEqual(omit(oldScene, 'flow'), omit(scene, 'flow'))) {
      throw new Error(`[G02] 第${ep}集第${index + 1}场的地点、在场人物或其他事实发生变化`);
    }
    const mapping = actionBridge(oldScene.flow, scene.flow);
    oldScene.flow.forEach((_, beat) => beforeKeys.push(`${index + 1}/${beat + 1}`));
    scene.flow.forEach((_, beat) => {
      const key = `${index + 1}/${beat + 1}`;
      expected.push(key);
      bridge.set(key, `${index + 1}/${mapping.get(beat + 1)}`);
    });
  });
  if (!isDeepStrictEqual(oldKeys, beforeKeys)) {
    throw new Error(`[G02] 第${ep}集原分镜节拍与${previous ? '修改前' : '正式'}剧本不一致，须读取匹配的基线`);
  }
  return { episode: current, bridge, expected };
}
