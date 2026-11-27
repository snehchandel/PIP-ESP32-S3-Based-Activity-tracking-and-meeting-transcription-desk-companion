"""HTTP client for model downloads that trusts the Windows certificate store.

Some networks (antivirus web shields, company proxies) re-sign HTTPS with their own root certificate, which Windows
trusts but Python's certifi bundle does not: downloads then failed with CERTIFICATE_VERIFY_FAILED while a browser or
curl worked. truststore makes Python verify against the operating system's store instead (still full verification).
"""
from __future__ import annotations

import ssl

import httpx


def ssl_context() -> ssl.SSLContext | bool:
    try:
        import truststore

        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except Exception:  # not installed: certifi, as before
        return True


def download_client() -> httpx.Client:
    return httpx.Client(timeout=httpx.Timeout(30.0, read=120.0), follow_redirects=True, verify=ssl_context())
