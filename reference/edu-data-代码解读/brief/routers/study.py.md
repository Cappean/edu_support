# study.py

## import

```python
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query

from ..database import fetch_all, fetch_one
from ..dependencies import get_current_user_id
from ..errors import not_found
from ..response import ok
from ..utils import (
    count_total,
    format_date,
    format_datetime,
    format_time,
    local_now,
    money,
    offset_limit,
)
```

`format_time` 在本文件用来格式化课次的上课时间段。

---

## `L23` router

```python
router = APIRouter(prefix="/api/v1", tags=["study"])
```

**10 个接口全是只读**。整个模块没有任何「提交作业」「开始考试」「上报播放进度」的写接口——
学习行为数据只能由造数脚本或外部系统写入。这是本模块最需要知道的事实。

## `L25` HOMEWORK_STATUS_EXPR

```python
HOMEWORK_STATUS_EXPR = """
CASE
    WHEN sub.id IS NOT NULL THEN sub.submit_status
    WHEN hw.due_at < %s THEN 'expired_unsubmitted'
    ELSE 'pending'
END
"""
```

"""作业状态是**查询时算出来的**，库里不存这个字段。

   三种情况：有提交记录就用提交状态；没提交且过了截止时间算 `expired_unsubmitted`；
   其余算 `pending`。

   注意这段 SQL 片段里有一个 `%s` 占位符（当前时间），所以每次拼接它的查询
   都必须多传一个 `now` 参数，而且位置随它出现的位置变化"""

---

## `L34` ensure_session_access

```python
def ensure_session_access(session_id: int, current_user_id: int) -> dict[str, Any]:
```

"""课次访问权限：必须通过 `student_cohort_rel` 证明用户报了这个班，
   且履约状态不是 cancelled / refunded。

   报错统一说「不存在或无权访问」——不区分「课次不存在」和「你没报名」，
   避免泄露课次是否存在"""

## `L52` ensure_video_access

```python
def ensure_video_access(video_id: int, current_user_id: int) -> dict[str, Any]:
```

"""视频访问权限，链路比课次多两跳：视频 → 素材 → 课次 → 班次 → 报名关系。
   顺带把 `asset.file_url` 带出来，播放地址就存在素材表上"""

## `L72` homework_payload

```python
def homework_payload(row: dict[str, Any]) -> dict[str, Any]:
```

"""作业的单行格式。`homeworkStatus` 就是上面那个 CASE 算出来的值，
   `submissionId` 为空表示没提交"""

## `L87` homework_submission_payload

```python
def homework_submission_payload(row: dict[str, Any]) -> dict[str, Any]:
```

"""提交记录的单行格式。和上面的区别：这个只有真实提交过的记录才有，
   所以没有「未提交」的分支"""

## `L100` exam_payload

```python
def exam_payload(row: dict[str, Any]) -> dict[str, Any]:
```

"""考试的单行格式。`attemptStatus` 用 `COALESCE(sub.attempt_status, 'not_started')`
   兜底——没作答记录就是「未开始」"""

## `L115` exam_submission_payload

```python
def exam_submission_payload(row: dict[str, Any]) -> dict[str, Any]:
```

"""考试作答记录的单行格式"""

---

## `L127` GET /sessions/{session_id}

```python
@router.get("/sessions/{session_id}")
def get_session_detail(
    session_id: Annotated[int, Path(description="课次 ID。")],
    current_user_id: Annotated[int, Depends(get_current_user_id)],
):
```

"""课次详情 + 授课教师列表。教师按 `sort_no` 排，可能是多位"""

## `L160` GET /videos/{video_id}

```python
@router.get("/videos/{video_id}")
def get_video_detail(
    video_id: Annotated[int, Path(description="视频 ID。")],
    current_user_id: Annotated[int, Depends(get_current_user_id)],
):
```

"""视频详情，含 `fileUrl`。这是唯一能拿到播放地址的接口"""

## `L177` GET /videos/{video_id}/chapters

```python
@router.get("/videos/{video_id}/chapters")
def list_video_chapters(
    video_id: Annotated[int, Path(description="视频 ID。")],
    current_user_id: Annotated[int, Depends(get_current_user_id)],
):
```

"""视频章节，按 `chapter_no` 升序。返回裸 list，没有分页。

   每个视频的章节数固定（造数时按 `session_video_chapter` 生成），
   所以这个接口的数据量可控"""

## `L205` GET /me/video-history

```python
@router.get("/me/video-history")
def list_my_video_history(
    current_user_id: Annotated[int, Depends(get_current_user_id)],
    page_no: Annotated[int, Query(alias="pageNo", description="页码，从 1 开始。")] = 1,
    page_size: Annotated[int, Query(alias="pageSize", description="每页条数，范围 1 到 100。")] = 20,
):
```

"""我看过的视频列表，带 `lastPositionSeconds`（上次看到哪）和 `progressPercent`。

   `progressPercent` 用 `float()` 而不是 `money()`——它不是金额，是个百分比数值"""

## `L255` GET /me/homeworks

