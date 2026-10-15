#!/usr/bin/env node
import { basename, extname, resolve } from "node:path";
import { readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
import { loadPreviz, keyframePrompt, spatialSummary, spatialCut, storyboardSegments, validateHandoff, gridComposer } from "./previz-handoff.mjs";

const SHOT_SIZES = { wide: "全景", medium: "中景", close: "特写", extreme_close: "大特写" };
const CAMERA = { "Static Shot": "固定镜头", "Tracking Shot": "跟拍", "Push In": "缓慢推镜", "Pull Out": "缓慢拉镜", "Pan Left": "左摇镜头", "Pan Right": "右摇镜头", "Tilt Up": "上摇镜头", "Tilt Down": "下摇镜头", "Handheld": "手持跟拍" };
const STABILITY = { stable: "稳定", "slight-shake": "微晃", handheld: "手持轻晃" };
const IMAGE_EXTENSIONS = new Set([".png", ".jpg", ".jpeg", ".webp"]);

function main() {
    const [command = "export", ...tail] = process.argv.slice(2);
    const args = parseArgs(tail);
    if (command === "help" || args.help) return printHelp();
    if (command === "export") return exportCanvas(args);
    if (command === "validate") return validateCanvas(args);
    fail(`未知命令：${command}`);
}

function parseArgs(tokens) {
    const values = {};
    for (let index = 0; index < tokens.length; index += 1) {
        const token = tokens[index];
        if (!token.startsWith("--")) fail(`参数必须以 -- 开头：${token}`);
        const key = token.slice(2);
        const next = tokens[index + 1];
        if (!next || next.startsWith("--")) values[key] = true;
        else {
            values[key] = next;
            index += 1;
        }
    }
    return values;
}

function exportCanvas(args) {
    const input = {
        storyboard: requiredPath(args, "storyboard"),
        script: requiredPath(args, "script"),
        art: requiredPath(args, "art"),
        cast: requiredPath(args, "cast"),
    };
    const out = resolve(required(args, "out"));
    const storyboard = readJson(input.storyboard);
    const script = readJson(input.script);
    const art = readJson(input.art);
    const cast = readJson(input.cast);
    const imageDir = args.images ? resolve(args.images) : null;
    const title = String(args.title || `${titleFromFile(input.storyboard)} · 分镜投产画布`);
    const projectId = safeId(args["project-id"] || `${titleFromFile(input.storyboard)}-storyboard`);
    const constraints = args.constraints ? readFileSync(resolve(args.constraints), "utf8").split(/\r?\n/).map((line) => line.trim()).filter(Boolean) : [];
    const previz = args.previz ? loadPreviz(requiredPath(args, "previz"), storyboard) : new Map();
    const packageData = buildCanvas({ storyboard, script, art, cast, sourcePaths: input, imageDir, title, projectId, constraints, includeCharacterViews: !args["no-character-views"], previz });
    writeFileSync(out, writeStoredZip(packageData.entries));
    console.log(`已导出：${out}`);
    console.log(`项目：${title}；关键帧组合节点 ${packageData.summary.keyframes} 个；H3 视频组合节点 ${packageData.summary.segments} 个；豆包 Seedance 视频组合节点 ${packageData.summary.segments} 个；嵌入参考图 ${packageData.summary.embeddedImages} 张。`);
    console.log("选定关键帧结果后，连接到视频组合节点并按镜号依次插入 @ 引用；修改参考图后在组合节点再次开始生成。");
    console.log(`站位与拍摄说明 ${packageData.summary.segments} 段；预演宫格 ${previz.size} 段。`);
    if (args.previz && previz.size < packageData.summary.segments) console.log(`未提供预演宫格的段落使用 storyboard 中已有的空间与拍摄信息。`);
}

function buildCanvas({ storyboard, script, art, cast, sourcePaths, imageDir, title, projectId, constraints, includeCharacterViews, previz = new Map() }) {
    assertArray(storyboard.episodes, "storyboard.episodes");
    assertArray(script.episodes, "script.episodes");
    assertArray(art.scenes, "art.scenes");
    assertArray(art.props, "art.props");
    assertArray(cast.characters, "cast.characters");

    const now = new Date().toISOString();
    const scriptByEpisode = new Map(script.episodes.map((episode) => [episode.ep, episode]));
    const imageFiles = imageDir ? collectImageFiles(imageDir) : [];
    const nodes = [];
    const connections = [];
    const embeddedFiles = [];
    let nodeNumber = 1;
    let connectionNumber = 1;
    let assetNumber = 1;

    const addNode = (node) => {
        node.id ||= `canvas-node-${String(nodeNumber).padStart(4, "0")}`;
        nodeNumber += 1;
        nodes.push(node);
        return node;
    };
    const addConnection = (fromNodeId, toNodeId) => {
        connections.push({ id: `canvas-connection-${String(connectionNumber).padStart(4, "0")}`, fromNodeId, toNodeId });
        connectionNumber += 1;
    };
    const makeImageNode = ({ title: nodeTitle, x, y, prompt, size = "16:9", imageFile = null, width = 330, height = 240 }) => {
        const metadata = { content: "", prompt, status: imageFile ? "success" : "idle", generationMode: "image", count: 1, size };
        if (imageFile) {
            const bytes = readFileSync(imageFile.path);
            const storageKey = `image:${projectId}-asset-${String(assetNumber).padStart(3, "0")}`;
            const archivePath = `projects/${projectId}/files/asset-${String(assetNumber).padStart(3, "0")}${imageFile.ext}`;
            const dimensions = imageDimensions(bytes, imageFile.ext);
            metadata.storageKey = storageKey;
            metadata.naturalWidth = dimensions.width;
            metadata.naturalHeight = dimensions.height;
            metadata.bytes = bytes.length;
            metadata.mimeType = imageFile.mimeType;
            embeddedFiles.push({ storageKey, path: archivePath, mimeType: imageFile.mimeType, bytes: bytes.length, data: bytes });
            assetNumber += 1;
        }
        return addNode({ type: "image", title: nodeTitle, position: { x, y }, width, height, metadata });
    };

    const sceneReference = new Map();
    const propReference = new Map();
    let assetIndex = 0;
    const assetPosition = () => {
        const position = { x: (assetIndex % 6) * 380, y: Math.floor(assetIndex / 6) * 300 };
        assetIndex += 1;
        return position;
    };

    for (const scene of art.scenes) {
        const lightingNodes = new Map();
        (scene.lighting || []).forEach((lighting, index) => {
            const stem = `${slug(scene.name)}-L${index + 1}-${slug(lighting.state)}`;
            const position = assetPosition();
            const node = makeImageNode({ title: `场景 · ${scene.name} · ${lighting.state}`, x: position.x, y: position.y, prompt: lighting.prompt || scene.image?.prompt || "", imageFile: findImage(imageFiles, stem) });
            lightingNodes.set(lighting.state, node.id);
        });
        const sheetPosition = assetPosition();
        const sheet = makeImageNode({ title: `场景 · ${scene.name} · 多视角设定图`, x: sheetPosition.x, y: sheetPosition.y, prompt: scene.image?.sheet || scene.image?.prompt || "", imageFile: findImage(imageFiles, `${slug(scene.name)}-sheet`) });
        for (const lightingNodeId of lightingNodes.values()) addConnection(sheet.id, lightingNodeId);
        sceneReference.set(scene.id, { lightingNodes, sheetId: sheet.id });
    }

    for (const prop of art.props) {
        const stateNodes = [];
        (prop.states || []).forEach((state, index) => {
            const stem = `${slug(prop.name)}-S${index + 1}-${slug(state.state)}`;
            const position = assetPosition();
            const node = makeImageNode({ title: `道具 · ${prop.name} · ${state.state}`, x: position.x, y: position.y, prompt: state.prompt || prop.image?.prompt || "", imageFile: findImage(imageFiles, stem) });
            stateNodes.push(node.id);
        });
        const sheetPosition = assetPosition();
        const sheet = makeImageNode({ title: `道具 · ${prop.name} · 多视角设定图`, x: sheetPosition.x, y: sheetPosition.y, prompt: prop.image?.sheet || prop.image?.prompt || "", imageFile: findImage(imageFiles, `${slug(prop.name)}-sheet`) });
        for (const stateNodeId of stateNodes) addConnection(sheet.id, stateNodeId);
        propReference.set(prop.id, [...stateNodes, sheet.id]);
    }

    // 全局色卡（可选）：一部剧一个色调规范。色调靠参考图连线传递——
    // 色卡连到每一张关键帧，而不是把色卡文案追加进关键帧提示词。
    let paletteNodeId = null;
    if (art.palette?.sheet) {
        const position = assetPosition();
        paletteNodeId = makeImageNode({ title: "色卡 · 全局色调与材质 DNA", x: position.x, y: position.y, prompt: art.palette.sheet, imageFile: findImage(imageFiles, "palette-sheet") }).id;
    }

    const characterReference = new Map();
    const characterStartX = 3400;
    for (let index = 0; index < cast.characters.length; index += 1) {
        const character = cast.characters[index];
        const core = characterCore(character.image?.prompt || "");
        const negative = String(character.image?.negativePrompt || "").trim();
        const master = addNode({
            type: "image",
            title: `角色锚点 · ${character.name} · 正面全身`,
            position: { x: characterStartX, y: index * 580 },
            width: 360,
            height: 540,
            metadata: {
                content: "",
                prompt: withNegative(`${core} Front-facing full-length body, neutral standing pose, both shoulders and both feet fully visible, straight-on orthographic camera, plain white studio background and soft floor contact shadow.`, negative),
                status: "idle",
                generationMode: "image",
                count: 1,
                size: "2:3",
            },
        });
        const reference = { masterId: master.id, viewNodeIds: new Map() };
        characterReference.set(character.id, reference);
        if (!includeCharacterViews) continue;
        const creature = isCreature(character);
        for (const [viewIndex, view] of (creature ? creatureViews() : humanViews()).entries()) {
            const viewNode = addNode({
                type: "image",
                title: `角色视图 · ${character.name} · ${view.title}`,
                position: { x: characterStartX + 420 + (viewIndex % 4) * 400, y: index * 580 + Math.floor(viewIndex / 4) * 300 },
                width: 360,
                height: 260,
                metadata: {
                    content: "",
                    prompt: withNegative(`Use the attached ${character.name} master reference image to preserve exactly the same identity, facial features, proportions, hairstyle, costume and identifying visual anchors. ${core} ${view.direction}`, negative),
                    status: "idle",
                    generationMode: "image",
                    count: 1,
                    size: view.size,
                },
            });
            addConnection(master.id, viewNode.id);
            reference.viewNodeIds.set(view.title, viewNode.id);
        }
    }

    const narrativeStartY = Math.max(1200, Math.ceil(assetIndex / 6) * 300 + 200);
    let segmentIndex = 0;
    let keyframes = 0;
    let narrativeY = narrativeStartY;
    for (const episode of storyboard.episodes) {
        const scriptEpisode = scriptByEpisode.get(episode.ep);
        if (!scriptEpisode) fail(`分镜第 ${episode.ep} 集在剧本中不存在。`);
        for (const segment of episode.segments || []) {
            if (!segment.id || !Array.isArray(segment.cuts) || !segment.h3Prompt) fail(`${segment.id || "未命名分段"} 缺少 cuts 或 h3Prompt。`);
            const scriptScene = scriptEpisode.scenes?.[segment.sceneIndex - 1];
            if (!scriptScene) fail(`${segment.id} 的 sceneIndex 无法映射到剧本场次。`);
            const y = narrativeY;
            const handoff = previz.get(segment.id);
            narrativeY += Math.max(600, (handoff?.references.length || 0) * 280);
            segmentIndex += 1;
            addNode({ type: "text", title: `${segment.id} · 站位与拍摄说明`, position: { x: -420, y }, width: 380, height: 280, metadata: { content: spatialSummary(segment, handoff), status: "success", fontSize: 14 } });
            if (handoff) {
                const gridText = addNode({ type: "text", title: `${segment.id} · 预演宫格提示词`, position: { x: -1260, y }, width: 380, height: 280, metadata: { content: handoff.prompt, status: "success", fontSize: 14 } });
                const references = handoff.references.map((reference, index) => {
                    const node = makeImageNode({ title: `${reference.shot} · 预演参考图`, x: -1660, y: y + index * 280, prompt: "", imageFile: reference });
                    return { shot: reference.shot, id: node.id };
                });
                const prompt = gridComposer(handoff.prompt, references);
                const grid = addNode({ type: "config", title: `${segment.id} · 预演宫格生图`, position: { x: -840, y }, width: 380, height: 280, metadata: { prompt, composerContent: prompt, status: "idle", generationMode: "image", count: 1, size: "16:9" } });
                addConnection(gridText.id, grid.id);
                for (const reference of references) addConnection(reference.id, grid.id);
            }
            const h3Text = addNode({ type: "text", title: `${segment.id} · H3 提示词`, position: { x: 0, y }, width: 340, height: 240, metadata: { content: segment.h3Prompt, status: "success", fontSize: 14 } });
            segment.cuts.forEach((cut, cutIndex) => {
                const frame = addNode({
                    type: "config",
                    title: `${segment.id} · 关键帧 ${cutIndex + 1}`,
                    position: { x: 400 + cutIndex * 840, y },
                    width: 340,
                    height: 280,
                    metadata: { composerContent: "", status: "idle", generationMode: "image", count: 1, size: "16:9" },
                });
                keyframes += 1;
                const referenceIds = new Set();
                const sceneAsset = sceneReference.get(scriptScene.sceneId);
                const sceneNodeId = sceneAsset?.lightingNodes.get(scriptScene.lighting) || sceneAsset?.sheetId;
                if (sceneNodeId) referenceIds.add(sceneNodeId);
                if (paletteNodeId) referenceIds.add(paletteNodeId);
                const characterIds = new Set(Array.isArray(cut.characters) ? cut.characters : (scriptScene.characters || []));
                for (const characterId of characterIds) {
                    if (characterId === "VO") continue;
                    const reference = characterReference.get(characterId);
                    if (!reference) continue;
                    referenceIds.add(reference.masterId);
                    for (const viewNodeId of selectCharacterViewIds(reference, cut)) referenceIds.add(viewNodeId);
                }
                const propIds = new Set(Array.isArray(cut.props) ? cut.props : (scriptScene.props || []));
                for (const propId of propIds) {
                    for (const propNodeId of propReference.get(propId) || []) referenceIds.add(propNodeId);
                }
                for (const id of referenceIds) addConnection(id, frame.id);
                frame.metadata.composerContent = keyframeComposer(keyframePrompt(segment, cut, cutIndex, handoff), nodes.filter((node) => referenceIds.has(node.id)));
            });
            addNode({ type: "text", title: `${segment.id} · 关键帧操作说明`, position: { x: 400, y: y + 320 }, width: 740, height: 220, metadata: { content: keyframeInstructions(segment), status: "success", fontSize: 14 } });
            const seconds = String(Math.max(1, Math.round(segment.cuts.reduce((total, cut) => total + Number(cut.seconds || 0), 0))));
            const videoX = 400 + segment.cuts.length * 840 + 20;
            addNode({ type: "config", title: `${segment.id} · H3 视频`, position: { x: videoX, y }, width: 340, height: 280, metadata: { composerContent: segment.h3Prompt, generationMode: "video", seconds, size: "16:9", videoMode: "reference" } });
            const seedance = seedancePrompt(segment, scriptScene, constraints, handoff);
            const seedanceText = addNode({ type: "text", title: `${segment.id} · 豆包 Seedance 提示词`, position: { x: videoX + 940, y }, width: 340, height: 240, metadata: { content: seedance, status: "success", fontSize: 14 } });
            addNode({ type: "config", title: `${segment.id} · 豆包 Seedance 视频`, position: { x: videoX + 1320, y }, width: 340, height: 280, metadata: { composerContent: seedance, generationMode: "video", seconds, size: "16:9", videoMode: "reference" } });
            addNode({ type: "text", title: `${segment.id} · 视频操作说明`, position: { x: videoX, y: y + 320 }, width: 900, height: 220, metadata: { content: videoInstructions(segment), status: "success", fontSize: 14 } });
            void h3Text;
            void seedanceText;
        }
    }

    const project = {
        id: projectId,
        title,
        createdAt: now,
        updatedAt: now,
        nodes,
        connections,
        chatSessions: [],
        activeChatId: null,
        backgroundMode: "lines",
        showImageInfo: false,
        viewport: { x: 0, y: 0, k: 0.55 },
    };
    const manifest = { app: "infinite-canvas", version: 3, exportedAt: now, projects: [{ project, files: embeddedFiles.map(({ data, ...file }) => file) }] };
    const entries = [
        { name: "projects.json", data: Buffer.from(JSON.stringify(manifest, null, 2), "utf8") },
        { name: `source/${basename(sourcePaths.storyboard)}`, data: Buffer.from(JSON.stringify(storyboard, null, 2), "utf8") },
        { name: `source/${basename(sourcePaths.script)}`, data: Buffer.from(JSON.stringify(script, null, 2), "utf8") },
        { name: `source/${basename(sourcePaths.art)}`, data: Buffer.from(JSON.stringify(art, null, 2), "utf8") },
        { name: `source/${basename(sourcePaths.cast)}`, data: Buffer.from(JSON.stringify(cast, null, 2), "utf8") },
        { name: "source/canvas-input.json", data: Buffer.from(JSON.stringify({ version: 3, storyboard: `source/${basename(sourcePaths.storyboard)}`, previz: [...previz.keys()], script: `source/${basename(sourcePaths.script)}`, constraints }), "utf8") },
        ...[...previz].flatMap(([sid, handoff]) => [
            { name: `source/previz/${sid}/grid-input.json`, data: Buffer.from(JSON.stringify(handoff.data, null, 2), "utf8") },
            { name: `source/previz/${sid}/grid-prompt.txt`, data: Buffer.from(handoff.prompt, "utf8") },
            { name: `source/previz/${sid}/grid-brief.md`, data: Buffer.from(handoff.brief, "utf8") },
        ]),
        ...embeddedFiles.map((file) => ({ name: file.path, data: file.data })),
    ];
    return { entries, summary: { segments: segmentIndex, keyframes, embeddedImages: embeddedFiles.length } };
}

function keyframeComposer(prompt, references) {
    if (!references.length) return prompt;
    return `${prompt}\n\n【参考图片对应】\n${references.map((node) => `${node.title}：@[node:${node.id}]`).join("\n")}\n场景参考负责环境，色卡负责色调与材质，角色参考负责身份与服装，道具参考负责物件外观；人物站位、构图和切点状态以本镜描述为准。`;
}

function keyframeInstructions(segment) {
    return [
        "1. 在每个关键帧组合节点的「组装提示词」中添加、移除或更换参考图，并同步正文中的 @ 引用；参考图片需要先生成或上传。",
        "2. 点击组合节点的「开始生成」，结果会另建图片节点。调整参考图后继续在组合节点生成，可以保留旧结果进行比较。",
        "3. 从每镜结果中选定一张图片，按下面的顺序连接到本段 H3 与豆包 Seedance 视频节点；替换结果时先移除旧图片到视频的连线。",
        ...segment.cuts.map((_, index) => `图片${index + 1} ← ${segment.id} · 关键帧 ${index + 1} 的选定结果`),
        "4. 需要基于已有结果修改时，把该结果连接到组合节点，在正文中 @ 引用并明确修改要求；输出图片的「重新生成」会复用它上次保存的参考。",
    ].join("\n");
}

function videoInstructions(segment) {
    return [
        "1. 本段 H3 与豆包 Seedance 视频使用组合节点。分别选择对应模型或通道，保留本段时长、画幅和参考模式。",
        "2. 每镜选定一张关键帧结果图片，连接到两个视频组合节点。在「组装提示词」正文最前面按镜号依次插入 @ 图片引用，并标明下面的对应关系；只连接图片不会提交参考图。",
        ...segment.cuts.map((_, index) => `Picture ${index + 1} / 图片${index + 1} ← ${segment.id} · 关键帧 ${index + 1} 的选定结果`),
        "3. @ 引用首次出现的顺序决定提交图片的编号。替换某镜参考图时，移除旧连线，并在原来的引用位置选择新图片；新增辅助参考图放在所有关键帧引用之后，保持原有镜号对应关系。",
        "4. 确认正文引用覆盖每镜选定图片，再点击视频组合节点的「开始生成」。结果会另建视频节点；修改提示词或参考图后，继续在组合节点生成新结果。",
    ].join("\n");
}

function seedancePrompt(segment, scriptScene, constraints, handoff) {
    const lines = segment.cuts.map((_, index) => `@[图片${index + 1}] = 分镜图 #${index + 1}`);
    if (lines.length) lines.push("");
    const opening = handoff?.data.planning?.opening || segment.blocking;
    if (String(opening || "").trim()) lines.push("【人物关系与构图逻辑】", String(opening).trim(), "");
    const beats = (scriptScene.flow || []).map((item) => ({ kind: item.line ? "line" : "action", speaker: item.speaker, text: item.line }));
    segment.cuts.forEach((cut, index) => {
        const spatial = spatialCut(segment, cut, index, handoff);
        cut = spatial.view;
        const push = (label, value) => {
            const text = String(value || "").trim();
            if (text) lines.push(`${label}：${text}`);
        };
        lines.push(`【镜头${index + 1}】`);
        push("焦距", cut.lens);
        push("机位", cut.cameraPosition);
        push("构图", cut.composition);
        push("运镜", CAMERA[cut.camera] || cut.camera);
        push("景别", SHOT_SIZES[cut.size] || cut.size);
        push("画面", `${spatial.action}（构图参考 @图片${index + 1}）`);
        push("动作承接", spatial.continuity);
        push("光影", cut.lighting);
        const [from, to] = cut.beats || [];
        const spoken = Number.isInteger(from) && Number.isInteger(to) ? beats.slice(from - 1, to).filter((beat) => beat.kind === "line") : [];
        lines.push(`台词：${spoken.length ? spoken.map((beat) => `${beat.speaker === "VO" ? "以画外音说" : ""}{${beat.text}}`).join(" ") : "{}"}`);
        push("视线落点", cut.eyeline);
        push("焦点", cut.focus);
        push("稳定性", STABILITY[cut.stability] || cut.stability);
        push("音效", cut.sfx);
        lines.push("");
    });
    if (String(segment.soundscape || "").trim()) lines.push(`<${String(segment.soundscape).trim()}>`);
    if (String(segment.music || "").trim()) lines.push(`（${String(segment.music).trim()}）`);
    if (String(segment.soundscape || "").trim() || String(segment.music || "").trim()) lines.push("");
    const rules = [...constraints];
    if (!rules.includes("保持无字幕，避免生成任何文字或字幕")) rules.push("保持无字幕，避免生成任何文字或字幕");
    if (segment.cuts.some((cut) => (cut.characters || []).filter((id) => id !== "VO").length >= 2) && !rules.includes("同框角色必须保留不同面孔、服饰和体态，避免生成双胞胎角色")) rules.push("同框角色必须保留不同面孔、服饰和体态，避免生成双胞胎角色");
    lines.push("【约束】", ...rules.map((rule, index) => `${index + 1}. ${rule}`));
    return lines.join("\n");
}

function humanViews() {
    return [
        { title: "正面头像", direction: "Isolated front-facing head-and-shoulders portrait, neutral expression, plain white background.", size: "1:1" },
        { title: "侧面 90 度", direction: "Full-body exact 90-degree side view, neutral standing pose, plain white background.", size: "2:3" },
        { title: "背面全身", direction: "Full-body back view, neutral standing pose, plain white background.", size: "2:3" },
        { title: "45 度头像", direction: "Isolated 45-degree head-and-shoulders portrait, plain white background.", size: "1:1" },
        { title: "发型与头部锚点", direction: "Isolated close-up of the hairstyle, headwear and facial identity anchors, plain white background.", size: "1:1" },
        { title: "领口与胸前锚点", direction: "Isolated close-up of collar, chest garment construction and front identity anchors, plain white background.", size: "1:1" },
        { title: "袖口锚点", direction: "Isolated close-up of sleeve, cuff and hand silhouette, plain white background.", size: "1:1" },
        { title: "鞋部锚点", direction: "Isolated close-up of footwear and hem, correct floor contact, plain white background.", size: "1:1" },
    ];
}

function creatureViews() {
    return [
        { title: "正面头部锚点", direction: "Isolated front-facing head close-up, plain white background.", size: "1:1" },
        { title: "侧面 90 度", direction: "Full-body exact 90-degree side view, correct quadruped anatomy, plain white background.", size: "2:3" },
        { title: "背面全身", direction: "Full-body back view, correct quadruped anatomy, plain white background.", size: "2:3" },
        { title: "45 度头部锚点", direction: "Isolated 45-degree head close-up, plain white background.", size: "1:1" },
        { title: "鳞冠锚点", direction: "Isolated close-up of the head scales and crown, plain white background.", size: "1:1" },
        { title: "肩甲锚点", direction: "Isolated close-up of shoulder armor scales and scars, plain white background.", size: "1:1" },
        { title: "前肢与爪锚点", direction: "Isolated close-up of forelimb and claws, correct anatomy, plain white background.", size: "1:1" },
        { title: "后足锚点", direction: "Isolated close-up of hind foot and claws, correct anatomy and floor contact, plain white background.", size: "1:1" },
    ];
}

function characterCore(prompt) {
    const withoutPose = String(prompt).replace(/\s*Three-quarter view,[\s\S]*$/i, "").trim();
    // A modern phone is an independent prop reference in this pipeline, not part of the character master image.
    return withoutPose.replace(/\s*(?:His|Her|Their) single identifying anchor:[^.]*?(?:phone|smartphone|mobile|black rectangular slab)[^.]*\.\s*/gi, " ").replace(/\s{2,}/g, " ").trim();
}

function selectCharacterViewIds(reference, cut) {
    const text = [cut.frame, cut.shot, cut.cameraPosition, cut.composition, cut.eyeline, cut.focus].filter(Boolean).join(" ");
    const viewTitle =
        /鞋|足部|脚步|鞋底|鞋尖|鞋跟|下摆/.test(text) ? "鞋部锚点" :
            /袖口|手腕|手掌|手指|拇指|手部|袖子/.test(text) ? "袖口锚点" :
                /领口|衣襟|胸前|肩章|胸徽|胸牌|衣领/.test(text) ? "领口与胸前锚点" :
                    /发髻|发型|头冠|头饰|发簪|头发/.test(text) ? "发型与头部锚点" :
                        /背影|背面|后背|背部|从背后|背向|背对/.test(text) ? "背面全身" :
                            /45\s*度|斜侧|三分之二|侧前/.test(text) ? "45 度头像" :
                                /侧脸|侧面|侧身|侧拍|侧后|90\s*度/.test(text) ? "侧面 90 度" :
                                    /特写|大特写|面部|脸部|眼睛|眼神/.test(text) || ["close", "extreme_close"].includes(cut.size) ? "正面头像" :
                                        null;
    const viewNodeId = viewTitle ? reference.viewNodeIds.get(viewTitle) : null;
    return viewNodeId ? [viewNodeId] : [];
}

function withNegative(prompt, negative) {
    return negative ? `${prompt} Avoid ${negative}.` : prompt;
}

function isCreature(character) {
    const text = [character.image?.prompt, ...(character.image?.tags || [])].join(" ").toLowerCase();
    return text.includes("quadruped") || text.includes("creature") || text.includes("spirit beast");
}

function collectImageFiles(directory) {
    if (!statSync(directory).isDirectory()) fail(`图片目录不存在：${directory}`);
    return readdirSync(directory, { withFileTypes: true })
        .filter((entry) => entry.isFile() && IMAGE_EXTENSIONS.has(extname(entry.name).toLowerCase()))
        .map((entry) => {
            const ext = extname(entry.name).toLowerCase();
            return { path: resolve(directory, entry.name), stem: basename(entry.name, ext).toLowerCase(), ext, mimeType: mimeType(ext) };
        });
}

function findImage(files, stem) {
    const expected = stem.toLowerCase();
    const compact = expected.replace(/-/g, "");
    return files.find((file) => file.stem === expected || slug(file.stem).toLowerCase().replace(/-/g, "") === compact) || null;
}

function imageDimensions(bytes, extension) {
    if (extension === ".png" && bytes.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]))) return { width: bytes.readUInt32BE(16), height: bytes.readUInt32BE(20) };
    if (extension === ".webp" && bytes.toString("ascii", 0, 4) === "RIFF" && bytes.toString("ascii", 8, 12) === "WEBP") return { width: 1536, height: 1024 };
    return { width: 1536, height: 1024 };
}

