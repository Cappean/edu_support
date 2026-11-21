"""Real Agent/MCP integration. Read-only prompts unless --ticket is explicitly passed."""

import asyncio
import json
import sys
from pathlib import Path
from uuid import uuid4

import httpx


async def main():
    async with httpx.AsyncClient(
        base_url="http://127.0.0.1:8000", timeout=30
    ) as client:
        students = (await client.get("/api/v1/demo/students")).json()
        login = (
            await client.post(
                "/api/v1/auth/demo", json={"user_id": students[0]["user_id"]}
            )
        ).json()
        client.headers["Authorization"] = "Bearer " + login["token"]
        cid = (await client.post("/api/v1/conversations")).json()["id"]
        prompts = [
            "帮我查一下我的订单，列出订单号和课程名称。",
            "我想退款，但我还没决定退哪个订单。",
            "先不退款了，告诉我工单是怎么处理的？",
            "取消刚才的退款任务。",
        ]
        if "--ticket" in sys.argv:
            prompts = [
                "我要提交一张售后工单：网页课程目录打不开，点击后一直空白。请直接提交，不关联订单。"
            ]
        report = []
        for prompt in prompts:
            response = await client.post(
                f"/api/v1/conversations/{cid}/messages",
                json={"content": prompt, "request_id": uuid4().hex},
            )
            response.raise_for_status()
            run_id = response.json()["run_id"]
            async with client.stream(
                "GET", f"/api/v1/runs/{run_id}/events", timeout=260
            ) as stream:
                stream.raise_for_status()
                events = []
                async for line in stream.aiter_lines():
                    if line.startswith("event: "):
                        events.append(line[7:])
            conversation = (await client.get(f"/api/v1/conversations/{cid}")).json()
            run = next(r for r in conversation["runs"] if r["id"] == run_id)
            answer = next(
                (
                    m["content"]
                    for m in reversed(conversation["messages"])
                    if m["run_id"] == run_id and m["role"] == "assistant"
                ),
                None,
            )
            result = {
                "prompt": prompt,
                "status": run["status"],
                "answer": answer,
                "events": events,
                "tasks": conversation["tasks"],
            }
            report.append(result)
            print(
                json.dumps(
                    {
                        "run_id": run_id,
                        "status": run["status"],
                        "delta_events": events.count("delta"),
                        "tool_calls": events.count("tool_start"),
                        "answer_present": bool(answer),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
            if run["status"] != "completed" or not answer:
                raise RuntimeError("Agent integration failed")
        target = (
            Path(__file__).resolve().parents[1]
            / ".runtime"
            / (
                "agent-ticket-report.json"
                if "--ticket" in sys.argv
                else "agent-report.json"
            )
        )
        target.write_text(
            json.dumps(
                {"conversation_id": cid, "results": report},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print("report:", target.name)


if __name__ == "__main__":
    asyncio.run(main())
