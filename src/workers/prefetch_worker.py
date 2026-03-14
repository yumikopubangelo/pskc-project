import asyncio
import logging
import time
from typing import Any, Dict, List

from src.api.ml_service import run_request_path_prefetch
from src.prefetch.queue import get_prefetch_queue
from src.runtime.bootstrap import build_runtime_services, shutdown_runtime_services

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)


def _filter_candidates(candidates: List[Dict[str, Any]], key_ids: List[str]) -> List[Dict[str, Any]]:
    target_keys = set(key_ids)
    return [candidate for candidate in candidates if candidate.get("key_id") in target_keys]


def process_prefetch_job(queue, secure_manager, job: Dict[str, Any]) -> Dict[str, Any]:
    candidates = job.get("candidates") or []
    if not candidates:
        queue.mark_completed(job)
        return {"status": "skipped", "prefetched_count": 0, "predictions_considered": 0}

    try:
        result = asyncio.run(
            run_request_path_prefetch(
                secure_manager=secure_manager,
                service_id=job.get("service_id", "default"),
                source_key_id=job.get("source_key_id", ""),
                candidates=candidates,
                ip_address=job.get("ip_address", ""),
            )
        )
    except Exception as exc:
        logger.exception("Prefetch worker job failed: %s", exc)
        retry_state = queue.retry(job, error=str(exc))
        return {"status": retry_state["status"], "error": str(exc), **retry_state}

    failed_store_keys = result.get("failed_store_keys", [])
    if failed_store_keys:
        dlq_error = f"secure_set_failed:{','.join(failed_store_keys)}"
        queue.move_to_dlq(job, error=dlq_error)
        return {"status": "dlq", **result}

    missing_keys = result.get("missing_keys", [])
    if missing_keys:
        retry_state = queue.retry(
            job,
            error=f"fetch_failed:{','.join(missing_keys)}",
            candidates=_filter_candidates(candidates, missing_keys),
        )
        return {"status": retry_state["status"], **result, **retry_state}

    queue.mark_completed(job)
    return {"status": "completed", **result}


def main() -> None:
    services = build_runtime_services()
    queue = get_prefetch_queue()
    secure_manager = services["secure_cache_manager"]

    logger.info("Prefetch worker started")

    try:
        while True:
            job = queue.dequeue()
            if job is None:
                continue

            result = process_prefetch_job(queue, secure_manager, job)

            logger.info(
                "Prefetch worker processed service=%s source_key=%s status=%s prefetched=%s considered=%s",
                job.get("service_id", "default"),
                job.get("source_key_id", ""),
                result.get("status", "unknown"),
                result.get("prefetched_count", 0),
                result.get("predictions_considered", 0),
            )
    except KeyboardInterrupt:
        logger.info("Prefetch worker interrupted")
    except Exception as exc:
        logger.exception("Prefetch worker crashed: %s", exc)
        raise
    finally:
        queue.close()
        shutdown_runtime_services(services)


if __name__ == "__main__":
    while True:
        try:
            main()
            break
        except KeyboardInterrupt:
            break
        except Exception:
            time.sleep(5)
