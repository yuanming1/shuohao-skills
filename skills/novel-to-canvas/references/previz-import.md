# 预演导入

交接约定依据 novel-previz 的普通宫格导出，以及既有站位宫格交付的 `locked-blocking-grid` 格式整理。导出器直接读取文件，不调用其他技能、Blender 或图片服务。

## 选择目录

在原有 export 命令中增加 `--previz <预演交付目录>`。可以指定项目预演目录、`_grid`、`_blocking-grid` 或单段目录。每个有效段需要 `grid-input.json` 和 `grid-prompt.txt`，可选 `grid-brief.md`。

脚本递归查找与 storyboard 段号相符的交付，不依赖可能只记录最近一次导出的 `index.json`。跳过 `.stale` 目录与带 `grid.todo` 的待办目录，不跟随目录符号链接。同段同时存在两种格式时优先站位宫格；同类存在多个版本时停止，改为指定唯一版本所在目录。部分段没有宫格时仍导入其 storyboard 字段，导出日志说明覆盖数量。

| 交付字段 | 画布去向 |
| --- | --- |
| `grid-prompt.txt` | 原文文本节点与宫格生图配置；有参考图时仅在配置末尾增加镜号对应关系 |
| `grid-brief.md` | 站位与拍摄说明中的交接原文 |
| `planning.opening` / `segment.blocking` | 段落开场空间、关键帧空间背景、Seedance 人物关系 |
| `planning.shots[].view` | 对应镜头的机位、构图、视线 |
| `planning.shots[].continuity` / `cut.note` | 说明与 Seedance 保存完整承接；关键帧仅提取明确的 `起始：` 内容 |
| `planning.shots[].action` / `cut.shot` | 说明与 Seedance 视频动作 |
| `cut.size/lens/cameraPosition/composition/eyeline/focus` | 说明及对应关键帧的拍摄信息 |
| `panel.reference` | 嵌入 ZIP 的预演参考图片，连入该段宫格配置并标明对应镜号 |

## 支持的交接结构

- `locked-storyboard`：顶层为 `mode`、`segment`、`layout`、`panels`。它没有单独的站位字段，空间与拍摄信息从 storyboard 补入说明和关键帧，原始宫格提示词保持不变。
- `locked-blocking-grid`：在上述结构上增加 `planning`，其中 `opening` 是开场站位，`shots` 保存逐镜拍摄安排。每条安排为 `shot`、`view`、`continuity`、`action`；`view` 为 `position`、`composition`、`eyeline`。
- `layout` 包含 `columns`、`rows`、`aspect`；`aspect` 表示格内画幅，宫格整张说明页的生图画幅默认 16:9，可在画布修改。
- 每个 panel 包含 `shot`、`time`、`size`、`frame`、`reference`。镜号沿用上游 `<段号>-f<序号>`；time 是两个十进制字符串，使用实际切点，不重新均分时长。

导入前按段号、镜号、格数、时长、景别和画面原文逐项对账。站位宫格字段与 storyboard 的非空同名内容冲突时，先同步上游再导出，不静默挑选其中一版。这项检查不会理解自然语言内部的空间矛盾；例如同一原文同时出现“银包在手中”和“银包已在案上”，仍需要人工修正上游。

## 参考图片与后续细化

`reference: null` 表示纯文字生成。图片路径为绝对路径或相对于所在 `grid-input.json` 的路径；支持 PNG、JPEG、WebP，文件必须存在且非空。只保存路径而不嵌入文件会在换机器后失效，因此脚本同时创建真实图片节点、存储映射和连线。预演参考图不会自动充当人物身份参考，也不会接入 H3/Seedance。

确认宫格后，将单镜画面裁剪为独立图片，连接到对应关键帧组合节点，并在「组装提示词」正文中通过 `@` 引用。调整参考图后在组合节点重新开始生成，选定新图片结果，再连接到两类视频组合节点，并在视频提示词最前面按镜号依次插入 `@` 图片引用。生图组合节点和整张宫格都不能直接充当视频关键帧。

原始交付文件归档到 ZIP 的 `source/previz/<段号>/`，实际参考图片打包到项目 files 中；验证不依赖原来的本机图片路径。`source/canvas-input.json` 记录导出规则版本、当前分镜入口、已导入的预演段号、剧本入口和视频全局约束，用于从 ZIP 内源数据重新核对提示词和连线。

白模的场景脚本、三维坐标配置和预演结果图片不会通过本入口自动转换成宫格或裁图。宫格生成、空间复核、裁图及人物替换仍在后续画布操作中完成。
