import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import marketing_campaigns as campaigns


def policy(**overrides):
    value = {"category": "marketing", "play": "inactivity", "inactivity_days": 7,
             "cooldown_hours": 24, "max_per_7_days": 2, "quiet_start": "22:00",
             "quiet_end": "08:00", "timezone": "Asia/Kolkata"}
    value.update(overrides)
    return value


def facts(**overrides):
    value = {"active": True, "address_verified": True, "marketing_consent": True,
             "suppressed": False, "complaint": False, "bounce": False,
             "unsubscribed": False, "last_activity": datetime.now(timezone.utc) - timedelta(days=8),
             "last_contact": None, "sent_last_7_days": 0, "duplicate": False,
             "observed_at": datetime(2026, 10, 4, 12, tzinfo=timezone.utc), "trigger_confirmed": True}
    value.update(overrides)
    return value


class CampaignPolicyTests(unittest.TestCase):
    def test_default_policy_is_valid_and_conservative(self):
        value = campaigns.default_policy()
        self.assertEqual(campaigns.validate_policy(value), value)
        self.assertEqual(value["inactivity_days"], 7)

    def test_policy_bounds_and_category_contract(self):
        with self.assertRaises(ValueError): campaigns.validate_policy(policy(inactivity_days=6))
        with self.assertRaises(ValueError): campaigns.validate_policy(policy(cooldown_hours=23))
        with self.assertRaises(ValueError): campaigns.validate_policy(policy(category="transactional", play="service_event"))
        self.assertEqual(campaigns.validate_policy(policy(category="transactional", play="service_event", service_event="receipt.ready"))["service_event"], "receipt.ready")

    def test_subject_and_copy_reject_credential_values(self):
        with self.assertRaises(ValueError): campaigns.validate_subject("token=secret-value")
        with self.assertRaises(ValueError): campaigns.validate_copy("Bearer abcdefghijkl")

    def test_missing_consent_suppression_and_stale_facts_fail_closed(self):
        now = datetime(2026, 10, 4, 12, tzinfo=timezone.utc)
        self.assertEqual(campaigns.evaluate_recipient(policy(), facts(marketing_consent=False), now)["reason"], "marketing_consent_required")
        self.assertEqual(campaigns.evaluate_recipient(policy(), facts(suppressed=True), now)["reason"], "suppressed_or_risk_flagged")
        missing = facts(); missing.pop("last_activity")
        self.assertEqual(campaigns.evaluate_recipient(policy(), missing, now)["reason"], "missing_or_invalid_facts")

    def test_frequency_and_cooldown_return_next_time_without_identifiers(self):
        now = datetime(2026, 10, 4, 12, tzinfo=timezone.utc)
        result = campaigns.evaluate_recipient(policy(max_per_7_days=1), facts(sent_last_7_days=1), now)
        self.assertEqual(result["reason"], "frequency_cap")
        result = campaigns.evaluate_recipient(policy(), facts(last_contact=now - timedelta(hours=1)), now)
        self.assertEqual(result["reason"], "cooldown")
        self.assertEqual(set(result), {"eligible", "reason", "next_eligible_at"})

    def test_inactivity_and_quiet_boundaries(self):
        now = datetime(2026, 10, 4, 0, 30, tzinfo=timezone.utc)  # 06:00 IST
        result = campaigns.evaluate_recipient(policy(), facts(last_activity=now - timedelta(days=7), observed_at=now), now)
        self.assertEqual(result["reason"], "quiet_hours")
        now = datetime(2026, 10, 4, 4, 30, tzinfo=timezone.utc)  # 10:00 IST
        self.assertTrue(campaigns.evaluate_recipient(policy(), facts(last_activity=now - timedelta(days=7), observed_at=now), now)["eligible"])
        self.assertEqual(campaigns.evaluate_recipient(policy(), facts(last_activity=now - timedelta(days=6), observed_at=now), now)["reason"], "inactivity_not_due")

    def test_transactional_requires_matching_service_event_and_dst_zone(self):
        p = policy(category="transactional", play="service_event", service_event="invoice.ready", timezone="America/New_York")
        now = datetime(2026, 11, 1, 14, 30, tzinfo=timezone.utc)
        result = campaigns.evaluate_recipient(p, facts(service_event="other", last_activity=None, observed_at=now), now)
        self.assertEqual(result["reason"], "service_event_mismatch")
        result = campaigns.evaluate_recipient(p, facts(service_event="invoice.ready", last_activity=None, observed_at=now), now)
        self.assertTrue(result["eligible"])

    def test_fresh_source_and_confirmed_trigger_are_required(self):
        now = datetime(2026, 10, 4, 12, tzinfo=timezone.utc)
        for observed in (now - timedelta(minutes=6), now + timedelta(seconds=1)):
            self.assertEqual(campaigns.evaluate_recipient(policy(), facts(observed_at=observed), now)['reason'], 'stale_or_future_facts')
        self.assertEqual(campaigns.evaluate_recipient(policy(), facts(trigger_confirmed=False), now)['reason'], 'trigger_not_confirmed')

    def test_marketing_cannot_disguise_a_service_event(self):
        with self.assertRaises(ValueError):
            campaigns.validate_policy(policy(play='service_event'))

    def test_subject_header_injection_is_rejected(self):
        with self.assertRaises(ValueError):
            campaigns.validate_subject('Hello\nBcc: injected@example.com')

    def test_repeated_quiet_hour_never_returns_a_past_boundary(self):
        now = datetime(2026, 11, 1, 6, 15, tzinfo=timezone.utc)
        p = policy(timezone='America/New_York', quiet_start='22:00', quiet_end='01:30')
        result = campaigns.evaluate_recipient(p, facts(observed_at=now, last_activity=now-timedelta(days=8)), now)
        self.assertEqual(result['reason'], 'quiet_hours')
        self.assertEqual(result['next_eligible_at'], '2026-11-01T06:30:00+00:00')

    def test_skipped_quiet_boundary_still_returns_a_nonquiet_time(self):
        now = datetime(2026, 3, 8, 5, 30, tzinfo=timezone.utc)
        p = policy(timezone='America/New_York', quiet_start='22:00', quiet_end='02:30')
        result = campaigns.evaluate_recipient(p, facts(observed_at=now, last_activity=now-timedelta(days=8)), now)
        self.assertEqual(result['reason'], 'quiet_hours')
        self.assertEqual(result['next_eligible_at'], '2026-03-08T07:30:00+00:00')


if __name__ == "__main__":
    unittest.main()
