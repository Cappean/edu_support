# main.py

## import

```python
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .config import APP_PORT
from .errors import AppError
from .response import fail
from .routers.cart import router as cart_router
from .routers.consultations import router as consultations_router
from .routers.coupons import router as coupons_router
from .routers.courses import router as courses_router
from .routers.enrollments import router as enrollments_router
from .routers.favorites import router as favorites_router
from .routers.interactions import router as interactions_router
from .routers.orders import router as orders_router
from .routers.payments import router as payments_router
from .routers.study import router as study_router
from .routers.tickets import router as tickets_router
from .routers.users import router as users_router
```

12 个 router 全部在这里被引入，每个都 `as xxx_router` 避免和模块名混淆。

---

## `L25` OPENAPI_TAGS

```python
OPENAPI_TAGS = [
    {"name": "users", "description": "1. 用户信息与学习档案查询"},
    {"name": "courses", "description": "2. 课程与班次查询"},
    {"name": "favorites", "description": "3. 收藏"},
    {"name": "consultations", "description": "4. 咨询"},
    {"name": "coupons", "description": "5. 优惠券"},
    {"name": "cart", "description": "6. 购物车"},
    {"name": "orders", "description": "7. 订单"},
    {"name": "payments", "description": "8. 支付与退款"},
    {"name": "enrollments", "description": "9. 报名关系与学习中心"},
    {"name": "study", "description": "10. 课次、视频、作业、考试"},
    {"name": "interactions", "description": "11. 互动与评价"},
    {"name": "tickets", "description": "12. 工单与售后服务"},
]
```

"""只影响 `/docs` 页面的分组顺序和描述，不影响路由行为"""

---

## `L40` app

```python
app = FastAPI(title="Edu Data API", version="0.1.0", openapi_tags=OPENAPI_TAGS)
```

"""整个应用实例。**没有任何中间件**——没有 CORS、没有 GZip、没有请求日志。
   浏览器里调这些接口会被跨域拦掉，要做前端页面得自己加 `CORSMiddleware`"""

## `L42` 路由挂载

```python
app.include_router(users_router)
app.include_router(courses_router)
app.include_router(favorites_router)
app.include_router(consultations_router)
app.include_router(coupons_router)
app.include_router(cart_router)
app.include_router(orders_router)
app.include_router(payments_router)
app.include_router(enrollments_router)
app.include_router(study_router)
app.include_router(interactions_router)
app.include_router(tickets_router)
```

12 行按业务模块顺序排列，每个 router 自带 `prefix="/api/v1"`，所以这里是平铺挂载，没有额外前缀。

---

## `L56` handle_app_error

```python
@app.exception_handler(AppError)
async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
```

"""业务异常的总出口。`AppError` 自带 `status_code`，这里原样用作 HTTP 状态码，
   响应体走 `fail(exc.code, exc.message)`"""

## `L64` handle_validation_error

```python
@app.exception_handler(RequestValidationError)
async def handle_validation_error(
    _: Request, exc: RequestValidationError
) -> JSONResponse:
```

"""FastAPI 自己的参数校验失败（类型不对、缺必填字段）走这里，状态码固定 422，
   `code` 固定 `VALIDATION_ERROR`，`message` 是把 pydantic 的报错原文塞进去的字符串。

   注意 `message` 不是给人看的话，是一段多行错误描述——前端要展示得自己截取"""

## `L74` handle_value_error

```python
@app.exception_handler(ValueError)
async def handle_value_error(_: Request, exc: ValueError) -> JSONResponse:
```

"""兜住所有裸 `ValueError`，转成 400 `BAD_REQUEST`。
   主要用来接 `utils.parse_datetime()` 抛的格式错误"""

## `L79` health

```python
@app.get("/health")
def health() -> dict[str, object]:
```

"""返回固定的 `{"code": 0, "message": "ok", "data": {"status": "ok"}}`。
   **不查数据库**——MySQL 挂了它照样返回 ok，不能当健康检查用"""

## `L84` 直接运行

```python
if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=APP_PORT, reload=False)
```

"""`uv run -m app.main` 走的就是这里。`reload=False`，改代码要手动重启。
   `host="0.0.0.0"` 意味着同网段其他机器也能访问"""

---

## 谁在用它

| 谁 | 干什么 |
|---|---|
| `uvicorn` | `uv run -m app.main` 加载这里的 `app` 对象 |
| `tests/conftest.py` | `TestClient(app)` 做接口测试，不占端口 |
| `init_db.py` / `generate/` | 无关，它们只碰数据库 |

三个异常处理器是**全局唯一**的错误出口。任何 router 抛出的 `AppError` 都会到这里，
所以所有接口的错误响应格式必然一致。
