# utils.py

## import

```python
from datetime import date, datetime, time, timedelta
from decimal import Decimal
import json
from typing import Any
from zoneinfo import ZoneInfo
```

`ZoneInfo` 依赖系统的 IANA 时区库。Linux/macOS 自带，**Windows 上必须额外装 `tzdata`**，否则模块导入就抛 `ZoneInfoNotFoundError`。

---

## `L11` LOCAL_TZ

```python
LOCAL_TZ = ZoneInfo("Asia/Shanghai")
```

全项目的时间基准。造数（`generate/insert_support.py`）和这里各定义了一份同名常量。

## `L14` local_now

```python
def local_now() -> datetime:
```

"""返回**去掉 tzinfo** 的北京时间——MySQL 的 DATETIME 不带时区，带 tz 的 datetime 会写不进去"""

## `L18` offset_limit

```python
def offset_limit(page_no: int, page_size: int) -> tuple[int, int]:
```

"""把页码和每页条数夹到合法范围：`page_no` 最小 1，`page_size` 夹在 1~100。
   返回 `(offset, limit)` 供 SQL 直接拼"""

## `L24` format_datetime

```python
def format_datetime(value: datetime | None) -> str | None:
```

## `L28` format_date

```python
def format_date(value: date | None) -> str | None:
```

## `L32` format_time

```python
def format_time(value: time | timedelta | None) -> str | None:
```

"""这三个是响应序列化用的。`None` 原样返回 `None` 而不是空串，
   所以响应里没值的字段是 `null`。`format_time` 额外能吃 `timedelta`——
   MySQL 的 TIME 列 pymysql 可能给成 timedelta"""

## `L43` money

```python
def money(value: Decimal | float | int | None) -> float | None:
```

"""把 MySQL 的 `DECIMAL` 转成 `float`。不转的话 `json.dumps` 直接报
   `TypeError: Object of type Decimal is not JSON serializable`，
   所以所有金额字段进响应前都要过它一遍"""

## `L51` parse_datetime

```python
def parse_datetime(value: str, field_name: str) -> datetime:
```

"""按两种格式解析请求里的时间字符串，都失败就抛 `ValueError`（会被 `main.py`
   的处理器转成 400）。`field_name` 只用来拼错误消息"""

## `L60` make_no

```python
def make_no(prefix: str) -> str:
```

"""生成业务单号，格式 `{prefix}{YYYYmmddHHMMSSffffff}`，微秒级时间戳。
   订单用 `ORD`、支付用 `PAY`、工单用 `TKT`。注意它**不保证唯一**——
   同一微秒内两次调用会撞号"""

## `L64` json_list

```python
def json_list(value: Any) -> list[Any]:
```

"""把库里存的 JSON 字符串还原成 list，兼容三种入参：`None` → 空 list、
   已是 list → 原样、字符串 → `json.loads`"""

## `L77` count_total

```python
def count_total(sql: str, params: Any | None = None) -> int:
```

"""分页接口专用的计数函数。约定 SQL 里把计数列 `AS total`，这里只读这一列。
   查不到或为 `NULL` 时返回 0"""

---

## 谁在用它

| 模块 | 用什么 |
|---|---|
| `routers/*.py` | 几乎全用：`money`（金额）、`format_datetime`（时间）、`offset_limit` + `count_total`（分页）、`make_no`（建单） |
| `orders.py` | 五样全用上 |
| `payments.py` | 用 `make_no` 生成支付流水号 |

`count_total` 内部的 `fetch_one` 是**函数内导入**而不是模块顶部——`database` 并没有反过来依赖 `utils`，所以这不是为了绕循环导入，只是把导入限制在使用处。
