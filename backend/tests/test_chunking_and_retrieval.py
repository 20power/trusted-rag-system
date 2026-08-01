from __future__ import annotations

import json
from pathlib import Path

from app.db.models import Document
from app.services.evaluation import EvaluationCase, _match_option, evaluate_retrieval
from app.services.indexing import index_document
from app.services.retrieval import (
    SearchHit,
    _requested_extensions,
    _round_robin_documents,
    _score,
    search_chunks,
)


def _document(artifact_path: Path) -> Document:
    return Document(
        doc_id="NFRA-TEST-001",
        source_title="2023年4季度保险业资金运用情况表",
        original_filename="2023年四季度保险业资金运用情况表.xlsx",
        relative_path="sample.xlsx",
        source_path=str(artifact_path.with_suffix(".xlsx")),
        extension=".xlsx",
        mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        file_signature="zip-ooxml",
        size_bytes=128,
        sha256="a" * 64,
        sequence_no=1,
        year_hint=2023,
        ingest_status="parsed",
        parsed_artifact_path=str(artifact_path),
    )


def test_spreadsheet_rows_are_searchable_with_cell_evidence(db, tmp_path: Path) -> None:
    artifact = tmp_path / "parsed.json"
    artifact.write_text(
        json.dumps(
            {
                "content": {
                    "text_blocks": [],
                    "tables": [],
                    "workbook": {
                        "sheets": [
                            {
                                "name": "2023年4季度保险资金运用情况表",
                                "cells": [
                                    {"address": "A1", "row": 1, "column": 1, "value": "项目"},
                                    {
                                        "address": "B1",
                                        "row": 1,
                                        "column": 2,
                                        "value": "账面余额",
                                    },
                                    {
                                        "address": "A6",
                                        "row": 6,
                                        "column": 1,
                                        "value": "资金运用余额",
                                    },
                                    {
                                        "address": "B6",
                                        "row": 6,
                                        "column": 2,
                                        "value": 281573.61,
                                    },
                                ],
                            }
                        ]
                    },
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    document = _document(artifact)
    db.add(document)
    db.commit()

    count = index_document(document, db)
    hits = search_chunks(
        db,
        (
            "根据 Excel 附件《2023年4季度保险业资金运用情况表》，"
            "资金运用余额在截至当期账面余额口径下是多少？"
        ),
        top_k=3,
    )

    assert count == 2
    assert hits
    assert hits[0].doc_id == document.doc_id
    assert hits[0].locator == "sheet:2023年4季度保险资金运用情况表!A6:B6"
    assert "B6=281573.61" in hits[0].content

    report = evaluate_retrieval(
        db,
        [
            EvaluationCase(
                question_id="Q009",
                source_type="excel",
                question=(
                    "根据 Excel 附件《2023年4季度保险业资金运用情况表》，"
                    "资金运用余额在截至当期账面余额口径下是多少？"
                ),
                retrieval_query=(
                    "根据 Excel 附件《2023年4季度保险业资金运用情况表》，"
                    "资金运用余额在截至当期账面余额口径下是多少？"
                ),
                source_title="2023年4季度保险业资金运用情况表",
                expected_sheet="2023年4季度保险资金运用情况表",
                expected_cell="B6",
                expected_text=None,
            )
        ],
        top_k=3,
    )
    assert report["document_recall_at_k"] == 1.0
    assert report["evidence_recall_at_k"] == 1.0
    assert report["evidence_mrr"] == 1.0


def test_choice_option_matching_supports_numeric_and_text_answers() -> None:
    assert _match_option("正确选项是 B。[1]", {"A": "甲", "B": "乙"}) == "B"
    assert (
        _match_option(
            "目标数值为 31739.18 亿元。[1]",
            {"A": "31739.18", "B": "6428.56", "C": "24912.73", "D": "397.89"},
        )
        == "A"
    )
    assert (
        _match_option(
            "交易账簿包括为交易目的持有的金融工具、外汇和商品头寸。[1]",
            {
                "A": "仅包括贷款",
                "B": "为交易目的持有的金融工具、外汇和商品头寸",
                "C": "仅包括存款",
                "D": "以上均不属于",
            },
        )
        == "B"
    )


def test_explicit_attachment_type_maps_to_source_extensions() -> None:
    assert _requested_extensions("根据 PDF 附件《测试制度》回答") == (".pdf",)
    assert _requested_extensions("根据 Excel 附件《测试表》取数") == (
        ".xls",
        ".xlsx",
    )
    assert _requested_extensions("根据 Word 附件《测试制度》回答") == (
        ".doc",
        ".docx",
    )
    assert _requested_extensions("根据《测试制度》回答") is None


def test_requested_title_similarity_outweighs_nearby_wrong_document() -> None:
    question = "根据《中资商业银行行政许可事项申请材料目录及格式要求（2023年版）》回答"
    correct = _score(
        question,
        title="附件：中资商业银行行政许可事项申请材料目录及格式要求（2023年）.pdf",
        search_text="申请材料目录",
        content="申请材料目录",
        requested_title="中资商业银行行政许可事项申请材料目录及格式要求（2023年版）",
    )
    wrong = _score(
        question,
        title="非银行金融机构行政许可事项申请材料目录及格式要求（2021年版）.doc",
        search_text="申请材料目录",
        content="申请材料目录",
        requested_title="中资商业银行行政许可事项申请材料目录及格式要求（2023年版）",
    )

    assert correct > wrong + 5


def test_duplicate_candidate_phrases_do_not_accumulate_score() -> None:
    base_question = "关于《测试制度》，下列哪项正确？"
    candidate = "候选表述：监管机构应当保存完整证据链。"
    duplicated = f"{candidate}；监管机构应当保存完整证据链。"
    parameters = {
        "title": "测试制度",
        "search_text": "监管机构应当保存完整证据链。",
        "content": "监管机构应当保存完整证据链。",
        "requested_title": "测试制度",
    }

    single_score = _score(f"{base_question}\n{candidate}", **parameters)
    duplicate_score = _score(f"{base_question}\n{duplicated}", **parameters)

    assert abs(duplicate_score - single_score) < 1


def test_candidate_evidence_is_balanced_across_documents() -> None:
    def hit(chunk_id: str, doc_id: str, score: float) -> SearchHit:
        return SearchHit(
            chunk_id=chunk_id,
            doc_id=doc_id,
            title=doc_id,
            source_file=f"{doc_id}.pdf",
            locator=chunk_id,
            chunk_type="page",
            content=chunk_id,
            score=score,
            metadata={},
        )

    balanced = _round_robin_documents(
        [
            hit("a1", "doc-a", 10),
            hit("a2", "doc-a", 9),
            hit("a3", "doc-a", 8),
            hit("b1", "doc-b", 7),
            hit("b2", "doc-b", 6),
        ],
        limit=3,
    )

    assert [item.chunk_id for item in balanced] == ["a1", "b1", "a2"]
