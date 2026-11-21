"""Verify real model text streaming and tool calling without printing credentials."""

import asyncio
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


async def main():
    missing = [key for key in ("OPENAI_API_KEY", "OPENAI_MODEL") if not os.getenv(key)]
    if missing:
        raise SystemExit("Missing configuration: " + ", ".join(missing))
    client = AsyncOpenAI(
        api_key=os.environ["OPENAI_API_KEY"],
        base_url=os.getenv("OPENAI_BASE_URL") or None,
        timeout=45,
        max_retries=0,
    )
    try:
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "lookup_order",
                    "description": "查询示例订单",
                    "parameters": {
                        "type": "object",
                        "properties": {"order_id": {"type": "string"}},
                        "required": ["order_id"],
                    },
                },
            }
        ]
        result = await client.chat.completions.create(
            model=os.environ["OPENAI_MODEL"],
            messages=[
                {"role": "user", "content": "请调用 lookup_order 查询订单 TEST001。"}
            ],
            tools=tools,
            tool_choice={"type": "function", "function": {"name": "lookup_order"}},
        )
        calls = result.choices[0].message.tool_calls or []
        valid = bool(
            calls
            and calls[0].function.name == "lookup_order"
            and json.loads(calls[0].function.arguments).get("order_id") == "TEST001"
        )
        print("tool_call:", "PASS" if valid else "FAIL")
        if not valid:
            raise SystemExit(1)
        stream = await client.chat.completions.create(
            model=os.environ["OPENAI_MODEL"],
            messages=[{"role": "user", "content": "只回复：连接成功"}],
            stream=True,
        )
        parts = []
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                parts.append(chunk.choices[0].delta.content)
        print("text_stream:", "PASS" if "".join(parts).strip() else "FAIL")
        if not "".join(parts).strip():
            raise SystemExit(1)
    except Exception as error:
        # Do not render provider response bodies or URLs, which may contain credentials.
        print(
            "model_check_failed:",
            type(error).__name__,
            "status:",
            getattr(error, "status_code", None),
        )
        raise SystemExit(1) from None
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