```python
@router.get("/me/homeworks")
def list_my_homeworks(
    current_user_id: Annotated[int, Depends(get_current_user_id)],
    status: Annotated[
        str | None,
        Query(description="作业状态。可选值：pending、submitted、expired_unsubmitted。"),
    ] = None,
    cohort_id: Annotated[int | None, Query(alias="cohortId", description="班次 ID。")] = None,
    due_before: Annotated[
        str | None,
        Query(alias="dueBefore", description="截止时间上限，格式：YYYY-MM-DD HH:mm:ss。"),
    ] = None,
    page_no: Annotated[int, Query(alias="pageNo", description="页码，从 1 开始。")] = 1,
    page_size: Annotated[int, Query(alias="pageSize", description="每页条数，范围 1 到 100。")] = 20,
):
```

"""我的作业列表，是**班次里的全部作业**而不是「我提交过的作业」——
   没提交的也会出现，状态为 `pending` 或 `expired_unsubmitted`。

   `status` 筛选拼的是 `HOMEWORK_STATUS_EXPR`，所以这个条件下推不到索引。

   注意两个参数列表是分开构造的（`params` 给 count 查询、`select_params` 给数据查询），
   因为 `HOMEWORK_STATUS_EXPR` 在数据查询里出现了**两次**（SELECT 列和 WHERE 条件），
   占位符顺序和 count 查询不一样。改 SQL 时两块都要跟着改，否则参数错位"""

## `L339` GET /homeworks/{homework_id}

```python
@router.get("/homeworks/{homework_id}")
def get_homework_detail(
    homework_id: Annotated[int, Path(description="Homework ID.")],
    current_user_id: Annotated[int, Depends(get_current_user_id)],
):
```

"""作业详情。权限校验是内联 SQL，没用 `ensure_*` helper。

   返回字段只有四个，**没有题目列表**——题库关系在 `session_homework_question_rel` 表里，
   但没有任何接口暴露它"""

## `L369` GET /me/homework-submissions

```python
@router.get("/me/homework-submissions")
def list_my_homework_submissions(
    current_user_id: Annotated[int, Depends(get_current_user_id)],
    status: Annotated[
        str | None,
        Query(description="作业提交状态。可选值：submitted、expired_unsubmitted。"),
    ] = None,
    page_no: Annotated[int, Query(alias="pageNo", description="页码，从 1 开始。")] = 1,
    page_size: Annotated[int, Query(alias="pageSize", description="每页条数，范围 1 到 100。")] = 20,
):
```

"""我的作业提交记录。只包含真正有记录的行，所以状态枚举里没有 `pending`——
   这个接口和上面的 `/me/homeworks` 不是一回事，那个是「要做什么」，这个是「做过什么」"""

## `L416` GET /me/exams

```python
@router.get("/me/exams")
def list_my_exams(
    current_user_id: Annotated[int, Depends(get_current_user_id)],
    status: Annotated[
        str | None,
        Query(description="考试状态。可选值：not_started、in_progress、submitted、absent、timeout。"),
    ] = None,
    cohort_id: Annotated[int | None, Query(alias="cohortId", description="班次 ID。")] = None,
    deadline_before: Annotated[
        str | None,
        Query(alias="deadlineBefore", description="截止时间上限，格式：YYYY-MM-DD HH:mm:ss。"),
    ] = None,
    page_no: Annotated[int, Query(alias="pageNo", description="页码，从 1 开始。")] = 1,
    page_size: Annotated[int, Query(alias="pageSize", description="每页条数，范围 1 到 100。")] = 20,
):
```

"""我的考试列表，结构和 `/me/homeworks` 对称：班次里全部考试，没作答的算 `not_started`。

   状态枚举比作业多三个（`in_progress` / `absent` / `timeout`），
   因为考试有作答过程而不只是提交与否"""

## `L486` GET /exams/{exam_id}

```python
@router.get("/exams/{exam_id}")
def get_exam_detail(
    exam_id: Annotated[int, Path(description="考试 ID。")],
    current_user_id: Annotated[int, Depends(get_current_user_id)],
):
```

"""考试详情，带 `totalScore` 和 `passScore`。

   同样没有题目列表——`session_exam_question_rel` 表存了关联但无接口暴露"""

## `L519` GET /me/exam-submissions

```python
@router.get("/me/exam-submissions")
def list_my_exam_submissions(
    current_user_id: Annotated[int, Depends(get_current_user_id)],
    status: Annotated[
        str | None,
        Query(description="考试作答状态。可选值：not_started、in_progress、submitted、absent、timeout。"),
    ] = None,
    page_no: Annotated[int, Query(alias="pageNo", description="页码，从 1 开始。")] = 1,
    page_size: Annotated[int, Query(alias="pageSize", description="每页条数，范围 1 到 100。")] = 20,
):
```

"""我的考试作答记录。和 `/me/homework-submissions` 不同，这里的状态枚举
   保留了全部五个值，因为考试记录在「未开始」时也可能存在行"""

---

## 谁在用它

| 谁 | 干什么 |
|---|---|
| `main.py` | `include_router(study_router)` |
| `enrollments.py` | 不 import 本文件，`/progress` 自己聚合考勤、视频、作业、考试成绩 |
| `users.py` | 不 import 本文件，`_fetch_recent_learning_records` 自己 UNION 三张表 |
| 掌柜小二 agent | 课表查询、视频打不开的排障、作业/考试进度追问 |

同一个「学习进度」在本文件、`enrollments.py`、`users.py` 三处各有一套查询逻辑，
彼此不复用。改表结构要三处一起改。
