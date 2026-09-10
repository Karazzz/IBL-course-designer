# schemas/ 结构化课程状态 Schema

四个 schema 与 skill 主文档第 5 节对应。所有 schema 允许扩展字段（`additionalProperties: true`），避免因新增需求阻塞设计。

| 文件 | 对象 | 用途 |
|---|---|---|
| `project_state.schema.json` | project_state | 项目级状态：各产物版本、确认状态、已完成内容、待确认事项 |
| `course_spec.schema.json` | course_spec | 整套课程 / 模块的权威设计规格 |
| `lesson_spec.schema.json` | lesson_spec | 单节课的权威设计规格 |
| `ppt_brief.schema.json` | ppt_brief | 从课程设计派生的 PPT 教学交接数据 |

## 关系

- `project_state` 登记 `course_spec` / `lesson_spec` / `ppt_brief` 的当前版本与确认状态，是跨轮次继续设计的入口；
- `lesson_spec` 通过 `course_id`、`objective_ref` 引用所属 `course_spec`；
- `ppt_brief` 必须记录来源（`course_spec` 或 `lesson_spec` 的 id 与版本），源更新后由本 Skill 判断是否重新派生；
- 教案、学案、PPT 等面向用户的成品是这些状态的派生物，不应反过来成为唯一课程状态。

## 约定

- 版本号建议 `v1`、`v1.1` 递增；已确认（confirmed）的内容不原位修改，改动即升版本并写 `changelog`；
- 用户未确认但已采用的暂定条件写入 `assumptions`；等待确认的事项登记到 `project_state.pending_confirmations`；
- 更新任何规格后，同步更新 `project_state` 的版本与确认状态。
