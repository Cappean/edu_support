# cart.py

## import

```python
from typing import Annotated

from fastapi import APIRouter, Body, Depends, Path
from pydantic import BaseModel, Field

from ..database import db_cursor, fetch_all, fetch_one
from ..dependencies import get_current_user_id
from ..errors import bad_request, not_found
from ..response import ok
from ..utils import format_datetime, local_now, money
```

---

## `L16` router

```python
router = APIRouter(prefix="/api/v1", tags=["cart"])
```

## `L18` CART_SOURCES

```python
CART_SOURCES = {"series_detail", "search_result", "recommendation", "activity_page"}
```

"""加入来源白名单。与 `favorites.py` 的 `FAVORITE_SOURCES` 内容一致，各自维护一份"""

## `L21` CartItemCreateRequest

```python
class CartItemCreateRequest(BaseModel):
    cohortId: int = Field(description="班次 ID。")
    cartSource: str = Field(
        description="加入来源。可选值：series_detail、search_result、recommendation、activity_page。"
    )
```

"""加购的是**班次**不是课程系列——同一个系列的不同期次可以同时在车里"""

## `L28` ensure_cohort

```python
def ensure_cohort(cohort_id: int) -> dict[str, object]:
```

"""查不到或已停用就抛 404，顺带带出 `series.delivery_mode`（后续判断线上线下要用）。

   注意：`orders.py` 和 `consultations.py` 里有**完全相同的一份**，三处各写一遍。
   改这里的查询条件不会影响另外两处"""

---

## `L43` GET /cart/items

```python
@router.get("/cart/items")
def list_cart_items(current_user_id: Annotated[int, Depends(get_current_user_id)]):
```

"""返回购物车**全部**内容，没有分页——`data` 是裸 list，不像别的接口包着
   `{list, pageNo, pageSize, total}`。客户端要按两种结构解析。

   `removed_at IS NULL` 才是「在车里」，被移除的记录仍在表中"""

## `L74` POST /cart/items

```python
@router.post("/cart/items")
def add_cart_item(
    body: Annotated[CartItemCreateRequest, Body(description="加入购物车请求体。")],
    current_user_id: Annotated[int, Depends(get_current_user_id)],
):
```

"""加入购物车，单价取自班次的 `sale_price` 快照。

   注意这里有个行为盲点：如果该班次**已经在车里**（`removed_at` 为空），
   函数直接返回旧 `itemId`，**不会刷新 `unit_price`**——班次涨价后，
   车里的价格仍是加购当时的价格。只有从「已移除」状态复活时才会更新价格和来源"""

## `L127` DELETE /cart/items/{item_id}

```python
@router.delete("/cart/items/{item_id}")
def remove_cart_item(
    item_id: Annotated[int, Path(description="购物车项 ID。")],
    current_user_id: Annotated[int, Depends(get_current_user_id)],
):
```

"""软删：把 `removed_at` 打上时间戳。

   `WHERE` 带 `user_id` 和 `removed_at IS NULL`，所以删别人的项、或者重复删同一项，
   SQL 影响 0 行，但**响应仍然返回 `{"removed": true}`**——客户端无法区分成功与空操作"""

---

## 谁在用它

| 谁 | 干什么 |
|---|---|
| `main.py` | `include_router(cart_router)` |
| `orders.py` | 不调用本文件。下单不需要先加购，可以从班次直接建单 |

`shopping_cart_item` 表只有本文件读写。下单流程**不会**自动清空购物车——买完了车里的东西还在。
