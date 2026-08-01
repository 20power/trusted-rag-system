from __future__ import annotations

import json
from urllib.request import Request, urlopen

BASE_URL = "http://127.0.0.1:8000/api/v1"


def request_json(path: str, payload: dict[str, object] | None = None) -> dict:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(f"{BASE_URL}{path}", data=data, headers=headers)
    with urlopen(request, timeout=600) as response:
        return json.loads(response.read().decode("utf-8"))


health = request_json("/health")
questions = [
    (
        "excel",
        "lexical_policy",
        "根据《2023年10月全国各地区原保险保费收入情况表》，"
        "全国合计在合计口径下的数值是多少？",
    ),
    (
        "word",
        "hybrid",
        "根据《商业银行资本管理办法》，交易账簿包括什么？",
    ),
]
results = {}
for label, expected_retrieval_mode, question in questions:
    result = request_json(
        "/questions/ask",
        {"question": question, "top_k": 5},
    )
    if result.get("retrieval_mode") != expected_retrieval_mode:
        raise RuntimeError(
            f"{label} 检索路由异常，期望 {expected_retrieval_mode}：{result}"
        )
    if not result.get("evidence"):
        raise RuntimeError(f"{label} 未返回证据：{result}")
    first_evidence = result["evidence"][0]
    results[label] = {
        "status": result.get("status"),
        "answer_mode": result.get("answer_mode"),
        "retrieval_mode": result.get("retrieval_mode"),
        "answer": result.get("answer"),
        "first_evidence": {
            "source_file": first_evidence.get("source_file"),
            "locator": first_evidence.get("locator"),
            "content": first_evidence.get("content"),
        },
        "citations": result.get("citations"),
        "warnings": result.get("warnings"),
    }

print(json.dumps({"health": health, "results": results}, ensure_ascii=False, indent=2))