function mimeType(extension) {
    return { ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp" }[extension] || "application/octet-stream";
}

function validateCanvas(args) {
    const zipPath = requiredPath(args, "zip");
    const entries = readStoredZip(readFileSync(zipPath));
    if (!entries.has("projects.json")) fail("ZIP 缺少 projects.json。");
    const manifest = JSON.parse(entries.get("projects.json").toString("utf8"));
    if (manifest.app !== "infinite-canvas" || !Array.isArray(manifest.projects) || !manifest.projects.length) fail("projects.json 不是无限画布项目包。");
    const project = manifest.projects[0].project;
    const nodes = project?.nodes || [];
    const h3 = nodes.filter((node) => ["video", "config"].includes(node.type) && node.title.endsWith(" · H3 视频"));
    const seedance = nodes.filter((node) => ["video", "config"].includes(node.type) && node.title.endsWith(" · 豆包 Seedance 视频"));
    const keyframes = nodes.filter((node) => ["image", "config"].includes(node.type) && / · 关键帧 \d+$/.test(node.title));
    if (!h3.length || h3.length !== seedance.length) fail("H3 与豆包 Seedance 视频节点数量不一致。");
    if (seedance.some((node) => { const prompt = node.metadata?.composerContent ?? node.metadata?.prompt ?? ""; return !prompt.includes("【镜头1】") || !prompt.includes("【约束】"); })) fail("存在不完整的豆包 Seedance 提示词。");
    if (keyframes.some((node) => /场景一致性锚点|光照状态：|保持已连接的写实场景/.test(node.metadata?.composerContent ?? node.metadata?.prompt ?? ""))) fail("关键帧中混入了不应追加的场景说明。");
    const connectedNodeIds = new Set(project.connections.flatMap((connection) => [connection.fromNodeId, connection.toNodeId]));
    const unlinkedReferences = nodes.filter((node) => node.type === "image" && /^(场景|道具|角色锚点|角色视图|色卡) ·/.test(node.title) && !connectedNodeIds.has(node.id));
    if (unlinkedReferences.length) fail(`存在 ${unlinkedReferences.length} 个未连线的参考图片节点：${unlinkedReferences.map((node) => node.title).join("、")}`);
    const files = manifest.projects.flatMap((item) => item.files || []);
    const missing = files.filter((file) => !entries.has(file.path));
    if (missing.length) fail(`ZIP 缺少 ${missing.length} 个嵌入图片。`);
    const input = entries.has("source/canvas-input.json") ? JSON.parse(entries.get("source/canvas-input.json").toString("utf8")) : null;
    if (input) {
        if (![1, 2, 3].includes(input.version) || !entries.has(input.storyboard) || !Array.isArray(input.previz)) fail("ZIP 的源数据索引无效。");
        if (input.version === 3 && (!entries.has(input.script) || !Array.isArray(input.constraints) || input.constraints.some((line) => typeof line !== "string"))) fail("ZIP 的剧本或视频约束索引无效。");
        const storyboard = args.storyboard ? readJson(requiredPath(args, "storyboard")) : JSON.parse(entries.get(input.storyboard).toString("utf8"));
        const script = input.version === 3 ? JSON.parse(entries.get(input.script).toString("utf8")) : null;
        validateSpatialImport(project, entries, storyboard, input.previz, files, input.version, script, input.constraints);
    } else if (args.storyboard) {
        // 旧导出包没有空间交接索引，继续按原来的 cut.frame 规则验证。
        const storyboard = readJson(requiredPath(args, "storyboard"));
        const expected = storyboard.episodes.flatMap((episode) => (episode.segments || []).flatMap((segment) => segment.cuts.map((cut, index) => ({ title: `${segment.id} · 关键帧 ${index + 1}`, prompt: cut.frame }))));
        const mismatch = expected.find((frame) => nodes.find((node) => node.title === frame.title)?.metadata?.prompt !== frame.prompt);
        if (mismatch) fail(`关键帧与 storyboard 原文不一致：${mismatch.title}`);
    }
    console.log(`通过：关键帧节点 ${keyframes.length} 个；H3 视频 ${h3.length} 条；豆包 Seedance 视频 ${seedance.length} 条；嵌入文件 ${files.length} 个。`);
}

function validateSpatialImport(project, entries, storyboard, previzIds, files, version, script, constraints) {
    const { nodes, connections } = project;
    const segments = storyboardSegments(storyboard);
    const unique = (title, type) => {
        const matches = nodes.filter((node) => node.title === title && node.type === type);
        if (matches.length !== 1) fail(`缺少或重复的画布节点：${title}`);
        return matches[0];
    };
    const readEntry = (path) => {
        if (!entries.has(path)) fail(`ZIP 缺少预演交付：${path}`);
        return entries.get(path).toString("utf8");
    };
    if (new Set(previzIds).size !== previzIds.length || previzIds.some((sid) => !segments.has(sid))) fail("预演索引段号重复或不在当前分镜中。");
    const handoffs = new Map(previzIds.map((sid) => {
        const prefix = `source/previz/${sid}/`;
        const handoff = { data: JSON.parse(readEntry(`${prefix}grid-input.json`)), prompt: readEntry(`${prefix}grid-prompt.txt`), brief: readEntry(`${prefix}grid-brief.md`) };
        validateHandoff(handoff.data, segments.get(sid));
        return [sid, handoff];
    }));
    for (const [sid, segment] of segments) {
        const handoff = handoffs.get(sid);
        if (unique(`${sid} · 站位与拍摄说明`, "text").metadata?.content !== spatialSummary(segment, handoff)) fail(`${sid} 的站位与拍摄说明丢失或与源数据不一致。`);
        const frames = segment.cuts.map((cut, index) => {
            const node = unique(`${sid} · 关键帧 ${index + 1}`, version >= 2 ? "config" : "image");
            let prompt = keyframePrompt(segment, cut, index, handoff);
            if (version >= 2) {
                const incoming = connections.filter((edge) => edge.toNodeId === node.id).map((edge) => edge.fromNodeId);
                const references = nodes.filter((item) => incoming.includes(item.id));
                if (new Set(incoming).size !== incoming.length || references.length !== incoming.length || references.some((item) => item.type !== "image")) fail(`${node.title} 的参考图连线无效。`);
                if (node.metadata?.generationMode !== "image" || node.metadata?.count !== 1 || node.metadata?.size !== "16:9") fail(`${node.title} 的生图配置不正确。`);
                if (connections.some((edge) => edge.fromNodeId === node.id)) fail(`${node.title} 是生成配置，不能直接作为图片结果连接。`);
                prompt = keyframeComposer(prompt, references);
            }
            if ((version >= 2 ? node.metadata?.composerContent : node.metadata?.prompt) !== prompt) fail(`关键帧的画面、空间、拍摄信息或参考引用与源数据不一致：${node.title}`);
            return node.id;
        });
        if (version >= 2 && unique(`${sid} · 关键帧操作说明`, "text").metadata?.content !== keyframeInstructions(segment)) fail(`${sid} 的关键帧操作说明或图片顺序不正确。`);
        if (version === 3 && unique(`${sid} · 视频操作说明`, "text").metadata?.content !== videoInstructions(segment)) fail(`${sid} 的视频操作说明或参考图编号不正确。`);
        for (const label of ["H3", "豆包 Seedance"]) {
            const video = unique(`${sid} · ${label} 视频`, version === 3 ? "config" : "video");
            const incoming = connections.filter((edge) => edge.toNodeId === video.id).map((edge) => edge.fromNodeId);
            const invalid = version >= 2 ? incoming.length !== 0 : incoming.length !== frames.length || incoming.some((id, index) => id !== frames[index]);
            if (invalid) fail(`${video.title} 的关键帧引用不正确；组合节点需要先生成图片，再连接选定结果。`);
            if (version === 3) {
                const seconds = String(Math.max(1, Math.round(segment.cuts.reduce((total, cut) => total + Number(cut.seconds || 0), 0))));
                if (video.metadata?.generationMode !== "video" || video.metadata?.seconds !== seconds || video.metadata?.size !== "16:9" || video.metadata?.videoMode !== "reference") fail(`${video.title} 的视频模式、时长或画幅不正确。`);
                const episode = storyboard.episodes.find((episode) => episode.segments?.some((item) => item.id === sid));
                const scene = script.episodes?.find((item) => item.ep === episode.ep)?.scenes?.[segment.sceneIndex - 1];
                if (!scene) fail(`${sid} 的视频提示词无法映射到归档剧本场次。`);
                const prompt = label === "H3" ? segment.h3Prompt : seedancePrompt(segment, scene, constraints, handoff);
                if (video.metadata?.composerContent !== prompt || unique(`${sid} · ${label} 提示词`, "text").metadata?.content !== prompt) fail(`${video.title} 的组合提示词或原文与源数据不一致。`);
                if (connections.some((edge) => edge.fromNodeId === video.id)) fail(`${video.title} 尚未生成结果，不应存在输出连线。`);
            }
        }
        if (!handoff) continue;
        const gridText = unique(`${sid} · 预演宫格提示词`, "text");
        const grid = unique(`${sid} · 预演宫格生图`, "config");
        if (gridText.metadata?.content !== handoff.prompt) fail(`${sid} 的预演宫格原始提示词发生变化。`);
        const references = handoff.data.panels.filter((panel) => panel.reference != null).map((panel) => {
            const node = unique(`${panel.shot} · 预演参考图`, "image");
            if (!files.some((file) => file.storageKey === node.metadata?.storageKey)) fail(`${panel.shot} 的预演参考图没有嵌入 ZIP。`);
            const outgoing = connections.filter((edge) => edge.fromNodeId === node.id);
            if (outgoing.length !== 1 || outgoing[0].toNodeId !== grid.id) fail(`${panel.shot} 的预演参考图没有仅连接到对应宫格。`);
            return { shot: panel.shot, id: node.id };
        });
        const prompt = gridComposer(handoff.prompt, references);
        if (grid.metadata?.prompt !== prompt || grid.metadata?.composerContent !== prompt || grid.metadata?.generationMode !== "image") fail(`${sid} 的预演宫格生图配置与交付不一致。`);
        const expected = [gridText.id, ...references.map((reference) => reference.id)];
        const incoming = connections.filter((edge) => edge.toNodeId === grid.id).map((edge) => edge.fromNodeId);
        if (incoming.length !== expected.length || incoming.some((id, index) => id !== expected[index])) fail(`${sid} 的预演宫格参考连线不正确，或混入了交付之外的参考图。`);
        if (connections.some((edge) => edge.fromNodeId === grid.id)) fail(`${sid} 的整张宫格不能直接作为关键帧或视频参考。`);
    }
}

function writeStoredZip(entries) {
    const date = new Date();
    const dosTime = (date.getHours() << 11) | (date.getMinutes() << 5) | Math.floor(date.getSeconds() / 2);
    const dosDate = ((date.getFullYear() - 1980) << 9) | ((date.getMonth() + 1) << 5) | date.getDate();
    const local = [];
    const central = [];
    let offset = 0;
    for (const entry of entries) {
        const name = Buffer.from(entry.name.replace(/\\/g, "/"), "utf8");
        const data = Buffer.isBuffer(entry.data) ? entry.data : Buffer.from(entry.data);
        const crc = crc32(data);
        const header = Buffer.alloc(30);
        header.writeUInt32LE(0x04034b50, 0);
        header.writeUInt16LE(20, 4);
        header.writeUInt16LE(0x0800, 6);
        header.writeUInt16LE(0, 8);
        header.writeUInt16LE(dosTime, 10);
        header.writeUInt16LE(dosDate, 12);
        header.writeUInt32LE(crc, 14);
        header.writeUInt32LE(data.length, 18);
        header.writeUInt32LE(data.length, 22);
        header.writeUInt16LE(name.length, 26);
        local.push(header, name, data);
        const record = Buffer.alloc(46);
        record.writeUInt32LE(0x02014b50, 0);
        record.writeUInt16LE(0x0314, 4);
        record.writeUInt16LE(20, 6);
        record.writeUInt16LE(0x0800, 8);
        record.writeUInt16LE(0, 10);
        record.writeUInt16LE(dosTime, 12);
        record.writeUInt16LE(dosDate, 14);
        record.writeUInt32LE(crc, 16);
        record.writeUInt32LE(data.length, 20);
        record.writeUInt32LE(data.length, 24);
        record.writeUInt16LE(name.length, 28);
        record.writeUInt16LE(0, 30);
        record.writeUInt16LE(0, 32);
        record.writeUInt16LE(0, 34);
        record.writeUInt16LE(0, 36);
        record.writeUInt32LE(0, 38);
        record.writeUInt32LE(offset, 42);
        central.push(record, name);
        offset += header.length + name.length + data.length;
    }
    const centralData = Buffer.concat(central);
    const end = Buffer.alloc(22);
    end.writeUInt32LE(0x06054b50, 0);
    end.writeUInt16LE(0, 4);
    end.writeUInt16LE(0, 6);
    end.writeUInt16LE(entries.length, 8);
    end.writeUInt16LE(entries.length, 10);
    end.writeUInt32LE(centralData.length, 12);
    end.writeUInt32LE(offset, 16);
    end.writeUInt16LE(0, 20);
    return Buffer.concat([...local, centralData, end]);
}

function readStoredZip(bytes) {
    let endOffset = -1;
    for (let index = bytes.length - 22; index >= Math.max(0, bytes.length - 65557); index -= 1) if (bytes.readUInt32LE(index) === 0x06054b50) { endOffset = index; break; }
    if (endOffset < 0) fail("不是有效的 ZIP 文件。");
    const count = bytes.readUInt16LE(endOffset + 10);
    let cursor = bytes.readUInt32LE(endOffset + 16);
    const entries = new Map();
    for (let index = 0; index < count; index += 1) {
        if (bytes.readUInt32LE(cursor) !== 0x02014b50) fail("ZIP 中央目录损坏。");
        const method = bytes.readUInt16LE(cursor + 10);
        const compressed = bytes.readUInt32LE(cursor + 20);
        const nameLength = bytes.readUInt16LE(cursor + 28);
        const extraLength = bytes.readUInt16LE(cursor + 30);
        const commentLength = bytes.readUInt16LE(cursor + 32);
        const localOffset = bytes.readUInt32LE(cursor + 42);
        const name = bytes.subarray(cursor + 46, cursor + 46 + nameLength).toString("utf8");
        if (method !== 0 || bytes.readUInt32LE(localOffset) !== 0x04034b50) fail("验证器只支持本技能生成的无压缩 ZIP。" );
        const localNameLength = bytes.readUInt16LE(localOffset + 26);
        const localExtraLength = bytes.readUInt16LE(localOffset + 28);
        const dataOffset = localOffset + 30 + localNameLength + localExtraLength;
        entries.set(name, bytes.subarray(dataOffset, dataOffset + compressed));
        cursor += 46 + nameLength + extraLength + commentLength;
    }
    return entries;
}

function crc32(bytes) {
    let value = 0xffffffff;
    for (const byte of bytes) value = CRC_TABLE[(value ^ byte) & 0xff] ^ (value >>> 8);
    return (value ^ 0xffffffff) >>> 0;
}

const CRC_TABLE = (() => {
    const table = new Uint32Array(256);
    for (let index = 0; index < 256; index += 1) {
        let value = index;
        for (let bit = 0; bit < 8; bit += 1) value = value & 1 ? 0xedb88320 ^ (value >>> 1) : value >>> 1;
        table[index] = value >>> 0;
    }
    return table;
})();

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
    try { main(); } catch (error) { fail(error.message); }
}

