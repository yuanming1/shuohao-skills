---
name: novel-previz
description: |
  预演技能：先分析 novel-storyboard 的分镜，建议白模、宫格、白模与宫格组合或不额外预演，
  逐段给出镜头范围、判断依据与能力限制。方式初筛由脚本执行，不要求 Blender 或场景配置。
  宫格分支依据分镜画面描述与可选参考图片，导出锁定镜号与实际时长的完整宫格提示词；细节问题只复核已有画面。
  白模分支通过可复用场景配置生成 greybox-harness 场景脚本，检查时间轴与引用。
  用户要求「预演、白模预演、宫格预演、关键帧复核、分析预演方式、分镜进 Blender」，
  或者分镜完成后需要判断哪些片段值得预演时使用。不默认全部白模，不自动出图或调用付费模型。
---

# novel-previz · 预演技能

**先分析需要检查的问题，再选择预演方式；不是所有分镜都需要白模。**
`{baseDir}` 是本文件所在目录。方法与限制见 [references/previs-selection.md](references/previs-selection.md)，
宫格方法见 [references/grid-preview.md](references/grid-preview.md)，不要求安装外部宫格技能。

```text
已确认的 storyboard.json
        ↓ analyze（只分析，不生成）
逐段方式 + 镜头范围 + 依据 + 限制
        ├─ 白模：场景配置 → export → Blender 静帧/视频
        ├─ 宫格：原分镜描述（图片可选）→ export-grid → 完整提示词与交接包
        ├─ 复核提示：检查已有关键帧，有问题退回分镜修正
        └─ 不额外预演：继续原有分镜流程
```

分析为确定性规则初筛，不等于完整理解剧情。首次场景配置及复杂动作仍需要人工或 Agent 处理；
重复的镜号、时间轴与已配置空间转换由脚本完成。

## 工作流

### 0. 先分析预演方式

```bash
python3 {baseDir}/scripts/storyboard_to_shots.py analyze \
  --storyboard <剧名>-storyboard.json --out <输出目录> [--ep 1] [--segment E01-01]
```

生成 `_analysis/analysis.json` 与 `_analysis/analysis.md`，每段说明：
**建议哪种方式、具体检查哪些镜头、为什么、哪些内容仍未支持。**
分析无需 `script.json`、场景配置或 Blender，不修改镜头顺序和秒数。

| 需要检查什么 | 优先方式 |
|---|---|
| 多人空间、机位、门框遮挡、过肩关系 | 白模 |
| 多镜头的主体与景别变化、反应和画面承接 | 宫格 |
| 表情、文字、道具细节、身份揭示 | 复核已有关键帧，不新增预演方式 |
| 空间与多镜头视觉衔接同时重要 | 白模 + 宫格 |
| 普通重复镜头、没有明确疑点 | 不额外预演 |

执行规则：

- 从统一入口处理预演请求时，先运行分析；不要默认遍历所有段落生成白模。
- 使用报告的 `scope` 选取范围；只对需要白模的段落进入下方流程。原有显式 `export` 命令保持兼容，不强制改动已有批处理。
- 宫格按原镜号与实际切点组织，不固定十五格、不均分时长；准备方法已内化到 `grid-preview.md`。
- 文字线索是初筛，不是语义证明。用户有明确检查目标时按选择说明复核，不能把没有命中规则解释成没有风险。
- 推荐白模不表示已经支持该动作；跟拍、环绕、交接、打斗等必须阅读报告限制，不能以降级静态替代后宣称验证完成。
- 方式仅有白模、宫格和不额外预演；已有关键帧的细节提示放在 `scope.review`，不列入 `methods`。
- 宫格可以脚本导出完整提示词，但不自动生成图片；实际出图仍需要用户明确要求和图像工具。

### 宫格分支：导出完整提示词

```bash
python3 {baseDir}/scripts/storyboard_to_shots.py export-grid \
  --storyboard <剧名>-storyboard.json --out <输出目录>
```

