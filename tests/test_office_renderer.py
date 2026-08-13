from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from render_office import RenderError, expand_slides, load_payload, render, validate_payload  # noqa: E402


class OfficeRendererTests(unittest.TestCase):
    def setUp(self) -> None:
        self.example_path = ROOT / "tools" / "example-kit.json"
        self.payload = load_payload(self.example_path)

    def test_example_payload_is_valid(self) -> None:
        validate_payload(self.payload)

    def test_live_build_expands_cumulative_bullets(self) -> None:
        slides = self.payload["presentation"]["slides"]
        expanded = expand_slides(slides, "live")
        self.assertEqual(len(expanded), 5)
        build_states = [slide for slide in expanded if slide["type"] == "bullets"]
        self.assertEqual([len(slide["bullets"]) for slide in build_states], [1, 2, 3])
        self.assertEqual([slide["_build_step"] for slide in build_states], [1, 2, 3])

    def test_final_build_keeps_one_complete_slide(self) -> None:
        slides = self.payload["presentation"]["slides"]
        expanded = expand_slides(slides, "final")
        self.assertEqual(len(expanded), 3)
        self.assertEqual(expanded[1]["bullets"], slides[1]["bullets"])

    def test_more_than_three_bullets_is_rejected(self) -> None:
        payload = json.loads(json.dumps(self.payload))
        payload["presentation"]["slides"][1]["bullets"].append("第四个要点")
        with self.assertRaisesRegex(RenderError, "超过 3 个要点"):
            validate_payload(payload)

    def test_weighted_question_requires_one_best_option(self) -> None:
        payload = json.loads(json.dumps(self.payload))
        payload["documents"][0]["sections"].append(
            {
                "title": "前测",
                "questions": [
                    {
                        "prompt": "哪一项是自变量？",
                        "options": [
                            {"label": "A", "text": "保持不变的因素", "score": 2},
                            {"label": "B", "text": "主动改变的因素", "score": 4},
                            {"label": "C", "text": "测量结果", "score": 2},
                            {"label": "D", "text": "测量工具", "score": 1}
                        ]
                    }
                ]
            }
        )
        validate_payload(payload)
        payload["documents"][0]["sections"][-1]["questions"][0]["options"][0]["score"] = 4
        with self.assertRaisesRegex(RenderError, "只能有一个 4 分选项"):
            validate_payload(payload)

    @unittest.skipUnless(
        importlib.util.find_spec("docx") and importlib.util.find_spec("pptx"),
        "Office renderer dependencies are not installed",
    )
    def test_example_renders_native_office_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            payload = json.loads(json.dumps(self.payload))
            payload["documents"][0]["sections"].append(
                {
                    "title": "来源与评分示例",
                    "sources": [
                        {
                            "title": "python-docx documentation",
                            "publisher": "python-docx",
                            "url": "https://python-docx.readthedocs.io/en/latest/",
                            "key_points": "生成原生 DOCX",
                            "application": "用于文件渲染"
                        }
                    ],
                    "questions": [
                        {
                            "prompt": "哪一项是自变量？",
                            "options": [
                                {"label": "A", "text": "保持不变的因素", "score": 2},
                                {"label": "B", "text": "主动改变的因素", "score": 4},
                                {"label": "C", "text": "测量结果", "score": 2},
                                {"label": "D", "text": "测量工具", "score": 1}
                            ]
                        }
                    ]
                }
            )
            outputs = render(payload, Path(directory), build_mode="live")
            self.assertEqual({path.suffix for path in outputs}, {".docx", ".pptx"})
            for path in outputs:
                self.assertTrue(path.is_file())
                with zipfile.ZipFile(path) as archive:
                    self.assertIn("[Content_Types].xml", archive.namelist())
            pptx_path = next(path for path in outputs if path.suffix == ".pptx")
            with zipfile.ZipFile(pptx_path) as archive:
                slides = [
                    name
                    for name in archive.namelist()
                    if name.startswith("ppt/slides/slide") and name.endswith(".xml")
                ]
                self.assertEqual(len(slides), 5)
                self.assertTrue(any(name.startswith("ppt/notesSlides/") for name in archive.namelist()))

    @unittest.skipUnless(
        importlib.util.find_spec("docx") and importlib.util.find_spec("pptx"),
        "Office renderer dependencies are not installed",
    )
    def test_student_document_hides_option_scores_and_rationales(self) -> None:
        payload = {
            "schema_version": 1,
            "documents": [
                {
                    "filename": "前测.docx",
                    "title": "前测",
                    "audience": "student",
                    "sections": [
                        {
                            "title": "选择题",
                            "questions": [
                                {
                                    "prompt": "哪一项是自变量？",
                                    "options": [
                                        {"label": "A", "text": "保持不变", "score": 2, "rationale": "控制变量"},
                                        {"label": "B", "text": "主动改变", "score": 4, "rationale": "最佳答案"},
                                        {"label": "C", "text": "测量结果", "score": 2, "rationale": "因变量"},
                                        {"label": "D", "text": "测量工具", "score": 1, "rationale": "无关概念"}
                                    ]
                                }
                            ]
                        }
                    ]
                }
            ]
        }
        with tempfile.TemporaryDirectory() as directory:
            output = render(payload, Path(directory), only="docx")[0]
            with zipfile.ZipFile(output) as archive:
                document_xml = archive.read("word/document.xml").decode("utf-8")
            self.assertIn("主动改变", document_xml)
            self.assertNotIn("4 分", document_xml)
            self.assertNotIn("最佳答案", document_xml)


if __name__ == "__main__":
    unittest.main()
