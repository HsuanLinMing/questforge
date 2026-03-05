# src/questforge_server/storage/r2_cleanup.py
from __future__ import annotations

import os
import time
import datetime
import threading
from typing import Any

def start_r2_cleanup_thread(blob_store: Any) -> None:
    """
    Start a background thread that periodically deletes expired R2 objects.
    Depends on `list_objects_v2` and `delete_object` methods on the blob_store.
    """
    if not hasattr(blob_store, "list_objects_v2") or not hasattr(blob_store, "delete_object"):
        return  # Probably BlobStoreNoop or lack of methods

    enabled = (os.getenv("QF_R2_CLEANUP_ENABLED") or "0").strip()
    if enabled != "1":
        return

    # Use smaller TTLs for testing if needed
    ttl_hours_rt = float(os.getenv("QF_R2_TTS_TTL_HOURS", "168") or "168")         # default: 7 days
    ttl_hours_pool = float(os.getenv("QF_R2_POOL_TTS_TTL_HOURS", "336") or "336")  # default: 14 days
    interval_s = float(os.getenv("QF_R2_CLEANUP_INTERVAL_SECONDS", "3600") or "3600")

    prefixes = [
        ("runtime_sample/", ttl_hours_rt),
        ("tts_runs/", ttl_hours_rt),
        ("pool_tts/", ttl_hours_pool),
    ]

    def _loop() -> None:
        while True:
            for prefix, ttl_h in prefixes:
                try:
                    _run_cleanup_once(blob_store, prefix, ttl_h)
                except Exception as e:
                    print(f"[R2_CLEANUP] error on {prefix}: {e!r}", flush=True)
            time.sleep(interval_s)

    t = threading.Thread(target=_loop, name="r2-cleanup", daemon=True)
    t.start()
    print(f"[R2_CLEANUP] thread started. interval={interval_s}s", flush=True)


def _run_cleanup_once(blob_store: Any, prefix: str, ttl_hours: float) -> None:
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(hours=ttl_hours)
    
    continuation_token = None
    deleted_count = 0
    scanned_count = 0
    
    while True:
        res = blob_store.list_objects_v2(prefix=prefix, continuation_token=continuation_token, max_keys=100)
        contents = res.get("Contents", [])
        
        for item in contents:
            scanned_count += 1
            last_mod_str = item.get("LastModified")  # e.g. 2023-10-18T14:46:11.000Z
            key = item.get("Key")
            
            if not last_mod_str or not key:
                continue
                
            try:
                # parse pseudo-ISO8601 string from S3 XML
                last_mod_str = last_mod_str.replace("Z", "+00:00")
                lm = datetime.datetime.fromisoformat(last_mod_str).replace(tzinfo=None)
                if lm < cutoff:
                    if blob_store.delete_object(key):
                        deleted_count += 1
            except Exception:
                pass
                
        if not res.get("IsTruncated"):
            break
            
        continuation_token = res.get("NextContinuationToken")
        if not continuation_token:
            break
            
        # Protect against taking forever or overwhelming R2
        if deleted_count >= 1000:
            print(f"[R2_CLEANUP] hit arbitrary limit of 1000 deletions for {prefix}", flush=True)
            break
            
    if scanned_count > 0:
        print(f"[R2_CLEANUP] scanned={scanned_count} deleted={deleted_count} prefix={prefix}", flush=True)
