"""Fictional PRs for a reproducible, honestly labeled local walkthrough.

These are hand-authored patches, not live UFO work or measured model results.
Training samples have no feedback until a human reviews them. Held-out labels
are kept in a separate collection and must never be sent to the reviewer.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .core import normalize_experience


DATASET_VERSION = "reflex-synthetic-prs-v1"
# Fixture revision metadata, not a claim that any agent work happened at this time.
FIXTURE_REVISION_AT = "2026-09-27T00:00:00.000Z"


_CONVENTIONS = [
    "Bug fixes need a regression test in the patch.",
    "Production services must not catch Exception or use bare except.",
    "Network calls need explicit timeouts.",
    "Check authorization for access to user-owned resources.",
    "Parameterize SQL, validate untrusted paths, and keep secrets out of code.",
    "Report concrete blocking issues only; do not reject for style preferences.",
]


def _pr(identifier: str, title: str, diff: str, *, split: str = "train", change_type: str = "feature", details: str = "") -> dict[str, Any]:
    example = normalize_experience({
        "id": identifier,
        "title": title,
        "task": "Review this pull request and decide whether it is safe to merge.",
        "repo": "fictional/reflex-workbench",
        "diff": diff.strip(),
        "context": {
            "fictional": True,
            "change_type": change_type,
            "engineering_conventions": _CONVENTIONS,
            "review_context": details,
            "test_evidence": "No tests have been executed. Review any test changes visible in the patch.",
        },
        "agent_review": None,
        "human_feedback": None,
        "trajectory": [],
        "source": "sample",
        "split": split,
    })
    example["created_at"] = FIXTURE_REVISION_AT
    example["updated_at"] = FIXTURE_REVISION_AT
    return example


SAMPLE_PRS: list[dict[str, Any]] = [
    _pr("sample-01", "Keep checkout alive when payment fails", """
diff --git a/payments.py b/payments.py
--- a/payments.py
+++ b/payments.py
@@ -8,1 +8,4 @@
-    receipt = gateway.charge(order)
+    try:
+        receipt = gateway.charge(order)
+    except Exception:
+        return {"status": "paid"}
""", change_type="bugfix", details="This patch is the complete PR. Failed charges must never appear paid."),
    _pr("sample-02", "Handle a declined card explicitly", """
diff --git a/checkout.py b/checkout.py
@@ -4,1 +4,4 @@
-    return charge(card)
+    try:
+        return charge(card)
+    except CardDeclined:
+        return {"status": "declined"}
diff --git a/tests/test_checkout.py b/tests/test_checkout.py
@@ -0,0 +1,4 @@
+def test_declined_card_is_not_paid(monkeypatch):
+    monkeypatch.setattr(checkout, "charge", raise_declined)
+    assert checkout.purchase("card") == {"status": "declined"}
+    assert receipts.count() == 0
""", change_type="bugfix", details="CardDeclined is a documented domain exception; raise_declined and receipts are existing test helpers."),
    _pr("sample-03", "Add account lookup by email", """
diff --git a/accounts.py b/accounts.py
@@ -0,0 +1,3 @@
+def find_account(connection, email):
+    query = f"SELECT id FROM accounts WHERE email = '{email}'"
+    return connection.execute(query).fetchone()
""", details="email comes from an unauthenticated account-recovery request."),
    _pr("sample-04", "Use bound parameters for account search", """
diff --git a/search.py b/search.py
@@ -0,0 +1,3 @@
+def search_accounts(connection, email):
+    return connection.execute(
+        "SELECT id FROM accounts WHERE email = ?", (email,)).fetchall()
diff --git a/tests/test_search.py b/tests/test_search.py
@@ -0,0 +1,2 @@
+def test_quote_in_email_is_data(db):
+    assert search_accounts(db, "x' OR 1=1 --") == []
"""),
    _pr("sample-05", "Fetch inventory from supplier", """
diff --git a/inventory.py b/inventory.py
@@ -0,0 +1,5 @@
+import requests
+def supplier_inventory(sku):
+    response = requests.get(SUPPLIER_URL, params={"sku": sku})
+    response.raise_for_status()
+    return response.json()
""", details="This synchronous function runs in a worker thread; SUPPLIER_URL is trusted configuration."),
    _pr("sample-06", "Bound supplier request duration", """
