#!/usr/bin/env node
import { basename, extname, resolve } from "node:path";
import { readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";

const PHOTO_PREFIX = "Photorealistic live-action cinematic character reference, natural skin texture, true-to-life facial anatomy, realistic fabric and physically plausible lighting, no stylization.";
const PHOTO_NEGATIVE = "anime, manga, comic panel, illustration, cel shading, stylized fantasy art, 3D render, plastic skin, inconsistent identity, different hairstyle, deformed anatomy, extra digits, readable text or logos";
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
    const packageData = buildCanvas({ storyboard, script, art, cast, sourcePaths: input, imageDir, title, projectId, constraints, includeCharacterViews: !args["no-character-views"] });
    writeFileSync(out, writeStoredZip(packageData.entries));
    console.log(`已导出：${out}`);
    console.log(`项目：${title}；关键帧 ${packageData.summary.keyframes} 张；H3 视频 ${packageData.summary.segments} 条；豆包 Seedance 视频 ${packageData.summary.segments} 条；嵌入参考图 ${packageData.summary.embeddedImages} 张。`);
}

function buildCanvas({ storyboard, script, art, cast, sourcePaths, imageDir, title, projectId, constraints, includeCharacterViews }) {
    assertArray(storyboard.episodes, "storyboard.episodes");
    assertArray(script.episodes, "script.episodes");
    assertArray(art.scenes, "art.scenes");
    assertArray(art.props, "art.props");
    assertArray(cast.characters, "cast.characters");

    const now = new Date().toISOString();
    const scriptByEpisode = new Map(script.episodes.map((episode) => [episode.ep, episode]));
    const sceneNames = new Map(art.scenes.map((scene) => [scene.id, scene.name]));
    const propNames = new Map(art.props.map((prop) => [prop.id, prop.name]));
    const characterNames = new Map(cast.characters.map((character) => [character.id, character.name]));
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
            const node = makeImageNode({ title: `写实场景 · ${scene.name} · ${lighting.state}`, x: position.x, y: position.y, prompt: lighting.prompt || scene.image?.prompt || "", imageFile: findImage(imageFiles, stem) });
            lightingNodes.set(lighting.state, node.id);
        });
        const sheetPosition = assetPosition();
        const sheet = makeImageNode({ title: `写实场景 · ${scene.name} · 多视角设定图`, x: sheetPosition.x, y: sheetPosition.y, prompt: scene.image?.sheet || scene.image?.prompt || "", imageFile: findImage(imageFiles, `${slug(scene.name)}-sheet`) });
        sceneReference.set(scene.id, { lightingNodes, fallback: sheet.id });
    }

    for (const prop of art.props) {
        const stateNodes = [];
        (prop.states || []).forEach((state, index) => {
            const stem = `${slug(prop.name)}-S${index + 1}-${slug(state.state)}`;
            const position = assetPosition();
            const node = makeImageNode({ title: `写实道具 · ${prop.name} · ${state.state}`, x: position.x, y: position.y, prompt: state.prompt || prop.image?.prompt || "", imageFile: findImage(imageFiles, stem) });
            stateNodes.push(node.id);
        });
        const sheetPosition = assetPosition();
        const sheet = makeImageNode({ title: `写实道具 · ${prop.name} · 多视角设定图`, x: sheetPosition.x, y: sheetPosition.y, prompt: prop.image?.sheet || prop.image?.prompt || "", imageFile: findImage(imageFiles, `${slug(prop.name)}-sheet`) });
        propReference.set(prop.id, stateNodes[0] || sheet.id);
    }

    const characterReference = new Map();
    const characterStartX = 3400;
    for (let index = 0; index < cast.characters.length; index += 1) {
        const character = cast.characters[index];
        const core = characterCore(character.image?.prompt || "");
        const negative = [character.image?.negativePrompt, PHOTO_NEGATIVE].filter(Boolean).join(", ");
        const master = addNode({
            type: "image",
            title: `角色锚点 · ${character.name} · 正面全身`,
            position: { x: characterStartX, y: index * 580 },
            width: 360,
            height: 540,
            metadata: {
                content: "",
                prompt: `${PHOTO_PREFIX} ${core} Front-facing full-length body, neutral standing pose, both shoulders and both feet fully visible, straight-on orthographic camera, plain white studio background and soft floor contact shadow. Avoid ${negative}.`,
                status: "idle",
                generationMode: "image",
                count: 1,
                size: "2:3",
            },
        });
        characterReference.set(character.id, master.id);
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
                    prompt: `${PHOTO_PREFIX} Use the attached ${character.name} master reference image to preserve exactly the same identity, facial features, proportions, hairstyle, costume and identifying visual anchors. ${core} ${view.direction} Avoid ${negative}.`,
                    status: "idle",
                    generationMode: "image",
                    count: 1,
                    size: view.size,
                },
            });
            addConnection(master.id, viewNode.id);
        }
    }

    const narrativeStartY = Math.max(1200, Math.ceil(assetIndex / 6) * 300 + 200);
    let segmentIndex = 0;
    let keyframes = 0;
    for (const episode of storyboard.episodes) {
        const scriptEpisode = scriptByEpisode.get(episode.ep);
        if (!scriptEpisode) fail(`分镜第 ${episode.ep} 集在剧本中不存在。`);
        for (const segment of episode.segments || []) {
            if (!segment.id || !Array.isArray(segment.cuts) || !segment.h3Prompt) fail(`${segment.id || "未命名分段"} 缺少 cuts 或 h3Prompt。`);
            const scriptScene = scriptEpisode.scenes?.[segment.sceneIndex - 1];
            if (!scriptScene) fail(`${segment.id} 的 sceneIndex 无法映射到剧本场次。`);
            const y = narrativeStartY + segmentIndex * 340;
            segmentIndex += 1;
            const h3Text = addNode({ type: "text", title: `${segment.id} · H3 提示词`, position: { x: 0, y }, width: 340, height: 240, metadata: { content: segment.h3Prompt, status: "success", fontSize: 14 } });
            const keyframeNodes = [];
            segment.cuts.forEach((cut, cutIndex) => {
                const frame = addNode({
                    type: "image",
                    title: `${segment.id} · 关键帧 ${cutIndex + 1}`,
                    position: { x: 400 + cutIndex * 380, y },
                    width: 340,
                    height: 240,
                    metadata: { content: "", prompt: String(cut.frame || ""), status: "idle", generationMode: "image", count: 1, size: "16:9" },
                });
                keyframeNodes.push(frame);
                keyframes += 1;
                const sceneAsset = sceneReference.get(scriptScene.sceneId);
                const sceneNodeId = sceneAsset?.lightingNodes.get(scriptScene.lighting) || sceneAsset?.fallback;
                if (sceneNodeId) addConnection(sceneNodeId, frame.id);
                const characterIds = new Set([...(scriptScene.characters || []), ...(cut.characters || [])]);
                for (const characterId of characterIds) {
                    if (characterId !== "VO" && characterReference.has(characterId)) addConnection(characterReference.get(characterId), frame.id);
                }
                const propIds = new Set([...(scriptScene.props || []), ...(cut.props || [])]);
                for (const propId of propIds) if (propReference.has(propId)) addConnection(propReference.get(propId), frame.id);
            });
            const seconds = String(Math.max(1, Math.round(segment.cuts.reduce((total, cut) => total + Number(cut.seconds || 0), 0))));
            const videoX = 400 + segment.cuts.length * 380 + 20;
            const h3Video = addNode({ type: "video", title: `${segment.id} · H3 视频`, position: { x: videoX, y }, width: 420, height: 236, metadata: { content: "", prompt: segment.h3Prompt, status: "idle", generationMode: "video", seconds, size: "16:9", videoMode: "reference" } });
            const seedance = seedancePrompt(segment, scriptScene, constraints);
            const seedanceText = addNode({ type: "text", title: `${segment.id} · 豆包 Seedance 提示词`, position: { x: videoX + 480, y }, width: 340, height: 240, metadata: { content: seedance, status: "success", fontSize: 14 } });
            const seedanceVideo = addNode({ type: "video", title: `${segment.id} · 豆包 Seedance 视频`, position: { x: videoX + 880, y }, width: 420, height: 236, metadata: { content: "", prompt: seedance, status: "idle", generationMode: "video", seconds, size: "16:9", videoMode: "reference" } });
            for (const frame of keyframeNodes) {
                addConnection(frame.id, h3Video.id);
                addConnection(frame.id, seedanceVideo.id);
            }
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
        ...embeddedFiles.map((file) => ({ name: file.path, data: file.data })),
    ];
    return { entries, summary: { segments: segmentIndex, keyframes, embeddedImages: embeddedFiles.length } };
}

function seedancePrompt(segment, scriptScene, constraints) {
    const lines = segment.cuts.map((_, index) => `@[图片${index + 1}] = 分镜图 #${index + 1}`);
    if (lines.length) lines.push("");
    if (String(segment.blocking || "").trim()) lines.push("【人物关系与构图逻辑】", String(segment.blocking).trim(), "");
    const beats = (scriptScene.flow || []).map((item) => ({ kind: item.line ? "line" : "action", speaker: item.speaker, text: item.line }));
    segment.cuts.forEach((cut, index) => {
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
        push("画面", `${String(cut.shot || "").trim()}（构图参考 @图片${index + 1}）`);
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
    const h3 = nodes.filter((node) => node.type === "video" && node.title.endsWith(" · H3 视频"));
    const seedance = nodes.filter((node) => node.type === "video" && node.title.endsWith(" · 豆包 Seedance 视频"));
    const keyframes = nodes.filter((node) => node.type === "image" && / · 关键帧 \d+$/.test(node.title));
    if (!h3.length || h3.length !== seedance.length) fail("H3 与豆包 Seedance 视频节点数量不一致。");
    if (seedance.some((node) => !node.metadata?.prompt?.includes("【镜头1】") || !node.metadata?.prompt?.includes("【约束】"))) fail("存在不完整的豆包 Seedance 提示词。");
    if (keyframes.some((node) => /场景一致性锚点|光照状态：|保持已连接的写实场景/.test(node.metadata?.prompt || ""))) fail("关键帧中混入了不应追加的场景说明。");
    const files = manifest.projects.flatMap((item) => item.files || []);
    const missing = files.filter((file) => !entries.has(file.path));
    if (missing.length) fail(`ZIP 缺少 ${missing.length} 个嵌入图片。`);
    if (args.storyboard) {
        const storyboard = readJson(requiredPath(args, "storyboard"));
        const expected = storyboard.episodes.flatMap((episode) => (episode.segments || []).flatMap((segment) => segment.cuts.map((cut, index) => ({ title: `${segment.id} · 关键帧 ${index + 1}`, prompt: cut.frame }))));
        const mismatch = expected.find((frame) => nodes.find((node) => node.title === frame.title)?.metadata?.prompt !== frame.prompt);
        if (mismatch) fail(`关键帧与 storyboard 原文不一致：${mismatch.title}`);
    }
    console.log(`通过：关键帧 ${keyframes.length} 张；H3 视频 ${h3.length} 条；豆包 Seedance 视频 ${seedance.length} 条；嵌入文件 ${files.length} 个。`);
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

main();

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
    try { return JSON.parse(readFileSync(path, "utf8")); } catch (error) { fail(`无法读取 JSON：${path}（${error.message}）`); }
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
    console.log(`用法：\n  node export-infinite-canvas.mjs export --storyboard <storyboard.json> --script <script.json> --art <art.json> --cast <cast.json> --out <canvas.zip> [--images <目录>] [--title <画布标题>] [--project-id <项目标识>] [--constraints <文本文件>] [--no-character-views]\n  node export-infinite-canvas.mjs validate --zip <canvas.zip> [--storyboard <storyboard.json>]`);
}
