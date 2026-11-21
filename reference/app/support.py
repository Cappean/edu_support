"""Small support use cases. Transactions and ownership remain in education backend."""

import hashlib
import json
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, Field

from .database import db_cursor, fetch_all, fetch_one
from .dependencies import get_current_user_id
from .errors import conflict, forbidden, not_found
from .utils import local_now, make_no

router = APIRouter(prefix="/support", tags=["support"])
User = Annotated[int, Depends(get_current_user_id)]


def admin(x_actor_role: Annotated[str | None, Header()] = None):
    # Outer middleware authenticates the service that supplies this role.
    if x_actor_role != "admin":
        raise forbidden("ADMIN_REQUIRED", "需要管理员权限")


def migrate():
    with db_cursor() as (_, c):
        c.execute("""CREATE TABLE IF NOT EXISTS support_operation (
            operation_key VARCHAR(180) PRIMARY KEY, fingerprint CHAR(64) NOT NULL,
            result_json JSON NULL, created_at DATETIME NOT NULL
        ) ENGINE=InnoDB""")
        c.execute(
            "SELECT IS_NULLABLE FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='service_ticket' AND COLUMN_NAME='order_item_id'"
        )
        if c.fetchone()["IS_NULLABLE"] == "NO":
            c.execute("ALTER TABLE service_ticket MODIFY order_item_id BIGINT NULL")


def transact(key: str, payload: dict, action):
    fingerprint = hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode()
    ).hexdigest()
    with db_cursor() as (_, c):
        # Duplicate-key UPDATE acquires an exclusive lock immediately. INSERT IGNORE
        # would acquire shared locks that deadlock when concurrent callers upgrade.
        c.execute(
            "INSERT INTO support_operation VALUES (%s,%s,NULL,%s) ON DUPLICATE KEY UPDATE operation_key=operation_key",
            (key, fingerprint, local_now()),
        )
        c.execute(
            "SELECT * FROM support_operation WHERE operation_key=%s FOR UPDATE", (key,)
        )
        row = c.fetchone()
        if row["fingerprint"] != fingerprint:
            raise conflict("IDEMPOTENCY_CONFLICT", "相同操作标识不能用于不同内容")
        if row["result_json"]:
            return json.loads(row["result_json"])
        result = action(c)
        c.execute(
            "UPDATE support_operation SET result_json=%s WHERE operation_key=%s",
            (json.dumps(result, ensure_ascii=False, default=str), key),
        )
        return result


def item_for_refund(c, user_id: int, order_item_id: int):
    c.execute(
        "SELECT * FROM order_item WHERE id=%s AND user_id=%s FOR UPDATE",
        (order_item_id, user_id),
    )
    item = c.fetchone()
    if not item:
        raise not_found("ORDER_ITEM_NOT_FOUND", "未找到当前学员的订单明细")
    c.execute("SELECT * FROM `order` WHERE id=%s FOR UPDATE", (item["order_id"],))
    order = c.fetchone()
    if item["order_item_status"] not in {"paid", "completed"}:
        raise conflict("NOT_REFUNDABLE", "该课程当前状态不能申请退款")
    c.execute(
        "SELECT * FROM payment_record WHERE order_id=%s AND payment_status IN ('paid','partial_refunded') ORDER BY id DESC LIMIT 1 FOR UPDATE",
        (item["order_id"],),
    )
    payment = c.fetchone()
    c.execute(
        "SELECT COALESCE(SUM(approved_amount),0) amount FROM refund_request WHERE order_item_id=%s AND refund_status='refunded'",
        (order_item_id,),
    )
    already = c.fetchone()["amount"]
    amount = Decimal(item["payable_amount"]) - Decimal(already)
    if (
        not payment
        or amount <= 0
        or amount > Decimal(payment["amount"]) - Decimal(payment["refund_amount"] or 0)
    ):
        raise conflict("NOT_REFUNDABLE", "支付记录不足以支持全额退回剩余可退金额")
    return item, order, payment, amount


@router.get("/students")
def students(limit: int = Query(20, ge=1, le=100)):
    return fetch_all(
        """SELECT u.id user_id, sp.id student_id, u.nickname, u.real_name,
        (SELECT COUNT(*) FROM `order` o WHERE o.user_id=u.id) order_count
        FROM student_profile sp JOIN sys_user u ON u.id=sp.user_id
        WHERE u.yn=1 AND sp.yn=1 ORDER BY order_count DESC,u.id LIMIT %s""",
        (limit,),
    )


