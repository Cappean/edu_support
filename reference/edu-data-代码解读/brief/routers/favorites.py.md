# favorites.py

## import

```python
from typing import Annotated

from fastapi import APIRouter, Body, Depends, Path, Query
from pydantic import BaseModel, Field

from ..database import db_cursor, fetch_all
from ..dependencies import get_current_user_id
from ..errors import bad_request, not_found
from ..response import ok
from ..utils import count_total, format_datetime, local_now, offset_limit
```

---

## `L16` router

```python
router = APIRouter(prefix="/api/v1", tags=["favorites"])
```

## `L18` FAVORITE_SOURCES

```python
FAVORITE_SOURCES = {"series_detail", "search_result", "recommendation", "activity_page"}
```

"""收藏来源白名单。和 `cart.py` 的 `CART_SOURCES` 内容完全相同，但两个文件各定义一份，
   加新来源要改两处"""

## `L21` FavoriteCreateRequest

```python
class FavoriteCreateRequest(BaseModel):
    favoriteSource: str = Field(
        description="收藏来源。可选值：series_detail、search_result、recommendation、activity_page。"
    )
```

"""只有一个字段。来源是必填的，不传会被 pydantic 拦成 422"""

## `L27` ensure_series

```python
def ensure_series(series_id: int) -> dict[str, object]:
```

"""查不到（含已下架）就抛 404。注意用的是 `fetch_all` 再取 `[0]`，不是 `fetch_one`——
   结果一样但多绕一层

   `sale_status = 'on_sale'` 只限制「收藏」这个动作：下架课程不能新收藏，
   但已经收藏过的下架课程仍会出现在下面的列表里，因为列表只查 `series_favorite` 不筛课程状态"""

---

## `L37` GET /me/favorites

```python
@router.get("/me/favorites")
def list_my_favorites(
    current_user_id: Annotated[int, Depends(get_current_user_id)],
    page_no: Annotated[int, Query(alias="pageNo", description="页码，从 1 开始。")] = 1,
    page_size: Annotated[int, Query(alias="pageSize", description="每页条数，范围 1 到 100。")] = 20,
):
```

"""分页返回我收藏的课程。`yn = 1` 过滤掉已取消的，课程名靠 JOIN `series` 带出。
   响应里没有课程价格和班次信息——想看详情要再调课程接口"""

## `L83` POST /series/{series_id}/favorite

```python
@router.post("/series/{series_id}/favorite")
def favorite_series(
    body: Annotated[FavoriteCreateRequest, Body(description="收藏课程请求体。")],
    series_id: Annotated[int, Path(description="课程系列 ID。")],
    current_user_id: Annotated[int, Depends(get_current_user_id)],
):
```

"""幂等设计：重复收藏不报错，也不会产生第二行记录。

   取消过的收藏（`yn = 0`）会被 UPDATE 复活而不是 INSERT 新行，所以 `favoriteId` 保持稳定。
   响应里的 `created` 靠 `yn == 0` 反推——它表示「这次是从取消状态恢复的」，
   不是「这行记录刚插入的」"""

## `L131` DELETE /series/{series_id}/favorite

```python
@router.delete("/series/{series_id}/favorite")
def unfavorite_series(
    series_id: Annotated[int, Path(description="课程系列 ID。")],
    current_user_id: Annotated[int, Depends(get_current_user_id)],
):
```

"""软删，只把 `yn` 置 0，不删行。

   不校验课程是否存在，也不校验之前是否真的收藏过——取消一个从没收藏过的课程
   照样返回 `{"favorited": false}`，客户端分辨不出来"""

---

## 谁在用它

| 谁 | 干什么 |
|---|---|
| `main.py` | `include_router(favorites_router)` |
| 掌柜小二 agent | 「我收藏了哪些课」这类查询，或收藏作为转化动作 |

收藏表 `series_favorite` 只有本文件读写，其他 router 不碰。
