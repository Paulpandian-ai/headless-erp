"""`scripted` client: a deterministic, non-LLM agent used to validate the harness itself.

It follows the simulate-then-commit discipline over the treatment surface only, is state-driven
(the harness may call it again after a human accepted goods), and stops with a hand-off message
whenever a human is needed. It is NOT a substitute for the SDK clients in the paper's matrix.
"""

from __future__ import annotations

import re
import time
from typing import Any

from anerp.eval.clients.base import RunTrace, ToolCallRecord
from anerp.eval.surface import ToolSurface


class ScriptedClient:
    name = "scripted"

    def available(self) -> bool:
        return True

    def run(
        self, narrative: str, surface: ToolSurface, *, max_steps: int, task_id: str
    ) -> RunTrace:
        trace = RunTrace()
        if surface.name != "treatment":
            trace.final_text = "scripted client only understands the agent-native surface"
            trace.error = "unsupported_surface"
            return trace
        runner = _Runner(surface, trace, task_id)
        try:
            handler = getattr(
                runner, "task_" + re.sub(r"[^a-z0-9_]", "_", task_id.split("__")[0]), None
            )
            if handler is None:
                trace.final_text = f"no script for task {task_id}"
                trace.error = "no_script"
            else:
                handler(narrative)
        except _Stop as stop:
            trace.final_text = str(stop)
        return trace


class _Stop(Exception):
    pass


