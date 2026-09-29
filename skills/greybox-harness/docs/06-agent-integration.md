# 让 agent 开 Blender

这一层讲的是:**Claude Code(或别的 agent)怎么从一段剧本走到一个能用的 `scene.py`。**

有两条通道,它们不是二选一,是**分工**:

| | 怎么跑 | 强在哪 | 弱在哪 |
|---|---|---|---|
| **headless 脚本** | `blender -b --python scene.py -- <mode>` | 确定性、可复现、能进 CI、能批量、无 GUI | 看不到实时视口,每次都得整帧渲染 |
| **BlenderMCP** | agent 通过 MCP 连一个**开着 GUI 的 Blender** | 能看、能试、能一句一句改、能截视口 | **在 `blender -b` 下起不来**;会话状态不可复现 |

这套 harness 的**生产回路是 headless 的**。MCP 是**探索期和排查期**的东西。
下面第 4 节讲的那条纪律是全篇最重要的一句:**live 会话不是真相,`scene.py` 才是。**

---

## 1. 接上 BlenderMCP

**Blender 这一侧** —— 装 addon,在 View3D 侧栏(N 键)的 BlenderMCP 面板里点 Start:

- addon 落在 `~/Library/Application Support/Blender/<版本>/scripts/addons/blender_mcp_addon.py`(macOS)
- 它起的是一个 socket server,默认 `localhost:9876`
- **Blender 必须是开着窗口的 GUI 进程。** 在 `blender -b` 里它会直接打印
  `cannot start server in background mode` 然后退出 —— 这不是 bug,是它的设计

**agent 这一侧** —— Claude Code:

```bash
claude mcp add blender -- uvx blender-mcp
claude mcp list        # 确认连上了
```

其他 agent 用等价的 MCP 配置:

```json
{ "mcpServers": { "blender": { "command": "uvx", "args": ["blender-mcp"] } } }
```

## 2. 只用这四个能力,别碰其他的

addon 暴露了不少东西,做灰模**只需要四个**:

| 工具 | 用来干嘛 |
|---|---|
| `get_scene_info` | 场景里现在有哪些物件、类型、位置 —— 用来核对脚本跑出来的结果 |
| `get_object_info` | 单个物件的变换、尺寸、材质 |
| `execute_code` | 在 Blender 里跑任意 Python。**这是主力**,建几何、摆机位、读关节坐标都靠它 |
| `get_viewport_screenshot` | 抓视口。不是渲染,几乎瞬时,适合快速看一眼 |

