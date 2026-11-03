# novel-storyboard-blocking-02 · 站位与空间

**本组第 02 步，调用使用 `$novel-storyboard-blocking`。** 分镜初稿之后按需执行，空间明确后再进行 03 情绪与镜头增强、04 动作与连续状态复核；每一步承接最新分镜。编号只用于显示与使用指引，本技能可独立处理已有分镜。

这是 fork 中新增的独立技能：给分镜补齐空间和机位安排，同步关键帧、Seedance 与 H3 正文，再交付“左侧站位图＋右侧分镜宫格”的彩色人偶调度图提示词。
宫格主要表达人物调度：每个角色对应一种颜色，左右两侧与后续各段保持同色，移动路径按人物颜色和镜号标明起点、方向与停点。颜色映射、逐镜路径与调度用途写回正式 `blocking`，导出后位于视频提示词的【人物关系与构图逻辑】；真实角色外貌和服装仍由角色设定图确定。

空间修订原位更新传入的正式 `storyboard.json`，不另存分镜版本。后续增强、动作复核及导出继续使用同一路径；相关报告和宫格从正式文件重新生成。

## 使用位置

剧本与场景设定 → 01 分镜初稿 → **02 空间规划与提示词同步** → 03 表现增强（按需）→ 04 动作与连续状态复核（按需）→ 最终宫格评审、关键帧与视频生成。

让 Agent 使用本目录 [SKILL.md](SKILL.md)，并提供项目分镜、剧本以及已有场景资料。
如果只是运行 `export`，它不会自动补写空间或同步视频；缺少人偶对应或路径说明等材料时返回待补清单。Agent 应先把已确认的调度约定写入正式分镜，再导出。

```bash
python skills/novel-storyboard-blocking/scripts/blocking.py export \
  --storyboard 项目-storyboard.json --segment E01-02 --out ./previz
```

图片可选，已有图片时追加 `--frames <关键帧目录>`。输出放在 `previz/_blocking-grid/`，包含出图提示词、五字段交接包和逐镜复核说明。
真实场景内容和动作承接仍需 Agent 或人工判断；脚本不调用生成服务，不生成图片或视频。
实际生成后，该图可以按接口能力作为单独的人物调度参考提交；路径或文字提及不会自动上传图片，正式关键帧的原编号保持不变。

已有交接包中补齐的颜色与路径说明可写回原分镜：

```bash
python skills/novel-storyboard-blocking/scripts/blocking.py sync-dispatch \
  --storyboard 项目-storyboard.json --plan ./previz/_blocking-grid/E01-02/grid-input.json
```

命令只更新 `blocking` 的调度约定，校对原开场事实和镜头内容，拒绝旧包及冲突颜色；缺项返回 2，输入或版本不一致返回 3。通过后需重新导出宫格和视频提示词，H3 仍按工作流单独同步。

## 独立体验

自有故事见 [雨棚取件](examples/雨棚取件-story.md)。样例交接包已经包含空间安排，可直接导出：

```bash
python skills/novel-storyboard-blocking/scripts/blocking.py export \
  --plan skills/novel-storyboard-blocking/examples/雨棚取件-plan.json --out ./previz
node skills/novel-storyboard-blocking/scripts/selftest.mjs
```

Node 自测入口默认在 Windows 使用 `python`，其他系统使用 `python3`；可通过 `STORYBOARD_BLOCKING_PYTHON` 指定解释器。
日常导出只需要 Python 3 标准库。所有输出建议放到实际项目工作目录，不提交生成的报告或图片。

## 与上游同步

本次功能只增加 `skills/novel-storyboard-blocking/`，不修改上游已有文件、默认流程或数据结构。
既有安装脚本能够发现新增技能，也可以直接引用本目录的 `SKILL.md`。
它可以单独复制，不导入其他技能代码；上游更新后如有数据兼容问题，只在本目录调整适配和自测。
同步上游前按正常 Git 流程提交或暂存本地工作。未来上游新增同名目录时仍需处理冲突。
