# courses.py

## import

```python
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query

from ..dependencies import get_optional_current_user_id
from ..database import execute, fetch_all, fetch_one
from ..errors import not_found
from ..response import ok
from ..utils import (
    count_total,
    format_date,
    format_time,
    json_list,
    local_now,
    offset_limit,
)
```

`execute` 在这个文件里出现，是因为列表接口会写搜索日志——全项目唯一的「GET 请求写库」。

---

## `L22` router

```python
router = APIRouter(prefix="/api/v1", tags=["courses"])
```

这个 router 的三个接口都是**公共查询**，不强制要求 `X-User-Id`。

---

## `L25` GET /series

```python
@router.get("/series")
def list_series(
    keyword: Annotated[str | None, Query(description="课程名称关键字。")] = None,
    category_id: Annotated[
        int | None,
        Query(alias="categoryId", description="课程分类 ID；分类数量较多，不在接口文档中展开枚举。"),
    ] = None,
    learning_goal_code: Annotated[
        str | None,
        Query(
            alias="learningGoalCode",
            description=(
                "学习目标编码。可选值：score_improvement、school_sync、"
                "exam_preparation、postgraduate_exam、certificate_exam、"
                "skill_improvement、job_hunting、promotion、career_switch、"
                "interest_learning、other。"
            ),
        ),
    ] = None,
    delivery_mode_code: Annotated[
        str | None,
        Query(
            alias="deliveryModeCode",
            description="授课方式编码。可选值：online_recorded、online_live、offline_face_to_face。",
        ),
    ] = None,
    current_user_id: Annotated[int | None, Depends(get_optional_current_user_id)] = None,
    page_no: Annotated[int, Query(alias="pageNo", description="页码，从 1 开始。")] = 1,
    page_size: Annotated[int, Query(alias="pageSize", description="每页条数，范围 1 到 100。")] = 20,
):
```

"""课程搜索，四个筛选条件可任意组合。只返回 `sale_status = 'on_sale'` 的课程。

   **这是全项目唯一在 GET 里写库的接口**：带了 `keyword` 且传了 `X-User-Id` 时，
   会把这次搜索插进 `series_search_log`（来源固定 `course_list_page`，点击数留空）。
   所以同一个请求传不传用户头，结果相同但副作用不同。

   `learningGoalCode` 走 `JSON_CONTAINS`——课程表里存的是 JSON 数组，用 SQL 函数匹配。
   这条件用不上索引，课程量大了会慢。

   排序按平均分降序，同分再按评价数——**没有按销量或上新时间排的选项**"""

## `L128` GET /series/{series_id}

```python
@router.get("/series/{series_id}")
def get_series_detail(
    series_id: Annotated[int, Path(description="课程系列 ID。")],
):
```

"""课程详情。**没有用户参数**，`X-User-Id` 传不传都一样。

   已下架的课程返回 404，不是返回带状态字段的对象——意味着收藏过的下架课程
   点进来会看到「课程不存在」。

   三个数组字段（适用身份 / 学习目标 / 年级）在库里是 JSON 字符串，
   响应前用 `json_list()` 还原成数组"""

## `L164` GET /series/{series_id}/cohorts

```python
@router.get("/series/{series_id}/cohorts")
def list_series_cohorts(
    series_id: Annotated[int, Path(description="课程系列 ID。")],
):
```

"""该课程的在售班次列表。

   注意查询条件里有 `c.current_student_count < c.max_student_count`——
   **满员的班次直接被过滤掉**，不是返回后让前端判断。所以「想报的班次看不到」
   大概率是满了，不是不存在。

   `campusName` 只在 `delivery_mode == 'offline_face_to_face'` 时返回，
   线上班次即使挂了校区也返回 `null`。

   返回裸 list，**没有分页**"""

## `L215` GET /cohorts/{cohort_id}

```python
@router.get("/cohorts/{cohort_id}")
def get_cohort_detail(
    cohort_id: Annotated[int, Path(description="班次 ID。")],
):
```

"""班次详情，一次带出两个数组：课程模块（`modules`）和全部课次（`sessions`）。

   和上面的列表接口不同，这里**不筛容量**——满员班次照样能查详情。

   `sessions` 返回全部课次，不区分是否已上过。没报名的用户也能看到完整课表"""

## `L290` _series_list_item

```python
def _series_list_item(row: dict[str, Any]) -> dict[str, Any]:
```

"""课程列表的单行格式。私有函数，只有 `list_series` 用。

   位置在文件末尾，而其他文件的辅助函数都放在调用处之前——本文件是个例外"""

---

## 谁在用它

| 谁 | 干什么 |
|---|---|
| `main.py` | `include_router(courses_router)` |
| 掌柜小二 agent | 课程咨询的主入口：`/series` 搜索 → `/series/{id}` 详情 → `/series/{id}/cohorts` 拿班次和价格 |
| `orders.py` | 不调用本文件，但下单要的 `cohortId` 就来自这里的班次列表 |

`series` 和 `series_cohort` 两张表全项目只有本文件读（写由造数脚本负责），
其余 router 都是通过 `cohortId` 间接引用。
