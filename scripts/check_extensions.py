"""Verify actual learning tools and newly published knowledge are usable by Agent."""

import asyncio
import json
import sys
from pathlib import Path
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


async def main():
    from edu_support.config import ADMIN_PASSWORD

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
            result = r.json()
            assert result["status"] == "completed"
            return result

        learning = await say(
            "帮我查询已经报名的班次，并查询其中第一个班次的学习进度，展示考勤、视频、作业和考试情况。"
        )
        print("learning_agent_completed", flush=True)
        admin = (
            await c.post(
                "/api/v1/auth/admin",
                json={"username": "admin", "password": ADMIN_PASSWORD},
            )
        ).json()
        ah = {"Authorization": "Bearer " + admin["token"]}
        marker = "ZXQ" + uuid4().hex[:10]
        value = "青松" + uuid4().hex[:8]
        body = {
            "kind": "faq",
            "title": marker + "专属验收说明",
            "body": "本次专属验收标记为"
            + value
            + "。仅用于验证知识发布后可被查询，不是业务政策。",
            "category": "临时验收",
            "status": "published",
        }
        created = (
            await c.post("/api/v1/admin/knowledge", headers=ah, json=body)
        ).json()
        try:
            answer = await say(
                "请从知识库查找 " + marker + " 的专属验收标记是什么，附上来源。"
            )
            assert value in answer["answer"], "new knowledge not used in response"
            assert created["id"] in answer["answer"], "missing knowledge citation"
            (ROOT / ".runtime/extensions-report.json").write_text(
                json.dumps(
                    {
                        "result": "passed",
                        "conversation_id": cid,
                        "learning": learning,
                        "new_knowledge": answer,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            print("new_knowledge_without_agent_changes: PASS", flush=True)
        finally:
            r = await c.put(
                "/api/v1/admin/knowledge/" + created["id"],
                headers=ah,
                json=body | {"status": "draft", "version": 1},
            )
            r.raise_for_status()
            r = await c.delete("/api/v1/admin/knowledge/" + created["id"], headers=ah)
            r.raise_for_status()


if __name__ == "__main__":
    asyncio.run(main())
