# tickets.py

## import

```python
from datetime import datetime
from typing import Annotated, cast

from fastapi import APIRouter, Body, Depends, Path, Query
from pydantic import BaseModel, Field

from ..database import db_cursor, fetch_all, fetch_one
from ..dependencies import get_current_user_id
from ..errors import bad_request, conflict, not_found
from ..response import ok
from ..utils import count_total, format_datetime, local_now, make_no, offset_limit
```

---

## `L17` router

```python
router = APIRouter(prefix="/api/v1", tags=["tickets"])
```

## `L19` 三个白名单

```python
TICKET_TYPES = {"after_sales", "complaint", "refund"}
PRIORITY_LEVELS = {"low", "medium", "high", "urgent"}
TICKET_SOURCES = {"user_app", "customer_service"}
```

"""工单类型只有三种。`refund` 类型有额外约束——必须关联一条退款申请（见 `create_service_ticket`）。

   `ticketSource` 区分「用户在 App 里提的」和「客服代建的」，这条记录决定后续责任归属"""

---

## `L24` ServiceTicketCreateRequest

```python
class ServiceTicketCreateRequest(BaseModel):
    ticketType: str = Field(description="工单类型。可选值：after_sales、complaint、refund。")
    priorityLevel: str = Field(description="优先级。可选值：low、medium、high、urgent。")
    ticketSource: str = Field(description="工单来源。可选值：user_app、customer_service。")
    title: str = Field(description="标题。")
    ticketContent: str = Field(description="工单内容。")
    studentId: int = Field(description="学员档案 ID。")
    orderItemId: int = Field(description="订单明细 ID。")
    refundRequestId: int | None = Field(default=None, description="退款申请 ID。")
```

"""八个字段，只有 `refundRequestId` 可选——**工单必须挂在一条订单明细上**，
不能凭空提一个「我就是要投诉」的工单。

   三个白名单字段是 `str` 而不是 `Literal`/枚举，非法值靠 `validate_ticket_body` 抛 400，
   不会变成 422"""

## `L35` SatisfactionSurveyCreateRequest

```python
class SatisfactionSurveyCreateRequest(BaseModel):
    scoreValue: int = Field(description="满意度评分，取值范围 1 到 5。")
    commentText: str | None = Field(default=None, description="反馈内容。")
```

"""范围校验不在 pydantic 里做，在接口函数开头手写 `if not 1 <= scoreValue <= 5`"""

---

## `L40` ticket_list_payload

```python
def ticket_list_payload(row: dict[str, object]) -> dict[str, object]:
```

"""工单列表的单行格式。只给五个字段，**没有工单内容**——内容太长，列表不展示"""

## `L52` validate_ticket_body

```python
def validate_ticket_body(body: ServiceTicketCreateRequest) -> None:
```

"""五道检查：三个白名单取值，以及 `title` / `ticketContent` 去空格后不能为空。
   全抛 400 `bad_request`，错误码各不相同"""

## `L65` ensure_order_item_owned

```python
def ensure_order_item_owned(order_item_id: int, current_user_id: int) -> dict[str, object]:
```

