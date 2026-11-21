import asyncio

import httpx
import pytest

from edu_support.education import EducationError, ReferenceHTTP


def test_timeout_is_explicit_service_failure():
    async def scenario():
        async def timeout(request):
            raise httpx.ReadTimeout("test timeout")

        async with httpx.AsyncClient(transport=httpx.MockTransport(timeout)) as client:
            with pytest.raises(EducationError) as error:
                await ReferenceHTTP(client).request(
                    "GET", "/support/orders", user_id=161
                )
            assert error.value.status == 503
            assert error.value.code == "EDUCATION_UNAVAILABLE"

    asyncio.run(scenario())


def test_trusted_identity_injected_and_error_preserved():
    async def scenario():
        async def handler(request):
            assert request.headers["X-User-Id"] == "161"
            assert request.headers["X-Service-Key"]
            assert "X-Actor-Role" not in request.headers
            return httpx.Response(
                409, json={"code": "REFUND_IN_PROGRESS", "message": "申请已存在"}
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(EducationError) as error:
                await ReferenceHTTP(client).request(
                    "POST", "/support/refunds", user_id=161, json={}
                )
            assert error.value.code == "REFUND_IN_PROGRESS"

    asyncio.run(scenario())