class _Runner:
    def __init__(self, surface: ToolSurface, trace: RunTrace, task_id: str) -> None:
        self.surface = surface
        self.trace = trace
        self.task_id = task_id
        self.n = 0
        self.notes: list[str] = []

    def call(self, name: str, **args: Any) -> dict[str, Any]:
        t0 = time.perf_counter()
        out = self.surface.call(name, args)
        self.trace.tool_calls.append(
            ToolCallRecord(
                name,
                args,
                out.get("ok"),
                (out.get("error") or {}).get("code"),
                args.get("mode"),
                round((time.perf_counter() - t0) * 1000, 1),
            )
        )
        self.trace.steps += 1
        return out

    def query(self, name: str, **args: Any) -> dict[str, Any]:
        return self.call(name, **args).get("result", {})

    def write(self, name: str, **args: Any) -> dict[str, Any]:
        sim = self.call(name, mode="simulate", **args)
        if not sim.get("ok"):
            raise _Stop(
                f"{name} rejected: {sim['error']['code']} - {sim['error']['message']}. "
                + " ".join(self.notes)
            )
        if (
            sim.get("commit_would_fail_with")
            and sim["commit_would_fail_with"] != "REQUIRES_APPROVAL"
        ):
            raise _Stop(
                f"{name} would fail with {sim['commit_would_fail_with']}: {'; '.join(sim['policy']['reasons'])}. Projected: {sim['projected_effects'].get('details')}. "
                + " ".join(self.notes)
            )
        self.n += 1
        key = f"{self.task_id}-{name}-{self.n:02d}"
        commit = self.call(
            name, mode="commit", idempotency_key=key, simulation_id=sim["simulation_id"], **args
        )
        if not commit.get("ok"):
            err = commit["error"]
            if err["code"] == "REQUIRES_APPROVAL":
                d = err.get("details", {})
                raise _Stop(
                    f"REQUIRES_APPROVAL ({d.get('approval_kind')}): request {d.get('approval_request_id')} is pending for a human. {d.get('next_step', '')} "
                    + " ".join(self.notes)
                )
            if err["code"] == "MATCH_VARIANCE_EXCEEDED":
                d = err.get("details", {})
                raise _Stop(
                    f"MATCH_VARIANCE_EXCEEDED: {err['message']}. Not posted; invoice_variance request {d.get('approval_request_id')} parked for a human. "
                    + " ".join(self.notes)
                )
            raise _Stop(f"{name} commit failed: {err['code']}: {err['message']}")
        doc = commit.get("document") or {}
        self.notes.append(f"{doc.get('type')} {doc.get('number')}")
        if commit.get("approval_request"):
            raise _Stop(
                f"REQUIRES_APPROVAL: {doc.get('number')} is draft; approval request {commit['approval_request']['id']} pending for a human approver. "
                + " ".join(self.notes)
            )
        return commit

    def finish(self, text: str) -> None:
        raise _Stop(text + (" Documents: " + ", ".join(self.notes) if self.notes else ""))

    # ---- state-driven procure-to-pay ------------------------------------------------------
    def _find_po(self, supplier: str, total_cents: int) -> dict[str, Any] | None:
        for po in self.query("search_documents", type="PurchaseOrder", party=supplier)["items"]:
            if po["total_cents"] == total_cents and po["status"] != "cancelled":
                return po
        return None

    def _p2p(
        self,
        supplier: str,
        lines: list[dict[str, Any]],
        *,
        reference: str,
        invoice_costs: dict[str, str] | None = None,
        pay: bool = True,
        pay_amount: str | None = None,
    ) -> str:
        total = sum(int(round(float(line["unit_cost"]) * 100)) * int(line["qty"]) for line in lines)
        existing = self._find_po(supplier, total)
        if existing is None:
            po_number = self.write("create_purchase_order", supplier=supplier, lines=lines)[
                "document"
            ]["number"]
        else:
            po_number = existing["number"]
            self.notes.append(f"PurchaseOrder {po_number} (existing)")
        po = self.query("get_document", id_or_number=po_number)
        pending = [
            a
            for a in po.get("approval_requests", [])
            if a["status"] == "pending" and a["kind"] == "goods_acceptance"
        ]
        if pending:
            raise _Stop(
                f"Delivery for {po_number} awaits the warehouse count (request {pending[0]['id']})."
            )
        if po["status"] == "approved" and not any(line["received_qty"] for line in po["lines"]):
            self.write(
                "receive_goods", po=po_number
            )  # agent commit parks a goods_acceptance request (stops)
        invoices = [i for i in po.get("supplier_invoices", []) if i["status"] != "reversed"]
        if not invoices:
            costs = invoice_costs or {}
            inv_lines = [
                {
                    "sku": line["sku"],
                    "qty": line["received_qty"] - line["invoiced_qty"],
                    "unit_cost": costs.get(line["sku"], f"{line['unit_cost_cents'] / 100:.2f}"),
                }
                for line in po["lines"]
                if line["received_qty"] > line["invoiced_qty"]
            ]
            if not inv_lines:
                raise _Stop(f"Nothing accepted yet on {po_number}; waiting for the warehouse.")
            inv_number = self.write(
                "post_supplier_invoice", po=po_number, supplier_reference=reference, lines=inv_lines
            )["document"]["number"]
        else:
            inv_number = invoices[0]["number"]
        if pay:
            inv = self.query("get_document", id_or_number=inv_number)
            if inv.get("open_item", {}).get("remaining_cents", 0) > 0:
                self.write(
                    "pay_supplier",
                    invoice=inv_number,
                    **({"amount": pay_amount} if pay_amount else {}),
                )
        return po_number

    def task_p2p_01_simple(self, n: str) -> None:
        self._p2p(
            "ACME", [{"sku": "VALVE-2IN", "qty": 10, "unit_cost": "50.00"}], reference="ACME-1001"
        )
        self.finish(
            "Ordered, received (accepted by the warehouse), invoiced and paid 10 VALVE-2IN from ACME."
        )

    def task_p2p_02_partial_receipt(self, n: str) -> None:
        self._p2p(
            "BOLT", [{"sku": "FLANGE-4", "qty": 200, "unit_cost": "15.00"}], reference="BOLT-1"
        )
        self.finish("Invoiced and paid the accepted quantity; the PO stays partially received.")

    def task_p2p_04_over_threshold(self, n: str) -> None:
        self.write(
            "create_purchase_order",
            supplier="ACME",
            lines=[{"sku": "PUMP-SM", "qty": 30, "unit_cost": "400.00"}],
        )
        self.finish("PO created.")

    def task_p2p_05_cancel(self, n: str) -> None:
        po = self.write(
            "create_purchase_order",
            supplier="ACME",
            lines=[{"sku": "VALVE-2IN", "qty": 3, "unit_cost": "50.00"}],
        )["document"]["number"]
        self.write("cancel_purchase_order", po=po, reason="manager changed their mind")
        self.finish("Created then cancelled the PO before any receipt.")

    def task_p2p_06_price_variance_5pct(self, n: str) -> None:
        self._p2p(
            "ACME",
            [{"sku": "VALVE-2IN", "qty": 10, "unit_cost": "50.00"}],
            reference="ACME-V5",
            invoice_costs={"VALVE-2IN": "52.50"},
        )
        self.finish("posted")

    def task_p2p_07_variance_within_tolerance(self, n: str) -> None:
        self._p2p(
            "ACME",
            [{"sku": "VALVE-2IN", "qty": 10, "unit_cost": "50.00"}],
            reference="ACME-V1",
            invoice_costs={"VALVE-2IN": "50.50"},
        )
        self.finish("Invoice posted with a 1% variance inside tolerance, paid.")

    def task_p2p_08_reverse_wrong_grn(self, n: str) -> None:
        grns = [
            g
            for g in self.query("search_documents", type="GoodsReceipt")["items"]
            if g["status"] == "posted" and g["total_cents"] == 62500
        ]
        if grns:
            self.write("reverse_goods_receipt", grn=grns[0]["number"], reason="goods never arrived")
            po_id = self.query("get_document", id_or_number=grns[0]["number"])["po_id"]
            self.write(
                "receive_goods", po=po_id, lines=[{"sku": "HOSE-10M", "qty": 25}]
            )  # parks for the warehouse count
        self.finish(
            "Reversed the wrong receipt; the real delivery was counted and accepted by the warehouse."
        )

    def task_p2p_09_partial_payment(self, n: str) -> None:
        self._p2p(
            "ACME",
            [{"sku": "PUMP-SM", "qty": 10, "unit_cost": "400.00"}],
            reference="ACME-P9",
            pay_amount="2500.00",
        )
        self.finish("Paid 2,500.00 of 4,000.00; 1,500.00 remains open.")

    def task_o2c_01_simple(self, n: str) -> None:
        so = self.write(
            "create_sales_order", customer="NORTH", lines=[{"sku": "VALVE-2IN", "qty": 5}]
        )["document"]["number"]
        self.write("ship_order", so=so)
        inv = self.write("issue_customer_invoice", so=so)["document"]["number"]
        self.write("record_customer_payment", invoice=inv)
        self.finish("Sold, shipped, invoiced and collected 5 VALVE-2IN for NORTH.")

    def task_o2c_02_credit_limit(self, n: str) -> None:
        sim = self.call(
            "create_sales_order",
            mode="simulate",
            customer="HARB",
            lines=[{"sku": "PUMP-SM", "qty": 10}],
        )
        if sim.get("commit_would_fail_with") == "CREDIT_LIMIT_EXCEEDED":
            credit = sim["projected_effects"]["details"]["credit_check"]
            raise _Stop(
                f"Cannot create: CREDIT_LIMIT_EXCEEDED. Exposure {credit['exposure_after_cents']} vs limit {credit['credit_limit_cents']} cents. Propose: reduce to 7 units or collect open receivables first."
            )
        self.finish("unexpected")

    def task_o2c_03_partial_ship(self, n: str) -> None:
        so = self.write(
            "create_sales_order", customer="NORTH", lines=[{"sku": "HOSE-10M", "qty": 60}]
        )["document"]["number"]
        self.write("ship_order", so=so, lines=[{"sku": "HOSE-10M", "qty": 40}])
        self.write("issue_customer_invoice", so=so)
        self.finish("Shipped and invoiced 40 of 60 hoses.")

    def task_o2c_04_credit_note(self, n: str) -> None:
        so = self.write(
            "create_sales_order", customer="NORTH", lines=[{"sku": "VALVE-2IN", "qty": 4}]
        )["document"]["number"]
        self.write("ship_order", so=so)
        inv = self.write("issue_customer_invoice", so=so)["document"]["number"]
        self.write(
            "issue_credit_note", invoice=inv, amount="80.00", reason="one unit damaged in transit"
        )
        self.write("record_customer_payment", invoice=inv)
        self.finish("Invoiced 320.00, credited 80.00, collected 240.00.")

    def task_o2c_05_out_of_stock(self, n: str) -> None:
        so = self.write(
            "create_sales_order", customer="NORTH", lines=[{"sku": "PUMP-SM", "qty": 3}]
        )["document"]["number"]
        sim = self.call("ship_order", mode="simulate", so=so)
        if sim.get("commit_would_fail_with") == "INSUFFICIENT_STOCK":
            raise _Stop(
                f"Cannot ship {so}: INSUFFICIENT_STOCK ({sim['projected_effects']['details']['stock_check']}). Propose: receive PUMP-SM from a supplier first, nothing is on hand."
            )
        self.finish("unexpected")

    def task_o2c_06_payment_reversal(self, n: str) -> None:
        pays = self.query("search_documents", type="CustomerPayment")["items"]
        bounced = next(p for p in pays if p["status"] == "posted")
        self.write("reverse_customer_payment", payment=bounced["number"], reason="cheque bounced")
        self.finish("Reversed the bounced receipt; the invoice is open again.")

    def task_gl_01_manual_je(self, n: str) -> None:
        self.write(
            "post_journal_entry",
            memo="Office rent accrual",
            lines=[
                {"account": "5100", "debit": "1200.00"},
                {"account": "2000", "credit": "1200.00"},
            ],
        )
        self.finish("Posted the accrual.")

    def task_gl_02_reverse_je(self, n: str) -> None:
        jes = self.query("search_documents", type="JournalEntry")["items"]
        target = next(j for j in jes if j["status"] == "posted" and j["total_cents"] == 999900)
        self.write("reverse_journal_entry", je=target["number"], reason="posted twice")
        self.finish("Reversed the duplicate entry.")

    def task_gl_03_closed_period(self, n: str) -> None:
        m = re.search(r"dated (\d{4}-\d{2}-\d{2})", n)
        date = m.group(1) if m else None
        sim = self.call(
            "post_journal_entry",
            mode="simulate",
            posting_date=date,
            memo="Late consulting fee",
            lines=[{"account": "5100", "debit": "400.00"}, {"account": "1000", "credit": "400.00"}],
        )
        if sim.get("commit_would_fail_with") == "PERIOD_CLOSED":
            raise _Stop(
                f"Refused: PERIOD_CLOSED for {date}. The period is closed; either reopen it with a reason or re-date the entry into the open period. Nothing was posted."
            )
        self.finish("unexpected")

    def task_close_01_clean(self, n: str) -> None:
        m = re.search(r"period (\d{4}-\d{2})", n)
        period = m.group(1) if m else ""
        self.write("close_period", period=period)
        self.finish(f"Closed {period}.")

    def task_close_02_blocked(self, n: str) -> None:
        m = re.search(r"period (\d{4}-\d{2})", n)
        period = m.group(1) if m else ""
        check = self.query("get_period", period_code=period)["close_readiness"]
        if not check["ready"]:
            raise _Stop(
                f"Cannot close {period}: {'; '.join(check['blockers'])}. Resolve the blocked supplier invoice(s) {check['blocked_supplier_invoices']} first."
            )
        self.finish("unexpected")

    def task_dup_01_retry_storm(self, n: str) -> None:
        self._p2p(
            "BOLT",
            [{"sku": "HOSE-10M", "qty": 20, "unit_cost": "25.00"}],
            reference="BOLT-20",
            pay=False,
        )
        self.finish("Ordered, received (accepted) and invoiced 20 HOSE-10M from BOLT.")
