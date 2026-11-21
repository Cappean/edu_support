"""Durable application store; education transactions stay in reference."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import uuid4

from .config import DB_PATH


def now():
    return datetime.now(UTC).isoformat()


@contextmanager
def connect():
    db = sqlite3.connect(DB_PATH, timeout=20)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init():
    with connect() as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript("""
        CREATE TABLE IF NOT EXISTS conversations (
          id TEXT PRIMARY KEY,user_id INTEGER NOT NULL,title TEXT NOT NULL,
          created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS runs (
          id TEXT PRIMARY KEY,conversation_id TEXT NOT NULL REFERENCES conversations(id),
          request_id TEXT NOT NULL,input TEXT NOT NULL,status TEXT NOT NULL,
          created_at TEXT NOT NULL,updated_at TEXT NOT NULL,UNIQUE(conversation_id,request_id));
        CREATE UNIQUE INDEX IF NOT EXISTS one_running_per_conversation
          ON runs(conversation_id) WHERE status='running';
        CREATE TABLE IF NOT EXISTS messages (
          id INTEGER PRIMARY KEY,conversation_id TEXT NOT NULL REFERENCES conversations(id),
          run_id TEXT,role TEXT NOT NULL,content TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS events (
          id INTEGER PRIMARY KEY,run_id TEXT NOT NULL REFERENCES runs(id),
          type TEXT NOT NULL,payload TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS knowledge (
          id TEXT PRIMARY KEY,kind TEXT NOT NULL,title TEXT NOT NULL,body TEXT NOT NULL,
          aliases TEXT NOT NULL,category TEXT NOT NULL,status TEXT NOT NULL,
          version INTEGER NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS audit (
          id INTEGER PRIMARY KEY,actor TEXT NOT NULL,action TEXT NOT NULL,
          detail TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS leases (
          name TEXT PRIMARY KEY,owner TEXT NOT NULL,expires_at REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS tasks (
          id TEXT PRIMARY KEY,conversation_id TEXT NOT NULL REFERENCES conversations(id),
          kind TEXT NOT NULL,status TEXT NOT NULL,slots TEXT NOT NULL,
          source_message TEXT NOT NULL,updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS tool_receipts (
          run_id TEXT NOT NULL,tool_name TEXT NOT NULL,arguments TEXT NOT NULL,
          result TEXT NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(run_id,tool_name,arguments));
        CREATE TABLE IF NOT EXISTS request_payloads (
          run_id TEXT PRIMARY KEY REFERENCES runs(id),payload TEXT NOT NULL);
        CREATE UNIQUE INDEX IF NOT EXISTS one_assistant_reply
          ON messages(run_id) WHERE role='assistant' AND run_id IS NOT NULL;
        """)
        # A crashed process must not permanently block a conversation. Actual stale
        # recovery is performed using expiring leases by the execution service.
        if not db.execute("SELECT 1 FROM knowledge LIMIT 1").fetchone():
            timestamp = now()
            for kind, title, body, aliases, category in [
                (
                    "faq",
                    "如何申请退款",
                    "请告诉客服需要退款的订单或课程、退款原因和退款类型。信息齐全后会提交申请，由管理员审核；提交申请不代表退款成功。当前演示系统仅支持全额退款，金额以系统校验结果为准。",
                    "退费,退款流程,申请退款",
                    "售后服务",
                ),
                (
                    "article",
                    "工单服务说明",
                    "客服暂时无法解决的问题，可在您同意后提交工单。您可以继续补充说明，管理员会异步回复，填写处理结果后结单。不提供实时人工聊天。",
                    "人工,投诉,售后,工单",
                    "服务指南",
                ),
                (
                    "faq",
                    "如何查询学习进度",
                    "告诉客服您的班次名称，可以查询考勤、视频学习、作业和考试情况。查询结果来自平台业务记录。",
                    "进度,考勤,作业,考试",
                    "学习服务",
                ),
            ]:
                db.execute(
                    "INSERT INTO knowledge VALUES (?,?,?,?,?,?,?,1,?,?)",
                    (
                        uuid4().hex,
                        kind,
                        title,
                        body,
                        aliases,
                        category,
                        "published",
                        timestamp,
                        timestamp,
                    ),
                )


def rows(sql, params=()):
    with connect() as db:
        return [dict(row) for row in db.execute(sql, params).fetchall()]


def one(sql, params=()):
    result = rows(sql, params)
    return result[0] if result else None


def execute(sql, params=()):
    with connect() as db:
        return db.execute(sql, params).lastrowid


def event(run_id, kind, payload):
    return execute(
        "INSERT INTO events(run_id,type,payload,created_at) VALUES (?,?,?,?)",
        (run_id, kind, json.dumps(payload, ensure_ascii=False, default=str), now()),
    )


def audit(actor, action, detail):
    execute(
        "INSERT INTO audit(actor,action,detail,created_at) VALUES (?,?,?,?)",
        (actor, action, json.dumps(detail, ensure_ascii=False, default=str), now()),
    )
