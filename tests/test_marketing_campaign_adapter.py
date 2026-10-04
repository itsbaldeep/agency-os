import hashlib
import json
import sys
from pathlib import Path
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
import marketing_campaign_adapter as adapter


NOW = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)


def item(state="ready", brand=7):
    return {"id": 22, "brand_id": brand, "kind": "email_campaign", "channel": "email", "title": "Welcome", "body": "Subject: Welcome\n\nApproved launch fact.", "state": state, "revision": 3, "brief": {"subject": "Welcome", "campaign_policy": {"category": "marketing", "play": "welcome", "inactivity_days": 0, "cooldown_hours": 24, "max_per_7_days": 2, "quiet_start": "22:00", "quiet_end": "08:00", "timezone": "UTC", "service_event": ""}}}


CONFIG = {"schema_version": 1, "base_url": "http://localhost:8123", "credential_ref": "/home/agency/.config/agency/source.env", "credential_name": "SOURCE_TOKEN"}


def preview(audience="a" * 64, **changes):
    value = {"schema_version": 1, "brand_id": 7, "item_id": 22, "revision": 3, "message_digest": adapter._message_digest(item()), "policy_digest": adapter._policy_digest(item()["brief"]["campaign_policy"]), "audience_digest": audience, "source_revision": "rev_1", "eligible_count": 2, "suppressed_count": 1, "generated_at": (NOW - timedelta(minutes=1)).isoformat(), "expires_at": (NOW + timedelta(hours=2)).isoformat(), "provider_ready": True}
    value.update(changes)
    return value


