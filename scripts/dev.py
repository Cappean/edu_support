"""Start both APIs and the Vite client, stop child processes on Ctrl+C."""

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    children = []
    try:
        for folder, module, port in [
            ("reference", "app.main:app", "8001"),
            ("src", "edu_support.main:app", "8000"),
        ]:
            env = os.environ | {
                "PYTHONPATH": str(ROOT / folder),
                "PYTHONUNBUFFERED": "1",
                "PYTHONIOENCODING": "utf-8",
            }
            children.append(
                subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "uvicorn",
                        module,
                        "--host",
                        "127.0.0.1",
                        "--port",
                        port,
                    ],
                    cwd=ROOT,
                    env=env,
                )
            )
        import httpx

        for port, path in [(8001, "/health"), (8000, "/api/v1/health")]:
            for attempt in range(60):
                if any(child.poll() is not None for child in children):
                    raise RuntimeError("后端进程启动失败，请查看上方错误")
                try:
                    if httpx.get(
                        f"http://127.0.0.1:{port}{path}", timeout=2
                    ).is_success:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.5)
            else:
                raise RuntimeError("后端启动超时")
        # Dependencies are installed with pnpm; invoke installed Vite directly so
        # every startup is offline and does not depend on a global pnpm command.
        children.append(
            subprocess.Popen(
                [
                    "node",
                    str(ROOT / "frontend/node_modules/vite/bin/vite.js"),
                    "--host",
                    "127.0.0.1",
                ],
                cwd=ROOT / "frontend",
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        )
        print(
            "\n学员客服：http://127.0.0.1:5173\n管理后台：http://127.0.0.1:5173/admin\nAPI 文档：http://127.0.0.1:8000/docs\n管理员账号：admin；本地生成密码位于 .runtime/admin-password.txt（若配置 ADMIN_PASSWORD 则使用配置值）。\n",
            flush=True,
        )
        while all(child.poll() is None for child in children):
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        for child in reversed(children):
            if child.poll() is None:
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/PID", str(child.pid), "/T", "/F"],
                        capture_output=True,
                        check=False,
                    )
                else:
                    child.terminate()


if __name__ == "__main__":
    main()
