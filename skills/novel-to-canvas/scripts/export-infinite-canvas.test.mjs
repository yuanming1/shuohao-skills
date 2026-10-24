import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";
import { loadPreviz, keyframePrompt } from "./previz-handoff.mjs";
import { readStoredZip, writeStoredZip } from "./export-infinite-canvas.mjs";
import { boardAspect, characterBindings, CAMERA } from "./input-contract.mjs";

const cli = resolve(dirname(fileURLToPath(import.meta.url)), "export-infinite-canvas.mjs");
const png = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aTXcAAAAASUVORK5CYII=", "base64");

// 本技能自己的故事：顾客凭票来修伞铺取件，师傅看清票号后抬眼回应。
function fixture(t) {
    const root = mkdtempSync(resolve(tmpdir(), "novel-canvas-test-"));
    t.after(() => rmSync(root, { recursive: true, force: true }));
    const segment = {
        id: "E01-01", sceneIndex: 1, h3Prompt: "Original H3 prompt.",
        blocking: "顾客在工作台外侧，师傅在台后，两人隔台相对。",
        cuts: [
            { seconds: 1.25, size: "medium", frame: "顾客伸手出示取伞票，师傅在工作台后。", cameraPosition: "顾客右后方平视", composition: "顾客肩背在右前景，师傅在左中景", eyeline: "师傅看向取伞票", lens: "50mm", focus: "取伞票", note: "起始：取伞票仍在顾客手中；动作：师傅核对票号；结束：师傅抬头；接镜：接师傅反应。", shot: "师傅看清票号后抬头。", characters: ["C01", "C02"] },
            { seconds: 2.75, size: "close", frame: "师傅抬眼望向顾客，身后是伞架。", cameraPosition: "工作台外侧平视", composition: "师傅居中", eyeline: "顾客眼睛", note: "起始：师傅已经抬眼；动作：说明修理结果；结束：等待顾客回应；接镜：段落结束。", shot: "师傅说伞已经修好。", characters: ["C02"] },
        ],
    };
    const inputs = {
        storyboard: { episodes: [{ ep: 1, segments: [segment] }] },
        script: { episodes: [{ ep: 1, scenes: [{ sceneId: "S01", characters: ["C01", "C02"], props: [], flow: [] }] }] },
        art: { scenes: [{ id: "S01", name: "修伞铺", image: { prompt: "An empty umbrella repair workshop." } }], props: [] },
        cast: { characters: [{ id: "C01", name: "顾客", image: { prompt: "Customer." } }, { id: "C02", name: "师傅", image: { prompt: "Craftsperson." } }] },
    };
    const save = () => {
        for (const [name, data] of Object.entries(inputs)) writeFileSync(resolve(root, `${name}.json`), JSON.stringify(data));
    };
    const run = (...args) => spawnSync(process.execPath, [cli, ...args], { encoding: "utf8" });
    const exportZip = (previz, includeCharacterViews = false, constraints = [], extra = {}) => {
        save();
        const zip = resolve(root, "canvas.zip");
        const args = Object.keys(inputs).flatMap((name) => [`--${name}`, resolve(root, `${name}.json`)]);
        const constraintsPath = resolve(root, "constraints.txt");
        if (constraints.length) writeFileSync(constraintsPath, constraints.join("\n"));
        const result = run("export", ...args, ...(includeCharacterViews ? [] : ["--no-character-views"]), "--out", zip, ...(previz ? ["--previz", previz] : []), ...(constraints.length ? ["--constraints", constraintsPath] : []), ...(extra.images ? ["--images", extra.images] : []), ...(extra.characterImages ? ["--character-images", extra.characterImages] : []), ...(extra.characterSheetsOnly ? ["--character-sheets-only"] : []));
        assert.equal(result.status, 0, result.stderr);
        const entries = readStoredZip(readFileSync(zip));
        const manifest = JSON.parse(entries.get("projects.json").toString("utf8"));
        return { zip, entries, manifest, project: manifest.projects[0].project };
    };
    return { root, inputs, segment, run, exportZip };
}

function handoff(segment, blocking = false) {
    let start = 0;
    const data = {
        mode: blocking ? "locked-blocking-grid" : "locked-storyboard",
        segment: segment.id,
        layout: { columns: 2, rows: 1, aspect: "16:9" },
        panels: segment.cuts.map((cut, index) => {
            const time = [String(start), String(start += cut.seconds)];
            return { shot: `${segment.id}-f${index + 1}`, time, size: cut.size, frame: cut.frame, reference: null };
        }),
    };
    if (blocking) data.planning = {
        opening: segment.blocking,
        shots: segment.cuts.map((cut, index) => ({ shot: `${segment.id}-f${index + 1}`, view: { position: cut.cameraPosition, composition: cut.composition, eyeline: cut.eyeline }, continuity: cut.note, action: cut.shot })),
    };
    return data;
}

