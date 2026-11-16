"""DNS transport privacy, cache expiry, answer validation and TLS identity."""

from unittest.mock import AsyncMock

import dns.message
import dns.rrset
import httpx
import pytest
from app.core import neon_dns
from sqlalchemy.engine import make_url


def transport(monkeypatch, handler):
    real = httpx.AsyncClient
    monkeypatch.setattr(
        neon_dns.httpx,
        "AsyncClient",
        lambda **kw: real(transport=httpx.MockTransport(handler), **kw),
    )


async def test_binary_dns_sends_only_hostname_and_respects_ttl(monkeypatch):
    calls = []
    now = [100.0]
    monkeypatch.setattr(neon_dns.time, "monotonic", lambda: now[0])

    def answer(request):
        calls.append(request)
        assert str(request.url) == "https://1.1.1.1/dns-query"
        assert request.method == "POST" and "authorization" not in request.headers
        query = dns.message.from_wire(request.content)
        assert query.question[0].name.to_text() == "fixture.neon.tech."
        response = dns.message.make_response(query)
        response.answer.append(
            dns.rrset.from_text("fixture.neon.tech.", 60, "IN", "A", "93.184.216.34")
        )
        return httpx.Response(200, content=response.to_wire())

    transport(monkeypatch, answer)
    resolver = neon_dns.NeonResolver()
    assert await resolver.addresses("fixture.neon.tech") == ("93.184.216.34",)
    now[0] += 59
    await resolver.addresses("fixture.neon.tech")
    assert len(calls) == 1
    now[0] += 2
    await resolver.addresses("fixture.neon.tech")
    assert len(calls) == 2


@pytest.mark.parametrize(
    "name,address", [("fixture.neon.tech.", "127.0.0.1"), ("unrelated.neon.tech.", "93.184.216.34")]
)
async def test_unrelated_or_private_dns_answers_fail_closed(monkeypatch, name, address):
    def answer(request):
        response = dns.message.make_response(dns.message.from_wire(request.content))
        response.answer.append(dns.rrset.from_text(name, 60, "IN", "A", address))
        return httpx.Response(200, content=response.to_wire())

    transport(monkeypatch, answer)
    with pytest.raises(ConnectionError, match="Database DNS resolution unavailable") as error:
        await neon_dns.NeonResolver().addresses("fixture.neon.tech")
    assert "fixture" not in str(error.value) and address not in str(error.value)


async def test_dns_http_failure_never_leaks_response_or_uses_stale_answers(monkeypatch):
    transport(monkeypatch, lambda request: httpx.Response(503, text="private hostname"))
    resolver = neon_dns.NeonResolver()
    resolver.cache["fixture.neon.tech"] = (0, ("93.184.216.34",))
    with pytest.raises(ConnectionError) as error:
        await resolver.addresses("fixture.neon.tech")
    assert "private" not in str(error.value) and "fixture" not in str(error.value)


async def test_non_neon_hosts_never_reach_resolver(monkeypatch):
    transport(monkeypatch, lambda request: pytest.fail("Unexpected DNS disclosure"))
    with pytest.raises(ValueError):
        await neon_dns.NeonResolver().addresses("localhost")


async def test_database_tls_keeps_original_hostname_and_verifies_certificate(monkeypatch):
    import psycopg

    resolve = AsyncMock(return_value=("93.184.216.34", "93.184.216.35"))
    connect = AsyncMock()
    monkeypatch.setattr(neon_dns.resolver, "addresses", resolve)
    monkeypatch.setattr(psycopg.AsyncConnection, "connect", connect)
    await neon_dns.connect_neon(
        make_url("postgresql://fixture:private-password@fixture.neon.tech/demo")
    )
    resolve.assert_awaited_once_with("fixture.neon.tech")
    args = connect.call_args.kwargs
    assert args["host"] == "fixture.neon.tech,fixture.neon.tech"
    assert args["hostaddr"] == "93.184.216.34,93.184.216.35"
    assert args["sslmode"] == "verify-full" and args["sslrootcert"]
    assert args["channel_binding"] == "require"
    assert args["password"] == "private-password"
    assert args["prepare_threshold"] is None


async def test_libpq_connection_failure_cannot_leak_private_connection_details(monkeypatch):
    import psycopg

    monkeypatch.setattr(neon_dns.resolver, "addresses", AsyncMock(return_value=("93.184.216.34",)))
    monkeypatch.setattr(
        psycopg.AsyncConnection,
        "connect",
        AsyncMock(side_effect=psycopg.OperationalError("private-host password=private-password")),
    )
    with pytest.raises(ConnectionError) as error:
        await neon_dns.connect_neon(
            make_url("postgresql://fixture:private-password@fixture.neon.tech/demo")
        )
    assert "private" not in str(error.value) and "fixture" not in str(error.value)
    assert error.value.__suppress_context__
