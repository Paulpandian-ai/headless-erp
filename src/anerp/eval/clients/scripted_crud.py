"""The `scripted` oracle over the control (CRUD) surface.

Best case for the baseline: an agent that knows the schema, the posting rules and the company's
policies perfectly and does every piece of bookkeeping itself with `list_rows` / `insert_row` /
`update_row` - document numbers, journal entries and lines, open items, stock, line quantities,
statuses. It is the same twenty tasks as the treatment script, so tool-call counts and latencies
are comparable per task, but it is NOT an LLM agent: it shows what the CRUD surface costs even
when nothing goes wrong.

One thing the control surface cannot express is left as it is: the CRUD tools have no approval
requests, so `p2p_04` cannot park a draft PO for a human. The warehouse works the same way on
both arms: the script stops after ordering, the harness's human step reports the count as a
status line (`runner.human_step`), and on the next round the script records the receipt at that
count - on this surface nothing posts it for you.
"""

from __future__ import annotations

import json
import re
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from anerp.eval.clients.base import RunTrace, ToolCallRecord
from anerp.eval.surface import ToolSurface

# The company's rules, as the oracle knows them (policies/default.yaml). On the CRUD surface
# nothing enforces them; the script applies them itself so its behaviour matches the kernel's.
PO_APPROVAL_THRESHOLD_CENTS = 1_000_000
PRICE_TOLERANCE_PCT = 2.0
PRICE_TOLERANCE_ABS_CENTS = 5000

CASH, AR, INVENTORY, GRIR, AP, REVENUE, COGS, OPEX, PPV = (
    "1000",
    "1200",
    "1300",
    "1400",
    "2000",
    "4000",
    "5000",
    "5100",
    "5200",
)
NUMBER_WIDTH = 6
PREFIX = {
    "journal_entry": "JE",
    "purchase_order": "PO",
    "goods_receipt": "GRN",
    "supplier_invoice": "SINV",
    "supplier_payment": "PAY",
    "sales_order": "SO",
    "shipment": "SHP",
    "customer_invoice": "CINV",
    "customer_payment": "RCPT",
    "credit_note": "CN",
}


class _Stop(Exception):
    pass


def _json(value: Any) -> Any:
    """JSON columns read through the raw CRUD SELECT are text on SQLite, parsed on Postgres."""
    return json.loads(value) if isinstance(value, str) else value


def _cents(amount: str | float | int) -> int:
    return int(round(float(amount) * 100))


def _fmt(cents: int) -> str:
    return f"{cents / 100:,.2f}"


