# config.py

## import

```python
import os
from pathlib import Path

from dotenv import load_dotenv
```

---

## `L10` ROOT_DIR 与 .env 加载

```python
ROOT_DIR = Path(__file__).resolve().parent.parent

load_dotenv(ROOT_DIR / ".env")
```

`app/config.py` 往上两级就是项目根，`.env` 在那里。`load_dotenv` 是模块级语句，**导入即执行**——任何 `import app.config` 都会先把环境变量读进来。

---

## `L14` 运行参数

```python
APP_PORT = int(os.getenv("APP_PORT", "8000"))
DEMO_PAYMENT_SIGNATURE = os.getenv("DEMO_PAYMENT_SIGNATURE", "mock-payment-signature")
```

两个都有默认值，`.env` 里不写也能启动。

`DEMO_PAYMENT_SIGNATURE` 只被 `payments.py` 用，是模拟支付回调的校验签名，不是真实密钥。

---

## `L17` DB_CONFIG

```python
DB_CONFIG = {
    "host": os.environ["DB_HOST"],
    "port": int(os.environ["DB_PORT"]),
    "user": os.environ["DB_USER"],
    "password": os.environ["DB_PASSWORD"],
    "database": os.environ["DB_NAME"],
    "charset": "utf8mb4",
    "autocommit": False,
}
```

注意：这五个用 `os.environ[...]` 而不是 `getenv(..., 默认值)`，缺任何一个在导入时就抛 `KeyError`，服务直接起不来，不会静默连到错误的库。

`autocommit: False` 意味着所有写操作都要显式 `commit()`。`database.db_cursor()` 负责这件事，所以绕开它自己 `pymysql.connect` 写数据会提交不上去。

`generate/config.py` 里另有一份结构相同的 `DB_CONFIG`，两份独立但读同一个 `.env`，连的是同一个库。
