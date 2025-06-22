import asyncio
import aiohttp
import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from contextlib import asynccontextmanager
import psycopg2
from psycopg2.extras import execute_values
import websockets
import logging
from dataclasses import dataclass
from enum import Enum

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# QuestDB connection parameters
QUESTDB_HOST = "localhost"
QUESTDB_PORT = 8812
QUESTDB_USER = "admin"
QUESTDB_PASSWORD = "quest"
QUESTDB_DATABASE = "qdb"

# Coinbase API endpoints
COINBASE_REST_URL = "https://api.coinbase.com/v2"
COINBASE_WS_URL = "wss://ws-feed.exchange.coinbase.com"

# Supported trading pairs
TRADING_PAIRS = [
    "BTC-USD", "ETH-USD", "SOL-USD", "LINK-USD", 
    "MATIC-USD", "AVAX-USD", "DOT-USD", "ADA-USD"
]

@dataclass
class Trade:
    symbol: str
    price: float
    size: float
    side: str
    time: datetime
    trade_id: int

@dataclass
class Ticker:
    symbol: str
    best_bid: float
    best_ask: float
    last_price: float
    volume_24h: float
    time: datetime

class CoinbaseDataIngestion:
    def __init__(self):
        self.conn = None
        self.cursor = None
        self.running = False
        self.websocket_task = None
        self.rest_api_task = None
        self.connected_clients = set()
    
    def parse_coinbase_time(self, time_str: str) -> datetime:
        """Parse Coinbase timestamp and return naive UTC datetime"""
        # Coinbase returns timestamps like: 2025-06-22T13:48:39.499077Z
        if time_str.endswith('Z'):
            # Parse ISO format with Z suffix
            dt = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
        else:
            dt = datetime.fromisoformat(time_str)
        
        # Convert to naive UTC datetime for QuestDB
        return dt.replace(tzinfo=None) if dt.tzinfo else dt
        
    def connect_questdb(self):
        """Connect to QuestDB using PostgreSQL wire protocol"""
        try:
            self.conn = psycopg2.connect(
                host=QUESTDB_HOST,
                port=QUESTDB_PORT,
                user=QUESTDB_USER,
                password=QUESTDB_PASSWORD,
                database=QUESTDB_DATABASE
            )
            self.cursor = self.conn.cursor()
            logger.info("Connected to QuestDB successfully")
        except Exception as e:
            logger.error(f"Failed to connect to QuestDB: {e}")
            raise
        
    def create_tables(self):
        """Create tables for crypto data"""
        try:
            # Table for real-time trades
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS coinbase_trades (
                    symbol SYMBOL,
                    price DOUBLE,
                    size DOUBLE,
                    side SYMBOL,
                    trade_id LONG,
                    timestamp TIMESTAMP
                ) timestamp(timestamp) PARTITION BY DAY;
            """)
            
            # Table for ticker data
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS coinbase_ticker (
                    symbol SYMBOL,
                    best_bid DOUBLE,
                    best_ask DOUBLE,
                    last_price DOUBLE,
                    spread DOUBLE,
                    volume_24h DOUBLE,
                    timestamp TIMESTAMP
                ) timestamp(timestamp) PARTITION BY DAY;
            """)
            
            # Table for 1-minute candles
            self.cursor.execute("""
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
            """)
            
            # Table for exchange rates (spot prices)
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS coinbase_spot_prices (
                    base SYMBOL,
                    currency SYMBOL,
                    amount DOUBLE,
                    timestamp TIMESTAMP
                ) timestamp(timestamp) PARTITION BY DAY;
            """)
            
            self.conn.commit()
            logger.info("QuestDB tables created successfully")
        except Exception as e:
            logger.error(f"Failed to create tables: {e}")
            raise
    
    def insert_trade(self, trade: Trade):
        """Insert a single trade into QuestDB"""
        try:
            # Convert timezone-aware datetime to naive UTC datetime for QuestDB
            timestamp = trade.time.replace(tzinfo=None) if trade.time.tzinfo else trade.time
            
            query = """
                INSERT INTO coinbase_trades (symbol, price, size, side, trade_id, timestamp) 
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
    
    def insert_ticker(self, ticker: Ticker):
        """Insert ticker data"""
        try:
            spread = ticker.best_ask - ticker.best_bid
            # Convert timezone-aware datetime to naive UTC datetime for QuestDB
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
    
    def insert_spot_price(self, base: str, currency: str, amount: float):
        """Insert spot price data"""
        try:
            query = """
                INSERT INTO coinbase_spot_prices (base, currency, amount, timestamp) 
                VALUES (%s, %s, %s, %s)
            """
            # Use timezone-aware datetime and convert to naive UTC for QuestDB
            timestamp = datetime.now(timezone.utc).replace(tzinfo=None)
            self.cursor.execute(query, (base, currency, amount, timestamp))
            self.conn.commit()
        except Exception as e:
            logger.error(f"Failed to insert spot price: {e}")
            self.conn.rollback()
    
    async def fetch_spot_prices(self):
        """Fetch spot prices from Coinbase REST API"""
        async with aiohttp.ClientSession() as session:
            while self.running:
                try:
                    # Fetch spot prices for major cryptocurrencies
                    cryptos = ['BTC', 'ETH', 'SOL', 'LINK', 'MATIC']
                    
                    for crypto in cryptos:
                        url = f"{COINBASE_REST_URL}/exchange-rates?currency={crypto}"
                        async with session.get(url) as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                rates = data['data']['rates']
                                
                                # Store USD rate
                                if 'USD' in rates:
                                    self.insert_spot_price(
                                        crypto, 'USD', 
                                        float(rates['USD'])
                                    )
                        
                        await asyncio.sleep(0.5)  # Rate limiting
                    
                    await asyncio.sleep(10)  # Fetch every 10 seconds
                    
                except Exception as e:
                    logger.error(f"Error fetching spot prices: {e}")
                    await asyncio.sleep(30)
    
    async def coinbase_websocket_feed(self):
        """Connect to Coinbase WebSocket for real-time data"""
        subscribe_message = {
            "type": "subscribe",
            "product_ids": TRADING_PAIRS,
            "channels": ["ticker", "matches"]  # matches = trades
        }
        
        while self.running:
            try:
                async with websockets.connect(COINBASE_WS_URL) as websocket:
                    # Subscribe to channels
                    await websocket.send(json.dumps(subscribe_message))
                    logger.info("Connected to Coinbase WebSocket feed")
                    
                    async for message in websocket:
                        data = json.loads(message)
                        
                        if data['type'] == 'ticker':
                            ticker = Ticker(
                                symbol=data['product_id'],
                                best_bid=float(data['best_bid']),
                                best_ask=float(data['best_ask']),
                                last_price=float(data['price']),
                                volume_24h=float(data['volume_24h']),
                                time=self.parse_coinbase_time(data['time'])
                            )
                            self.insert_ticker(ticker)
                            
                            # Broadcast to connected WebSocket clients
                            await self.broadcast_to_clients({
                                'type': 'ticker',
                                'data': {
                                    'symbol': ticker.symbol,
                                    'price': ticker.last_price,
                                    'bid': ticker.best_bid,
                                    'ask': ticker.best_ask,
                                    'volume': ticker.volume_24h
                                }
                            })
                        
                        elif data['type'] == 'match':  # Trade
                            trade = Trade(
                                symbol=data['product_id'],
                                price=float(data['price']),
                                size=float(data['size']),
                                side=data['side'],
                                time=self.parse_coinbase_time(data['time']),
                                trade_id=int(data['trade_id'])
                            )
                            self.insert_trade(trade)
                            
                            # Broadcast to connected WebSocket clients
                            await self.broadcast_to_clients({
                                'type': 'trade',
                                'data': {
                                    'symbol': trade.symbol,
                                    'price': trade.price,
                                    'size': trade.size,
                                    'side': trade.side
                                }
                            })
                            
            except Exception as e:
                logger.error(f"WebSocket error: {e}")
                await asyncio.sleep(5)  # Reconnect after 5 seconds
    
    async def generate_candles(self):
        """Generate 1-minute candles from trades"""
        await asyncio.sleep(30)  # Initial delay to accumulate some trades
        
        while self.running:
            try:
                # First, check if we have any trades
                self.cursor.execute("SELECT count() FROM coinbase_trades")
                trade_count = self.cursor.fetchone()[0]
                
                if trade_count > 0:
                    # Aggregate all trades into 1-minute candles, including current minute
                    query = """
                        INSERT INTO coinbase_candles (symbol, open, high, low, close, volume, trade_count, timestamp)
                        SELECT 
                            symbol,
                            first(price) as open,
                            max(price) as high,
                            min(price) as low,
                            last(price) as close,
                            sum(size) as volume,
                            count(*) as trade_count,
                            date_trunc('minute', timestamp) as timestamp
                        FROM coinbase_trades
                        WHERE timestamp >= dateadd('h', -24, now())  -- Process last 24 hours
                        GROUP BY symbol, date_trunc('minute', timestamp)
                    """
                    self.cursor.execute(query)
                    self.conn.commit()
                    
                    rows_affected = self.cursor.rowcount
                    logger.info(f"Generated {rows_affected} candle records")
                else:
                    logger.info("No trades yet to generate candles")
                
                await asyncio.sleep(30)  # Run every 30 seconds instead of 60
                
            except Exception as e:
                logger.error(f"Error generating candles: {e}")
                self.conn.rollback()
                await asyncio.sleep(30)
    
    async def broadcast_to_clients(self, message: dict):
        """Broadcast message to all connected WebSocket clients"""
        if self.connected_clients:
            disconnected = set()
            for client in self.connected_clients:
                try:
                    await client.send_json(message)
                except:
                    disconnected.add(client)
            
            # Remove disconnected clients
            self.connected_clients -= disconnected
    
    def get_latest_prices(self) -> Dict[str, float]:
        """Get latest prices for all symbols"""
        try:
            self.cursor.execute("""
                SELECT symbol, last(last_price) 
                FROM coinbase_ticker 
                WHERE timestamp > dateadd('m', -5, now())
                GROUP BY symbol
            """)
            return {row[0]: row[1] for row in self.cursor.fetchall()}
        except Exception as e:
            logger.error(f"Error getting latest prices: {e}")
            return {}
    
    def get_stats(self) -> dict:
        """Get current statistics"""
        stats = {}
        try:
            # Get trade count
            self.cursor.execute("SELECT count() FROM coinbase_trades WHERE timestamp > dateadd('h', -1, now())")
            stats['trades_last_hour'] = self.cursor.fetchone()[0]
            
            # Get latest prices
            stats['latest_prices'] = self.get_latest_prices()
            
            # Get 24h volume
            self.cursor.execute("""
                SELECT symbol, sum(size) as volume
                FROM coinbase_trades 
                WHERE timestamp > dateadd('h', -24, now())
                GROUP BY symbol
            """)
            stats['volume_24h'] = {row[0]: row[1] for row in self.cursor.fetchall()}
            
        except Exception as e:
            logger.error(f"Error getting stats: {e}")
        
        return stats

