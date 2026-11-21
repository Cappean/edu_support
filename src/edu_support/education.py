"""HTTP adapter for the existing education application."""

from typing import Protocol

import httpx

from .config import REFERENCE_URL, SECRET


class EducationPort(Protocol):
    async def request(
        self,
        method: str,
        path: str,
        user_id: int | None = None,
        admin: bool = False,
        **kwargs,
    ): ...


class EducationError(Exception):
    def __init__(self, status, code, message):
        self.status, self.code, self.message = status, code, message
        super().__init__(message)


class ReferenceHTTP:
    def __init__(self, client: httpx.AsyncClient):
        self.client = client

    async def request(self, method, path, user_id=None, admin=False, **kwargs):
        headers = {"X-Service-Key": SECRET}
        if user_id:
            headers["X-User-Id"] = str(user_id)
        if admin:
            headers["X-Actor-Role"] = "admin"
        try:
            response = await self.client.request(
                method, REFERENCE_URL + path, headers=headers, **kwargs
            )
        except httpx.HTTPError:
            raise EducationError(
                503, "EDUCATION_UNAVAILABLE", "教育业务服务暂时不可用，请稍后重试"
            ) from None
        if response.is_error:
            try:
                error = response.json()
            except ValueError:
                error = {}
            raise EducationError(
                response.status_code,
                error.get("code", "EDUCATION_ERROR"),
                error.get("message", "业务请求失败"),
            )
        value = response.json()
        if isinstance(value, dict) and value.get("code") == 0:
            return value["data"]
        return value
