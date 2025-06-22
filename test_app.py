#!/usr/bin/env python3
"""
Test script to verify the application components work properly
"""
import sys
import logging
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def test_imports():
    """Test if all modules can be imported successfully"""
    try:
        logger.info("Testing imports...")
        
        # Test config
        from config import QUESTDB_CONFIG, TRADING_PAIRS, COINBASE_WS_URL
        logger.info(f"✓ Config loaded - {len(TRADING_PAIRS)} trading pairs configured")
        
        # Test models
        from models import Trade, Ticker, QUESTDB_SCHEMAS
        logger.info(f"✓ Models loaded - {len(QUESTDB_SCHEMAS)} database schemas defined")
        
        # Test database client (without connecting)
        from database import QuestDBClient
        logger.info("✓ Database client loaded")
        
        # Test websocket client
        from websocket_client import CoinbaseWebSocketClient
        logger.info("✓ WebSocket client loaded")
        
        # Test main app
        from main import app
        logger.info("✓ FastAPI app loaded")
        
        return True
    except Exception as e:
        logger.error(f"✗ Import failed: {e}")
        return False

def test_data_models():
    """Test if data models work correctly"""
    try:
        logger.info("Testing data models...")
        
        from models import Trade, Ticker
        
        # Test Ticker creation
        ticker = Ticker(
            symbol="BTC-USD",
            best_bid=50000.0,
            best_ask=50001.0,
            last_price=50000.5,
            volume_24h=1000000.0,
            time=datetime.now()
        )
        logger.info(f"✓ Ticker model: {ticker.symbol} @ ${ticker.last_price}")
        
        # Test Trade creation
        trade = Trade(
            symbol="BTC-USD",
            price=50000.0,
            size=0.1,
            side="buy",
            time=datetime.now(),
            trade_id=12345
        )
        logger.info(f"✓ Trade model: {trade.side} {trade.size} {trade.symbol} @ ${trade.price}")
        
        return True
    except Exception as e:
        logger.error(f"✗ Data model test failed: {e}")
        return False

def test_websocket_client():
    """Test websocket client initialization"""
    try:
        logger.info("Testing WebSocket client...")
        
        from websocket_client import CoinbaseWebSocketClient
        
        def dummy_ticker_handler(ticker):
            logger.info(f"Received ticker: {ticker.symbol}")
        
        def dummy_trade_handler(trade):
            logger.info(f"Received trade: {trade.symbol}")
        
        # Test client creation
        client = CoinbaseWebSocketClient(
            on_ticker=dummy_ticker_handler,
            on_trade=dummy_trade_handler
        )
        logger.info("✓ WebSocket client created successfully")
        
        # Test timestamp parsing
        test_time = "2023-01-01T12:00:00.000000Z"
        parsed_time = client.parse_coinbase_time(test_time)
        logger.info(f"✓ Time parsing works: {parsed_time}")
        
        return True
    except Exception as e:
        logger.error(f"✗ WebSocket client test failed: {e}")
        return False

def main():
    """Run all tests"""
    logger.info("Starting application component tests...")
    
    tests = [
        ("Module Imports", test_imports),
        ("Data Models", test_data_models),
        ("WebSocket Client", test_websocket_client),
    ]
    
    results = []
    for test_name, test_func in tests:
        logger.info(f"\n--- Running {test_name} Test ---")
        result = test_func()
        results.append((test_name, result))
        logger.info(f"--- {test_name} Test {'PASSED' if result else 'FAILED'} ---\n")
    
    # Summary
    logger.info("=" * 50)
    logger.info("TEST SUMMARY")
    logger.info("=" * 50)
    
    passed = 0
    for test_name, result in results:
        status = "PASS" if result else "FAIL"
        logger.info(f"{test_name}: {status}")
        if result:
            passed += 1
    
    logger.info(f"\nOverall: {passed}/{len(results)} tests passed")
    
    if passed == len(results):
        logger.info("🎉 All tests passed! The application components are working correctly.")
        logger.info("\nTo start the application:")
        logger.info("1. Make sure QuestDB is running on localhost:8812")
        logger.info("2. Run: ./venv/Scripts/python.exe main.py")
        logger.info("3. Open http://localhost:8000 in your browser")
        return 0
    else:
        logger.error("❌ Some tests failed. Please check the errors above.")
        return 1

if __name__ == "__main__":
    sys.exit(main())