- 默认重新分析并只处理推荐宫格的段落；`--ep 1` 可按集筛选。明确添加 `--segment E01-02` 时覆盖方式建议，但单镜仍不制作宫格。
- **没有图片也可导出**，无需视频提示词；必需的是分镜中的 `cut.frame` 画面描述、景别和时长。已有关键帧提示词不等于已经生成的图片。
- 有图片时才添加 `--frames <目录>`；允许只提供部分镜头图片，缺少的镜头依据原描述，不列为待补。参考图命名为 `E01-02-f1.png` 等，放在图像目录根部或对应段号子目录；支持 PNG/JPG/JPEG/WebP，每镜只能匹配一个非空文件。
- 默认 `source` 在有图时沿用参考画幅；无图时不声称已知原画幅，要求各格一致。可以明确添加 `--aspect 16:9|9:16|1:1`。原镜号、切序、景别、切点状态与实际时长保持不变，不固定十五格或每格两秒。
- 完整段输出 `_grid/<段号>/grid-input.json`、`grid-prompt.txt`、`grid-brief.md`；汇总见 `_grid/index.json`。
- 缺少必要的画面描述/景别、已提供图片为空或有多个版本时输出 `grid.todo`，不交付完整提示词；退出码 2 表示待补，3 表示输入或模板错误。
- 重复导出先把所选段旧交付改名为 `.stale`；取消推荐或出现缺项时不留下可误使用的旧提示词。局部导出不修改其他段，索引仅列本次范围。
- 模板优先级：`--builder <技能目录>` → 仓库或已注册的 storyboard-builder → 本技能内化模板。显式指定的模板无效时报告错误，不静默回退。

这是**脚本读取宫格技能模板**，不是自动启动另一个 Agent。无需每次人工重算布局和时间码；
单独复制本技能也能使用内化模板。无图时直接提交完整提示词；有图片时一起提交，图片路径不会自动上传。
角色图与场景图也可在实际出图时另行附加，本命令仅自动匹配按镜号命名的关键帧；未提供图像时不宣称已验证外观。
显式指定的 `--frames` 路径不存在或不是目录时报告输入错误；没有图片请省略该参数。
本命令不拼图、不出图，也未检查像素内容；要精确保留原帧像素，应另使用拼图工具。
白模抽帧宫格属于另一条检查空间的路径，不能冒充有外观的宫格生成。

下面 1–4 步仅用于**已选择白模**的段落。

### 1. 首次:生成待填场景配置

```bash
python3 {baseDir}/scripts/storyboard_to_shots.py init-config \
  --storyboard <剧名>-storyboard.json --script <剧名>-script.json \
  [--art <剧名>-art.json] --out <输出目录>
```

产出 `scene-config.json` 骨架:所有用到的场景/人物锚点/道具以 null 占位 + `missing[]` 缺项清单。
照 [references/scene-config.md](references/scene-config.md) 填——房间、站位、朝向、姿态、挂手道具。
**同一场景只配一次**,后面的段落自动复用(geo-reuse 门会验证复用是字节级一致的)。

### 2. 每次导出

```bash
python3 {baseDir}/scripts/storyboard_to_shots.py export \
  --storyboard <剧名>-storyboard.json --script <剧名>-script.json \
  --config scene-config.json [--art ...] [--outline ...] \
  --out <输出目录> [--ep 1] [--segment E01-01] [--blockout <greybox-harness/blockout 路径>]
```

- 完整段 → `<段号>/scene.py`，提供九个模式。
- 配置缺项段 → `<段号>/scene.py.todo` + 缺项清单；人物与道具同框时，道具也必须完整配置。
- 重复导出先将所选段的旧 `scene.py` 改名为 `scene.py.stale`，保留最近一次版本，不再暴露旧的可执行入口；补齐后清除旧 `.todo`。
- 先执行对账门，再发布文件。任何门违规时，本次选中的段落都不发布 `scene.py`，其他未选中的段落不受影响。
- `_report/report.json`：18 道门、运镜降级、待补清单，以及逐段逐切的 `unverified` 未预演清单。
- 退出码：0 结构对账通过 / 1 门违规 / 2 有待补 / 3 输入错误。**退出码 0 不代表构图、动作或表演已经验证。**

### 3. 白模预演(接力 greybox-harness)

```bash
blender -b --python-exit-code 1 --python <输出目录>/E01-01/scene.py -- audit      # 送模版明度自检
blender -b --python-exit-code 1 --python <输出目录>/E01-01/scene.py -- probe      # 人体关节实测
blender -b --python-exit-code 1 --python <输出目录>/E01-01/scene.py -- project    # 构图数字
blender -b --python-exit-code 1 --python <输出目录>/E01-01/scene.py -- blockers   # 遮挡扫描
blender -b --python-exit-code 1 --python <输出目录>/E01-01/scene.py -- plan  out  # 俯视平面图
blender -b --python-exit-code 1 --python <输出目录>/E01-01/scene.py -- review out # 审片静帧 → 人 confirm
blender -b --python-exit-code 1 --python <输出目录>/E01-01/scene.py -- anim out/model # 干净白模帧序列
ffmpeg -framerate 24 -i out/model/f_%04d.png -pix_fmt yuv420p out/model.mp4
```

### 4. 手改 scene.py 之后

```bash
python3 {baseDir}/scripts/storyboard_to_shots.py validate \
  --storyboard <剧名>-storyboard.json --segment E01-01 \
  --scene-py <输出目录>/E01-01/scene.py
```

