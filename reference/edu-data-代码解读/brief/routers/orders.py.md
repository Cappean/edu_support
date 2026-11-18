# orders.py

## import

```python
from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Path, Query
from pydantic import BaseModel, Field

from ..database import db_cursor, fetch_all, fetch_one
from ..dependencies import get_current_user_id
from ..errors import conflict, not_found
from ..response import ok
from ..utils import count_total, format_datetime, local_now, make_no, money, offset_limit
```

`db_cursor` 是唯一能拿事务的地方（`create_order`、`cancel_order` 用它同时改多张表），其余函数用 `fetch_one` / `fetch_all` 单条查。

---

## `L17` router

```python
router = APIRouter(prefix="/api/v1", tags=["orders"])
```

12 个 router 用同一个 prefix，各自带 tag。`main.py` 逐个 `include_router` 挂上去。

---

## `L20` OrderQuoteRequest

```python
class OrderQuoteRequest(BaseModel):
    cohortId: int = Field(description="班次 ID。")
    couponReceiveRecordId: int | None = Field(default=None, description="领券记录 ID。")
```

"""试算请求体。只有两个字段——试算不落库，不需要学员、渠道、备注"""

## `L25` OrderCreateRequest

```python
class OrderCreateRequest(BaseModel):
    studentId: int = Field(description="学员档案 ID。")
    cohortId: int = Field(description="班次 ID。")
    couponReceiveRecordId: int | None = Field(default=None, description="领券记录 ID。")
    orderSourceChannelId: int | None = Field(default=None, description="订单来源渠道 ID。")
    remark: str | None = Field(default=None, description="下单备注。")
```

"""比试算多三个字段。studentId 必填且必须属于当前用户；
   渠道字段是归因用的，站内自然下单不传"""

## `L33` OrderCancelRequest

```python
class OrderCancelRequest(BaseModel):
    reason: str = Field(description="取消原因。")
```

"""声明了必填，但 `cancel_order` 全程没读它——原因不落库"""

---

## `L37` ensure_student_owned

```python
def ensure_student_owned(student_id: int, current_user_id: int) -> dict[str, Any]:
```

"""查不到就抛 404。查询条件带 user_id，防止拿别人的 studentId 下单"""

## `L47` ensure_cohort

```python
def ensure_cohort(cohort_id: int) -> dict[str, Any]:
```

"""连 `series` 带出 `delivery_mode`，后续判断线上线下要用。这里查了 `yn = 1`"""

## `L62` ensure_channel

```python
def ensure_channel(channel_id: int) -> None:
```

"""只校验存在性，不返回行——调用方只要知道渠道合法就够了"""

## `L67` ensure_order_owned

```python
def ensure_order_owned(order_id: int, current_user_id: int) -> dict[str, Any]:
```

"""注意：**没有 `yn` 条件**。`order` 表压根没有 `yn` 字段，只有 `order_status`，
   已取消或已退款的订单仍然能查到——取消接口自己判状态，详情接口允许查历史单"""

## `L77` coupon_applicable_to_cohort

```python
def coupon_applicable_to_cohort(coupon_id: int, cohort_id: int) -> bool:
```

"""优惠券的适用范围判定。系列范围与分类范围**同时**满足才算适用；
   某一边没配置就视为不限制。一次调用返回两个布尔值，省掉两次往返"""

## `L116` validate_order_source_channel

```python
def validate_order_source_channel(
    current_user_id: int, cohort_id: int, order_source_channel_id: int | None
) -> None:
```

"""渠道归因校验，两种放行：没传渠道、或该用户在这班次压根没咨询记录。
   有咨询记录时，下单渠道必须与咨询渠道一致，否则抛 409"""

## `L150` coupon_discount

```python
def coupon_discount(
    receive_id: int | None, current_user_id: int, total: Decimal, cohort_id: int
) -> Decimal:
```

"""算这一单能减多少钱。三种情况抛 409：券不属于该用户/已用/过期、券不适用此班次、金额未达门槛。
   `discount` 类型按折扣率算，其他类型按固定额，且都封顶到订单总额"""

