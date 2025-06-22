# config.py
"""
Configuration settings for the Crypto Analytics System
"""

# QuestDB Configuration
QUESTDB_CONFIG = {
    "host": "localhost",
    "port": 8812,
    "user": "admin",
    "password": "quest",
    "database": "qdb"
}

# Coinbase API Configuration
COINBASE_REST_URL = "https://api.coinbase.com/v2"
COINBASE_WS_URL = "wss://ws-feed.exchange.coinbase.com"

# Supported trading pairs
TRADING_PAIRS = [
    "BTC-USD", "ETH-USD", "SOL-USD", "LINK-USD", 
    "MATIC-USD", "AVAX-USD", "DOT-USD", "ADA-USD"
]

# Data ingestion settings
CANDLE_GENERATION_INTERVAL = 30  # seconds
SPOT_PRICE_FETCH_INTERVAL = 10  # seconds
WEBSOCKET_RECONNECT_DELAY = 5  # seconds

# Logging configuration
LOG_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"