@router.get("/orders")
def orders(user_id: User, keyword: str = ""):
    return fetch_all(
        """SELECT o.id order_id,o.order_no,o.order_status,o.paid_amount,
        i.id order_item_id,i.item_name,i.cohort_id,i.order_item_status,i.payable_amount
        FROM `order` o JOIN order_item i ON i.order_id=o.id
        WHERE o.user_id=%s AND (o.order_no LIKE %s OR i.item_name LIKE %s)
        ORDER BY o.created_at DESC LIMIT 80""",
        (user_id, "%" + keyword + "%", "%" + keyword + "%"),
    )


@router.get("/refunds/eligibility/{item_id}")
def eligibility(item_id: int, user_id: User):
    with db_cursor() as (_, c):
        item, _, _, amount = item_for_refund(c, user_id, item_id)
        c.execute(
            "SELECT id,refund_no,refund_status FROM refund_request WHERE order_item_id=%s AND refund_status IN ('pending','approved')",
            (item_id,),
        )
        existing = c.fetchone()
    return {
        "order_item_id": item_id,
        "course": item["item_name"],
        "amount": str(amount),
        "eligible": not bool(existing),
        "existing_application": existing,
    }


class RefundInput(BaseModel):
    order_item_id: int
    reason: str = Field(min_length=2, max_length=2000)
    refund_type: Literal[
        "personal_reason",
        "course_unsatisfied",
        "schedule_conflict",
        "duplicate_purchase",
    ]
    operation_id: str = Field(min_length=8, max_length=100)


@router.post("/refunds")
def submit_refund(body: RefundInput, user_id: User):
    def action(c):
        item, _, payment, amount = item_for_refund(c, user_id, body.order_item_id)
        c.execute(
            "SELECT id FROM refund_request WHERE order_item_id=%s AND refund_status IN ('pending','approved')",
            (body.order_item_id,),
        )
        if c.fetchone():
            raise conflict(
                "REFUND_IN_PROGRESS", "该课程已有待处理退款申请，请查询处理状态"
            )
        now, number = local_now(), make_no("RF")
        c.execute(
            """INSERT INTO refund_request
            (institution_id,refund_no,order_id,order_item_id,payment_id,user_id,student_id,
             refund_type,refund_reason,refund_status,apply_amount,yn,applied_at,created_at,updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'pending',%s,1,%s,%s,%s)""",
            (
                item["institution_id"],
                number,
                item["order_id"],
                body.order_item_id,
                payment["id"],
                user_id,
                item["student_id"],
                body.refund_type,
                body.reason,
                amount,
                now,
                now,
                now,
            ),
        )
        return {
            "id": c.lastrowid,
            "number": number,
            "status": "pending",
            "amount": str(amount),
        }

    return transact(f"refund:{user_id}:{body.operation_id}", body.model_dump(), action)


@router.get("/refunds")
def my_refunds(user_id: User):
    return fetch_all(
        """SELECT r.*,i.item_name FROM refund_request r JOIN order_item i ON i.id=r.order_item_id
        WHERE r.user_id=%s ORDER BY r.id DESC LIMIT 100""",
        (user_id,),
    )


class ReviewInput(BaseModel):
    decision: Literal["approve", "reject"]
    note: str = Field(min_length=2, max_length=2000)
    operation_id: str = Field(min_length=8, max_length=100)


