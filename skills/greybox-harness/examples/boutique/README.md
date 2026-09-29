# 示例 · 精品店

一条 16 秒、7 镜 6 切的购买段落。它是刻意挑的 —— 覆盖了这套管线里最容易翻车的几件事:

| 镜 | 时间 | 机位 | 它在演示什么 |
|---|---|---|---|
| S1 | 0.0–3.2 | 橱窗中景 | 主体是**橱窗里那件东西**,所以人不能站在它正前方 —— 摆到画面右缘当侧面前景 |
| S2 | 3.2–5.0 | 入口中景 | 一个连续空间里的两个子区域，靠**一次硬切**连起来;中间的路不拍 |
| S3 | 5.0–7.4 | 柜台中景 | 两人隔柜台面对面。**两人都贴到柜台边**,否则手够不到台面 |
| S4 | 7.4–9.2 | 包装手部 | 插镜。台面在 1.09m，平视会贴着台面 → **从上方俯下来**;而且**手必须在道具上** |
| S5 | 9.2–11.6 | 店员过肩 | 过肩，带一次很小的推进 |
| S6 | 11.6–13.2 | 终端特写 | 手机的位置从**手的实测世界坐标**取，不硬填 |
| S7 | 13.2–16.0 | 柜台横向 | 一件道具**只许移动一次**,而且要卡在某个时间点之后 |

另外演示的:
- **洞口必须是真的洞** —— 橱窗壁龛和入口都是分段的墙 + 留空，不放板子
- **竖肋当刻度尺** —— 空立面在透视里读不出远近
- **同一个角色的三组走位**互不干扰，靠 `FIG` 的 key 按镜切换可见性

## 跑

```bash
blender -b --python scene.py -- audit        # 送模版明度自检:谁和谁会糊成一片
blender -b --python scene.py -- probe        # 关节实测坐标
blender -b --python scene.py -- project      # 构图数字
blender -b --python scene.py -- blockers     # 遮挡扫描(全部通畅)
blender -b --python scene.py -- plan        out
blender -b --python scene.py -- review_anim /tmp/rev
blender -b --python scene.py -- anim        /tmp/mod
ffmpeg -framerate 24 -i /tmp/rev/f_%04d.png -pix_fmt yuv420p out/review.mp4
ffmpeg -framerate 24 -i /tmp/mod/f_%04d.png -pix_fmt yuv420p out/model.mp4

blender -b --python scene.py -- export out/facts.json      # 白模事实 → 给 prompt 对账
python3 ../../tools/check_prompt.py prompt.txt scene.py --facts out/facts.json
python3 ../../tools/verify_cuts.py out/model.mp4 scene.py
```

## out/ 里有什么

| 文件 | 是什么 |
|---|---|
| `review.mp4` | 审片版:彩色描边、烧镜号。**给人看的** |
| `model.mp4` | 送模版:平光灰模。**喂给生成模型的** |
| `plan.png` | 俯视平面图 + 七个机位的视锥楔形 |
| `review_sheet.png` | 每一镜入点/出点各一帧的接触表 |
| `verify_report.txt` | 切点核验(拿白模自己验自己，6/6) |
| `facts.json` | 每一镜每个元素的画面坐标/占幅/距离，`check_prompt --facts` 拿它做三层对账 |

## 没有附带的

**定妆板、空镜、商品实物图都没有** —— 那些在我这边是第三方版权素材。
`prompt.txt` 里的 `@图片1…5` 就是留给它们的槽位，你自己准备:

```
@图片1  人物定妆板     锁脸、发型、服化道
@图片2  店外空镜       锁立面材质与夜色
@图片3  店内空镜       锁墙/天花/地面材质与灯光
@图片4  商品实物图     锁轮廓、颜色、五金
@图片5  礼袋实物图     锁颜色、比例、提手
```

**成片也没有附带** —— 我这边跑出来的那条画面里有可辨认的第三方品牌标识，不适合放进公开仓库。
你自己跑出来之后，用 `verify_cuts.py` 对着 `scene.py` 量一遍就知道复现得怎么样。
