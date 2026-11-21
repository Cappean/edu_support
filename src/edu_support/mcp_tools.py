"""MCP protocol adapter: identity is injected by the trusted executor, never the model."""

from typing import Literal

import httpx
from itsdangerous import BadSignature, URLSafeTimedSerializer
from mcp.server.fastmcp import FastMCP

from . import storage
from .config import SECRET
from .education import EducationError, ReferenceHTTP
from .knowledge import KeywordSearch

signer = URLSafeTimedSerializer(SECRET, salt="tool-capability")
mcp = FastMCP(
    "教育客服业务能力",
    stateless_http=True,
    json_response=True,
    streamable_http_path="/",
)


def issue_capability(user_id, run_id):
    return signer.dumps({"user_id": user_id, "run_id": run_id})


def identity(capability):
    try:
        return signer.loads(capability, max_age=600)
    except BadSignature:
        raise ValueError("无效或过期的工具执行身份") from None


async def education(capability, method, path, **kwargs):
    who = identity(capability)
    async with httpx.AsyncClient(timeout=25) as client:
        try:
            return await ReferenceHTTP(client).request(
                method, path, user_id=who["user_id"], **kwargs
            )
        except EducationError as error:
            return {
                "ok": False,
                "error": {"code": error.code, "message": error.message},
            }


def require_intent(capability, kind):
    who = identity(capability)
    run = storage.one("SELECT input FROM runs WHERE id=?", (who["run_id"],))
    # Agent persisted explicit intent, including source message IDs, before invoking
    # a write tool. Executor also enforces the same state; MCP is not a bypass.
    if not run:
        raise ValueError("办理请求不存在")
    task = storage.one(
        "SELECT t.* FROM tasks t JOIN runs r ON r.conversation_id=t.conversation_id WHERE r.id=? AND t.kind=? AND t.status='active'",
        (who["run_id"], kind),
    )
    if not task:
        raise ValueError("当前没有相应的明确办理诉求，请先澄清用户需求")
    return who


@mcp.tool()
async def search_courses(query: str, capability: str):
    """按课程名称关键词查询课程和在售班次信息。"""
    return await education(
        capability, "GET", "/api/v1/series", params={"keyword": query, "pageSize": 10}
    )


@mcp.tool()
async def get_course_detail(course_id: int, capability: str):
    """获取课程详情及对应班次。course_id 来自课程查询结果。"""
    detail = await education(capability, "GET", f"/api/v1/series/{course_id}")
    cohorts = await education(capability, "GET", f"/api/v1/series/{course_id}/cohorts")
    return {"detail": detail, "cohorts": cohorts}


@mcp.tool()
async def list_my_orders(keyword: str, capability: str):
    """查询当前学员的订单和订单明细。keyword 可为订单号或课程名，空字符串查询全部。退款使用返回的 order_item_id。"""
    return await education(
        capability, "GET", "/support/orders", params={"keyword": keyword}
    )


@mcp.tool()
async def list_my_cohorts(capability: str):
    """查询当前学员已报名的班次，获取班次 ID 后可查询学习进度。"""
    return await education(capability, "GET", "/api/v1/me/cohorts")


@mcp.tool()
async def get_my_learning_progress(cohort_id: int, capability: str):
    """查询当前学员指定班次的考勤、视频、作业、考试学习进度。"""
    return await education(
        capability, "GET", f"/api/v1/me/cohorts/{cohort_id}/progress"
    )


@mcp.tool()
async def check_refund_eligibility(order_item_id: int, capability: str):
    """校验退款资格并由系统计算全额可退金额；不创建申请。"""
    return await education(
        capability, "GET", f"/support/refunds/eligibility/{order_item_id}"
    )


@mcp.tool()
async def submit_refund_application(
    order_item_id: int,
    reason: str,
    refund_type: Literal[
        "personal_reason",
        "course_unsatisfied",
        "schedule_conflict",
        "duplicate_purchase",
    ],
    capability: str,
):
    """用户明确要求退款且订单、原因、类型齐全时提交全额退款申请。仅咨询政策不可调用。不表示退款已成功。"""
    who = require_intent(capability, "refund")
    return await education(
        capability,
        "POST",
        "/support/refunds",
        json={
            "order_item_id": order_item_id,
            "reason": reason,
            "refund_type": refund_type,
            "operation_id": f"{who['run_id']}:{order_item_id}",
        },
    )


@mcp.tool()
async def list_my_refunds(capability: str):
    """查询当前学员退款申请及审核结果。"""
    return await education(capability, "GET", "/support/refunds")


@mcp.tool()
async def submit_ticket(
    title: str,
    description: str,
    ticket_type: Literal["after_sales", "complaint", "refund"],
    capability: str,
    order_item_id: int | None = None,
):
    """用户明确要求提交工单/投诉，或同意兜底建单后提交。标题和具体问题必填；订单选填，不得编造。"""
    who = require_intent(capability, "ticket")
    return await education(
        capability,
        "POST",
        "/support/tickets",
        json={
            "title": title,
            "description": description,
            "ticket_type": ticket_type,
            "order_item_id": order_item_id,
            "operation_id": f"{who['run_id']}:ticket",
        },
    )


@mcp.tool()
async def list_my_tickets(capability: str):
    """查询当前学员的工单列表和状态。"""
    return await education(capability, "GET", "/support/tickets")


@mcp.tool()
async def get_my_ticket(ticket_id: int, capability: str):
    """查询当前学员工单详情、全部公开回复和处理结果，不含内部备注。"""
    return await education(capability, "GET", f"/support/tickets/{ticket_id}")


@mcp.tool()
async def append_my_ticket_message(ticket_id: int, content: str, capability: str):
    """按用户明确要求为未结单的本人问题工单补充说明。"""
    who = require_intent(capability, "ticket_message")
    return await education(
        capability,
        "POST",
        f"/support/tickets/{ticket_id}/messages",
        json={"content": content, "operation_id": f"{who['run_id']}:{ticket_id}"},
    )


@mcp.tool()
async def search_knowledge(query: str, capability: str):
    """查询已发布 FAQ 和政策文章。无结果时说明没有依据，不编造政策。返回来源引用。"""
    identity(capability)
    return KeywordSearch().search(query)


@mcp.tool()
async def get_knowledge_item(item_id: str, capability: str):
    """按知识 ID 获取已发布条目的完整正文和版本。"""
    identity(capability)
    return storage.one(
        "SELECT id,kind,title,body,version FROM knowledge WHERE id=? AND status='published'",
        (item_id,),
    ) or {"error": "内容不存在或已下架"}
