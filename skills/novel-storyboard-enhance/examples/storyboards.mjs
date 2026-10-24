/** 《雪站回灯》的程序检查材料；沿用既有分镜字段，不定义新 schema。 */
const baseNote = '起始：人物站位与手部状态保持；动作：完成既定唤灯过程；结束：记录灯纹或受光阶段；接镜：继承最近终态。';
const reason = '增强依据：按本镜观察任务细化既有反应或灯纹，保留人物、能力及结果。';
function cut(beat, frame, shot) {
  const value = { beats: [beat, beat], seconds: 4, size: 'medium', camera: 'Static Shot', characters: ['C01', 'C02'] };
  Object.assign(value, { props: ['P01'], frame, shot, note: baseNote, lens: '50mm 标准，深景深' });
  Object.assign(value, { cameraPosition: '门廊一侧，平视朝院门', composition: '中心构图', eyeline: '灯沿', focus: '锁定人物与石灯', stability: 'stable' });
  return value;
}
export function prompt(first = 'The young apprentice listens, keeping her right palm above the lamp.', second = 'The existing amber ring lights up before the lamp core glows.', third = 'A static shot shows the lit lamp and the existing stone path.') {
  return 'How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the 0.00-second mark of the target video; Picture 2 (from Shot 2) aligns with the 4.00-second mark of the target video; Picture 3 (from Shot 3) aligns with the 8.00-second mark of the target video.\n\nintegrated_multimodal_description:\n'
    + `[Shot 1] <Picture 1> Static shot. The apprentice keeps her right palm above the lamp. The older mentor (S1) says <d>[Chinese] 先稳住。</d> ${first} The young apprentice (S2) replies <d>[Chinese] 我来。</d>\n`
    + `[Shot 2] At 00:04.000, <Picture 2> Static shot. ${second}\n`
    + `[Shot 3] At 00:08.000, <Picture 3> ${third}\n\n`
    + 'overall_soundscape: Wind outside the sheltered porch; the existing lamp hums as its core lights.\n\nnon_diegetic_music: N/A';
}
export function board() {
  const cuts = [
    cut(1, '中景，岑雪在石灯左侧，右掌停在灯沿上方，罗衡在右后方。', '固定镜头，年轻学徒望着石灯，年长师父提醒，她回答。'),
    cut(2, '中景，岑雪右掌仍停在暗着的灯沿上方，左手垂下，罗衡在后方。', '固定镜头，灯沿原有环纹依次亮起，随后灯芯发光。'),
    cut(3, '中景，岑雪与罗衡仍在石灯两侧，灯芯已亮，院门方向的石路延伸出画面。', '固定镜头，石灯照亮原有石路，年长师父望向院门方向。'),
  ];
  const segment = { id: 'E01-01', sceneIndex: 1, cuts, h3Prompt: prompt(), blocking: '岑雪在门廊石灯左侧，罗衡在右后方；院门在灯前方，两人不换位。' };
  segment.soundscape = '门廊外风声；灯芯亮起后灯鸣持续。';
  return { source: '雪站回灯', episodes: [{ ep: 1, segments: [segment] }] };
}
export function enhanced() {
  const value = board();
  const segment = value.episodes[0].segments[0];
  const [first, second, third] = segment.cuts;
  first.shot = '固定镜头，年轻学徒右掌仍停在灯沿上方。听到年长师父提醒后，她看向师父，再把视线移回灯沿，稳住右手后回答。左手保持垂下。';
  first.eyeline = '师父面部，再回到灯沿';
  first.note = '起始：学徒右掌悬在灯沿上方，望着石灯；动作：听到提醒后看向师父，再回看灯沿并稳住手，回答原台词；结束：右掌保持悬停，左手垂下；接镜：灯纹尚未点亮，下一镜继续唤灯。' + reason;
  second.shot = '固定镜头，年轻学徒右掌继续停在灯沿上方。原有琥珀色环纹沿灯沿依次点亮，闭合后灯芯发光，近旁石面逐渐受光；人物与灯座位置保持。';
  second.lighting = '原有灯芯发光，使灯座附近石面出现暖色受光，门廊外天色保持。';
  second.note = '起始：右掌悬停，环纹与灯芯未亮；动作：原有环纹依次亮起后灯芯发光；结束：灯芯持续发光，近旁石面受光；接镜：保持唤灯成功与人物位置，第三镜揭示石路。' + reason;
  third.camera = 'Pull Out';
  third.shot = '镜头从石灯与两人中景缓慢后拉，露出原有通向院门的受光石路；年长师父沿路望向院门，两人留在原位置，灯芯持续发光。';
  third.note = '起始：灯芯已亮，两人仍在石灯两侧；动作：摄影机小幅后拉，揭示原有受光石路；结束：人物、石灯与通向院门的路同时可读；接镜：唤灯成功，灯光持续，不新增行走或攻击。' + reason;
  segment.h3Prompt = prompt(
    'After hearing the reminder, she looks at the mentor, returns her gaze to the lamp and steadies her raised hand. Her right palm stays above the lamp and her left hand stays lowered.',
    'Her right palm stays above the lamp. The existing amber ring lights progressively along the rim; only after it closes does the core glow, lighting the nearby stone surface. Both characters and the pedestal stay in place.',
    'The camera slowly pulls out from the medium view of the lamp and the two people, revealing the existing lit stone path toward the gate. The mentor looks along that path; neither person moves, and the lamp stays lit.',
  );
  return value;
}