重抠 SHOTS 与分镜累加对账,点名人改造成的漂移。**优先改场景配置重新生成,手改是下策。**

## 白模固定转换规则

- 镜号 = `{段号}-f{切序}`(与分镜关键帧 `E01-01-f3.png` 命名对齐);时间轴 = 切镜秒数累加,首镜 0.0 起,相邻首尾相接
- 帧率取整**逐字复刻** rig.render_anim:`f = int(round((t-base)*24))`;frames-24 门预检每镜 ≥1 帧、漂移 ≤ 半帧
- 机位名 = `S{切序}_{景别}`;焦距从 `cut.lens` 的 `NNmm` 解析,失败用 `defaultLens` 并计 ⚠
- 主体 = `characters[0]`（多角色取锚点质心、按主角朝向定方位）;无角色有道具 → 道具;双空 → sceneAnchor
- 人物组键 = 排序后的角色 ID 拼接,空镜为 `_`;**每组独立 mannequin**,跨组同角色 tag 加 `_gN`(rig 的 hide_render 循环后到者覆盖,共享列表=黑洞)
- 运镜三档:A 直接(Push/Pull→速度制推拉,Truck→画面右向量,Pedestal→垂直) / B 近似(Zoom→推近、POV→眼点静态,`approxZoom:true` 才开且永远进降级清单) / C 静态+清单(Pan/Tilt/Arc/Tracking/Shake/Roll)
- 挂手道具运行期从 `human.hand()` 实测,失败用 fallback;fallback 兼作生成期几何

## 18 道对账门

seg-seq 段号连号 · cut-seconds 分镜时长 · seg-cap 段长上限 · frames-24 帧换算 · cam-enum 运镜/景别词表 ·
lens-parse 焦距可得 · join-scene 场次对接 · join-cast 人物道具对接 · pose-valid 姿势合法(堵 T-pose 静默) ·
seat-z 坐姿椅面 · furniture-args 家具参数 · prop-attach 道具挂接 · preset-valid 机位预设 ·
geo-reuse 场景复用 · cams-closure 机位闭合 · fig-closure 人物组闭合(堵 rig 不校验 FIG 的静默黑洞) ·
shots-roundtrip 时间轴回读(与 tools 同款正则重抠) · py-syntax 语法可解析

每道门都有击穿用例(selftest),门自身崩了也算失败,不静默。

## 自测

```bash
python3 {baseDir}/scripts/storyboard_to_shots.py selftest
node {baseDir}/scripts/selftest.mjs

# 额外执行本机 Blender；可传入可执行文件的完整路径
python3 {baseDir}/scripts/storyboard_to_shots.py selftest --blender blender
node {baseDir}/scripts/selftest.mjs --blender blender
```

覆盖:20 运镜 × 5 景别全枚举夹具、18 门逐门击穿、幂等(两跑字节一致)、geo-reuse、
validate 三种漂移抓取、init-config 骨架与拒绝覆盖、部分配置 → .todo + 退出码 2、
与 harness 的 POSES/正则同步检查、上游格式兼容夹具，以及窗棂单元素元组、人物道具同框缺项、
完整→缺项→恢复、门失败不发布、局部重导出、未预演提示、Windows 路径导出。

自有分析样例见 `examples/失物窗口-story.md` 与 `examples/失物窗口-analysis-storyboard.json`。
自测覆盖五段分析结果、组合镜头范围、已有画面复核、动作降级提示、否定线索、输入不变和命令行报告。
宫格自测覆盖完整提示词、原时间码、无图与部分有图、重复图片、旧交付撤下、模板来源、独立回退及局部导出。

默认自测仅检查分析、转换与生成文本。`--blender` 额外实际执行四段场景的 `audit` / `project`，
并渲染第一段的逐镜审片 PNG；不生成完整视频、不调用生成模型。未运行 Blender 时会明确提示跳过。

## 边界(不做的事)

- 不改写正式视频提示词；导出的宫格提示词仅用于可选评审，不替换既有投产协议。
- 不解析走位散文、不生成 WALKS(Tracking Shot 降级为静态并进清单,走位戏手填)
- 白模转换不按文字还原 `blocking`、`cameraPosition`、`composition`、`eyeline`、`focus`、`stability` 的自由文本；机位依据景别、焦距和场景配置生成。
- `frame`、`shot`、`cut.note` 不会被转换成人物动作、道具状态变化或动作承接；相关字段进入报告 `unverified`，并写入生成脚本的说明。
- 同一场景同一角色只有一套站位；多站位、交接与复杂动作仍需人工配置或修改场景脚本，不属于当前自动适配范围。
- 不出图、不渲染——渲染在 greybox-harness,出片在生成模型
