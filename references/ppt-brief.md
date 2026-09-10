# 为 PPT 准备内容 Recipe（ppt_brief）

## 适用场景
根据 lesson_spec 生成课堂 PPT 的内容简报，交由 `scripts/render.py pptx` 依据 `samples/template.pptx` 的 IBL_* 版式渲染成品。
必须基于已确认的 `course_spec` / `lesson_spec` 派生，并记录来源 id 与版本；源规格未确认时，先完成课程设计的确认；源规格更新后，评估 `ppt_brief` 是否需要重新派生，并更新 `project_state` 的版本关系。

ppt_brief 只描述：
- 这一页的教学主题（`topic`）；
- 学生应该看到的内容（`points` 结构化要点，或 `content` 整段文本由渲染器切分）；
- 是否需要图片或视频（`media`）；
- 教师如何使用这一页推进课堂（`teacher_action`，渲染为演讲者备注）。

不负责配色、字体、动画和具体视觉设计；版式由渲染器按内容自动选择，仅在语义明确时用 `layout` 给出提示。

## 生成原则
1. PPT 服务于课堂推进，不是 lesson_spec 的全文搬运。
2. 一个 brief item 表示一个明确的教学节拍，原则上对应一页 PPT。
3. 需要"先思考、后揭晓"的内容必须拆成不同 item，不得提前展示答案。
4. `points` 优先于 `content`：能结构化就给结构化要点（title/detail/badge）；`content` 只在内容确为连贯段落时使用，渲染器按行和句读切分为 ≤3 个要点。
5. `teacher_action` 描述教师在这一页做什么（提问、追问、组织讨论、揭示答案、总结、布置任务），放映时学生不可见。
6. 媒体类型仅使用 `image`、`video` 或 `none`；需要媒体时描述内容本身，不规定图库、文件或视觉风格。本 skill 不生成真实图片，渲染后占位符留空待插入。当 `media.type` 为 `video` 时，`description` 除描述画面内容外，还应写明教师需查找的视频主题与中英文检索关键词建议，渲染为占位说明文字供教师检索使用。
7. `layout` 是可选提示，仅在自动选择不符合教学意图时使用。
8. 渲染器可以优化版式和视觉表达，但不得改变教学顺序、提前泄露答案或改变核心教学意图。
9. 按 `schemas/ppt_brief.schema.json` 生成 `ppt_brief`，登记到 `project_state`。

## 版式与自动选择
| layout | 版式 | 适合内容 | 自动选择条件（无 layout 提示时） |
|---|---|---|---|
| `cover` | 封面（标题/副标题） | 课题封面 | 第 1 页 |
| `points` | 左主面板 + 右侧三行论点 | 1 个核心观点 + 至多 3 个支撑点（points 第 1 条进主面板） | ≥4 个要点（与 rows 交替）/ 缺省 |
| `rows` | 左大卡 + 右侧 01–03 编号行 | 同 points，节奏交替 | ≥4 个要点（与 points 交替） |
| `image` | 整页大图 + 说明 | 图片/视频页 | `media.type` 为 image/video |
| `quote` | 左右观点面板 + 中部图片与小结 | 两方观点对照、讨论、辨析 | 恰好 2 个要点 |
| `cards` | 三竖卡（圆形徽标 + 标题 + 说明） | 3 个并列短要点 | 恰好 3 个要点（均无 detail） |
| `columns` | 横幅导语 + 三栏（标题 + 详情） | 3 个并列要点带说明 | 恰好 3 个要点（含 detail） |

要点数量映射：`points` 版/`rows` 版用前 4 条（第 1 条 = 主观点）；`cards`/`columns` 版取前 3 条；`quote` 版取前 2 条。

## slides 例子

```json
{
  "lesson_spec_ref": "L03-相关与因果",
  "subtitle": "AI 科学研究入门 · 第 3 课",
  "slides": [
    {
      "topic": "相关不等于因果",
      "layout": "cover",
      "subtitle": "冰淇淋与溺水：一个反直觉的统计现象",
      "teacher_action": "开场抛出课题，说明本课将用真实数据做一次因果排查。"
    },
    {
      "topic": "一个奇怪的现象",
      "content": "统计数据表明，城市冰淇淋销量上升时，溺水事故同步上升。吃冰淇淋会导致溺水吗？",
      "media": { "type": "image", "description": "小孩拿着冰淇淋站在泳池旁，同时联想到夏天、冰淇淋和游泳" },
      "teacher_action": "提出反直觉问题，暂不公布答案；邀请学生提出解释并追问共同因素。"
    },
    {
      "topic": "可能的解释",
      "points": [
        { "title": "气温是共同变量", "detail": "夏天气温升高，冰淇淋销量与玩水人数同时增加。", "badge": "气温" },
        { "title": "相关 ≠ 因果", "detail": "两件事同步变化，不代表一件导致另一件。" },
        { "title": "警惕第三变量", "detail": "找“A 同时导致 B 和 C”的更多例子。" }
      ],
      "teacher_action": "揭示共同变量，回应提出类似解释的学生；布置寻找反例任务。"
    },
    {
      "topic": "课堂讨论",
      "points": [
        { "detail": "正方：数据显示相关就足够指导行动。" },
        { "detail": "反方：没有因果机制的相关不可靠。" }
      ],
      "subtitle": "相关性能否指导决策？",
      "teacher_action": "组织两方辩论，追问各自的证据与机制。"
    }
  ]
}
```
