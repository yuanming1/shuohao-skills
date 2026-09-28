---
name: novel-storyboard
version: 1.4.0
description: |
  给 AI 短剧出分镜：三层结构——段（一次视频生成，≤15 秒）→ 分镜（段内 2–5 秒的剪切，认领剧本节拍）
  → 分镜图（每切一张关键帧：主分镜图钉 0.00 秒，子分镜图钉各自切点）。
  每段自带一条 MiniMax H3 视频提示词（官方口径默认英文、逐镜换行，promptLang 可切中文）：对齐指令和
  [Shot k] 切点时刻由分镜结构推导、逐字对账，台词逐字进 <d> 块（写法规范已内化为
  references/h3-prompt.md，不依赖外部 skill）。
  产出 storyboard.json + Markdown + 单页评审报告（分镜节奏带 / 分集分镜表 / 生成批次单 /
  配音对齐单，含导出 JSON）。分镜图出图拿场景与角色设定图当参考图走 codex $imagegen（可选）。
  17 道质量门全部由脚本确定性检查（第 17 道 shot-recipe 可选：挂上 shot-recipes 卡库才查，不挂就明说跳过）；
  写提示词前必须规划逐镜起始、动作、结束与接镜状态，复用 cut.note 留存；出图后逐段复核连续性，结构校验通过不代表视觉验收通过。
  export 默认要求绑定当前输入版本的逐切审核记录；只交文字用 --draft。导出 H3 投产包（每段提示词 + 按 Picture 序的分镜图清单）。零依赖、零 API key，用当前会话额度。
  Use when asked to 分镜、出分镜、镜头表、切镜、storyboard for AI short drama。
allowed-tools:
  - Read
  - Write
  - Bash
  - Task
  - Glob
triggers:
  - novel-storyboard
  - 分镜
  - 出分镜
  - 镜头表
  - 切镜
  - 首帧
  - storyboard
  - shot list
metadata:
  license: Apache-2.0
  requires:
    bins:
      - node          # >= 18，只用标准库，无 npm 依赖
    optional:
      - codex         # 有才出首帧图；没有就只交提示词，其余照常
  runtimes:
    - claude-code
    - codex
---

## novel-storyboard

给 AI 短剧出**分镜**——管线里第一个直接面对视频模型的层。**前提刻在骨子里：镜头是生成出来的，多切一镜的成本几乎为零**，所以这里不心疼镜头数量，上限只有一个：视频模型单段生成的时长（默认 15 秒）。

**核心机制：镜头认领节拍。** 每个镜头声明它覆盖剧本某场的哪几个连续节拍（`sceneIndex` + `beats: [起, 止]`），镜头不许跨场次——换景必换镜。这让分镜和剧本的关系变成可机械对账的：

| 交付 | 解决什么 |
| --- | --- |
| 节拍认领 | 每个节拍被恰好一个镜头认领、顺序不乱——剧本改了重跑 validate，失效的镜头当场点名 |
| 单镜头 ≤ 15 秒 | AI 视频单段生成上限，长对话在这里被强制拆镜（`params.maxShotSeconds` 按模型改） |
| 台词装得下 | 认领节拍的台词秒数 ≤ 镜头秒数——逐镜检查，不是拍脑袋 |
| 首帧 + 运动双提示词 | 首帧给图像模型（配合参考图），运动是模型无关的过程描述；景别、运镜是枚举，英文短语必须写进对应提示词 |
| **H3 视频提示词（每镜一段）** | MiniMax H3 的 I2VA 结构：固定对齐指令 + integrated_multimodal_description + overall_soundscape + non_diegetic_music。**认领节拍的台词逐字进 `<d>[Chinese] …</d>` 块**——对白、声景、配乐一段提示词全带上 |
| 生成批次单 | 同场景 + 同光照的镜头归一批，共用同一张环境参考图——AI 版的顺场表，脚本自动汇总 |
| 配音对齐单 | 每句台词对到镜号——TTS 音频贴到哪一段视频，脚本自动汇总 |

`{baseDir}` = 本文件所在目录。脚本 `{baseDir}/scripts/novel-storyboard.mjs`，零依赖，`node` 直接跑。

**边界（不做的事）**：不写戏不改台词（`novel-script` 的活）、不出场景/角色/道具设定图（`novel-art` / `novel-characters` 的活）、不做视频生成与剪辑合成。口型/唇形同步暂不管——那是生成管线的事。

