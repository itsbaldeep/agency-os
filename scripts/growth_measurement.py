#!/usr/bin/env python3
"""Deterministic, aggregate-only acquisition measurement for SEO audits.

This module deliberately requests no GSC or GA4 dimensions.  It compares two
non-overlapping, delayed 28-day windows and leaves sparse results explicitly
inconclusive instead of manufacturing a percentage or a trend.
Google API semantics: GSC Search Analytics requests with no dimensions return
property-level aggregation (https://developers.google.com/webmaster-tools/v1/searchanalytics/query),
and GA4 reports with no dimensions return one property aggregate
(https://developers.google.com/analytics/devguides/reporting/data/v1/rest/v1beta/properties/runReport).
GSC dates use Pacific Time; GA4 dates use the property timezone.
"""
from datetime import datetime, timedelta, timezone
import math
import urllib.parse

import seo_measurement

WINDOW_DAYS = 28
GSC_MIN_IMPRESSIONS = 100
GA4_MIN_USERS = 30
GA4_MIN_SESSIONS = 30
JOURNEY_ROW_CAP = 250


def _date(value):
    if value is None:
        return datetime.now(timezone.utc).date()
    if isinstance(value, datetime):
        return value.date()
    return value if hasattr(value, "year") else datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()


def windows(captured_at=None, lag_days=3):
    """Return current and immediately preceding non-overlapping 28-day windows."""
    day = _date(captured_at)
    current_end = day - timedelta(days=int(lag_days))
    current_start = current_end - timedelta(days=WINDOW_DAYS - 1)
    previous_end = current_start - timedelta(days=1)
    previous_start = previous_end - timedelta(days=WINDOW_DAYS - 1)

    def item(start, end):
        return {"start_date": start.isoformat(), "end_date": end.isoformat(), "days": WINDOW_DAYS}
    return {"current": item(current_start, current_end), "previous": item(previous_start, previous_end)}


def _metric_delta(current, previous):
    if current is None or previous is None:
        return {"absolute": None, "percent": None, "trend": "unknown"}
    absolute = current - previous
    if previous == 0:
        return {"absolute": absolute, "percent": None, "trend": "emerging" if current > 0 else "inconclusive"}
    percent = round((absolute / previous) * 100, 2)
    return {"absolute": absolute, "percent": percent, "trend": "up" if absolute > 0 else "down" if absolute < 0 else "flat"}


def _period(metric, window):
    return {
        "window": window,
        "status": metric.get("status", "source_unavailable"),
        "metrics": metric.get("metrics", {}) if metric.get("status") == "available" else {},
    }


def _comparison(current, previous, metric_names):
    out = {}
    for name in metric_names:
        current_value = current.get("metrics", {}).get(name) if current.get("status") == "available" else None
        previous_value = previous.get("metrics", {}).get(name) if previous.get("status") == "available" else None
        out[name] = {"current": current_value, "previous": previous_value, **_metric_delta(current_value, previous_value)}
    return out


def _gsc_period(result):
    if result.get("status") != "available":
        return result
    values = {"clicks": result.get("clicks", 0), "impressions": result.get("impressions", 0),
              "ctr": result.get("ctr", 0), "weighted_average_position": result.get("weighted_average_position", 0)}
    try:
        values = {key: float(value) for key, value in values.items()}
    except (TypeError, ValueError):
        return {"status": "source_unavailable", "error": "non_numeric GSC metric"}
    if not all(math.isfinite(value) for value in values.values()):
        return {"status": "source_unavailable", "error": "nonfinite GSC metric"}
    if values["impressions"] == 0:
        values["weighted_average_position"] = None
    return {"status": "available", "metrics": values}


def _ga4_period(result):
    if result.get("status") != "available":
        return result
    totals = result.get("totals", {})
    try:
        values = {name: float(totals.get(name, 0)) for name in ("sessions", "totalUsers", "keyEvents") if name in totals}
    except (TypeError, ValueError):
        return {"status": "source_unavailable", "error": "non_numeric GA4 metric"}
    if not all(math.isfinite(value) for value in values.values()):
        return {"status": "source_unavailable", "error": "nonfinite GA4 metric"}
    return {"status": "available", "metrics": values}


