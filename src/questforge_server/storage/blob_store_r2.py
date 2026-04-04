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
import urllib.parse
import hashlib
import hmac
import datetime
import json
from typing import Optional

from questforge_server.storage.blob_store import BlobStore, BlobStoreNoop


def _url_parts(raw: str) -> tuple[str, str, str, list[str]]:
    text = (raw or "").strip()
    if not text:
        return "", "", "", ["missing"]

    parsed = urllib.parse.urlparse(text)
    issues: list[str] = []
    if parsed.scheme not in ("http", "https"):
        issues.append("invalid_scheme")
    if not parsed.netloc:
        issues.append("missing_host")
    return parsed.scheme, parsed.netloc, parsed.path or "/", issues


def _url_diag(name: str, raw: str) -> str:
    scheme, host, path, issues = _url_parts(raw)
    status = "ok" if not issues else ",".join(issues)
    value = (raw or "").strip() or "<empty>"
    return (
        f"{name} value={value!r} scheme={scheme or '<empty>'} "
        f"host={host or '<empty>'} path={path or '<empty>'} status={status}"
    )


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

    @property
    def endpoint_url(self) -> str:
        return self._endpoint

    @property
    def public_base_url(self) -> str:
        return self._public_base

    @property
    def endpoint_host(self) -> str:
        return urllib.parse.urlparse(self._endpoint).netloc or "<empty>"

    @property
    def public_host(self) -> str:
        return urllib.parse.urlparse(self._public_base).netloc or "<empty>"

    @staticmethod
    def env_summary() -> str:
        endpoint = (os.getenv("QF_R2_ENDPOINT_URL") or "").strip()
        public_base = (os.getenv("QF_R2_PUBLIC_BASE_URL") or "").strip()
        bucket = (os.getenv("QF_R2_BUCKET_NAME") or "").strip()
        access_key = bool((os.getenv("QF_R2_ACCESS_KEY_ID") or "").strip())
        secret_key = bool((os.getenv("QF_R2_SECRET_ACCESS_KEY") or "").strip())
        return (
            f"{_url_diag('QF_R2_ENDPOINT_URL', endpoint)} "
            f"{_url_diag('QF_R2_PUBLIC_BASE_URL', public_base)} "
            f"QF_R2_BUCKET_NAME={bucket!r} "
            f"QF_R2_ACCESS_KEY_ID_set={access_key} "
            f"QF_R2_SECRET_ACCESS_KEY_set={secret_key}"
        )

    def startup_check(self) -> dict:
        probe_key = "__qf_startup_probe__"
        url = self._object_url(probe_key)
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
                return {
                    "ok": True,
                    "status": resp.status,
                    "host": self.endpoint_host,
                    "url": url,
                    "public_host": self.public_host,
                    "public_base_url": self.public_base_url,
                }
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            if e.code == 404:
                return {
                    "ok": True,
                    "status": 404,
                    "host": self.endpoint_host,
                    "url": url,
                    "public_host": self.public_host,
                    "public_base_url": self.public_base_url,
                    "detail": "probe_not_found",
                }
            return {
                "ok": False,
                "status": e.code,
                "host": self.endpoint_host,
                "url": url,
                "public_host": self.public_host,
                "public_base_url": self.public_base_url,
                "error": body[:200],
            }
        except Exception as e:
            return {
                "ok": False,
                "host": self.endpoint_host,
                "url": url,
                "public_host": self.public_host,
                "public_base_url": self.public_base_url,
                "error": str(e),
            }

    @staticmethod
    def from_env() -> "BlobStore":
        endpoint = (os.getenv("QF_R2_ENDPOINT_URL") or "").strip()
        access_key = (os.getenv("QF_R2_ACCESS_KEY_ID") or "").strip()
        secret_key = (os.getenv("QF_R2_SECRET_ACCESS_KEY") or "").strip()
        bucket = (os.getenv("QF_R2_BUCKET_NAME") or "").strip()
        public_base = (os.getenv("QF_R2_PUBLIC_BASE_URL") or "").strip()

        issues: list[str] = []
        if not endpoint:
            issues.append("QF_R2_ENDPOINT_URL missing/empty")
        else:
            _, _, _, endpoint_issues = _url_parts(endpoint)
            if endpoint_issues:
                issues.append(_url_diag("QF_R2_ENDPOINT_URL", endpoint))

        if not public_base:
            issues.append("QF_R2_PUBLIC_BASE_URL missing/empty")
        else:
            _, _, _, public_issues = _url_parts(public_base)
            if public_issues:
                issues.append(_url_diag("QF_R2_PUBLIC_BASE_URL", public_base))

        if not access_key:
            issues.append("QF_R2_ACCESS_KEY_ID missing/empty")
        if not secret_key:
            issues.append("QF_R2_SECRET_ACCESS_KEY missing/empty")
        if not bucket:
            issues.append("QF_R2_BUCKET_NAME missing/empty")

        if issues:
            print("[BlobStore] R2 disabled → using BlobStoreNoop (local-only)", flush=True)
            for issue in issues:
                print(f"[BlobStore] {issue}", flush=True)
            return BlobStoreNoop()

        _, endpoint_host, _, _ = _url_parts(endpoint)
        _, public_host, _, _ = _url_parts(public_base)
        print(
            f"[BlobStore] R2 configured bucket={bucket} "
            f"endpoint_host={endpoint_host or '<empty>'} public_host={public_host or '<empty>'}",
            flush=True,
        )
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
        public_url = self.public_url(key)
        object_host = urllib.parse.urlparse(url).netloc or "<empty>"
        public_host = urllib.parse.urlparse(public_url).netloc or "<empty>"
        
        # ✅ Add Cache-Control for edge caching
        # Max-age defaults to 1 year, immutable for view_fp hashes
        cache_control = os.getenv("QF_R2_CACHE_CONTROL", "public, max-age=31536000, immutable")
        
        extra_headers = {
            "content-type": content_type,
            "cache-control": cache_control,
        }
        
        signed = _sign_v4(
            method="PUT",
            url=url,
            region=self._region,
            service="s3",
            access_key=self._access_key,
            secret_key=self._secret_key,
            payload=data,
            extra_headers=extra_headers,
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
                "Cache-Control": cache_control,
                "Content-Length": str(len(data)),
            },
        )
        try:
            print(
                "[BlobStoreR2] PUT start",
                {
                    "key": key,
                    "host": object_host,
                    "url": url,
                    "public_host": public_host,
                    "public_url": public_url,
                    "bytes": len(data),
                },
                flush=True,
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                status = resp.status
            if status not in (200, 201, 204):
                raise RuntimeError(f"R2 PUT failed status={status}")
            return public_url
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            print(
                "[BlobStoreR2] PUT HTTPError",
                {
                    "key": key,
                    "host": object_host,
                    "url": url,
                    "public_url": public_url,
                    "status": e.code,
                    "body": body[:200],
                },
                flush=True,
            )
            raise RuntimeError(
                f"R2 PUT HTTPError status={e.code} host={object_host!r} "
                f"url={url!r} public_url={public_url!r} body={body[:200]!r}"
            ) from e
        except urllib.error.URLError as e:
            print(
                "[BlobStoreR2] PUT URLError",
                {
                    "key": key,
                    "host": object_host,
                    "url": url,
                    "public_url": public_url,
                    "err": repr(e),
                },
                flush=True,
            )
            raise RuntimeError(
                f"R2 PUT URLError host={object_host!r} url={url!r} "
                f"public_url={public_url!r} key={key!r} err={e!r}"
            ) from e
        except Exception as e:
            print(
                "[BlobStoreR2] PUT error",
                {
                    "key": key,
                    "host": object_host,
                    "url": url,
                    "public_url": public_url,
                    "err": repr(e),
                },
                flush=True,
            )
            raise

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

    def delete_object(self, key: str) -> bool:
        """Deletes an object. Returns True if successfully deleted (or if it didn't exist)."""
        url = self._object_url(key)
        signed = _sign_v4(
            method="DELETE",
            url=url,
            region=self._region,
            service="s3",
            access_key=self._access_key,
            secret_key=self._secret_key,
            payload=b"",
        )
        req = urllib.request.Request(
            url=url,
            method="DELETE",
            headers={
                "Authorization": signed["Authorization"],
                "x-amz-date": signed["x-amz-date"],
                "x-amz-content-sha256": signed["x-amz-content-sha256"],
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status in (200, 204)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return True
            print(f"[BlobStoreR2] Delete HTTPError {e.code}: {e.read().decode('utf-8', errors='replace')[:100]}", flush=True)
            return False
        except Exception as ex:
            print(f"[BlobStoreR2] Delete error: {ex!r}", flush=True)
            return False

    def list_objects_v2(self, prefix: str = "", continuation_token: Optional[str] = None, max_keys: int = 1000) -> dict:
        """
        Implementation of S3 ListObjectsV2.
        Returns a dict: {"Contents": [{"Key": str, "LastModified": str, ...}], "NextContinuationToken": str, "IsTruncated": bool}
        """
        import urllib.parse
        import xml.etree.ElementTree as ET

        base_url = f"{self._endpoint}/{self._bucket}"
        query_params = {
            "list-type": "2",
            "max-keys": str(max_keys)
        }
        if prefix:
            query_params["prefix"] = prefix
        if continuation_token:
            query_params["continuation-token"] = continuation_token

        # AWS SigV4 requires the query string to be sorted by key alphabetically
        sorted_params = sorted(query_params.items(), key=lambda x: x[0])
        
        def quote_aws(val):
            return urllib.parse.quote(str(val), safe="~")

        qs = "&".join(f"{quote_aws(k)}={quote_aws(v)}" for k, v in sorted_params)
        url = f"{base_url}?{qs}"

        signed = _sign_v4(
            method="GET",
            url=url,
            region=self._region,
            service="s3",
            access_key=self._access_key,
            secret_key=self._secret_key,
            payload=b"",
        )

        req = urllib.request.Request(
            url=url,
            method="GET",
            headers={
                "Authorization": signed["Authorization"],
                "x-amz-date": signed["x-amz-date"],
                "x-amz-content-sha256": signed["x-amz-content-sha256"],
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                xml_data = resp.read()

            root = ET.fromstring(xml_data)
            ns = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}
            
            result = {
                "Contents": [],
                "IsTruncated": False,
                "NextContinuationToken": None
            }

            is_truncated_elem = root.find("s3:IsTruncated", ns)
            if is_truncated_elem is not None and is_truncated_elem.text == "true":
                result["IsTruncated"] = True

            next_token_elem = root.find("s3:NextContinuationToken", ns)
            if next_token_elem is not None:
                result["NextContinuationToken"] = next_token_elem.text

            contents = root.findall("s3:Contents", ns)
            for c in contents:
                k = c.find("s3:Key", ns)
                lm = c.find("s3:LastModified", ns)
                if k is not None and lm is not None:
                    result["Contents"].append({
                        "Key": k.text,
                        "LastModified": lm.text,
                    })

            return result

        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            if e.code == 403:
                print(f"[BlobStoreR2] WARNING: list_objects 403 Forbidden. Body: {body[:250]}", flush=True)
            else:
                print(f"[BlobStoreR2] list_objects HTTPError {e.code}: {body[:250]}", flush=True)
            return {"Contents": [], "IsTruncated": False, "NextContinuationToken": None}
        except Exception as e:
            print(f"[BlobStoreR2] list_objects error: {e!r}", flush=True)
            return {"Contents": [], "IsTruncated": False, "NextContinuationToken": None}