/** 同一故事的另一种摄影选择：三镜固定，以关系构图、局部前景和结果全景协同。 */
export function compositionEnhanced() {
  const original = board();
  const value = enhanced();
  const segment = value.episodes[0].segments[0];
  const [first, second, third] = segment.cuts;
  Object.assign(first, {
    cameraPosition: '人物关系轴靠院门一侧，斜向石灯与两人取景，平视',
    composition: '双人中景，学徒为主、师父为辅，两张三分之二侧脸和悬掌分开，灯沿位于下部',
    focus: '提醒者与回答者的面部、学徒悬掌和灯沿均可辨',
    frame: '中景，岑雪在石灯左侧，右掌尚未稳住，罗衡仍在右后方；从关系轴靠院门一侧斜拍，两人侧脸和悬掌分开，灯纹尚暗。',
  });
  first.shot = '固定双人中景，从人物关系轴靠院门一侧斜拍，两人发声面部与悬掌均可见。年轻学徒听到年长师父提醒后，先看师父，再回看灯沿、稳住右手后回答；左手垂下，灯纹尚暗。';
  Object.assign(second, {
    cameraPosition: '同一关系轴靠院门一侧，从师父肩旁斜拍学徒与灯沿',
    composition: '师父肩部局部占右下小块前景，学徒三分之二侧脸、右掌和灯沿分开呈现，肩部不遮接点',
    focus: '学徒稳定的右掌与灯沿为主，面部注视可辨，前景肩部不抢焦点',
    frame: '中景，岑雪右掌已稳在暗着的灯沿上方，注视灯沿，左手垂下；罗衡仍在右后方，仅肩部局部进入右下前景，不遮住学徒面部、右掌和灯沿。',
  });
  second.shot = '固定中景，从年长师父肩旁观察年轻学徒，保持关系轴靠院门一侧；师父的肩部局部留在右下前景，避开学徒面部、悬掌和灯沿。学徒延续已稳定的右掌与注视；原有琥珀环纹沿边依次亮起，闭合后灯芯发光，近旁石面受光。两人原位不动。';
  Object.assign(third, {
    size: 'wide', camera: 'Static Shot', lens: '28mm 广角，较深景深',
    cameraPosition: '同一关系轴靠院门一侧的斜向全景机位，以开阔取景容纳人物、灯和原石路；实际可用空间待素材确认',
    composition: '两人和石灯位于画幅一端，原有受光石路沿对角线通向院门，不裁掉结果路径',
  });
  Object.assign(third, {
    focus: '两人原位置、已亮石灯与受光石路均可辨',
    eyeline: '师父沿已亮石路望向院门，学徒仍注视灯沿',
    frame: '全景，岑雪仍在石灯左侧悬掌，罗衡仍在右后方；灯芯已亮，原有受光石路沿画面对角线通向院门。机位保持同一关系轴侧，两人没有移位。',
    shot: '固定全景从切点呈现两人、已亮石灯及原有受光石路。年长师父沿路望向院门，年轻学徒保持原悬掌，两人不移动，灯光与灯鸣持续，不重新唤灯。',
  });
  const reasons = [
    '本次编写：以双人关系构图明确提醒与承担，作为后镜把师父退为局部前景的依据；不改变两次对白的画内发声。',
    '本次编写：前镜已确认关系，本镜由同等强调两人改为突出学徒悬掌与灯纹，师父只保留肩部局部；同侧机位和遮挡仍待真实素材验证。',
    '本次编写：前两镜分别确认决定和执行，本镜从切点直接呈现完整结果，采用固定全景而非后拉；原人物、灯与石路位置保持，取景空间待验证。',
  ];
  segment.cuts.forEach((item, index) => {
    item.note = original.episodes[0].segments[0].cuts[index].note + ' ' + item.note
      + ' 增强依据：摄影组合；' + reasons[index];
  });
  third.note = original.episodes[0].segments[0].cuts[2].note
    + ' 起始：灯芯已亮，两人原位，起幅全景包含原有受光石路；动作：师父沿路望向院门，摄影机固定；结束：人物、灯与照明结果同时可读；接镜：持续亮灯，不重复唤灯。增强依据：摄影组合；' + reasons[2];
  segment.h3Prompt = prompt(
    'In a static two-person medium frame from the gate-facing side of their interaction axis, both three-quarter faces and the raised palm remain visible. After the reminder, the apprentice looks at the mentor, returns her gaze to the lamp and steadies her right hand. Her left hand stays lowered and the ring stays dark.',
    'A static medium view from beside the mentor’s shoulder stays on the same side of the interaction axis. A small part of his shoulder occupies the lower-right foreground without obscuring the apprentice’s face, raised palm or lamp rim. She maintains her already steady palm and attention. The existing amber ring lights progressively around the rim; only after it closes does the core glow and illuminate the nearby stone. Both people stay in place.',
    'Static Shot. The shot starts wide from an oblique camera on the same side of the interaction axis, showing both people, the lit lamp and the existing illuminated stone path extending diagonally toward the gate. The mentor looks along the path while the apprentice keeps her palm in place. Neither moves; the light and hum continue.',
  );
  return value;
}
