from __future__ import annotations

import io

import pytest
from openpyxl import Workbook

from funding_terminal.config import Settings
from funding_terminal.domain.errors import ImportValidationError
from funding_terminal.services.import_service import ImportFileParser, normalize_symbol


def test_normalize_base_asset() -> None:
    assert normalize_symbol(" btc ") == ("BTC", None)
    assert normalize_symbol('"eth"') == ("ETH", None)


def test_normalize_usdt_pair_to_base_asset() -> None:
    assert normalize_symbol("BTCUSDT") == ("BTC", None)


def test_rejects_non_usdt_pair() -> None:
    assert normalize_symbol("ETHBTC") == (
        "ETHBTC",
        "Only BASE or BASEUSDT inputs are accepted in Stage 1.",
    )
    assert normalize_symbol("BTCUSDC") == (
        "BTCUSDC",
        "Only BASE or BASEUSDT inputs are accepted in Stage 1.",
    )


def test_csv_valid_dedupe_lowercase_and_blank_rows() -> None:
    parser = ImportFileParser(Settings(database_url="postgresql://example"))
    parsed = parser.parse("universe.csv", b"Symbol,Enabled\nbtc,1\n\nETHUSDT,0\nBTC,1\n")
    assert parsed.total_rows == 3
    assert [asset.base_asset for asset in parsed.assets] == ["BTC", "ETH"]
    assert parsed.assets[1].enabled is False
    assert parsed.duplicate_count == 1


def test_csv_missing_symbol_column() -> None:
    parser = ImportFileParser(Settings(database_url="postgresql://example"))
    with pytest.raises(ImportValidationError):
        parser.parse("universe.csv", b"Ticker\nBTC\n")


def test_too_many_rows() -> None:
    parser = ImportFileParser(Settings(database_url="postgresql://example", import_max_rows=1))
    with pytest.raises(ImportValidationError):
        parser.parse("universe.csv", b"Symbol\nBTC\nETH\n")


def test_xlsx_valid() -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Symbol", "Enabled"])
    sheet.append(["SOLUSDT", 1])
    buffer = io.BytesIO()
    workbook.save(buffer)

    parser = ImportFileParser(Settings(database_url="postgresql://example"))
    parsed = parser.parse("universe.xlsx", buffer.getvalue())

    assert parsed.file_type == "XLSX"
    assert parsed.assets[0].base_asset == "SOL"
