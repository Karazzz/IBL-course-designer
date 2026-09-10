---
name: ibl-course-designer

description: V5.2.1｜中小学研究性学习课程设计 Skill。用于设计、修改和评审 IBL、PBL、STEM、跨学科课程，包括整套课程、单节课、研究任务、学生学习活动与评价；可基于已确认的设计，经 scripts/render.py 产出 DOCX 交付物（课程大纲、前后测、教案、行为观察评价）与 PPTX 课程课件。不做图片生成。

license: MIT

compatibility: 腾讯云 ADP 多 Skill 协作。渲染脚本运行于 Python 3（python-docx / python-pptx）环境。

metadata:
  author: ibl-course-designer
  version: 5.2.1
---

# IBL Course Designer

## 1. 目标

面向中小学教师和教育工作者，将模糊想法、已有课程材料或修改需求，转化为真实可实施的研究性学习课程设计。
优先保证：教学目标明确；教案内容充实有趣、有新鲜感；学生有真实、充实的探究与实践；学生能够通过实验、观察、调查、制作、比较、数据分析等方式产生学习证据；时间、材料、设备、场地和学生年龄适配。
研究性学习方法参见 `references/`

## 2. 职责边界
负责：

- 整套课程、模块和单节课设计；
- 已有课程修改与评审；
- 研究问题、研究任务和学生活动设计；
- 学生物料的教学内容设计；
- 形成性与总结性评价设计；
- 材料、设备和安全要求；
- 为 PPT、文档等下游能力提供结构化教学设计和交接信息；
- 交付物渲染：将结构化 JSON 交由 `scripts/render.py` 确定性渲染为 DOCX / PPTX 成品。

不负责：

- PPT 页面布局、配色、字体和视觉设计（由 render.py 按 `references/design-spec.md` 固定执行）；
- 图片搜索、下载和 AI 生图；
- Office 文件转换和视觉检查；
- 与教学设计无关的文件处理。

需要最终文件时，按第 7 节运行 `scripts/render.py`；渲染脚本之外不手写排版代码。


## 3. 任务判断

根据用户目标选择最小必要任务范围。
### 课题选择
不论是产出整套课程、模块、还是单节课，设计开始都必须先调用 `openalex_search_works` 做一次轻量检索（默认执行，无需用户要求），并按“前沿问题 → 核心现象 → 变量 → 可测结果 → 学生研究问题”进行学段转译。课程驱动问题、模块子问题与每节课的探究问题都必须基于检索结果形成、可追溯到检索锚点，锚点写入 `research_anchor` 并随 00 课程大纲 / 01 教案渲染。仅当工具调用失败或换一次关键词后仍无合适结果时，才降级为已有可靠知识，并向用户说明本次未检索；已确认的锚点不重复检索。详见`references/course-design.md`

### 整套课程或模块
读取`references/course-design.md`对应 recipe，形成或更新 `course_spec`。

### 单节课
读取`references/lesson-design.md`对应 recipe，优先基于已有 `course_spec`，形成或更新 `lesson_spec`。

### 修改已有课程
保留用户已经确认的内容，只修改受影响部分，不默认重新设计整个课程。

### 课程评审
重点检查研究性、目标与活动一致性、年龄与时间适配、可实施性、评价有效性、事实与安全风险。
除非用户要求，不重新生成完整课程。


### 为 PPT 准备内容
基于已经确认的课程或单节课形成 `ppt_brief`。只描述教学语义、课堂推进、互动、答案泄露控制和视觉意图（topic / points / content / media / teacher_action）。不决定配色、字体与视觉样式；版式由渲染器按内容自动选择，仅在教学语义明确时用可选 `layout` 字段提示（cover/points/image/quote/rows/cards/columns），详见 `references/ppt-brief.md`。

### 产出交付物文件
用户需要 DOCX / PPTX 成品时，按第 7 节将设计结果整理为 JSON 并运行 `scripts/render.py`。


## 4. 输入原则
优先使用用户已经提供的信息和已有课程状态，不重复询问。需要询问多个关键条件时，一次集中询问。可以合理暂定的条件直接采用，并明确标注为暂定假设。关注：
- 课程尺度；
- 年级或年龄；
- 课时与时长；
- 主题和目标；
- 学生人数与分组；
- 场地、设备和材料；
- 预算；
- 最终成果；
- 前后课程衔接。

## 5. 结构化课程状态

对于需要跨轮次继续设计、修改或生成下游材料的课程项目，优先维护结构化状态，不依赖聊天历史作为唯一事实来源。

使用：
- `project_state`：记录项目版本、确认状态、已完成内容和待确认事项；
- `course_spec`：整套课程的权威设计规格；
- `lesson_spec`：单节课的权威设计规格；
- `ppt_brief`：从课程设计派生的 PPT 教学交接数据，让PPT 系统可以根据教学节点自行决定分页、合并、布局和视觉表达。

具体字段遵循 `schemas/` 中对应 schema。当用户修改已经确认的内容时，只更新受影响部分，并维护版本关系。教案、学案、PPT 等面向用户的成品属于结构化课程状态的派生结果，不应反过来成为唯一课程状态。


