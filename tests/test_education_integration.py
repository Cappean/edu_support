"""Opt-in real MySQL tests using isolated, explicitly tagged test rows."""

import os
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_EDUCATION_INTEGRATION") != "1",
    reason="requires local education MySQL",
)


@pytest.fixture
def education():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "reference"))
    from app.database import db_cursor, fetch_one
    from app.main import app
    from app.support import migrate
    from app.support_security import service_secret

    migrate()
    client = TestClient(app, headers={"X-Service-Key": service_secret()})
    prefix = "IT" + uuid4().hex[:16]
    sample = fetch_one(
        "SELECT sp.id student_id,sp.user_id,c.id cohort_id,c.institution_id FROM student_profile sp CROSS JOIN series_cohort c WHERE sp.yn=1 AND c.yn=1 ORDER BY (SELECT COUNT(*) FROM `order` o WHERE o.user_id=sp.user_id) DESC,sp.id,c.id LIMIT 1"
    )
    from app.utils import local_now

    now = local_now()
    with db_cursor() as (_, c):
        c.execute(
            """INSERT INTO `order` (institution_id,order_no,user_id,student_id,order_status,total_amount,discount_amount,payable_amount,paid_amount,refund_amount,created_at,updated_at)
            VALUES (%s,%s,%s,%s,'paid',100,0,100,100,0,%s,%s)""",
            (
                sample["institution_id"],
                prefix,
                sample["user_id"],
                sample["student_id"],
                now,
                now,
            ),
        )
        order_id = c.lastrowid
        c.execute(
            """INSERT INTO order_item (institution_id,order_id,user_id,student_id,cohort_id,order_item_status,item_name,unit_price,discount_amount,payable_amount,service_period_days,created_at,updated_at)
            VALUES (%s,%s,%s,%s,%s,'paid','集成测试课程',100,0,100,30,%s,%s)""",
            (
                sample["institution_id"],
                order_id,
                sample["user_id"],
                sample["student_id"],
                sample["cohort_id"],
                now,
                now,
            ),
        )
        item_id = c.lastrowid
        c.execute(
            "INSERT INTO payment_record (institution_id,order_id,payment_no,payment_channel,payment_status,amount,refund_amount,paid_at,created_at,updated_at) VALUES (%s,%s,%s,'wechat_pay','paid',100,0,%s,%s,%s)",
            (sample["institution_id"], order_id, prefix, now, now, now),
        )
    created_tickets = []
    yield client, sample, order_id, item_id, prefix, created_tickets
    client.close()
    # Remove only records owned by this fixture, preserve existing reference data.
    with db_cursor() as (_, c):
        for ticket_id in created_tickets:
            c.execute(
                "DELETE FROM service_ticket_follow_record WHERE ticket_id=%s",
                (ticket_id,),
            )
            c.execute("DELETE FROM service_ticket WHERE id=%s", (ticket_id,))
        c.execute("DELETE FROM refund_request WHERE order_id=%s", (order_id,))
        c.execute("DELETE FROM payment_record WHERE order_id=%s", (order_id,))
        c.execute("DELETE FROM order_item WHERE order_id=%s", (order_id,))
        c.execute("DELETE FROM `order` WHERE id=%s AND order_no=%s", (order_id, prefix))
        c.execute(
            "DELETE FROM support_operation WHERE operation_key LIKE %s",
            ("%" + prefix + "%",),
        )


def test_full_refund_idempotency_and_atomic_approval(education):
    client, sample, order_id, item_id, prefix, _ = education
    headers = {"X-User-Id": str(sample["user_id"])}
    body = {
        "order_item_id": item_id,
        "reason": "集成测试退款",
        "refund_type": "personal_reason",
        "operation_id": prefix + "refund",
    }
    assert (
        client.get(
            "/support/refunds/eligibility/" + str(item_id), headers=headers
        ).json()["amount"]
        == "100.00"
    )
    a = client.post("/support/refunds", headers=headers, json=body)
    assert a.status_code == 200, a.text
    assert (
        client.post("/support/refunds", headers=headers, json=body).json() == a.json()
    )
    changed = body | {"reason": "不同请求"}
    assert (
        client.post("/support/refunds", headers=headers, json=changed).status_code
        == 409
    )
    body2 = body | {"operation_id": prefix + "refund2"}
    assert (
        client.post("/support/refunds", headers=headers, json=body2).status_code == 409
    )
    rid = a.json()["id"]
    review = {
        "decision": "approve",
        "note": "测试通过，模拟退款",
        "operation_id": prefix + "review",
    }
    assert (
        client.post(f"/support/admin/refunds/{rid}/review", json=review).status_code
        == 403
    )
    result = client.post(
        f"/support/admin/refunds/{rid}/review",
        headers={"X-Actor-Role": "admin"},
        json=review,
    )
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "refunded"
    assert (
        client.post(
            f"/support/admin/refunds/{rid}/review",
            headers={"X-Actor-Role": "admin"},
            json=review,
        ).json()
        == result.json()
    )
    from app.database import fetch_one

    assert (
        fetch_one(
            "SELECT order_status,refund_amount FROM `order` WHERE id=%s", (order_id,)
        )["order_status"]
        == "refunded"
    )
    assert (
        fetch_one(
            "SELECT payment_status FROM payment_record WHERE order_id=%s", (order_id,)
        )["payment_status"]
        == "refunded"
    )
    assert (
        fetch_one("SELECT order_item_status FROM order_item WHERE id=%s", (item_id,))[
            "order_item_status"
        ]
        == "refunded"
    )