def _number(value, name):
    """Accept finite, non-negative provider numbers without coercing bad data to zero."""
    if isinstance(value, bool):
        raise ValueError("invalid " + name)
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError("invalid " + name)
    return number


def _strict_gsc_payload(payload):
    if not isinstance(payload, dict) or payload.get("responseAggregationType") != "byProperty":
        return {"status": "source_unavailable", "error": "malformed aggregate GSC response"}
    rows = payload.get("rows", [])
    if rows is None:
        rows = []
    if not isinstance(rows, list) or len(rows) > 1:
        return {"status": "source_unavailable", "error": "aggregate GSC response has unexpected rows"}
    if not rows:
        return {"status": "available", "clicks": 0.0, "impressions": 0.0, "ctr": 0.0, "weighted_average_position": 0.0}
    row = rows[0]
    if not isinstance(row, dict) or row.get("keys") not in (None, []):
        return {"status": "source_unavailable", "error": "malformed aggregate GSC row"}
    try:
        return {"status": "available", "clicks": _number(row["clicks"], "clicks"), "impressions": _number(row["impressions"], "impressions"), "ctr": _number(row["ctr"], "ctr"), "weighted_average_position": _number(row["position"], "position")}
    except (KeyError, TypeError, ValueError):
        return {"status": "source_unavailable", "error": "invalid aggregate GSC metric"}


def _strict_ga4_payload(payload):
    if not isinstance(payload, dict):
        return {"status": "source_unavailable", "error": "malformed aggregate GA4 response"}
    headers = payload.get("metricHeaders")
    required = {"sessions", "totalUsers", "keyEvents"}
    if not isinstance(headers, list) or len(headers) != len(required) or not all(isinstance(h, dict) and isinstance(h.get("name"), str) for h in headers) or {h["name"] for h in headers} != required:
        return {"status": "source_unavailable", "error": "aggregate GA4 metric headers unavailable"}
    if payload.get("dimensionHeaders") not in (None, []):
        return {"status": "source_unavailable", "error": "aggregate GA4 response contains dimensions"}
    rows = payload.get("rows", [])
    if rows is None:
        rows = []
    if not isinstance(rows, list) or len(rows) > 1:
        return {"status": "source_unavailable", "error": "aggregate GA4 response has unexpected rows"}
    if payload.get("rowCount", len(rows)) != len(rows):
        return {"status": "source_unavailable", "error": "aggregate GA4 row count mismatch"}
    if not rows:
        return {"status": "available", "totals": {name: 0.0 for name in required}}
    row = rows[0]
    if isinstance(row, dict) and row.get("dimensionValues") not in (None, []):
        return {"status": "source_unavailable", "error": "aggregate GA4 row contains dimensions"}
    values = row.get("metricValues") if isinstance(row, dict) else None
    if not isinstance(values, list) or len(values) != len(headers):
        return {"status": "source_unavailable", "error": "aggregate GA4 metric values unavailable"}
    try:
        totals = {header["name"]: _number(value["value"], header["name"]) for header, value in zip(headers, values)}
    except (KeyError, TypeError, ValueError):
        return {"status": "source_unavailable", "error": "invalid aggregate GA4 metric"}
    return {"status": "available", "totals": totals}


def _source_state(current, previous, low_volume):
    if current.get("status") != "available":
        return "source_unavailable"
    if previous.get("status") != "available":
        return "historical_unavailable"
    return "insufficient_evidence" if low_volume else "available"


def _source_status(current, previous):
    if current.get("status") != "available":
        return "source_unavailable"
    return "available" if previous.get("status") == "available" else "partial"


