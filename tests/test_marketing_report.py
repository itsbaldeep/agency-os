import copy
import unittest

from scripts.marketing_report import ReportValidationError, normalize_report


def valid_report():
    return {
        "schema_version": 1,
        "report_id": "assessment-17",
        "status": "partial",
        "generated_at": "2026-09-14T10:00:00+00:00",
        "subject": {"name": "TrueApply", "url": "https://trueapply.in"},
        "sources": [
            {"key": "gsc", "label": "Search Console", "state": "available",
             "freshness": "fresh", "checked_at": "2026-09-14T09:59:00Z",
             "observed_at": "2026-09-14T09:00:00Z",
             "metrics": [{"key": "clicks", "state": "observed", "value": 0, "unit": "count"}]},
            {"key": "ga4", "label": "Analytics", "state": "unavailable",
             "freshness": "unknown", "checked_at": "2026-09-14T09:59:00Z", "metrics": []},
        ],
        "claims": [{"text": "Search Console currently reports zero clicks.", "type": "fact",
                     "confidence": "high", "source_refs": ["gsc"]}],
        "actions": [
            {"id": "access", "title": "Grant analytics access", "detail": "Connect GA4 before measuring acquisition.",
             "priority": "high", "mode": "human", "human_decision_required": True,
             "status": "proposed", "dependencies": [], "source_refs": ["ga4"]},
            {"id": "instrument", "title": "Instrument funnel events", "detail": "Add events after access is approved.",
             "priority": "medium", "mode": "review_required", "human_decision_required": True,
             "status": "proposed", "dependencies": ["access"], "source_refs": ["ga4"]},
        ],
    }


class MarketingReportTests(unittest.TestCase):
    def test_valid_report_preserves_zero_and_source_states(self):
        report = normalize_report(valid_report())
        gsc = next(source for source in report["sources"] if source["key"] == "gsc")
        clicks = gsc["metrics"][0]
        self.assertEqual(clicks["value"], 0)
        ga4 = next(source for source in report["sources"] if source["key"] == "ga4")
        self.assertEqual(ga4["state"], "unavailable")
        self.assertEqual(report["actions"][0]["id"], "access")

    def test_malformed_report_is_rejected(self):
        candidate = valid_report()
        candidate["actions"][0]["human_decision_required"] = "yes"
        with self.assertRaises(ReportValidationError) as caught:
            normalize_report(candidate)
        self.assertIn("must be boolean", str(caught.exception))

    def test_infinite_observed_metric_is_rejected(self):
        candidate = valid_report()
        candidate["sources"][0]["metrics"][0]["value"] = float("inf")
        with self.assertRaises(ReportValidationError) as caught:
            normalize_report(candidate)
        self.assertIn("must be finite", str(caught.exception))

    def test_unsupported_claim_is_rejected(self):
        candidate = valid_report()
        candidate["claims"] = [{"text": "Traffic is growing", "type": "fact",
                                 "confidence": "high", "source_refs": []}]
        with self.assertRaises(ReportValidationError):
            normalize_report(candidate)

    def test_unavailable_source_cannot_support_claim(self):
        candidate = valid_report()
        candidate["claims"] = [{"text": "Analytics traffic is zero", "type": "observation",
                                 "confidence": "low", "source_refs": ["ga4"]}]
        with self.assertRaises(ReportValidationError) as caught:
            normalize_report(candidate)
        self.assertIn("non-available source", str(caught.exception))

    def test_action_dependencies_and_human_decision_fields(self):
        candidate = valid_report()
        candidate["actions"][1]["dependencies"] = ["missing"]
        with self.assertRaises(ReportValidationError) as caught:
            normalize_report(candidate)
        self.assertIn("unknown action", str(caught.exception))

    def test_action_cannot_reference_unknown_evidence_or_be_omitted(self):
        candidate = valid_report()
        candidate["actions"][0]["source_refs"] = ["missing"]
        with self.assertRaises(ReportValidationError) as caught:
            normalize_report(candidate)
        self.assertIn("unknown source", str(caught.exception))

        candidate = valid_report()
        candidate["actions"] = []
        with self.assertRaises(ReportValidationError) as caught:
            normalize_report(candidate)
        self.assertIn("at least one prioritized next step", str(caught.exception))

    def test_normalization_is_deterministic_and_does_not_mutate_input(self):
        candidate = valid_report()
        original = copy.deepcopy(candidate)
        first = normalize_report(candidate)
        second = normalize_report(candidate)
        self.assertEqual(first, second)
        self.assertEqual(candidate, original)
        self.assertEqual([item["key"] for item in first["sources"]], ["ga4", "gsc"])
        self.assertEqual([item["id"] for item in first["actions"]], ["access", "instrument"])


if __name__ == "__main__":
    unittest.main()
