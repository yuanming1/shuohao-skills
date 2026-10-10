# 站位宫格交接包

`grid-input.json` 是本技能内部可携带、可重新导出的交接包，不替换或扩展上游 storyboard schema。
只包含导出提示词和复核说明实际消费的内容；每个对象最多五个字段。

## 顶层

| 字段 | 消费位置 |
|---|---|
| `mode` | 固定 `locked-blocking-grid`，导出器检查输入类型 |
| `segment` | 原段号，决定文件夹和图页标题 |
| `layout` | `columns`、`rows`、`aspect`；决定右侧布局和单格画幅 |
| `panels` | 按原切序的关键帧描述及可选参考图片 |
| `planning` | `opening` 为原 `blocking`，`shots` 为逐镜空间与动作依据 |

## 每格 panels 条目

| 字段 | 消费位置 |
|---|---|
| `shot` | 原镜号，如 E01-02-f1 |
| `time` | 起止秒数的十进制字符串数组，累加保留精度 |
| `size` | 原景别 |
| `frame` | 原切点画面描述，逐字进入提示词 |
| `reference` | 可选图片路径，没有图片为 null；重导出时相对路径按交接包目录解析 |

## 每镜 planning.shots 条目

| 字段 | 消费位置 |
|---|---|
| `shot` | 与 panels 同位置镜号一一对应 |
| `view` | `position`、`composition`、`eyeline`，对应上游机位、构图和视线 |
| `continuity` | 原 `cut.note`，供状态说明与接镜复核 |
| `action` | 原 `cut.shot`，供布局路径标注及视频同步复核，不能当作静帧终态 |

右侧列数按镜头数平方根向上取整，最多四列；多余格子留空。时间从零开始连续累加。
导出器检查镜号、时间轴、布局、材料缺项、参考文件唯一性与非空，不判断正文空间语义。
从 `--plan` 重导出时没有上游文件可比对，不声称该包一定是分镜最新版；修订项目后应重新从 `--storyboard` 导出。
