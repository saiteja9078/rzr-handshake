-- Agent Commerce Protocol schema.
-- seed.sql is intentionally not included: seed data is supplied separately.

CREATE TABLE merchants (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    razorpay_account_ref TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE products (
    id BIGSERIAL PRIMARY KEY,
    merchant_id BIGINT NOT NULL REFERENCES merchants(id),
    name TEXT NOT NULL,
    brand TEXT,
    category TEXT NOT NULL,
    description TEXT,
    rating_avg NUMERIC(2,1) DEFAULT 0,
    rating_count INTEGER DEFAULT 0,
    bayesian_rating NUMERIC(3,2) DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_products_category ON products(category);
CREATE INDEX idx_products_merchant ON products(merchant_id);

CREATE TABLE variants (
    id BIGSERIAL PRIMARY KEY,
    product_id BIGINT NOT NULL REFERENCES products(id),
    attributes JSONB NOT NULL DEFAULT '{}',
    price NUMERIC(10,2) NOT NULL,
    mrp NUMERIC(10,2),
    stock_qty INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_variants_product ON variants(product_id);
CREATE INDEX idx_variants_attrs ON variants USING GIN (attributes);
CREATE INDEX idx_variants_price ON variants(price);

CREATE TABLE customers (
    id BIGSERIAL PRIMARY KEY,
    name TEXT,
    email TEXT UNIQUE,
    auth_token TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE orders (
    id BIGSERIAL PRIMARY KEY,
    customer_id BIGINT NOT NULL REFERENCES customers(id),
    variant_id BIGINT NOT NULL REFERENCES variants(id),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    unit_price NUMERIC(10,2) NOT NULL,
    total_amount NUMERIC(10,2) NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    razorpay_payment_link_id TEXT,
    paid_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_orders_customer ON orders(customer_id);
CREATE INDEX idx_orders_status ON orders(status);
CREATE UNIQUE INDEX idx_orders_payment_link ON orders(razorpay_payment_link_id)
    WHERE razorpay_payment_link_id IS NOT NULL;

CREATE TABLE payments (
    id BIGSERIAL PRIMARY KEY,
    order_id BIGINT NOT NULL REFERENCES orders(id),
    razorpay_payment_id TEXT,
    razorpay_signature TEXT,
    verified BOOLEAN DEFAULT FALSE,
    status TEXT NOT NULL DEFAULT 'pending',
    amount NUMERIC(10,2) NOT NULL,
    raw_webhook_payload JSONB,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_payments_order ON payments(order_id);

CREATE TABLE reviews (
    id BIGSERIAL PRIMARY KEY,
    product_id BIGINT NOT NULL REFERENCES products(id),
    customer_id BIGINT NOT NULL REFERENCES customers(id),
    order_id BIGINT NOT NULL REFERENCES orders(id),
    rating SMALLINT NOT NULL CHECK (rating BETWEEN 1 AND 5),
    text TEXT,
    sentiment TEXT,
    helpful_count INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(order_id)
);
CREATE INDEX idx_reviews_product ON reviews(product_id);

CREATE TABLE audit_log (
    id BIGSERIAL PRIMARY KEY,
    actor TEXT,
    event_type TEXT NOT NULL,
    entity_type TEXT,
    entity_id BIGINT,
    details JSONB,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_audit_entity ON audit_log(entity_type, entity_id);
CREATE INDEX idx_audit_event ON audit_log(event_type);
