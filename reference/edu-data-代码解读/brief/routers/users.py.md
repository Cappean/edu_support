# users.py

## import

```python
from typing import Annotated, Any

from fastapi import APIRouter, Depends

from ..database import fetch_all, fetch_one
from ..dependencies import get_current_user_id
from ..errors import not_found
from ..response import ok
from ..utils import format_date, format_datetime
```

整个文件不写库，只有三个查询接口。

---

## `L15` router

```python
router = APIRouter(prefix="/api/v1", tags=["users"])
```

---

## `L18` GET /me

```python
@router.get("/me")
def get_me(current_user_id: Annotated[int, Depends(get_current_user_id)]):
```

"""当前用户基础信息。虽然 `get_current_user_id` 已经查过一次 `sys_user`，
   这里还是重新查了整行——为了让响应带上 nickname、mobile 这些字段。

   注意返回的 `userId` 和请求头里的 `X-User-Id` 恒等，所以这个接口不能用来查别人。

   没有任何用户能调通的兜底：`yn = 0` 的账号在这一步就 404 了，
   而 `get_current_user_id` 也会拦住它——两道检查重复"""

## `L52` GET /me/student-profile

```python
@router.get("/me/student-profile")
def get_student_profile(
    current_user_id: Annotated[int, Depends(get_current_user_id)],
):
```

"""学员档案，把四个维度表 JOIN 起来给出「身份 / 目标 / 学历 / 年级」的 code + name。

   注意 `dim_education_level` 和 `dim_grade` 用的是 **LEFT JOIN**：职场人没有学历层次、
   在校生没有年级，这两种情况都合法。响应里对应的字段会是 `null` 而不是空对象——
   靠 `if row["level_code"] else None` 判断。

   这个接口是 agent 做用户画像的主要数据源：`learnerIdentity` 和 `learningGoal`
   决定后续推荐什么课程、用什么话术"""

## `L110` GET /me/learning-summary

```python
@router.get("/me/learning-summary")
def get_learning_summary(
    current_user_id: Annotated[int, Depends(get_current_user_id)],
):
```

"""学习总览：三个班次计数（在读 / 已完成 / 已关闭）+ 最近 10 条学习动态。

   计数直接对 `student_cohort_rel` 聚合，不区分机构。
   `cancelled` 和 `refunded` 合并成 `cancelledOrRefundedCohortCount`，分不开了。

   先查 `student_profile` 判存在，没有档案就 404——和上一个接口的前置条件一样"""

## `L149` _fetch_recent_learning_records

```python
def _fetch_recent_learning_records(current_user_id: int) -> list[dict[str, Any]]:
```

"""私有函数（下划线开头），只被 `get_learning_summary` 调用。

   把视频播放、作业提交、考试提交三种记录 `UNION ALL` 成一张表，按时间倒序取 10 条。
   所以同一个 `user_id` 参数传了三遍——三个子查询各要一次。

   返回的 `type` 只有 `video` / `homework` / `exam` 三种取值，
   前端要靠它决定跳哪个详情页。这里没有讨论、评价、工单的记录"""

---

## 谁在用它

| 谁 | 干什么 |
|---|---|
| `main.py` | `include_router(users_router)` |
| 掌柜小二 agent | 三个接口都是开场必查：识别身份（`/me` + `/me/student-profile`）、概览进度（`/me/learning-summary`） |
| `dependencies.py` | 不调用本文件，自己查 `sys_user` 校验身份 |

单班次的详细学习进度不在这里，在 `enrollments.py` 的 `/me/cohorts/{cohort_id}/progress`。
本文件只给「跨班次的汇总」。
