import asyncio
import json
import logging
import secrets
import sqlite3
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from itsdangerous import BadSignature, URLSafeTimedSerializer
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from pydantic import BaseModel, Field

from . import storage
from .agent import run_agent
from .config import ADMIN_PASSWORD, CHECKPOINT_PATH, SECRET
from .education import EducationError, ReferenceHTTP
from .mcp_tools import mcp

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
)
log = logging.getLogger("edu_support")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpx2").setLevel(logging.WARNING)
tokens = URLSafeTimedSerializer(SECRET, salt="http-auth")
jobs = set()
mcp_app = mcp.streamable_http_app()


async def lease_worker(app, owner):
    """One local application instance owns recovery; lease expires on process crash."""
    while True:
        with storage.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            lease = db.execute("SELECT * FROM leases WHERE name='executor'").fetchone()
            if lease and lease["owner"] != owner and lease["expires_at"] > time.time():
                raise RuntimeError(
                    "另一个实例正在执行会话；当前演示版只运行一个应用实例"
                )
            db.execute(
                "INSERT INTO leases VALUES ('executor',?,?) ON CONFLICT(name) DO UPDATE SET owner=excluded.owner,expires_at=excluded.expires_at",
                (owner, time.time() + 15),
            )
        await asyncio.sleep(3)


async def recover_runs(app):
    # Reuse the original run ID and business idempotency keys. A completed write
    # followed by a crash must be replayed as the same operation, not a new one.
    for run in storage.rows(
        "SELECT r.*,c.user_id FROM runs r JOIN conversations c ON c.id=r.conversation_id WHERE r.status='running'"
    ):
        task = asyncio.create_task(
            execute_run(
                app, run["conversation_id"], run["user_id"], run["id"], run["input"]
            )
        )
        jobs.add(task)
        task.add_done_callback(jobs.discard)


@asynccontextmanager
async def lifespan(app):
    storage.init()
    async with (
        httpx.AsyncClient(timeout=25) as client,
        AsyncSqliteSaver.from_conn_string(CHECKPOINT_PATH) as saver,
    ):
        app.state.education = ReferenceHTTP(client)
        app.state.saver = saver
        owner = uuid4().hex
        with storage.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            lease = db.execute("SELECT * FROM leases WHERE name='executor'").fetchone()
            if lease and lease["expires_at"] > time.time():
                raise RuntimeError("已有执行实例或旧租约尚未到期，请稍后重试")
            db.execute(
                "INSERT OR REPLACE INTO leases VALUES ('executor',?,?)",
                (owner, time.time() + 15),
            )
        heartbeat = asyncio.create_task(lease_worker(app, owner))
        async with mcp.session_manager.run():
            await recover_runs(app)
            yield
        heartbeat.cancel()
        await asyncio.gather(heartbeat, return_exceptions=True)
        for task in list(jobs):
            task.cancel()
        if jobs:
            await asyncio.gather(*list(jobs), return_exceptions=True)
        storage.execute(
            "DELETE FROM leases WHERE name='executor' AND owner=?", (owner,)
        )


app = FastAPI(title="教育服务台", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["Authorization", "Content-Type"],
)
app.mount("/mcp", mcp_app)


@app.exception_handler(EducationError)
async def education_error(request, error):
    return JSONResponse(
        status_code=error.status, content={"detail": error.message, "code": error.code}
    )


def actor(request: Request):
    value = request.headers.get("Authorization", "").removeprefix("Bearer ")
    try:
        return tokens.loads(value, max_age=43200)
    except BadSignature:
        raise HTTPException(401, "请重新选择学员或登录管理后台") from None


def student(who=Depends(actor)):
    if who.get("role") != "student":
        raise HTTPException(403, "需要学员身份")
    return who["user_id"]


def administrator(who=Depends(actor)):
    if who.get("role") != "admin":
        raise HTTPException(403, "需要管理员身份")
    return who


def own(conversation_id, user_id):
    result = storage.one(
        "SELECT * FROM conversations WHERE id=? AND user_id=?",
        (conversation_id, user_id),
    )
    if not result:
        raise HTTPException(404, "会话不存在")
    return result


@app.get("/api/v1/demo/students")
async def demo_students(request: Request):
    return await request.app.state.education.request("GET", "/support/students")


