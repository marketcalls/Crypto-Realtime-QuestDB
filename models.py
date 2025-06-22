# models.py
"""
Data models and database schema definitions
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

@dataclass
class Trade:
    """Represents a single trade execution"""
    symbol: str
    price: float
    size: float
    side: str
    time: datetime
    trade_id: int

@dataclass
class Ticker:
    """Represents ticker/quote data"""
    symbol: str
    best_bid: float
    best_ask: float
    last_price: float
    volume_24h: float
    time: datetime

@dataclass
class Candle:
    """Represents OHLCV candle data"""
    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    trade_count: int
    timestamp: datetime

@dataclass
class MarketStats:
    """Market statistics for dashboard"""
    symbol: str
    current_price: float
    change_1h: float
    change_24h: float
    volume_24h: float
    high_24h: float
    low_24h: float
    trades_count: int

# QuestDB Table Schemas
QUESTDB_SCHEMAS = {
    "coinbase_trades": """
        CREATE TABLE IF NOT EXISTS coinbase_trades (
            symbol SYMBOL,
            price DOUBLE,
            size DOUBLE,
            side SYMBOL,
            trade_id LONG,
            timestamp TIMESTAMP
        ) timestamp(timestamp) PARTITION BY DAY;
    """,
    
    "coinbase_ticker": """
        CREATE TABLE IF NOT EXISTS coinbase_ticker (
            symbol SYMBOL,
            best_bid DOUBLE,
            best_ask DOUBLE,
            last_price DOUBLE,
            spread DOUBLE,
            volume_24h DOUBLE,
            timestamp TIMESTAMP
        ) timestamp(timestamp) PARTITION BY DAY;
    """,
    
    "coinbase_candles": """
        CREATE TABLE IF NOT EXISTS coinbase_candles (
            symbol SYMBOL,
            open DOUBLE,
            high DOUBLE,
            low DOUBLE,
            close DOUBLE,
            volume DOUBLE,
            trade_count LONG,
            timestamp TIMESTAMP
        ) timestamp(timestamp) PARTITION BY DAY;
    """,
    
    "coinbase_spot_prices": """
        CREATE TABLE IF NOT EXISTS coinbase_spot_prices (
            base SYMBOL,
            currency SYMBOL,
            amount DOUBLE,
            timestamp TIMESTAMP
        ) timestamp(timestamp) PARTITION BY DAY;
    """
}