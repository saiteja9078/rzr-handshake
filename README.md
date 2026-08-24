# RZR-Handshake

RZR-Handshake makes a merchant transactable by an AI buyer end to end. The merchant service, `acp`, exposes a structured catalog and bounded order tools over MCP streamable HTTP. Razorpay talks to the same FastAPI process through a separate plain REST webhook route. The client agent is a small standalone CLI that translates natural-language requests into typed MCP calls and persists its conversation and pending purchases.

## Trust boundary

```text
Customer text
    -> client-agent (replaceable intent parser)
    -> MCP typed tools at /mcp
    -> acp + PostgreSQL + Razorpay Payment Links

Razorpay -> POST /webhooks/razorpay (signature verification, stock lock, paid/failed transition)
```

`acp` contains no LLM. It is deterministic and auditable. `create_order` re-reads the variant price and stock from the database, enforces `MAX_QTY` and `MAX_SPEND`, and returns only an `awaiting_payment` Payment Link. It never trusts a caller-supplied price and never marks an order paid. Only a verified Razorpay webhook can decrement stock and move an order to `paid`.

## Layout

* `acp/db/schema.sql` — PostgreSQL schema. `seed.sql` is intentionally not included; seed data is supplied separately as requested.
* `acp/app/tools/` — the seven MCP tool implementations.
* `acp/app/payments/webhook_handler.py` — plain `POST /webhooks/razorpay` route.
* `acp/app/rating/bayesian.py` — Bayesian ratings and deterministic sentiment.
* `client-agent/app/agent.py` — CLI client agent with a replaceable parser.
* `tests/test_acp_flow.py` — focused SQLite tests for the money path and failure case.

## Run locally without credentials

The default database is `sqlite+aiosqlite:///./acp_demo.db` and the default payment provider is a deterministic demo Payment Link provider. This makes the whole protocol and webhook path runnable without moving money. For actual Razorpay test-mode links, set the variables in `.env.example` and use `PAYMENT_PROVIDER=razorpay` or `auto`.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt

PYTHONPATH=. .venv/bin/uvicorn acp.app.main:app --reload
```

The server exposes:

* `GET /health`
* MCP streamable HTTP at `/mcp`
* Razorpay REST webhook at `POST /webhooks/razorpay`

In another terminal, after supplying a customer and product through your seed data:

```bash
CUSTOMER_ID=1 .venv/bin/python client-agent/app/agent.py
```

Example conversation:

```text
you> show me red shoes under 5000
you> buy product 1 variant 3 quantity 1
you> confirm
agent> Order #... is awaiting payment for ₹.... Open this Razorpay test-mode link: ...
you> status order 1
```

The client shows the amount before confirmation, then persists the pending order and payment link in `client-agent/session.sqlite3`. It reports `paid` or the explicit sold-out/refund-required message after polling.

## PostgreSQL / Razorpay test mode

Start PostgreSQL with `docker compose up -d postgres`, set `DATABASE_URL`, and apply the schema:

```bash
psql "$DATABASE_URL" -f acp/db/schema.sql
psql "$DATABASE_URL" -f /path/to/your/seed.sql
```

Set `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, and `RAZORPAY_WEBHOOK_SECRET` from Razorpay test mode. Configure Razorpay to POST payment-link events to:

```text
https://<your-public-host>/webhooks/razorpay
```

The webhook signature is HMAC-SHA256 over the exact raw request body. The configured webhook secret is preferred; the key secret is used as a fallback for the simplified build specification.

## MCP tools

The server registers exactly these tool names:

* `get_catalog_schema()` — call once and cache for the client session.
* `search_catalog(filters)` — category, price, rating, JSON attributes, keyword, sort, page.
* `get_product_details(product_id, variant_id?)`
* `get_more_reviews(product_id, page)`
* `create_order(request)` — customer, product, variant, quantity, and optional reasoning context.
* `get_order_status(order_id)`
* `submit_review(request)` — paid-order and customer ownership gated.

Every tool call and state transition is written to `audit_log`. Search results include Bayesian weighted ratings and positive/negative review evidence. Review sentiment is a deterministic rating rule: 4–5 positive, 3 neutral, 1–2 negative.

## Required graceful failure demo

Use a variant seeded with `stock_qty = 1`. Create two orders before completing either Payment Link. Complete both signed webhook sequences. The first transaction locks and decrements the variant. The second re-checks the locked row, marks its order `failed`, writes a `refund_required` payment, emits `stock_depleted_post_payment`, and returns:

> This sold out right before your payment cleared; a refund is required.

There is no negative stock and no silent failure. The test suite exercises this exact sequence.

## Tests

```bash
PYTHONPATH=. .venv/bin/python -m pytest -q
```

The tests use a temporary SQLite database and a fake Payment Link client; production deployment remains PostgreSQL-first through `DATABASE_URL` and the official Razorpay Python SDK.