def recommendations(gsc, ga4):
    """Produce review-only next steps from measured facts, with stable IDs."""
    actions = []
    gsc_current = gsc.get("windows", {}).get("current", {}).get("metrics", {})
    ga_current = ga4.get("windows", {}).get("current", {}).get("metrics", {})
    if gsc.get("state") == "source_unavailable":
        actions.append({"id": "growth-gsc-access", "priority": "high", "title": "Restore Search Console measurement", "reason": "Search Console is unavailable, so search demand cannot be assessed.", "mode": "review_required"})
    elif gsc_current.get("impressions") == 0:
        actions.append({"id": "growth-search-demand", "priority": "high", "title": "Create a search demand test", "reason": "The current Search Console window has zero impressions. Verify indexing and target one relevant query before reviewing a focused content test.", "mode": "review_required"})
    elif gsc.get("state") == "historical_unavailable":
        actions.append({"id": "growth-gsc-history", "priority": "low", "title": "Collect a complete comparison window", "reason": "Current Search Console data is available, but the previous comparison window is unavailable. Keep measuring before calling a trend.", "mode": "review_required"})
    elif gsc.get("state") == "insufficient_evidence":
        actions.append({"id": "growth-gsc-sample", "priority": "medium", "title": "Build enough search evidence", "reason": "Search volume is too low to call a trend; publish and distribute one focused asset, then remeasure.", "mode": "review_required"})
    elif gsc_current.get("clicks", 0) == 0:
        actions.append({"id": "growth-snippet-ctr", "priority": "medium", "title": "Improve search snippets", "reason": "Pages received impressions but no clicks in the current window.", "mode": "review_required"})
    if ga4.get("state") == "source_unavailable":
        actions.append({"id": "growth-ga4-access", "priority": "high", "title": "Restore Analytics measurement", "reason": "GA4 is unavailable, so user acquisition cannot be assessed.", "mode": "review_required"})
    elif ga_current.get("totalUsers") == 0:
        actions.append({"id": "growth-distribution", "priority": "high", "title": "Run a distribution test", "reason": "No users were recorded in the current GA4 window. Verify tracking before reviewing a focused distribution test.", "mode": "review_required"})
    elif ga4.get("state") == "historical_unavailable":
        actions.append({"id": "growth-ga4-history", "priority": "low", "title": "Collect a complete traffic comparison window", "reason": "Current GA4 data is available, but the previous comparison window is unavailable. Keep measuring before calling a trend.", "mode": "review_required"})
    elif ga4.get("state") == "insufficient_evidence":
        actions.append({"id": "growth-ga4-sample", "priority": "medium", "title": "Build enough user evidence", "reason": "GA4 volume is too low to call a reliable traffic trend.", "mode": "review_required"})
    elif ga_current.get("keyEvents", 0) == 0:
        actions.append({"id": "growth-conversion", "priority": "medium", "title": "Review the conversion path", "reason": "Users are present but no configured key events were recorded. Verify event configuration before inferring a conversion problem.", "mode": "review_required"})
    return actions


