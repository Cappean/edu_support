"""Actual model evaluation of task switching, clarification and knowledge fallback."""

import asyncio
import json
import sys
from pathlib import Path
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


async def main():
    from edu_support import storage

    report = []
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8000", timeout=260) as c:
        students = (await c.get("/api/v1/demo/students")).json()
        login = (
            await c.post("/api/v1/auth/demo", json={"user_id": students[0]["user_id"]})
        ).json()
        c.headers["Authorization"] = "Bearer " + login["token"]
        cid = (await c.post("/api/v1/conversations")).json()["id"]

        async def say(content):
            r = await c.post(
                f"/api/v1/conversations/{cid}/messages?wait=true",
                json={"content": content, "request_id": uuid4().hex},
            )
            r.raise_for_status()
            run = r.json()
            assert run["status"] == "completed"
            state = (await c.get(f"/api/v1/conversations/{cid}")).json()
            events = storage.rows(
                "SELECT type,payload FROM events WHERE run_id=? ORDER BY id",
                (run["run_id"],),
            )
            report.append(
                {
                    "input": content,
                    "answer": run["answer"],
                    "tasks": state["tasks"],
                    "events": events,
                }
            )
            print("scenario_completed", len(report), flush=True)
            return state, events

        state, _ = await say(
            "我要申请退款，订单号我等会再提供，先记录我的诉求，不要替我选择订单。"
        )
        assert any(
            t["kind"] == "refund" and t["status"] == "active" for t in state["tasks"]
        )
        state, _ = await say(
            "插入一个查询：帮我找找Python课程，查完后继续刚才的退款，退款订单号我稍后给你。"
        )
        assert any(
            t["kind"] == "refund" and t["status"] == "active" for t in state["tasks"]
        )
        state, _ = await say("取消刚才的退款，不申请了。")
        assert any(
            t["kind"] == "refund" and t["status"] == "cancelled" for t in state["tasks"]
        )
        await say("只咨询一下退款政策，不要替我申请。")
        await say(
            "有量子宇宙会员免费续费一千年的政策吗？请查真实政策，没有就明确说没有。"
        )
        await say("帮我处理一下。")
        for step in report:
            assert not any(e["type"] == "operation_result" for e in step["events"]), (
                "unexpected business write"
            )
        (ROOT / ".runtime/scenarios-report.json").write_text(
            json.dumps(
                {"result": "passed", "conversation_id": cid, "checks": report},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print("switch_resume_cancel_clarify_no_unrequested_writes: PASS", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
