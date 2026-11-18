# payments.py

## import

```python
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Header, Path, Query
from pydantic import BaseModel, Field

from ..config import DEMO_PAYMENT_SIGNATURE
from ..database import db_cursor, fetch_all, fetch_one
from ..dependencies import get_current_user_id
from ..errors import bad_request, conflict, not_found, unauthorized
from ..response import ok
from ..utils import count_total, format_datetime, local_now, make_no, money, offset_limit
```

`Header` 只在这个文件出现——支付回调要读 `X-Demo-Payment-Signature`。`DEMO_PAYMENT_SIGNATURE` 也从 `config` 带进来。

---

## `L18` router

```python
router = APIRouter(prefix="/api/v1", tags=["payments"])
```

## `L20` PAYMENT_CHANNELS

```python
PAYMENT_CHANNELS = {"wechat_pay", "alipay", "bank_card"}
```

## `L21` REFUND_TYPES

```python
REFUND_TYPES = {
    "personal_reason",
    "course_unsatisfied",
    "schedule_conflict",
    "duplicate_purchase",
}
```

"""四个退款原因类型。需求文档里「收集退款类型」这一步的取值就来自这里"""

---

## `L29` OrderPaymentCreateRequest

```python
class OrderPaymentCreateRequest(BaseModel):
    paymentChannelCode: str = Field(description="支付渠道编码。可选值：wechat_pay、alipay、bank_card。")
```

"""只有一个字段——金额不由客户端传，取自订单的 `payable_amount`"""

## `L33` MockPaymentNotificationRequest

```python
class MockPaymentNotificationRequest(BaseModel):
    paymentNo: str = Field(description="支付流水号。")
    orderId: int = Field(description="订单 ID；必须与支付流水所属订单一致。")
    paymentChannelCode: str = Field(
        description="支付渠道编码；必须与支付流水的支付渠道一致。可选值：wechat_pay、alipay、bank_card。"
    )
    amount: Decimal = Field(description="支付渠道回传金额；必须与支付流水金额一致。")
    tradeStatus: str = Field(description="交易状态。可选值：paid、failed、closed。")
    thirdPartyTradeNo: str | None = Field(default=None, description="第三方交易号。")
```

"""模拟支付渠道的回调体。三个字段是**冗余的一致性校验项**——`orderId`、渠道、金额
   都必须和库里已有的支付记录吻合，任何一项不符都拒绝处理"""

## `L44` PaymentCloseRequest

```python
class PaymentCloseRequest(BaseModel):
    closeReason: str = Field(description="关闭原因；当前仅用于接口入参表达，不单独落库。")
```

"""描述里明确写了不落库。字段存在只是为了接口形态完整"""

## `L48` RefundRequestCreateRequest

```python
class RefundRequestCreateRequest(BaseModel):
    refundType: str = Field(
        description=(
            "退款类型。可选值：personal_reason、course_unsatisfied、"
            "schedule_conflict、duplicate_purchase。"
        )
    )
    refundReason: str = Field(description="退款原因。")
    applyAmount: Decimal = Field(description="申请退款金额。")
    remark: str | None = Field(default=None, description="备注。")
```

"""`applyAmount` 允许部分退款，所以它和订单实付金额不一定相等。
   需求文档里「收集订单号 → 退款原因 → 退款类型」三步，对应这里的后三个字段"""

---

## `L60` refund_payload

```python
def refund_payload(row: dict[str, Any]) -> dict[str, object]:
```

"""退款申请的单行格式。注意两个金额字段**没有过 `money()`**，直接把 `Decimal` 塞进响应，
   靠 FastAPI 的 `jsonable_encoder` 兜底转 float。其余文件的金额都显式转了，这里是个例外"""

## `L73` payment_payload

```python
def payment_payload(row: dict[str, Any]) -> dict[str, object]:
```

"""支付记录的单行格式。`amount` 走了 `money()`，和上面不一致"""

## `L86` ensure_order_item_owned

```python
def ensure_order_item_owned(order_item_id: int, current_user_id: int) -> dict[str, Any]:
```

"""订单明细归属校验。`tickets.py` 里有逐字相同的一份"""

## `L96` ensure_order_owned

```python
def ensure_order_owned(order_id: int, current_user_id: int) -> dict[str, Any]:
```

"""`orders.py` 里也有同名同实现的函数——两处各写一遍"""

## `L106` ensure_payment_owned

```python
def ensure_payment_owned(payment_id: int, current_user_id: int) -> dict[str, Any]:
```

"""支付记录没有 `user_id` 字段，所以要 JOIN `order` 表才能校验归属"""

---

## `L121` POST /orders/{order_id}/payments

```python
@router.post("/orders/{order_id}/payments")
def create_order_payment(
    body: Annotated[OrderPaymentCreateRequest, Body(description="创建支付单请求体。")],
    order_id: Annotated[int, Path(description="订单 ID。")],
    current_user_id: Annotated[int, Depends(get_current_user_id)],
):
```

"""创建支付单。只有 `pending` 状态的订单能建，其他状态抛 409 `ORDER_NOT_CREATABLE_FOR_PAYMENT`。

   **幂等**：同一订单已有 `pending` 的支付记录时不会新建，只更新支付渠道，复用原记录。
   所以用户反复点「去支付」不会堆出一串支付单。

   金额取订单的 `payable_amount`，客户端无法指定。响应里的 `paymentParams.mockToken`
   是假的占位符，没有真实调起支付渠道的能力"""

## `L191` GET /orders/{order_id}/payments

