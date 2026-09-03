"""Imports every table so SQLModel.metadata (and Alembic) sees the full schema."""

from anerp.approvals.models import ApprovalRequest
from anerp.events.models import Event
from anerp.finance.models import FiscalPeriod, JournalEntry, JournalLine, OpenItem
from anerp.ledger.models import (
    ApiToken,
    DocumentSequence,
    IdempotencyRecord,
    PolicyVersion,
    Receipt,
    ServerKey,
)
from anerp.masterdata.models import Account, Customer, Item, Supplier
from anerp.procurement.models import (
    GoodsReceipt,
    PurchaseOrder,
    PurchaseOrderLine,
    SupplierInvoice,
    SupplierPayment,
)
from anerp.sales.models import (
    CreditNote,
    CustomerInvoice,
    CustomerPayment,
    SalesOrder,
    SalesOrderLine,
    Shipment,
)

DOCUMENT_TYPES: dict[str, type] = {
    "Account": Account,
    "Supplier": Supplier,
    "Customer": Customer,
    "Item": Item,
    "FiscalPeriod": FiscalPeriod,
    "JournalEntry": JournalEntry,
    "OpenItem": OpenItem,
    "PurchaseOrder": PurchaseOrder,
    "GoodsReceipt": GoodsReceipt,
    "SupplierInvoice": SupplierInvoice,
    "SupplierPayment": SupplierPayment,
    "SalesOrder": SalesOrder,
    "Shipment": Shipment,
    "CustomerInvoice": CustomerInvoice,
    "CustomerPayment": CustomerPayment,
    "CreditNote": CreditNote,
    "ApprovalRequest": ApprovalRequest,
}

NUMBER_PREFIXES: dict[str, str] = {
    "JournalEntry": "JE",
    "PurchaseOrder": "PO",
    "GoodsReceipt": "GRN",
    "SupplierInvoice": "SINV",
    "SupplierPayment": "PAY",
    "SalesOrder": "SO",
    "Shipment": "SHP",
    "CustomerInvoice": "CINV",
    "CustomerPayment": "RCPT",
    "CreditNote": "CN",
}

__all__ = [
    "DOCUMENT_TYPES",
    "NUMBER_PREFIXES",
    "Account",
    "ApiToken",
    "ApprovalRequest",
    "CreditNote",
    "Customer",
    "CustomerInvoice",
    "CustomerPayment",
    "DocumentSequence",
    "Event",
    "FiscalPeriod",
    "GoodsReceipt",
    "IdempotencyRecord",
    "Item",
    "JournalEntry",
    "JournalLine",
    "OpenItem",
    "PolicyVersion",
    "PurchaseOrder",
    "PurchaseOrderLine",
    "Receipt",
    "SalesOrder",
    "SalesOrderLine",
    "ServerKey",
    "Shipment",
    "Supplier",
    "SupplierInvoice",
    "SupplierPayment",
]