"""校验订单明细归属，查不到抛 404。返回整行——调用方要用它的 `institution_id`
   和 `student_id`」

## `L75` ensure_student_owned

```python
def ensure_student_owned(student_id: int, current_user_id: int) -> dict[str, object]:
```

"""与 `orders.py` 的同名函数逐字相同，两处各写一遍"""

## `L85` ensure_refund_owned

```python
def ensure_refund_owned(
    refund_request_id: int | None, current_user_id: int
) -> dict[str, object]:
```

"""退款申请归属校验。`refund_request_id` 为 `None` 时直接抛 400——
   「退款工单必须关联退款申请」这条规则实现在这里"""

## `L99` find_assignee

```python
def find_assignee(institution_id: int) -> dict[str, object] | None:
```

"""挑工单处理人：该机构下第一个 `role_category` 属于 `service`、`operations`、`management`
   的在职职员。

   注意和 `consultations.py` 的顾问分配规则**不一样**——那边取的是 `sales` / `service`。
   同一个机构，咨询和工单会落到不同的人身上。

   返回 `None` 时工单照样创建，`assignee_user_id` 留空（不像咨询那边直接 409 拒绝——见下条）"""

## `L115` ensure_ticket_owned

```python
def ensure_ticket_owned(ticket_id: int, current_user_id: int) -> dict[str, object]:
```

"""工单归属校验，带 `yn = 1`。三个查询类接口都先过它"""

---

## `L125` GET /service-tickets

```python
@router.get("/service-tickets")
def list_service_tickets(
    current_user_id: Annotated[int, Depends(get_current_user_id)],
    ticket_type: Annotated[
        str | None,
        Query(alias="ticketType", description="工单类型。可选值：after_sales、complaint、refund。"),
    ] = None,
    ticket_status: Annotated[
        str | None,
        Query(alias="ticketStatus", description="工单状态。可选值：pending、in_progress、closed。"),
    ] = None,
    page_no: Annotated[int, Query(alias="pageNo", description="页码，从 1 开始。")] = 1,
    page_size: Annotated[int, Query(alias="pageSize", description="每页条数，范围 1 到 100。")] = 20,
):
```

"""我的工单列表，可按类型和状态筛。查询用 `SELECT *` 但输出只取五个字段"""

## `L176` POST /service-tickets

```python
@router.post("/service-tickets")
def create_service_ticket(
    body: Annotated[ServiceTicketCreateRequest, Body(description="创建服务工单请求体。")],
    current_user_id: Annotated[int, Depends(get_current_user_id)],
):
```

"""创建工单。校验链条比别的接口长：

   白名单检查 → 订单明细归属 → 学员档案归属 → **学员必须就是订单明细上的那个学员**
   → 若是退款工单则校验退款申请归属且必须对同一条明细 → 非退款工单不许带退款申请。

   最后会尝试自动分配处理人，**分配不到也照样建单**（`assignee_user_id` 为 `None`），
   这点和咨询接口不同——那边没人就 409。

   工单号用 `make_no("TK")`，也就是 `TK` + 微秒时间戳，形如 `TK20261118103012345678`。
   而造数脚本生成的工单号是 `TKT000000000001` 这种 15 位流水号——
   **两种格式并存**，按工单号做前缀匹配时要注意"""

## `L233` GET /service-tickets/{ticket_id}

```python
@router.get("/service-tickets/{ticket_id}")
def get_service_ticket_detail(
    ticket_id: Annotated[int, Path(description="工单 ID。")],
    current_user_id: Annotated[int, Depends(get_current_user_id)],
):
```

"""工单详情。比列表多出 `ticketContent` 和 `refundRequestId`。

   注意**没有返回处理人、优先级、工单来源**——这些字段存了但查不出来"""

## `L256` GET /service-tickets/{ticket_id}/follow-records

```python
@router.get("/service-tickets/{ticket_id}/follow-records")
def list_service_ticket_follow_records(
    ticket_id: Annotated[int, Path(description="工单 ID。")],
    current_user_id: Annotated[int, Depends(get_current_user_id)],
):
```

"""工单的跟进流水，按时间正序（和其他接口的倒序相反）。

   本文件**没有任何接口能创建跟进记录**——那些数据只能由造数脚本或外部系统写入"""

## `L286` POST /service-tickets/{ticket_id}/satisfaction-surveys

```python
@router.post("/service-tickets/{ticket_id}/satisfaction-surveys")
def create_satisfaction_survey(
    body: Annotated[SatisfactionSurveyCreateRequest, Body(description="提交工单满意度评价请求体。")],
    ticket_id: Annotated[int, Path(description="工单 ID。")],
    current_user_id: Annotated[int, Depends(get_current_user_id)],
):
```

"""给工单打满意度。两个前置条件：工单状态必须是 `closed`（否则 409 `TICKET_NOT_CLOSED`），
   且该工单还没有有效评价（否则 409 `SURVEY_EXISTS`）。

   评分范围 1~5 在函数体里手写检查，越界抛 400。工单没关闭时提交会被拒——
   所以 agent 想引导用户评价，得先确认工单已结单"""

---

## 谁在用它

| 模块 | 关系 |
|---|---|
| `main.py` | `include_router(tickets_router)` |
| `orders.py` | 无直接关系，但工单必须挂在 `order_item` 上，下单流程要先生成明细 |
| `payments.py` | 无直接关系，退款工单通过 `refund_request_id` 关联，走的是 `refund_request` 表 |

`service_ticket` / `service_ticket_follow_record` / `service_ticket_satisfaction_survey`
三张表由本文件读写。它是需求文档里「工单提交」任务流程的唯一落地接口。