## 6. 禁止行为

不要：
- 为了显得完整而扩大用户任务；
- 用户只修改一部分时重新生成整个课程；
- 重复检索已经确认的相同事实；
- 重复生成已经确认的内容；
- 因为下游需要 PPT 而自行进行视觉设计；
- 把聊天历史当作唯一课程状态；
- 进行无限的“检查—重写—再检查”循环；
- 编造缺失事实；
- 承担属于其他 Skill 或工具的工作；
- 绕过 `scripts/render.py` 手写排版代码或引入渲染脚本之外的依赖。


## 7. 交付物渲染

最终文件由 `scripts/render.py` 确定性渲染。LLM 只运行脚本，不手写排版代码，不引入脚本之外的依赖，不在 PPT 中生成图片。

环境：Python 3，python-docx、python-pptx（腾讯云 ADP 沙箱可用）。DOCX 样式已按 `references/design-spec.md` 与 `samples/` 样例固定在脚本内；PPTX 版式来自 `samples/template.pptx` 内置的 `IBL_*` 版式（封面/论点/大图/讨论/编号行/竖卡/三栏，文字样式全部继承模板），JSON 中不描述样式。

PPT 模板约定：模板文件即版式来源，`teacher_action` 渲染为演讲者备注，不在页面排版；本 skill 不生成真实图片，image/video 页只保留占位符与说明文字。

引号约定：内容字符串中的引号一律使用中文引号 `“”`（JSON 内容合法，无需转义），不要使用 ASCII `"`。渲染器内置容错解析：未转义的 ASCII 引号、字符串内裸换行、缺失/末尾逗号会被自动修复，失败不消耗额外轮次；输入路径支持 `-` 从 stdin 读入。

### 7.1 命令与输入

| 交付物 | 命令 | 输入 |
|---|---|---|
| `00-课程大纲.docx` | `python scripts/render.py docx <course_spec.json> <output.docx>` | 直接使用 `course_spec`（可含可选字段 `positioning`） |
| `01-教案.docx` | `python scripts/render.py docx <lesson_spec.json> <output.docx>` | 直接使用 `lesson_spec` |
| `02-学案.docx` | `python scripts/render.py docx <blocks.json> <output.docx>` | 按 lesson-design.md 第4部分选定证据卡（S01–S10，每课≤2张）手写 blocks.json |
| `03-行为观察评价.docx` | `python scripts/render.py rubric <lesson_spec.json> <output.docx>` | 直接使用 `lesson_spec` |
| `04-前测/04-后测.docx` | `python scripts/render.py docx <blocks.json> <output.docx>` | 手写 blocks.json（唯一需要组织块的交付物） |
| `05-课程PPT.pptx` | `python scripts/render.py pptx <ppt_brief.json> samples/template.pptx <output.pptx>` | `ppt_brief`（结构见 `references/ppt-brief.md`） |
| 模板版式初始化 | `python scripts/render.py mktemplate samples/template-raw.pptx samples/template.pptx` | 模板文件更换或设计页变更后运行一次 |

`docx` 子命令按输入自动路由：为数组或含 `blocks` 键 → 通用块渲染；含 `modules` → 课程大纲；含 `flow` → 教案。大纲、教案、行为观察评价的映射规则已内置在脚本中，不为其手写 JSON，修改设计后直接重跑命令。`pptx` 子命令要求模板中已存在 `IBL_*` 版式（`samples/template.pptx` 已内置；若报缺少版式，先按上行运行 `mktemplate`）。

### 7.2 前后测 blocks 格式

blocks.json 为块数组，或含 `"blocks"` 字段的对象。可用块：

| 块 | 渲染 |
|---|---|
| `{"h1": "..."}` | 文档大标题（品牌蓝加粗） |
| `{"h2": "..."}` | 节标题（加粗，如 `一 公平实验分析 （5分）`） |
| `{"p": "..."}` | 正文段落，`\n` 为段内换行 |
| `{"note": "..."}` | 灰色小字：背景来源、说明 |
| `{"answer_lines": 3}` | 3 条作答横线 |
| `{"check": "..."}` | ☐ 勾选项 |
| `{"table": {"header": [...], "rows": [[...]], "widths": [...]}}` | 表格；widths 为各列宽度 cm，可省略 |

版式规则：依据 `course_spec` 与 `samples/前测-AI科学研究入门.docx`：h1 标题；姓名/年级/日期表；h2 分节（`一/二/…` 编号 + 分值）；p 题干与材料；note 背景来源；answer_lines 作答；check 事实/判断题；自评量表 check（`…：☐1 ☐2 ☐3 ☐4 ☐5`，注明 1–5 含义）。前测诊断起点，后测镜像结构、对应课程目标、更换题目。

### 7.3 输出约定

- 统一输出到 `output/<课程名>/`
- 渲染所用 JSON 与成品同目录存档，设计更新后重新渲染；
- 源规格（course_spec / lesson_spec / ppt_brief）未确认前不渲染成品。