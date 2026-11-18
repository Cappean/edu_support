# __init__.py

## 包职责

```python
"""FastAPI service for the education mock data set."""
```

空包，只有一行 module docstring，没有导出任何东西。

`app/` 是服务层，和同级的 `generate/`（造数）、`init_db.py`（建表）之间没有代码依赖——三者只共享一份 MySQL 库。所以 `app/` 单独拷走配上已有的库就能跑。

模块依赖方向：`config` → `database` → `dependencies` → `routers/*`，`main.py` 在最外层把 router 装到 app 上。