function writeHandoff(folder, data, prompt = "Original grid prompt.\r\n保留实际时长，不重分镜。\r\n") {
    mkdirSync(folder, { recursive: true });
    writeFileSync(resolve(folder, "grid-input.json"), JSON.stringify(data));
    writeFileSync(resolve(folder, "grid-prompt.txt"), prompt);
    writeFileSync(resolve(folder, "grid-brief.md"), "核对工作台两侧站位。\n");
    return folder;
}

const nodeNamed = (project, title) => {
    const node = project.nodes.find((item) => item.title === title);
    assert.ok(node, title);
    return node;
};
const incoming = (project, node) => project.connections.filter((edge) => edge.toNodeId === node.id).map((edge) => project.nodes.find((item) => item.id === edge.fromNodeId));
const validate = (context, zip) => {
    const result = context.run("validate", "--zip", zip);
    assert.equal(result.status, 0, result.stderr);
};
const rewriteZip = (context, exported, mutate) => {
    const manifest = structuredClone(exported.manifest);
    const entries = new Map(exported.entries);
    mutate(manifest.projects[0].project, entries);
    entries.set("projects.json", Buffer.from(JSON.stringify(manifest)));
    const zip = resolve(context.root, "modified.zip");
    writeFileSync(zip, writeStoredZip([...entries].map(([name, data]) => ({ name, data }))));
    return zip;
};

test("关键帧保留最终画面原文，规划备注进入说明节点", (t) => {
    const context = fixture(t);
    const before = structuredClone(context.inputs.storyboard);
    const { project, zip, entries } = context.exportZip();
    const frame = nodeNamed(project, "E01-01 · 关键帧 1");
    const prompt = frame.metadata.composerContent;
    assert.equal(frame.type, "config");
    assert.deepEqual(Object.keys(frame.metadata).sort(), ["composerContent", "count", "generationMode", "size", "status"]);
    assert.equal(frame.metadata.generationMode, "image");
    assert.equal(prompt.split("\n\n【参考图片对应】")[0], context.segment.cuts[0].frame);
    assert.ok(!prompt.includes("【本段开场空间】"));
    assert.ok(prompt.startsWith(context.segment.cuts[0].frame));
    assert.ok(!prompt.includes("结束：师傅抬头"));
    const summary = nodeNamed(project, "E01-01 · 站位与拍摄说明").metadata.content;
    assert.ok(summary.includes(context.segment.cuts[0].note));
    assert.equal(nodeNamed(project, "E01-01 · H3 视频").metadata.composerContent, context.segment.h3Prompt);
    assert.deepEqual(JSON.parse(entries.get("source/storyboard.json")), before);
    assert.deepEqual(context.inputs.storyboard, before);
    assert.equal(project.nodes.filter((node) => node.type === "config").length, context.segment.cuts.length + 2);
    const instructions = nodeNamed(project, "E01-01 · 关键帧操作说明").metadata.content;
    assert.ok(instructions.includes("图片1 ← E01-01 · 关键帧 1"));
    assert.ok(instructions.includes("图片2 ← E01-01 · 关键帧 2"));
    for (const label of ["H3", "豆包 Seedance"]) assert.deepEqual(incoming(project, nodeNamed(project, `E01-01 · ${label} 视频`)), []);
    assert.equal(JSON.parse(entries.get("source/canvas-input.json")).version, 4);
    const second = nodeNamed(project, "E01-01 · 关键帧 2");
    assert.ok(second.position.x > frame.position.x + 340 + 96 + 340); // 画布默认在右侧创建结果图片。
    validate(context, zip);
});

