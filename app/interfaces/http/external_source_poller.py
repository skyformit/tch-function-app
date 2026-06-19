import logging
import os

import azure.functions as func

from app.use_cases.external_source_poller import _run_external_poll_cycle, poll_external_items_http
from core.app import app


app.route(route="poll-external-items", methods=["POST"])(poll_external_items_http)


if (os.getenv("ENABLE_EXTERNAL_ITEM_TIMER") or "false").strip().lower() == "true":

    @app.timer_trigger(
        schedule="0 */5 * * * *",
        arg_name="mytimer",
        run_on_startup=False,
        use_monitor=(os.getenv("SOURCE_TIMER_USE_MONITOR", "false").strip().lower() == "true"),
    )
    def poll_external_items(mytimer: func.TimerRequest) -> None:
        if mytimer.past_due:
            logging.warning("External item poller is past due")
        try:
            result = _run_external_poll_cycle()
            logging.info(
                "External poll completed ok=%s items_seen=%s processed=%s skipped=%s",
                result.get("ok"),
                result.get("items_seen"),
                result.get("processed_count"),
                result.get("skipped_count"),
            )
        except Exception:
            logging.exception("External poll failed")
