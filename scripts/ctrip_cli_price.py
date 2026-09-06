#!/usr/bin/env python3
"""Atomic date-based Ctrip price collection operations."""

from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from ctrip_cli_browser import focus_page  # noqa: E402
from ctrip_hotel_prices import (  # noqa: E402
    build_detail_url,
    build_page_price_checks,
    build_page_room_rows,
    capture_room_data,
    flatten_room_rows,
    page_price_check_status,
    validate_price_config,
)


def collect_one_stay(
    page: Any,
    detail_url: str,
    check_in: date,
    check_out: date,
    *,
    config: dict[str, Any],
    source_file: str = "",
) -> dict[str, Any]:
    """Collect one stay; the operation owns one focused page and one URL."""

    validate_price_config(config)
    page = focus_page(page)
    target_url = build_detail_url(
        detail_url,
        check_in,
        check_out,
        adults=int(config.get("adults", 2)),
        children=int(config.get("children", 0)),
        rooms=int(config.get("rooms", 1)),
        city_id=config.get("city_id"),
    )
    collection = capture_room_data(
        page,
        target_url,
        api_timeout_seconds=float(config.get("api_timeout_seconds", 45)),
        settle_ms=int(config.get("settle_ms", 1500)),
        price_mode=config["price_mode"],
        show_all_rooms_xpath=config["show_all_rooms_xpath"],
        page_price_xpath=config.get("page_price_xpath", ""),
        page_room_name_xpath=config.get("page_room_name_xpath", ""),
        page_price_sample_size=int(config.get("page_price_sample_size", 0)),
        page_price_timeout_seconds=float(
            config.get("page_price_timeout_seconds", 15)
        ),
    )
    captured_at = datetime.now(timezone.utc).isoformat()
    response_rows = flatten_room_rows(
        hotel_name=str(config.get("hotel_name", "")),
        check_in=check_in.isoformat(),
        check_out=check_out.isoformat(),
        detail_url=target_url,
        captured_at=captured_at,
        source_file=source_file,
        responses=collection["responses"],
    )
    page_price_rows = collection["page_price_rows"]
    checks = build_page_price_checks(
        response_rows,
        page_price_rows,
        sample_size=int(config.get("page_price_sample_size", 0)),
    )
    page_price_error = collection["page_price_error"]
    if config["price_mode"] == "page_xpath":
        room_rows = build_page_room_rows(
            hotel_name=str(config.get("hotel_name", "")),
            check_in=check_in.isoformat(),
            check_out=check_out.isoformat(),
            detail_url=target_url,
            captured_at=captured_at,
            source_file=source_file,
            response_rows=response_rows,
            page_price_rows=page_price_rows,
        )
    else:
        room_rows = response_rows

    payload: dict[str, Any] = {
        "hotel_name": str(config.get("hotel_name", "")),
        "check_in": check_in.isoformat(),
        "check_out": check_out.isoformat(),
        "detail_url": target_url,
        "price_mode": config["price_mode"],
        "responses": collection["responses"],
        "page_price_rows": page_price_rows,
        "page_price_checks": checks,
        "page_price_check_status": page_price_check_status(
            page_price_rows=page_price_rows,
            checks=checks,
            error=page_price_error,
        ),
        "room_rows": room_rows,
    }
    if page_price_error:
        payload["page_price_check_error"] = page_price_error
    return payload


__all__ = ["collect_one_stay"]
