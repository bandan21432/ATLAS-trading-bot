import os
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestQuoteRequest

API_KEY = os.environ.get("ALPACA_API_KEY")
SECRET_KEY = os.environ.get("ALPACA_SECRET_KEY")
PAPER = os.environ.get("ALPACA_PAPER", "true").lower() != "false"  # default to paper trading

_trading_client = None
_data_client = None


def _require_keys():
    if not API_KEY or not SECRET_KEY:
        raise RuntimeError(
           
        )


def get_trading_client() -> TradingClient:
    global _trading_client
    _require_keys()
    if _trading_client is None:
        _trading_client = TradingClient(API_KEY, SECRET_KEY, paper=PAPER)
    return _trading_client


def get_data_client() -> StockHistoricalDataClient:
    global _data_client
    _require_keys()
    if _data_client is None:
        _data_client = StockHistoricalDataClient(API_KEY, SECRET_KEY)
    return _data_client


def get_account_summary() -> dict:
    client = get_trading_client()
    acct = client.get_account()
    return {
        "equity": float(acct.equity),
        "cash": float(acct.cash),
        "buying_power": float(acct.buying_power),
        "portfolio_value": float(acct.portfolio_value),
        "status": acct.status.value if hasattr(acct.status, "value") else str(acct.status),
        "paper": PAPER,
    }


def get_positions() -> list[dict]:
    client = get_trading_client()
    positions = client.get_all_positions()
    return [
        {
            "symbol": p.symbol,
            "quantity": float(p.qty),
            "avg_entry_price": float(p.avg_entry_price),
            "market_value": float(p.market_value),
            "unrealized_pl": float(p.unrealized_pl),
        }
        for p in positions
    ]


def get_quote(symbol: str) -> dict:
    client = get_data_client()
    req = StockLatestQuoteRequest(symbol_or_symbols=symbol)
    quote = client.get_stock_latest_quote(req)[symbol]
    return {
        "symbol": symbol,
        "bid": float(quote.bid_price),
        "ask": float(quote.ask_price),
        "mid": round((float(quote.bid_price) + float(quote.ask_price)) / 2, 2),
    }


def place_order(symbol: str, side: str, quantity: float, order_type: str = "MKT", limit_price: float = None) -> dict:

  
    client = get_trading_client()
    order_side = OrderSide.BUY if side.upper() == "BUY" else OrderSide.SELL

    if order_type == "LMT":
        if limit_price is None:
            raise ValueError("limit_price is required for LMT orders")
        req = LimitOrderRequest(
            symbol=symbol, qty=quantity, side=order_side,
            time_in_force=TimeInForce.DAY, limit_price=limit_price,
        )
    else:
        req = MarketOrderRequest(
            symbol=symbol, qty=quantity, side=order_side,
            time_in_force=TimeInForce.DAY,
        )

    order = client.submit_order(req)
    return {
        "symbol": symbol,
        "side": side.upper(),
        "quantity": quantity,
        "order_type": order_type,
        "status": order.status.value if hasattr(order.status, "value") else str(order.status),
        "order_id": str(order.id),
    }