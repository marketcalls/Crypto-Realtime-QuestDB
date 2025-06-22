# websocket_client.py
"""
Coinbase WebSocket client for real-time data ingestion
"""
import asyncio
import json
import websockets
from datetime import datetime
import logging
from typing import Callable, Set

from config import COINBASE_WS_URL, TRADING_PAIRS, WEBSOCKET_RECONNECT_DELAY
from models import Trade, Ticker

logger = logging.getLogger(__name__)

class CoinbaseWebSocketClient:
    """Manages WebSocket connection to Coinbase"""
    
    def __init__(self, on_ticker: Callable, on_trade: Callable):
        self.on_ticker = on_ticker
        self.on_trade = on_trade
        self.running = False
        self.broadcast_callbacks: Set[Callable] = set()
    
    def add_broadcast_callback(self, callback: Callable):
        """Add callback for broadcasting data to clients"""
        self.broadcast_callbacks.add(callback)
    
    def remove_broadcast_callback(self, callback: Callable):
        """Remove broadcast callback"""
        self.broadcast_callbacks.discard(callback)
    
    def parse_coinbase_time(self, time_str: str) -> datetime:
        """Parse Coinbase timestamp and return naive UTC datetime"""
        if time_str.endswith('Z'):
            dt = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
        else:
            dt = datetime.fromisoformat(time_str)
        return dt.replace(tzinfo=None) if dt.tzinfo else dt
    
    async def _broadcast_data(self, message: dict):
        """Broadcast data to all registered callbacks"""
        for callback in self.broadcast_callbacks:
            try:
                await callback(message)
            except Exception as e:
                logger.error(f"Error in broadcast callback: {e}")
    
    async def connect_and_subscribe(self):
        """Connect to Coinbase WebSocket and subscribe to channels"""
        subscribe_message = {
            "type": "subscribe",
            "product_ids": TRADING_PAIRS,
            "channels": ["ticker", "matches"]
        }
        
        while self.running:
            try:
                async with websockets.connect(COINBASE_WS_URL) as websocket:
                    await websocket.send(json.dumps(subscribe_message))
                    logger.info("Connected to Coinbase WebSocket feed")
                    
                    async for message in websocket:
                        await self._process_message(json.loads(message))
                        
            except Exception as e:
                logger.error(f"WebSocket error: {e}")
                if self.running:
                    await asyncio.sleep(WEBSOCKET_RECONNECT_DELAY)
    
    async def _process_message(self, data: dict):
        """Process incoming WebSocket message"""
        try:
            msg_type = data.get('type')
            
            if msg_type == 'ticker':
                ticker = Ticker(
                    symbol=data['product_id'],
                    best_bid=float(data['best_bid']),
                    best_ask=float(data['best_ask']),
                    last_price=float(data['price']),
                    volume_24h=float(data['volume_24h']),
                    time=self.parse_coinbase_time(data['time'])
                )
                
                # Store in database
                self.on_ticker(ticker)
                
                # Broadcast to clients
                await self._broadcast_data({
                    'type': 'ticker',
                    'data': {
                        'symbol': ticker.symbol,
                        'price': ticker.last_price,
                        'bid': ticker.best_bid,
                        'ask': ticker.best_ask,
                        'volume': ticker.volume_24h,
                        'spread': ticker.best_ask - ticker.best_bid
                    }
                })
            
            elif msg_type == 'match':  # Trade
                trade = Trade(
                    symbol=data['product_id'],
                    price=float(data['price']),
                    size=float(data['size']),
                    side=data['side'],
                    time=self.parse_coinbase_time(data['time']),
                    trade_id=int(data['trade_id'])
                )
                
                # Store in database
                self.on_trade(trade)
                
                # Broadcast to clients
                await self._broadcast_data({
                    'type': 'trade',
                    'data': {
                        'symbol': trade.symbol,
                        'price': trade.price,
                        'size': trade.size,
                        'side': trade.side,
                        'time': trade.time.isoformat()
                    }
                })
                
        except Exception as e:
            logger.error(f"Error processing message: {e}")
    
    async def start(self):
        """Start the WebSocket client"""
        self.running = True
        await self.connect_and_subscribe()
    
    def stop(self):
        """Stop the WebSocket client"""
        self.running = False