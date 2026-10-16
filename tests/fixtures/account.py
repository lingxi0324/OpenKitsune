"""In-memory account credentials and HTTP transport for account unit tests."""

import httpx


class MemoryTokenStore:
    def __init__(self, value: str | None = None):
        self.value = value

    async def load_refresh_token(self):
        return self.value

    async def save_refresh_token(self, value):
        self.value = value

    async def clear(self):
        self.value = None


def mock_account_transport(monkeypatch, handler):
    client = httpx.AsyncClient
    monkeypatch.setattr(
        "openkitsune.account.oidc.httpx.AsyncClient",
        lambda **kwargs: client(transport=httpx.MockTransport(handler), **kwargs),
    )
