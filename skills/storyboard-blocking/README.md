# storyboard-blocking · 站位与分镜贯通

这是 fork 中新增的独立技能：给分镜补齐空间和机位安排，同步关键帧、Seedance 与 H3 正文，再交付“左侧站位图＋右侧分镜宫格”的完整出图提示词。

## 使用位置

剧本与场景设定 → 分镜初稿 → **空间规划与提示词同步** → 站位宫格评审 → 关键帧与视频生成。

让 Agent 使用本目录 [SKILL.md](SKILL.md)，并提供项目分镜、剧本以及已有场景资料。
如果只是运行导出脚本，它不会自动补写空间或同步视频；字段缺失时会返回待补清单。

```bash
python skills/storyboard-blocking/scripts/blocking.py export \
  --storyboard 项目-storyboard.json --segment E01-02 --out ./previz
```

图片可选，已有图片时追加 `--frames <关键帧目录>`。输出放在 `previz/_blocking-grid/`，包含出图提示词、五字段交接包和逐镜复核说明。
真实场景内容和动作承接仍需 Agent 或人工判断；脚本不调用生成服务，不生成图片或视频。

## 独立体验

自有故事见 [雨棚取件](examples/雨棚取件-story.md)。样例交接包已经包含空间安排，可直接导出：

```bash
python skills/storyboard-blocking/scripts/blocking.py export \
  --plan skills/storyboard-blocking/examples/雨棚取件-plan.json --out ./previz
node skills/storyboard-blocking/scripts/selftest.mjs
```

Node 自测入口默认在 Windows 使用 `python`，其他系统使用 `python3`；可通过 `STORYBOARD_BLOCKING_PYTHON` 指定解释器。
日常导出只需要 Python 3 标准库。所有输出建议放到实际项目工作目录，不提交生成的报告或图片。

## 与上游同步

本次功能只增加 `skills/storyboard-blocking/`，不修改上游已有文件、默认流程或数据结构。
既有安装脚本能够发现新增技能，也可以直接引用本目录的 `SKILL.md`。
它可以单独复制，不导入其他技能代码；上游更新后如有数据兼容问题，只在本目录调整适配和自测。
同步上游前按正常 Git 流程提交或暂存本地工作。未来上游新增同名目录时仍需处理冲突。