def collect_growth(token, gsc_property=None, ga4_property=None, captured_at=None,
                   metric_fetcher=None, lag_days=3):
    """Collect aggregate GSC and GA4 periods using a bounded injected fetcher."""
    captured = captured_at or datetime.now(timezone.utc).isoformat()
    period_windows = windows(captured, lag_days=lag_days)
    fetch = metric_fetcher or seo_measurement.google_metric

    def request(endpoint, payload):
        try:
            result = fetch(endpoint, token, payload)
            return result if isinstance(result, dict) else {"status": "source_unavailable", "error": "malformed provider result"}
        except Exception as exc:
            return {"status": "source_unavailable", "error": type(exc).__name__}

    gsc_periods = {}
    ga4_periods = {}
    gsc_endpoint = None
    if gsc_property and token:
        gsc_endpoint = "https://searchconsole.googleapis.com/webmasters/v3/sites/" + urllib.parse.quote(str(gsc_property), safe="") + "/searchAnalytics/query"
        for label, window in period_windows.items():
            response = request(gsc_endpoint, {"startDate": window["start_date"], "endDate": window["end_date"], "type": "web", "aggregationType": "byProperty", "dataState": "final", "rowLimit": 1})
            normalized = _strict_gsc_payload(response.get("data")) if response.get("status") == "available" else {"status": "source_unavailable", "error": "provider request unavailable"}
            gsc_periods[label] = _gsc_period(normalized)
    else:
        gsc_periods = {label: {"status": "source_unavailable", "error": "property or access unavailable"} for label in period_windows}
    ga4_endpoint = None
    if ga4_property and token:
        ga4_endpoint = "https://analyticsdata.googleapis.com/v1beta/properties/" + str(ga4_property) + ":runReport"
        for label, window in period_windows.items():
            response = request(ga4_endpoint, {"dateRanges": [{"startDate": window["start_date"], "endDate": window["end_date"]}], "metrics": [{"name": name} for name in ("sessions", "totalUsers", "keyEvents")], "limit": 1})
            normalized = _strict_ga4_payload(response.get("data")) if response.get("status") == "available" else {"status": "source_unavailable", "error": "provider request unavailable"}
            ga4_periods[label] = _ga4_period(normalized)
    else:
        ga4_periods = {label: {"status": "source_unavailable", "error": "property or access unavailable"} for label in period_windows}
    gsc = {"status": _source_status(gsc_periods["current"], gsc_periods["previous"]), "property": gsc_property, "date_timezone": "Google Search Console API (Pacific Time)", "checked_at": captured, "windows": gsc_periods, "comparison": _comparison(gsc_periods["current"], gsc_periods["previous"], ("clicks", "impressions", "ctr", "weighted_average_position"))}
    ga4 = {"status": _source_status(ga4_periods["current"], ga4_periods["previous"]), "property": str(ga4_property) if ga4_property else None, "date_timezone": "GA4 property timezone", "checked_at": captured, "windows": ga4_periods, "comparison": _comparison(ga4_periods["current"], ga4_periods["previous"], ("sessions", "totalUsers", "keyEvents"))}
    gsc_low = gsc["status"] == "available" and (gsc_periods["current"].get("metrics", {}).get("impressions", 0) < GSC_MIN_IMPRESSIONS or gsc_periods["previous"].get("metrics", {}).get("impressions", 0) < GSC_MIN_IMPRESSIONS)
    ga4_low = ga4["status"] == "available" and (ga4_periods["current"].get("metrics", {}).get("totalUsers", 0) < GA4_MIN_USERS or ga4_periods["previous"].get("metrics", {}).get("totalUsers", 0) < GA4_MIN_USERS or ga4_periods["current"].get("metrics", {}).get("sessions", 0) < GA4_MIN_SESSIONS or ga4_periods["previous"].get("metrics", {}).get("sessions", 0) < GA4_MIN_SESSIONS)
    gsc["state"] = _source_state(gsc_periods["current"], gsc_periods["previous"], gsc_low)
    ga4["state"] = _source_state(ga4_periods["current"], ga4_periods["previous"], ga4_low)
    gsc_current_available = gsc_periods["current"].get("status") == "available"
    ga4_current_available = ga4_periods["current"].get("status") == "available"
    result = {"schema_version": 1, "status": "available" if gsc["status"] == "available" and ga4["status"] == "available" else "partial" if gsc_current_available or ga4_current_available else "source_unavailable", "captured_at": captured, "windows": period_windows, "sources": {"gsc": gsc, "ga4": ga4}, "confidence": "unavailable" if not gsc_current_available and not ga4_current_available else "partial" if gsc["status"] != "available" or ga4["status"] != "available" else "insufficient_evidence" if gsc_low or ga4_low else "available", "recommendations": []}
    result["recommendations"] = recommendations(gsc, ga4)
    return result


def _journey_number(value, name, *, rate=False):
    number = _number(value, name)
    if rate and number > 1:
        raise ValueError("invalid " + name)
    return number


