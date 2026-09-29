---
name: greybox-harness
description: 用 Blender 白模(greybox)给 AI 视频生成做机位、空间和切点的预演层——建房间、摆机位、导出参考视频喂进生成模型的 video 通道，再用规范化的 prompt 补齐表演与材质。当任务涉及「白模/greybox/previs/分镜预演」、要让同一场景的多个镜头保持空间一致、要精确控制硬切时刻、或要在花钱出片之前先验证机位和遮挡时使用。
---

# 白模 harness · AI 视频生成的 dev 环境

**白模是机位和空间的 dev 环境，生成模型是 prod。**
先在 Blender 里把房间、机位、走位、切点试对，人 confirm 之后再花钱出片。

核心主张:**空间和时间用几何控制，长相和表演用文字控制，两者不许互相越界。**

## 什么时候用

- 同一个场景要出好几条，需要它们看起来是同一个房间
- 需要精确控制「第几秒切一刀」
- 一条里有多个机位、多次硬切
- 有「道具只能动一次」「人物统一从左往右」这类硬锁
- 出片贵，想在花钱之前拦住错误

单镜头、无切点、空间不重要的片子，**不需要这套东西**。

## 目录

| 路径 | 是什么 |
|---|---|
| `blockout/` | Blender 工具链。`rig`(建体块/双通道渲染/平面图)、`human`(可摆姿势的人体代理)、`project`(投影校验/遮挡扫描) |
| `blockout/scene_template.py` | **开新场景从这里复制** |
| `tools/` | `verify_cuts`(切点核验)、`check_prompt`(prompt 自检)、`contact_sheet`(接触表)、`slice_shots`(按镜号切片) |
| `templates/` | prompt 骨架、跨条复用的空间锁骨架 |
| `examples/boutique/` | 一条 16 秒 7 镜 6 切的完整例子，含白模视频、平面图、prompt、核验报告 |
| `docs/` | 流程、铁律、prompt 规范、模型侧实测、疑难排查 |

## 怎么跑

```bash
# 1. 建场景(复制模板改)
cp blockout/scene_template.py scenes/my_scene.py

# 2. 先算再渲 —— 每一步都不花钱
blender -b --python scenes/my_scene.py -- probe          # 人体关节实测坐标
blender -b --python scenes/my_scene.py -- project        # 构图数字:位置/占幅/距离
blender -b --python scenes/my_scene.py -- blockers       # 谁挡住了谁
blender -b --python scenes/my_scene.py -- plan  out      # 俯视平面图 + 视锥

# 3. 审片版给人看 → confirm
blender -b --python scenes/my_scene.py -- review      out
blender -b --python scenes/my_scene.py -- review_anim out/review
ffmpeg -framerate 24 -i out/review/f_%04d.png -pix_fmt yuv420p out/review.mp4

# 4. 送模版给模型
blender -b --python scenes/my_scene.py -- anim out/model
ffmpeg -framerate 24 -i out/model/f_%04d.png -pix_fmt yuv420p out/model.mp4

# 5. 写 prompt 并自检
python3 tools/check_prompt.py prompts/my.txt scenes/my_scene.py

# 6. 出片 → 核验
python3 tools/verify_cuts.py result.mp4 scenes/my_scene.py
python3 tools/contact_sheet.py result.mp4 -o sheet.png --scene scenes/my_scene.py
```

## 读哪份文档

- 先看 [`docs/01-pipeline.md`](docs/01-pipeline.md) —— 八步流程和每一步在干嘛
- 动手前必读 [`docs/02-ironclad-rules.md`](docs/02-ironclad-rules.md) —— **14 条铁律，每一条都是花过钱换来的**
- 写 prompt 时看 [`docs/03-prompt-spec.md`](docs/03-prompt-spec.md) —— 章节顺序、每节写什么、为什么
- 换模型时看 [`docs/04-model-notes.md`](docs/04-model-notes.md) —— 该测什么、我这边的实测数
- 出问题时看 [`docs/05-troubleshooting.md`](docs/05-troubleshooting.md) —— 症状 → 诊断 → 修法

## 三条最容易踩的

1. **给模型的是平光灰模，不是彩色审片版。** 参考视频是像素通道不是说明书通道 ——
   描边、烧字、饱和色都可能被抄进成片。两个通道的**几何**逐字节一致，
   但**明度不一定** —— 审片版靠描边和颜色分层，送模版只有明度。跑 `-- audit` 自检。
2. **要看穿的地方必须是真的洞。** Workbench 里没有透明，
   一块「玻璃」就是一堵实心墙,主体会被吃掉。
3. **核验数据从场景文件取，不从 prompt 取。** prompt 的时间码本来就是照着场景文件抄的,
   拿它验 prompt 是循环验证。

## 依赖

- Blender 5.x(用了自带的 Rigify;`BLENDER_WORKBENCH` 直接赋值可用，虽然不在 engine 枚举里)
- ffmpeg / ffprobe
- Python + Pillow(只有接触表用)
- 一个提供「参考视频 + 参考图」两个通道的视频生成模型