---

### Step 0 — 定输入与范围

**script.json 是硬前提**——分镜离开剧本没有意义，validate/render 都必须给 `--script`。其余上游按有则用：

- `--outline` / `--cast`：提示词禁人名检查 + 报告里 C01 显示成人名
- `--art`：报告里 S01 显示成场景名 + 批次单嵌场景设定图
- `--shots <卡片目录>`：**可选**挂载 shot-recipes 的镜头配方卡库（指向 `shot-recipes/references/cards`，只接受目录不接受导出的 JSON），开第 17 道 `shot-recipe` 门。没装 shot-recipes 就别给——本 skill 自包含，不依赖它

**一次切几集**：跟剧本的批次走（剧本写到哪就分到哪），默认一批 ≤ 3 集。

### Step 1 — seed 工作底稿

```bash
node {baseDir}/scripts/novel-storyboard.mjs seed <script.json> --eps 1-3 > <workdir>/storyboard.json
```

确定性展开：每场的节拍清单（编号、动作/台词、每拍秒数、说话人）进 `seedScenes`，这就是切镜时的工作底稿。**每拍几秒是算出来的，不要让模型重新估。** shots 留空，切镜才是模型的活。

### Step 2 — 逐集分段切镜并规划动作承接 ⛔ 不能跳

每集一份任务，能并发就并发。每份任务拿到：

- `{baseDir}/references/storyboard-pass.md`、`{baseDir}/references/continuity.md` 和 `{baseDir}/references/schema.md`（先读承接规则，再写提示词）
- 该集的 seedScenes 底稿 + 场景卡（art.json 的锚点与光照提示词）+ 角色卡（cast.json 的形象要点）

流程：**先按剧情单元分段**（每段 9–15 秒、不跨场），**段内切 2–5 秒的分镜**，然后按 `references/continuity.md` 写每切的起始、动作、结束和接镜安排。复用已有 `cut.note` 留存，供提示词编写、Markdown / HTML 报告与成图复核消费，不新增 JSON 字段。先检查同场景内的相邻切与跨段边界，再写分镜图提示词。

**一份承接安排生成两种提示词**：`frame` 描写切点当下的单一状态，`h3Prompt` 描写从该状态开始的动作与结果。换机位不等于换站位；不擅自增加剧本没有的松手、离开、交接或恢复。只交文字也必须完成承接规划与语义复核。

**每段写一条 `h3Prompt`**，照 `{baseDir}/references/h3-prompt.md` 写（官方方法论的内化版，**不依赖任何外部 skill**）。官方口径默认英文（`promptLang` 可切中文），**每个镜头独立一行**。要点：首行对齐指令和 `[Shot k]` 切点时刻**由分镜秒数推导，一个字符都不许漂**（validate 逐字对账）；认领台词**逐字**进 `<d>[Chinese] …</d>`；每切的运镜词写进自己那一行；声景与配乐分进后两个字段——**声景也是动作指令，画面改了声景一起改**。

切完把 `seedScenes` 删掉。

### Step 3 — 结构校验与承接复核 ⛔ 不能跳

```bash
node {baseDir}/scripts/novel-storyboard.mjs validate <storyboard.json> \
  --script <script.json> --outline <outline.json> --cast <cast.json> \
  [--shots </path/to/cards>]
```

17 道质量门全是代码：节拍全覆盖（分镜级，恰好一次、按顺序、连续）、段 0 < 总秒 ≤ 15、**每切 2–5 秒**、台词装得进分镜、每集总时长在剧本目标 ±15% 内、同框 ≤ 3 人（超了必须带拆解说明）、段号 E01-01 格式连号、景别短语在分镜图提示词里、**风格短语统一**（`style` 预设 realistic/ghibli 与角色/场景 skill 同名对齐，同剧分镜图不许画风漂）、运镜用 H3 词表且在自己的 [Shot k] 段落里、**H3 对齐指令由分镜结构推导逐字对账 + 切点时刻逐个对**、**认领台词逐字进 `<d>` 块**、**提示词语言与 promptLang 一致**（双向查：中文写成英文、英文混进中文都拦）、分镜图提示词全英文非空、英文提示词不含角色名（中文 H3 提示词放行）、场次/人物/道具对账剧本、**镜头配方对账**（可选门，见下）。

