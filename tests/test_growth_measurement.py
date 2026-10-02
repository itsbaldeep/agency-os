import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import growth_measurement as growth


class GrowthMeasurementTests(unittest.TestCase):
    @staticmethod
    def _provider(current=True, previous=True, volume=100):
        def fetch(url, _token, payload):
            start = payload.get("startDate") or payload["dateRanges"][0]["startDate"]
            is_current = start == "2026-08-17"
            if (is_current and not current) or (not is_current and not previous):
                return {"status": "source_unavailable", "error": "provider unavailable"}
            if "searchconsole" in url:
                return {"status": "available", "data": {"responseAggregationType": "byProperty", "rows": [{"clicks": 10, "impressions": volume, "ctr": .1, "position": 4}]}}
            return {"status": "available", "data": {"metricHeaders": [{"name": "sessions"}, {"name": "totalUsers"}, {"name": "keyEvents"}], "rows": [{"metricValues": [{"value": str(volume)}, {"value": str(volume)}, {"value": "2"}]}]}}
        return fetch

    def test_windows_are_non_overlapping_and_28_days(self):
        result = growth.windows("2026-09-16T12:00:00+00:00")
        self.assertEqual(result["current"], {"start_date": "2026-08-17", "end_date": "2026-09-13", "days": 28})
        self.assertEqual(result["previous"]["end_date"], "2026-08-16")

    def test_collects_aggregate_queries_and_preserves_zero(self):
        calls = []

        def fetch(url, token, payload):
            calls.append((url, payload))
            if "searchconsole" in url:
                return {"status": "available", "data": {"responseAggregationType": "byProperty", "rows": []}}
            return {"status": "available", "data": {"metricHeaders": [{"name": "sessions"}, {"name": "totalUsers"}, {"name": "keyEvents"}], "rows": [{"metricValues": [{"value": "4"}, {"value": "2"}, {"value": "0"}]}]}}

        result = growth.collect_growth("token", "sc-domain:example.test", "123", "2026-09-16T00:00:00+00:00", fetch)
        self.assertEqual(len(calls), 4)
        self.assertEqual({payload["startDate"] for url, payload in calls if "searchconsole" in url}, {"2026-08-17", "2026-07-20"})
        for url, payload in calls:
            if "searchconsole" in url:
                self.assertEqual(payload["aggregationType"], "byProperty")
            else:
                self.assertNotIn("dimensions", payload)
                self.assertNotIn("eventCount", [m["name"] for m in payload["metrics"]])
        self.assertEqual(result["sources"]["gsc"]["windows"]["current"]["metrics"]["impressions"], 0)
        self.assertIsNone(result["sources"]["gsc"]["comparison"]["impressions"]["percent"])
        self.assertEqual(result["confidence"], "insufficient_evidence")

    def test_unavailable_sources_are_explicit_and_recommend_access(self):
        result = growth.collect_growth(None, "sc-domain:example.test", None, "2026-09-16T00:00:00+00:00")
        self.assertEqual(result["status"], "source_unavailable")
        self.assertEqual(result["confidence"], "unavailable")
        self.assertEqual([x["id"] for x in result["recommendations"]], ["growth-gsc-access", "growth-ga4-access"])

    def test_zero_baseline_has_no_percentage(self):
        delta = growth._metric_delta(3, 0)
        self.assertEqual(delta["trend"], "emerging")
        self.assertIsNone(delta["percent"])

    def test_invalid_gsc_metrics_fail_closed(self):
        for value in ("bad", "NaN", -1, True, None, [], {}):
            with self.subTest(value=value):
                payload = {"responseAggregationType": "byProperty", "rows": [{"clicks": value, "impressions": 10, "ctr": 0, "position": 2}]}
                self.assertEqual(growth._strict_gsc_payload(payload)["status"], "source_unavailable")

    def test_gsc_rejects_wrong_aggregation_and_dimensions(self):
        for payload in ({}, {"responseAggregationType": "byPage"}, {"responseAggregationType": "byProperty", "rows": [{"keys": ["page"]}]}):
            self.assertEqual(growth._strict_gsc_payload(payload)["status"], "source_unavailable")

    def test_ga4_invalid_values_and_headers(self):
        headers = [{"name": name} for name in ("sessions", "totalUsers", "keyEvents")]
        for value in ("bad", "NaN", -1, True, None, [], {}):
            payload = {"metricHeaders": headers, "rows": [{"metricValues": [{"value": value}, {"value": "2"}, {"value": "0"}]}]}
            self.assertEqual(growth._strict_ga4_payload(payload)["status"], "source_unavailable")
        for invalid in ([], [{"name": []}], headers[:2], headers[:2] + [headers[0]]):
            self.assertEqual(growth._strict_ga4_payload({"metricHeaders": invalid})["status"], "source_unavailable")

    def test_ga4_empty_is_zero_only_with_valid_headers(self):
        payload = {"metricHeaders": [{"name": name} for name in ("sessions", "totalUsers", "keyEvents")]}
        self.assertEqual(growth._strict_ga4_payload(payload)["totals"]["totalUsers"], 0)
        payload["rowCount"] = 2
        self.assertEqual(growth._strict_ga4_payload(payload)["status"], "source_unavailable")

    def test_partial_access_never_claims_full_confidence(self):
        result = growth.collect_growth("test", "sc-domain:example.test", None, metric_fetcher=lambda *args: {"status": "available", "data": {"responseAggregationType": "byProperty"}})
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["confidence"], "partial")
        self.assertEqual(result["recommendations"][0]["id"], "growth-search-demand")

    def test_provider_exception_is_contained_and_redacted(self):
        def fail(*args):
            raise ValueError("sensitive-provider-detail")
        result = growth.collect_growth("test", "sc-domain:example.test", "123", metric_fetcher=fail)
        self.assertEqual(result["status"], "source_unavailable")
        self.assertNotIn("sensitive-provider-detail", str(result))

    def test_malformed_provider_result_is_contained(self):
        for payload in (None, [], {"status": "available", "data": []}):
            result = growth.collect_growth("test", "sc-domain:example.test", "123", metric_fetcher=lambda *args: payload)
            self.assertEqual(result["status"], "source_unavailable")

    def test_current_only_data_is_historical_gap_without_access_rotation(self):
        result = growth.collect_growth("test", "sc-domain:example.test", "123", "2026-09-16T00:00:00+00:00", self._provider(current=True, previous=False, volume=100))
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["sources"]["gsc"]["state"], "historical_unavailable")
        self.assertIn("growth-gsc-history", [item["id"] for item in result["recommendations"]])
        self.assertNotIn("growth-gsc-access", [item["id"] for item in result["recommendations"]])

    def test_prior_only_data_treats_current_window_as_unavailable(self):
        result = growth.collect_growth("test", "sc-domain:example.test", "123", "2026-09-16T00:00:00+00:00", self._provider(current=False, previous=True, volume=100))
        self.assertEqual(result["status"], "source_unavailable")
        self.assertEqual(result["sources"]["gsc"]["state"], "source_unavailable")
        self.assertIn("growth-gsc-access", [item["id"] for item in result["recommendations"]])

    def test_normal_two_window_data_is_available(self):
        result = growth.collect_growth("test", "sc-domain:example.test", "123", "2026-09-16T00:00:00+00:00", self._provider(volume=100))
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["confidence"], "available")
        self.assertEqual(result["sources"]["ga4"]["state"], "available")


if __name__ == "__main__":
    unittest.main()
