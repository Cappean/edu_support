# edu-data 源码解读

- 本文档中的 `"""..."""` 是文档补充的说明，源码中没有；代码块里的 `#` 才是原作者写的。
- 覆盖范围：`app/` 下全部 21 个 `.py`。未覆盖 `generate/`（造数脚本）、`tests/`、`init_db.py`、`sql/`、`seeds/`、`docker/`、`pyproject.toml`、`.env`。
- 基于 2026-11-18 的源码生成，对应 `smoke` 档数据（800 用户 / 900 订单）。
