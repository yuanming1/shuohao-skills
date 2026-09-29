# 场景配置 scene-config.json 填写说明

每剧一份,与 storyboard.json 放在同一输出目录。`init-config` 生成骨架后照本文填。
**核心契约:`null` = 未填。** 生成器遇到未填的必填项只会把该段降级成 `.todo` + 缺项清单,
绝不编造坐标——白模预演的价值就在「数字是真的」。

完整范例:[examples/渡口-previz-scene-config.json](../examples/渡口-previz-scene-config.json)。

## 坐标系(与 greybox-harness 一致)

- X 画面左右、Y 纵深、Z 高;单位一律米
- 人物 `face` 朝向:0=面朝 +X,逆时针为正,90=面朝 +Y
- 机位自动摆在**主体面朝射线**上(在主体面前 dist 米处回看),所以人物朝向就决定了正拍/侧拍

## 顶层

| 字段 | 必填 | 说明 |
|---|---|---|
| `version` | 是 | 固定 `1` |
| `drama` | 否 | 剧名,信息性 |
| `defaultLens` | 是 | 分镜 `lens` 字段解析不出 `NNmm` 时的兜底焦距(报告里计 ⚠) |
| `approxZoom` | 否 | 默认 `false`。`true` 时 Zoom 按推近、POV 按眼点静态近似——**永远同时进降级清单**,不是白模化 |
| `camPresets` | 否 | 覆盖五档机位预设 `{景别: {dist, eye, lookZ}}`,只填要改的档 |
| `scenes` | 是 | 键 = art.json 的 sceneId(如 `S01`) |
| `missing` | — | init-config 维护的缺项索引,export 会现场重算,不用手管 |

内置五档预设(dist=与主体距离/米,eye=机高,lookZ=注视高度;eye/lookZ 按主体身高 ÷1.68 缩放):

| 景别 | dist | eye | lookZ |
|---|---|---|---|
| extreme-wide 大远景 | 6.5 | 1.70 | 1.00 |
| wide 全景 | 4.5 | 1.60 | 1.10 |
| medium 中景 | 2.4 | 1.55 | 1.25 |
| close 特写 | 1.2 | 1.55 | 1.48 |
| extreme-close 大特写 | 0.6 | 1.50 | 1.52 |

## 场景 `scenes.<sceneId>`

| 字段 | 必填 | 说明 |
|---|---|---|
| `name` | 否 | 场景名(init 会从 art.json 预填) |
| `openAir` | 否 | 默认 `false` 室内;`true` 外景=无壳 |
| `room` | 室内必填 | `{x0,x1,y0,y1,zc,panel}` → `rig.room(...)`;外景时留 null |
| `floor` | 外景必填 | `{cx,cy,sx,sy,mat}` 地面板(mat 默认 FLOOR),命名自动带「地面_」前缀使遮挡扫描自动忽略 |
| `setPieces` | 否 | 外景「房间」的替代:立面/塔楼/护栏等 `box`/`cyl` 体块 `{name,cx,cy,cz,sx,sy,sz\|r,h,mat,role,yaw}` |
| `furniture[]` | 否 | 直通 rig 家具,`kind` ∈ desk/chair/monitor/window/box/cyl,参数与 rig 签名 1:1(注意 chair 的 `face` 是**坐者面朝**) |
| `sceneAnchor` | 有空镜则必填 | `{pos,face,lookZ}` 空镜切(无人物无道具)的拍摄主体 |
| `anchors` | 按需 | 人物站位,键 = C 编号 |
| `props` | 按需 | 道具,键 = P 编号 |

门窗要留**真的洞**:用 setPieces 分段砌墙,不要放「玻璃板」——Workbench 里那就是实心墙(铁律 2)。

## 人物锚点 `anchors.<C编号>`

| 字段 | 必填 | 默认 | 说明 |
|---|---|---|---|
| `pos` | 是 | — | `[x, y]` 站位 |
| `face` | 是 | — | 朝向角度(0=朝+X);机位摆在面朝射线上,填错=背影 |
| `pose` | 否 | `"stand"` | 必须是 human.POSES 之一:stand / sit / sit_phone / sit_side_phone / sit_type / recline / recline_phone / stand_hold / stand_reach_r / stand_reach_l / walk_r / walk_l / walk_bag_r / walk_bag_reach_l(写错会被 pose-valid 门拦住,不会静默 T-pose) |
| `height` | 否 | 1.68 | 身高(米);机高与注视高度按它缩放 |
| `lead` | 否 | true | 主角材质(暗)还是配角(亮) |
| `seatZ` | 坐姿必填 | — | 椅面高度,坐姿姿态不给会悬空 |

**同一场景同一人物只有一套锚点**(v1 限制)。同角色多站位(如 boutique 的橱窗/门口/柜台三组)暂不支持自动生成,
需要时手改生成的 scene.py 并跑 validate。

## 道具 `props.<P编号>`

`hand` 与 `pos` **必须且只能给一个**:

| 字段 | 必填 | 说明 |
|---|---|---|
| `hand` | 二选一 | `"C01:R"` 挂在某人右手,运行期从 `human.hand()` 实测(铁律:道具跟着手走,不硬填) |
| `pos` | 二选一 | `[x, y]` 落点;`z` 填 `"floor"`(默认,落地)或数字(中心高) |
| `fallback` | hand 时必填 | 手查不到时的兜底坐标 `[x,y,z]`,兼作生成期机位几何/构图估计——**认真填,别乱填** |
| `offset` | 否 | 挂手偏移 `[dx,dy,dz]`,如皮箱垂在手下方 `[0.05,-0.15,-0.30]` |
| `dims` | 是 | box:`[sx,sy,sz]`;cyl:`[r,h]` |
| `shape` | 否 | `box`(默认)/`cyl` |
| `mat` | 否 | 调色板键,默认 PROP:WALL/WOOD/FLOOR/DARK/RELIEF/SCRN/GLASS/BODY/EXTRA/PROP |
| `role` | 否 | 默认 prop:shell/furniture/screen/prop |
| `name` | 否 | 显示名(报告/MARKS 里用),默认道具编号 |

道具是**场景几何**，当前实现不随镜头隐藏。某镜不引用 `props` 并不会让道具消失；
逐镜持物变化、交接和隐藏不在自动适配范围，不能据此宣称动作连续性已验证。

**人物与道具同框也要检查道具配置。** 被引用道具缺少落点或挂手信息、尺寸、挂手兜底坐标时，
该段进入待补清单，不发布可执行文件。`shape`、`mat`、`role`、`z` 等可选值为 null 时采用表中默认值。

## 填写流程建议

1. 先跑 `init-config`,拿到骨架和缺项清单
2. 对着 art.json 的场景 `anchors`(一致性锚点)回想空间:门在哪、主墙在哪、人站哪
3. 基础机位由景别、焦距、人物朝向和 `camPresets` 推导，**不解析 `cameraPosition`、`composition` 等文字**；需要准确还原时，检查报告 `unverified` 并人工复核或调整场景。
4. 填写后运行 `export`，先处理待补项和违规，再查看 `unverified` 未预演清单；待补清零不代表全部分镜意图已经实现。
5. `blender -b --python <段>/scene.py -- plan out` 出俯视图,检查站位/家具关系对不对,改配置再导出
