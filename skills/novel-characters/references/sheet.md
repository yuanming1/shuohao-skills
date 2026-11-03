# 角色设定图的版面规格

`image.sheet` 是给出图模型的完整版面指令。本 skill 只产出提示词，图像由下游生成；画风在出图时统一附加。

## 画布与上下布局

每个角色一张 16:9 横向画布，背景全域纯白 `#FFFFFF`。上下区域通过留白组织，**画面中没有分割线、边框、基准线、字母、编号或任何文字标注**。下文的区域名和五条基准只是排版约束，不是需要绘制的元素。

| 区域 | 占画布高度 | 从左到右的内容 |
| --- | --- | --- |
| 上部 | 1/3 | 面部正面特写、面部左侧严格 90° 特写 |
| 下部 | 2/3 | 正面无头部、左侧严格 90° 无头部、背面有头部的身体三视图 |

上部两个视图等比例、等距排列，完整呈现头顶、发型、耳朵与下巴，不替换成半身像。左侧视图展示人物自身的左侧，鼻尖朝画面左方；不能替换成右侧或四分之三侧面。

下部三个视图等距排列，均完整保留身体与双脚。正面与左侧视图只省略头部，颈部保留至下巴底所在高度，以干净的非血腥设计截面收口，不能变成空白脸、无五官头部、裁到肩膀或裁到领口。背面视图保留完整头部和发型。

## 五条绝对基准

先以背面完整人物确定同一套身体尺度，再旋转得到正面与左侧视图；不能把无头部视图单独放大到背面头顶高度。五条基准逐条写入英文正文，所有基准线均不可见：

| 绝对基准 | 必须明确的约束 |
| --- | --- |
| 脚底线 | 三个身体视图的脚底落在同一个水平高度，脚下留白一致 |
| 髋线 | 三个视图的髋部骨性位置处于同一个水平高度，不能以腰带或衣摆代替 |
| 肩线 | 三个视图的肩部骨性位置处于同一个水平高度，保持人物原有体态 |
| 颈部切断面对齐下巴底 | 正面与左侧的颈部切断面在同一高度，对齐完整人物尺度中的下巴底高度；背面保留头部，不绘制截面 |
| 身高比例 | 三个视图共用同一缩放比例、躯干长度、四肢长度及原有头身比例；前两个只省略头部，不能补偿性增高、拉伸、压扁或透视缩短 |

不再使用一句“三张全身身形一致”代替这五项。人物本来驼背、肥胖或有特殊体态时，三个视图都保留，不能为了对齐而改成另一种体型。

## 人物与服装一致性

主体描述承接 `image.prompt` 中的年龄、身份对应的服饰、面料品质、发饰、随身物件与仪态，不能排版后只剩衣服颜色。五个视图属于同一个人、同一套装束；原文明确的乔装或落难状态仍然保留，不擅自更换礼服。正面和侧面特写的骨相、年龄、五官、发际线与发型一致，背面头部也承接同一发型。身体视图按相同尺度保留服装和物件，头部饰物只出现在有头部的视图中。

这张设定图不附加细节条、额外视图或说明文字。可辨认的细节直接落实在对应的面部与身体视图中。

## 光照与留白

上部两张面部特写使用一致的柔和方向光和轻微环境遮蔽，保持五官体积与辨识度。下部三个身体视图使用均匀平光、正交视角，无透视缩短和背景投影，便于比对尺度。光照只作用于人物，背景保持纯白；视图之间与画布四周留出干净空隙。

## 英文提示词骨架

替换方括号中的人物描述后交付，区域名与基准名只作为指令，不绘制在图内：

```text
Single character model sheet on ONE 16:9 landscape canvas. Plain pure white background (#FFFFFF) throughout. Arrange exactly two horizontal regions using whitespace only. NO dividing lines, panel borders, visible guide lines, letters, numbers, labels, captions or any other text anywhere in the image.

UPPER ONE-THIRD of the canvas height: exactly two facial close-ups, evenly spaced, from left to right: front view, then strict LEFT 90-degree profile with the nose pointing toward image left. Show the complete crown, hairstyle, ears and chin at the same scale. Both close-ups depict the SAME person with matching facial structure, age, features and hairstyle: [facial description, age, source-supported ethnicity, era and region]. LIGHTING IN THE UPPER REGION ONLY: consistent soft directional light with gentle ambient occlusion; keep the background pure white.

LOWER TWO-THIRDS of the canvas height: exactly three orthographic body views, evenly spaced, from left to right: FRONT VIEW WITHOUT THE HEAD; strict LEFT 90-DEGREE VIEW WITHOUT THE HEAD; BACK VIEW WITH THE COMPLETE HEAD. [Body, costume, material, footwear, fixed belongings and habitual posture.] The first two views retain the neck up to a clean, non-graphic design cut at chin-base height; omit the entire head, not just its facial features. The back view retains the complete head and matching hairstyle. Show the entire body and both feet in each view, with clear space around each silhouette. LIGHTING IN THE LOWER REGION: flat even orthographic lighting with no directional key and no cast shadows on the background.

FIVE ABSOLUTE ALIGNMENT REFERENCES, all invisible: FOOT-SOLE LINE: all three pairs of feet rest at exactly the same horizontal level. HIP LINE: the anatomical hip landmarks share the same horizontal level in all three views. SHOULDER LINE: the anatomical shoulder landmarks share the same horizontal level in all three views, preserving the character's established posture. NECK CUT PLANE AT CHIN-BASE HEIGHT: the front and left neck cut planes share one horizontal level matching the underside of the chin in the complete character's body scale; keep the back head intact. HEIGHT PROPORTIONS: use one identical body scale, torso length, limb lengths and original head-to-body ratio across all three views; only omit the heads in the first two, never enlarge their bodies to reach the back view's crown. No stretching, squashing or foreshortening. These are alignment instructions only; never draw the reference lines or their names. No additional detail strip or extra views.
```

## 文件名与报告

`render` 默认去 cast.json 同级的 `images/<slug>-sheet.png` 找图；图在别处时传入 `--images <目录>`。本 skill 不产生这些文件。下游出图后重新执行 `render`，报告会嵌入图片，角色列表缩略图截取上部左侧的正面特写。

`node scripts/novel-characters.mjs slug "<角色名>"` 生成安全文件名，中文会保留。
