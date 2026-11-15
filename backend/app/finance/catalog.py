"""The data catalogue: what the agent (and a person) is told about the analytics schema.

This is the only description of the data the model receives, so it carries meaning, not just names: what a row
is, which columns are money, how the business metrics are defined. Every table and column of schema
`analytics` must be documented here; a test compares this file with the database.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Column:
    name: str
    type: str
    description: str


@dataclass(frozen=True)
class TableDoc:
    name: str
    description: str
    columns: tuple[Column, ...]

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "columns": [c.__dict__ for c in self.columns],
        }


def _t(name: str, description: str, *columns: tuple[str, str, str]) -> TableDoc:
    return TableDoc(name, description, tuple(Column(*c) for c in columns))


_TABLES = [
    _t(
        "order_lines",
        "One row per line of a COMPLETED order, with money converted to USD. Start here for revenue, "
        "discount, cost and margin questions; cancelled and returned orders are already excluded.",
        ("order_item_id", "bigint", "Line id"),
        ("order_id", "bigint", "Order the line belongs to"),
        ("order_date", "date", "Date of the order"),
        ("customer_id", "bigint", "Customer id"),
        ("customer_name", "text", "Customer name"),
        ("segment", "text", "Customer segment: Enterprise, Mid-Market or SMB"),
        ("region", "text", "Customer region: North, South, East or West"),
        ("product_id", "bigint", "Product id"),
        ("sku", "text", "Product code"),
        ("product_name", "text", "Product name"),
        ("category", "text", "Metals, Plastics, Packaging, Electronics, Tools or Chemicals"),
        ("supplier", "text", "Supplier of the product"),
        ("quantity", "int", "Units sold"),
        ("currency", "text", "Currency the order was placed in: USD, EUR or GBP"),
        ("discount_pct", "numeric", "Discount as a fraction of list price (0.05 = 5%)"),
        ("unit_price_usd", "numeric", "Price per unit before discount, USD"),
        ("unit_cost_usd", "numeric", "Cost per unit in force on the order date, USD"),
        ("revenue_usd", "numeric", "Net revenue of the line after discount, USD"),
        ("discount_usd", "numeric", "Discount given on the line, USD"),
        ("cogs_usd", "numeric", "Cost of goods sold for the line, USD"),
        ("gross_profit_usd", "numeric", "revenue_usd minus cogs_usd"),
    ),
    _t(
        "orders",
        "Every order including cancelled and returned ones.",
        ("id", "bigint", "Order id"),
        ("customer_id", "bigint", "Customer id"),
        ("order_date", "date", "Date of the order"),
        ("status", "text", "completed, cancelled or returned"),
        ("currency", "text", "USD, EUR or GBP"),
        ("fx_rate_to_usd", "numeric", "Multiply order-currency amounts by this to get USD"),
    ),
    _t(
        "order_items",
        "Raw order lines in the order's own currency. Prefer order_lines unless you need non-completed orders.",
        ("id", "bigint", "Line id"),
        ("order_id", "bigint", "Order id"),
        ("product_id", "bigint", "Product id"),
        ("quantity", "int", "Units"),
        ("unit_price", "numeric", "Price per unit in the ORDER currency, before discount"),
        ("discount_pct", "numeric", "Discount fraction"),
        ("unit_cost_usd", "numeric", "Cost per unit in USD on the order date"),
    ),
    _t(
        "customers",
        "Customers.",
        ("id", "bigint", "Customer id"),
        ("name", "text", "Customer name"),
        ("segment", "text", "Enterprise, Mid-Market or SMB"),
        ("region_id", "bigint", "Region id (join regions)"),
        ("payment_terms_days", "int", "Days allowed between invoice and payment"),
        ("created_on", "date", "When the customer was added"),
    ),
    _t(
        "regions",
        "Sales regions.",
        ("id", "bigint", "Region id"),
        ("name", "text", "North, South, East, West"),
    ),
    _t(
        "suppliers",
        "Suppliers of products.",
        ("id", "bigint", "Supplier id"),
        ("name", "text", "Supplier name"),
    ),
    _t(
        "products",
        "Products sold.",
        ("id", "bigint", "Product id"),
        ("sku", "text", "Product code"),
        ("name", "text", "Product name"),
        ("category", "text", "Product category"),
        ("supplier_id", "bigint", "Supplier id"),
        ("list_price_usd", "numeric", "List price per unit, USD"),
    ),
    _t(
        "product_costs",
        "Cost history: what each product costs from its supplier, from a given date until the next row.",
        ("id", "bigint", "Row id"),
        ("product_id", "bigint", "Product id"),
        ("supplier_id", "bigint", "Supplier id"),
        ("unit_cost_usd", "numeric", "Cost per unit, USD"),
        ("effective_from", "date", "First day this cost applies"),
    ),
    _t(
        "invoices",
        "One invoice per completed order.",
        ("id", "bigint", "Invoice id"),
        ("order_id", "bigint", "Order id"),
        ("customer_id", "bigint", "Customer id"),
        ("issued_date", "date", "Date issued"),
        ("due_date", "date", "Date payment is due"),
        ("amount_usd", "numeric", "Invoice amount, USD"),
    ),
    _t(
        "payments",
        "Payments received. An invoice with no payment row is still outstanding.",
        ("id", "bigint", "Payment id"),
        ("invoice_id", "bigint", "Invoice paid"),
        ("paid_date", "date", "Date paid"),
        ("amount_usd", "numeric", "Amount paid, USD"),
    ),
    _t(
        "expenses",
        "Operating expenses by month, category and region (not cost of goods).",
        ("id", "bigint", "Row id"),
        ("expense_month", "date", "First day of the month"),
        ("category", "text", "Salaries, Marketing, Logistics, Rent or Software"),
        ("region_id", "bigint", "Region id"),
        ("amount_usd", "numeric", "Amount, USD"),
    ),
    _t(
        "budgets",
        "Monthly plan by region. Category 'Revenue' is the revenue target; other categories are expense budgets.",
        ("id", "bigint", "Row id"),
        ("budget_month", "date", "First day of the month"),
        ("category", "text", "Revenue, Salaries, Marketing, Logistics, Rent or Software"),
        ("region_id", "bigint", "Region id"),
        ("amount_usd", "numeric", "Planned amount, USD"),
    ),
    _t(
        "fx_rates",
        "Monthly currency rates.",
        ("id", "bigint", "Row id"),
        ("currency", "text", "EUR or GBP"),
        ("rate_month", "date", "First day of the month"),
        ("rate_to_usd", "numeric", "USD per one unit of the currency"),
    ),
]

CATALOG: dict[str, TableDoc] = {t.name: t for t in _TABLES}

# Business definitions. The agent is told to use exactly these.
METRICS: dict[str, dict[str, str]] = {
    "revenue": {
        "definition": "Net revenue from completed orders after discounts, in USD.",
        "sql": "SUM(revenue_usd) FROM analytics.order_lines",
    },
    "gross_margin": {
        "definition": "(revenue - cost of goods sold) / revenue.",
        "sql": "SUM(gross_profit_usd) / NULLIF(SUM(revenue_usd), 0) FROM analytics.order_lines",
    },
    "operating_margin": {
        "definition": "(revenue - cost of goods sold - operating expenses) / revenue, for the same period "
        "and region. Operating expenses come from analytics.expenses.",
        "sql": "(SUM(gross_profit_usd) - <SUM(amount_usd) FROM analytics.expenses for the same months>) "
        "/ NULLIF(SUM(revenue_usd), 0)",
    },
    "discount_rate": {
        "definition": "Discount given as a share of revenue before discount.",
        "sql": "SUM(discount_usd) / NULLIF(SUM(revenue_usd + discount_usd), 0) FROM analytics.order_lines",
    },
    "dso": {
        "definition": "Days sales outstanding: average days from invoice issue to payment, over invoices paid "
        "in the period. Unpaid invoices are not included; report them separately as outstanding.",
        "sql": "AVG(p.paid_date - i.issued_date) FROM analytics.invoices i JOIN analytics.payments p "
        "ON p.invoice_id = i.id",
    },
    "overdue": {
        "definition": "An invoice is overdue when its due date has passed (relative to the last day of data) and it "
        "has no payment. Report overdue invoices by count and amount alongside any days-late figure.",
        "sql": "FROM analytics.invoices i LEFT JOIN analytics.payments p ON p.invoice_id = i.id "
        "WHERE p.id IS NULL AND i.due_date < DATE '2026-09-30'",
    },
    "days_late": {
        "definition": "Days between the due date and the payment date (negative means paid early).",
        "sql": "AVG(p.paid_date - i.due_date)",
    },
}

DATA_RANGE = {"first_order": "2024-01-01", "last_order": "2026-09-30", "reporting_currency": "USD"}


def catalog_payload() -> dict:
    return {
        "tables": [t.as_dict() for t in CATALOG.values()],
        "metrics": [{"name": k, **v} for k, v in METRICS.items()],
        "data_range": DATA_RANGE,
    }