test("两类视频使用可编辑组合节点，保留原文、时长、画幅和参考模式", (t) => {
    const context = fixture(t);
    const { project, zip } = context.exportZip();
    for (const label of ["H3", "豆包 Seedance"]) {
        const node = nodeNamed(project, `E01-01 · ${label} 视频`);
        const original = nodeNamed(project, `E01-01 · ${label} 提示词`);
        assert.equal(node.type, "config");
        assert.deepEqual(Object.keys(node.metadata).sort(), ["composerContent", "generationMode", "seconds", "size", "videoMode"]);
        assert.equal(node.metadata.generationMode, "video");
        assert.equal(node.metadata.seconds, "4");
        assert.equal(node.metadata.size, "16:9");
        assert.equal(node.metadata.videoMode, "reference");
        assert.equal(node.metadata.composerContent, original.metadata.content);
        assert.deepEqual(incoming(project, node), []);
        assert.ok(!project.connections.some((edge) => edge.fromNodeId === node.id));
        assert.ok(!node.metadata.composerContent.includes("@[node:")); // 实际图片未生成，不创建虚假的引用。
    }
    assert.equal(project.nodes.filter((node) => node.type === "video").length, 0);
    const instructions = nodeNamed(project, "E01-01 · 视频操作说明").metadata.content;
    assert.ok(instructions.includes("正文最前面按镜号依次插入 @ 图片引用"));
    for (const index of [1, 2]) assert.ok(instructions.includes(`Picture ${index} / 图片${index} ← E01-01 · 关键帧 ${index}`));
    assert.ok(instructions.includes("只连接图片不会提交参考图"));
    const h3 = nodeNamed(project, "E01-01 · H3 视频");
    const seedanceText = nodeNamed(project, "E01-01 · 豆包 Seedance 提示词");
    assert.ok(seedanceText.position.x > h3.position.x + h3.width + 96 + 420);
    validate(context, zip);
});

test("正式画幅传递到关键帧与两类视频，素材设定及宫格说明页维持各自画幅", (t) => {
    const context = fixture(t);
    context.inputs.storyboard.aspectRatio = "9:16";
    const folder = writeHandoff(resolve(context.root, "previz"), handoff(context.segment));
    const exported = context.exportZip(folder);
    for (const title of ["关键帧 1", "关键帧 2", "H3 视频", "豆包 Seedance 视频"]) {
        assert.equal(nodeNamed(exported.project, `E01-01 · ${title}`).metadata.size, "9:16");
    }
    assert.equal(nodeNamed(exported.project, "E01-01 · 预演宫格生图").metadata.size, "16:9");
    validate(context, exported.zip);
    const zip = rewriteZip(context, exported, (project) => { nodeNamed(project, "E01-01 · 关键帧 1").metadata.size = "16:9"; });
    assert.notEqual(context.run("validate", "--zip", zip).status, 0);
    assert.equal(boardAspect({ _meta: { orientation: "portrait" } }), "9:16");
    assert.equal(boardAspect({ episodes: [{ segments: [{ cuts: [{ frame: "中景 9:16" }] }] }] }), "9:16");
    assert.equal(boardAspect({ aspectRatio: "16:9", _meta: { orientation: "portrait" } }), "16:9");
    assert.throws(() => boardAspect({ aspectRatio: "1:1" }), /aspectRatio/);
});

test("无编号角色卡通过大纲姓名或别名绑定，顺序变化不影响角色连线", (t) => {
    const context = fixture(t);
    for (const character of context.inputs.cast.characters) delete character.id;
    context.inputs.cast.characters[1].aliases = ["修伞师傅"];
    context.inputs.cast.characters.reverse();
    context.inputs.outline = { characters: [{ id: "C01", name: "顾客" }, { id: "C02", name: "修伞师傅" }] };
    const { project, zip, entries } = context.exportZip();
    const references = incoming(project, nodeNamed(project, "E01-01 · 关键帧 2"));
    assert.ok(references.some((node) => node.title === "角色锚点 · 师傅 · 正面全身"));
    assert.ok(!references.some((node) => node.title.includes("顾客")));
    assert.ok(entries.has("source/outline.json"));
    validate(context, zip);
    const noOutline = context.run("export", ...["storyboard", "script", "art", "cast"].flatMap((name) => [`--${name}`, resolve(context.root, `${name}.json`)]), "--out", resolve(context.root, "missing.zip"));
    assert.notEqual(noOutline.status, 0);
    assert.match(noOutline.stderr, /outline|角色/);
    assert.throws(() => characterBindings({ characters: [{ name: "甲" }, { name: "甲" }] }, { characters: [{ id: "C01", name: "甲" }] }), /唯一/);
    assert.throws(() => characterBindings({ characters: [{ id: "C02", name: "甲" }] }, { characters: [{ id: "C01", name: "甲" }] }), /冲突/);
});