diff --git a/supplier.py b/supplier.py
@@ -0,0 +1,5 @@
+def current_stock(sku):
+    response = requests.get(SUPPLIER_URL, params={"sku": sku}, timeout=(2, 8))
+    response.raise_for_status()
+    return response.json()["available"]
+
""", details="Called synchronously from the existing background worker; malformed upstream responses should fail visibly."),
    _pr("sample-07", "Expose invoice detail endpoint", """
diff --git a/invoices.py b/invoices.py
@@ -0,0 +1,4 @@
+@router.get("/invoices/{invoice_id}")
+def invoice_detail(invoice_id, user=Depends(current_user)):
+    invoice = db.get_invoice(invoice_id)
+    return invoice.to_dict()
""", details="Invoice IDs are guessable. db.get_invoice does no ownership filtering. Authentication alone does not grant access to another customer's invoice."),
    _pr("sample-08", "Filter invoice reads by owner", """
diff --git a/invoice_read.py b/invoice_read.py
@@ -0,0 +1,6 @@
+def read_invoice(invoice_id, user):
+    invoice = db.find_invoice(id=invoice_id, owner_id=user.id)
+    if invoice is None:
+        raise HTTPException(404, "Invoice not found")
+    return invoice.to_dict()
+
""", details="db.find_invoice uses a parameterized query. The route supplies an authenticated user."),
    _pr("sample-09", "Download uploaded reports", """
diff --git a/reports.py b/reports.py
@@ -0,0 +1,3 @@
+@router.get("/reports/{name:path}")
+def download(name):
+    return FileResponse(REPORT_ROOT / name)
""", details="The route is authenticated for a shared report collection. name is fully user-controlled. REPORT_ROOT contains only public team reports."),
    _pr("sample-10", "Confine report downloads to the report root", """
diff --git a/report_files.py b/report_files.py
@@ -0,0 +1,7 @@
+def resolve_report(name):
+    root = REPORT_ROOT.resolve()
+    candidate = (root / name).resolve()
+    if not candidate.is_relative_to(root) or not candidate.is_file():
+        raise HTTPException(404, "Report not found")
+    return FileResponse(candidate)
+
""", details="Trusted process owns this read-only directory; untrusted users cannot modify symlinks. Authorization is handled by the existing route."),
    _pr("sample-11", "Preserve optional labels on tickets", """
diff --git a/tickets.py b/tickets.py
@@ -0,0 +1,4 @@
+def new_ticket(title, labels=[]):
+    labels.append("new")
+    return Ticket(title=title, labels=labels)
+
""", details="Called for independent requests. Ticket stores the passed labels list without copying."),
    _pr("sample-12", "Create independent default ticket labels", """
diff --git a/ticket_factory.py b/ticket_factory.py
@@ -0,0 +1,4 @@
+def create_ticket(title, labels=None):
+    ticket_labels = list(labels) if labels is not None else []
+    ticket_labels.append("new")
+    return Ticket(title=title, labels=ticket_labels)
"""),
    _pr("sample-13", "Move API credentials into service module", """
diff --git a/service_config.py b/service_config.py
@@ -0,0 +1,3 @@
+# Fictional placeholder represents a committed production credential.
+API_KEY = "fictional-production-credential-do-not-use"
+client = VendorClient(api_key=API_KEY)
""", details="All data is fictional. The change represents moving a production credential from managed configuration into committed source."),
    _pr("sample-14", "Read service credentials from configuration", """
diff --git a/vendor_client.py b/vendor_client.py
@@ -0,0 +1,5 @@
+import os
+def vendor_client():
+    credential = os.environ["VENDOR_CREDENTIAL"]
+    return VendorClient(api_key=credential, timeout=10)
+
""", details="The application already validates environment configuration at startup. VendorClient is the team's existing authenticated client."),
    _pr("sample-15", "Restore uploaded user preferences", """
diff --git a/preferences.py b/preferences.py
@@ -0,0 +1,4 @@
+import pickle
+def restore_preferences(upload_bytes):
+    preferences = pickle.loads(upload_bytes)
+    return preferences
""", details="upload_bytes comes directly from a signed-in user's upload; users are not trusted to execute code on the server."),
    _pr("sample-16", "Parse preference uploads as validated JSON", """
