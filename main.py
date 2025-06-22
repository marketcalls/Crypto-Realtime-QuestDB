# main.py
"""
Main FastAPI application with modular architecture
"""
import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Set
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from config import LOG_LEVEL, LOG_FORMAT, CANDLE_GENERATION_INTERVAL
from database import QuestDBClient
from websocket_client import CoinbaseWebSocketClient

# Configure logging
logging.basicConfig(level=LOG_LEVEL, format=LOG_FORMAT)
logger = logging.getLogger(__name__)

# Global instances
db_client = QuestDBClient()
ws_client = None
connected_clients: Set[WebSocket] = set()

# Background tasks
background_tasks = []

async def generate_candles_task():
    """Background task to generate candles"""
    while True:
        try:
            db_client.generate_candles()
        except Exception as e:
            logger.error(f"Error in candle generation: {e}")
        await asyncio.sleep(CANDLE_GENERATION_INTERVAL)

async def broadcast_to_clients(message: dict):
    """Broadcast message to all connected WebSocket clients"""
    if connected_clients:
        disconnected = set()
        for client in connected_clients:
            try:
                await client.send_json(message)
            except:
                disconnected.add(client)
        connected_clients.difference_update(disconnected)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    global ws_client
    
    # Startup
    logger.info("Starting Crypto Analytics System...")
    
    # Initialize database
    db_client.connect()
    db_client.create_tables()
    
    # Initialize WebSocket client
    ws_client = CoinbaseWebSocketClient(
        on_ticker=db_client.insert_ticker,
        on_trade=db_client.insert_trade
    )
    ws_client.add_broadcast_callback(broadcast_to_clients)
    
    # Start background tasks
    ws_task = asyncio.create_task(ws_client.start())
    candles_task = asyncio.create_task(generate_candles_task())
    
    background_tasks.extend([ws_task, candles_task])
    
    logger.info("System started successfully!")
    
    yield
    
    # Shutdown
    logger.info("Shutting down Crypto Analytics System...")
    
    # Stop WebSocket client
    ws_client.stop()
    
    # Cancel background tasks
    for task in background_tasks:
        task.cancel()
    
    # Close database connection
    db_client.close()
    
    logger.info("System shut down successfully!")

# Create FastAPI app
app = FastAPI(
    title="Crypto Analytics with QuestDB",
    description="Real-time cryptocurrency data ingestion and analytics",
    version="1.0.0",
    lifespan=lifespan
)

# Serve static files (if needed)
# app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    """Serve the main dashboard"""
    dashboard_path = Path(__file__).parent / "dashboard.html"
    with open(dashboard_path, "r") as f:
        return HTMLResponse(content=f.read())

@app.get("/api/prices")
async def get_prices():
    """Get latest prices for all symbols"""
    prices = db_client.get_latest_prices()
    return JSONResponse(content=prices)

@app.get("/api/market-stats")
async def get_market_stats():
    """Get comprehensive market statistics"""
    stats = db_client.get_market_stats()
    return JSONResponse(content=stats)

@app.get("/api/candles/{symbol}")
async def get_candles(symbol: str, limit: int = 60):
    """Get recent candles for a symbol"""
    candles = db_client.get_recent_candles(symbol, limit)
    return JSONResponse(content=candles)

@app.get("/api/data-points")
async def get_data_points():
    """Get total data points stored"""
    try:
        # Get counts from each table separately
        total = 0
        
        # Count ticker data
        db_client.cursor.execute("SELECT count() FROM coinbase_ticker")
        ticker_count = db_client.cursor.fetchone()[0]
        total += ticker_count
        
        # Count trades data
        db_client.cursor.execute("SELECT count() FROM coinbase_trades")
        trades_count = db_client.cursor.fetchone()[0]
        total += trades_count
        
        # Count candles data
        db_client.cursor.execute("SELECT count() FROM coinbase_candles")
        candles_count = db_client.cursor.fetchone()[0]
        total += candles_count
        
        logger.info(f"Data points - Ticker: {ticker_count}, Trades: {trades_count}, Candles: {candles_count}")
        
        return JSONResponse(content={"total": total})
    except Exception as e:
        logger.error(f"Error getting data points: {e}")
        return JSONResponse(content={"total": 0})

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time updates"""
    await websocket.accept()
    connected_clients.add(websocket)
    
    try:
        # Send initial data
        await websocket.send_json({
            'type': 'connected',
            'data': {
                'message': 'Connected to Crypto Analytics Dashboard',
                'prices': db_client.get_latest_prices()
            }
        })
        
        # Keep connection alive
        while True:
            await websocket.receive_text()
            
    except WebSocketDisconnect:
        connected_clients.remove(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        connected_clients.discard(websocket)

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        # Check database connection
        db_client.cursor.execute("SELECT 1")
        db_status = "healthy"
    except:
        db_status = "unhealthy"
    
    return {
        "status": "healthy" if db_status == "healthy" else "degraded",
        "database": db_status,
        "websocket": "healthy" if ws_client and ws_client.running else "unhealthy",
        "connected_clients": len(connected_clients)
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )