// 场景方向是资产视角，不按人物的画面左右猜测。各视角共同提供环境与布局参考。
export const SCENE_VIEWS = [
    { key: "front", label: "正面全景", aliases: ["front", "正面", "前面"] },
    { key: "back", label: "背面全景", aliases: ["back", "背面", "后面"] },
    { key: "left", label: "左面全景", aliases: ["left", "左面", "左侧"] },
    { key: "right", label: "右面全景", aliases: ["right", "右面", "右侧"] },
    { key: "top", label: "空间俯视图", aliases: ["top", "俯视", "俯视图"] },
];

const normalize = (value) => String(value || "").normalize("NFKC").toLowerCase().replace(/[^\p{L}\p{N}]+/gu, "");
const text = (value) => typeof value === "string" ? value.trim() : "";

function uniqueImage(files, stems, label) {
    const wanted = new Set(stems.map(normalize));
    const matches = files.filter((file) => wanted.has(normalize(file.stem)));
    if (matches.length > 1) throw new Error(`${label} 有多份匹配图片，请保留唯一版本：${matches.map((file) => file.path).join("、")}`);
    return matches[0] || null;
}

export function sceneViewTitle(scene, lighting, firstLighting, view) {
    const suffix = lighting && lighting !== firstLighting ? `${lighting} · ` : "";
    return `场景 · ${scene.name} · ${suffix}${SCENE_VIEWS.find((item) => item.key === view).label}`;
}

export function sceneViewFamilies(scene, files) {
    const first = scene.lighting?.[0];
    const defaultViews = scene.image?.views || first?.views || {};
    const families = [];
    const make = (lighting, index, prompts, allowGeneric) => {
        const views = SCENE_VIEWS.flatMap((view) => {
            const suffixes = view.aliases;
            const statePrefixes = lighting ? [
                `${scene.name}-L${index + 1}-${lighting}`,
                `${scene.id}-${String(index + 1).padStart(2, "0")}-${lighting}`,
                `${scene.id}-L${index + 1}-${lighting}`,
            ] : [];
            const genericPrefixes = [scene.name, scene.id];
            const stems = (prefixes) => prefixes.flatMap((prefix) => suffixes.map((suffix) => `${prefix}-${suffix}`));
            const specific = statePrefixes.length ? uniqueImage(files, stems(statePrefixes), `${scene.name}/${lighting}/${view.label}`) : null;
            const generic = allowGeneric ? uniqueImage(files, stems(genericPrefixes), `${scene.name}/${view.label}`) : null;
            const imageFile = specific || generic;
            const prompt = text(prompts?.[view.key]);
            if (!prompt && !imageFile) return [];
            return [{ key: view.key, title: sceneViewTitle(scene, lighting, first?.state, view.key), prompt, imageFile }];
        });
        if (views.length) families.push({ lighting: lighting || null, views });
    };
    // 通用五图只属于首个光照或无光照的默认场景，不能当成其他光照的现成图。
    make(first?.state, 0, defaultViews, true);
    (scene.lighting || []).forEach((lighting, index) => {
        if (index === 0) return;
        make(lighting.state, index, lighting.views || {}, false);
    });
    return families;
}

export function selectSceneViews(records, sceneId, lighting) {
    const own = records.filter((record) => record.sceneId === sceneId);
    const exact = own.filter((record) => record.lighting === (lighting || null));
    return (exact.length ? exact : own.filter((record) => record.lighting === null)).filter((record) => record.storageKey);
}
