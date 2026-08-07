from funding_terminal.__main__ import format_status_lines
from funding_terminal.domain.models import DashboardStats
from funding_terminal.services.settings_service import DEFAULT_TRADING_SETTINGS


def test_status_prints_capital_and_fee_breakdown() -> None:
    settings = DEFAULT_TRADING_SETTINGS
    stats = DashboardStats(
        total_symbols=3,
        eligible_symbols=2,
        enabled_symbols=2,
        rejected_symbols=1,
        last_import_at=None,
        settings=settings,
    )

    output = "\n".join(format_status_lines(stats, settings, True, True, True))

    assert "capital:" in output
    assert "  total: 4000 USDT" in output
    assert "  spot_budget: 2000 USDT" in output
    assert "  futures_margin_budget: 2000 USDT" in output
    assert "  futures_capacity: 2000 USDT" in output
    assert "  max_hedged_notional: 2000 USDT" in output
    assert "fees:" in output
    assert "  discount: 45%" in output
    assert "  spot_maker_base: 0.1%" in output
    assert "  spot_maker_effective: 0.055%" in output
    assert "  futures_taker_base: 0.05%" in output
    assert "  futures_taker_effective: 0.0275%" in output