diff --git a/preference_import.py b/preference_import.py
@@ -0,0 +1,4 @@
+import json
+def import_preferences(upload_bytes):
+    payload = json.loads(upload_bytes)
+    return PreferenceSchema.model_validate(payload)
""", details="Uploads are size limited to 32 KiB by the route. Existing PreferenceSchema forbids extra fields and validates all accepted preferences."),
    _pr("sample-17", "Load exchange rate in an async route", """
diff --git a/exchange.py b/exchange.py
@@ -0,0 +1,5 @@
+@router.get("/rate")
+async def exchange_rate():
+    response = requests.get(RATE_URL, timeout=5)
+    response.raise_for_status()
+    return response.json()
""", details="requests performs blocking I/O. RATE_URL is trusted. The ASGI server shares this event loop with concurrent requests."),
    _pr("sample-18", "Use the shared async rate client", """
diff --git a/rates.py b/rates.py
@@ -0,0 +1,5 @@
+@router.get("/exchange-rate")
+async def get_rate():
+    response = await rate_client.get(RATE_URL, timeout=5)
+    response.raise_for_status()
+    return response.json()
""", details="rate_client is an existing httpx.AsyncClient opened at startup and closed at shutdown. RATE_URL is trusted."),
    _pr("sample-19", "Accept inventory reservations", """
diff --git a/reservations.py b/reservations.py
@@ -0,0 +1,6 @@
+def reserve(db, sku):
+    available = db.get_stock(sku)
+    if available < 1:
+        raise SoldOut()
+    db.set_stock(sku, available - 1)
+    return Reservation(sku)
""", details="Each DB helper commits separately. Multiple workers reserve the same SKU concurrently. No lock or transaction surrounds this function."),
    _pr("sample-20", "Reserve inventory with an atomic update", """
diff --git a/stock_reservation.py b/stock_reservation.py
@@ -0,0 +1,7 @@
+def reserve_one(db, sku):
+    with db.transaction():
+        changed = db.execute("UPDATE stock SET qty = qty - 1 WHERE sku = ? AND qty > 0", (sku,))
+        if changed.rowcount != 1:
+            raise SoldOut()
+        return db.create_reservation(sku)
+
""", details="db.transaction commits on success and rolls back on exceptions. The stock row is unique per SKU; reservation creation uses the same transaction."),
    _pr("sample-21", "Allow callers to select pagination size", """
diff --git a/list_orders.py b/list_orders.py
@@ -0,0 +1,4 @@
+def list_orders(request):
+    limit = int(request.query_params.get("limit", "25"))
+    return db.orders_for_user(request.user.id, limit=limit)
+
""", details="The DB helper accepts any integer with no maximum. This endpoint has no other request validation. Callers may send non-integers, negative limits, or millions of rows."),
    _pr("sample-22", "Validate order pagination at the boundary", """
diff --git a/order_api.py b/order_api.py
@@ -0,0 +1,4 @@
+@router.get("/orders")
+def orders(limit: int = Query(default=25, ge=1, le=100), user=Depends(current_user)):
+    return db.orders_for_user(user.id, limit=limit)
+
""", details="FastAPI Query validation rejects malformed and out-of-range values. DB access is parameterized and scoped to user ownership."),
    _pr("sample-23", "Process retried billing webhooks", """
diff --git a/billing_webhook.py b/billing_webhook.py
@@ -0,0 +1,4 @@
+def handle_invoice_paid(event):
+    verify_signature(event)
+    account = db.account_for(event.customer_id)
+    db.add_credit(account.id, event.credit_amount)
""", details="The provider retries delivery with the same event ID. add_credit always increments; the route and database provide no duplicate-event protection."),
    _pr("sample-24", "Credit billing events once", """
diff --git a/billing_events.py b/billing_events.py
@@ -0,0 +1,7 @@
+def credit_paid_invoice(event):
+    verify_signature(event)
+    with db.transaction():
+        if not db.insert_event_if_absent(event.id):
+            return {"duplicate": True}
+        db.add_credit(event.customer_id, event.credit_amount)
+    return {"credited": True}
""", details="insert_event_if_absent uses INSERT ON CONFLICT DO NOTHING on a unique event ID. It and add_credit share this transaction. Customer IDs map to the correct account."),
    _pr("sample-25", "Surface carrier errors to API callers", """
diff --git a/carrier_labels.py b/carrier_labels.py
@@ -0,0 +1,5 @@
+def create_label(request):
+    try:
+        return carrier.create_label(request)
+    except CarrierUnavailable as exc:
+        return JSONResponse({"detail": str(exc)}, status_code=503)
""", details="CarrierUnavailable is a narrow documented exception with no credentials or user data. carrier.create_label has a configured timeout. This is a new public API endpoint."),
    _pr("sample-26", "Return a stable carrier error response", """
