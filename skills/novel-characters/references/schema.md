# 角色卡结构

`cast.json` 顶层：

```json
{
  "source": "渡口",
  "lang": "zh",
  "summary": "民国年间的清晨，一条河的渡口浓雾未散。摆渡四十年的老船夫照常开船，先后上船的是……",
  "characters": [ /* 角色卡 */ ]
}
```

| 顶层字段 | 必填 | 说明 |
| --- | --- | --- |
| `source` | 是 | 书名/篇名，报告标题用 |
| `lang` | 是 | 报告语言，默认 `zh` |
| `ui` | 视情况 | 界面文案翻译。`lang` 是 `zh`/`en`/`ja` 时**不需要**（内置）；其他任何语言**必填**，否则 `validate` 报错。用 `ui-template <lang>` 生成骨架后翻译。只覆盖部分键也可以，缺的用内置英文兜底 |
| `summary` | 是 | **故事摘要**，中文 3–5 句。交代时空背景、核心情境、人物聚在一起的由头。报告顶部显示，让人不看原文也知道这几个角色是什么关系。不要剧透结局，也不要写成推荐语 |
| `characters` | 是 | 角色卡数组 |

`summary` 缺失会被 `validate` 判为违规——报告顶部会空着。

单张角色卡：

```json
{
  "name": "老周",
  "aliases": ["老伯"],
  "importance": "major",
  "oneLiner": "在渡口摆渡四十年的老船夫，一只眼睛是白的。",

  "persona": {
    "gender": "男",
    "ageRange": "约七十岁（推断）",
    "identity": "渡口船夫",
    "appearance": "背驼得像一张拉满的弓。左眼被风沙磨得只剩一层白翳。……",
    "personality": ["沉默", "耐性", "老练"],
    "temperament": "开口时嗓子里像卡着半口江水，含混、发沉。……",
    "motivation": "把船开过去。雾再厚也照常开船。",
    "arc": "静止。他是这条河的一部分。",
    "relationships": [{ "name": "沈知微", "relation": "向他问路的年轻渡客" }],
    "evidence": ["雾一厚，连自己的手都看不清。"]
  },

  "image": {
    "prompt": "Character design sheet of an elderly Chinese ferryman ...",
    "promptLocal": "角色设定图：约七十岁的中国老船夫……",
    "negativePrompt": "young face, smooth poreless skin, perfectly symmetrical face, dead eyes without catchlights, helmet hair, extra fingers, ...",
    "tags": ["character sheet", "three-quarter view", "neutral background"],
    "sheet": "Single character model sheet on ONE 16:9 landscape canvas ... Plain pure white background ... NO dividing lines, panel borders, visible guide lines, letters, numbers, labels, captions or any other text ... UPPER ONE-THIRD ... front facial close-up, LEFT 90-degree profile ... LOWER TWO-THIRDS ... FRONT VIEW WITHOUT THE HEAD; LEFT 90-DEGREE VIEW WITHOUT THE HEAD; BACK VIEW WITH THE COMPLETE HEAD ... FOOT-SOLE LINE ... HIP LINE ... SHOULDER LINE ... NECK CUT PLANE AT CHIN-BASE HEIGHT ... HEIGHT PROPORTIONS ..."
  },

  "voice": {
    "timbre": "沙哑低沉的男中低音，喉音重",
    "pitch": "低",
    "pace": "缓慢，字与字之间拖着气口",
    "accent": "南方水乡口音，尾音含混",
    "emotion": "疲惫而平静",
    "referenceHint": "像一个在同一个渡口喊了四十年「开船」的人",
    "prompt": "An elderly male voice, around seventy-five. Low bass-baritone ..."
  }
}
```

## 语言分工

「本地语言」= 顶层 `lang` 指定的语言，默认中文。

| 字段 | 类型 | 语言 | 说明 |
| --- | --- | --- | --- |
| `name` | string | 原文 | 原文里用得最多的称呼 |
| `aliases` | string[] | 原文 | 其他称谓；职业名词（如「货郎」）归 `identity`，不进这里 |
| `importance` | enum | — | `protagonist` / `major` / `supporting` / `minor`，**只能这四个** |
| `oneLiner` | string | **本地语言** | 一句话抓住这个人 |
| `persona.*` | — | **本地语言** | `personality` 3–5 个词 |
| `persona.evidence` | string[] | **原文语言** | **逐字引用**，永远不翻译——翻了就不是证据了。没有就空数组 |
| `image.prompt` | string | **英文** | 单张人物图；**禁止出现人名**；**必须写明族裔／年代／地域，并保留身份对应的可见设计**，不指定渲染画风 |
| `image.promptLocal` | string | 本地语言 | 上面那条的译文；`lang=en` 时省略；**同样禁止人名** |
| `image.negativePrompt` | string | **英文** | 逗号分隔 |
| `image.tags` | string[] | **英文** | 4–8 个检索标签：题材、年代、色板、材质、光照。**不打画风标**（`semi-realistic`、`painterly` 这类），画风出图时才定 |
| `image.sheet` | string | **英文** | **角色设定图**，16:9 上下布局：上部 1/3 为正面与左侧 90° 面部特写，下部 2/3 为正面无头部、左侧 90° 无头部、背面有头部的身体三视图；纯白背景，无分割线或文字；五条绝对基准见 `sheet.md`；**禁止出现人名**；**必须写明族裔／年代／地域** |
| `voice.timbre/pitch/pace/accent/emotion/referenceHint` | string | **本地语言** | 最容易写漂的地方，注意 |
| `voice.prompt` | string | **英文** | 给 TTS 音色设计引擎。**没有 `promptLocal` 对照版，这是有意的**——上面六项已经是本地语言，再给一段中文散文只会让人复制错，把它喂进 TTS（生产里踩过） |

**英文字段不跟随 `lang`。** 图像模型和 TTS 引擎吃英文最稳，跟报告用什么语言无关。

## 设定图的上下布局

16:9 横构图，纯白背景，以留白组织上下两个区域，不绘制分割线、字母、编号或任何文字标注。

- **上部 1/3**：正面、左侧严格 90° 的面部特写，两张等比例。
- **下部 2/3**：正面无头部、左侧严格 90° 无头部、背面有完整头部的身体三视图。

用**脚底线、髋线、肩线、颈部切断面对齐下巴底、身高比例**五条绝对基准约束下部三个身体。基准不可见；前两个身体只省略头部，不能单独放大来追平背面头顶。完整英文骨架与对齐定义见 `sheet.md`。

## 校验

`scripts/novel-characters.mjs validate <cast.json> <book.txt>` 会检查：结构完整性、`importance` 枚举、**引文逐字**、**出图提示词不含人名**、**语言分工**。违规逐条列出并 exit 1。

脚本不判断衣着是否符合人物身份。该项由生成角色卡时按 `profile-pass.md` 的身份—外观语义自检完成；通过结构校验不代表造型语义已通过。
