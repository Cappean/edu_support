# coupons.py

## import

```python
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Path, Query

from ..database import db_cursor, fetch_all, fetch_one
from ..dependencies import get_current_user_id
from ..errors import conflict, not_found
from ..response import ok
from ..utils import (
    count_total,
    format_datetime,
    local_now,
    make_no,
    money,
    offset_limit,
)
```

`cast` 在本文件用得很密——查出来的行是 `dict[str, object]`，取值后要显式告诉类型检查器是什么类型。运行时 `cast` 什么都不做。

---

## `L24` router

```python
router = APIRouter(prefix="/api/v1", tags=["coupons"])
```

## `L27` ensure_coupon

```python
def ensure_coupon(coupon_id: int) -> dict[str, object]:
```

"""按主键取券，停用的（`yn = 0`）算不存在，抛 404。

   定义在这里但**本文件没有调用点**——文件内的逻辑都是直接写 SQL"""

## `L34` coupon_payload

```python
def coupon_payload(row: dict[str, object]) -> dict[str, object]:
```

"""券的对外格式。五个数值字段都要转：金额走 `money()` 变 float，
   `discountRate` 单独 `float()`（它不在 `money` 的签名里），时间走 `format_datetime()`。

   注意 `discountRate` 为 `None` 时也返回 `None`——固定金额券没有折扣率"""

## `L55` user_receive_count

```python
def user_receive_count(coupon_id: int, current_user_id: int) -> int:
```

"""查某用户领过某券几次。注意它**不筛 `yn`**，软删的领取记录也算进去。

   同样是定义在文件里但没有调用点，`/coupons/available` 内联了这条统计"""

---

## `L67` GET /coupons/available

```python
@router.get("/coupons/available")
def list_available_coupons(
    current_user_id: Annotated[int, Depends(get_current_user_id)],
    series_id: Annotated[
        int | None, Query(alias="seriesId", description="课程系列 ID。")
    ] = None,
    category_id: Annotated[
        int | None,
        Query(
            alias="categoryId",
            description="课程分类 ID；分类数量较多，不在接口文档中展开枚举。",
        ),
    ] = None,
):
```

"""我还能领的券。三个基础条件：启用、在有效期内、总库存没领完。再加一条个人条件：
   我领过的次数少于 `per_user_limit`。

   `seriesId` / `categoryId` 是可选的过滤条件，逻辑和 `orders.py` 的
   `coupon_applicable_to_cohort` 一致：**券没配范围就通吃，配了则必须匹配**。

   返回裸 list，**没有分页**，硬上限 50 条（按到期时间升序，快过期的排前面）"""

## `L140` POST /coupons/{coupon_id}/receive

```python
@router.post("/coupons/{coupon_id}/receive")
def receive_coupon(
    coupon_id: Annotated[int, Path(description="优惠券 ID。")],
    current_user_id: Annotated[int, Depends(get_current_user_id)],
):
```

"""领券。这是全项目**唯一使用行锁**的地方：`SELECT ... FOR UPDATE` 锁住券行，
   防止并发领取超出库存。

   校验顺序：券存在 → 已过期（409 `COUPON_EXPIRED`）→ 库存不足（409 `COUPON_OUT_OF_STOCK`）
   → 个人领取达上限（409 `COUPON_RECEIVE_LIMIT_EXCEEDED`）。任一失败整个事务回滚，库存不会减。

   成功后 `coupon.receive_count` 加一。领取记录的 `receive_source` 固定写 `user_receive`，
   另一种取值是系统发放"""

## `L205` GET /me/coupons

```python
@router.get("/me/coupons")
def list_my_coupons(
    current_user_id: Annotated[int, Depends(get_current_user_id)],
    status: Annotated[
        str | None,
        Query(description="领券状态。可选值：unused、used、expired。"),
    ] = None,
    page_no: Annotated[int, Query(alias="pageNo", description="页码，从 1 开始。")] = 1,
    page_size: Annotated[
        int, Query(alias="pageSize", description="每页条数，范围 1 到 100。")
    ] = 20,
):
```

"""我的券包，按领取时间倒序。

   返回里**没有 `couponId`**——只有 `receiveId`。下单时要用的是 `receiveId`
   （`orders.py` 的 `couponReceiveRecordId` 就是这个），所以券包的字段刚好够用。

   注意 `receive_status` 是库里存的静态值，过了 `expired_at` 不会自动变 `expired`——
   `status=expired` 筛的是被系统改过状态的那些"""

---

## 谁在用它

| 模块 | 关系 |
|---|---|
| `main.py` | `include_router(coupons_router)` |
| `orders.py` | **不 import 本文件**，`coupon_discount` 自己查 `coupon_receive_record` 和 `coupon` 表 |

两处对「券是否可用于某班次」的判定是两套独立实现：本文件写 SQL 过滤，
`orders.py` 写成 Python 函数。改判定规则要同步改两处，否则会出现「券包显示可用、下单却报不适用」。
