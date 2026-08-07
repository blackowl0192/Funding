ALTER TABLE trading_settings
    ADD COLUMN IF NOT EXISTS spot_budget NUMERIC(38,18),
    ADD COLUMN IF NOT EXISTS futures_margin_budget NUMERIC(38,18),
    ADD COLUMN IF NOT EXISTS futures_leverage INTEGER,
    ADD COLUMN IF NOT EXISTS spot_maker_base_fee NUMERIC(38,18),
    ADD COLUMN IF NOT EXISTS spot_taker_base_fee NUMERIC(38,18),
    ADD COLUMN IF NOT EXISTS futures_maker_base_fee NUMERIC(38,18),
    ADD COLUMN IF NOT EXISTS futures_taker_base_fee NUMERIC(38,18),
    ADD COLUMN IF NOT EXISTS fee_discount_rate NUMERIC(38,18);

DO $$
DECLARE
    has_legacy_fee_columns BOOLEAN;
BEGIN
    SELECT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'trading_settings'
          AND column_name = 'spot_maker_fee'
    )
    INTO has_legacy_fee_columns;

    IF has_legacy_fee_columns THEN
        UPDATE trading_settings
        SET
            spot_budget = COALESCE(
                spot_budget,
                CASE
                    WHEN total_capital >= 4000 THEN 2000
                    ELSE total_capital / 2
                END
            ),
            futures_margin_budget = COALESCE(
                futures_margin_budget,
                CASE
                    WHEN total_capital >= 4000 THEN 2000
                    ELSE total_capital - (total_capital / 2)
                END
            ),
            futures_leverage = COALESCE(futures_leverage, 1),
            fee_discount_rate = COALESCE(fee_discount_rate, 0.45),
            spot_maker_base_fee = COALESCE(
                spot_maker_base_fee,
                COALESCE(spot_maker_fee, 0.00055) / 0.55
            ),
            spot_taker_base_fee = COALESCE(
                spot_taker_base_fee,
                COALESCE(spot_taker_fee, 0.00055) / 0.55
            ),
            futures_maker_base_fee = COALESCE(
                futures_maker_base_fee,
                COALESCE(futures_maker_fee, 0.00011) / 0.55
            ),
            futures_taker_base_fee = COALESCE(
                futures_taker_base_fee,
                COALESCE(futures_taker_fee, 0.000275) / 0.55
            ),
            updated_at = NOW();
    ELSE
        UPDATE trading_settings
        SET
            spot_budget = COALESCE(
                spot_budget,
                CASE
                    WHEN total_capital >= 4000 THEN 2000
                    ELSE total_capital / 2
                END
            ),
            futures_margin_budget = COALESCE(
                futures_margin_budget,
                CASE
                    WHEN total_capital >= 4000 THEN 2000
                    ELSE total_capital - (total_capital / 2)
                END
            ),
            futures_leverage = COALESCE(futures_leverage, 1),
            fee_discount_rate = COALESCE(fee_discount_rate, 0.45),
            spot_maker_base_fee = COALESCE(spot_maker_base_fee, 0.001),
            spot_taker_base_fee = COALESCE(spot_taker_base_fee, 0.001),
            futures_maker_base_fee = COALESCE(futures_maker_base_fee, 0.0002),
            futures_taker_base_fee = COALESCE(futures_taker_base_fee, 0.0005),
            updated_at = NOW();
    END IF;
END $$;

ALTER TABLE trading_settings
    ALTER COLUMN spot_budget SET DEFAULT 2000,
    ALTER COLUMN futures_margin_budget SET DEFAULT 2000,
    ALTER COLUMN futures_leverage SET DEFAULT 1,
    ALTER COLUMN spot_maker_base_fee SET DEFAULT 0.001,
    ALTER COLUMN spot_taker_base_fee SET DEFAULT 0.001,
    ALTER COLUMN futures_maker_base_fee SET DEFAULT 0.0002,
    ALTER COLUMN futures_taker_base_fee SET DEFAULT 0.0005,
    ALTER COLUMN fee_discount_rate SET DEFAULT 0.45,
    ALTER COLUMN spot_budget SET NOT NULL,
    ALTER COLUMN futures_margin_budget SET NOT NULL,
    ALTER COLUMN futures_leverage SET NOT NULL,
    ALTER COLUMN spot_maker_base_fee SET NOT NULL,
    ALTER COLUMN spot_taker_base_fee SET NOT NULL,
    ALTER COLUMN futures_maker_base_fee SET NOT NULL,
    ALTER COLUMN futures_taker_base_fee SET NOT NULL,
    ALTER COLUMN fee_discount_rate SET NOT NULL;

ALTER TABLE trading_settings
    DROP COLUMN IF EXISTS spot_maker_fee,
    DROP COLUMN IF EXISTS spot_taker_fee,
    DROP COLUMN IF EXISTS futures_maker_fee,
    DROP COLUMN IF EXISTS futures_taker_fee;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'trading_settings_capital_positive'
    ) THEN
        ALTER TABLE trading_settings
            ADD CONSTRAINT trading_settings_capital_positive
            CHECK (total_capital > 0);
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'trading_settings_budget_non_negative'
    ) THEN
        ALTER TABLE trading_settings
            ADD CONSTRAINT trading_settings_budget_non_negative
            CHECK (spot_budget >= 0 AND futures_margin_budget >= 0);
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'trading_settings_budget_within_total'
    ) THEN
        ALTER TABLE trading_settings
            ADD CONSTRAINT trading_settings_budget_within_total
            CHECK (spot_budget + futures_margin_budget <= total_capital);
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'trading_settings_futures_leverage_allowed'
    ) THEN
        ALTER TABLE trading_settings
            ADD CONSTRAINT trading_settings_futures_leverage_allowed
            CHECK (futures_leverage IN (1, 2));
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'trading_settings_quote_asset_usdt'
    ) THEN
        ALTER TABLE trading_settings
            ADD CONSTRAINT trading_settings_quote_asset_usdt
            CHECK (quote_asset = 'USDT');
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'trading_settings_base_fees_valid'
    ) THEN
        ALTER TABLE trading_settings
            ADD CONSTRAINT trading_settings_base_fees_valid
            CHECK (
                spot_maker_base_fee >= 0
                AND spot_maker_base_fee < 1
                AND spot_taker_base_fee >= 0
                AND spot_taker_base_fee < 1
                AND futures_maker_base_fee >= 0
                AND futures_maker_base_fee < 1
                AND futures_taker_base_fee >= 0
                AND futures_taker_base_fee < 1
            );
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'trading_settings_fee_discount_valid'
    ) THEN
        ALTER TABLE trading_settings
            ADD CONSTRAINT trading_settings_fee_discount_valid
            CHECK (fee_discount_rate >= 0 AND fee_discount_rate < 1);
    END IF;
END $$;
