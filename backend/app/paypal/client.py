"""Typed, resilient PayPal REST client.

- OAuth client-credentials token cached until shortly before expiry.
- Retries with exponential backoff on 429 / 5xx / transport errors.
- Every mutating call carries a ``PayPal-Request-Id`` so retries are idempotent on PayPal's side.
- Live mutations are refused unless ALLOW_LIVE=true (belt and braces with config).
"""
from __future__ import annotations

import base64
import time
import uuid
from dataclasses import dataclass
from typing import Any

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential_jitter

from app.config import Settings, get_settings
from app.logging import get_logger

log = get_logger("paypal")


class PayPalError(RuntimeError):
    def __init__(self, status: int, body: Any, method: str, path: str):
        self.status = status
        self.body = body
        self.method = method
        self.path = path
        name = body.get("name") if isinstance(body, dict) else None
        super().__init__(f"{method} {path} -> {status} {name or body}")

    @property
    def retryable(self) -> bool:
        return self.status == 429 or self.status >= 500


def _is_retryable(exc: BaseException) -> bool:
    return isinstance(exc, (httpx.TransportError,)) or (isinstance(exc, PayPalError) and exc.retryable)


@dataclass
class _Token:
    value: str
    expires_at: float


class PayPalClient:
    MUTATING = {"POST", "PATCH", "PUT", "DELETE"}

    def __init__(self, settings: Settings | None = None, transport: httpx.BaseTransport | None = None):
        self.s = settings or get_settings()
        self._http = httpx.Client(base_url=self.s.paypal_base_url, timeout=30.0, transport=transport)
        self._token: _Token | None = None

    # ---------------------------------------------------------------- auth

    def _get_token(self) -> str:
        if self._token and self._token.expires_at - 60 > time.time():
            return self._token.value
        if not self.s.paypal_configured:
            raise RuntimeError("PayPal credentials not configured (PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET)")
        basic = base64.b64encode(f"{self.s.paypal_client_id}:{self.s.paypal_client_secret}".encode()).decode()
        r = self._http.post(
            "/v1/oauth2/token",
            headers={"Authorization": f"Basic {basic}"},
            data={"grant_type": "client_credentials"},
        )
        if r.status_code != 200:
            raise PayPalError(r.status_code, _safe_json(r), "POST", "/v1/oauth2/token")
        body = r.json()
        self._token = _Token(body["access_token"], time.time() + int(body.get("expires_in", 3600)))
        return self._token.value

    # ---------------------------------------------------------------- core

    @retry(
        retry=retry_if_exception(_is_retryable),
        wait=wait_exponential_jitter(initial=0.5, max=8),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    def request(
        self,
        method: str,
        path: str,
        *,
        json: Any | None = None,
        params: dict | None = None,
        headers: dict | None = None,
        request_id: str | None = None,
    ) -> Any:
        method = method.upper()
        if method in self.MUTATING and self.s.paypal_env == "live" and not self.s.allow_live:
            raise RuntimeError("Refusing live mutation: ALLOW_LIVE is not set")
        hdrs = {
            "Authorization": f"Bearer {self._get_token()}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }
        if method in self.MUTATING:
            hdrs["PayPal-Request-Id"] = request_id or str(uuid.uuid4())
        if headers:
            hdrs.update(headers)
        r = self._http.request(method, path, json=json, params=params, headers=hdrs)
        if r.status_code == 401 and self._token:
            # token revoked server-side; refresh once
            self._token = None
            hdrs["Authorization"] = f"Bearer {self._get_token()}"
            r = self._http.request(method, path, json=json, params=params, headers=hdrs)
        if r.status_code >= 400:
            err = PayPalError(r.status_code, _safe_json(r), method, path)
            log.warning("paypal.error", status=r.status_code, path=path, body=err.body)
            raise err
        if r.status_code == 204 or not r.content:
            return {}
        return r.json()

    def get(self, path: str, **kw) -> Any:
        return self.request("GET", path, **kw)

    def post(self, path: str, json: Any | None = None, **kw) -> Any:
        return self.request("POST", path, json=json, **kw)

    # ---------------------------------------------------------------- orders / payments

    def get_order(self, order_id: str) -> dict:
        return self.get(f"/v2/checkout/orders/{order_id}")

    def create_order(self, body: dict, request_id: str | None = None) -> dict:
        return self.post("/v2/checkout/orders", body, request_id=request_id)

    def capture_order(self, order_id: str, body: dict | None = None, request_id: str | None = None) -> dict:
        return self.post(f"/v2/checkout/orders/{order_id}/capture", body or {}, request_id=request_id)

    def get_capture(self, capture_id: str) -> dict:
        return self.get(f"/v2/payments/captures/{capture_id}")

    def refund_capture(self, capture_id: str, amount: dict | None, note: str, request_id: str) -> dict:
        body: dict[str, Any] = {"note_to_payer": note[:255]}
        if amount:
            body["amount"] = amount
        return self.post(f"/v2/payments/captures/{capture_id}/refund", body, request_id=request_id)

    def get_refund(self, refund_id: str) -> dict:
        return self.get(f"/v2/payments/refunds/{refund_id}")

    def get_authorization(self, auth_id: str) -> dict:
        return self.get(f"/v2/payments/authorizations/{auth_id}")

    def void_authorization(self, auth_id: str, request_id: str) -> dict:
        return self.post(f"/v2/payments/authorizations/{auth_id}/void", {}, request_id=request_id)

    # ---------------------------------------------------------------- payouts

    def create_payout(self, body: dict, request_id: str) -> dict:
        return self.post("/v1/payments/payouts", body, request_id=request_id)

    def get_payout_batch(self, batch_id: str) -> dict:
        return self.get(f"/v1/payments/payouts/{batch_id}")

    # ---------------------------------------------------------------- invoices

    def create_invoice(self, body: dict, request_id: str) -> dict:
        return self.post("/v2/invoicing/invoices", body, request_id=request_id)

    def send_invoice(self, invoice_id: str, request_id: str) -> dict:
        return self.post(f"/v2/invoicing/invoices/{invoice_id}/send", {"send_to_recipient": True}, request_id=request_id)

    def get_invoice(self, invoice_id: str) -> dict:
        return self.get(f"/v2/invoicing/invoices/{invoice_id}")

    def record_invoice_payment(self, invoice_id: str, body: dict, request_id: str) -> dict:
        return self.post(f"/v2/invoicing/invoices/{invoice_id}/payments", body, request_id=request_id)

    def list_invoices(self, page: int = 1, page_size: int = 50) -> dict:
        return self.get("/v2/invoicing/invoices", params={"page": page, "page_size": page_size, "total_required": "true"})

    # ---------------------------------------------------------------- disputes

    def list_disputes(self, page_size: int = 50, next_page_token: str | None = None, **filters) -> dict:
        params = {"page_size": page_size, **filters}
        if next_page_token:
            params["next_page_token"] = next_page_token
        return self.get("/v1/customer/disputes", params=params)

    def get_dispute(self, dispute_id: str) -> dict:
        return self.get(f"/v1/customer/disputes/{dispute_id}")

    def provide_evidence(self, dispute_id: str, evidences: list[dict], request_id: str) -> dict:
        """Submit text evidence (no attachments) for a dispute."""
        body = {"evidences": evidences}
        return self.post(f"/v1/customer/disputes/{dispute_id}/provide-evidence", body, request_id=request_id)

    def send_dispute_message(self, dispute_id: str, message: str, request_id: str) -> dict:
        return self.post(f"/v1/customer/disputes/{dispute_id}/send-message", {"message": message}, request_id=request_id)

    def accept_claim(self, dispute_id: str, note: str, request_id: str) -> dict:
        return self.post(f"/v1/customer/disputes/{dispute_id}/accept-claim", {"note": note}, request_id=request_id)

    # ---------------------------------------------------------------- reporting

    def list_transactions(self, start: str, end: str, page: int = 1, page_size: int = 100) -> dict:
        return self.get(
            "/v1/reporting/transactions",
            params={
                "start_date": start,
                "end_date": end,
                "fields": "transaction_info",
                "page": page,
                "page_size": page_size,
            },
        )

    # ---------------------------------------------------------------- webhooks

    def verify_webhook_signature(self, headers: dict, body: dict, webhook_id: str) -> bool:
        payload = {
            "auth_algo": headers.get("paypal-auth-algo", ""),
            "cert_url": headers.get("paypal-cert-url", ""),
            "transmission_id": headers.get("paypal-transmission-id", ""),
            "transmission_sig": headers.get("paypal-transmission-sig", ""),
            "transmission_time": headers.get("paypal-transmission-time", ""),
            "webhook_id": webhook_id,
            "webhook_event": body,
        }
        r = self.post("/v1/notifications/verify-webhook-signature", payload)
        return r.get("verification_status") == "SUCCESS"

    def healthcheck(self) -> bool:
        try:
            self._get_token()
            return True
        except Exception:  # noqa: BLE001
            return False


def _safe_json(r: httpx.Response) -> Any:
    try:
        return r.json()
    except ValueError:
        return r.text