# Create global instance
ingestion = CoinbaseDataIngestion()

# Create FastAPI app with lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    ingestion.connect_questdb()
    ingestion.create_tables()
    ingestion.running = True
    
    # Start background tasks
    ingestion.websocket_task = asyncio.create_task(ingestion.coinbase_websocket_feed())
    ingestion.rest_api_task = asyncio.create_task(ingestion.fetch_spot_prices())
    candles_task = asyncio.create_task(ingestion.generate_candles())
    
    yield
    
    # Shutdown
    ingestion.running = False
    if ingestion.websocket_task:
        ingestion.websocket_task.cancel()
    if ingestion.rest_api_task:
        ingestion.rest_api_task.cancel()
    candles_task.cancel()
    
    if ingestion.cursor:
        ingestion.cursor.close()
    if ingestion.conn:
        ingestion.conn.close()

app = FastAPI(lifespan=lifespan)

@app.get("/")
async def root():
    return {"message": "Coinbase crypto data ingestion running", "pairs": TRADING_PAIRS}

@app.get("/stats")
async def get_stats():
    """Get current statistics"""
    return ingestion.get_stats()

@app.get("/prices")
async def get_prices():
    """Get latest prices"""
    return ingestion.get_latest_prices()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time data"""
    await websocket.accept()
    ingestion.connected_clients.add(websocket)
    
    try:
        # Send initial data
        await websocket.send_json({
            'type': 'connected',
            'data': {
                'message': 'Connected to Coinbase data feed',
                'prices': ingestion.get_latest_prices()
            }
        })
        
        # Keep connection alive
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ingestion.connected_clients.remove(websocket)

# HTML page for testing WebSocket
@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Coinbase Crypto Data</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 20px; }
            .price-card { 
                display: inline-block; 
                margin: 10px; 
                padding: 15px; 
                border: 1px solid #ddd; 
                border-radius: 5px;
                min-width: 200px;
            }
            .symbol { font-weight: bold; font-size: 18px; }
            .price { font-size: 24px; color: #2e7d32; }
            .trade { 
                padding: 5px; 
                margin: 2px; 
                background: #f5f5f5;
                border-radius: 3px;
            }
            .buy { color: green; }
            .sell { color: red; }
            #trades { max-height: 400px; overflow-y: auto; }
        </style>
    </head>
    <body>
        <h1>Coinbase Real-Time Crypto Data</h1>
        <div id="prices"></div>
        <h2>Recent Trades</h2>
        <div id="trades"></div>
        
        <script>
            const ws = new WebSocket('ws://localhost:8000/ws');
            const pricesDiv = document.getElementById('prices');
            const tradesDiv = document.getElementById('trades');
            const priceElements = {};
            
            ws.onmessage = function(event) {
                const message = JSON.parse(event.data);
                
                if (message.type === 'ticker') {
                    updatePrice(message.data);
                } else if (message.type === 'trade') {
                    showTrade(message.data);
                } else if (message.type === 'connected') {
                    // Initialize prices
                    for (const [symbol, price] of Object.entries(message.data.prices)) {
                        updatePrice({ symbol, price });
                    }
                }
            };
            
            function updatePrice(data) {
                if (!priceElements[data.symbol]) {
                    const card = document.createElement('div');
                    card.className = 'price-card';
                    card.innerHTML = `
                        <div class="symbol">${data.symbol}</div>
                        <div class="price" id="price-${data.symbol}">$${data.price.toFixed(2)}</div>
                        <div id="bid-ask-${data.symbol}"></div>
                    `;
                    pricesDiv.appendChild(card);
                    priceElements[data.symbol] = true;
                } else {
                    document.getElementById(`price-${data.symbol}`).textContent = `$${data.price.toFixed(2)}`;
                }
                
                if (data.bid && data.ask) {
                    document.getElementById(`bid-ask-${data.symbol}`).innerHTML = 
                        `Bid: $${data.bid.toFixed(2)} | Ask: $${data.ask.toFixed(2)}`;
                }
            }
            
            function showTrade(data) {
                const trade = document.createElement('div');
                trade.className = `trade ${data.side}`;
                trade.textContent = `${new Date().toLocaleTimeString()} - ${data.symbol}: ${data.side.toUpperCase()} ${data.size} @ $${data.price.toFixed(2)}`;
                tradesDiv.insertBefore(trade, tradesDiv.firstChild);
                
                // Keep only last 50 trades
                while (tradesDiv.children.length > 50) {
                    tradesDiv.removeChild(tradesDiv.lastChild);
                }
            }
        </script>
    </body>
    </html>
    """

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)