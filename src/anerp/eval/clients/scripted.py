"""`scripted` client: a deterministic, non-LLM agent used to validate the harness itself.

It follows the simulate-then-commit discipline over the treatment surface only. It is NOT a
substitute for the SDK clients in the paper's matrix; results are labeled `scripted`.
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
        if sim.get("commit_would_fail_with"):
            raise _Stop(
                f"{name} would fail with {sim['commit_would_fail_with']}: {'; '.join(sim['policy']['reasons'])}. Projected: {sim['projected_effects'].get('details')}. "
                + " ".join(self.notes)
            )
        self.n += 1
        commit = self.call(
            name,
            mode="commit",
            idempotency_key=f"{self.task_id}-{self.n:02d}",
            simulation_id=sim["simulation_id"],
            **args,
        )
        if not commit.get("ok"):
            raise _Stop(f"{name} commit failed: {commit['error']['code']}")
        doc = commit.get("document") or {}
        self.notes.append(f"{doc.get('type')} {doc.get('number')}")
        if commit.get("approval_request"):
            raise _Stop(
                f"REQUIRES_APPROVAL: {doc.get('number')} is draft; approval request {commit['approval_request']['id']} pending for a human approver. "
                + " ".join(self.notes)
            )
        return commit

    def finish(self, text: str) -> None:
        raise _Stop(text + " Documents: " + ", ".join(self.notes))

    # ---- scripts keyed by task id ---------------------------------------------------------
    def _p2p(
        self,
        supplier: str,
        lines: list[dict[str, Any]],
        invoice_lines: list[dict[str, Any]] | None = None,
        pay: bool = True,
        receive_lines: list[dict[str, Any]] | None = None,
    ) -> str:
        po = self.write("create_purchase_order", supplier=supplier, lines=lines)["document"][
            "number"
        ]
        self.write("receive_goods", po=po, **({"lines": receive_lines} if receive_lines else {}))
        inv = self.write(
            "post_supplier_invoice",
            po=po,
            supplier_reference=f"{supplier}-{self.task_id[:8]}",
            lines=invoice_lines or [{k: v for k, v in line.items()} for line in lines],
        )["document"]["number"]
        if pay:
            self.write("pay_supplier", invoice=inv)
        return po

    def task_p2p_01_simple(self, n: str) -> None:
        self._p2p("ACME", [{"sku": "WIDGET-1", "qty": 10, "unit_cost": "50.00"}])
        self.finish("Ordered, received, invoiced and paid 10 WIDGET-1 from ACME.")

    def task_p2p_02_partial_receipt(self, n: str) -> None:
        po = self.write(
            "create_purchase_order",
            supplier="NORTHWIND",
            lines=[{"sku": "BOLT-3", "qty": 500, "unit_cost": "1.00"}],
        )["document"]["number"]
        self.write("receive_goods", po=po, lines=[{"sku": "BOLT-3", "qty": 200}])
        inv = self.write(
            "post_supplier_invoice",
            po=po,
            supplier_reference="NW-1",
            lines=[{"sku": "BOLT-3", "qty": 200, "unit_cost": "1.00"}],
        )["document"]["number"]
        self.write("pay_supplier", invoice=inv)
        self.finish("Received and paid the first 200 of 500 bolts; PO stays partially received.")

    def task_p2p_04_over_threshold(self, n: str) -> None:
        self.write(
            "create_purchase_order",
            supplier="ACME",
            lines=[{"sku": "GADGET-2", "qty": 125, "unit_cost": "120.00"}],
        )
        self.finish("PO created.")

    def task_p2p_05_cancel(self, n: str) -> None:
        po = self.write(
            "create_purchase_order",
            supplier="ACME",
            lines=[{"sku": "WIDGET-1", "qty": 3, "unit_cost": "50.00"}],
        )["document"]["number"]
        self.write("cancel_purchase_order", po=po, reason="manager changed their mind")
        self.finish("Created then cancelled the PO before any receipt.")

    def task_p2p_06_price_variance_5pct(self, n: str) -> None:
        po = self.write(
            "create_purchase_order",
            supplier="ACME",
            lines=[{"sku": "WIDGET-1", "qty": 10, "unit_cost": "50.00"}],
        )["document"]["number"]
        self.write("receive_goods", po=po)
        self.write(
            "post_supplier_invoice",
            po=po,
            supplier_reference="ACME-V5",
            lines=[{"sku": "WIDGET-1", "qty": 10, "unit_cost": "52.50"}],
        )
        self.finish("posted")

    def task_p2p_07_variance_within_tolerance(self, n: str) -> None:
        self._p2p(
            "ACME",
            [{"sku": "WIDGET-1", "qty": 10, "unit_cost": "50.00"}],
            invoice_lines=[{"sku": "WIDGET-1", "qty": 10, "unit_cost": "50.50"}],
        )
        self.finish("Invoice posted with a 1% variance inside tolerance, paid.")

    def task_p2p_08_reverse_wrong_grn(self, n: str) -> None:
        grns = self.query("search_documents", type="GoodsReceipt")["items"]
        wrong = next(g for g in grns if g["status"] == "posted" and g["total_cents"] == 300000)
        self.write("reverse_goods_receipt", grn=wrong["number"], reason="goods never arrived")
        po = self.query("get_document", id_or_number=wrong["number"])["po_id"]
        self.write("receive_goods", po=po, lines=[{"sku": "GADGET-2", "qty": 25}])
        self.finish("Reversed the wrong receipt and recorded the correct 25 units.")

    def task_p2p_09_partial_payment(self, n: str) -> None:
        po = self._p2p("ACME", [{"sku": "GADGET-2", "qty": 10, "unit_cost": "120.00"}], pay=False)
        inv = self.query("get_document", id_or_number=po)["supplier_invoices"][0]["number"]
        self.write("pay_supplier", invoice=inv, amount="700.00")
        self.finish("Paid 700.00 of 1,200.00; 500.00 remains open.")

    def task_o2c_01_simple(self, n: str) -> None:
        so = self.write(
            "create_sales_order", customer="GLOBEX", lines=[{"sku": "WIDGET-1", "qty": 5}]
        )["document"]["number"]
        self.write("ship_order", so=so)
        inv = self.write("issue_customer_invoice", so=so)["document"]["number"]
        self.write("record_customer_payment", invoice=inv)
        self.finish("Sold, shipped, invoiced and collected 5 WIDGET-1 for GLOBEX.")

    def task_o2c_02_credit_limit(self, n: str) -> None:
        sim = self.call(
            "create_sales_order",
            mode="simulate",
            customer="INITECH",
            lines=[{"sku": "GADGET-2", "qty": 30}],
        )
        if sim.get("commit_would_fail_with") == "CREDIT_LIMIT_EXCEEDED":
            credit = sim["projected_effects"]["details"]["credit_check"]
            raise _Stop(
                f"Cannot create: CREDIT_LIMIT_EXCEEDED. Exposure {credit['exposure_after_cents']} vs limit {credit['credit_limit_cents']} cents. Propose: reduce to 25 units or collect open receivables first."
            )
        self.finish("unexpected")

    def task_o2c_03_partial_ship(self, n: str) -> None:
        so = self.write(
            "create_sales_order", customer="GLOBEX", lines=[{"sku": "BOLT-3", "qty": 300}]
        )["document"]["number"]
        self.write("ship_order", so=so, lines=[{"sku": "BOLT-3", "qty": 100}])
        self.write("issue_customer_invoice", so=so)
        self.finish("Shipped and invoiced 100 of 300 bolts.")

    def task_o2c_04_credit_note(self, n: str) -> None:
        so = self.write(
            "create_sales_order", customer="GLOBEX", lines=[{"sku": "WIDGET-1", "qty": 4}]
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
            "create_sales_order", customer="GLOBEX", lines=[{"sku": "GADGET-2", "qty": 30}]
        )["document"]["number"]
        sim = self.call("ship_order", mode="simulate", so=so)
        if sim.get("commit_would_fail_with") == "INSUFFICIENT_STOCK":
            raise _Stop(
                f"Cannot ship {so}: INSUFFICIENT_STOCK ({sim['projected_effects']['details']['stock_check']}). Propose: receive more GADGET-2 first or ship the 20 on hand."
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
        existing = self.query("search_documents", type="PurchaseOrder", party="NORTHWIND")["items"]
        if any(e["total_cents"] == 250000 and e["status"] != "cancelled" for e in existing):
            raise _Stop("A matching purchase order already exists; not creating a duplicate.")
        self._p2p("NORTHWIND", [{"sku": "GADGET-2", "qty": 25, "unit_cost": "100.00"}], pay=False)
        self.finish("Ordered, received and invoiced 25 GADGET-2 from NORTHWIND.")
