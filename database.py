# database.py
"""
Database connection and operations module
"""
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timezone
from typing import Dict, List, Optional
import logging

from config import QUESTDB_CONFIG
from models import Trade, Ticker, QUESTDB_SCHEMAS

logger = logging.getLogger(__name__)

class QuestDBClient:
    """Manages QuestDB connections and operations"""
    
    def __init__(self):
        self.conn = None
        self.cursor = None
    
    def connect(self):
        """Establish connection to QuestDB"""
        try:
            self.conn = psycopg2.connect(**QUESTDB_CONFIG)
            self.cursor = self.conn.cursor()
            logger.info("Connected to QuestDB successfully")
        except Exception as e:
            logger.error(f"Failed to connect to QuestDB: {e}")
            raise
    
    def create_tables(self):
        """Create all required tables"""
        try:
            for table_name, schema in QUESTDB_SCHEMAS.items():
                self.cursor.execute(schema)
                logger.info(f"Created/verified table: {table_name}")
            self.conn.commit()
        except Exception as e:
            logger.error(f"Failed to create tables: {e}")
            raise
    
    def insert_ticker(self, ticker: Ticker):
        """Insert ticker data"""
        try:
            spread = ticker.best_ask - ticker.best_bid
            timestamp = ticker.time.replace(tzinfo=None) if ticker.time.tzinfo else ticker.time
            
            query = """
                INSERT INTO coinbase_ticker 
                (symbol, best_bid, best_ask, last_price, spread, volume_24h, timestamp) 
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """
            self.cursor.execute(query, (
                ticker.symbol, ticker.best_bid, ticker.best_ask, 
                ticker.last_price, spread, ticker.volume_24h, timestamp
            ))
            self.conn.commit()
        except Exception as e:
            logger.error(f"Failed to insert ticker: {e}")
            self.conn.rollback()
    
    def insert_trade(self, trade: Trade):
        """Insert trade data"""
        try:
            timestamp = trade.time.replace(tzinfo=None) if trade.time.tzinfo else trade.time
            
            query = """
                INSERT INTO coinbase_trades 
                (symbol, price, size, side, trade_id, timestamp) 
                VALUES (%s, %s, %s, %s, %s, %s)
            """
            self.cursor.execute(query, (
                trade.symbol, trade.price, trade.size, 
                trade.side, trade.trade_id, timestamp
            ))
            self.conn.commit()
        except Exception as e:
            logger.error(f"Failed to insert trade: {e}")
            self.conn.rollback()
    
    def generate_candles(self):
        """Generate 1-minute candles from ticker data"""
        try:
            # First, create a temporary view to avoid duplicates
            query = """
                INSERT INTO coinbase_candles (symbol, open, high, low, close, volume, trade_count, timestamp)
                SELECT 
                    symbol,
                    first(last_price) as open,
                    max(last_price) as high,
                    min(last_price) as low,
                    last(last_price) as close,
                    avg(volume_24h) as volume,
                    count(*) as trade_count,
                    date_trunc('minute', timestamp) as timestamp
                FROM coinbase_ticker
                WHERE timestamp >= dateadd('h', -2, now())
                    AND date_trunc('minute', timestamp) NOT IN (
                        SELECT DISTINCT timestamp FROM coinbase_candles 
                        WHERE timestamp >= dateadd('h', -2, now())
                    )
                GROUP BY symbol, date_trunc('minute', timestamp)
            """
            self.cursor.execute(query)
            self.conn.commit()
            rows = self.cursor.rowcount
            if rows > 0:
                logger.info(f"Generated {rows} candle records")
        except Exception as e:
            logger.error(f"Failed to generate candles: {e}")
            self.conn.rollback()
    
    def get_latest_prices(self) -> Dict[str, float]:
        """Get latest prices for all symbols"""
        try:
            query = """
                SELECT symbol, last(last_price) as price
                FROM coinbase_ticker 
                WHERE timestamp > dateadd('m', -5, now())
                GROUP BY symbol
            """
            self.cursor.execute(query)
            return {row[0]: row[1] for row in self.cursor.fetchall()}
        except Exception as e:
            logger.error(f"Error getting latest prices: {e}")
            return {}
    
    def get_market_stats(self) -> List[Dict]:
        """Get comprehensive market statistics"""
        try:
            query = """
                WITH current_data AS (
                    SELECT 
                        symbol,
                        last(last_price) as current_price,
                        last(volume_24h) as volume_24h
                    FROM coinbase_ticker
                    WHERE timestamp > dateadd('m', -5, now())
                    GROUP BY symbol
                ),
                hour_ago AS (
                    SELECT 
                        symbol,
                        first(last_price) as price_1h_ago
                    FROM coinbase_ticker
                    WHERE timestamp BETWEEN dateadd('m', -65, now()) 
                        AND dateadd('h', -1, now())
                    GROUP BY symbol
                ),
                day_ago AS (
                    SELECT 
                        symbol,
                        first(last_price) as price_24h_ago
                    FROM coinbase_ticker
                    WHERE timestamp BETWEEN dateadd('m', -1445, now()) 
                        AND dateadd('h', -24, now())
                    GROUP BY symbol
                ),
                day_stats AS (
                    SELECT 
                        symbol,
                        max(last_price) as high_24h,
                        min(last_price) as low_24h
                    FROM coinbase_ticker
                    WHERE timestamp > dateadd('h', -24, now())
                    GROUP BY symbol
                ),
                trade_counts AS (
                    SELECT 
                        symbol,
                        count(*) as trades_count
                    FROM coinbase_trades
                    WHERE timestamp > dateadd('h', -24, now())
                    GROUP BY symbol
                )
                SELECT 
                    c.symbol,
                    c.current_price,
                    COALESCE(((c.current_price - h.price_1h_ago) / h.price_1h_ago * 100), 0) as change_1h,
                    COALESCE(((c.current_price - d.price_24h_ago) / d.price_24h_ago * 100), 0) as change_24h,
                    c.volume_24h,
                    COALESCE(ds.high_24h, c.current_price) as high_24h,
                    COALESCE(ds.low_24h, c.current_price) as low_24h,
                    COALESCE(tc.trades_count, 0) as trades_count
                FROM current_data c
                LEFT JOIN hour_ago h ON c.symbol = h.symbol
                LEFT JOIN day_ago d ON c.symbol = d.symbol
                LEFT JOIN day_stats ds ON c.symbol = ds.symbol
                LEFT JOIN trade_counts tc ON c.symbol = tc.symbol
                ORDER BY c.volume_24h DESC
            """
            
            self.cursor.execute(query)
            columns = [desc[0] for desc in self.cursor.description]
            return [dict(zip(columns, row)) for row in self.cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting market stats: {e}")
            return []
    
    def get_recent_candles(self, symbol: str, limit: int = 60) -> List[Dict]:
        """Get recent candles for a symbol"""
        try:
            query = """
                SELECT 
                    timestamp as time,
                    open, high, low, close, volume
                FROM coinbase_candles
                WHERE symbol = %s
                ORDER BY timestamp DESC
                LIMIT %s
            """
            self.cursor.execute(query, (symbol, limit))
            columns = [desc[0] for desc in self.cursor.description]
            return [dict(zip(columns, row)) for row in self.cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting candles: {e}")
            return []
    
    def close(self):
        """Close database connections"""
        if self.cursor:
            self.cursor.close()
        if self.conn:
            self.conn.close()
        logger.info("QuestDB connection closed")