test("最新动作、摄影和声音字段进入视频，完整复核备注不作为生成指令", (t) => {
    const context = fixture(t);
    context.inputs.art.palette = { sheet: "Warm material palette." };
    delete context.inputs.art.props;
    const cut = context.segment.cuts[1];
    Object.assign(cut, { size: "extreme-close", camera: "Arc Shot", shot: "师傅松开已获台面支撑的伞柄。", sfx: "伞柄轻触台面。", lighting: "台灯暖光。" });
    context.segment.soundscape = "雨声持续，伞柄落稳后才响。";
    context.segment.h3Prompt = "Latest accepted H3 action and sound.";
    const { project, zip } = context.exportZip(undefined, true);
    const prompt = nodeNamed(project, "E01-01 · 豆包 Seedance 视频").metadata.composerContent;
    for (const value of [cut.shot, cut.sfx, cut.lighting, context.segment.soundscape, "景别：大特写", "运镜：环绕"]) assert.ok(prompt.includes(value));
    assert.ok(!prompt.includes(cut.note));
    assert.ok(!prompt.includes("动作承接："));
    assert.equal(nodeNamed(project, "E01-01 · H3 视频").metadata.composerContent, context.segment.h3Prompt);
    assert.ok(incoming(project, nodeNamed(project, "E01-01 · 关键帧 2")).some((node) => node.title === "角色视图 · 师傅 · 正面头像"));
    assert.equal(CAMERA.size, 20);
    validate(context, zip);
});

test("视频组合节点随包校验自定义约束和剧本逐句台词", (t) => {
    const context = fixture(t);
    context.inputs.script.episodes[0].scenes[0].flow.push({ speaker: "C02", line: "你的伞修好了。" });
    context.segment.cuts[1].beats = [1, 1];
    const constraints = ["保持伞架排列不变。"];
    const { project, zip, entries } = context.exportZip(undefined, false, constraints);
    const prompt = nodeNamed(project, "E01-01 · 豆包 Seedance 视频").metadata.composerContent;
    assert.ok(prompt.includes("{你的伞修好了。}"));
    assert.ok(prompt.includes(constraints[0]));
    const input = JSON.parse(entries.get("source/canvas-input.json"));
    assert.deepEqual(input.constraints, constraints);
    assert.ok(entries.has(input.script));
    assert.equal(Object.keys(input).length, 5);
    validate(context, zip);
});

test("场景、色卡、角色和道具连入组合节点并逐项写入有效 @ 引用", (t) => {
    const context = fixture(t);
    context.inputs.art.palette = { sheet: "A palette reference sheet." };
    context.inputs.art.props.push({ id: "P01", name: "取伞票", image: { prompt: "An umbrella claim ticket." } });
    context.inputs.script.episodes[0].scenes[0].props.push("P01");
    const { project, zip } = context.exportZip();
    for (const index of [1, 2]) {
        const frame = nodeNamed(project, `E01-01 · 关键帧 ${index}`);
        const references = incoming(project, frame);
        const tokens = [...frame.metadata.composerContent.matchAll(/@\[node:([^\]]+)\]/g)].map((match) => match[1]);
        assert.deepEqual(new Set(tokens), new Set(references.map((node) => node.id)));
        assert.equal(tokens.length, references.length);
        for (const node of references) {
            assert.equal(node.type, "image");
            assert.ok(frame.metadata.composerContent.includes(`${node.title}：@[node:${node.id}]`));
        }
        for (const prefix of ["场景 ·", "色卡 ·", "道具 ·", "角色锚点 ·"]) assert.ok(references.some((node) => node.title.startsWith(prefix)));
        assert.equal(references.some((node) => node.title.includes("顾客")), index === 1);
        assert.ok(!project.connections.some((edge) => edge.fromNodeId === frame.id));
    }
    validate(context, zip);
});

test("没有参考图片的关键帧组合节点仍可按纯文字生成", (t) => {
    const context = fixture(t);
    context.inputs.art.scenes = [];
    context.inputs.cast.characters = [];
    for (const cut of context.segment.cuts) cut.characters = [];
    const { project, zip } = context.exportZip();
    const frame = nodeNamed(project, "E01-01 · 关键帧 1");
    assert.deepEqual(incoming(project, frame), []);
    assert.equal(frame.metadata.composerContent, keyframePrompt(context.segment, context.segment.cuts[0], 0));
    validate(context, zip);
});

test("默认角色多视角仍沿主参考生成，并在对应关键帧中显式引用", (t) => {
    const context = fixture(t);
    const { project, zip } = context.exportZip(undefined, true);
    const views = project.nodes.filter((node) => node.title.startsWith("角色视图 ·"));
    assert.equal(views.length, 16);
    const frame = nodeNamed(project, "E01-01 · 关键帧 2");
    const portrait = nodeNamed(project, "角色视图 · 师傅 · 正面头像");
    const master = nodeNamed(project, "角色锚点 · 师傅 · 正面全身");
    assert.ok(incoming(project, frame).some((node) => node.id === portrait.id));
    assert.ok(frame.metadata.composerContent.includes(`@[node:${portrait.id}]`));
    assert.deepEqual(incoming(project, portrait).map((node) => node.id), [master.id]);
    validate(context, zip);
});