class SelectStudent(BaseModel):
    user_id: int


@app.post("/api/v1/auth/demo")
async def select_student(body: SelectStudent, request: Request):
    # Validate against the preselected demo accounts, not arbitrary numeric IDs.
    students = await demo_students(request)
    selected = next((s for s in students if s["user_id"] == body.user_id), None)
    if not selected:
        raise HTTPException(403, "请选择预置演示学员")
    return {
        "token": tokens.dumps({"role": "student", "user_id": body.user_id}),
        "student": selected,
    }


class Login(BaseModel):
    username: str
    password: str


@app.post("/api/v1/auth/admin")
async def admin_login(body: Login, request: Request):
    # Persistent short lockout prevents unbounded guessing even across restarts.
    address = request.client.host if request.client else "local"
    recent = storage.one(
        "SELECT COUNT(*) n FROM audit WHERE actor=? AND action='login_failed' AND created_at>?",
        (address, datetime.fromtimestamp(time.time() - 300, UTC).isoformat()),
    )
    if recent["n"] >= 10:
        raise HTTPException(429, "尝试次数过多，请五分钟后重试")
    if body.username != "admin" or not secrets.compare_digest(
        body.password, ADMIN_PASSWORD
    ):
        storage.audit(address, "login_failed", {})
        raise HTTPException(401, "账号或密码不正确")
    return {"token": tokens.dumps({"role": "admin", "name": "admin"})}


@app.get("/live")
async def live():
    return {"status": "alive"}


@app.get("/api/v1/health")
async def health(request: Request):
    await request.app.state.education.request("GET", "/health")
    storage.one("SELECT 1")
    import os

    return {
        "status": "ready",
        "model_configured": bool(
            os.getenv("OPENAI_API_KEY") and os.getenv("OPENAI_MODEL")
        ),
    }


@app.get("/api/v1/conversations")
async def conversations(user_id=Depends(student)):
    return storage.rows(
        "SELECT * FROM conversations WHERE user_id=? ORDER BY updated_at DESC",
        (user_id,),
    )


@app.post("/api/v1/conversations")
async def create_conversation(user_id=Depends(student)):
    cid, timestamp = uuid4().hex, storage.now()
    storage.execute(
        "INSERT INTO conversations VALUES (?,?,?,?,?)",
        (cid, user_id, "新的咨询", timestamp, timestamp),
    )
    return {"id": cid, "title": "新的咨询"}


@app.get("/api/v1/conversations/{cid}")
async def conversation(cid: str, user_id=Depends(student)):
    row = own(cid, user_id)
    row["messages"] = storage.rows(
        "SELECT * FROM messages WHERE conversation_id=? ORDER BY id", (cid,)
    )
    row["tasks"] = storage.rows(
        "SELECT * FROM tasks WHERE conversation_id=? ORDER BY updated_at DESC", (cid,)
    )
    row["runs"] = storage.rows(
        "SELECT id,status,created_at FROM runs WHERE conversation_id=? ORDER BY created_at",
        (cid,),
    )
    row["operations"] = storage.rows(
        "SELECT e.id,e.run_id,e.payload FROM events e JOIN runs r ON r.id=e.run_id WHERE r.conversation_id=? AND e.type='operation_result' ORDER BY e.id",
        (cid,),
    )
    for operation in row["operations"]:
        operation["payload"] = json.loads(operation["payload"])
    return row


class BusinessObject(BaseModel):
    kind: Literal["order", "cohort"]
    id: int = Field(gt=0)


class ChatInput(BaseModel):
    content: str = Field(min_length=1, max_length=6000)
    request_id: str = Field(min_length=8, max_length=100)
    business_object: BusinessObject | None = None


