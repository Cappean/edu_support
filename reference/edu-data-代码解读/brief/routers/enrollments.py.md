# enrollments.py

## import

```python
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query

from ..database import fetch_all, fetch_one
from ..dependencies import get_current_user_id
from ..errors import not_found
from ..response import ok
from ..utils import count_total, format_date, format_datetime, offset_limit
```

只读，不写库，所以没有 `db_cursor`。

---

## `L15` router

```python
router = APIRouter(prefix="/api/v1", tags=["enrollments"])
```

## `L18` ensure_cohort_rel

```python
def ensure_cohort_rel(
    cohort_id: int, current_user_id: int, allow_closed: bool = False
) -> dict[str, Any]:
```

"""取当前用户在某班次的履约关系，没有就 404。

   `allow_closed=True` 时连已取消/已退款的关系也放行——`/me/cohorts/{id}` 和
   `/progress` 用这个模式，让退课的人仍能回看历史；其余接口用默认值，拦掉失效关系。

   注意 `interactions.py` 里有个**同名函数但签名不同**（没有 `allow_closed`，恒定拦失效关系），
   两者互不影响"""

## `L33` counts

```python
def counts(row: dict[str, Any] | None, total: str, first: str, second: str) -> dict[str, int]:
```

"""把「总数 / 一个计数 / 另一个计数」压成统一结构，返回 `totalSessions`、`presentCount`、
   `absentCount` 三个键。只有考勤在用，但键名是写死的 session 语义——
   视频、作业、考试那三组的字段名各自手写"""

---

## `L42` GET /me/cohorts

```python
@router.get("/me/cohorts")
def list_my_cohorts(
    current_user_id: Annotated[int, Depends(get_current_user_id)],
    status: Annotated[
        str | None,
        Query(description="履约状态。可选值：active、completed、cancelled、refunded。"),
    ] = None,
    page_no: Annotated[int, Query(alias="pageNo", description="页码，从 1 开始。")] = 1,
    page_size: Annotated[int, Query(alias="pageSize", description="每页条数，范围 1 到 100。")] = 20,
):
```

"""我报过的班次列表，带班次名和系列名。

   默认不筛状态，所以已退款、已取消的班次也会出现在列表里，靠客户端看 `enrollStatusCode` 区分"""

## `L102` GET /me/cohorts/{cohort_id}

```python
@router.get("/me/cohorts/{cohort_id}")
def get_my_cohort_detail(
    cohort_id: Annotated[int, Path(description="班次 ID。")],
    current_user_id: Annotated[int, Depends(get_current_user_id)],
):
```

"""履约关系详情。字段很少——只有 `cohortId`、状态、报名时间、完成时间。

   注意 `serviceEndAt` 是**硬编码 `None`**，不是从库里查的。这个字段永远返回 `null`"""

## `L119` GET /me/cohorts/{cohort_id}/sessions

```python
@router.get("/me/cohorts/{cohort_id}/sessions")
def list_my_cohort_sessions(
    cohort_id: Annotated[int, Path(description="班次 ID。")],
    current_user_id: Annotated[int, Depends(get_current_user_id)],
):
```

"""班次下所有课次，每行附上该学员的考勤状态、作业提交状态、考试作答状态。

   三张提交表都是 LEFT JOIN，所以没记录的课次这些字段是 `null` 而不是被过滤掉。

   这里的 `ensure_cohort_rel` 用默认参数，**已退课的学员调不通**（404）。
   而下面的 `/progress` 允许查——同一个班次，两个接口的权限不一样"""

## `L164` GET /me/cohorts/{cohort_id}/progress

```python
@router.get("/me/cohorts/{cohort_id}/progress")
def get_my_cohort_progress(
    cohort_id: Annotated[int, Path(description="班次 ID。")],
    current_user_id: Annotated[int, Depends(get_current_user_id)],
):
```

"""单班次的学习进度，四组数字一次给全：考勤、视频、作业、考试。

   这正是需求文档里「学习进度查询」要的全部内容——返回结构可以直接喂给 LLM 组织语言。

   两个口径细节：
   `attendance.totalSessions` 数的是 `session_attendance` 表里的行数，不是班次课次总数。
   某课次若没有为该学员生成考勤记录，就不计入总数，进度条会显得「满分」。
   `video.totalVideos` 用的是 `COUNT(DISTINCT play.video_id)`，即「看过的视频数」，
   不是「班次里视频总数」——没点开过的视频不进分母，所以完成率天然偏高。

   响应里 `enrollStatusCode` 可能是 `cancelled` / `refunded`，调用方要自己判断是否还该展示进度"""

---

## 谁在用它

| 谁 | 干什么 |
|---|---|
| `main.py` | `include_router(enrollments_router)` |
| 掌柜小二 agent | `/me/cohorts` 列班次、`/progress` 查进度，是需求 4.3 的唯一数据源 |
| `study.py` | 不 import 本文件，自己按 `session_id` / `video_id` 查，不复用这里的班次归属校验 |