test("递归读取场景光照与人物裁图，缺光照时回退场景设定图", (t) => {
    const context = fixture(t);
    const images = resolve(context.root, "images");
    const characterImages = resolve(context.root, "character-images");
    mkdirSync(resolve(images, "lighting"), { recursive: true });
    mkdirSync(characterImages, { recursive: true });
    writeFileSync(resolve(images, "修伞铺-sheet.png"), png);
    writeFileSync(resolve(images, "顾客-sheet.png"), png);
    writeFileSync(resolve(images, "lighting", "S01-01-白昼.png"), png);
    writeFileSync(resolve(characterImages, "顾客-正面全身.png"), png);
    writeFileSync(resolve(characterImages, "顾客-正面头像.png"), png);
    context.inputs.art.scenes[0].lighting = [{ state: "白昼" }, { state: "夜晚" }];
    context.inputs.script.episodes[0].scenes[0].lighting = "白昼";
    const { project, zip, entries } = context.exportZip(undefined, true, [], { images, characterImages });
    const daylight = nodeNamed(project, "场景 · 修伞铺 · 白昼");
    const night = nodeNamed(project, "场景 · 修伞铺 · 夜晚");
    const sheet = nodeNamed(project, "场景 · 修伞铺 · 多视角设定图");
    assert.equal(daylight.metadata.status, "success");
    assert.ok(daylight.metadata.storageKey);
    assert.equal(night.metadata.status, "idle");
    assert.equal(sheet.metadata.status, "success");
    const frame = nodeNamed(project, "E01-01 · 关键帧 1");
    assert.ok(incoming(project, frame).some((node) => node.id === daylight.id));
    assert.ok(!incoming(project, frame).some((node) => node.id === night.id));
    const master = nodeNamed(project, "角色锚点 · 顾客 · 正面全身");
    const portrait = nodeNamed(project, "角色视图 · 顾客 · 正面头像");
    const characterSheet = nodeNamed(project, "角色设定图 · 顾客");
    assert.equal(master.metadata.status, "success");
    assert.equal(portrait.metadata.status, "success");
    assert.equal(characterSheet.metadata.status, "success");
    assert.deepEqual(incoming(project, master).map((node) => node.id), [characterSheet.id]);
    const files = JSON.parse(entries.get("projects.json").toString("utf8")).projects[0].files;
    for (const node of [daylight, sheet, master, portrait, characterSheet]) assert.ok(files.some((file) => file.storageKey === node.metadata.storageKey), node.title);
    validate(context, zip);
    context.inputs.script.episodes[0].scenes[0].lighting = "夜晚";
    const fallback = context.exportZip(undefined, false, [], { images, characterImages });
    const fallbackFrame = nodeNamed(fallback.project, "E01-01 · 关键帧 1");
    const fallbackSheet = nodeNamed(fallback.project, "场景 · 修伞铺 · 多视角设定图");
    assert.ok(incoming(fallback.project, fallbackFrame).some((node) => node.id === fallbackSheet.id));
    validate(context, fallback.zip);
});

test("仅导入人物设定图时跳过主参考和独立视图", (t) => {
    const context = fixture(t);
    const images = resolve(context.root, "images");
    mkdirSync(images, { recursive: true });
    writeFileSync(resolve(images, "顾客-sheet.png"), png);
    const { project, zip, entries } = context.exportZip(undefined, true, [], { images, characterSheetsOnly: true });
    assert.equal(project.nodes.filter((node) => node.title.startsWith("角色锚点 ·")).length, 0);
    assert.equal(project.nodes.filter((node) => node.title.startsWith("角色视图 ·")).length, 0);
    const sheet = nodeNamed(project, "角色设定图 · 顾客");
    assert.equal(sheet.metadata.status, "success");
    const frame = nodeNamed(project, "E01-01 · 关键帧 1");
    assert.ok(incoming(project, frame).some((node) => node.id === sheet.id));
    const placeholder = nodeNamed(project, "角色设定图 · 师傅");
    assert.equal(placeholder.metadata.status, "idle");
    const files = JSON.parse(entries.get("projects.json").toString("utf8")).projects[0].files;
    assert.equal(files.length, 1);
    validate(context, zip);
});

