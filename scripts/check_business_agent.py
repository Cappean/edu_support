"""Actual model -> MCP -> MySQL -> administrator -> student closed-loop check.

Creates isolated test orders and removes only those fixture-owned business rows.
Real conversation/audit evidence stays in the local application database.
"""

import asyncio
import json
import sys
from pathlib import Path
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]


async def main():
    from test_education_integration import education

    from edu_support.config import ADMIN_PASSWORD

    fixture = education.__wrapped__()
    client, sample, order_id, item_id, prefix, created = next(fixture)
    report = []
    try:
        async with httpx.AsyncClient(
            base_url="http://127.0.0.1:8000", timeout=260
        ) as c:
            students = (await c.get("/api/v1/demo/students")).json()
            assert sample["user_id"] in [s["user_id"] for s in students]
            login = (
                await c.post("/api/v1/auth/demo", json={"user_id": sample["user_id"]})
            ).json()
            c.headers["Authorization"] = "Bearer " + login["token"]
            cid = (await c.post("/api/v1/conversations")).json()["id"]

            async def say(content):
                response = await c.post(
                    f"/api/v1/conversations/{cid}/messages?wait=true",
                    json={"content": content, "request_id": uuid4().hex},
                )
                response.raise_for_status()
                result = response.json()
                assert result["status"] == "completed", result
                report.append(
                    {
                        "prompt": content,
                        "answer": result["answer"],
                        "run_id": result["run_id"],
                    }
                )
                print("agent_turn_completed", len(report), flush=True)
                return result

            await say(
                f"我要退款订单 {prefix}，原因是个人原因，最近没时间学习，退款类型选择个人原因。请直接提交全额退款申请。"
            )
            refunds = (await c.get("/api/v1/me/refunds")).json()
            application = next((r for r in refunds if r["order_id"] == order_id), None)
            assert application and application["refund_status"] == "pending", (
                "Agent did not create pending refund"
            )
            admin = (
                await c.post(
                    "/api/v1/auth/admin",
                    json={"username": "admin", "password": ADMIN_PASSWORD},
                )
            ).json()
            ah = {"Authorization": "Bearer " + admin["token"]}
            review = await c.post(
                f"/api/v1/admin/refunds/{application['id']}/review",
                headers=ah,
                json={
                    "decision": "approve",
                    "note": "集成验证：通过并模拟退款",
                    "operation_id": prefix + "approval",
                },
            )
            review.raise_for_status()
            assert review.json()["status"] == "refunded"
            await say("查一下刚才的退款申请现在是什么状态。")
            await say(
                "我要提交售后工单，问题是课程目录页面点击后一直白屏，标题为集成验证页面白屏，不需要关联订单，请直接提交。"
            )
            tickets = (await c.get("/api/v1/me/tickets")).json()
            ticket = next((t for t in tickets if "集成验证" in t["title"]), None)
            assert ticket, "Agent did not create ticket"
            created.append(ticket["id"])
            r = await c.post(
                f"/api/v1/admin/tickets/{ticket['id']}/messages",
                headers=ah,
                json={
                    "content": "已收到，正在检查。",
                    "operation_id": prefix + "reply",
                },
            )
            r.raise_for_status()
            await say(f"请在工单 {ticket['id']} 补充：刷新后仍然白屏，浏览器是 Edge。")
            detail = (await c.get(f"/api/v1/me/tickets/{ticket['id']}")).json()
            assert any("Edge" in row["follow_content"] for row in detail["records"])
            r = await c.post(
                f"/api/v1/admin/tickets/{ticket['id']}/messages",
                headers=ah,
                json={
                    "content": "已修复目录服务，现结单。",
                    "close": True,
                    "operation_id": prefix + "close",
                },
            )
            r.raise_for_status()
            await say(f"查询工单 {ticket['id']} 的处理结果。")
            detail = (await c.get(f"/api/v1/me/tickets/{ticket['id']}")).json()
            assert detail["ticket_status"] == "closed"
            (ROOT / ".runtime" / "business-agent-report.json").write_text(
                json.dumps(
                    {"conversation_id": cid, "checks": report, "result": "passed"},
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            print("business_agent_closed_loop: PASS", flush=True)
    finally:
        try:
            next(fixture)
        except StopIteration:
            pass


if __name__ == "__main__":
    asyncio.run(main())
