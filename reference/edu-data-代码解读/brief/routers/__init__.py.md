# routers/__init__.py

## 包职责

```python
"""API router package."""
```

空包，只有一行 docstring。12 个 router 模块平铺在这一层，文件名即业务域：

| 文件 | 业务 |
|---|---|
| `users.py` | 当前用户信息与学员档案 |
| `courses.py` | 课程系列、班次、课次查询 |
| `favorites.py` | 收藏 |
| `consultations.py` | 咨询记录 |
| `coupons.py` | 优惠券领取与列表 |
| `cart.py` | 购物车 |
| `orders.py` | 订单试算、下单、查询、取消 |
| `payments.py` | 支付与退款 |
| `enrollments.py` | 报名关系与学习进度 |
| `study.py` | 课次、视频、作业、考试 |
| `interactions.py` | 讨论与评价 |
| `tickets.py` | 工单与售后 |

**这些模块互不 import**。跨业务的读写全部直接落到数据库上，靠表结构约束而不是代码调用维系关系。所以读单个文件看不出完整影响面——改一张表要全局搜。