class TestContract(unittest.TestCase):
    def current_contract(self):
        current = datetime.now(UTC)
        fresh = preview(generated_at=(current-timedelta(minutes=1)).isoformat(), expires_at=(current+timedelta(hours=2)).isoformat())
        return adapter.approval_contract(item(), CONFIG, fresh, current-timedelta(seconds=1), current-timedelta(minutes=1))

    def test_mutated_contract_never_reaches_source(self):
        original = self.current_contract()
        for changed in ({**original, 'recipients': ['private@example.com']},
                        {**original, 'audience_digest': 'f'*64},
                        {**original, 'message': {**original['message'], 'body': 'Changed copy'}},
                        {**original, 'policy': {**original['policy'], 'cooldown_hours': 48}}):
            with patch.object(adapter, '_request') as request:
                with self.assertRaises(ValueError): adapter.request_dispatch(changed, CONFIG, {})
                request.assert_not_called()

    def test_wrong_configuration_and_early_schedule_cannot_send(self):
        contract = self.current_contract()
        with patch.object(adapter, '_request') as request:
            with self.assertRaisesRegex(ValueError, 'config_digest_mismatch'):
                adapter.request_dispatch(contract, {**CONFIG, 'base_url':'http://localhost:8124'}, {})
            request.assert_not_called()
        current = datetime.now(UTC)
        future = adapter.approval_contract(item(), CONFIG, preview(generated_at=current.isoformat(), expires_at=(current+timedelta(hours=2)).isoformat()), current+timedelta(minutes=30), current)
        with patch.object(adapter, '_request') as request:
            with self.assertRaisesRegex(ValueError, 'send_not_due'):
                adapter.request_dispatch(future, CONFIG, {})
            request.assert_not_called()

    def test_preview_contains_rules_and_copy_and_rejects_wrong_identity(self):
        payload = adapter.preview_request(item(), NOW)
        self.assertEqual(payload['policy'], item()['brief']['campaign_policy'])
        self.assertEqual(payload['message']['subject'], 'Welcome')
        with patch.object(adapter, '_request', return_value=preview(brand_id=8)):
            with self.assertRaisesRegex(ValueError, 'preview_mismatch'):
                adapter.request_preview(item(), CONFIG, {}, NOW)

    def test_source_snapshot_created_during_request_is_not_future_data(self):
        response = preview(generated_at=(NOW+timedelta(milliseconds=500)).isoformat())
        with patch.object(adapter.time, 'monotonic', side_effect=[100,101]), patch.object(adapter, '_request', return_value=response):
            result = adapter.request_preview(item(), CONFIG, {}, NOW)
        self.assertEqual(result['generated_at'], response['generated_at'])

    def test_missing_subject_and_copy_cannot_be_reviewed(self):
        missing = item(); missing['body'] = 'Body without a subject'; missing['brief'].pop('subject')
        with self.assertRaisesRegex(ValueError, 'campaign_subject_required'):
            adapter.preview_request(missing, NOW)
        missing = item(); missing['body'] = ''
        with self.assertRaisesRegex(ValueError, 'campaign_copy_required'):
            adapter.preview_request(missing, NOW)

    def test_uncertain_response_never_claims_delivery(self):
        contract = self.current_contract()
        for response in ({}, {'recipients':['private@example.com']}, {'status':'delivered'}):
            with patch.object(adapter, '_credential', return_value='fixture-token'), patch.object(adapter, '_request', return_value=response):
                self.assertEqual(adapter.request_dispatch(contract, CONFIG, {})['status'], 'uncertain')

    def test_bad_local_credential_is_not_an_uncertain_send(self):
        with patch.object(adapter, '_credential', side_effect=ValueError('credential unavailable')), patch.object(adapter, '_request') as request:
            with self.assertRaisesRegex(ValueError, 'credential unavailable'):
                adapter.request_dispatch(self.current_contract(), CONFIG, {})
            request.assert_not_called()

    def test_suppression_can_shrink_but_never_grow_the_approved_audience(self):
        contract = self.current_contract()
        receipt = {key:contract[key] for key in ('schema_version','brand_id','item_id','revision','idempotency_key','audience_digest','message_digest','policy_digest','source_revision')}
        receipt.update(status='delivered',eligible_count=1,delivered_count=1,suppressed_count=1)
        self.assertEqual(adapter.validate_receipt(receipt, contract)['suppressed_count'], 1)
        with self.assertRaisesRegex(ValueError, 'receipt_count_exceeds_audience'):
            adapter.validate_receipt({**receipt,'eligible_count':3}, contract)
        with self.assertRaisesRegex(ValueError, 'incomplete_delivery_receipt'):
            adapter.validate_receipt({**receipt,'suppressed_count':0}, contract)

    def test_exact_hashes_bind_message_policy_and_approval(self):
        contract = adapter.approval_contract(item(), CONFIG, preview(), NOW + timedelta(minutes=30), NOW)
        self.assertEqual(len(contract["approval_digest"]), 64)
        self.assertEqual(contract["idempotency_key"], hashlib.sha256(("campaign:" + contract["approval_digest"]).encode()).hexdigest())
        changed = item(); changed["body"] = "Subject: Welcome\n\nDifferent approved fact."
        with self.assertRaisesRegex(ValueError, "preview_mismatch"):
            adapter.approval_contract(changed, CONFIG, preview(), NOW + timedelta(minutes=30), NOW)

    def test_unknown_recipient_fields_and_bad_source_counts_rejected(self):
        with self.assertRaisesRegex(ValueError, "invalid_preview"):
            adapter._validate_preview({**preview(), "recipients": ["person@example.com"]}, NOW)
        with self.assertRaisesRegex(ValueError, "invalid_preview_count"):
            adapter._validate_preview(preview(eligible_count=True), NOW)
        with self.assertRaisesRegex(ValueError, "source_not_ready"):
            adapter._validate_preview(preview(provider_ready=False), NOW)

    def test_expired_and_stale_preview_rejected(self):
        with self.assertRaisesRegex(ValueError, "invalid_preview_window"):
            adapter._validate_preview(preview(generated_at=(NOW - timedelta(minutes=6)).isoformat()), NOW)
        with self.assertRaisesRegex(ValueError, "preview_expired"):
            adapter.approval_contract(item(), CONFIG, preview(expires_at=(NOW + timedelta(minutes=1)).isoformat()), NOW + timedelta(minutes=2), NOW)

    def test_wrong_brand_and_receipt_growth_rejected(self):
        with self.assertRaisesRegex(ValueError, "preview_mismatch"):
            adapter.approval_contract(item(brand=8), CONFIG, preview(), NOW + timedelta(minutes=30), NOW)
        contract = adapter.approval_contract(item(), CONFIG, preview(), NOW + timedelta(minutes=30), NOW)
        receipt = {"schema_version": 1, "brand_id": 7, "item_id": 22, "revision": 3, "idempotency_key": contract["idempotency_key"], "audience_digest": contract["audience_digest"], "message_digest": contract["message_digest"], "policy_digest": contract["policy_digest"], "status": "delivered", "eligible_count": 2, "delivered_count": 2, "suppressed_count": 1, "source_revision": "rev_1"}
        with self.assertRaisesRegex(ValueError, "receipt_count_exceeds_audience"):
            adapter.validate_receipt(receipt, contract)

    def test_dispatch_requires_approval_and_network_becomes_uncertain(self):
        with self.assertRaisesRegex(ValueError, "approval_required"):
            adapter.request_dispatch({"idempotency_key": "x"}, CONFIG, {})
        current = datetime.now(UTC)
        fresh_preview = preview(generated_at=(current - timedelta(minutes=1)).isoformat(), expires_at=(current + timedelta(hours=2)).isoformat())
        contract = adapter.approval_contract(item(), CONFIG, fresh_preview, current - timedelta(seconds=1), current - timedelta(minutes=1))
        with patch.object(adapter, "_credential", return_value="secret"):
            result = adapter.request_dispatch(contract, CONFIG, {}, opener=lambda *a, **k: (_ for _ in ()).throw(OSError("offline")))
        self.assertEqual(result, {"status": "uncertain", "error": "source_unavailable"})

    def test_receipt_requires_exact_query_key(self):
        contract = adapter.approval_contract(item(), CONFIG, preview(), NOW + timedelta(minutes=30), NOW)
        with self.assertRaisesRegex(ValueError, "invalid_idempotency_key"):
            adapter.request_receipt({**contract, "idempotency_key": "bad"}, CONFIG, {})

    def test_config_is_localhost_only(self):
        with self.assertRaisesRegex(ValueError, "invalid_base_url"):
            adapter.validate_config({**CONFIG, "base_url": "https://example.com:443"})


if __name__ == "__main__":
    unittest.main()
