"""Deterministic application boundaries; no simulated model claimed as real integration."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from edu_support import storage
from edu_support.agent import task_control
from edu_support.knowledge import KeywordSearch
from edu_support.main import app, tokens
from edu_support.mcp_tools import identity, issue_capability, require_intent


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", str(tmp_path / "test.sqlite"))
    storage.init()
    # Do not start real network/recovery workers for boundary tests.
    c = TestClient(app)
    yield c
    c.close()


def auth(role="student", user_id=161):
    return {
        "Authorization": "Bearer " + tokens.dumps({"role": role, "user_id": user_id})
    }


def test_cross_student_conversation_isolation(client):
    created = client.post("/api/v1/conversations", headers=auth()).json()
    assert (
        client.get("/api/v1/conversations/" + created["id"], headers=auth()).status_code
        == 200
    )
    assert (
        client.get(
            "/api/v1/conversations/" + created["id"], headers=auth(user_id=162)
        ).status_code
        == 404
    )
    assert client.get("/api/v1/conversations", headers=auth(user_id=162)).json() == []


def test_admin_routes_reject_student_and_missing_auth(client):
    for path in [
        "/api/v1/admin/knowledge",
        "/api/v1/admin/audit",
        "/api/v1/admin/education/orders",
    ]:
        assert client.get(path).status_code == 401
        assert client.get(path, headers=auth()).status_code == 403


def test_knowledge_publish_offline_and_version_conflict(client):
    headers = auth("admin")
    body = {
        "kind": "faq",
        "title": "专属测试政策ZXQ",
        "body": "测试专属说明",
        "status": "draft",
    }
    created = client.post("/api/v1/admin/knowledge", headers=headers, json=body).json()
    assert not KeywordSearch().search("ZXQ")
    body.update(version=1, status="published")
    assert (
        client.put(
            "/api/v1/admin/knowledge/" + created["id"], headers=headers, json=body
        ).status_code
        == 200
    )
    assert KeywordSearch().search("ZXQ")[0]["version"] == 2
    assert (
        client.put(
            "/api/v1/admin/knowledge/" + created["id"], headers=headers, json=body
        ).status_code
        == 409
    )
    body.update(version=2, status="offline")
    assert (
        client.put(
            "/api/v1/admin/knowledge/" + created["id"], headers=headers, json=body
        ).status_code
        == 200
    )
    assert not KeywordSearch().search("ZXQ")


def test_tasks_switch_resume_cancel_persist(client):
    cid = client.post("/api/v1/conversations", headers=auth()).json()["id"]
    task_control(
        cid,
        "source-1",
        {"action": "activate", "kind": "refund", "slots": {"reason": "没时间"}},
    )
    task_control(cid, "source-2", {"action": "activate", "kind": "query", "slots": {}})
    assert storage.one("SELECT * FROM tasks WHERE kind='refund'")["status"] == "paused"
    task_control(cid, "source-3", {"action": "resume", "kind": "refund", "slots": {}})
    assert "没时间" in storage.one("SELECT * FROM tasks WHERE kind='refund'")["slots"]
    task_control(cid, "source-4", {"action": "cancel", "kind": "refund", "slots": {}})
    assert (
        storage.one("SELECT * FROM tasks WHERE kind='refund'")["status"] == "cancelled"
    )
    assert client.get("/api/v1/conversations/" + cid, headers=auth()).json()["tasks"]


def test_mcp_capability_and_missing_write_intent(client):
    cid = client.post("/api/v1/conversations", headers=auth()).json()["id"]
    run_id = uuid4().hex
    storage.execute(
        "INSERT INTO runs VALUES (?,?,?,?,?,?,?)",
        (
            run_id,
            cid,
            "request-000",
            "查询政策",
            "completed",
            storage.now(),
            storage.now(),
        ),
    )
    capability = issue_capability(161, run_id)
    assert identity(capability)["user_id"] == 161
    with pytest.raises(ValueError):
        identity(capability + "corrupted")
    with pytest.raises(ValueError):
        require_intent(capability, "refund")


def test_request_dedup_and_payload_conflict(client):
    cid = client.post("/api/v1/conversations", headers=auth()).json()["id"]
    storage.execute(
        "INSERT INTO runs VALUES (?,?,?,?,?,?,?)",
        (
            "old-run",
            cid,
            "same-request",
            "查订单",
            "completed",
            storage.now(),
            storage.now(),
        ),
    )
    response = client.post(
        "/api/v1/conversations/" + cid + "/messages",
        headers=auth(),
        json={"request_id": "same-request", "content": "查订单"},
    )
    assert response.json()["run_id"] == "old-run"
    response = client.post(
        "/api/v1/conversations/" + cid + "/messages",
        headers=auth(),
        json={"request_id": "same-request", "content": "我要退款"},
    )
    assert response.status_code == 409


def test_internal_closure_rejected(client):
    response = client.post(
        "/api/v1/admin/tickets/1/messages",
        headers=auth("admin"),
        json={
            "content": "完成",
            "internal": True,
            "close": True,
            "operation_id": uuid4().hex,
        },
    )
    assert response.status_code == 400


def test_completed_query_restores_paused_task(client):
    cid = client.post("/api/v1/conversations", headers=auth()).json()["id"]
    task_control(
        cid,
        "refund-source",
        {"action": "activate", "kind": "refund", "slots": {"reason": "个人原因"}},
    )
    task_control(
        cid, "query-source", {"action": "activate", "kind": "query", "slots": {}}
    )
    result = task_control(
        cid, "query-source", {"action": "complete", "kind": "query", "slots": {}}
    )
    assert result["resumed"]["kind"] == "refund"
    assert storage.one("SELECT * FROM tasks WHERE kind='refund'")["status"] == "active"


def test_event_replay_is_owned_and_cursor_based(client):
    cid = client.post("/api/v1/conversations", headers=auth()).json()["id"]
    run_id = uuid4().hex
    storage.execute(
        "INSERT INTO runs VALUES (?,?,?,?,?,?,?)",
        (
            run_id,
            cid,
            "events-000",
            "查订单",
            "completed",
            storage.now(),
            storage.now(),
        ),
    )
    first = storage.event(run_id, "delta", {"text": "一"})
    storage.event(run_id, "done", {"text": "一二"})
    path = f"/api/v1/runs/{run_id}/events"
    assert client.get(path, headers=auth(user_id=162)).status_code == 404
    response = client.get(path + f"?after={first}", headers=auth())
    assert "event: done" in response.text and "event: delta" not in response.text


def test_business_object_retry_uses_original_request_not_mutable_business_state(client):
    import json

    cid = client.post("/api/v1/conversations", headers=auth()).json()["id"]
    request = {
        "content": "查这个订单",
        "request_id": "object-request-001",
        "business_object": {"kind": "order", "id": 1},
    }
    run_id = uuid4().hex
    storage.execute(
        "INSERT INTO runs VALUES (?,?,?,?,?,?,?)",
        (
            run_id,
            cid,
            request["request_id"],
            "原先保存的业务状态",
            "completed",
            storage.now(),
            storage.now(),
        ),
    )
    storage.execute(
        "INSERT INTO request_payloads VALUES (?,?)",
        (run_id, json.dumps(request, ensure_ascii=False, sort_keys=True)),
    )
    # No education service is configured in this boundary test. A retry must return
    # its original run without re-reading a potentially changed business object.
    response = client.post(
        f"/api/v1/conversations/{cid}/messages", headers=auth(), json=request
    )
    assert response.status_code == 200 and response.json()["run_id"] == run_id
    request["business_object"]["id"] = 2
    assert (
        client.post(
            f"/api/v1/conversations/{cid}/messages", headers=auth(), json=request
        ).status_code
        == 409
    )