**有违规逐条修，改完重跑，直到通过。**

这 17 项是程序结构检查，**不验证自由文本里的动作语义，也不看生成图片**。结构通过后，逐切对照剧本、`cut.note`、`frame` 与对应 `[Shot k]`：动作有没有漏写或重复、起始帧是否提前完成动作、人物与持物状态能否接上、环境变化是否延续。缺承接安排或存在未解释的状态跳变时，先修再进入出图；不要把关键词齐全当作语义通过。

**第 17 道 `shot-recipe`（可选挂载）**：给了 `--shots` 才查，不给就明说跳过。cut 上可以写一个可选的 `recipe`（配方卡 id，**cut 级不是 segment 级**，**多格配方靠连续同 id 的分镜表达**，不是数组），门查三条——id 在卡库里、卡片的每条 `must_phrases` 出现在该切的 `frame` 里（两边小写化后 `includes`）、卡片 `cuts` 下限 ≥ 2 时连续同 id 的分镜数不得低于该下限。卡片的**建议景别与运镜不设门**，只在报告的「配方」列和 `checkup` 末尾提示偏离：配方是语汇不是法条，可选挂载的东西一旦变严就没人挂。

### Step 4 — 出分镜图（可选）

一切一张 16:9 关键帧，走 codex 内置 `$imagegen`，读 `{baseDir}/references/frame.md` 照契约做。要点：

- **没有 codex 就整步跳过**，只交提示词，报告显示占位不装有
- **参考图是命根子**：`-i` 挂上该段场景设定图（该光照状态）+ 画内角色的设定图 + 涉及道具的设定图，提示词只负责取景和此刻的姿态
- 一格一次调用绝不批量；输出 `./<段号>/f<切序>.png`（f1 = 主分镜图，每段一个文件夹）
- **默认先出第一段的整套分镜图给用户看效果**（3–5 张），确认画风和正反打构图再往后补——一集约 30–40 格，错了浪费的是整批
- 单个失败跳过不阻断，最后汇总说明

**出图后必须整段复核**：把本段各图和同场上一段末图并排，对照 `cut.note` 检查位置、接触关系、持物、动作阶段和环境状态；具体清单见 `references/frame.md`。不连贯时修对应图片及后续受影响镜头，不能只加一句「保持连贯」。图片缺失或在外部画布生成但未回看时，标记视觉连续性未验收，不能交成已验证的投产素材。

### Step 4.5 — 投产前审核记录 ⛔

读 `{baseDir}/references/production.md`。先确定实际模型和可提交秒数，再生成审核底稿；逐切比较剧本动作、前后状态、分镜图与运动词，填具体观察依据，不能机械批量把待审改成通过。底稿同时锁定分镜、剧本、上游输入和图片字节；任何变化都使旧审核失效。

```bash
node {baseDir}/scripts/novel-storyboard.mjs review-template <storyboard.json> --script <script.json> --out <分镜图目录> --model h3 > review.json
node {baseDir}/scripts/novel-storyboard.mjs export <storyboard.json> --script <script.json> --out <分镜图目录> --review review.json
```

两条命令带相同的 `--outline / --cast / --art`（如有）。默认导出拒绝缺图、缺评、旧版审核、不同段序/秒数以及非 H3 目标；其他模型须先另行适配。**只交文字用 `export ... --draft`**，草稿会明确标记未验收，不可直接投产。程序只能检查审核记录与输入版本，不能替代真实看图，也不证明成片已经连贯。

### Step 5 — 输出与汇报

```bash
cd <输出目录>
node {baseDir}/scripts/novel-storyboard.mjs render <剧名>-storyboard.json --md \
  --script <script.json> --outline <outline.json> --art <art.json> > <剧名>-storyboard.md
node {baseDir}/scripts/novel-storyboard.mjs render <剧名>-storyboard.json --html \
  --script <script.json> --outline <outline.json> --art <art.json> > storyboard-report.html
```

