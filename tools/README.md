# 原生 Office 文件生成器

`render_office.py` 把紧凑 JSON 渲染为原生 DOCX 和 PPTX。模型只生成教学内容，不生成排版代码、HTML 或 OOXML。

## 安装

```bash
python -m pip install -r tools/requirements.txt
```

## 使用

```bash
python tools/render_office.py tools/example-kit.json --output-dir output
```

常用参数：

- `--only all|docx|pptx`：选择输出类型，默认 `all`；
- `--build-mode live`：把 3 个要点自动展开为 `1`、`1+2`、`1+2+3` 三张实际幻灯片；
- `--build-mode final`：每个逻辑页只输出最终完整状态，适合讲义；
- `--pdf`：调用环境中的 LibreOffice/soffice 把 DOCX 转为 PDF，不经 HTML。

输入字段见 `example-kit.json`。课件坐标、字体、颜色、备注区、累积构建页和文档表格均由脚本处理。每次只需替换 JSON 中的课程内容。

文档章节还支持来源卡和加权题目：

```json
{
  "title": "检索与前测",
  "sources": [{
    "title": "来源标题", "publisher": "发布方", "url": "https://...",
    "date": "2022", "accessed": "2026-08-11",
    "key_points": "关键信息", "application": "本课如何采用",
    "caveat": "限制", "license": "使用条件"
  }],
  "questions": [{
    "prompt": "题干",
    "options": [
      {"label": "A", "text": "选项", "score": 2, "level": "需关注", "rationale": "理由"},
      {"label": "B", "text": "选项", "score": 4, "level": "优秀", "rationale": "理由"},
      {"label": "C", "text": "选项", "score": 2, "level": "需关注", "rationale": "理由"},
      {"label": "D", "text": "选项", "score": 1, "level": "明显不足", "rationale": "理由"}
    ]
  }]
}
```

`audience: "student"` 会自动隐藏题目分值和解析；`audience: "teacher"` 会显示完整评分依据。

## 依赖与许可

- [python-pptx](https://github.com/scanny/python-pptx)，MIT；
- [python-docx](https://github.com/python-openxml/python-docx)，MIT；
- 可选 [LibreOffice](https://www.libreoffice.org/)，仅用于本地 PDF 转换。

这些依赖未复制进 Skill ZIP，运行环境需按 `requirements.txt` 安装。
