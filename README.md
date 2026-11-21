# 知行 · 教育智能客服

LangGraph 驱动的客服 Agent，通过 MCP 调用现有教育业务 API 和知识模块。包含学员客服界面和管理后台。

- 学员：预置身份切换、流式咨询、历史会话、订单和学习查询、全额退款申请、异步工单。
- 管理员：教育业务查询、FAQ/文章维护、退款审批与模拟退款、工单回复和结单。
- 执行保障：身份隔离、服务鉴权、事务、幂等、持久化任务与检查点、失败和重启恢复。

使用现有 MySQL 教育数据，不重建完整教育平台；不提供真实支付、实时人工接管或文档上传。

## 开始使用

完整步骤见 [启动与验证](doc/启动与验证.md)。数据库配置沿用 `reference/.env`，模型配置填写根目录 `.env`，字段见 `.env.example`。

```powershell
$env:UV_CACHE_DIR = "$PWD\.runtime\uv-cache"
$env:UV_PROJECT_ENVIRONMENT = "$PWD\.runtime\venv"
uv sync
cd frontend
npm exec --yes --package=pnpm@10.28.2 -- pnpm install
cd ..
.runtime\venv\Scripts\python.exe scripts/dev.py
```

学员端 `http://127.0.0.1:5173`，管理端 `/admin`。管理员账号 `admin`，随机密码见本地 `.runtime/admin-password.txt`；可用 `ADMIN_PASSWORD` 覆盖。

## 项目结构

```text
src/edu_support/   应用 API、Agent、MCP、知识与教育适配器
frontend/         React + TypeScript + Vite
reference/        复用的教育业务后端及增量扩展
tests/            权限、状态、幂等与业务集成测试
scripts/          启动、真实模型及闭环验证
doc/              设计、进度与启动文档
```

## 验证

```powershell
.runtime\venv\Scripts\python.exe -m pytest -q --basetemp=.runtime/test-tmp
.runtime\venv\Scripts\python.exe scripts/check_model.py
```

真实数据库测试显式开启 `RUN_EDUCATION_INTEGRATION=1`；真实 Agent 脚本需先启动后端，使用模型 API。项目当前针对本机单实例演示，未声明生产容量或高可用保证。
