"""Opt-in Neon DNS over HTTPS; database secrets never enter DNS requests.

Only the hostname is sent to Cloudflare. Binary POST keeps the name out of HTTP
access-log URLs. libpq keeps the original hostname for SNI/certificate checking
and uses hostaddr for transport, without changing the machine's DNS settings.
"""

import ipaddress
import time

import certifi
import dns.message
import dns.rcode
import dns.rdatatype
import httpx


class NeonResolver:
    def __init__(self):
        self.cache = {}

    async def addresses(self, hostname):
        if not hostname or not hostname.endswith(".neon.tech"):
            raise ValueError("Only Neon database hostnames may use the database resolver.")
        cached = self.cache.get(hostname)
        if cached and cached[0] > time.monotonic():
            return cached[1]
        query = dns.message.make_query(hostname, dns.rdatatype.A)
        try:
            async with httpx.AsyncClient(timeout=4, trust_env=False) as client:
                response = await client.post(
                    "https://1.1.1.1/dns-query",
                    content=query.to_wire(),
                    headers={
                        "accept": "application/dns-message",
                        "content-type": "application/dns-message",
                    },
                )
                response.raise_for_status()
            answer = dns.message.from_wire(response.content)
            if not query.is_response(answer) or answer.rcode() != dns.rcode.NOERROR:
                raise ValueError()
            names = {query.question[0].name.canonicalize()}
            # Follow only CNAMEs rooted at the requested database hostname.
            for _ in answer.answer:
                for record in answer.answer:
                    if record.rdtype == dns.rdatatype.CNAME and record.name.canonicalize() in names:
                        names.update(item.target.canonicalize() for item in record)
            addresses, ttls = [], []
            for record in answer.answer:
                if record.name.canonicalize() not in names:
                    continue
                ttls.append(record.ttl)
                if record.rdtype == dns.rdatatype.A:
                    for item in record:
                        address = ipaddress.IPv4Address(item.address)
                        if not address.is_global:
                            raise ValueError()
                        if str(address) not in addresses:
                            addresses.append(str(address))
            if not addresses:
                raise ValueError()
        except Exception:
            raise ConnectionError(
                "Database DNS resolution unavailable; no connection attempted."
            ) from None
        result = tuple(addresses)
        self.cache[hostname] = (time.monotonic() + min(300, min(ttls)), result)
        return result


resolver = NeonResolver()


class DatabaseConnectError(ConnectionError):
    def __init__(self, sqlstate=None):
        super().__init__("Database connection unavailable; connection details redacted.")
        self.sqlstate = sqlstate


async def connect_neon(url):
    import psycopg

    addresses = await resolver.addresses(url.host)
    params = dict(url.query)
    params.update(
        host=",".join([url.host] * len(addresses)),
        hostaddr=",".join(addresses),
        port=url.port or 5432,
        user=url.username,
        password=url.password,
        dbname=url.database,
        sslmode="verify-full",
        sslrootcert=certifi.where(),
        channel_binding="require",
        connect_timeout=5,
        prepare_threshold=None,
    )
    try:
        return await psycopg.AsyncConnection.connect(**params)
    except psycopg.Error as exc:
        # libpq messages can contain private server/role names. Celery also logs
        # connection failures before a task claims a run, outside the API handler.
        raise DatabaseConnectError(exc.sqlstate) from None
