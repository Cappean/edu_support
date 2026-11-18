# consultations.py

## import

```python
from typing import Annotated

from fastapi import APIRouter, Body, Depends, Path, Query
from pydantic import BaseModel, Field

from ..database import db_cursor, fetch_all, fetch_one
from ..dependencies import get_current_user_id
from ..errors import bad_request, conflict, not_found
from ..response import ok
from ..utils import count_total, format_datetime, local_now, offset_limit
```

---

## `L16` router

```python
router = APIRouter(prefix="/api/v1", tags=["consultations"])
```

## `L18` CONSULT_CHANNELS

```python
CONSULT_CHANNELS = {"phone", "online_chat", "wechat", "offline_visit"}
```

"""咨询方式白名单。注意和 `sourceChannelId` 是两个不同的东西：这个是「用什么方式咨询」，
   那个是「从哪个招生渠道来的」（关联 `dim_channel`）"""

## `L21` ConsultationCreateRequest

```python
class ConsultationCreateRequest(BaseModel):
    consultChannel: str = Field(
        description="咨询渠道。可选值：phone、online_chat、wechat、offline_visit。"
    )
    contactMobile: str = Field(description="咨询人联系电话。")
    consultContent: str | None = Field(default=None, description="咨询内容。")
    sourceChannelId: int = Field(description="来源渠道 ID。")
```

"""四个字段全在创建时确定。`sourceChannelId` 必填——这条记录本身就是转化归因的起点，
   订单的来源渠道校验会回溯到这里"""

## `L30` ensure_cohort

```python
def ensure_cohort(cohort_id: int) -> dict[str, object]:
```

"""与 `orders.py`、`cart.py` 里同名函数逐字相同，三处各写一遍。

   返回整行班次数据，但调用方只用到 `institution_id`"""

---

## `L45` POST /cohorts/{cohort_id}/consultations

```python
@router.post("/cohorts/{cohort_id}/consultations")
def create_consultation(
    body: Annotated[
        ConsultationCreateRequest, Body(description="创建咨询记录请求体。")
    ],
    cohort_id: Annotated[int, Path(description="班次 ID。")],
    current_user_id: Annotated[int, Depends(get_current_user_id)],
):
```

"""创建一条咨询记录。

   **顾问是系统自动分配的**，客户端指定不了：取该班次所属机构里第一个
   `role_category` 为 `sales` 或 `service` 的在职职员。机构一个都没有就抛 409 `NO_CONSULTANT`。

   校验顺序：咨询方式白名单 → 班次存在 → 来源渠道存在 → 找顾问。前面任一失败都不会写库"""

## `L106` GET /me/consultations

```python
@router.get("/me/consultations")
def list_my_consultations(
    current_user_id: Annotated[int, Depends(get_current_user_id)],
    page_no: Annotated[int, Query(alias="pageNo", description="页码，从 1 开始。")] = 1,
    page_size: Annotated[
        int, Query(alias="pageSize", description="每页条数，范围 1 到 100。")
    ] = 20,
):
```

"""我的咨询历史，按咨询时间倒序。

   响应里没有顾问信息，也没有班次名称——只给 `cohortId`，要显示课程名得再查一次"""

---

## 谁在用它

| 模块 | 关系 |
|---|---|
| `main.py` | `include_router(consultations_router)` |
| `orders.py` | **不 import 本文件**，但 `validate_order_source_channel` 直接查 `consultation_record` 表：有咨询记录时，订单渠道必须与咨询渠道一致 |

这条隐形依赖是本模块最需要注意的地方——咨询表的写入方式一变，订单的渠道校验就会跟着变。