diff --git a/carrier_quotes.py b/carrier_quotes.py
@@ -0,0 +1,5 @@
+def get_quote(request):
+    try:
+        return carrier.quote(request)
+    except CarrierUnavailable:
+        return JSONResponse({"error_code": "carrier.unavailable", "message": "Try again later."}, status_code=503)
""", details="CarrierUnavailable is a documented exception. carrier.quote has a configured timeout. This is a new public API endpoint."),
]


def _held_out(identifier: str, title: str, diff: str, decision: str, tags: list[str], *, critical: list[str] | None = None, change_type: str = "feature", details: str = "") -> dict[str, Any]:
    example = _pr(identifier, title, diff, split="eval", change_type=change_type, details=details)
    example["gold"] = {"decision": decision, "issue_tags": tags, "critical_issue_tags": critical or []}
    return example


HELD_OUT_PRS: list[dict[str, Any]] = [
    _held_out("held-out-01", "Suppress notification delivery errors", """
diff --git a/notify.py b/notify.py
@@ -2,1 +2,4 @@
-    return mailer.deliver(message)
+    try:
+        return mailer.deliver(message)
+    except Exception:
+        return {"delivered": True}
""", "REJECT", ["broad_exception", "missing_regression_test"], critical=["broad_exception"], change_type="bugfix", details="Complete bug-fix PR with no added tests. Delivery errors must remain visible to callers."),
    _held_out("held-out-02", "Return an explicit expired-token error", """
diff --git a/token_refresh.py b/token_refresh.py
@@ -2,1 +2,4 @@
-    return tokens.refresh(token)
+    try:
+        return tokens.refresh(token)
+    except ExpiredToken:
+        raise HTTPException(401, "Token expired")
diff --git a/tests/test_token_refresh.py b/tests/test_token_refresh.py
@@ -0,0 +1,3 @@
+def test_expired_token_gets_401(client, expired_token):
+    result = client.post("/refresh", json={"token": expired_token})
+    assert result.status_code == 401
""", "APPROVE", [], change_type="bugfix", details="ExpiredToken is the documented domain exception. Fixtures exercise the real refresh endpoint."),
    _held_out("held-out-03", "Show shipment search results", """
diff --git a/shipments.py b/shipments.py
@@ -0,0 +1,3 @@
+def find_shipments(db, tracking):
+    statement = "SELECT status FROM shipments WHERE tracking = '%s'" % tracking
+    return db.execute(statement).fetchall()
""", "REJECT", ["sql_injection"], critical=["sql_injection"], details="Tracking is an untrusted query parameter. This publicly searchable table contains public delivery status only."),
    _held_out("held-out-04", "Add safe shipment lookup", """
diff --git a/shipment_lookup.py b/shipment_lookup.py
@@ -0,0 +1,4 @@
+def shipment_status(db, tracking_code):
+    row = db.execute("SELECT status FROM parcels WHERE tracking = ?", (tracking_code,)).fetchone()
+    return row["status"] if row else None
+
""", "APPROVE", [], details="The sqlite3 row factory provides mapping access; only public tracking status is returned."),
    _held_out("held-out-05", "Read cloud storage metadata", """
diff --git a/object_metadata.py b/object_metadata.py
@@ -0,0 +1,5 @@
+@router.get("/public-object-metadata")
+async def object_metadata():
+    response = requests.get(PUBLIC_METADATA_URL)
+    response.raise_for_status()
+    return response.json()
""", "REJECT", ["missing_timeout", "event_loop_blocking"], details="This is an ASGI async handler. requests is synchronous. PUBLIC_METADATA_URL is trusted and its contents are public."),
    _held_out("held-out-06", "Load public metadata without blocking", """
diff --git a/cloud_metadata.py b/cloud_metadata.py
@@ -0,0 +1,5 @@
+@router.get("/cloud-metadata")
+async def cloud_metadata():
+    response = await shared_http.get(CLOUD_INFO_URL, timeout=7)
+    response.raise_for_status()
+    return response.json()
""", "APPROVE", [], details="shared_http is the app's lifespan-managed httpx.AsyncClient. The URL and returned public metadata are trusted."),
    _held_out("held-out-07", "Read saved workspace exports", """
