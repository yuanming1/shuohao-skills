---
name: novel-to-canvas
description: 将 AI 短剧的 storyboard.json、script.json、art.json 与 cast.json 导出为可直接导入 Infinite Canvas 的原生 ZIP。自动建立关键帧、场景/角色/道具参考图连线，并同时提供 MiniMax H3 与豆包 Seedance 视频节点。用户要求导入无限画布、画布投产包、分镜 ZIP、H3/豆包双视频提示词或修复画布关键帧提示词时使用。
---

# Novel Infinite Canvas

使用本技能把已经完成的短剧分镜打成原生 Infinite Canvas 项目包。脚本完全使用 Node 标准库，不依赖画布应用、npm 包或其他技能。

## 输入要求

必须提供同一批项目的四份 JSON：

- `storyboard.json`：每段必须有 `id`、`sceneIndex`、`cuts`、`h3Prompt`、`blocking`。
- `script.json`：用于按 `sceneIndex` 找到正确场次、道具和逐字台词。
- `art.json`：用于生成场景/道具参考节点及其连线。
- `cast.json`：用于生成角色主参考和独立多视角节点。

可选 `images` 目录只放已确认可用的写实场景、道具图片。脚本只嵌入能够对应 `art.json` 场景/道具的图片；不会自动打包未知图片或人物来源图，防止漫画、插画等不合格参考混入画布。

## 导出

```bash
node {baseDir}/scripts/export-infinite-canvas.mjs export \
  --storyboard <剧名>-storyboard.json \
  --script <剧名>-script.json \
  --art <剧名>-art.json \
  --cast <剧名>-cast.json \
  --images <写实场景与道具图片目录> \
  --out <输出目录>/<剧名>-分镜画布.zip \
  --title "<剧名> · 分镜投产画布"
```

图片文件名遵循 `novel-art` 的导出约定时可自动匹配：

- 场景光照：`<场景名>-L<序号>-<光照状态>.png`
- 道具状态：`<道具名>-S<序号>-<状态>.png`
- 设定图：`<场景或道具名>-sheet.png`

可选参数：

- `--constraints <文本文件>`：每行一条 Seedance 全局约束。
- `--project-id <标识>`：指定画布项目及本地图片存储键前缀。
- `--no-character-views`：只创建角色主参考图节点，不创建多视角和局部锚点节点。

## 固定导出规则

- 每一格关键帧图片节点的提示词严格等于 `cut.frame`。不追加场景锚点、光照标签或“保持已连接参考图”的通用句。
- 场景、角色、道具的一致性通过画布连线传递。场景映射必须是 `segment.sceneIndex -> script scene.sceneId -> art scene.id`，不得用数组位置猜测。
- 每个分段同时创建 H3 提示词/视频节点和豆包 Seedance 提示词/视频节点；两类视频节点连接同一批关键帧。
- `blocking` 仅进入豆包提示词的 `【人物关系与构图逻辑】`。它用于跨镜空间连续性，不是关键帧出图提示词。
- 每个角色创建一张正面全身主参考与 8 张独立多视角/局部锚点节点。人物图不做拼接大图；先生成主参考，再沿连线生成视图。
- 手机等独立道具保持在道具节点中；角色主参考不会把英文 `phone`、`smartphone`、`mobile` 或 `black rectangular slab` 识别锚点带入画面。

导入画布后，在应用配置中选择对应视频通道：H3 节点使用 H3 通道，`豆包 Seedance 视频` 节点使用豆包通道。

## 验证

```bash
node {baseDir}/scripts/export-infinite-canvas.mjs validate \
  --zip <输出目录>/<剧名>-分镜画布.zip \
  --storyboard <剧名>-storyboard.json
```

验证会检查：关键帧是否逐字对齐 storyboard、H3/Seedance 节点数量、Seedance 协议段、嵌入图片路径，以及关键帧中是否混入不该追加的场景文案。
