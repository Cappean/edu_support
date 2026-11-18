# response.py

## import

```python
from typing import Any
```

---

## `L8` ok

```python
def ok(data: Any = None) -> dict[str, Any]:
```

"""成功响应。`code` 是**整数 0**"""

## `L12` fail

```python
def fail(code: str, message: str) -> dict[str, Any]:
```

"""失败响应。`code` 这里是**字符串**（形如 `ORDER_NOT_FOUND`）"""

---

成功和失败两个结构，`code` 一个是 `int` 一个是 `str`，类型不同。客户端判断成败既可以看 `code` 的类型，也可以看 `data` 是不是 `None`。

两个函数的返回值都是裸 dict，直接作为路由的返回内容，FastAPI 会把它们序列化成 JSON。

## 谁在用它

| 模块 | 用哪个 |
|---|---|
| `routers/*.py` | 每个接口 `return ok({...})` |
| `main.py` | 三个异常处理器里 `fail(...)` 拼错误体 |

业务代码里**从不调 `fail()`**——出错就 `raise AppError`，由 `main.py` 顶层统一转。
