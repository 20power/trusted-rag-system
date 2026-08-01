from __future__ import annotations

import json
from copy import deepcopy

import httpx

from app.core.config import Settings
from app.services.answering import _format_number, build_answer
from app.services.model_client import OpenAICompatibleChatClient
from app.services.retrieval import SearchHit


def _sheet_hit() -> SearchHit:
    return SearchHit(
        chunk_id="chunk-1",
        doc_id="NFRA-032",
        title="2025年9月全国各地区原保险保费收入情况表",
        source_file="032_2025年9月全国各地区原保险保费收入情况表.xlsx",
        locator="sheet:各地区数据（月度）!B4:G4",
        chunk_type="sheet_row",
        content="B4=全 国；C4=52145.77；D4=11250.32",
        score=12.0,
        metadata={
            "sheet": "各地区数据（月度）",
            "cells": [
                {"address": "B4", "row": 4, "column": 2, "value": "全 国"},
                {"address": "C4", "row": 4, "column": 3, "value": 52145.77},
                {"address": "D4", "row": 4, "column": 4, "value": 11250.32},
            ],
            "header_cells": [
                {"address": "C3", "row": 3, "column": 3, "value": "合计"},
                {"address": "D3", "row": 3, "column": 4, "value": "财产险"},
                {"address": "F2", "row": 2, "column": 6, "value": "单位：亿元"},
            ],
        },
    )


def _text_hit() -> SearchHit:
    return SearchHit(
        chunk_id="chunk-2",
        doc_id="NFRA-409",
        title="商业银行资本管理办法",
        source_file="附件13：账簿划分和名词解释.docx",
        locator="paragraph:6",
        chunk_type="paragraph",
        content="交易账簿包括为交易目的持有的金融工具、外汇和商品头寸。",
        score=9.0,
        metadata={"style": "Normal"},
    )


def test_table_question_returns_deterministic_cell_answer() -> None:
    result = build_answer(
        question="《2025年9月全国各地区原保险保费收入情况表》中，全国合计是多少？",
        hits=[_sheet_hit()],
        settings=Settings(app_env="test"),
    )

    assert result.status == "answered"
    assert result.answer_mode == "deterministic_table"
    assert "52145.77亿元" in result.answer
    assert "单元格：C4" in result.answer
    assert result.citations[0]["cell"] == "C4"


def test_financial_float_format_matches_two_decimal_reporting_precision() -> None:
    assert _format_number(275230.625444969) == "275230.63"
    assert _format_number(0.0223) == "0.0223"


def test_excel_choice_is_selected_directly_from_ranked_evidence() -> None:
    result = build_answer(
        question=(
            "哪一项是全 国？\n"
            "候选项：A. 全 国；B. 北京；C. 天津；D. 河北"
        ),
        hits=[_sheet_hit()],
        settings=Settings(app_env="test"),
    )

    assert result.answer_mode == "deterministic_choice"
    assert "A. 全 国" in result.answer


def test_excel_change_choice_is_calculated_from_same_row() -> None:
    result = build_answer(
        question=(
            "“全 国”从“合计”到“财产险”的数值变化约为多少？\n"
            "候选项：A. -40895.45；B. 40895.45；C. 52145.77；D. 11250.32"
        ),
        hits=[_sheet_hit()],
        settings=Settings(app_env="test"),
    )

    assert result.answer_mode == "deterministic_choice"
    assert "A. -40895.45" in result.answer


def test_excel_generic_period_change_uses_first_and_last_numeric_cells() -> None:
    hit = deepcopy(_sheet_hit())
    hit.content = "B4=全 国；C4=100；D4=120；E4=150；F4=180"
    hit.metadata["cells"] = [
        {"address": "B4", "row": 4, "column": 2, "value": "全 国"},
        {"address": "C4", "row": 4, "column": 3, "value": 100},
        {"address": "D4", "row": 4, "column": 4, "value": 120},
        {"address": "E4", "row": 4, "column": 5, "value": 150},
        {"address": "F4", "row": 4, "column": 6, "value": 180},
    ]

    result = build_answer(
        question=(
            "“全 国”从“年-季度”到“季度”的数值变化约为多少？\n"
            "候选项：A. 20；B. 50；C. 80；D. -80"
        ),
        hits=[hit],
        settings=Settings(app_env="test"),
    )

    assert result.answer_mode == "deterministic_choice"
    assert "C. 80" in result.answer