## `L179` available_coupon_receives

```python
def available_coupon_receives(
    current_user_id: int, total: Decimal, cohort_id: int
) -> list[dict[str, object]]:
```

"""列出该用户手上所有可用于此班次的券，每条带上算好的优惠金额。
   判定逻辑与 `coupon_discount` 一致——试算和真下单不会出现两个价"""

## `L227` order_list_payload

```python
def order_list_payload(row: dict[str, Any]) -> dict[str, object]:
```

"""订单列表的单行格式。列表接口用它，所以字段比详情接口少一大截"""

---

## `L238` POST /orders/quote

```python
@router.post("/orders/quote")
def quote_order(
    body: Annotated[OrderQuoteRequest, Body(description="订单试算请求体。")],
    current_user_id: Annotated[int, Depends(get_current_user_id)],
):
```

"""试算：算总价、算优惠、列出可用券，全程不写库。
   agent 在用户点「确认下单」之前应该先调这个，让用户看到实际要付多少"""

## `L257` POST /orders

```python
@router.post("/orders")
def create_order(
    body: Annotated[OrderCreateRequest, Body(description="创建订单请求体。")],
    current_user_id: Annotated[int, Depends(get_current_user_id)],
):
```

"""真正下单。一个事务里写 `order` 和 `order_item` 两张表，后者一条记录对应一个班次。
   订单初始状态 `pending`，此时还不算报名成功——要等支付。`service_period_days` 写死 90"""

## `L333` GET /orders

```python
@router.get("/orders")
def list_orders(
    current_user_id: Annotated[int, Depends(get_current_user_id)],
    status: Annotated[
        str | None,
        Query(description="订单状态。可选值：pending、paid、completed、cancelled、partial_refunded、refunded。"),
    ] = None,
    page_no: Annotated[int, Query(alias="pageNo", description="页码，从 1 开始。")] = 1,
    page_size: Annotated[int, Query(alias="pageSize", description="每页条数，范围 1 到 100。")] = 20,
):
```

"""按状态筛 + 分页。Python 变量名是 `page_no`，对外暴露的参数名靠 `alias` 变成 `pageNo`，
   所以调用方传的是 `?pageNo=1&pageSize=3`，传 `page_no` 会被忽略"""

## `L377` GET /orders/{order_id}

```python
@router.get("/orders/{order_id}")
def get_order_detail(
    order_id: Annotated[int, Path(description="订单 ID。")],
    current_user_id: Annotated[int, Depends(get_current_user_id)],
):
```

"""路径参数是**数字主键**，不是订单号。传 `ORD0000000001` 直接 422，因为类型是 `int`。
   响应把最近一条支付记录和退款汇总一起带出来，`paymentSummary` / `refundSummary` 可能为空的字段是 `None`"""

## `L429` POST /orders/{order_id}/cancel

```python
@router.post("/orders/{order_id}/cancel")
def cancel_order(
    body: Annotated[OrderCancelRequest, Body(description="取消订单请求体。")],
    order_id: Annotated[int, Path(description="订单 ID。")],
    current_user_id: Annotated[int, Depends(get_current_user_id)],
):
```

"""只允许取消 `pending` 状态，其他状态抛 409。
   一个事务同时改三张表：`order` 置 cancelled、`order_item` 置 cancelled、`payment_record` 里待支付的置 closed。
   `body.reason` 收了但没写进任何表"""

---

## 谁在用它

| 模块 | 干什么 |
|---|---|
| `app/main.py` | `include_router(orders_router)`，唯一引用本文件的地方 |
| `payments.py` | 不 import 本文件，直接查 `order` 表推进支付状态 |
| `tickets.py` | 同上，工单通过 `order_item_id` 关联，不经过本文件 |

router 之间互不 import。任何跨模块的操作都直接落到数据库上，所以改 `order` 表结构时，
`payments.py` 和 `tickets.py` 也会受影响，光看本文件发现不了。
