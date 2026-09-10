"""A2A: delegated procure-to-pay completes; over-threshold returns input-required with the approval id."""

from __future__ import annotations

import httpx2
import pytest

from anerp.admin.tokens import bootstrap_admin
from anerp.server import create_app
from tests.conftest import Client


def _task(r):
    body = r.json()
    assert "result" in body, body
    return body["result"]["task"]


def _rpc(msg_id: str, parts: list[dict], task_id: str | None = None, context_id: str | None = None):
    message = {"messageId": msg_id, "role": "ROLE_USER", "parts": parts}
    if task_id:
        message["taskId"] = task_id
    if context_id:
        message["contextId"] = context_id
    return {"jsonrpc": "2.0", "id": msg_id, "method": "SendMessage", "params": {"message": message}}


@pytest.mark.anyio
async def test_a2a_procure_to_pay(kernel, human: Client):
    bootstrap_admin(kernel)
    kernel.commit()
    app = create_app()
    async with app.router.lifespan_context(app):
        transport = httpx2.ASGITransport(app=app)
        async with httpx2.AsyncClient(
            transport=transport, base_url="http://testserver", headers={"A2A-Version": "1.0"}
        ) as http:
            # 1. delegated P2P: stops for the warehouse count, resumes after a human accepts
            r = await http.post(
                "/a2a",
                json=_rpc(
                    "m1",
                    [
                        {
                            "data": {
                                "skill": "procure-to-pay",
                                "params": {
                                    "supplier": "ACME",
                                    "lines": [{"sku": "VALVE-2IN", "qty": 5, "unit_cost": "50.00"}],
                                },
                            }
                        }
                    ],
                ),
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert "result" in body, body
            task = body["result"]["task"]
            assert task["status"]["state"] == "TASK_STATE_INPUT_REQUIRED", [
                p.get("text") or p.get("data") for p in task["status"]["message"]["parts"]
            ]
            data = next(p["data"] for p in task["status"]["message"]["parts"] if "data" in p)
            assert data["approval_request_id"] and set(data["documents"]) == {"PurchaseOrder"}
            po_number = data["documents"]["PurchaseOrder"]
            req = human.query("list_pending_approvals", kind="goods_acceptance")["pending"][0]
            assert (
                req["id"] == data["approval_request_id"]
                and req["requested_by"] == "agent:anerp-finance"
            )
            human.ok("accept_goods", request_id=req["id"], comment="counted")
            r = await http.post(
                "/a2a",
                json=_rpc(
                    "m1b",
                    [{"text": "goods accepted, continue"}],
                    task_id=task["id"],
                    context_id=task["contextId"],
                ),
            )
            task = _task(r)
            assert task["status"]["state"] == "TASK_STATE_COMPLETED", r.json()
            data = next(p["data"] for p in task["status"]["message"]["parts"] if "data" in p)
            assert data["ok"] and {"SupplierInvoice", "SupplierPayment"} <= set(data["documents"])
            doc = human.query("get_document", id_or_number=po_number)
            assert (
                doc["status"] == "invoiced"
                and doc["receipts"][0]["actor_id"] == "agent:anerp-finance"
            )

            # 2. over threshold -> po_approval input-required; approved -> goods acceptance; accepted -> completed
            r = await http.post(
                "/a2a",
                json=_rpc(
                    "m2",
                    [
                        {
                            "data": {
                                "skill": "procure-to-pay",
                                "params": {
                                    "supplier": "ACME",
                                    "lines": [{"sku": "PUMP-SM", "qty": 30, "unit_cost": "400.00"}],
                                },
                            }
                        }
                    ],
                ),
            )
            task = _task(r)
            assert task["status"]["state"] == "TASK_STATE_INPUT_REQUIRED", r.json()
            data = next(p["data"] for p in task["status"]["message"]["parts"] if "data" in p)
            po_number = data["documents"]["PurchaseOrder"]
            assert human.query("get_document", id_or_number=po_number)["status"] == "draft"
            human.ok("approve_purchase_order", po=po_number, comment="approved via inbox")
            r = await http.post(
                "/a2a",
                json=_rpc(
                    "m3",
                    [{"text": "approved, continue"}],
                    task_id=task["id"],
                    context_id=task["contextId"],
                ),
            )
            task2 = _task(r)
            assert task2["status"]["state"] == "TASK_STATE_INPUT_REQUIRED", (
                task2["status"]["state"],
                task2["status"].get("message"),
            )
            data = next(p["data"] for p in task2["status"]["message"]["parts"] if "data" in p)
            human.ok(
                "accept_goods",
                request_id=data["approval_request_id"],
                accepted_lines=[{"sku": "PUMP-SM", "qty": 28, "damaged_qty": 2}],
            )
            r = await http.post(
                "/a2a",
                json=_rpc(
                    "m3b",
                    [{"text": "accepted 28, 2 damaged"}],
                    task_id=task["id"],
                    context_id=task["contextId"],
                ),
            )
            task3 = _task(r)
            assert task3["status"]["state"] == "TASK_STATE_COMPLETED", (
                task3["status"]["state"],
                task3["status"].get("message"),
            )
            po_doc = human.query("get_document", id_or_number=po_number)
            # 28 of 30 accepted (2 damaged): the accepted quantity is invoiced and the PO stays open
            assert po_doc["status"] == "partially_received"
            assert po_doc["supplier_invoices"][0]["total_cents"] == 28 * 40000
            assert (
                po_doc["lines"][0]["received_qty"] == 28
                and po_doc["lines"][0]["invoiced_qty"] == 28
            )

            # 3. blocked: credit limit on order-to-cash -> failed with the reason
            r = await http.post(
                "/a2a",
                json=_rpc(
                    "m4",
                    [
                        {
                            "data": {
                                "skill": "order-to-cash",
                                "params": {
                                    "customer": "HARB",
                                    "lines": [{"sku": "PUMP-SM", "qty": 10}],
                                },
                            }
                        }
                    ],
                ),
            )
            task = _task(r)
            assert task["status"]["state"] == "TASK_STATE_FAILED"
            data = next(p["data"] for p in task["status"]["message"]["parts"] if "data" in p)
            assert data["blocked"]["would_fail_with"] == "CREDIT_LIMIT_EXCEEDED"