@router.post("/admin/refunds/{refund_id}/review", dependencies=[Depends(admin)])
def review_refund(refund_id: int, body: ReviewInput):
    def action(c):
        c.execute("SELECT * FROM refund_request WHERE id=%s FOR UPDATE", (refund_id,))
        r = c.fetchone()
        if not r:
            raise not_found("REFUND_NOT_FOUND", "退款申请不存在")
        if r["refund_status"] != "pending":
            raise conflict("ALREADY_REVIEWED", "该申请已经处理")
        now = local_now()
        c.execute(
            "SELECT id FROM sys_user WHERE id IN (SELECT user_id FROM staff_profile WHERE yn=1) AND yn=1 ORDER BY id LIMIT 1"
        )
        actor = c.fetchone()
        actor_id = actor["id"] if actor else None
        if body.decision == "reject":
            c.execute(
                "UPDATE refund_request SET refund_status='rejected',remark=%s,approver_user_id=%s,approved_at=%s,updated_at=%s WHERE id=%s",
                (body.note, actor_id, now, now, refund_id),
            )
            return {"id": refund_id, "status": "rejected"}
        item, order, payment, amount = item_for_refund(
            c, r["user_id"], r["order_item_id"]
        )
        if amount != r["apply_amount"]:
            raise conflict("AMOUNT_CHANGED", "可退金额已变化，请驳回后重新申请")
        c.execute(
            "UPDATE refund_request SET refund_status='refunded',approved_amount=%s,remark=%s,approver_user_id=%s,approved_at=%s,refunded_at=%s,updated_at=%s WHERE id=%s",
            (amount, body.note, actor_id, now, now, now, refund_id),
        )
        c.execute(
            "UPDATE order_item SET order_item_status='refunded',updated_at=%s WHERE id=%s",
            (now, item["id"]),
        )
        total = Decimal(order["refund_amount"] or 0) + amount
        status = (
            "refunded"
            if total >= Decimal(order["paid_amount"] or 0)
            else "partial_refunded"
        )
        c.execute(
            "UPDATE `order` SET refund_amount=%s,order_status=%s,updated_at=%s WHERE id=%s",
            (total, status, now, order["id"]),
        )
        payment_total = Decimal(payment["refund_amount"] or 0) + amount
        c.execute(
            "UPDATE payment_record SET refund_amount=%s,payment_status=%s,refund_at=%s,updated_at=%s WHERE id=%s",
            (
                payment_total,
                "refunded"
                if payment_total >= payment["amount"]
                else "partial_refunded",
                now,
                now,
                payment["id"],
            ),
        )
        c.execute(
            "UPDATE student_cohort_rel SET enroll_status='refunded',cancelled_at=%s,updated_at=%s WHERE order_item_id=%s",
            (now, now, item["id"]),
        )
        return {
            "id": refund_id,
            "status": "refunded",
            "amount": str(amount),
            "simulated": True,
        }

    return transact(
        f"review:{refund_id}:{body.operation_id}", body.model_dump(), action
    )


