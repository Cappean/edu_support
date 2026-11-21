"""Crash/restart real application and verify same persisted run resumes.

Run only while application port 8000 is stopped; reference and Vite may remain up.
"""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[1]


async def ready(client, process):
    for _ in range(90):
        if process.poll() is not None:
            raise RuntimeError(
                "recovery app process exited; inspect .runtime/recovery-server.log"
            )
        try:
            if (await client.get("/api/v1/health")).is_success:
                return
        except httpx.HTTPError:
            pass
        await asyncio.sleep(0.4)
    raise RuntimeError("app readiness timeout")


async def main():
    child = None
    env = os.environ | {
        "PYTHONPATH": str(ROOT / "src"),
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUNBUFFERED": "1",
    }
    command = [
        sys.executable,
        "-m",
        "uvicorn",
        "edu_support.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        "8000",
    ]
    with (ROOT / ".runtime/recovery-server.log").open("w", encoding="utf-8") as log:

        def start():
            return subprocess.Popen(
                command,
                cwd=ROOT,
                env=env,
                stdout=log,
                stderr=log,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )

        try:
            async with httpx.AsyncClient(
                base_url="http://127.0.0.1:8000", timeout=5
            ) as client:
                try:
                    await client.get("/live")
                except httpx.HTTPError:
                    pass
                else:
                    raise RuntimeError(
                        "port 8000 already running; stop it before crash test"
                    )
                child = start()
                await ready(client, child)
                students = (await client.get("/api/v1/demo/students")).json()
                login = (
                    await client.post(
                        "/api/v1/auth/demo", json={"user_id": students[0]["user_id"]}
                    )
                ).json()
                client.headers["Authorization"] = "Bearer " + login["token"]
                cid = (await client.post("/api/v1/conversations")).json()["id"]
                request = {
                    "content": "请查询我的订单，并列出全部订单号、课程和状态。",
                    "request_id": uuid4().hex,
                }
                run = (
                    await client.post(
                        f"/api/v1/conversations/{cid}/messages", json=request
                    )
                ).json()
                # Interrupt after at least one completed tool node is checkpointed.
                sys.path.insert(0, str(ROOT / "src"))
                from edu_support import storage

                for _ in range(150):
                    if storage.one(
                        "SELECT id FROM events WHERE run_id=? AND type='tool_result'",
                        (run["run_id"],),
                    ):
                        break
                    await asyncio.sleep(0.2)
                else:
                    raise RuntimeError("no tool progress to interrupt")
                child.kill()
                child.wait(timeout=10)
                assert (
                    storage.one("SELECT status FROM runs WHERE id=?", (run["run_id"],))[
                        "status"
                    ]
                    == "running"
                )
                await asyncio.sleep(16)
                child = start()
                await ready(client, child)
                for _ in range(180):
                    state = storage.one(
                        "SELECT status FROM runs WHERE id=?", (run["run_id"],)
                    )
                    if state["status"] != "running":
                        break
                    await asyncio.sleep(1)
                assert state["status"] == "completed", state
                detail = (await client.get(f"/api/v1/conversations/{cid}")).json()
                assert len([m for m in detail["messages"] if m["role"] == "user"]) == 1
                assert (
                    len([m for m in detail["messages"] if m["role"] == "assistant"])
                    == 1
                )
                duplicate = (
                    await client.post(
                        f"/api/v1/conversations/{cid}/messages", json=request
                    )
                ).json()
                assert duplicate["run_id"] == run["run_id"]
                report = {
                    "result": "passed",
                    "conversation_id": cid,
                    "run_id": run["run_id"],
                    "same_run_resumed": True,
                    "duplicate_input": False,
                }
                (ROOT / ".runtime/recovery-report.json").write_text(
                    json.dumps(report, indent=2), encoding="utf-8"
                )
                print("crash_restart_same_run: PASS", flush=True)
        finally:
            if child and child.poll() is None:
                child.terminate()
                child.wait(timeout=10)


if __name__ == "__main__":
    asyncio.run(main())