def test_no_order_ticket_reply_private_notes_and_close(education):
    client, sample, _, _, prefix, created = education
    h = {"X-User-Id": str(sample["user_id"])}
    admin = {"X-Actor-Role": "admin"}
    payload = {
        "title": "测试无订单问题",
        "description": "测试页面加载异常，无法查看课程",
        "operation_id": prefix + "ticket",
    }
    response = client.post("/support/tickets", headers=h, json=payload)
    assert response.status_code == 200, response.text
    tid = response.json()["id"]
    created.append(tid)
    assert (
        client.post("/support/tickets", headers=h, json=payload).json()
        == response.json()
    )
    assert (
        client.get(
            f"/support/tickets/{tid}", headers={"X-User-Id": str(sample["user_id"] + 1)}
        ).status_code
        == 404
    )
    for content, internal in [("内部排查", True), ("请稍后重试", False)]:
        r = client.post(
            f"/support/admin/tickets/{tid}/messages",
            headers=admin,
            json={
                "content": content,
                "internal": internal,
                "operation_id": prefix + str(internal),
            },
        )
        assert r.status_code == 200, r.text
    detail = client.get(f"/support/tickets/{tid}", headers=h).json()
    assert (
        len(detail["records"]) == 1
        and detail["records"][0]["follow_content"] == "请稍后重试"
    )
    assert (
        len(
            client.get(f"/support/admin/tickets/{tid}", headers=admin).json()["records"]
        )
        == 2
    )
    supplement = {"content": "重试后已经恢复", "operation_id": prefix + "supplement"}
    assert (
        client.post(
            f"/support/tickets/{tid}/messages", headers=h, json=supplement
        ).status_code
        == 200
    )
    close = {
        "content": "问题已恢复，现结单",
        "close": True,
        "operation_id": prefix + "close",
    }
    assert (
        client.post(
            f"/support/admin/tickets/{tid}/messages", headers=admin, json=close
        ).status_code
        == 200
    )
    assert (
        client.get(f"/support/tickets/{tid}", headers=h).json()["ticket_status"]
        == "closed"
    )
    assert (
        client.post(
            f"/support/tickets/{tid}/messages",
            headers=h,
            json=supplement | {"operation_id": prefix + "late"},
        ).status_code
        == 409
    )


def test_refund_rejection_keeps_order_paid(education):
    client, sample, order_id, item_id, prefix, _ = education
    headers = {"X-User-Id": str(sample["user_id"])}
    body = {
        "order_item_id": item_id,
        "reason": "验证驳回",
        "refund_type": "personal_reason",
        "operation_id": prefix + "reject-submit",
    }
    result = client.post("/support/refunds", headers=headers, json=body)
    assert result.status_code == 200, result.text
    rid = result.json()["id"]
    review = {
        "decision": "reject",
        "note": "演示驳回说明",
        "operation_id": prefix + "reject-review",
    }
    response = client.post(
        f"/support/admin/refunds/{rid}/review",
        headers={"X-Actor-Role": "admin"},
        json=review,
    )
    assert response.status_code == 200
    from app.database import fetch_one

    assert (
        fetch_one("SELECT order_status FROM `order` WHERE id=%s", (order_id,))[
            "order_status"
        ]
        == "paid"
    )
    assert (
        fetch_one("SELECT remark FROM refund_request WHERE id=%s", (rid,))["remark"]
        == review["note"]
    )


def test_concurrent_same_operation_creates_one_refund(education):
    from concurrent.futures import ThreadPoolExecutor

    client, sample, _, item_id, prefix, _ = education
    payload = {
        "order_item_id": item_id,
        "reason": "并发去重验证",
        "refund_type": "personal_reason",
        "operation_id": prefix + "concurrent",
    }

    def submit(_):
        return client.post(
            "/support/refunds",
            headers={"X-User-Id": str(sample["user_id"])},
            json=payload,
        )

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(submit, range(4)))
    assert all(r.status_code == 200 for r in results)
    assert len({r.json()["id"] for r in results}) == 1


def test_learning_progress_has_catalog_totals_and_owned_scores(education):
    client, *_ = education
    from app.database import fetch_one

    relation = fetch_one(
        "SELECT * FROM student_cohort_rel WHERE enroll_status='active' ORDER BY id LIMIT 1"
    )
    result = client.get(
        f"/api/v1/me/cohorts/{relation['cohort_id']}/progress",
        headers={"X-User-Id": str(relation["user_id"])},
    )
    assert result.status_code == 200, result.text
    data = result.json()["data"]
    assert data["video"]["completedVideos"] <= data["video"]["totalVideos"]
    total = fetch_one(
        """SELECT COUNT(*) n FROM session_video v
        JOIN session_asset a ON a.id=v.asset_id
        JOIN series_cohort_session s ON s.id=a.session_id
        JOIN series_cohort_course c ON c.id=s.series_cohort_course_id WHERE c.cohort_id=%s""",
        (relation["cohort_id"],),
    )["n"]
    assert data["video"]["totalVideos"] == total
    for score in data["exam"]["scores"]:
        actual = fetch_one(
            "SELECT score_value FROM session_exam_submission WHERE student_id=%s AND exam_id=%s",
            (relation["student_id"], score["examId"]),
        )
        assert score["score"] == (
            float(actual["score_value"]) if actual["score_value"] is not None else None
        )