class TicketInput(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    description: str = Field(min_length=4, max_length=5000)
    ticket_type: Literal["after_sales", "complaint", "refund"] = "after_sales"
    order_item_id: int | None = None
    operation_id: str = Field(min_length=8, max_length=100)


@router.post("/tickets")
def create_ticket(body: TicketInput, user_id: User):
    def action(c):
        c.execute(
            "SELECT id FROM student_profile WHERE user_id=%s AND yn=1", (user_id,)
        )
        student = c.fetchone()
        if not student:
            raise not_found("STUDENT_NOT_FOUND", "学员不存在")
        if body.order_item_id:
            c.execute(
                "SELECT institution_id FROM order_item WHERE id=%s AND user_id=%s",
                (body.order_item_id, user_id),
            )
            item = c.fetchone()
            if not item:
                raise not_found("ORDER_NOT_FOUND", "关联订单不属于当前学员")
            institution = item["institution_id"]
        else:
            c.execute("SELECT id FROM org_institution WHERE yn=1 ORDER BY id LIMIT 1")
            institution = c.fetchone()["id"]
        now, number = local_now(), make_no("TK")
        c.execute(
            """INSERT INTO service_ticket (institution_id,ticket_no,user_id,student_id,
            order_item_id,ticket_type,ticket_source,priority_level,ticket_status,title,ticket_content,
            yn,created_at,updated_at) VALUES (%s,%s,%s,%s,%s,%s,'customer_service','medium','pending',%s,%s,1,%s,%s)""",
            (
                institution,
                number,
                user_id,
                student["id"],
                body.order_item_id,
                body.ticket_type,
                body.title,
                body.description,
                now,
                now,
            ),
        )
        return {"id": c.lastrowid, "number": number, "status": "pending"}

    return transact(f"ticket:{user_id}:{body.operation_id}", body.model_dump(), action)


@router.get("/tickets")
def tickets(user_id: User):
    return fetch_all(
        "SELECT id,ticket_no,title,ticket_content,ticket_status,created_at,updated_at FROM service_ticket WHERE user_id=%s ORDER BY id DESC LIMIT 100",
        (user_id,),
    )


def ticket_detail(ticket_id: int, user_id: int | None):
    row = fetch_one(
        "SELECT * FROM service_ticket WHERE id=%s"
        + (" AND user_id=%s" if user_id else ""),
        (ticket_id, user_id) if user_id else (ticket_id,),
    )
    if not row:
        raise not_found("TICKET_NOT_FOUND", "工单不存在")
    row["records"] = fetch_all(
        "SELECT id,follow_user_id,follow_type,follow_content,followed_at FROM service_ticket_follow_record WHERE ticket_id=%s"
        + (" AND follow_type<>'internal_note'" if user_id else "")
        + " ORDER BY id",
        (ticket_id,),
    )
    return row


@router.get("/tickets/{ticket_id}")
def get_ticket(ticket_id: int, user_id: User):
    return ticket_detail(ticket_id, user_id)


class MessageInput(BaseModel):
    content: str = Field(min_length=1, max_length=5000)
    internal: bool = False
    close: bool = False
    operation_id: str = Field(min_length=8, max_length=100)


def add_record(ticket_id: int, body: MessageInput, user_id: int | None):
    def action(c):
        c.execute("SELECT * FROM service_ticket WHERE id=%s FOR UPDATE", (ticket_id,))
        ticket = c.fetchone()
        if not ticket or (user_id and ticket["user_id"] != user_id):
            raise not_found("TICKET_NOT_FOUND", "工单不存在")
        if ticket["ticket_status"] == "closed":
            raise conflict("TICKET_CLOSED", "工单已结单，请提交新工单")
        if user_id and (body.internal or body.close):
            raise forbidden("ADMIN_REQUIRED", "学员不能写内部备注或结单")
        actor = user_id
        if not actor:
            c.execute(
                "SELECT user_id FROM staff_profile WHERE yn=1 ORDER BY id LIMIT 1"
            )
            actor = c.fetchone()["user_id"]
        now = local_now()
        c.execute(
            """INSERT INTO service_ticket_follow_record
            (ticket_id,follow_user_id,follow_type,follow_channel,follow_result,follow_content,followed_at,created_at,updated_at)
            VALUES (%s,%s,%s,'user_app',%s,%s,%s,%s,%s)""",
            (
                ticket_id,
                actor,
                "internal_note" if body.internal else "reply_user",
                "resolved" if body.close else "pending_follow_up",
                body.content,
                now,
                now,
                now,
            ),
        )
        status = (
            "closed"
            if body.close
            else ("in_progress" if not user_id else ticket["ticket_status"])
        )
        c.execute(
            "UPDATE service_ticket SET ticket_status=%s,updated_at=%s,closed_at=%s,first_response_at=COALESCE(first_response_at,%s) WHERE id=%s",
            (
                status,
                now,
                now if body.close else None,
                now if not user_id else None,
                ticket_id,
            ),
        )
        return {"id": ticket_id, "status": status, "record_id": c.lastrowid}

    return transact(
        f"record:{user_id or 'admin'}:{ticket_id}:{body.operation_id}",
        body.model_dump(),
        action,
    )


@router.post("/tickets/{ticket_id}/messages")
def student_message(ticket_id: int, body: MessageInput, user_id: User):
    return add_record(ticket_id, body, user_id)


@router.get("/admin/tickets/{ticket_id}", dependencies=[Depends(admin)])
def admin_ticket(ticket_id: int):
    return ticket_detail(ticket_id, None)


@router.post("/admin/tickets/{ticket_id}/messages", dependencies=[Depends(admin)])
def admin_message(ticket_id: int, body: MessageInput):
    return add_record(ticket_id, body, None)


@router.get("/admin/{kind}", dependencies=[Depends(admin)])
def admin_list(
    kind: str,
    q: str = "",
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
):
    sources = {
        "students": (
            "student_profile t JOIN sys_user u ON u.id=t.user_id",
            "t.id,t.user_id,u.real_name,u.nickname,t.created_at",
            "u.real_name",
        ),
        "courses": ("series t", "t.*", "t.series_name"),
        "cohorts": ("series_cohort t", "t.*", "t.cohort_name"),
        "orders": ("`order` t", "t.*", "t.order_no"),
        "refunds": ("refund_request t", "t.*", "t.refund_no"),
        "tickets": ("service_ticket t", "t.*", "t.title"),
        "learning": ("student_cohort_rel t", "t.*", "t.enroll_status"),
    }
    if kind not in sources:
        raise not_found("UNKNOWN_RESOURCE", "未知查询类型")
    table, fields, search = sources[kind]
    where = f"WHERE {search} LIKE %s"
    total = fetch_one(f"SELECT COUNT(*) n FROM {table} {where}", ("%" + q + "%",))["n"]
    rows = fetch_all(
        f"SELECT {fields} FROM {table} {where} ORDER BY t.id DESC LIMIT %s OFFSET %s",
        ("%" + q + "%", size, (page - 1) * size),
    )
    return {"items": rows, "total": total, "page": page, "size": size}


@router.get("/admin/learning/{user_id}/{cohort_id}", dependencies=[Depends(admin)])
def admin_learning(user_id: int, cohort_id: int):
    from .routers.enrollments import get_my_cohort_progress

    return get_my_cohort_progress(cohort_id, user_id)["data"]
