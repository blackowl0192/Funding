from funding_terminal.exchange.binance.parser import (
    parse_futures_exchange_info,
    parse_spot_exchange_info,
)


def test_parse_active_spot() -> None:
    instruments = parse_spot_exchange_info(
        {
            "symbols": [
                {
                    "symbol": "BTCUSDT",
                    "status": "TRADING",
                    "baseAsset": "BTC",
                    "quoteAsset": "USDT",
                    "isSpotTradingAllowed": True,
                }
            ]
        }
    )
    assert instruments["BTCUSDT"].is_active is True


def test_parse_inactive_spot() -> None:
    instruments = parse_spot_exchange_info(
        {
            "symbols": [
                {
                    "symbol": "BTCUSDT",
                    "status": "HALT",
                    "baseAsset": "BTC",
                    "quoteAsset": "USDT",
                    "isSpotTradingAllowed": True,
                }
            ]
        }
    )
    assert instruments["BTCUSDT"].is_active is False


def test_parse_active_perpetual() -> None:
    instruments = parse_futures_exchange_info(
        {
            "symbols": [
                {
                    "symbol": "ETHUSDT",
                    "pair": "ETHUSDT",
                    "status": "TRADING",
                    "baseAsset": "ETH",
                    "quoteAsset": "USDT",
                    "marginAsset": "USDT",
                    "contractType": "PERPETUAL",
                }
            ]
        }
    )
    assert instruments["ETHUSDT"].is_active_perpetual_usdt is True


def test_delivery_futures_rejected_by_model_property() -> None:
    instruments = parse_futures_exchange_info(
        {
            "symbols": [
                {
                    "symbol": "ETHUSDT",
                    "pair": "ETHUSDT",
                    "status": "TRADING",
                    "baseAsset": "ETH",
                    "quoteAsset": "USDT",
                    "marginAsset": "USDT",
                    "contractType": "CURRENT_QUARTER",
                }
            ]
        }
    )
    assert instruments["ETHUSDT"].is_active_perpetual_usdt is False


def test_wrong_quote_rejected_by_model_property() -> None:
    instruments = parse_futures_exchange_info(
        {
            "symbols": [
                {
                    "symbol": "ETHBTC",
                    "pair": "ETHBTC",
                    "status": "TRADING",
                    "baseAsset": "ETH",
                    "quoteAsset": "BTC",
                    "marginAsset": "BTC",
                    "contractType": "PERPETUAL",
                }
            ]
        }
    )
    assert instruments["ETHBTC"].is_active_perpetual_usdt is False