async def execute_run(app, cid, user_id, run_id, content):
    try:
        async with asyncio.timeout(240):
            answer = await run_agent(cid, user_id, run_id, content, app.state.saver)
        # Commit answer, terminal event and execution status together. A crash
        # cannot leave a saved reply that will be duplicated by recovery.
        with storage.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if (
                db.execute("SELECT status FROM runs WHERE id=?", (run_id,)).fetchone()[
                    "status"
                ]
                == "completed"
            ):
                return
            timestamp = storage.now()
            db.execute(
                "INSERT OR IGNORE INTO messages(conversation_id,run_id,role,content,created_at) VALUES (?,?,?,?,?)",
                (cid, run_id, "assistant", str(answer), timestamp),
            )
            db.execute(
                "INSERT INTO events(run_id,type,payload,created_at) VALUES (?,?,?,?)",
                (
                    run_id,
                    "done",
                    json.dumps({"text": answer}, ensure_ascii=False),
                    timestamp,
                ),
            )
            db.execute(
                "UPDATE runs SET status='completed',updated_at=? WHERE id=?",
                (timestamp, run_id),
            )
    except asyncio.CancelledError:
        # Keep 'running' so restart recovery continues the same operation.
        storage.event(run_id, "interrupted", {"message": "服务重启后将继续处理"})
        raise
    except Exception as error:
        log.error("run_failed run_id=%s type=%s", run_id, type(error).__name__)
        message = "本次处理未能完成，已保存对话。请查看业务结果后再继续，避免重复申请。"
        storage.event(run_id, "error", {"message": message, "trace_id": run_id})
        storage.execute(
            "UPDATE runs SET status='failed',updated_at=? WHERE id=?",
            (storage.now(), run_id),
        )


@app.post("/api/v1/conversations/{cid}/messages")
async def send_message(
    cid: str,
    body: ChatInput,
    request: Request,
    wait: bool = False,
    user_id=Depends(student),
):
    own(cid, user_id)
    content = body.content
    raw_payload = json.dumps(
        body.model_dump(exclude_none=True), ensure_ascii=False, sort_keys=True
    )
    prior = storage.one(
        "SELECT r.*,p.payload FROM runs r LEFT JOIN request_payloads p ON p.run_id=r.id WHERE r.conversation_id=? AND r.request_id=?",
        (cid, body.request_id),
    )
    if prior and prior["payload"] is not None:
        if prior["payload"] != raw_payload:
            raise HTTPException(409, "重复请求标识对应的消息内容不一致")
        answer = (
            storage.one(
                "SELECT content FROM messages WHERE run_id=? AND role='assistant'",
                (prior["id"],),
            )
            if wait
            else None
        )
        return {
            "run_id": prior["id"],
            "status": prior["status"],
            **({"answer": answer["content"] if answer else None} if wait else {}),
        }
    if body.business_object:
        obj = body.business_object
        path = (
            f"/api/v1/orders/{obj.id}"
            if obj.kind == "order"
            else f"/api/v1/me/cohorts/{obj.id}"
        )
        verified = await request.app.state.education.request(
            "GET", path, user_id=user_id
        )
        content += (
            "\n[平台已校验的业务对象："
            + json.dumps(
                {"type": obj.kind, "data": verified}, ensure_ascii=False, default=str
            )
            + "]"
        )
    with storage.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        prior = db.execute(
            "SELECT * FROM runs WHERE conversation_id=? AND request_id=?",
            (cid, body.request_id),
        ).fetchone()
        if prior:
            raw_prior = db.execute(
                "SELECT payload FROM request_payloads WHERE run_id=?", (prior["id"],)
            ).fetchone()
            if (raw_prior and raw_prior["payload"] != raw_payload) or (
                not raw_prior and prior["input"] != content
            ):
                raise HTTPException(409, "重复请求标识对应的消息内容不一致")
            if wait and prior["status"] == "completed":
                answer = db.execute(
                    "SELECT content FROM messages WHERE run_id=? AND role='assistant' ORDER BY id DESC LIMIT 1",
                    (prior["id"],),
                ).fetchone()
                return {
                    "run_id": prior["id"],
                    "status": prior["status"],
                    "answer": answer["content"] if answer else None,
                }
            return {"run_id": prior["id"], "status": prior["status"]}
        run_id, timestamp = uuid4().hex, storage.now()
        try:
            db.execute(
                "INSERT INTO runs VALUES (?,?,?,?,?,?,?)",
                (
                    run_id,
                    cid,
                    body.request_id,
                    content,
                    "running",
                    timestamp,
                    timestamp,
                ),
            )
        except sqlite3.IntegrityError:
            raise HTTPException(409, "当前会话正在处理上一条消息") from None
        db.execute("INSERT INTO request_payloads VALUES (?,?)", (run_id, raw_payload))
        db.execute(
            "INSERT INTO messages(conversation_id,run_id,role,content,created_at) VALUES (?,?,?,?,?)",
            (cid, run_id, "user", content, timestamp),
        )
        db.execute(
            "UPDATE conversations SET title=CASE WHEN title=? THEN ? ELSE title END,updated_at=? WHERE id=?",
            ("新的咨询", body.content[:30], timestamp, cid),
        )
    task = asyncio.create_task(execute_run(request.app, cid, user_id, run_id, content))
    jobs.add(task)
    task.add_done_callback(jobs.discard)
    if wait:
        # Optional non-streaming mode uses exactly the same persisted execution.
        await asyncio.shield(task)
        state = storage.one("SELECT status FROM runs WHERE id=?", (run_id,))
        answer = storage.one(
            "SELECT content FROM messages WHERE run_id=? AND role='assistant' ORDER BY id DESC LIMIT 1",
            (run_id,),
        )
        return {
            "run_id": run_id,
            "status": state["status"],
            "answer": answer["content"] if answer else None,
        }
    return {"run_id": run_id, "status": "running"}


