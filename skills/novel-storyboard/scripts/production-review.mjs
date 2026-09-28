import { createHash } from 'node:crypto';

const hash = (value) => createHash('sha256').update(value).digest('hex');
const segmentsOf = (board) => (board?.episodes ?? []).flatMap((episode) => episode.segments ?? []);
const picturePath = (dir, id) => `${dir === '.' ? '' : `${dir}/`}${id}.png`;

export function reviewTemplate(board, ctx, { readImage = () => null, dir = '.', model = '' } = {}) {
  const segments = segmentsOf(board);
  const cuts = segments.flatMap((segment) => segment.cuts.map((cut, index) => ({
    id: `${segment.id}/f${index + 1}`,
    verdict: 'pending',
    evidence: '',
  })));
  const pictures = cuts.map(({ id }) => {
    const bytes = readImage(picturePath(dir, id));
    return bytes?.length ? hash(bytes) : null;
  });
  return {
    fingerprint: hash(JSON.stringify([board, ctx.script, ctx.outline ?? null, ctx.cast ?? null, ctx.art ?? null, pictures])),
    model,
    segments: segments.map((segment) => ({
      id: segment.id,
      seconds: Math.round(segment.cuts.reduce((total, cut) => total + cut.seconds, 0) * 1e6) / 1e6,
    })),
    cuts,
  };
}

export function productionProblems(board, ctx, review, { readImage = () => null, dir = '.' } = {}) {
  const problems = [];
  const cache = new Map();
  const loadImage = (path) => {
    if (!cache.has(path)) cache.set(path, readImage(path));
    return cache.get(path);
  };
  const expected = reviewTemplate(board, ctx, { readImage: loadImage, dir });
  if (!review || typeof review !== 'object' || Array.isArray(review)) {
    return ['缺少逐切审核记录：先运行 review-template 并实际复核；只交文字请使用 --draft。'];
  }
  if (review.fingerprint !== expected.fingerprint) {
    problems.push('审核已过期：剧本、分镜、上游资料或分镜图发生变化，必须重新审核当前版本。');
  }
  if (review.model !== 'h3') {
    problems.push('当前导出器只提供 H3 提示词契约；确认实际目标为 h3。其他模型必须另行适配，不能原样标为投产通过。');
  }
  if (!Array.isArray(review.segments) || review.segments.length !== expected.segments.length) {
    problems.push('实际提交段清单与分镜不一致，禁止漏段或额外拼段。');
  }
  expected.segments.forEach((segment, index) => {
    const actual = review.segments?.[index];
    if (actual?.id !== segment.id) {
      problems.push(`第 ${index + 1} 段必须是 ${segment.id}，不得按生成完成顺序拼接。`);
    }
    if (!Number.isFinite(actual?.seconds) || Math.abs(actual.seconds - segment.seconds) > 1e-6) {
      problems.push(`${segment.id} 提交时长必须为 ${segment.seconds}s；改时长须同步重排分镜和提示词，禁止静默取整。`);
    }
  });
  if (!Array.isArray(review.cuts) || review.cuts.length !== expected.cuts.length) {
    problems.push('审核必须覆盖全部分镜及每切的入镜承接，不能漏评或重复占位。');
  }
  const cuts = segmentsOf(board).flatMap((segment) => segment.cuts);
  expected.cuts.forEach(({ id }, index) => {
    if (!loadImage(picturePath(dir, id))?.length) problems.push(`${id} 缺少非空分镜图，不能完成视觉审核。`);
    if (!String(cuts[index]?.note ?? '').trim()) problems.push(`${id} 缺少动作承接安排，先规划再审核。`);
    const actual = review.cuts?.[index];
    if (actual?.id !== id) problems.push(`第 ${index + 1} 条审核必须对应 ${id}。`);
    if (actual?.verdict !== 'pass' || typeof actual?.evidence !== 'string' || !actual.evidence.trim()) {
      problems.push(`${id} 未完成带观察依据的通过审核；pending、fail 或空依据都不能投产。`);
    }
  });
  return problems;
}