def _journey_report(result, *, dimension, metrics, row_mapper):
    """Normalize one bounded GA4 dimension report without retaining PII."""
    if not isinstance(result, dict) or result.get("status") != "available":
        return {"status": "source_unavailable", "error": "provider request unavailable", "rows": []}
    payload = result.get("data")
    if not isinstance(payload, dict):
        return {"status": "source_unavailable", "error": "malformed journey response", "rows": []}
    headers = payload.get("metricHeaders")
    dimensions = payload.get("dimensionHeaders")
    if (not isinstance(headers, list) or {h.get("name") for h in headers if isinstance(h, dict)} != set(metrics)
            or len(headers) != len(metrics) or not isinstance(dimensions, list)
            or [d.get("name") for d in dimensions if isinstance(d, dict)] != [dimension]):
        return {"status": "source_unavailable", "error": "journey headers unavailable", "rows": []}
    rows = payload.get("rows")
    row_count = payload.get("rowCount", len(rows) if isinstance(rows, list) else -1)
    if not isinstance(rows, list) or not isinstance(row_count, int) or isinstance(row_count, bool) or row_count < 0:
        return {"status": "source_unavailable", "error": "journey rows unavailable", "rows": []}
    if row_count != len(rows) and row_count <= JOURNEY_ROW_CAP:
        return {"status": "source_unavailable", "error": "journey row count mismatch", "rows": []}
    truncated = row_count > JOURNEY_ROW_CAP or len(rows) > JOURNEY_ROW_CAP
    clean = []
    dropped = 0
    for row in rows[:JOURNEY_ROW_CAP]:
        try:
            if not isinstance(row, dict) or not isinstance(row.get("dimensionValues"), list) or len(row["dimensionValues"]) != 1:
                raise ValueError("invalid dimension")
            value = str(row["dimensionValues"][0].get("value") or "")[:500]
            if not value or "?" in value or "#" in value:
                dropped += 1
                continue
            metric_values = row.get("metricValues")
            if not isinstance(metric_values, list) or len(metric_values) != len(headers):
                raise ValueError("invalid metrics")
            metrics_out = {}
            for header, metric in zip(headers, metric_values):
                name = header["name"]
                metrics_out[name] = _journey_number(metric["value"], name, rate=name == "engagementRate")
            clean.append({dimension: value, "metrics": metrics_out})
        except (KeyError, TypeError, ValueError):
            dropped += 1
    if truncated or dropped:
        status = "partial" if clean or row_count == 0 else "source_unavailable"
    else:
        status = "available"
    return {"status": status, "rows": clean, "row_count": row_count,
            "returned_rows": len(clean), "row_cap": JOURNEY_ROW_CAP,
            "truncated": truncated, "dropped_rows": dropped}


def collect_journey(token, ga4_property, captured_at=None, request_fn=None):
    """Collect aggregate GA4 journey reports for one delayed 28-day window.

    The dimensions are limited to page paths, event names, and channel groups.
    The result does not contain users, emails, demographics, or query strings;
    event stages are aggregate counts and are not sequential distinct-user
    funnel measurements.
    """
    captured = captured_at or datetime.now(timezone.utc).isoformat()
    period = windows(captured)["current"]
    unavailable = {"status": "source_unavailable", "error": "property or access unavailable", "rows": []}
    if not token or not ga4_property:
        return {"schema_version": 1, "status": "source_unavailable", "property": str(ga4_property) if ga4_property else None,
                "captured_at": captured, "window": period, "sources": {"page_views": unavailable, "events": unavailable, "channels": unavailable},
                "coverage": {"row_cap": JOURNEY_ROW_CAP, "available_sources": 0, "requested_sources": 3},
                "limitation": "Event stage counts are aggregate events, not sequential distinct-user funnel counts."}
    fetch = request_fn or seo_measurement.google_metric
    endpoint = "https://analyticsdata.googleapis.com/v1beta/properties/" + str(ga4_property) + ":runReport"

    def request(dimensions, metrics):
        payload = {"dateRanges": [{"startDate": period["start_date"], "endDate": period["end_date"]}],
                   "dimensions": [{"name": name} for name in dimensions],
                   "metrics": [{"name": name} for name in metrics], "limit": JOURNEY_ROW_CAP}
        try:
            result = fetch(endpoint, token, payload)
            return result if isinstance(result, dict) else {"status": "source_unavailable"}
        except Exception as exc:
            return {"status": "source_unavailable", "error": type(exc).__name__}

    page_views = _journey_report(request(["pagePath"], ["screenPageViews", "sessions", "engagementRate"]), dimension="pagePath", metrics=("screenPageViews", "sessions", "engagementRate"), row_mapper=None)
    events = _journey_report(request(["eventName"], ["eventCount"]), dimension="eventName", metrics=("eventCount",), row_mapper=None)
    channels = _journey_report(request(["sessionDefaultChannelGroup"], ["sessions"]), dimension="sessionDefaultChannelGroup", metrics=("sessions",), row_mapper=None)
    sources = {"page_views": page_views, "events": events, "channels": channels}
    available = sum(source["status"] == "available" for source in sources.values())
    partial = sum(source["status"] == "partial" for source in sources.values())
    status = "available" if available == 3 else "partial" if available or partial else "source_unavailable"
    return {"schema_version": 1, "status": status, "property": str(ga4_property), "captured_at": captured,
            "window": period, "sources": sources,
            "coverage": {"row_cap": JOURNEY_ROW_CAP, "available_sources": available, "partial_sources": partial, "requested_sources": 3},
            "limitation": "Event stage counts are aggregate events, not sequential distinct-user funnel counts."}
