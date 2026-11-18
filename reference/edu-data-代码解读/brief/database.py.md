# database.py

## import

```python
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from typing import Any, cast

import pymysql
from pymysql.cursors import DictCursor

from .config import DB_CONFIG
```

---

## `L15` get_connection

```python
def get_connection() -> pymysql.connections.Connection:
```

"""直接用 `DB_CONFIG` 开连接。没有连接池，每次调用都是一个新 TCP 连接"""

## `L19` db_cursor

```python
@contextmanager
def db_cursor(dict_cursor: bool = True) -> Iterator[tuple[Any, Any]]:
```

"""产出 `(conn, cursor)`。正常退出自动 `commit()`，抛异常自动 `rollback()`，最后关 cursor 与连接。
   需要多张表原子写时用它，单条查询别用"""

## `L34` fetch_one

```python
def fetch_one(sql: str, params: Any | None = None) -> dict[str, Any] | None:
```

"""查不到返回 `None`，不抛异常——查不到算不算错误，由调用方决定"""

## `L40` fetch_all

```python
def fetch_all(sql: str, params: Any | None = None) -> list[dict[str, Any]]:
```

"""恒返回 list，查不到就是空 list"""

## `L46` execute

```python
def execute(sql: str, params: Any | None = None) -> int:
```

"""单条写，返回受影响行数"""

## `L52` executemany

```python
def executemany(sql: str, params: Iterable[tuple[Any, ...]]) -> int:
```

"""批量写，返回受影响行数。`generate/insert_support.py` 靠它批量灌种子数据，
   服务层几乎用不到"""

---

四个查询函数都用 `DictCursor`，返回的是 `{列名: 值}`。这是全项目最底层的取数口，`routers/*.py` 全部经由它访问 MySQL。

注意每个函数内部都是「新建连接 → 用完关闭」，没有复用。压测时会直接把压力打到 MySQL 的连接数上限。

## 谁在用它

| 模块 | 用什么 |
|---|---|
| `dependencies.py` | `fetch_one` 校验用户存在 |
| `routers/*.py` | 四个都会出现；`db_cursor` 只在下单、取消、支付这类多表事务里 |
| `tests/conftest.py` | `db_cursor` / `fetch_one` / `fetch_all`，用于查样本数据 |