def test_excel_comparison_uses_target_column_across_all_candidates() -> None:
    hits = []
    for index, (label, value) in enumerate(
        [("全国合计", 800.0), ("北京", 50.0), ("天津", 30.0), ("公司本级", 2.0)],
        start=1,
    ):
        hit = deepcopy(_sheet_hit())
        hit.chunk_id = f"chunk-{index}"
        hit.content = f"B{index}={label}；G{index}={value}"
        hit.metadata["cells"] = [
            {"address": f"B{index}", "column": 2, "value": label},
            {"address": f"G{index}", "column": 7, "value": value},
        ]
        hit.metadata["header_cells"] = [
            {"address": "G3", "column": 7, "value": "健康险"}
        ]
        hits.append(hit)

    result = build_answer(
        question=(
            "在“健康险”口径下，以下哪一项数值最高？\n"
            "候选项：A. 全国合计；B. 北京；C. 天津；D. 公司本级"
        ),
        hits=hits,
        settings=Settings(app_env="test"),
    )

    assert result.answer_mode == "deterministic_choice"
    assert "A. 全国合计" in result.answer
    assert len(result.citations) == 4


def test_text_question_stays_evidence_only_without_model() -> None:
    result = build_answer(
        question="交易账簿包括什么？",
        hits=[_text_hit()],
        settings=Settings(app_env="test"),
    )

    assert result.status == "evidence_only"
    assert result.answer_mode == "evidence_only"


class _FakeModelClient:
    def __init__(self, response: str) -> None:
        self.response = response

    def complete(self, *, system_prompt: str, user_prompt: str) -> str:
        assert "只能使用" in system_prompt
        assert "paragraph:6" in user_prompt
        return self.response


def test_grounded_model_answer_requires_valid_citation() -> None:
    settings = Settings(
        app_env="test",
        llm_provider="local",
        llm_base_url="http://model.local/v1",
        llm_model="test-model",
    )
    result = build_answer(
        question="交易账簿包括什么？",
        hits=[_text_hit()],
        settings=settings,
        model_client=_FakeModelClient(
            '{"answer":"交易账簿包括为交易目的持有的金融工具、外汇和商品头寸。[1]",'
            '"citations":[1]}'
        ),
    )

    assert result.status == "answered"
    assert result.answer_mode == "grounded_model"
    assert result.citations[0]["evidence_index"] == 1


def test_valid_structured_citation_is_added_to_answer_when_marker_is_missing() -> None:
    settings = Settings(
        app_env="test",
        llm_provider="local",
        llm_base_url="http://model.local/v1",
        llm_model="test-model",
    )
    result = build_answer(
        question="交易账簿包括什么？",
        hits=[_text_hit()],
        settings=settings,
        model_client=_FakeModelClient(
            '{"answer":"交易账簿包括为交易目的持有的金融工具、外汇和商品头寸。",'
            '"citations":[1]}'
        ),
    )

    assert result.status == "answered"
    assert result.answer.endswith("[1]")
    assert result.warnings


def test_invalid_model_output_falls_back_to_evidence() -> None:
    settings = Settings(
        app_env="test",
        llm_provider="local",
        llm_base_url="http://model.local/v1",
        llm_model="test-model",
    )
    result = build_answer(
        question="交易账簿包括什么？",
        hits=[_text_hit()],
        settings=settings,
        model_client=_FakeModelClient('{"answer":"资本要求为99%。[1]","citations":[1]}'),
    )

    assert result.status == "evidence_only"
    assert result.answer_mode == "model_fallback"
    assert "不存在的数字" in result.warnings[0]


def test_openai_compatible_client_sends_expected_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer secret"
        payload = json.loads(request.content)
        assert payload["model"] == "local-model"
        assert payload["temperature"] == 0.0
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"answer":"ok","citations":[1]}'}}]},
        )

    settings = Settings(
        app_env="test",
        llm_provider="local",
        llm_base_url="http://model.local/v1",
        llm_api_key="secret",
        llm_model="local-model",
    )
    client = OpenAICompatibleChatClient(
        settings,
        transport=httpx.MockTransport(handler),
    )

    assert client.complete(system_prompt="system", user_prompt="user").startswith("{")