test("普通纯文字宫格原文逐字保留，不混入资产参考，支持部分段交付", (t) => {
    const context = fixture(t);
    const second = structuredClone(context.segment);
    second.id = "E01-02";
    context.inputs.storyboard.episodes[0].segments.push(second);
    const folder = writeHandoff(resolve(context.root, "previz", "_grid", "E01-01"), handoff(context.segment));
    const { project, zip, entries } = context.exportZip(resolve(context.root, "previz"));
    const original = readFileSync(resolve(folder, "grid-prompt.txt"), "utf8");
    const grid = nodeNamed(project, "E01-01 · 预演宫格生图");
    assert.equal(grid.metadata.prompt, original);
    assert.equal(grid.metadata.composerContent, original);
    assert.equal(nodeNamed(project, "E01-01 · 预演宫格提示词").metadata.content, original);
    assert.deepEqual(incoming(project, grid).map((node) => node.type), ["text"]);
    assert.ok(nodeNamed(project, "E01-02 · 站位与拍摄说明").metadata.content.includes(second.blocking));
    assert.ok(!project.nodes.some((node) => node.title === "E01-02 · 预演宫格生图"));
    assert.equal(entries.get("source/previz/E01-01/grid-prompt.txt").toString(), original);
    validate(context, zip);
});

test("站位交付补充分镜空缺，排除撤下的版本，并优先于普通宫格", (t) => {
    const context = fixture(t);
    const data = handoff(context.segment, true);
    const folder = resolve(context.root, "previz");
    writeHandoff(resolve(folder, "_grid", "E01-01"), handoff(context.segment));
    writeHandoff(resolve(folder, "_blocking-grid", "E01-01"), data, "Blocking grid original.");
    writeHandoff(resolve(folder, "old.stale", "E01-01"), data);
    const todo = writeHandoff(resolve(folder, "pending", "E01-01"), data);
    writeFileSync(resolve(todo, "grid.todo"), "待补充");
    context.segment.blocking = "";
    for (const cut of context.segment.cuts) for (const key of ["cameraPosition", "composition", "eyeline", "note", "shot"]) delete cut[key];
    const { project, zip } = context.exportZip(folder);
    const prompt = nodeNamed(project, "E01-01 · 关键帧 1").metadata.composerContent;
    assert.equal(prompt.split("\n\n【参考图片对应】")[0], context.segment.cuts[0].frame);
    const seedance = nodeNamed(project, "E01-01 · 豆包 Seedance 视频").metadata.composerContent;
    assert.ok(seedance.includes(data.planning.shots[0].action));
    assert.ok(!seedance.includes(data.planning.shots[0].continuity));
    assert.ok(nodeNamed(project, "E01-01 · 站位与拍摄说明").metadata.content.includes(data.planning.shots[0].continuity));
    assert.equal(nodeNamed(project, "E01-01 · 预演宫格生图").metadata.prompt, "Blocking grid original.");
    validate(context, zip);
    writeHandoff(resolve(folder, "another", "E01-01"), data);
    assert.throws(() => loadPreviz(folder, context.inputs.storyboard), /多份同类/);
});

test("镜号、原文、时长或站位版本不匹配时拒绝导入", (t) => {
    const context = fixture(t);
    const folder = resolve(context.root, "previz");
    for (const mutate of [
        (data) => { data.panels[0].shot = "E01-01-f2"; },
        (data) => { data.panels[0].frame = "旧版画面"; },
        (data) => { data.panels[0].time[1] = "2"; },
        (data) => { data.planning.opening = "师傅在台外"; },
    ]) {
        const data = handoff(context.segment, true);
        mutate(data);
        writeHandoff(folder, data);
        assert.throws(() => loadPreviz(folder, context.inputs.storyboard), /不一致|冲突/);
    }
});

test("表现增强或动作修订后，旧站位宫格不能覆盖最终正文", (t) => {
    const context = fixture(t);
    const folder = writeHandoff(resolve(context.root, "previz"), handoff(context.segment, true));
    for (const field of ["shot", "cameraPosition", "composition", "eyeline", "note"]) {
        const before = context.segment.cuts[0][field];
        context.segment.cuts[0][field] = `${before} 已修订。`;
        assert.throws(() => loadPreviz(folder, context.inputs.storyboard), /冲突/);
        context.segment.cuts[0][field] = before;
    }
});

