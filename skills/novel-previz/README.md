# novel-previz · 预演技能

先分析分镜，选择**白模、宫格、白模与宫格组合或不额外预演**，再处理对应分支。
不再默认所有段落都转换成白模。

| 检查目标 | 适合的方式 |
|---|---|
| 空间、机位、多人遮挡 | 白模 |
| 多镜头顺序、景别和主体变化 | 宫格 |
| 表情、文字、道具细节 | 复核已有关键帧，不新增预演 |
| 同时存在空间和多镜头衔接问题 | 白模 + 宫格 |
| 简单重复画面，没有明确疑点 | 不额外预演 |

## 先运行分析

在本技能目录运行自有样例：

```bash
python3 scripts/storyboard_to_shots.py analyze \
  --storyboard examples/失物窗口-analysis-storyboard.json --out ./previz
```

产出：

- `previz/_analysis/analysis.json`：每段的方式、镜头范围、依据和限制。
- `previz/_analysis/analysis.md`：可阅读的分析结果与后续处理说明。

样例故事见 [examples/失物窗口-story.md](examples/失物窗口-story.md)，先确定故事再安排检查范围。
配套 JSON 是本技能自有的最小分析夹具，不是完整投产分镜。使用真实项目时替换为已确认的分镜文件。
可添加 `--ep 1` 或 `--segment E01-03` 筛选范围。

**这是规则初筛，不是完整剧情理解。** 结构与有限文字线索会给出可复核依据；
分析不会修改分镜、启动 Blender、出图或调用模型。复杂否定、隐含动作和跨段承接仍需人工复核。

## 选择之后

- **白模**：准备一次场景配置，后续重复执行转换脚本。
- **宫格**：运行 `export-grid`，读取分镜画面描述，交付完整宫格图提示词和锁定分镜数据，图片可选。
- **已有关键帧复核**：只检查 `scope.review` 列出的原画面，发现问题退回分镜修正，不重新生成一套关键帧。
- **组合**：先检查空间，再比较连续画面；单格细节回看已有原图。
- **不额外预演**：继续原流程，不为了凑流程追加材料。

## 宫格分支

```bash
python3 scripts/storyboard_to_shots.py export-grid --storyboard 项目-storyboard.json --out ./previz
```

默认重新分析，仅导出推荐宫格的段；添加 `--segment E01-02` 可明确选择某段，单镜除外。
**必需的是分镜 JSON 中的画面描述、景别和时长，不是视频提示词，也不要求已经出图。**
有实际图片时才追加 `--frames ./frames`；允许只有部分镜头有图，缺少的镜头依据原描述。
参考图使用 `frames/E01-02-f1.png` 或 `frames/E01-02/E01-02-f1.png` 等命名，
支持 PNG/JPG/JPEG/WebP，每镜只能有一个非空版本。导出：

- `previz/_grid/index.json`：本次交付状态、模板来源及限制。
- `previz/_grid/<段号>/grid-input.json`：原镜号、实际时间码、景别、切点状态和可选图片路径；没有图片时 `reference` 为 `null`。
- `grid-prompt.txt`：可以提交给图像工具的完整宫格图提示词。
- `grid-brief.md`：参考图清单与锁定规则。

没有图片不阻断导出；已提供图片为空或有重复版本、分镜缺少必要字段时输出 `grid.todo`，退出码 2，不发布完整提示词。
重复导出先将所选段旧交付保存为 `.stale`，防止旧提示词继续误使用；输入或模板错误为退出码 3。显式图片目录无效也会报错，没有图片请省略 `--frames`。

**这次衔接的是完整宫格生成提示词，不只是拼图说明。** 程序优先读取已安装的 storyboard-builder 锁定分镜模板，
没有安装时使用本技能内化模板，也可以通过 `--builder <目录>` 指定；不需要每次由 Agent 重新处理。
宫格不固定十五格或每格两秒，保留原顺序和实际时长；有图时默认沿用参考画幅，无图时不虚构原画幅，可通过 `--aspect 9:16` 等明确指定。

**没有自动出图。** 无图时可以直接提交提示词；有图时再一起提交参考图片，路径不会自动上传。
角色图或场景图可在出图时另外附加；当前命令只自动匹配按原镜号命名的关键帧。
无图提示词会明确标注仅依据文字，不承诺外观一致性已经验证。
如果只需要像素完全不变的原图排列，应另使用拼图工具。白模视频抽帧宫格是另一条空间检查路径。
完整说明见 [references/grid-preview.md](references/grid-preview.md)。

## 白模分支

下面命令中的项目文件与段号应替换为你的实际输入，仅对选中的白模段落执行：

```bash
python3 scripts/storyboard_to_shots.py init-config \
  --storyboard 项目-storyboard.json --script 项目-script.json --out ./previz

# 按 references/scene-config.md 填写 previz/scene-config.json
python3 scripts/storyboard_to_shots.py export \
  --storyboard 项目-storyboard.json --script 项目-script.json \
  --config previz/scene-config.json --segment E01-04 --out ./previz

blender -b --python-exit-code 1 --python previz/E01-04/scene.py -- review out
blender -b --python-exit-code 1 --python previz/E01-04/scene.py -- review_anim out/rev
ffmpeg -framerate 24 -i out/rev/f_%04d.png -pix_fmt yuv420p out/rev.mp4
```

这是基础白模适配，不会自动还原文字中的精确构图、站位变化、动作或道具交接。
导出报告的 `unverified` 与分析报告的能力限制必须一起阅读，结构门通过不代表这些内容已经验证。

## 导出安全与验证

- 被引用道具缺少坐标、尺寸或挂手兜底时，不生成可执行场景。
- 重复导出把所选段旧脚本保留为 `scene.py.stale`；缺项输出 `.todo`，补齐后清除待办。
- 对账门失败时，本批次不发布 `scene.py`；分析报告与导出报告分目录存放。

```bash
python3 scripts/storyboard_to_shots.py selftest
python3 scripts/storyboard_to_shots.py selftest --blender blender
```

第二条命令额外执行 Blender 场景与静帧检查；默认自测不证明渲染可运行。

## 依赖与文档

- 分析和宫格提示词导出：Python 3 标准库，不依赖 Blender；宫格模板有内化回退，不强依赖其他技能。
- 白模执行：已有 greybox-harness 工具链；路径可通过 `--blockout` 指定。
- 白模渲染和视频合成：Blender 5.x 与 ffmpeg。

完整流程见 [SKILL.md](SKILL.md)，选择依据见 [references/previs-selection.md](references/previs-selection.md)，
场景配置见 [references/scene-config.md](references/scene-config.md)。
