# interactions.py

## import

```python
import json
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Path, Query
from pydantic import BaseModel, Field

from ..database import db_cursor, fetch_all, fetch_one
from ..dependencies import get_current_user_id, get_optional_current_user_id
from ..errors import bad_request, conflict, not_found
from ..response import ok
from ..utils import count_total, format_datetime, local_now, make_no, offset_limit
```

---

## `L17` router

```python
router = APIRouter(prefix="/api/v1", tags=["interactions"])
```

## `L20` CohortReviewCreateRequest

```python
class CohortReviewCreateRequest(BaseModel):
    scoreOverall: int = Field(description="综合评分，取值范围 1 到 5。")
    scoreTeacher: int = Field(description="教师评分，取值范围 1 到 5。")
    scoreContent: int = Field(description="内容评分，取值范围 1 到 5。")
    scoreService: int = Field(description="服务评分，取值范围 1 到 5。")
    reviewTags: list[str] = Field(default_factory=list, description="评价标签。")
    reviewContent: str | None = Field(default=None, description="评价内容。")
    anonymousFlag: int = Field(default=0, description="是否匿名。可选值：0 非匿名、1 匿名。")
```

"""四个评分必填，标签和内容可选。

   注意：pydantic 的 `Field(description=...)` **不做范围校验**，写「1 到 5」只是文档说明，
   真正的校验在下面的 `validate_scores` 里，靠 `bad_request` 抛 400 而不是 422"""

## `L30` validate_scores

```python
def validate_scores(body: CohortReviewCreateRequest) -> None:
```

"""检查四个评分是否都在 1~5，以及 `anonymousFlag` 是否只取 0 或 1。
   越界抛 400 `INVALID_SCORE` / `INVALID_ANONYMOUS_FLAG`"""

## `L38` ensure_cohort_rel

```python
def ensure_cohort_rel(cohort_id: int, current_user_id: int) -> dict[str, Any]:
```

"""要求当前用户在该班次有**有效履约关系**（`enroll_status` 不是 cancelled / refunded）。
   没有就抛 404 —— 意味着没买课的人评价不了，退课之后也评价不了"""

## `L54` review_payload

```python
def review_payload(row: dict[str, Any]) -> dict[str, Any]:
```

"""评价的单行格式。`review_tags` 在库里是 JSON 字符串，这里 `json.loads` 还原成数组。
   只暴露 `scoreOverall` 一个分数，另外三个维度（教师/内容/服务）不返回"""

---

## `L64` POST /cohorts/{cohort_id}/reviews

```python
@router.post("/cohorts/{cohort_id}/reviews")
def create_cohort_review(
    body: Annotated[CohortReviewCreateRequest, Body(description="提交班次评价请求体。")],
    cohort_id: Annotated[int, Path(description="班次 ID。")],
    current_user_id: Annotated[int, Depends(get_current_user_id)],
):
```

"""提交评价。一人一班次只能有一条有效评价，重复提交抛 409 `REVIEW_EXISTS`。

   评价编号用 `make_no("RV")` 生成。写入后再查一次拿 `review_no` 回填响应——
   因为 `lastrowid` 只有主键，没有单号"""

## `L117` GET /cohorts/{cohort_id}/reviews

```python
@router.get("/cohorts/{cohort_id}/reviews")
def list_cohort_reviews(
    cohort_id: Annotated[int, Path(description="班次 ID。")],
    current_user_id: Annotated[int | None, Depends(get_optional_current_user_id)] = None,
    only_mine: Annotated[bool, Query(alias="onlyMine", description="是否只查询当前用户自己的评价。")] = False,
    page_no: Annotated[int, Query(alias="pageNo", description="页码，从 1 开始。")] = 1,
    page_size: Annotated[int, Query(alias="pageSize", description="每页条数，范围 1 到 100。")] = 20,
):
```

"""班次评价列表，公开可看（`X-User-Id` 走可选版本）。

   `onlyMine=true` 时必须有用户身份，但这里抛的是 **400 `bad_request`**，
   而 `dependencies.py` 里缺头抛的是 **401 `unauthorized`**——同一个「缺用户」问题，
   两个地方给的状态码不一样"""

---

## 谁在用它

| 谁 | 干什么 |
|---|---|
| `main.py` | `include_router(interactions_router)` |
| 掌柜小二 agent | 评价查询可作闲聊佐证；提交评价是独立任务流程 |

`cohort_review` 表由本文件写、`enrollments.py` 和 `study.py` 不涉及。但 `ensure_cohort_rel`
这个名字在 `enrollments.py` 里也有一份（签名带 `allow_closed` 参数），两者不是同一个函数。