@app.get("/api/v1/runs/{run_id}/events")
async def events(
    run_id: str, request: Request, after: int = 0, user_id=Depends(student)
):
    run = storage.one("SELECT * FROM runs WHERE id=?", (run_id,))
    if not run:
        raise HTTPException(404, "执行记录不存在")
    own(run["conversation_id"], user_id)

    async def stream():
        cursor = after
        while True:
            records = storage.rows(
                "SELECT * FROM events WHERE run_id=? AND id>? ORDER BY id",
                (run_id, cursor),
            )
            for record in records:
                cursor = record["id"]
                yield f"id: {cursor}\nevent: {record['type']}\ndata: {record['payload']}\n\n"
            state = storage.one("SELECT status FROM runs WHERE id=?", (run_id,))
            if state["status"] != "running":
                break
            if await request.is_disconnected():
                break
            yield ": keepalive\n\n"
            await asyncio.sleep(0.3)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/v1/me/{kind}")
async def my_list(
    kind: Literal["orders", "refunds", "tickets", "cohorts"],
    request: Request,
    user_id=Depends(student),
):
    path = "/api/v1/me/cohorts" if kind == "cohorts" else f"/support/{kind}"
    return await request.app.state.education.request("GET", path, user_id=user_id)


@app.get("/api/v1/me/tickets/{ticket_id}")
async def my_ticket(ticket_id: int, request: Request, user_id=Depends(student)):
    return await request.app.state.education.request(
        "GET", f"/support/tickets/{ticket_id}", user_id=user_id
    )


class TicketReply(BaseModel):
    content: str = Field(min_length=1, max_length=5000)
    operation_id: str = Field(min_length=8, max_length=100)
    internal: bool = False
    close: bool = False


@app.post("/api/v1/me/tickets/{ticket_id}/messages")
async def supplement(
    ticket_id: int, body: TicketReply, request: Request, user_id=Depends(student)
):
    return await request.app.state.education.request(
        "POST",
        f"/support/tickets/{ticket_id}/messages",
        user_id=user_id,
        json=body.model_dump(),
    )


@app.get("/api/v1/admin/education/{kind}", dependencies=[Depends(administrator)])
async def admin_education(
    kind: str, request: Request, q: str = "", page: int = 1, size: int = 20
):
    return await request.app.state.education.request(
        "GET",
        f"/support/admin/{kind}",
        admin=True,
        params={"q": q, "page": page, "size": size},
    )


@app.get("/api/v1/admin/tickets/{ticket_id}", dependencies=[Depends(administrator)])
async def admin_ticket(ticket_id: int, request: Request):
    return await request.app.state.education.request(
        "GET", f"/support/admin/tickets/{ticket_id}", admin=True
    )


@app.post(
    "/api/v1/admin/tickets/{ticket_id}/messages", dependencies=[Depends(administrator)]
)
async def reply(ticket_id: int, body: TicketReply, request: Request):
    if body.close and body.internal:
        raise HTTPException(400, "结单结果必须对学员公开")
    result = await request.app.state.education.request(
        "POST",
        f"/support/admin/tickets/{ticket_id}/messages",
        admin=True,
        json=body.model_dump(),
    )
    storage.audit(
        "admin",
        "ticket_reply",
        {"ticket_id": ticket_id, "internal": body.internal, "close": body.close},
    )
    return result