test("明确指定的预演参考图随包携带，只连接对应宫格并标明镜号", (t) => {
    const context = fixture(t);
    const data = handoff(context.segment);
    data.panels[1].reference = "reference.png";
    const folder = writeHandoff(resolve(context.root, "previz"), data);
    assert.throws(() => loadPreviz(folder, context.inputs.storyboard), /参考图片不存在/);
    writeFileSync(resolve(folder, "reference.png"), png);
    const { project, manifest, zip, entries } = context.exportZip(folder);
    const grid = nodeNamed(project, "E01-01 · 预演宫格生图");
    const reference = nodeNamed(project, "E01-01-f2 · 预演参考图");
    assert.deepEqual(incoming(project, grid).map((node) => node.type), ["text", "image"]);
    assert.ok(grid.metadata.composerContent.includes(`E01-01-f2：@[node:${reference.id}]`));
    const file = manifest.projects[0].files.find((file) => file.storageKey === reference.metadata.storageKey);
    assert.deepEqual(entries.get(file.path), png);
    rmSync(folder, { recursive: true });
    validate(context, zip); // 导入机器不需要访问原始本机图片路径。
});

test("验证能发现空间内容丢失、配置旧词、错误参考以及整张宫格混入视频", (t) => {
    const context = fixture(t);
    const folder = writeHandoff(resolve(context.root, "previz"), handoff(context.segment));
    const exported = context.exportZip(folder);
    for (const mutate of [
        (project) => { nodeNamed(project, "E01-01 · 关键帧 1").metadata.composerContent = context.segment.cuts[0].frame; },
        (project) => { nodeNamed(project, "E01-01 · 站位与拍摄说明").metadata.content = ""; },
        (project) => { nodeNamed(project, "E01-01 · 预演宫格生图").metadata.composerContent = "旧词"; },
        (project) => { project.connections.push({ id: "wrong-image", fromNodeId: nodeNamed(project, "E01-01 · 关键帧 1").id, toNodeId: nodeNamed(project, "E01-01 · 预演宫格生图").id }); },
        (project) => { project.connections.push({ id: "wrong-grid", fromNodeId: nodeNamed(project, "E01-01 · 预演宫格生图").id, toNodeId: nodeNamed(project, "E01-01 · H3 视频").id }); },
    ]) {
        const zip = rewriteZip(context, exported, mutate);
        assert.notEqual(context.run("validate", "--zip", zip).status, 0);
    }
});

test("验证拒绝丢失的 @ 引用、断开的参考、错误生图配置和组合节点直连视频", (t) => {
    const context = fixture(t);
    const exported = context.exportZip();
    for (const mutate of [
        (project) => { const node = nodeNamed(project, "E01-01 · 关键帧 1"); node.type = "image"; },
        (project) => { const metadata = nodeNamed(project, "E01-01 · 关键帧 1").metadata; metadata.composerContent = metadata.composerContent.replace(/@\[node:[^\]]+\]/, "图片1"); },
        (project) => { const node = nodeNamed(project, "E01-01 · 关键帧 1"); project.connections = project.connections.filter((edge) => edge.toNodeId !== node.id); },
        (project) => { nodeNamed(project, "E01-01 · 关键帧 1").metadata.generationMode = "video"; },
        (project) => { nodeNamed(project, "E01-01 · 关键帧操作说明").metadata.content = "图片顺序缺失"; },
        (project) => { project.connections.push({ id: "config-to-video", fromNodeId: nodeNamed(project, "E01-01 · 关键帧 1").id, toNodeId: nodeNamed(project, "E01-01 · H3 视频").id }); },
        (project) => { project.connections.push({ id: "asset-to-video", fromNodeId: nodeNamed(project, "角色锚点 · 顾客 · 正面全身").id, toNodeId: nodeNamed(project, "E01-01 · 豆包 Seedance 视频").id }); },
    ]) {
        const zip = rewriteZip(context, exported, mutate);
        assert.notEqual(context.run("validate", "--zip", zip).status, 0);
    }
});

