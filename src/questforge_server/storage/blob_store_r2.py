# src/questforge_server/storage/blob_store_r2.py
"""
Cloudflare R2 (S3-compatible) BlobStore implementation.

Required env vars:
  QF_R2_ENDPOINT_URL   e.g. https://<account_id>.r2.cloudflarestorage.com
  QF_R2_ACCESS_KEY_ID
  QF_R2_SECRET_ACCESS_KEY
  QF_R2_BUCKET_NAME
  QF_R2_PUBLIC_BASE_URL  e.g. https://pub-<hash>.r2.dev  (public bucket URL)

If any required env var is missing, from_env() returns a BlobStoreNoop.
"""
from __future__ import annotations

import os
import urllib.request
import urllib.error
import hashlib
import hmac
import datetime
import json
from typing import Optional

from questforge_server.storage.blob_store import BlobStore, BlobStoreNoop


def _sign_v4(
    method: str,
    url: str,
    region: str,
    service: str,
    access_key: str,
    secret_key: str,
    payload: bytes,
    extra_headers: Optional[dict] = None,
) -> dict:
    """
    AWS Signature Version 4 signing — compatible with Cloudflare R2.
    Returns a dict of signed headers (Authorization, x-amz-date, x-amz-content-sha256, host).
    """
    from urllib.parse import urlparse, quote

    parsed = urlparse(url)
    host = parsed.netloc
    path = parsed.path or "/"
    query = parsed.query

    dt = datetime.datetime.utcnow()
    amz_date = dt.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = dt.strftime("%Y%m%d")

    payload_hash = hashlib.sha256(payload).hexdigest()

    headers = {
        "host": host,
        "x-amz-date": amz_date,
        "x-amz-content-sha256": payload_hash,
    }
    if extra_headers:
        headers.update(extra_headers)

    # Canonical headers (sorted)
    sorted_keys = sorted(headers.keys())
    canonical_headers = "".join(f"{k}:{headers[k]}\n" for k in sorted_keys)
    signed_headers = ";".join(sorted_keys)

    canonical_request = "\n".join([
        method,
        path,
        query,
        canonical_headers,
        signed_headers,
        payload_hash,
    ])

    credential_scope = f"{date_stamp}/{region}/{service}/aws4_request"
    string_to_sign = "\n".join([
        "AWS4-HMAC-SHA256",
        amz_date,
        credential_scope,
        hashlib.sha256(canonical_request.encode()).hexdigest(),
    ])

    def _hmac(key: bytes, msg: str) -> bytes:
        return hmac.new(key, msg.encode(), hashlib.sha256).digest()

    signing_key = _hmac(
        _hmac(
            _hmac(
                _hmac(f"AWS4{secret_key}".encode(), date_stamp),
                region,
            ),
            service,
        ),
        "aws4_request",
    )

    signature = hmac.new(signing_key, string_to_sign.encode(), hashlib.sha256).hexdigest()

    authorization = (
        f"AWS4-HMAC-SHA256 Credential={access_key}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )

    return {
        "Authorization": authorization,
        "x-amz-date": amz_date,
        "x-amz-content-sha256": payload_hash,
        "Host": host,
    }


class BlobStoreR2(BlobStore):
    def __init__(
        self,
        endpoint_url: str,
        access_key_id: str,
        secret_access_key: str,
        bucket: str,
        public_base_url: str,
        region: str = "auto",
    ):
        self._endpoint = endpoint_url.rstrip("/")
        self._access_key = access_key_id
        self._secret_key = secret_access_key
        self._bucket = bucket
        self._public_base = public_base_url.rstrip("/")
        self._region = region

    @staticmethod
    def from_env() -> "BlobStore":
        endpoint = (os.getenv("QF_R2_ENDPOINT_URL") or "").strip()
        access_key = (os.getenv("QF_R2_ACCESS_KEY_ID") or "").strip()
        secret_key = (os.getenv("QF_R2_SECRET_ACCESS_KEY") or "").strip()
        bucket = (os.getenv("QF_R2_BUCKET_NAME") or "").strip()
        public_base = (os.getenv("QF_R2_PUBLIC_BASE_URL") or "").strip()

        if not all([endpoint, access_key, secret_key, bucket, public_base]):
            print("[BlobStore] R2 env vars missing → using BlobStoreNoop (local-only)", flush=True)
            return BlobStoreNoop()

        print(f"[BlobStore] R2 configured bucket={bucket}", flush=True)
        return BlobStoreR2(
            endpoint_url=endpoint,
            access_key_id=access_key,
            secret_access_key=secret_key,
            bucket=bucket,
            public_base_url=public_base,
        )

    def _object_url(self, key: str) -> str:
        return f"{self._endpoint}/{self._bucket}/{key}"

    def public_url(self, key: str) -> str:
        return f"{self._public_base}/{key}"

    def put_bytes(self, key: str, data: bytes, content_type: str = "audio/wav") -> str:
        url = self._object_url(key)
        signed = _sign_v4(
            method="PUT",
            url=url,
            region=self._region,
            service="s3",
            access_key=self._access_key,
            secret_key=self._secret_key,
            payload=data,
            extra_headers={"content-type": content_type},
        )
        req = urllib.request.Request(
            url=url,
            data=data,
            method="PUT",
            headers={
                "Authorization": signed["Authorization"],
                "x-amz-date": signed["x-amz-date"],
                "x-amz-content-sha256": signed["x-amz-content-sha256"],
                "Content-Type": content_type,
                "Content-Length": str(len(data)),
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                status = resp.status
            if status not in (200, 201, 204):
                raise RuntimeError(f"R2 PUT failed status={status}")
            return self.public_url(key)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"R2 PUT HTTPError {e.code}: {body[:200]}") from e

    def exists(self, key: str) -> bool:
        url = self._object_url(key)
        signed = _sign_v4(
            method="HEAD",
            url=url,
            region=self._region,
            service="s3",
            access_key=self._access_key,
            secret_key=self._secret_key,
            payload=b"",
        )
        req = urllib.request.Request(
            url=url,
            method="HEAD",
            headers={
                "Authorization": signed["Authorization"],
                "x-amz-date": signed["x-amz-date"],
                "x-amz-content-sha256": signed["x-amz-content-sha256"],
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status == 200
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return False
            return False
        except Exception:
            return False
