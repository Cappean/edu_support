# errors.py

## import

无。只有 `from __future__ import annotations`。

---

## `L6` AppError

```python
class AppError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
```

"""三个属性：`status_code` HTTP 状态码、`code` 业务错误码、`message` 给人看的说明。
   抛它就等于宣告请求失败，由 `main.py` 注册的处理器统一转成 JSON 响应"""

---

## `L14` 六个快捷构造

```python
def bad_request(code: str, message: str) -> AppError:

def unauthorized(code: str, message: str) -> AppError:

def forbidden(code: str, message: str) -> AppError:

def not_found(code: str, message: str) -> AppError:

def conflict(code: str, message: str) -> AppError:

def not_implemented(endpoint: str) -> AppError:
```

前五个只差 HTTP 状态码：400 / 401 / 403 / 404 / 409，参数签名完全一样。

`not_implemented` 是特殊的那个：状态码 501，参数是**接口名**而不是错误码，消息固定拼成「`{endpoint}` 接口已注册，业务实现待补齐」。

---

`forbidden` 和 `not_implemented` 在 `app/` 全目录**没有任何调用点**，只有定义。`bad_request` 只被 `cart.py`、`consultations.py`、`favorites.py` 用（校验来源字段合法性）。

## 谁在用它

| 模块 | 常用哪个 |
|---|---|
| `dependencies.py` | `unauthorized` 缺 user id、`not_found` 用户不存在 |
| `routers/*.py` | `not_found` 查不到、`conflict` 状态不允许、`bad_request` 参数非法 |
| `main.py` | 注册 `AppError` 的异常处理器 |
