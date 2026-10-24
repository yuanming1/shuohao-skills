// 输入约定整理自分镜、剧本、大纲及角色卡的数据合同；运行时不依赖其他技能。
export const SHOT_SIZES = new Map([
    ["extreme-wide", "大远景"], ["wide", "全景"], ["medium", "中景"],
    ["close", "特写"], ["extreme-close", "大特写"], ["extreme_close", "大特写"],
]);
export const CAMERA = new Map([
    ["Static Shot", "固定"], ["Push In", "推"], ["Pull Out", "拉"],
    ["Zoom In", "变焦推"], ["Zoom Out", "变焦拉"], ["Pan Left", "左摇"],
    ["Pan Right", "右摇"], ["Truck Left", "左移"], ["Truck Right", "右移"],
    ["Tilt Up", "仰摇"], ["Tilt Down", "俯摇"], ["Pedestal Up", "升"],
    ["Pedestal Down", "降"], ["Arc Shot", "环绕"], ["Tracking Shot", "跟拍"],
    ["Shake Slightly", "轻微晃动"], ["Shake Strongly", "强烈晃动"],
    ["POV", "主观视角"], ["Roll Clockwise", "顺旋"], ["Roll Counterclockwise", "逆旋"],
]);

export function boardAspect(board) {
    if (board.aspectRatio != null) {
        if (!["16:9", "9:16"].includes(board.aspectRatio)) throw new Error("storyboard.aspectRatio 只接受 16:9 或 9:16。");
        return board.aspectRatio;
    }
    const orientation = String(board._meta?.orientation ?? "").trim().toLowerCase();
    if (["portrait", "vertical", "v", "竖", "竖屏", "9:16"].includes(orientation)) return "9:16";
    if (["landscape", "horizontal", "h", "横", "横屏", "16:9"].includes(orientation)) return "16:9";
    const frames = (board.episodes || []).flatMap((ep) => (ep.segments || []).flatMap((seg) => seg.cuts || []));
    const count = (ratio) => frames.filter((cut) => new RegExp(`(^|[\\s,])${ratio}\\s*$`).test(cut.frame || "")).length;
    return count("9:16") > count("16:9") ? "9:16" : "16:9";
}

export function characterBindings(cast, outline) {
    const bindings = new Map();
    const register = (id, character) => {
        if (bindings.has(id) && bindings.get(id) !== character) throw new Error(`角色编号重复或映射冲突：${id}`);
        bindings.set(id, character);
    };
    for (const character of cast.characters) if (character.id) register(character.id, character);
    if (outline) {
        if (!Array.isArray(outline.characters)) throw new Error("outline.characters 必须是数组。");
        const ids = new Set();
        const matched = new Set();
        for (const item of outline.characters) {
            if (!item.id || !item.name || ids.has(item.id)) throw new Error(`大纲角色编号缺失或重复：${item.id}`);
            ids.add(item.id);
            const exact = cast.characters.filter((character) => character.name === item.name);
            const matches = exact.length ? exact : cast.characters.filter((character) => character.aliases?.includes(item.name));
            if (matches.length !== 1 || matched.has(matches[0])) throw new Error(`大纲角色 ${item.id}（${item.name}）无法唯一匹配角色卡；请核对姓名或别名。`);
            matched.add(matches[0]);
            const character = matches[0];
            if (character.id && character.id !== item.id) throw new Error(`角色卡与大纲编号冲突：${item.name}`);
            register(item.id, character);
        }
    }
    return bindings;
}
