"""Hold isolated MySQL browser-test records until the caller sends a newline."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tests"), str(ROOT / "src")]


def main():
    from test_education_integration import education

    generator = education.__wrapped__()
    client, sample, _, item_id, prefix, created = next(generator)
    try:
        headers = {"X-User-Id": str(sample["user_id"])}
        refund = client.post(
            "/support/refunds",
            headers=headers,
            json={
                "order_item_id": item_id,
                "reason": "浏览器验收退款",
                "refund_type": "personal_reason",
                "operation_id": prefix + "browser-refund",
            },
        )
        refund.raise_for_status()
        title = "浏览器验收工单" + prefix
        ticket = client.post(
            "/support/tickets",
            headers=headers,
            json={
                "title": title,
                "description": "课程目录页面白屏，浏览器端到端验证",
                "operation_id": prefix + "browser-ticket",
            },
        )
        ticket.raise_for_status()
        created.append(ticket.json()["id"])
        print(
            json.dumps(
                {
                    "user_id": sample["user_id"],
                    "refund": refund.json(),
                    "ticket": ticket.json(),
                    "title": title,
                }
            ),
            flush=True,
        )
        sys.stdin.readline()
    finally:
        try:
            next(generator)
        except StopIteration:
            pass


if __name__ == "__main__":
    main()