```python
@router.get("/orders/{order_id}/payments")
def list_order_payments(
    order_id: Annotated[int, Path(description="订单 ID。")],
    current_user_id: Annotated[int, Depends(get_current_user_id)],
):
```

"""某订单的全部支付记录，按创建时间倒序。**没有分页**，返回 `{list: [...]}`"""

## `L209` GET /payments/{payment_id}

```python
@router.get("/payments/{payment_id}")
def get_payment_detail(
    payment_id: Annotated[int, Path(description="支付记录 ID。")],
    current_user_id: Annotated[int, Depends(get_current_user_id)],
):
```

"""支付详情，比列表多出 `orderId`、`refundAmount`、`refundAt`"""

## `L232` POST /payments/{payment_id}/close

```python
@router.post("/payments/{payment_id}/close")
def close_payment(
    body: Annotated[PaymentCloseRequest, Body(description="关闭支付单请求体。")],
    payment_id: Annotated[int, Path(description="支付记录 ID。")],
    current_user_id: Annotated[int, Depends(get_current_user_id)],
):
```

"""关闭支付单。`closeReason` 必须非空，但内容不落库。

   只对 `pending` 生效，其他状态**静默跳过**——不报错，照常返回当前状态。
   所以对一个已支付的记录调关闭，会得到 `paymentStatusCode: "paid"`"""

## `L265` POST /payment-notifications/mock

```python
@router.post("/payment-notifications/mock")
def mock_payment_notification(
    body: Annotated[
        MockPaymentNotificationRequest,
        Body(description="模拟支付渠道异步回调请求体。"),
    ],
    payment_signature: Annotated[
        str | None,
        Header(
            alias="X-Demo-Payment-Signature",
            description="支付通知签名；默认值为 mock-payment-signature，可通过 DEMO_PAYMENT_SIGNATURE 环境变量覆盖。",
        ),
    ] = None,
):
```

"""**整个系统唯一的「支付成功」入口**。没有真实支付网关，前端要模拟付款就得调它。

   不需要 `X-User-Id`，改用 `X-Demo-Payment-Signature` 头校验——默认值
   `mock-payment-signature`，可从环境变量覆盖。签名不对抛 401 `INVALID_PAYMENT_SIGNATURE`。

   三重一致性校验：回调里的 `orderId`、`paymentChannelCode`、`amount` 必须与
   库中支付记录完全一致，任一不符抛 409。

   幂等：支付记录已是终态（paid / failed / closed / partial_refunded / refunded）时
   直接返回 `processed: false`，不重复处理。所以同一个回调重放是安全的。

   `tradeStatus` 为 `paid` 时，**一个事务里改四张表**：支付记录置 paid 并写第三方交易号、
   订单置 paid 并回填 `paid_amount` 和 `paid_at`、订单明细置 paid、
   优惠券领取记录置 used。落库顺序决定了任何一步失败都整体回滚。

   注意这里**不创建报名关系**——`student_cohort_rel` 是造数脚本生成的，
   支付成功后并没有代码去建。这是 mock 系统的边界，不是漏写"""

## `L380` POST /order-items/{order_item_id}/refund-requests

```python
@router.post("/order-items/{order_item_id}/refund-requests")
def create_refund_request(
    body: Annotated[RefundRequestCreateRequest, Body(description="创建退款申请请求体。")],
    order_item_id: Annotated[int, Path(description="订单明细 ID。")],
    current_user_id: Annotated[int, Depends(get_current_user_id)],
):
```

"""创建退款申请。挂的是**订单明细**不是订单——一个订单多项时能逐项退。

   四道前置检查：明细状态必须是 `paid` 或 `completed`（未支付不能退）、
   `applyAmount` 不超过明细的 `payable_amount`、该订单有可退的支付记录、
   该明细没有处理中的退款（`pending` / `approved`）。

   最后一条意味着同一明细同时只能有一个在途申请，被拒或退完才能再提。

   退款单号用 `make_no("RF")`。初始状态 `pending`，**本文件没有审批接口**——
   审批动作只能由外部或造数脚本完成"""

## `L458` GET /refund-requests

```python
@router.get("/refund-requests")
def list_refund_requests(
    current_user_id: Annotated[int, Depends(get_current_user_id)],
    status: Annotated[
        str | None,
        Query(description="退款状态。可选值：pending、approved、rejected、refunded。"),
    ] = None,
    page_no: Annotated[int, Query(alias="pageNo", description="页码，从 1 开始。")] = 1,
    page_size: Annotated[int, Query(alias="pageSize", description="每页条数，范围 1 到 100。")] = 20,
):
```

"""我的退款申请列表，可按状态筛"""

## `L502` GET /refund-requests/{refund_request_id}

```python
@router.get("/refund-requests/{refund_request_id}")
def get_refund_request_detail(
    refund_request_id: Annotated[int, Path(description="退款申请 ID。")],
    current_user_id: Annotated[int, Depends(get_current_user_id)],
):
```

"""退款申请详情。走的是内联 SQL 而不是 `ensure_*` helper——本文件三个查询接口里只有它不是"""

---

## 谁在用它

| 模块 | 关系 |
|---|---|
| `main.py` | `include_router(payments_router)` |
| `orders.py` | 不 import 本文件，但订单详情里的 `paymentSummary` / `refundSummary` 直接查这两张表 |
| `tickets.py` | 退款类工单必须带 `refundRequestId`，该 ID 就来自本文件创建的申请 |

`payment_record` / `refund_request` 两张表由本文件写。订单状态从 `pending` 变 `paid`
只发生在回调接口里——`orders.py` 自己没有改支付状态的路径。