diff --git a/workspace_exports.py b/workspace_exports.py
@@ -0,0 +1,4 @@
+def export_download(workspace_id, name, user):
+    workspace = db.get_workspace(workspace_id)
+    path = EXPORT_BASE / workspace.folder / name
+    return FileResponse(path)
""", "REJECT", ["missing_authorization", "path_traversal"], critical=["missing_authorization", "path_traversal"], details="Authenticated users pass any workspace ID and file name. get_workspace does not check membership. No middleware performs authorization; name may contain ../."),
    _held_out("held-out-08", "Serve exports for workspace members", """
diff --git a/member_exports.py b/member_exports.py
@@ -0,0 +1,9 @@
+def member_export(workspace_id, filename, user):
+    workspace = db.workspace_for_member(workspace_id, user.id)
+    if workspace is None:
+        raise HTTPException(404, "Not found")
+    root = (EXPORT_ROOT / workspace.folder).resolve()
+    target = (root / filename).resolve()
+    if not target.is_relative_to(root) or not target.is_file():
+        raise HTTPException(404, "Not found")
+    return FileResponse(target)
""", "APPROVE", [], details="workspace.folder is trusted configuration. The export directory is read-only to users and contains no user-writable symlinks."),
    _held_out("held-out-09", "Fix leaked handles in audit upload", """
diff --git a/audit_upload.py b/audit_upload.py
@@ -1,4 +1,4 @@
 def upload_audit(path):
-    stream = open(path, "rb")
-    return uploader.send(stream)
+    stream = open(path, "rb")
+    return uploader.send(stream, timeout=10)
""", "REJECT", ["resource_leak", "missing_regression_test"], change_type="bugfix", details="Complete bug-fix PR. uploader.send reads but does not close the stream and can raise. path is trusted. No tests are added."),
    _held_out("held-out-10", "Close audit files on upload failure", """
diff --git a/audit_archive.py b/audit_archive.py
@@ -1,3 +1,3 @@
 def archive_audit(path):
-    return uploader.send(open(path, "rb"), timeout=10)
+    with open(path, "rb") as stream:
+        return uploader.send(stream, timeout=10)
diff --git a/tests/test_audit_archive.py b/tests/test_audit_archive.py
@@ -0,0 +1,5 @@
+def test_archive_closes_file_on_failure(monkeypatch, tracked_file):
+    monkeypatch.setattr(uploader, "send", fail_upload)
+    with pytest.raises(UploadError):
+        archive_audit(tracked_file.path)
+    assert tracked_file.last_opened.closed
""", "APPROVE", [], change_type="bugfix", details="tracked_file and fail_upload are existing fixtures. The fixture tracks the real opened stream; fail_upload raises UploadError. path is trusted."),
    _held_out("held-out-11", "Expose inventory synchronization status", """
diff --git a/sync_api.py b/sync_api.py
@@ -0,0 +1,6 @@
+def synchronize_catalog(request):
+    try:
+        result = inventory.sync(request.catalog_id)
+        return {"synchronized": result.count}
+    except InventorySyncError as error:
+        return JSONResponse({"detail": str(error)}, status_code=502)
""", "REJECT", ["error_contract_violation"], details="InventorySyncError is a specific documented exception whose message contains no private data. inventory.sync has a configured timeout. Authorization is handled by the existing request dependency. This is a new public API endpoint."),
    _held_out("held-out-12", "Report temporary inventory provider failure", """
diff --git a/inventory_refresh.py b/inventory_refresh.py
@@ -0,0 +1,5 @@
+def refresh_availability(request):
+    try:
+        return inventory.refresh(request.warehouse_id)
+    except InventorySyncError:
+        return JSONResponse({"error_code": "inventory.unavailable", "message": "Inventory is temporarily unavailable."}, status_code=502)
""", "APPROVE", [], details="InventorySyncError is a specific documented exception. inventory.refresh has a configured timeout. Existing middleware checks warehouse membership. This is a new public API endpoint."),
]


def sample_experiences() -> list[dict[str, Any]]:
    """Return training samples only, safe for the public sample picker."""
    return deepcopy(SAMPLE_PRS)


def held_out_experiences() -> list[dict[str, Any]]:
    """Return held-out data including labels for backend evaluation only."""
    return deepcopy(HELD_OUT_PRS)
