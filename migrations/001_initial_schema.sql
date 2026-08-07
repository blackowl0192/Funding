CREATE TABLE IF NOT EXISTS symbols (
    id BIGSERIAL PRIMARY KEY,
    base_asset TEXT NOT NULL,
    spot_symbol TEXT,
    futures_symbol TEXT,
    spot_status TEXT,
    futures_status TEXT,
    mapping_status TEXT NOT NULL CHECK (
        mapping_status IN (
            'MATCHED',
            'SPOT_MISSING',
            'FUTURES_MISSING',
            'SPOT_INACTIVE',
            'FUTURES_INACTIVE',
            'UNSUPPORTED_SPOT',
            'UNSUPPORTED_FUTURES',
            'METADATA_MISMATCH',
            'INVALID_INPUT',
            'ERROR'
        )
    ),
    mapping_reason TEXT,
    strategy_eligible BOOLEAN NOT NULL DEFAULT FALSE,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    exchange TEXT NOT NULL DEFAULT 'BINANCE',
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_checked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(exchange, base_asset)
);

CREATE INDEX IF NOT EXISTS idx_symbols_exchange_enabled ON symbols(exchange, enabled);
CREATE INDEX IF NOT EXISTS idx_symbols_strategy_eligible ON symbols(strategy_eligible);
CREATE INDEX IF NOT EXISTS idx_symbols_mapping_status ON symbols(mapping_status);

CREATE TABLE IF NOT EXISTS import_runs (
    id BIGSERIAL PRIMARY KEY,
    filename TEXT,
    file_type TEXT,
    total_rows INTEGER,
    unique_assets INTEGER,
    matched_count INTEGER,
    rejected_count INTEGER,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    status TEXT NOT NULL CHECK (status IN ('COMPLETED', 'FAILED')),
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS trading_settings (
    id SMALLINT PRIMARY KEY CHECK (id = 1),
    total_capital NUMERIC(38,18) NOT NULL,
    quote_asset TEXT NOT NULL DEFAULT 'USDT',
    spot_maker_fee NUMERIC(38,18) NOT NULL,
    spot_taker_fee NUMERIC(38,18) NOT NULL,
    futures_maker_fee NUMERIC(38,18) NOT NULL,
    futures_taker_fee NUMERIC(38,18) NOT NULL,
    default_execution_mode TEXT NOT NULL CHECK (
        default_execution_mode IN ('MAKER', 'TAKER', 'MIXED')
    ),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO trading_settings (
    id,
    total_capital,
    quote_asset,
    spot_maker_fee,
    spot_taker_fee,
    futures_maker_fee,
    futures_taker_fee,
    default_execution_mode
)
VALUES (
    1,
    4000,
    'USDT',
    0.00055,
    0.00055,
    0.00011,
    0.000275,
    'MAKER'
)
ON CONFLICT (id) DO NOTHING;