class CrudRunner:
    """One task run over the CRUD surface; every helper is a small sequence of CRUD calls."""

    def __init__(self, surface: ToolSurface, trace: RunTrace, task_id: str) -> None:
        self.surface = surface
        self.trace = trace
        self.task_id = task_id
        self.now = datetime.now(UTC).replace(microsecond=0)
        self.today = self.now.date().isoformat()
        self.notes: list[str] = []
        self._accounts: dict[str, str] | None = None

    # ---- CRUD primitives -------------------------------------------------------------------
    def call(self, name: str, **args: Any) -> dict[str, Any]:
        t0 = time.perf_counter()
        out = self.surface.call(name, args)
        self.trace.tool_calls.append(
            ToolCallRecord(
                name,
                args,
                out.get("ok"),
                (out.get("error") or {}).get("code"),
                None,
                round((time.perf_counter() - t0) * 1000, 1),
            )
        )
        self.trace.steps += 1
        if not out.get("ok"):
            raise _Stop(f"{name} failed: {out.get('error', {}).get('message')}")
        return out

    def rows(self, table: str, **filters: Any) -> list[dict[str, Any]]:
        return list(self.call("list_rows", table=table, filters=filters, limit=500)["result"])

    def one(self, table: str, **filters: Any) -> dict[str, Any]:
        found = self.rows(table, **filters)
        if not found:
            raise _Stop(f"no {table} row matches {filters}")
        return found[0]

    def insert(self, table: str, **values: Any) -> str:
        return str(self.call("insert_row", table=table, values=values)["result"]["id"])

    def update(self, table: str, id_: str, **values: Any) -> None:
        self.call("update_row", table=table, id=id_, values=values)

    # ---- lookups ---------------------------------------------------------------------------
    def account_id(self, code: str) -> str:
        if self._accounts is None:
            self._accounts = {r["code"]: r["id"] for r in self.rows("account")}
        return self._accounts[code]

    def next_number(self, table: str) -> str:
        used = [
            int(r["number"].split("-")[-1])
            for r in self.rows(table)
            if isinstance(r.get("number"), str) and r["number"].split("-")[-1].isdigit()
        ]
        return f"{PREFIX[table]}-{(max(used) + 1 if used else 1):0{NUMBER_WIDTH}d}"

    def period(self, posting_date: str) -> dict[str, Any]:
        return self.one("fiscal_period", code=posting_date[:7])

    def finish(self, text: str) -> None:
        raise _Stop(text + (" Documents: " + ", ".join(self.notes) if self.notes else ""))

    # ---- bookkeeping the kernel would do ---------------------------------------------------
    def journal(
        self,
        memo: str,
        lines: list[tuple[str, int, int, str]],
        source_type: str,
        source_id: str,
        posting_date: str | None = None,
        reversal_of: str | None = None,
    ) -> str:
        """Post a balanced entry: (account, debit, credit, description) per line."""
        posting_date = posting_date or self.today
        period = self.period(posting_date)
        if period["status"] != "open":
            raise _Stop(
                f"Refused: PERIOD_CLOSED for {posting_date}. Period {period['code']} is closed; "
                "either reopen it with a reason or re-date the entry into the open period. "
                "Nothing was posted."
            )
        assert sum(d for _, d, _, _ in lines) == sum(c for _, _, c, _ in lines)
        je_id = self.insert(
            "journal_entry",
            number=self.next_number("journal_entry"),
            period_id=period["id"],
            period_code=period["code"],
            posting_date=posting_date,
            memo=memo,
            source_type=source_type,
            source_id=source_id,
            reversal_of_id=reversal_of,
            status="posted",
            total_debit_cents=sum(d for _, d, _, _ in lines),
        )
        if source_type == "ManualJournal" and not source_id:
            self.update("journal_entry", je_id, source_id=je_id)
        for i, (code, debit, credit, desc) in enumerate(lines, start=1):
            self.insert(
                "journal_line",
                entry_id=je_id,
                line_no=i,
                account_id=self.account_id(code),
                account_code=code,
                debit_cents=debit,
                credit_cents=credit,
                description=desc,
            )
        return je_id

    def reverse_journal(
        self, je: dict[str, Any], memo: str, source_type: str, source_id: str
    ) -> str:
        lines = sorted(self.rows("journal_line", entry_id=je["id"]), key=lambda x: x["line_no"])
        new_id = self.journal(
            memo,
            [
                (
                    x["account_code"],
                    x["credit_cents"],
                    x["debit_cents"],
                    f"reversal: {x['description']}",
                )
                for x in lines
            ],
            source_type,
            source_id,
            reversal_of=je["id"],
        )
        self.update("journal_entry", je["id"], status="reversed")
        return new_id

    @staticmethod
    def _po_status(lines: list[dict[str, Any]]) -> str:
        total = sum(x["qty"] for x in lines)
        received = sum(x["received_qty"] for x in lines)
        invoiced = sum(x["invoiced_qty"] for x in lines)
        if total > 0 and invoiced >= total:
            return "invoiced"
        if total > 0 and received >= total:
            return "received"
        return "partially_received" if received > 0 else "approved"

    @staticmethod
    def _so_status(lines: list[dict[str, Any]]) -> str:
        total = sum(x["qty"] for x in lines)
        shipped = sum(x["shipped_qty"] for x in lines)
        invoiced = sum(x["invoiced_qty"] for x in lines)
        if total > 0 and invoiced >= total:
            return "invoiced"
        if total > 0 and shipped >= total:
            return "shipped"
        return "partially_shipped" if shipped > 0 else "open"

    def create_po(self, supplier_code: str, lines: list[dict[str, Any]]) -> dict[str, Any]:
        supplier = self.one("supplier", code=supplier_code)
        total = sum(_cents(x["unit_cost"]) * int(x["qty"]) for x in lines)
        needs_approval = total > PO_APPROVAL_THRESHOLD_CENTS
        number = self.next_number("purchase_order")
        po_id = self.insert(
            "purchase_order",
            number=number,
            supplier_id=supplier["id"],
            status="draft" if needs_approval else "approved",
            total_cents=total,
            created_by="agent:eval",
            approved_by=None if needs_approval else "policy:auto",
            approved_at=None if needs_approval else self.now.isoformat(),
        )
        for i, x in enumerate(lines, start=1):
            item = self.one("item", sku=x["sku"])
            self.insert(
                "purchase_order_line",
                po_id=po_id,
                line_no=i,
                item_id=item["id"],
                sku=item["sku"],
                qty=int(x["qty"]),
                unit_cost_cents=_cents(x["unit_cost"]),
            )
        self.notes.append(f"PurchaseOrder {number}")
        if needs_approval:
            raise _Stop(
                f"REQUIRES_APPROVAL: {number} ({_fmt(total)}) exceeds the {_fmt(PO_APPROVAL_THRESHOLD_CENTS)} "
                "approval threshold; left as draft for a human approver. The CRUD tools have no "
                "approval request to raise. Documents: " + ", ".join(self.notes)
            )
        return {"id": po_id, "number": number, "supplier_id": supplier["id"], "total_cents": total}

    def receive(self, po: dict[str, Any], counted: dict[str, int] | None = None) -> str:
        lines = self.rows("purchase_order_line", po_id=po["id"])
        grn_lines, journal_lines, total = [], [], 0
        for line in lines:
            outstanding = line["qty"] - line["received_qty"]
            qty = (counted or {}).get(line["sku"], outstanding)
            if qty <= 0:
                continue
            value = line["unit_cost_cents"] * qty
            total += value
            item = self.one("item", sku=line["sku"])
            self.update("item", item["id"], on_hand_qty=item["on_hand_qty"] + qty)
            self.update("purchase_order_line", line["id"], received_qty=line["received_qty"] + qty)
            line["received_qty"] += qty
            journal_lines.append(
                (
                    INVENTORY,
                    value,
                    0,
                    f"GRN {qty} x {line['sku']} @ {_fmt(line['unit_cost_cents'])}",
                )
            )
            grn_lines.append(
                {
                    "po_line_id": line["id"],
                    "sku": line["sku"],
                    "expected_qty": outstanding,
                    "qty": qty,
                    "damaged_qty": 0,
                    "short_qty": max(outstanding - qty, 0),
                    "over_qty": 0,
                    "note": "",
                    "unit_cost_cents": line["unit_cost_cents"],
                    "account": INVENTORY,
                }
            )
        number = self.next_number("goods_receipt")
        grn_id = self.insert(
            "goods_receipt",
            number=number,
            po_id=po["id"],
            received_at=self.now.isoformat(),
            lines=grn_lines,
            total_cents=total,
            status="posted",
        )
        journal_lines.append((GRIR, 0, total, f"GR/IR for PO {po['number']}"))
        je_id = self.journal(
            f"Goods receipt {number} for PO {po['number']}", journal_lines, "GoodsReceipt", grn_id
        )
        self.update("goods_receipt", grn_id, journal_entry_id=je_id)
        self.update("purchase_order", po["id"], status=self._po_status(lines))
        self.notes.append(f"GoodsReceipt {number}")
        return grn_id

    def reverse_receipt(self, grn: dict[str, Any], reason: str) -> None:
        po = self.call("get_row", table="purchase_order", id=grn["po_id"])["result"]
        lines = self.rows("purchase_order_line", po_id=po["id"])
        for gl in _json(grn["lines"]):
            line = next(x for x in lines if x["id"] == gl["po_line_id"])
            item = self.one("item", sku=gl["sku"])
            self.update("item", item["id"], on_hand_qty=item["on_hand_qty"] - gl["qty"])
            self.update(
                "purchase_order_line", line["id"], received_qty=line["received_qty"] - gl["qty"]
            )
            line["received_qty"] -= gl["qty"]
        je = self.call("get_row", table="journal_entry", id=grn["journal_entry_id"])["result"]
        self.reverse_journal(
            je, f"Reversal of {grn['number']}: {reason}", "GoodsReceipt", grn["id"]
        )
        self.update("goods_receipt", grn["id"], status="reversed")
        self.update("purchase_order", po["id"], status=self._po_status(lines))
        self.notes.append(f"GoodsReceipt {grn['number']} reversed")

    def post_supplier_invoice(
        self, po: dict[str, Any], reference: str, lines: list[dict[str, Any]]
    ) -> dict[str, Any]:
        supplier = self.call("get_row", table="supplier", id=po["supplier_id"])["result"]
        po_lines = self.rows("purchase_order_line", po_id=po["id"])
        inv_lines, po_value, inv_value, max_pct = [], 0, 0, 0.0
        for x in lines:
            line = next(pl for pl in po_lines if pl["sku"] == x["sku"])
            qty, unit = int(x["qty"]), _cents(x["unit_cost"])
            available = line["received_qty"] - line["invoiced_qty"]
            if qty > available:
                raise _Stop(
                    f"Cannot invoice {qty} x {x['sku']}: only {available} received and uninvoiced."
                )
            po_value += line["unit_cost_cents"] * qty
            inv_value += unit * qty
            pct = abs(unit - line["unit_cost_cents"]) / line["unit_cost_cents"] * 100
            max_pct = max(max_pct, pct)
            inv_lines.append(
                {
                    "sku": x["sku"],
                    "po_line_id": line["id"],
                    "invoice_qty": qty,
                    "received_qty": line["received_qty"],
                    "already_invoiced_qty": line["invoiced_qty"],
                    "available_qty": available,
                    "qty_exceeded": False,
                    "po_unit_cost_cents": line["unit_cost_cents"],
                    "invoice_unit_cost_cents": unit,
                    "unit_variance_cents": unit - line["unit_cost_cents"],
                    "variance_cents": (unit - line["unit_cost_cents"]) * qty,
                    "variance_abs_cents": abs(unit - line["unit_cost_cents"]) * qty,
                    "variance_pct": round(pct, 2),
                }
            )
        variance = inv_value - po_value
        if max_pct > PRICE_TOLERANCE_PCT or abs(variance) > PRICE_TOLERANCE_ABS_CENTS:
            raise _Stop(
                f"MATCH_VARIANCE_EXCEEDED: invoice {reference} is {_fmt(variance)} "
                f"({max_pct:.1f}%) over PO {po['number']}, beyond the {PRICE_TOLERANCE_PCT}% / "
                f"{_fmt(PRICE_TOLERANCE_ABS_CENTS)} tolerance. Not posted; a human must review the "
                "variance. " + " ".join(self.notes)
            )
        grns = [
            g["id"] for g in self.rows("goods_receipt", po_id=po["id"]) if g["status"] == "posted"
        ]
        number = self.next_number("supplier_invoice")
        inv_id = self.insert(
            "supplier_invoice",
            number=number,
            supplier_id=supplier["id"],
            po_id=po["id"],
            grn_ids=grns,
            supplier_reference=reference,
            lines=inv_lines,
            total_cents=inv_value,
            variance_cents=variance,
            match_status="variance_within_tolerance" if variance else "matched",
            posting_date=self.today,
            status="posted",
        )
        journal_lines = [(GRIR, po_value, 0, f"clear GR/IR for PO {po['number']}")]
        if variance > 0:
            journal_lines.append((PPV, variance, 0, "purchase price variance"))
        elif variance < 0:
            journal_lines.append((PPV, 0, -variance, "purchase price variance (favourable)"))
        journal_lines.append((AP, 0, inv_value, f"AP {supplier['code']} {reference}"))
        je_id = self.journal(
            f"Supplier invoice {number} ({supplier['code']} {reference})",
            journal_lines,
            "SupplierInvoice",
            inv_id,
        )
        due = (self.now.date() + timedelta(days=int(supplier["payment_terms_days"]))).isoformat()
        oi_id = self.insert(
            "open_item",
            kind="ap",
            party_id=supplier["id"],
            source_doc_type="SupplierInvoice",
            source_doc_id=inv_id,
            source_doc_number=number,
            amount_cents=inv_value,
            remaining_cents=inv_value,
            due_date=due,
            status="open",
        )
        self.update("supplier_invoice", inv_id, journal_entry_id=je_id, open_item_id=oi_id)
        for il in inv_lines:
            line = next(pl for pl in po_lines if pl["id"] == il["po_line_id"])
            line["invoiced_qty"] += il["invoice_qty"]
            self.update("purchase_order_line", line["id"], invoiced_qty=line["invoiced_qty"])
        self.update("purchase_order", po["id"], status=self._po_status(po_lines))
        self.notes.append(f"SupplierInvoice {number}")
        return {"id": inv_id, "number": number, "open_item_id": oi_id, "total_cents": inv_value}

    def pay_supplier(self, inv: dict[str, Any], amount: str | None = None) -> None:
        open_item = self.call("get_row", table="open_item", id=inv["open_item_id"])["result"]
        supplier = self.call("get_row", table="supplier", id=open_item["party_id"])["result"]
        cents = _cents(amount) if amount else open_item["remaining_cents"]
        number = self.next_number("supplier_payment")
        pay_id = self.insert(
            "supplier_payment",
            number=number,
            supplier_id=supplier["id"],
            invoice_id=inv["id"],
            amount_cents=cents,
            posting_date=self.today,
            status="posted",
        )
        je_id = self.journal(
            f"Payment {number} for {inv['number']}",
            [
                (AP, cents, 0, f"settle {inv['number']}"),
                (CASH, 0, cents, f"paid {supplier['code']}"),
            ],
            "SupplierPayment",
            pay_id,
        )
        remaining = open_item["remaining_cents"] - cents
        self.update("supplier_payment", pay_id, journal_entry_id=je_id)
        self.update(
            "open_item",
            open_item["id"],
            remaining_cents=remaining,
            status="paid" if remaining == 0 else "partially_paid",
        )
        if remaining == 0:
            self.update("supplier_invoice", inv["id"], status="paid")
        self.notes.append(f"SupplierPayment {number}")

    def create_so(self, customer_code: str, lines: list[dict[str, Any]]) -> dict[str, Any]:
        customer = self.one("customer", code=customer_code)
        items = {x["sku"]: self.one("item", sku=x["sku"]) for x in lines}
        total = sum(items[x["sku"]]["list_price_cents"] * int(x["qty"]) for x in lines)
        exposure = sum(
            oi["remaining_cents"]
            for oi in self.rows("open_item", kind="ar", party_id=customer["id"])
            if oi["status"] in ("open", "partially_paid")
        )
        if exposure + total > customer["credit_limit_cents"]:
            raise _Stop(
                f"Cannot create: CREDIT_LIMIT_EXCEEDED. Exposure {exposure + total} vs limit "
                f"{customer['credit_limit_cents']} cents. Propose: reduce the quantity or collect "
                "open receivables first."
            )
        number = self.next_number("sales_order")
        so_id = self.insert(
            "sales_order",
            number=number,
            customer_id=customer["id"],
            status="open",
            total_cents=total,
            created_by="agent:eval",
        )
        for i, x in enumerate(lines, start=1):
            self.insert(
                "sales_order_line",
                so_id=so_id,
                line_no=i,
                item_id=items[x["sku"]]["id"],
                sku=x["sku"],
                qty=int(x["qty"]),
                unit_price_cents=items[x["sku"]]["list_price_cents"],
            )
        self.notes.append(f"SalesOrder {number}")
        return {"id": so_id, "number": number, "customer_id": customer["id"], "total_cents": total}

    def ship(self, so: dict[str, Any], requested: dict[str, int] | None = None) -> str:
        lines = self.rows("sales_order_line", so_id=so["id"])
        shp_lines, cogs = [], 0
        for line in lines:
            qty = (requested or {}).get(line["sku"], line["qty"] - line["shipped_qty"])
            if qty <= 0:
                continue
            item = self.one("item", sku=line["sku"])
            if item["on_hand_qty"] < qty:
                raise _Stop(
                    f"Cannot ship {so['number']}: INSUFFICIENT_STOCK ({line['sku']}: {qty} "
                    f"requested, {item['on_hand_qty']} on hand). Propose: receive {line['sku']} "
                    "from a supplier first; nothing was shipped."
                )
            line_cogs = item["standard_cost_cents"] * qty
            cogs += line_cogs
            self.update("item", item["id"], on_hand_qty=item["on_hand_qty"] - qty)
            self.update("sales_order_line", line["id"], shipped_qty=line["shipped_qty"] + qty)
            line["shipped_qty"] += qty
            shp_lines.append(
                {
                    "so_line_id": line["id"],
                    "sku": line["sku"],
                    "qty": qty,
                    "unit_cost_cents": item["standard_cost_cents"],
                    "cogs_cents": line_cogs,
                }
            )
        number = self.next_number("shipment")
        shp_id = self.insert(
            "shipment",
            number=number,
            so_id=so["id"],
            shipped_at=self.now.isoformat(),
            lines=shp_lines,
            cogs_cents=cogs,
            status="posted",
        )
        je_id = self.journal(
            f"Shipment {number} for SO {so['number']}",
            [(COGS, cogs, 0, f"COGS {number}"), (INVENTORY, 0, cogs, f"stock issued {number}")],
            "Shipment",
            shp_id,
        )
        self.update("shipment", shp_id, journal_entry_id=je_id)
        self.update("sales_order", so["id"], status=self._so_status(lines))
        self.notes.append(f"Shipment {number}")
        return shp_id

    def issue_customer_invoice(self, so: dict[str, Any]) -> dict[str, Any]:
        customer = self.call("get_row", table="customer", id=so["customer_id"])["result"]
        lines = self.rows("sales_order_line", so_id=so["id"])
        inv_lines, total = [], 0
        for line in lines:
            qty = line["shipped_qty"] - line["invoiced_qty"]
            if qty <= 0:
                continue
            total += line["unit_price_cents"] * qty
            self.update("sales_order_line", line["id"], invoiced_qty=line["invoiced_qty"] + qty)
            line["invoiced_qty"] += qty
            inv_lines.append(
                {
                    "so_line_id": line["id"],
                    "sku": line["sku"],
                    "qty": qty,
                    "unit_price_cents": line["unit_price_cents"],
                    "amount_cents": line["unit_price_cents"] * qty,
                }
            )
        shipments = [
            s["id"] for s in self.rows("shipment", so_id=so["id"]) if s["status"] == "posted"
        ]
        due = (self.now.date() + timedelta(days=int(customer["payment_terms_days"]))).isoformat()
        number = self.next_number("customer_invoice")
        inv_id = self.insert(
            "customer_invoice",
            number=number,
            customer_id=customer["id"],
            so_id=so["id"],
            shipment_ids=shipments,
            lines=inv_lines,
            total_cents=total,
            credited_cents=0,
            posting_date=self.today,
            due_date=due,
            status="posted",
        )
        je_id = self.journal(
            f"Customer invoice {number} for SO {so['number']}",
            [
                (AR, total, 0, f"AR {customer['code']} {number}"),
                (REVENUE, 0, total, f"revenue {number}"),
            ],
            "CustomerInvoice",
            inv_id,
        )
        oi_id = self.insert(
            "open_item",
            kind="ar",
            party_id=customer["id"],
            source_doc_type="CustomerInvoice",
            source_doc_id=inv_id,
            source_doc_number=number,
            amount_cents=total,
            remaining_cents=total,
            due_date=due,
            status="open",
        )
        self.update("customer_invoice", inv_id, journal_entry_id=je_id, open_item_id=oi_id)
        self.update("sales_order", so["id"], status=self._so_status(lines))
        self.notes.append(f"CustomerInvoice {number}")
        return {"id": inv_id, "number": number, "open_item_id": oi_id, "total_cents": total}

    def _settle_ar(self, open_item: dict[str, Any], inv_id: str, delta: int) -> int:
        remaining = open_item["remaining_cents"] - delta
        self.update(
            "open_item",
            open_item["id"],
            remaining_cents=remaining,
            status="paid" if remaining == 0 else "partially_paid",
        )
        return remaining

    def record_customer_payment(self, inv: dict[str, Any], amount: str | None = None) -> None:
        open_item = self.call("get_row", table="open_item", id=inv["open_item_id"])["result"]
        customer = self.call("get_row", table="customer", id=open_item["party_id"])["result"]
        cents = _cents(amount) if amount else open_item["remaining_cents"]
        number = self.next_number("customer_payment")
        rcpt_id = self.insert(
            "customer_payment",
            number=number,
            customer_id=customer["id"],
            invoice_id=inv["id"],
            amount_cents=cents,
            posting_date=self.today,
            status="posted",
        )
        je_id = self.journal(
            f"Receipt {number} for {inv['number']}",
            [
                (CASH, cents, 0, f"received from {customer['code']}"),
                (AR, 0, cents, f"settle {inv['number']}"),
            ],
            "CustomerPayment",
            rcpt_id,
        )
        self.update("customer_payment", rcpt_id, journal_entry_id=je_id)
        if self._settle_ar(open_item, inv["id"], cents) == 0:
            self.update("customer_invoice", inv["id"], status="paid")
        self.notes.append(f"CustomerPayment {number}")

    def issue_credit_note(self, inv: dict[str, Any], amount: str, reason: str) -> None:
        open_item = self.call("get_row", table="open_item", id=inv["open_item_id"])["result"]
        invoice = self.call("get_row", table="customer_invoice", id=inv["id"])["result"]
        customer = self.call("get_row", table="customer", id=open_item["party_id"])["result"]
        cents = _cents(amount)
        number = self.next_number("credit_note")
        cn_id = self.insert(
            "credit_note",
            number=number,
            customer_id=customer["id"],
            invoice_id=inv["id"],
            amount_cents=cents,
            reason=reason,
            posting_date=self.today,
        )
        je_id = self.journal(
            f"Credit note {number} against {inv['number']}: {reason}",
            [
                (REVENUE, cents, 0, f"credit {inv['number']}"),
                (AR, 0, cents, f"reduce AR {customer['code']}"),
            ],
            "CreditNote",
            cn_id,
        )
        self.update("credit_note", cn_id, journal_entry_id=je_id)
        self._settle_ar(open_item, inv["id"], cents)
        credited = invoice["credited_cents"] + cents
        changes: dict[str, Any] = {"credited_cents": credited}
        if credited == invoice["total_cents"]:
            changes["status"] = "credited"
        self.update("customer_invoice", inv["id"], **changes)
        self.notes.append(f"CreditNote {number}")

    # ---- state-driven procure-to-pay (mirrors the treatment script) ------------------------
    @staticmethod
    def _warehouse_count(narrative: str, po_number: str) -> dict[str, int] | None:
        """The count the harness's warehouse reported for this PO in a status update, if any."""
        m = re.search(
            rf"delivery for purchase order {re.escape(po_number)}: ([^;]+); no goods receipt",
            narrative,
        )
        if not m:
            return None
        return {sku: int(qty) for sku, qty in re.findall(r"([A-Z0-9-]+) x(\d+)", m.group(1))}

    def _find_po(self, supplier_code: str, total: int) -> dict[str, Any] | None:
        supplier = self.one("supplier", code=supplier_code)
        for po in self.rows("purchase_order", supplier_id=supplier["id"]):
            if po["total_cents"] == total and po["status"] != "cancelled":
                return po
        return None

    def _p2p(
        self,
        narrative: str,
        supplier: str,
        lines: list[dict[str, Any]],
        *,
        reference: str,
        invoice_costs: dict[str, str] | None = None,
        pay: bool = True,
        pay_amount: str | None = None,
    ) -> dict[str, Any]:
        total = sum(_cents(x["unit_cost"]) * int(x["qty"]) for x in lines)
        po = self._find_po(supplier, total)
        if po is None:
            po = self.create_po(supplier, lines)
        else:
            self.notes.append(f"PurchaseOrder {po['number']} (existing)")
        po_lines = self.rows("purchase_order_line", po_id=po["id"])
        if not any(x["received_qty"] for x in po_lines):
            counted = self._warehouse_count(narrative, po["number"])
            if counted is None:
                raise _Stop(f"Delivery for {po['number']} awaits the warehouse count.")
            self.receive(po, counted)
            po_lines = self.rows("purchase_order_line", po_id=po["id"])
        invoices = [
            i for i in self.rows("supplier_invoice", po_id=po["id"]) if i["status"] != "reversed"
        ]
        if invoices:
            inv = invoices[0]
        else:
            costs = invoice_costs or {}
            inv_lines = [
                {
                    "sku": x["sku"],
                    "qty": x["received_qty"] - x["invoiced_qty"],
                    "unit_cost": costs.get(x["sku"], f"{x['unit_cost_cents'] / 100:.2f}"),
                }
                for x in po_lines
                if x["received_qty"] > x["invoiced_qty"]
            ]
            inv = self.post_supplier_invoice(po, reference, inv_lines)
        if pay:
            oi = self.call("get_row", table="open_item", id=inv["open_item_id"])["result"]
            if oi["remaining_cents"] > 0:
                self.pay_supplier(inv, pay_amount)
        return po

    # ---- tasks -----------------------------------------------------------------------------
    def task_p2p_01_simple(self, n: str) -> None:
        self._p2p(
            n,
            "ACME",
            [{"sku": "VALVE-2IN", "qty": 10, "unit_cost": "50.00"}],
            reference="ACME-1001",
        )
        self.finish("Ordered, received, invoiced and paid 10 VALVE-2IN from ACME.")

    def task_p2p_02_partial_receipt(self, n: str) -> None:
        self._p2p(
            n, "BOLT", [{"sku": "FLANGE-4", "qty": 200, "unit_cost": "15.00"}], reference="BOLT-1"
        )
        self.finish("Invoiced and paid the accepted quantity; the PO stays partially received.")

    def task_p2p_04_over_threshold(self, n: str) -> None:
        self.create_po("ACME", [{"sku": "PUMP-SM", "qty": 30, "unit_cost": "400.00"}])
        self.finish("PO created.")

    def task_p2p_05_cancel(self, n: str) -> None:
        po = self.create_po("ACME", [{"sku": "VALVE-2IN", "qty": 3, "unit_cost": "50.00"}])
        self.update(
            "purchase_order",
            po["id"],
            status="cancelled",
            cancelled_reason="manager changed their mind",
        )
        self.finish("Created then cancelled the PO before any receipt.")

    def task_p2p_06_price_variance_5pct(self, n: str) -> None:
        self._p2p(
            n,
            "ACME",
            [{"sku": "VALVE-2IN", "qty": 10, "unit_cost": "50.00"}],
            reference="ACME-V5",
            invoice_costs={"VALVE-2IN": "52.50"},
        )
        self.finish("posted")

    def task_p2p_07_variance_within_tolerance(self, n: str) -> None:
        self._p2p(
            n,
            "ACME",
            [{"sku": "VALVE-2IN", "qty": 10, "unit_cost": "50.00"}],
            reference="ACME-V1",
            invoice_costs={"VALVE-2IN": "50.50"},
        )
        self.finish("Invoice posted with a 1% variance inside tolerance, paid.")

    def task_p2p_08_reverse_wrong_grn(self, n: str) -> None:
        wrong = [
            g for g in self.rows("goods_receipt", status="posted") if g["total_cents"] == 62500
        ]
        if wrong:
            self.reverse_receipt(wrong[0], "goods never arrived")
            raise _Stop("Reversed the wrong receipt; the real delivery awaits the warehouse count.")
        po = self.one("purchase_order", status="approved")
        counted = self._warehouse_count(n, po["number"])
        if counted:
            self.receive(po, counted)
        self.finish("Reversed the wrong receipt and recorded the real delivery of 25 HOSE-10M.")

    def task_p2p_09_partial_payment(self, n: str) -> None:
        self._p2p(
            n,
            "ACME",
            [{"sku": "PUMP-SM", "qty": 10, "unit_cost": "400.00"}],
            reference="ACME-P9",
            pay_amount="2500.00",
        )
        self.finish("Paid 2,500.00 of 4,000.00; 1,500.00 remains open.")

    def task_o2c_01_simple(self, n: str) -> None:
        so = self.create_so("NORTH", [{"sku": "VALVE-2IN", "qty": 5}])
        self.ship(so)
        inv = self.issue_customer_invoice(so)
        self.record_customer_payment(inv)
        self.finish("Sold, shipped, invoiced and collected 5 VALVE-2IN for NORTH.")

    def task_o2c_02_credit_limit(self, n: str) -> None:
        self.create_so("HARB", [{"sku": "PUMP-SM", "qty": 10}])
        self.finish("unexpected")

    def task_o2c_03_partial_ship(self, n: str) -> None:
        so = self.create_so("NORTH", [{"sku": "HOSE-10M", "qty": 60}])
        self.ship(so, {"HOSE-10M": 40})
        self.issue_customer_invoice(so)
        self.finish("Shipped and invoiced 40 of 60 hoses.")

    def task_o2c_04_credit_note(self, n: str) -> None:
        so = self.create_so("NORTH", [{"sku": "VALVE-2IN", "qty": 4}])
        self.ship(so)
        inv = self.issue_customer_invoice(so)
        self.issue_credit_note(inv, "80.00", "one unit damaged in transit")
        self.record_customer_payment(inv)
        self.finish("Invoiced 320.00, credited 80.00, collected 240.00.")

    def task_o2c_05_out_of_stock(self, n: str) -> None:
        so = self.create_so("NORTH", [{"sku": "PUMP-SM", "qty": 3}])
        self.ship(so)
        self.finish("unexpected")

    def task_o2c_06_payment_reversal(self, n: str) -> None:
        rcpt = self.one("customer_payment", status="posted")
        inv = self.call("get_row", table="customer_invoice", id=rcpt["invoice_id"])["result"]
        open_item = self.call("get_row", table="open_item", id=inv["open_item_id"])["result"]
        je = self.call("get_row", table="journal_entry", id=rcpt["journal_entry_id"])["result"]
        self.reverse_journal(
            je, f"Reversal of {rcpt['number']}: cheque bounced", "CustomerPayment", rcpt["id"]
        )
        self.update("customer_payment", rcpt["id"], status="reversed")
        remaining = open_item["remaining_cents"] + rcpt["amount_cents"]
        self.update(
            "open_item",
            open_item["id"],
            remaining_cents=remaining,
            status="open" if remaining == open_item["amount_cents"] else "partially_paid",
        )
        self.update("customer_invoice", inv["id"], status="posted")
        self.finish("Reversed the bounced receipt; the invoice is open again.")

    def task_gl_01_manual_je(self, n: str) -> None:
        self.journal(
            "Office rent accrual",
            [(OPEX, 120000, 0, "office rent"), (AP, 0, 120000, "rent accrual")],
            "ManualJournal",
            "",
        )
        self.finish("Posted the accrual.")

    def task_gl_02_reverse_je(self, n: str) -> None:
        dupes = [
            j
            for j in self.rows("journal_entry", status="posted")
            if j["total_debit_cents"] == 999900
        ]
        target = dupes[0]
        self.reverse_journal(
            target, f"Reversal of {target['number']}: posted twice", "ManualJournal", target["id"]
        )
        self.finish("Reversed the duplicate entry.")

    def task_gl_03_closed_period(self, n: str) -> None:
        m = re.search(r"dated (\d{4}-\d{2}-\d{2})", n)
        date = m.group(1) if m else self.today
        self.journal(
            "Late consulting fee",
            [(OPEX, 40000, 0, "consulting"), (CASH, 0, 40000, "consulting")],
            "ManualJournal",
            "",
            posting_date=date,
        )
        self.finish("unexpected")

    def _close_blockers(self, period: str) -> list[str]:
        blocked = [
            i["number"]
            for i in self.rows("supplier_invoice", status="blocked")
            if str(i["posting_date"])[:7] == period
        ]
        return [f"blocked supplier invoice(s) {', '.join(blocked)}"] if blocked else []

    def task_close_01_clean(self, n: str) -> None:
        m = re.search(r"period (\d{4}-\d{2})", n)
        period = m.group(1) if m else ""
        blockers = self._close_blockers(period)
        if blockers:
            raise _Stop(f"Cannot close {period}: {'; '.join(blockers)}.")
        row = self.period(period + "-01")
        self.update("fiscal_period", row["id"], status="closed")
        self.finish(f"Closed {period}.")

    def task_close_02_blocked(self, n: str) -> None:
        m = re.search(r"period (\d{4}-\d{2})", n)
        period = m.group(1) if m else ""
        blockers = self._close_blockers(period)
        if blockers:
            raise _Stop(f"Cannot close {period}: {'; '.join(blockers)}. Resolve them first.")
        self.finish("unexpected")

    def task_dup_01_retry_storm(self, n: str) -> None:
        self._p2p(
            n,
            "BOLT",
            [{"sku": "HOSE-10M", "qty": 20, "unit_cost": "25.00"}],
            reference="BOLT-20",
            pay=False,
        )
        self.finish("Ordered, received and invoiced 20 HOSE-10M from BOLT.")


def run_crud(surface: ToolSurface, task_id: str, narrative: str, trace: RunTrace) -> None:
    runner = CrudRunner(surface, trace, task_id)
    handler = getattr(runner, "task_" + re.sub(r"[^a-z0-9_]", "_", task_id.split("__")[0]), None)
    if handler is None:
        trace.final_text = f"no script for task {task_id}"
        trace.error = "no_script"
        return
    try:
        handler(narrative)
    except _Stop as stop:
        trace.final_text = str(stop)