export { buildCanvas, writeStoredZip, readStoredZip };

function required(args, key) {
    if (!args[key] || args[key] === true) fail(`缺少 --${key} 参数。`);
    return args[key];
}

function requiredPath(args, key) {
    const path = resolve(required(args, key));
    try { statSync(path); } catch { fail(`文件不存在：${path}`); }
    return path;
}

function readJson(path) {
    try { return JSON.parse(readFileSync(path, "utf8").replace(/^\uFEFF/, "")); } catch (error) { fail(`无法读取 JSON：${path}（${error.message}）`); }
}

function titleFromFile(path) {
    return basename(path).replace(/-storyboard\.json$/i, "").replace(/\.json$/i, "");
}

function slug(value) {
    return String(value || "").normalize("NFKC").replace(/[^\p{L}\p{N}]+/gu, "-").replace(/^-+|-+$/g, "");
}

function safeId(value) {
    return slug(value).toLowerCase().slice(0, 56) || "novel-storyboard-canvas";
}

function assertArray(value, label) {
    if (!Array.isArray(value)) fail(`${label} 必须是数组。`);
}

function fail(message) {
    console.error(`错误：${message}`);
    process.exit(1);
}

function printHelp() {
    console.log(`用法：\n  node export-infinite-canvas.mjs export --storyboard <storyboard.json> --script <script.json> --art <art.json> --cast <cast.json> --out <canvas.zip> [--previz <预演交付目录>] [--images <目录>] [--title <画布标题>] [--project-id <项目标识>] [--constraints <文本文件>] [--no-character-views]\n  node export-infinite-canvas.mjs validate --zip <canvas.zip> [--storyboard <storyboard.json>]`);
}
