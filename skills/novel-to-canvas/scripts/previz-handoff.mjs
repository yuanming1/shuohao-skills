import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, extname, resolve } from "node:path";

const MODES = new Set(["locked-storyboard", "locked-blocking-grid"]);
const LABELS = { size: "景别", lens: "焦距", cameraPosition: "机位", composition: "构图", eyeline: "视线", focus: "焦点" };
const SIZES = { wide: "全景", medium: "中景", close: "特写", extreme_close: "大特写" };
const MIME = { ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp" };
const text = (value) => typeof value === "string" ? value.trim() : "";
const assert = (condition, message) => { if (!condition) throw new Error(message); };

export function storyboardSegments(storyboard) {
    const segments = new Map();
    for (const episode of storyboard.episodes || []) for (const segment of episode.segments || []) {
        assert(!segments.has(segment.id), `分镜段号重复：${segment.id}`);
        segments.set(segment.id, segment);
    }
    return segments;
}

export function validateHandoff(data, segment) {
    const sid = data.segment;
    assert(MODES.has(data.mode), `${sid} 的预演模式不支持：${data.mode}`);
    assert(typeof sid === "string" && /^[\p{L}\p{N}_-]+$/u.test(sid), "预演段号不能用作安全的文件名。");
    assert(segment?.id === sid, `预演段号与分镜不匹配：${sid}`);
    assert(Array.isArray(data.panels) && data.panels.length === segment.cuts.length, `${sid} 的预演格数与分镜不一致。`);
    assert(data.layout && Number.isInteger(data.layout.columns) && data.layout.columns > 0 && Number.isInteger(data.layout.rows) && data.layout.rows > 0 && data.layout.columns * data.layout.rows >= data.panels.length, `${sid} 的预演布局无效。`);
    assert(["source", "16:9", "9:16", "1:1"].includes(data.layout.aspect), `${sid} 的预演画幅无效。`);
    let start = 0;
    data.panels.forEach((panel, index) => {
        const cut = segment.cuts[index];
        const shot = `${sid}-f${index + 1}`;
        const seconds = Number(cut.seconds);
        assert(Number.isFinite(seconds) && seconds > 0, `${shot} 的分镜时长无效。`);
        const end = start + seconds;
        assert(panel.shot === shot && panel.size === cut.size && panel.frame === cut.frame, `${shot} 的预演镜号、景别或画面与当前分镜不一致；请同步上游并重新导出预演。`);
        assert(Array.isArray(panel.time) && panel.time.length === 2 && panel.time.every((value) => typeof value === "string" && value.trim() && Number.isFinite(Number(value))) && Math.abs(Number(panel.time[0]) - start) < 1e-7 && Math.abs(Number(panel.time[1]) - end) < 1e-7, `${shot} 的预演切点与当前分镜不一致。`);
        start = end;
    });
    if (data.mode === "locked-blocking-grid") {
        assert(text(data.planning?.opening) && Array.isArray(data.planning?.shots) && data.planning.shots.length === segment.cuts.length, `${sid} 缺少完整的站位与逐镜拍摄安排。`);
        reconcile(segment.blocking, data.planning.opening, `${sid} 开场站位`);
        data.planning.shots.forEach((plan, index) => {
            const shot = `${sid}-f${index + 1}`;
            const cut = segment.cuts[index];
            assert(plan.shot === shot && text(plan.view?.position) && text(plan.view?.composition) && text(plan.view?.eyeline) && text(plan.continuity) && text(plan.action), `${shot} 的站位宫格拍摄信息不完整。`);
            for (const [field, value] of [["cameraPosition", plan.view.position], ["composition", plan.view.composition], ["eyeline", plan.view.eyeline], ["note", plan.continuity], ["shot", plan.action]]) reconcile(cut[field], value, `${shot} ${field}`);
        });
    } else {
        assert(data.planning == null, `${sid} 的普通宫格不能携带未经识别的 planning；请使用 locked-blocking-grid。`);
    }
}

function reconcile(source, planned, label) {
    assert(!text(source) || !text(planned) || text(source) === text(planned), `${label} 在分镜与预演中冲突；请同步上游后重新导出，不能静默选择一版。`);
}

export function loadPreviz(directory, storyboard) {
    const root = resolve(directory);
    assert(existsSync(root) && statSync(root).isDirectory(), `预演目录不存在：${root}`);
    const segments = storyboardSegments(storyboard);
    const candidates = new Map();
    const visit = (folder) => {
        // grid.todo 撤下整个段的旧交付；不读取 .stale，也不跟随目录符号链接。
        if (existsSync(resolve(folder, "grid.todo"))) return;
        for (const entry of readdirSync(folder, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
            if (entry.name.endsWith(".stale")) continue;
            const path = resolve(folder, entry.name);
            if (entry.isDirectory()) visit(path);
            else if (entry.isFile() && entry.name === "grid-input.json") {
                const data = JSON.parse(readFileSync(path, "utf8").replace(/^\uFEFF/, ""));
                if (!segments.has(data.segment)) continue;
                assert(MODES.has(data.mode), `${path} 的预演模式不支持。`);
                const group = candidates.get(data.segment) || [];
                group.push({ data, path });
                candidates.set(data.segment, group);
            }
        }
    };
    visit(root);
    const result = new Map();
    for (const [sid, group] of candidates) {
        const blocking = group.filter((item) => item.data.mode === "locked-blocking-grid");
        const choices = blocking.length ? blocking : group;
        assert(choices.length === 1, `${sid} 存在多份同类预演交付；请用 --previz 指定唯一版本目录。`);
        const { data, path } = choices[0];
        validateHandoff(data, segments.get(sid));
        const promptPath = resolve(dirname(path), "grid-prompt.txt");
        assert(existsSync(promptPath), `${sid} 缺少 grid-prompt.txt。`);
        const prompt = readFileSync(promptPath, "utf8");
        assert(prompt.trim(), `${sid} 的宫格提示词为空。`);
        const briefPath = resolve(dirname(path), "grid-brief.md");
        const brief = existsSync(briefPath) ? readFileSync(briefPath, "utf8") : "";
        const references = data.panels.filter((panel) => panel.reference != null).map((panel) => {
            assert(typeof panel.reference === "string" && panel.reference.trim(), `${panel.shot} 的参考图片路径无效。`);
            const imagePath = resolve(dirname(path), panel.reference);
            const ext = extname(imagePath).toLowerCase();
            assert(MIME[ext] && existsSync(imagePath) && statSync(imagePath).isFile() && statSync(imagePath).size > 0, `${panel.shot} 的预演参考图片不存在、为空或格式不支持：${imagePath}`);
            return { shot: panel.shot, path: imagePath, ext, mimeType: MIME[ext] };
        });
        result.set(sid, { data, prompt, brief, references });
    }
    assert(result.size, `预演目录中没有与当前分镜匹配的有效交付：${root}`);
    return result;
}

export function spatialCut(segment, cut, index, handoff) {
    const plan = handoff?.data?.planning?.shots?.[index];
    return {
        opening: text(handoff?.data?.planning?.opening) || text(segment.blocking),
        view: { ...cut, cameraPosition: text(plan?.view?.position) || cut.cameraPosition, composition: text(plan?.view?.composition) || cut.composition, eyeline: text(plan?.view?.eyeline) || cut.eyeline },
        continuity: text(plan?.continuity) || text(cut.note),
        action: text(plan?.action) || text(cut.shot),
    };
}

export function gridComposer(prompt, references) {
    if (!references.length) return prompt;
    return `${prompt}\n\n【预演交付中的参考图片对应】\n${references.map((reference) => `${reference.shot}：@[node:${reference.id}]`).join("\n")}\n每张参考图片只对应标明的镜号；未指定参考图片的镜头仍按原文生成。`;
}

function viewLines(view) {
    return Object.entries(LABELS).flatMap(([field, label]) => text(view[field]) ? [`${label}：${field === "size" ? SIZES[view[field]] || view[field] : text(view[field])}`] : []);
}

export function keyframePrompt(segment, cut, index, handoff) {
    const { opening, view, continuity } = spatialCut(segment, cut, index, handoff);
    const lines = viewLines(view);
    // 承接备注的动作、结束与接镜留在说明节点，不把终态提前写入静帧。
    const start = continuity.match(/(?:^|[；;\n])\s*起始\s*[：:]\s*([\s\S]*?)(?=[；;\n]\s*(?:动作|结束|接镜)\s*[：:]|$)/)?.[1]?.trim();
    if (!opening && !lines.length && !start) return String(cut.frame || "");
    const blocks = [String(cut.frame || "")];
    if (opening) blocks.push(`【本段开场空间】\n${opening}`);
    if (lines.length) blocks.push(`【本镜拍摄】\n${lines.join("\n")}`);
    if (start) blocks.push(`【切点起始状态】\n${start}`);
    blocks.push("只描绘本镜切点的单一瞬间。开场站位提供空间背景，不要求所有人物入镜；后续镜头的人物状态以本镜切点描述为准。视线安排若包含先后变化，只表现切点时的落点，不把后续动作或终态提前画入静帧。");
    return blocks.join("\n\n");
}

export function spatialSummary(segment, handoff) {
    const opening = text(handoff?.data?.planning?.opening) || text(segment.blocking);
    const blocks = [`${segment.id} · 站位与拍摄说明`, "这是导入的空间与拍摄安排，尚未验证实际几何、图像或动作连续性。"];
    if (opening) blocks.push(`【开场站位】\n${opening}`);
    let time = 0;
    segment.cuts.forEach((cut, index) => {
        const details = spatialCut(segment, cut, index, handoff);
        const end = time + Number(cut.seconds);
        const lines = [`【镜头 ${index + 1} · ${time.toFixed(3)}–${end.toFixed(3)} 秒】`, `切点画面：${cut.frame}`, ...viewLines(details.view)];
        if (details.continuity) lines.push(`动作承接（完整原文）：${details.continuity}`);
        if (details.action) lines.push(`视频动作（不等于静帧状态）：${details.action}`);
        blocks.push(lines.join("\n"));
        time = end;
    });
    if (handoff?.brief) blocks.push(`【预演交接原文】\n${handoff.brief}`);
    return blocks.join("\n\n");
}
