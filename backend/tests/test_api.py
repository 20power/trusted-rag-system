from fastapi.testclient import TestClient

from app.main import app


def test_health_endpoint() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_question_endpoint_refuses_when_no_evidence_exists() -> None:
    with TestClient(app) as client:
        response = client.post("/api/v1/questions/ask", json={"question": "测试问题"})

    assert response.status_code == 200
    assert response.json()["status"] == "no_evidence"