**其余的一律关掉。** addon 还带 Poly Haven / Hyper3D / Sketchfab / Hunyuan3D 这几个资产库集成
(在面板上有开关)。它们会往场景里塞**带贴图、带材质、带造型的成品模型** ——
那正好违反[铁律 3](02-ironclad-rules.md#3-白模只是图纸不是效果图):白模只是图纸,不是效果图。
灰模场景里出现一个 PBR 沙发,送模版就会把那个沙发的造型抄进成片。

> `execute_code` 是**在你的机器上执行任意 Python**。它只应该连到你自己起的本地 Blender。
> 不要把 9876 暴露到局域网以外。

## 3. 意图读取:从剧本到 `scene.py`

agent 拿到一段剧本,**第一件事是分堆**,不是建模。分错了后面全是白干。

```
剧本
 ├─ 空间事实  → 进白模        谁站在哪、面朝哪 · 什么东西放在哪
 │                            机位/景别/焦距 · 第几秒切一刀 · 道具什么时候动、动到哪
 ├─ 表演事实  → 进 prompt      情绪弧线 · 台词逐字 · 节奏 · 不许做的动作
 └─ 外观事实  → 进资产图        长相 · 服装细节 · 材质与光 · 道具的轮廓与五金
```

判据很简单:**这件事能不能用坐标写下来?** 能,就进白模;不能,就进 prompt 或资产图。

剧本里那些「不可漂移」的锁 —— 道具在哪只手、袋面朝哪、人物统一从左往右 ——
**同时是空间事实和表演事实**,两边都要写。

### agent 应该按这个顺序做

1. **先抽时间轴,再建几何。** 从剧本里数出这一条有几个镜头、每一镜多长、在第几秒硬切,
   写成 `SHOTS` 表。**这张表是整个项目的唯一真相** —— prompt 的时间码、切片边界、
   成片核验全部从它取。
2. **定坐标约定。** X 是画面左右(人物行进方向取 +X)、Y 是纵深、Z 是高。
   机位要正对主墙,否则「统一左→右」在画面上会翻([铁律 10](02-ironclad-rules.md))。
3. **建房间外壳。** 要看穿的地方留空,不要放玻璃板([铁律 2](02-ironclad-rules.md))。
4. **摆人,再摆道具。** 道具坐标从 `human.hand(tag, "R")` 读,不要硬填([铁律 7](02-ironclad-rules.md))。
5. **算机位,不要试机位。** 焦距 = 36mm ÷ 目标画幅宽 × 距离。用 `-- project` 出数字。
6. **跑自检**:`-- audit`(送模版明度)、`-- blockers`(遮挡)、`-- plan`(有没有越轴)。
7. **渲审片版,交给人。** 到这里为止一分钱没花。

### 什么时候该停下来问人

agent 应该自己决定的:焦距、机位微调、家具尺寸、姿势参数、竖肋间距。

**必须问人的**:

- 剧本和参考图打架(比如剧本写「商场店铺」而空镜是「街边旗舰店」)
- 某个镜头的主体到底是谁 —— 主体错了整镜作废
- 一条要不要拆(超过 30 秒必须拆,拆点落在哪一刀上是创作决定)
- 资产图缺失时,是等图还是用文字顶上

## 4. 唯一一条纪律:live 会话不是真相

MCP 很好用,好用到会让人忘记它是**易失的**。agent 在 live 会话里 `execute_code` 挪了一把椅子,
那个改动**只存在于那个 Blender 进程里**。关掉就没了,而且 `scene.py` 完全不知道这件事。

> **在 live 会话里做的任何改动,都必须回写进 `scene.py`。**
> live 会话是草稿纸,`scene.py` 是稿子。

推荐的回路:

```
agent 读剧本
  → 写 scene.py(几何 + 机位 + SHOTS)
  → 在 GUI Blender 里:execute_code 载入 scene.py,get_viewport_screenshot 看一眼
  → 不对?在 live 里试改,试通了 → 把改动写回 scene.py
  → headless 重跑一遍验证:blender -b --python scene.py -- review
  → 交给人 confirm
```

**验证那一步不能省。** live 会话里可能残留着你上一轮试出来的状态;
只有 `blender -b` 从零跑一遍出来的结果,才代表 `scene.py` 真正的样子。

## 5. 一段可以直接抄的 live 探查

在 GUI Blender 连上 MCP 之后,agent 用 `execute_code` 跑这个,能一次拿到建场景需要的全部实测数据:

```python
import sys, importlib
sys.path.insert(0, "/path/to/VLM-Generation-Harness/blockout")
import rig, human, project
for m in (rig, human, project):
    importlib.reload(m)          # live 会话里改完模块要 reload，否则跑的还是旧的

# 载入场景文件本身(它会自己 new_scene，清干净再建)
exec(open("/path/to/scenes/my_scene.py").read().split('if MODE ==')[0])

# 关节实测坐标 —— 道具往这儿放
for n in ("LEAD_头", "LEAD_hand.R", "LEAD_hand.L"):
    o = bpy.data.objects.get(n)
    if o: print(n, tuple(round(v, 3) for v in o.matrix_world.translation))

# 送模版明度自检
rig.audit_model_pass(bpy.data.objects)
```

看完视口截图,改动**回写进 `scene.py`**,然后 headless 重跑。

## 6. headless 六个模式,agent 该什么时候用哪个

```bash
blender -b --python scene.py -- audit        # 送模版里谁和谁会糊成一片
blender -b --python scene.py -- probe        # 人体关节的实测世界坐标
blender -b --python scene.py -- project      # 每个元素在画面的位置/占幅/距离
blender -b --python scene.py -- blockers     # 谁挡住了谁
blender -b --python scene.py -- plan   out   # 俯视平面图 + 视锥,看越轴
blender -b --python scene.py -- review out   # 审片静帧(彩色,给人看)
blender -b --python scene.py -- review_anim out/rev   # 审片视频 → 人 confirm
blender -b --python scene.py -- anim   out/mod        # 送模视频 → 喂模型
```

前五个都是**秒级、不出图或只出小图**,agent 应该频繁跑。
后两个要整帧渲染,确认几何之后再跑。

## 7. 别让 agent 做的事

- **别让它改 `SHOTS` 之外的时间码。** prompt 的时间码是从 `SHOTS` 抄的,
  agent 若两边分别编辑,就会出现「prompt 说 5.0 切、白模 4.6 切」这种谁也发现不了的漂移。
  用 `tools/check_prompt.py` 卡住。
- **别让它拿 prompt 去验 prompt。** 核验数据只能从 `scene.py` 取(见 [`01-pipeline.md`](01-pipeline.md))。
- **别让它在 live 会话里「顺手」加资产库模型。** 见第 2 节。
- **别让它跳过人的 confirm 直接出片。** 那一步是这整套东西存在的理由。
