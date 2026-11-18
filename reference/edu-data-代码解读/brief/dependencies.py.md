# dependencies.py

## import

```python
from typing import Annotated

from fastapi import Header

from .database import fetch_one
from .errors import not_found, unauthorized
```

---

## `L12` RequiredUserIdHeader

```python
RequiredUserIdHeader = Annotated[
    str | None,
    Header(
        alias="X-User-Id",
        description="当前用户 ID；需要用户身份的接口必填。",
    ),
]
```

## `L20` OptionalUserIdHeader

```python
OptionalUserIdHeader = Annotated[
    str | None,
    Header(
        alias="X-User-Id",
        description="当前用户 ID；公共查询接口可不传，传入时必须为合法且启用的用户 ID。",
    ),
]
```

两个类型别名指向同一个请求头，差别只在 OpenAPI 文档里的说明文案。标成 `str | None` 是故意的——让 FastAPI 把「缺失」交给下面的函数判断，而不是在框架层就返回 422，这样缺头能返回业务错误码。

---

## `L29` get_current_user_id

```python
def get_current_user_id(x_user_id: RequiredUserIdHeader) -> int:
```

"""三层校验，任一环节失败都抛 HTTP 401：头缺失或空白 → `MISSING_USER_ID`；
   非纯数字 → `INVALID_USER_ID`；数据库查不到或 `yn = 0` → 走 404 `USER_NOT_FOUND_OR_DISABLED`。

   注意这里抛的是 401 和 404 混用——格式错是 401，用户不存在是 404。
   返回的是 `int`，router 里拿到的就是数字，不用自己转"""

## `L48` get_optional_current_user_id

```python
def get_optional_current_user_id(x_user_id: OptionalUserIdHeader = None) -> int | None:
```

"""公共查询接口用：头为空直接返回 `None`，传了就照上面那套严格校验。
   所以「传了个不存在的用户 ID」照样报错，只有「不传」才放行"""

---

## 谁在用它

| 模块 | 用哪个 |
|---|---|
| 11 个 router 的所有写接口 | `Depends(get_current_user_id)` |
| `courses.py` | 两个都用——课程列表是公共的，走 optional |
| `tests/conftest.py` | 拼请求头：`{"X-User-Id": str(user_id)}` |

用法是写在路由函数签名里：

```python
def list_orders(current_user_id: Annotated[int, Depends(get_current_user_id)], ...):
```

FastAPI 会在进入函数体之前跑完校验，router 里不用写任何鉴权代码。
