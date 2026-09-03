"""A2A: delegated procure-to-pay completes; over-threshold returns input-required with the approval id."""

from __future__ import annotations

import httpx2
import pytest

from anerp.admin.tokens import bootstrap_admin
from anerp.server import create_app
from tests.conftest import Client


def _rpc(msg_id: str, parts: list[dict], task_id: str | None = None):
    message = {"messageId": msg_id, "role": "ROLE_USER", "parts": parts}
    if task_id:
        message["taskId"] = task_id
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
                                    "lines": [{"sku": "WIDGET-1", "qty": 5, "unit_cost": "50.00"}],
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
            assert task["status"]["state"] == "TASK_STATE_COMPLETED", body
            parts = task["status"]["message"]["parts"]
            data = next(p["data"] for p in parts if "data" in p)
            assert data["ok"] and set(data["documents"]) == {
                "PurchaseOrder",
                "GoodsReceipt",
                "SupplierInvoice",
                "SupplierPayment",
            }
            assert (
                human.query("get_document", id_or_number=data["documents"]["PurchaseOrder"])[
                    "status"
                ]
                == "invoiced"
            )
            receipts = human.query("get_document", id_or_number=data["documents"]["PurchaseOrder"])[
                "receipts"
            ]
            assert receipts[0]["actor_id"] == "agent:anerp-finance"

            # over threshold -> input-required with ApprovalRequest id, then resume after human approval
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
                                    "lines": [
                                        {"sku": "GADGET-2", "qty": 150, "unit_cost": "120.00"}
                                    ],
                                },
                            }
                        }
                    ],
                ),
            )
            task = r.json()["result"]["task"]
            assert task["status"]["state"] == "TASK_STATE_INPUT_REQUIRED", r.json()
            data = next(p["data"] for p in task["status"]["message"]["parts"] if "data" in p)
            assert data["approval_request_id"]
            po_number = data["documents"]["PurchaseOrder"]
            assert human.query("get_document", id_or_number=po_number)["status"] == "draft"
            human.ok("approve_purchase_order", po=po_number, comment="approved via inbox")
            r = await http.post(
                "/a2a", json=_rpc("m3", [{"text": "approved, continue"}], task_id=task["id"])
            )
            task2 = r.json()["result"]["task"]
            assert task2["status"]["state"] == "TASK_STATE_COMPLETED", (
                task2["status"]["state"],
                task2["status"].get("message"),
            )
            assert human.query("get_document", id_or_number=po_number)["status"] == "invoiced"

            # blocked: credit limit on order-to-cash -> failed with the reason
            r = await http.post(
                "/a2a",
                json=_rpc(
                    "m4",
                    [
                        {
                            "data": {
                                "skill": "order-to-cash",
                                "params": {
                                    "customer": "INITECH",
                                    "lines": [{"sku": "GADGET-2", "qty": 40}],
                                },
                            }
                        }
                    ],
                ),
            )
            task = r.json()["result"]["task"]
            assert task["status"]["state"] == "TASK_STATE_FAILED"
            data = next(p["data"] for p in task["status"]["message"]["parts"] if "data" in p)
            assert data["blocked"]["would_fail_with"] == "CREDIT_LIMIT_EXCEEDED"
