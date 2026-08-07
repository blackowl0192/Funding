CREATE TABLE IF NOT EXISTS funding_events (
    id BIGSERIAL PRIMARY KEY,
    symbol_id BIGINT NOT NULL
        REFERENCES symbols(id)
        ON DELETE CASCADE,
    futures_symbol TEXT NOT NULL,
    funding_time TIMESTAMPTZ NOT NULL,
    funding_rate NUMERIC(38,18) NOT NULL,
    mark_price NUMERIC(38,18),
    source TEXT NOT NULL DEFAULT 'BINANCE',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(source, futures_symbol, funding_time)
);

CREATE INDEX IF NOT EXISTS idx_funding_events_symbol_time
    ON funding_events(symbol_id, funding_time DESC);
CREATE INDEX IF NOT EXISTS idx_funding_events_futures_symbol_time
    ON funding_events(futures_symbol, funding_time DESC);
CREATE INDEX IF NOT EXISTS idx_funding_events_time
    ON funding_events(funding_time DESC);

CREATE TABLE IF NOT EXISTS funding_current (
    symbol_id BIGINT PRIMARY KEY
        REFERENCES symbols(id)
        ON DELETE CASCADE,
    futures_symbol TEXT NOT NULL,
    mark_price NUMERIC(38,18),
    index_price NUMERIC(38,18),
    last_funding_rate NUMERIC(38,18),
    next_funding_time TIMESTAMPTZ,
    interest_rate NUMERIC(38,18),
    funding_interval_hours NUMERIC(18,8),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_funding_current_futures_symbol
    ON funding_current(futures_symbol);
CREATE INDEX IF NOT EXISTS idx_funding_current_updated_at
    ON funding_current(updated_at DESC);

CREATE TABLE IF NOT EXISTS funding_statistics (
    id BIGSERIAL PRIMARY KEY,
    symbol_id BIGINT NOT NULL
        REFERENCES symbols(id)
        ON DELETE CASCADE,
    window_days INTEGER NOT NULL CHECK (window_days IN (7, 14, 30)),
    calculated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    event_count INTEGER NOT NULL DEFAULT 0,
    first_event_at TIMESTAMPTZ,
    last_event_at TIMESTAMPTZ,
    mean_rate NUMERIC(38,18) NOT NULL DEFAULT 0,
    median_rate NUMERIC(38,18) NOT NULL DEFAULT 0,
    min_rate NUMERIC(38,18) NOT NULL DEFAULT 0,
    max_rate NUMERIC(38,18) NOT NULL DEFAULT 0,
    stddev_rate NUMERIC(38,18) NOT NULL DEFAULT 0,
    cumulative_rate NUMERIC(38,18) NOT NULL DEFAULT 0,
    positive_count INTEGER NOT NULL DEFAULT 0,
    negative_count INTEGER NOT NULL DEFAULT 0,
    zero_count INTEGER NOT NULL DEFAULT 0,
    positive_ratio NUMERIC(38,18) NOT NULL DEFAULT 0,
    negative_ratio NUMERIC(38,18) NOT NULL DEFAULT 0,
    current_positive_streak INTEGER NOT NULL DEFAULT 0,
    longest_positive_streak INTEGER NOT NULL DEFAULT 0,
    current_negative_streak INTEGER NOT NULL DEFAULT 0,
    longest_negative_streak INTEGER NOT NULL DEFAULT 0,
    average_positive_rate NUMERIC(38,18) NOT NULL DEFAULT 0,
    average_negative_rate NUMERIC(38,18) NOT NULL DEFAULT 0,
    funding_interval_hours NUMERIC(18,8),
    estimated_events_per_day NUMERIC(18,8) NOT NULL DEFAULT 0,
    estimated_daily_rate NUMERIC(38,18) NOT NULL DEFAULT 0,
    estimated_30d_rate NUMERIC(38,18) NOT NULL DEFAULT 0,
    negative_events_last_24h INTEGER NOT NULL DEFAULT 0,
    negative_events_last_3d INTEGER NOT NULL DEFAULT 0,
    stability_score NUMERIC(8,4) NOT NULL DEFAULT 0,
    trend TEXT NOT NULL DEFAULT 'UNKNOWN' CHECK (
        trend IN ('IMPROVING', 'STABLE', 'DETERIORATING', 'UNKNOWN')
    ),
    reversal_warning BOOLEAN NOT NULL DEFAULT FALSE,
    data_quality TEXT NOT NULL DEFAULT 'INSUFFICIENT' CHECK (
        data_quality IN ('GOOD', 'PARTIAL', 'INSUFFICIENT', 'STALE')
    ),
    UNIQUE(symbol_id, window_days)
);

CREATE INDEX IF NOT EXISTS idx_funding_statistics_window_score
    ON funding_statistics(window_days, stability_score DESC);
CREATE INDEX IF NOT EXISTS idx_funding_statistics_symbol_window
    ON funding_statistics(symbol_id, window_days);
CREATE INDEX IF NOT EXISTS idx_funding_statistics_quality
    ON funding_statistics(data_quality);

CREATE TABLE IF NOT EXISTS funding_sync_state (
    symbol_id BIGINT PRIMARY KEY
        REFERENCES symbols(id)
        ON DELETE CASCADE,
    history_synced_at TIMESTAMPTZ,
    history_start_at TIMESTAMPTZ,
    history_end_at TIMESTAMPTZ,
    last_success_at TIMESTAMPTZ,
    last_error_at TIMESTAMPTZ,
    last_error TEXT,
    events_synced INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_funding_sync_state_history_synced_at
    ON funding_sync_state(history_synced_at DESC);
CREATE INDEX IF NOT EXISTS idx_funding_sync_state_last_error_at
    ON funding_sync_state(last_error_at DESC);