test("验证拒绝错误视频类型、模式、参数、旧提示词以及丢失的操作说明", (t) => {
    const context = fixture(t);
    const exported = context.exportZip();
    for (const mutate of [
        (project) => { nodeNamed(project, "E01-01 · H3 视频").type = "video"; },
        (project) => { nodeNamed(project, "E01-01 · H3 视频").metadata.generationMode = "image"; },
        (project) => { nodeNamed(project, "E01-01 · H3 视频").metadata.seconds = "9"; },
        (project) => { nodeNamed(project, "E01-01 · H3 视频").metadata.size = "9:16"; },
        (project) => { nodeNamed(project, "E01-01 · H3 视频").metadata.videoMode = "frames"; },
        (project) => { nodeNamed(project, "E01-01 · H3 视频").metadata.composerContent = "Old H3 prompt."; },
        (project) => { nodeNamed(project, "E01-01 · 豆包 Seedance 提示词").metadata.content = "旧版豆包提示词"; },
        (project) => { const node = nodeNamed(project, "E01-01 · 豆包 Seedance 视频"); node.metadata.composerContent += "\n过期动作。"; nodeNamed(project, "E01-01 · 豆包 Seedance 提示词").metadata.content = node.metadata.composerContent; },
        (project) => { nodeNamed(project, "E01-01 · 视频操作说明").metadata.content = "只连接图片即可"; },
        (project) => { project.connections.push({ id: "video-config-output", fromNodeId: nodeNamed(project, "E01-01 · H3 视频").id, toNodeId: nodeNamed(project, "E01-01 · 豆包 Seedance 视频").id }); },
    ]) {
        const zip = rewriteZip(context, exported, mutate);
        assert.notEqual(context.run("validate", "--zip", zip).status, 0);
    }
});

test("既有图片关键帧导出包仍按原版本校验画面和视频顺序", (t) => {
    const context = fixture(t);
    const exported = context.exportZip();
    const zip = rewriteZip(context, exported, (project, entries) => {
        const input = JSON.parse(entries.get("source/canvas-input.json"));
        input.version = 1;
        entries.set("source/canvas-input.json", Buffer.from(JSON.stringify(input)));
        const frames = context.segment.cuts.map((cut, index) => {
            const node = nodeNamed(project, `E01-01 · 关键帧 ${index + 1}`);
            node.type = "image";
            node.metadata.prompt = keyframePrompt(context.segment, cut, index, undefined, 1);
            delete node.metadata.composerContent;
            return node;
        });
        for (const label of ["H3", "豆包 Seedance"]) {
            const video = nodeNamed(project, `E01-01 · ${label} 视频`);
            video.type = "video";
            video.metadata.prompt = video.metadata.composerContent;
            delete video.metadata.composerContent;
            for (const frame of frames) project.connections.push({ id: `${label}-${frame.id}`, fromNodeId: frame.id, toNodeId: video.id });
        }
    });
    validate(context, zip);
});

test("既有关键帧组合节点与普通视频节点包仍通过原版本验证", (t) => {
    const context = fixture(t);
    const exported = context.exportZip();
    const zip = rewriteZip(context, exported, (project, entries) => {
        const input = JSON.parse(entries.get("source/canvas-input.json"));
        input.version = 2;
        entries.set("source/canvas-input.json", Buffer.from(JSON.stringify(input)));
        context.segment.cuts.forEach((cut, index) => {
            const node = nodeNamed(project, `E01-01 · 关键帧 ${index + 1}`);
            node.metadata.composerContent = node.metadata.composerContent.replace(cut.frame, keyframePrompt(context.segment, cut, index, undefined, 2));
        });
        for (const label of ["H3", "豆包 Seedance"]) {
            const video = nodeNamed(project, `E01-01 · ${label} 视频`);
            video.type = "video";
            video.metadata.prompt = video.metadata.composerContent;
            delete video.metadata.composerContent;
        }
        project.nodes = project.nodes.filter((node) => node.title !== "E01-01 · 视频操作说明");
    });
    validate(context, zip);
});

test("第三版包继续核对旧版空间追加和 Seedance 承接行", (t) => {
    const context = fixture(t);
    const exported = context.exportZip();
    const zip = rewriteZip(context, exported, (project, entries) => {
        const input = JSON.parse(entries.get("source/canvas-input.json"));
        input.version = 3;
        entries.set("source/canvas-input.json", Buffer.from(JSON.stringify(input)));
        context.segment.cuts.forEach((cut, index) => {
            const frame = nodeNamed(project, `E01-01 · 关键帧 ${index + 1}`);
            frame.metadata.composerContent = frame.metadata.composerContent.replace(cut.frame, keyframePrompt(context.segment, cut, index, undefined, 3));
        });
        for (const title of ["豆包 Seedance 视频", "豆包 Seedance 提示词"]) {
            const metadata = nodeNamed(project, `E01-01 · ${title}`).metadata;
            const field = title.endsWith("视频") ? "composerContent" : "content";
            for (let index = 0; index < context.segment.cuts.length; index += 1) {
                const cut = context.segment.cuts[index];
                const line = `画面：${cut.shot}（构图参考 @图片${index + 1}）`;
                metadata[field] = metadata[field].replace(line, `${line}\n动作承接：${cut.note}`);
            }
        }
    });
    validate(context, zip);
});
