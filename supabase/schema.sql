-- ============================================================
-- ClassifyHub — Supabase (Postgres) schema
-- Run this in the Supabase SQL Editor on a fresh project.
-- Matches server/app/models.py exactly (table & column names).
-- ============================================================

create extension if not exists pgcrypto;

create table if not exists tenants (
    id          serial primary key,
    name        varchar(120) not null,
    slug        varchar(120) not null unique,
    status      varchar(20)  not null default 'active',
    created_at  timestamptz  not null default now()
);

create table if not exists users (
    id            serial primary key,
    tenant_id     integer references tenants(id),   -- null => platform owner
    email         varchar(255) not null,
    full_name     varchar(120) not null default '',
    password_hash varchar(255) not null,
    role          varchar(20)  not null default 'user',  -- owner | admin | user
    is_active     boolean      not null default true,
    created_at    timestamptz  not null default now(),
    constraint uq_user_email unique (email)
);

create table if not exists plans (
    id            serial primary key,
    name          varchar(60) not null unique,
    price_monthly double precision not null default 0,
    max_users     integer not null default 3,
    max_endpoints integer not null default 2,
    max_assets    integer not null default 500,
    is_active     boolean not null default true
);

create table if not exists subscriptions (
    id         serial primary key,
    tenant_id  integer not null unique references tenants(id),
    plan_id    integer not null references plans(id),
    status     varchar(20) not null default 'active',  -- active | past_due | canceled
    started_at timestamptz not null default now()
);

create table if not exists payments (
    id           serial primary key,
    tenant_id    integer not null references tenants(id),
    plan_id      integer references plans(id),
    amount       double precision not null default 0,
    currency     varchar(10) not null default 'USD',
    status       varchar(20) not null default 'succeeded',
    provider_ref varchar(80) not null default ('pay_' || encode(gen_random_bytes(18), 'hex')),
    created_at   timestamptz not null default now()
);

create table if not exists payment_gateway_config (
    id              serial primary key,
    provider        varchar(40)  not null default 'stripe',
    mode            varchar(20)  not null default 'test',  -- test | live
    publishable_key varchar(255) not null default '',
    secret_key      varchar(255) not null default '',
    webhook_secret  varchar(255) not null default '',
    updated_at      timestamptz  not null default now()
);

create table if not exists classification_labels (
    id          serial primary key,
    tenant_id   integer not null references tenants(id),
    name        varchar(60) not null,
    level       integer not null default 0,         -- higher = more sensitive
    color       varchar(20) not null default '#6b7280',
    description varchar(255) not null default ''
);

create table if not exists classification_rules (
    id        serial primary key,
    tenant_id integer not null references tenants(id),
    name      varchar(120) not null,
    rule_type varchar(20) not null default 'keyword',  -- keyword | regex
    pattern   text not null,
    label_id  integer not null references classification_labels(id),
    priority  integer not null default 100,
    enabled   boolean not null default true
);

create table if not exists agent_builds (
    id               serial primary key,
    tenant_id        integer not null references tenants(id),
    platform         varchar(20) not null,            -- macos | windows
    version          varchar(20) not null default '1.0.0',
    enrollment_token varchar(80) unique not null default ('enroll_' || encode(gen_random_bytes(18), 'hex')),
    created_by       integer references users(id),
    created_at       timestamptz not null default now(),
    downloads        integer not null default 0
);

create table if not exists endpoints (
    id          serial primary key,
    tenant_id   integer not null references tenants(id),
    hostname    varchar(255) not null default '',
    platform    varchar(20)  not null default 'unknown',  -- macos | windows
    api_key     varchar(80) unique not null default ('ep_' || encode(gen_random_bytes(18), 'hex')),
    status      varchar(20)  not null default 'enrolled',
    enrolled_at timestamptz  not null default now(),
    last_seen   timestamptz,
    build_id    integer references agent_builds(id)
);

create table if not exists assets (
    id              serial primary key,
    tenant_id       integer not null references tenants(id),
    name            varchar(255) not null,
    asset_type      varchar(60) not null default 'document',
    content_excerpt text not null default '',
    label_id        integer references classification_labels(id),
    matched_rules   text not null default '',
    source          varchar(20) not null default 'manual',  -- manual | csv | agent
    endpoint_id     integer references endpoints(id),
    classified_at   timestamptz not null default now()
);

create table if not exists watermark_config (
    id                  serial primary key,
    tenant_id           integer not null unique references tenants(id),
    enabled             boolean not null default true,
    opacity             double precision not null default 0.15,
    font_size           integer not null default 18,
    placement           varchar(20) not null default 'tiled',
    show_timestamp      boolean not null default true,
    show_classification boolean not null default true
);

create table if not exists api_keys (
    id         serial primary key,
    tenant_id  integer not null references tenants(id),
    name       varchar(120) not null,
    key_prefix varchar(20)  not null,
    key_hash   varchar(64)  not null unique,
    created_by integer references users(id),
    created_at timestamptz  not null default now(),
    last_used  timestamptz,
    revoked    boolean      not null default false
);

create index if not exists ix_api_keys_tenant on api_keys(tenant_id);

create table if not exists contact_messages (
    id         serial primary key,
    name       varchar(120) not null,
    email      varchar(255) not null,
    company    varchar(120) not null default '',
    topic      varchar(60)  not null default 'General question',
    message    text not null,
    status     varchar(20)  not null default 'new',  -- new | replied
    created_at timestamptz  not null default now()
);

create table if not exists audit_logs (
    id         serial primary key,
    tenant_id  integer references tenants(id),
    user_id    integer references users(id),
    action     varchar(120) not null,
    detail     text not null default '',
    created_at timestamptz not null default now()
);

-- Indexes for the tenant-scoped hot paths
create index if not exists ix_users_tenant      on users(tenant_id);
create index if not exists ix_labels_tenant     on classification_labels(tenant_id);
create index if not exists ix_rules_tenant      on classification_rules(tenant_id);
create index if not exists ix_assets_tenant     on assets(tenant_id);
create index if not exists ix_assets_classified on assets(tenant_id, classified_at desc);
create index if not exists ix_endpoints_tenant  on endpoints(tenant_id);
create index if not exists ix_builds_tenant     on agent_builds(tenant_id);
create index if not exists ix_payments_tenant   on payments(tenant_id);
create index if not exists ix_audit_tenant      on audit_logs(tenant_id);

-- ============================================================
-- Seed data: subscription plans + platform owner account
-- Owner login: owner@classifyhub.app / owner-admin-123
-- (change the password after first login or seed your own hash)
-- ============================================================

insert into plans (name, price_monthly, max_users, max_endpoints, max_assets) values
    ('Free',         0,  3,    2,    500),
    ('Pro',         49,  25,   50,   50000),
    ('Enterprise', 199,  1000, 1000, 1000000)
on conflict (name) do nothing;

insert into users (tenant_id, email, full_name, password_hash, role)
values (
    null,
    'owner@classifyhub.app',
    'Platform Owner',
    '$2b$12$tp43O65Ma1pkDKZd80Bbr.XIy4iS8Zp65TzDrE1nuiJByVnnm2k7m',
    'owner'
)
on conflict (email) do nothing;