@app.get(
    "/api/v1/admin/learning/{user_id}/{cohort_id}",
    dependencies=[Depends(administrator)],
)
async def admin_learning(user_id: int, cohort_id: int, request: Request):
    return await request.app.state.education.request(
        "GET", f"/support/admin/learning/{user_id}/{cohort_id}", admin=True
    )


class Review(BaseModel):
    decision: Literal["approve", "reject"]
    note: str = Field(min_length=2, max_length=2000)
    operation_id: str = Field(min_length=8, max_length=100)


@app.post(
    "/api/v1/admin/refunds/{refund_id}/review", dependencies=[Depends(administrator)]
)
async def review(refund_id: int, body: Review, request: Request):
    result = await request.app.state.education.request(
        "POST",
        f"/support/admin/refunds/{refund_id}/review",
        admin=True,
        json=body.model_dump(),
    )
    storage.audit(
        "admin",
        "refund_review",
        {
            "refund_id": refund_id,
            "decision": body.decision,
            "operation_id": body.operation_id,
        },
    )
    return result


class KnowledgeInput(BaseModel):
    kind: Literal["faq", "article"]
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=20000)
    aliases: str = Field(default="", max_length=2000)
    category: str = Field(default="通用", max_length=100)
    status: Literal["draft", "published", "offline"] = "draft"
    version: int | None = None


@app.get("/api/v1/admin/knowledge", dependencies=[Depends(administrator)])
async def knowledge(q: str = ""):
    return storage.rows(
        "SELECT * FROM knowledge WHERE title LIKE ? OR body LIKE ? ORDER BY updated_at DESC",
        ("%" + q + "%", "%" + q + "%"),
    )


@app.post("/api/v1/admin/knowledge", dependencies=[Depends(administrator)])
async def add_knowledge(body: KnowledgeInput):
    kid, timestamp = uuid4().hex, storage.now()
    storage.execute(
        "INSERT INTO knowledge VALUES (?,?,?,?,?,?,?,1,?,?)",
        (
            kid,
            body.kind,
            body.title,
            body.body,
            body.aliases,
            body.category,
            body.status,
            timestamp,
            timestamp,
        ),
    )
    storage.audit("admin", "knowledge_create", {"id": kid})
    return {"id": kid, "version": 1}


@app.put("/api/v1/admin/knowledge/{kid}", dependencies=[Depends(administrator)])
async def edit_knowledge(kid: str, body: KnowledgeInput):
    with storage.connect() as db:
        result = db.execute(
            "UPDATE knowledge SET kind=?,title=?,body=?,aliases=?,category=?,status=?,version=version+1,updated_at=? WHERE id=? AND version=?",
            (
                body.kind,
                body.title,
                body.body,
                body.aliases,
                body.category,
                body.status,
                storage.now(),
                kid,
                body.version,
            ),
        )
        if not result.rowcount:
            raise HTTPException(409, "内容已变化或不存在，请刷新后重试")
    storage.audit("admin", "knowledge_update", {"id": kid, "version": body.version})
    return {"id": kid, "version": body.version + 1}


@app.delete("/api/v1/admin/knowledge/{kid}", dependencies=[Depends(administrator)])
async def delete_knowledge(kid: str):
    with storage.connect() as db:
        row = db.execute("SELECT status FROM knowledge WHERE id=?", (kid,)).fetchone()
        if not row:
            raise HTTPException(404, "内容不存在")
        if row["status"] != "draft":
            raise HTTPException(409, "已发布内容请下架保留记录，不直接删除")
        db.execute("DELETE FROM knowledge WHERE id=?", (kid,))
    storage.audit("admin", "knowledge_delete", {"id": kid})
    return {"deleted": True}


@app.get("/api/v1/admin/knowledge-search", dependencies=[Depends(administrator)])
async def preview(q: str):
    from .knowledge import KeywordSearch

    return KeywordSearch().search(q)


@app.get("/api/v1/admin/audit", dependencies=[Depends(administrator)])
async def audit():
    return storage.rows("SELECT * FROM audit ORDER BY id DESC LIMIT 100")