报告界面语言用 `--lang zh|en` 指定（优先级 `--lang` > JSON 顶层 `lang` 字段 > 默认中文）——只切界面标签，与 `promptLang`（H3 提示词语言）互相独立。`render` 自动去 `images/<镜号>-frame.png` 找首帧（批次单还会找场景设定图），**先出图再 render**。报告含：KPI 带、分镜节奏带（粗分隔 = 段边界、片宽 = 分镜时长占比、颜色深浅 = 景别远近、点击跳段卡）、分集分镜表（主分镜图 + 子分镜条 + 逐切分镜行 + 分镜图/H3 提示词复制按钮）、生成批次单、配音对齐单、质量门、导出 JSON。Markdown 版每段附完整 H3 提示词，直接复制可用。

汇报说清：几集几镜、总时长 vs 目标、几个生成批次、出了几张首帧、报告路径；**结构校验、承接语义复核、成图连续性验收分别汇报**，未做或缺图就写未验收，不把结构全绿当作全部完成。程序报告的承接备注是供人核对的计划，不是自动验收结论。

投产交接核对：图片顺序与切点一致；提示词只提交一份；实际生成时长等于段总秒数。下游不接受小数秒时，先调整分镜时长、对齐指令并重新校验导出，不能静默截短。目标视频模型不同于 H3 时，先按该工具输入契约适配，再检查内容和时长；本 skill 不执行视频生成。

最终落地：

```
<输出目录>/
├── <剧名>-storyboard.json
├── <剧名>-storyboard.md
├── storyboard-report.html         ← 双击就能开
├── review.json                    ← 逐切观察依据、投产设置与输入指纹（非草稿导出必需）
├── manifest.json                  ← export 生成
└── E01-01/                        ← 一段一个文件夹 = 一次 H3 生成的全部材料
    ├── f1.png                     ← 主分镜图（有 codex 才有）
    ├── f2.png …                   ← 子分镜图
    └── prompt.md                  ← H3 提示词（export 生成）
```

---

## 五个 skill 的接力（管线到此闭环）

```
novel-outline    → outline.json    （什么：结构与分集）
novel-characters → cast.json       （谁：角色设定图）
novel-art        → art.json        （哪里：场景/道具设定图）
novel-script     → script.json     （戏：场次、节拍、台词）
novel-storyboard → storyboard.json （怎么拍：镜头、首帧、批次）
```

分镜是消费端：seed 吃 script.json，分镜图出图吃 art 和 characters 的设定图当参考，H3 提示词直接下单给视频模型，配音对齐单接 script 台词本的 TTS 产物。五份 JSON 各自的报告都带导出按钮，改完都能喂回各自的 render/validate。

## 边界

- 报告界面内置中英（`--lang`，默认中文）；提示词语言由 `promptLang` 单独控制（默认英文）
- 秒数是**下给视频模型的生成时长**不是估算——段上限按你的模型改 `params.maxSegmentSeconds`，切的节奏区间改 `min/maxCutSeconds`
- 口型/唇形同步暂不管——那是生成管线的事
- 分镜图不要求一次成功，但进入视频生成前必须核对构图、资产和连续状态；外部生成的图也要回流验收

## 门失败会累积

`validate` 与 `checkup` 每次都把门的结果追加到**当前目录**的 `.gates.jsonl`；跑 `stats` 汇总：

```bash
node {baseDir}/scripts/novel-storyboard.mjs stats
```

回答三件事：**哪道门最常响**（那条规则模型最常无视，该改的是措辞）、**哪道门从没响过**（可能是死门，也可能规则已被内化）、**失败详情长什么样**（反复出现却没有门的那类问题，只能靠人看）。

不想记加 `--no-log`；写不进去静默跳过，不影响校验。

## 自测

```bash
node {baseDir}/scripts/selftest.mjs
node {baseDir}/scripts/production-selftest.mjs
```

271 项断言，不调模型、不花额度。17 道质量门每一道都有击穿用例；另测承接备注展示、缺失提示、中英文报告和 HTML 转义，不把这些测试当作成图语义验收。改完脚本先跑这个。

`production-selftest.mjs` 另外覆盖投产审核版本、逐切完整性、时长/段序、模型边界与 CLI 的草稿/正式导出分流，同样不能代替人工视觉验收。

## 自带样例

`{baseDir}/examples/渡口-storyboard.json`：《渡口》第 1 集完整分镜——10 段 34 切认领剧本全部 35 拍，平均 3.5 秒一切，共 119 秒 / 目标 120 秒，2 个生成批次，每段带完整的 H3 视频提示词（多图对齐 + 切点时刻全部对账通过）。当质量基准，也是自测夹具。
