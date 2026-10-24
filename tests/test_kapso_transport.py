"""Phase 8A/8E — Kapso transport, inbound parsing, reply routing, dedupe.

Covers the reported defect directly: **no customer number is special-cased**.
Every assertion here runs offline: the Kapso API key is intentionally unset by
`tests/_bootstrap.py`, so no HTTP request can leave the process. Where a send is
expected to succeed, the single transport call is patched and asserted on.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import pathlib
import sys
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import _bootstrap  # noqa: F401,E402  (must run first)

from app.agent import load_context  # noqa: E402
from app.database import Customer, Conversation, Message, SessionLocal  # noqa: E402
from app.kapso import InboundMessage, describe_send_error, normalize_phone  # noqa: E402
from app.kapso import kapso  # noqa: E402
from app.poller import claim_message  # noqa: E402

# The owner's number from the bug report. It is used as ONE of several senders —
# never as a permission gate.
OWNER_NUMBER = "919389748900"
SECOND_CUSTOMER = "919876543210"
THIRD_CUSTOMER = "14155550123"
WEBHOOK_SECRET = "test-webhook-secret"


def _meta_style_payload(sender: str, body: str, message_id: str) -> dict:
    return {
        "entry": [{"changes": [{"value": {
            "messaging_product": "whatsapp",
            "contacts": [{"profile": {"name": "Test Sender"}, "wa_id": sender}],
            "messages": [{
                "from": sender, "id": message_id, "timestamp": "1727791200",
                "type": "text", "text": {"body": body},
            }],
        }}]}],
    }


def _sign(raw: bytes, secret: str = WEBHOOK_SECRET) -> str:
    return hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


class PhoneNormalisationTests(unittest.TestCase):
    """8A.1/8A.2 — the canonical wa_id form used for every lookup."""

    def test_normalisation_strips_formatting(self) -> None:
        for raw in ("+91 93897 48900", "91-93897-48900", "+919389748900"):
            self.assertEqual(normalize_phone(raw), OWNER_NUMBER)
        self.assertEqual(normalize_phone(None), "")
        self.assertEqual(normalize_phone("not a number"), "")

    def test_different_customers_normalise_to_different_ids(self) -> None:
        ids = {normalize_phone(n) for n in (OWNER_NUMBER, SECOND_CUSTOMER, THIRD_CUSTOMER)}
        self.assertEqual(len(ids), 3)


class InboundParsingTests(unittest.TestCase):
    """8A.1/8A.2/8A.3 — every sender is parsed, regardless of who they are."""

    def test_meta_envelope_parsed_for_any_sender(self) -> None:
        for sender in (OWNER_NUMBER, SECOND_CUSTOMER, THIRD_CUSTOMER):
            parsed = kapso.parse_webhook(
                _meta_style_payload(sender, "hello", f"wamid.{sender}")
            )
            self.assertEqual(len(parsed), 1, f"sender {sender} was dropped")
            self.assertEqual(parsed[0].wa_id, sender)
            self.assertEqual(parsed[0].text, "hello")

    def test_single_object_payload_parsed(self) -> None:
        parsed = kapso.parse_webhook({
            "message": {"from": SECOND_CUSTOMER, "id": "wamid.single",
                        "type": "text", "text": {"body": "price please"}},
            "conversation": {"id": "conv-1", "contact_name": "Ravi"},
        })
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0].wa_id, SECOND_CUSTOMER)
        self.assertEqual(parsed[0].sender_name, "Ravi")
        self.assertEqual(parsed[0].conversation_id, "conv-1")

    def test_batch_envelope_parsed_for_several_customers(self) -> None:
        payload = {
            "type": "whatsapp.message.received", "batch": True,
            "data": [
                {"message": {"from": OWNER_NUMBER, "id": "wamid.b1",
                             "type": "text", "text": {"body": "first"}}},
                {"message": {"from": THIRD_CUSTOMER, "id": "wamid.b2",
                             "type": "text", "text": {"body": "second"}}},
            ],
        }
        parsed = kapso.parse_webhook(payload)
        self.assertEqual([m.wa_id for m in parsed], [OWNER_NUMBER, THIRD_CUSTOMER])

    def test_our_own_outbound_echo_is_ignored(self) -> None:
        payload = {"message": {
            "from": OWNER_NUMBER, "id": "wamid.echo", "type": "text",
            "text": {"body": "our reply"},
            "kapso": {"direction": "outbound"},
        }}
        self.assertEqual(kapso.parse_webhook(payload), [])

    def test_interactive_button_tap_yields_button_id(self) -> None:
        payload = {"message": {
            "from": SECOND_CUSTOMER, "id": "wamid.tap", "type": "interactive",
            "interactive": {"type": "button_reply",
                            "button_reply": {"id": "lang_te", "title": "తెలుగు"}},
        }}
        parsed = kapso.parse_webhook(payload)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0].button_id, "lang_te")

    def test_status_events_are_not_treated_as_messages(self) -> None:
        payload = {"message": {
            "from": OWNER_NUMBER, "id": "wamid.status-none", "type": "text",
            "text": {"body": ""},
        }}
        self.assertEqual(kapso.parse_webhook(payload), [])

    def test_delivery_status_events_are_parsed(self) -> None:
        payload = {"entry": [{"changes": [{"value": {"statuses": [
            {"id": "wamid.out1", "status": "delivered"},
            {"id": "wamid.out2", "status": "read"},
            {"id": "", "status": "sent"},  # no id -> dropped
        ]}}]}]}
        parsed = kapso.parse_statuses(payload)
        self.assertEqual(
            parsed,
            [{"message_id": "wamid.out1", "status": "delivered"},
             {"message_id": "wamid.out2", "status": "read"}],
        )


class WebhookSecurityTests(unittest.TestCase):
    """8A.6/8A.7 — signature contract and fail-closed behaviour."""

    def test_valid_signature_accepted(self) -> None:
        raw = b'{"hello":"world"}'
        self.assertTrue(kapso.verify_signature(raw, _sign(raw)))

    def test_sha256_prefixed_signature_accepted(self) -> None:
        raw = b'{"hello":"world"}'
        self.assertTrue(kapso.verify_signature(raw, "sha256=" + _sign(raw)))

    def test_tampered_body_rejected(self) -> None:
        raw = b'{"hello":"world"}'
        self.assertFalse(kapso.verify_signature(raw + b" ", _sign(raw)))

    def test_wrong_secret_rejected(self) -> None:
        raw = b'{"hello":"world"}'
        self.assertFalse(kapso.verify_signature(raw, _sign(raw, "wrong-secret")))

    def test_missing_header_rejected(self) -> None:
        self.assertFalse(kapso.verify_signature(b"{}", None))

    def test_fails_closed_without_a_configured_secret(self) -> None:
        raw = b"{}"
        with patch.object(kapso, "webhook_secret", ""):
            self.assertFalse(kapso.verify_signature(raw, _sign(raw)))


class SendErrorClassificationTests(unittest.TestCase):
    """The piece that makes "only my number gets replies" diagnosable."""

    def test_sandbox_allowlist_error_is_named(self) -> None:
        body = ('{"error":{"message":"(#131030) Recipient phone number not in '
                'allowed list","code":131030}}')
        detail = describe_send_error(body)
        self.assertIn("RECIPIENT NOT ALLOWED", detail)
        self.assertIn("allowlist", detail.lower())

    def test_closed_service_window_is_named(self) -> None:
        body = '{"error":{"code":131047,"message":"Re-engagement message"}}'
        self.assertIn("24-HOUR WINDOW", describe_send_error(body))

    def test_undeliverable_recipient_is_named(self) -> None:
        self.assertIn("UNDELIVERABLE",
                      describe_send_error('{"error":{"code":131026}}'))

    def test_unknown_error_is_passed_through_verbatim(self) -> None:
        detail = describe_send_error("Kapso send failed HTTP 500: upstream boom")
        self.assertIn("upstream boom", detail)

    def test_empty_error_is_described(self) -> None:
        self.assertIn("no detail", describe_send_error(""))

    def test_missing_credentials_error_is_actionable_and_secret_free(self) -> None:
        # 8A.11 — with the (test) key unset, the failure names the variable.
        detail = describe_send_error("Kapso send failed HTTP 401: KAPSO_API_KEY is not configured")
        self.assertIn("KAPSO_API_KEY", detail)
        self.assertNotIn("test-webhook-secret", detail)


class ConversationIsolationTests(unittest.TestCase):
    """8A.5 / Phase 5 — separate customers never share a context."""

    def _new_customer(self, db, phone: str, name: str) -> Customer:
        cust = Customer(phone=phone, display_phone=f"+{phone}", whatsapp_name=name)
        db.add(cust)
        db.flush()
        return cust

    def test_each_customer_gets_their_own_conversation(self) -> None:
        db = SessionLocal()
        try:
            a = self._new_customer(db, "919000000001", "Customer A")
            b = self._new_customer(db, "919000000002", "Customer B")
            conv_a = Conversation(customer_id=a.id, channel="whatsapp")
            conv_b = Conversation(customer_id=b.id, channel="whatsapp")
            db.add_all([conv_a, conv_b])
            db.commit()

            ctx_a = load_context(db, "919000000001", "Customer A")
            ctx_b = load_context(db, "919000000002", "Customer B")
            self.assertNotEqual(ctx_a.conversation.id, ctx_b.conversation.id)

            db.add(Message(conversation_id=conv_a.id, direction="in",
                           sender="customer", body="a-private-detail",
                           status="received"))
            db.commit()

            ctx_b_reloaded = load_context(db, "919000000002", "Customer B")
            bodies = [m.get("body") for m in ctx_b_reloaded.history]
            self.assertNotIn("a-private-detail", bodies,
                             "customer A's message leaked into customer B's context")
        finally:
            db.close()

    def test_conversations_are_isolated_by_customer_not_by_owner(self) -> None:
        db = SessionLocal()
        try:
            ctx_owner = load_context(db, OWNER_NUMBER, "Owner")
            ctx_other = load_context(db, SECOND_CUSTOMER, "Other")
            db.commit()
            self.assertNotEqual(ctx_owner.conversation.id, ctx_other.conversation.id)
            self.assertNotEqual(ctx_owner.customer.id, ctx_other.customer.id)
        finally:
            db.close()


class DuplicateDeliveryTests(unittest.TestCase):
    """8A.8 — a replayed webhook must not produce a second reply."""

    def test_first_claim_wins_and_replays_lose(self) -> None:
        db = SessionLocal()
        try:
            mid = "wamid.dedupe-check-1"
            self.assertTrue(claim_message(db, mid, "conv-x"))
            self.assertFalse(claim_message(db, mid, "conv-x"))
            self.assertFalse(claim_message(db, mid, "conv-y"))
        finally:
            db.close()

    def test_missing_message_id_is_never_treated_as_a_duplicate(self) -> None:
        db = SessionLocal()
        try:
            self.assertTrue(claim_message(db, "", "conv-z"))
        finally:
            db.close()


class ReplyRoutingTests(unittest.IsolatedAsyncioTestCase):
    """8A.1/8A.2/8A.4 — a NON-owner customer gets a reply addressed to them."""

    async def _run_turn_pair(self, sender: str) -> list:
        from app.agent import agent

        calls: list = []

        async def _record(to_wa_id, text, *args, **kwargs):
            calls.append((to_wa_id, text))
            return {"message_id": f"wamid.reply.{len(calls)}"}

        first = InboundMessage(
            message_id=f"wamid.{sender}.1", wa_id=sender, text="hi",
            sender_name="Test Customer",
        )
        second = InboundMessage(
            message_id=f"wamid.{sender}.2", wa_id=sender,
            text="do you have an SUV available tomorrow?",
            sender_name="Test Customer",
        )
        with patch.object(kapso, "send_text", new=AsyncMock(side_effect=_record)), \
             patch.object(kapso, "send_interactive_list",
                          new=AsyncMock(side_effect=RuntimeError("no interactive transport"))), \
             patch.object(kapso, "send_interactive_buttons",
                          new=AsyncMock(side_effect=RuntimeError("no interactive transport"))):
            await agent.handle_inbound(first)
            await agent.handle_inbound(second)
        return calls

    async def test_non_owner_customer_is_answered(self) -> None:
        calls = await self._run_turn_pair(SECOND_CUSTOMER)
        self.assertTrue(calls, "a non-owner customer received no reply at all")
        for to_wa_id, _text in calls:
            self.assertEqual(to_wa_id, SECOND_CUSTOMER,
                             "the reply was sent to the wrong recipient")

    async def test_owner_and_other_customers_are_treated_identically(self) -> None:
        owner_calls = await self._run_turn_pair(OWNER_NUMBER)
        other_calls = await self._run_turn_pair(THIRD_CUSTOMER)
        # Both senders produced a reply, each addressed to themselves.
        self.assertTrue(owner_calls)
        self.assertTrue(other_calls)
        self.assertTrue(all(to == OWNER_NUMBER for to, _ in owner_calls))
        self.assertTrue(all(to == THIRD_CUSTOMER for to, _ in other_calls))

    async def test_outbound_failure_is_recorded_with_the_recipient_conversation(self) -> None:
        from app.agent import agent

        sender = "919000000004"
        await agent.handle_inbound(InboundMessage(
            message_id="wamid.fail.1", wa_id=sender, text="hello"))

        db = SessionLocal()
        try:
            cust = db.query(Customer).filter(Customer.phone == sender).one()
            conv = db.query(Conversation).filter(
                Conversation.customer_id == cust.id).one()
            outbound = db.query(Message).filter(
                Message.conversation_id == conv.id,
                Message.direction == "out").all()
            self.assertTrue(outbound, "no outbound row was persisted for the turn")
            # Credentials are deliberately absent in tests -> a real failure,
            # recorded honestly rather than reported as sent.
            self.assertIn(outbound[-1].status, {"failed", "error"})
            self.assertIn("KAPSO_API_KEY", outbound[-1].error_detail or "")
        finally:
            db.close()


class WebhookEndpointTests(unittest.IsolatedAsyncioTestCase):
    """8A.6/8A.7 — the HTTP contract, without running the lifespan poller."""

    async def _post(self, payload: dict, signature: str | None):
        import httpx

        from main import app

        raw = json.dumps(payload).encode()
        headers = {"Content-Type": "application/json"}
        if signature is not None:
            headers["X-Webhook-Signature"] = signature
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                     base_url="http://testserver") as client:
            return await client.post("/api/whatsapp/webhook", content=raw,
                                     headers=headers)

    async def test_unsigned_webhook_is_rejected(self) -> None:
        response = await self._post(_meta_style_payload(SECOND_CUSTOMER, "hi", "w1"), None)
        self.assertEqual(response.status_code, 401)

    async def test_badly_signed_webhook_is_rejected(self) -> None:
        response = await self._post(
            _meta_style_payload(SECOND_CUSTOMER, "hi", "w2"), "deadbeef")
        self.assertEqual(response.status_code, 401)

    async def test_signed_webhook_from_a_new_customer_is_accepted(self) -> None:
        # 8A.2/8A.3: a brand-new, non-owner number is NOT rejected.
        sender = "919000000009"
        raw = json.dumps(_meta_style_payload(sender, "hello there", "wamid.new")).encode()
        import httpx

        from main import app

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                     base_url="http://testserver") as client:
            response = await client.post(
                "/api/whatsapp/webhook", content=raw,
                headers={"Content-Type": "application/json",
                         "X-Webhook-Signature": _sign(raw)})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "accepted")

        db = SessionLocal()
        try:
            cust = db.query(Customer).filter(Customer.phone == sender).first()
            self.assertIsNotNone(cust, "a new non-owner customer was not recorded")
        finally:
            db.close()

    async def test_replayed_webhook_does_not_create_a_second_reply(self) -> None:
        sender = "919000000010"
        payload = _meta_style_payload(sender, "one more", "wamid.replay")
        raw = json.dumps(payload).encode()
        import httpx

        from main import app

        transport = httpx.ASGITransport(app=app)
        for _ in range(2):
            async with httpx.AsyncClient(transport=transport,
                                        base_url="http://testserver") as client:
                response = await client.post(
                    "/api/whatsapp/webhook", content=raw,
                    headers={"Content-Type": "application/json",
                             "X-Webhook-Signature": _sign(raw)})
                self.assertEqual(response.status_code, 200)

        db = SessionLocal()
        try:
            cust = db.query(Customer).filter(Customer.phone == sender).one()
            conv = db.query(Conversation).filter(
                Conversation.customer_id == cust.id).one()
            outbound = db.query(Message).filter(
                Message.conversation_id == conv.id,
                Message.direction == "out").all()
            self.assertEqual(len(outbound), 1,
                             "a replayed webhook produced a duplicate reply")
        finally:
            db.close()


class NoOwnerAllowlistRegressionTests(unittest.TestCase):
    """8E.43 — the reported bug cannot silently return."""

    def setUp(self) -> None:
        self.app_dir = pathlib.Path(_bootstrap.__file__).resolve().parent.parent / "backend" / "app"

    def test_application_source_has_no_owner_number_hardcoded(self) -> None:
        offenders: list[str] = []
        for path in sorted(self.app_dir.rglob("*.py")):
            text = path.read_text(encoding="utf-8", errors="replace")
            if "9389748900" in text:
                offenders.append(str(path))
        self.assertEqual(offenders, [],
                         "an owner number is hardcoded in application source")

    def test_application_source_has_no_sender_allowlist_construct(self) -> None:
        # Case-insensitive, but word-boundary anchored so ordinary prose about
        # "the owner" or "an allowlist" in a comment/docstring is not a hit:
        # only an actual identifier-like sender gate counts.
        import re

        gate = re.compile(
            r"\b(ALLOWED_NUMBERS|OWNER_NUMBER|owner_number|allowed_senders|"
            r"allowed_numbers|is_owner_number|OWNER_PHONE)\b",
            re.IGNORECASE,
        )
        offenders: list[str] = []
        for path in sorted(self.app_dir.rglob("*.py")):
            text = path.read_text(encoding="utf-8", errors="replace")
            if gate.search(text):
                offenders.append(path.name)
        self.assertEqual(offenders, [],
                         f"sender-restriction constructs found in: {offenders}")


if __name__ == "__main__":
    unittest.main()
