from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestQuoteRequest


def get_trading_client(api_key: str, secret_key: str, paper: bool = True) -> TradingClient:
    return TradingClient(api_key, secret_key, paper=paper)


def get_data_client(api_key: str, secret_key: str) -> StockHistoricalDataClient:
    return StockHistoricalDataClient(api_key, secret_key)


def verify_credentials(api_key: str, secret_key: str, paper: bool) -> dict:
    """
    Used when a user first connects their account — makes one real API
    call to confirm the keys actually work before we save them.
    Raises on failure (bad keys, wrong paper/live flag, etc.).
    """
    client = get_trading_client(api_key, secret_key, paper)
    acct = client.get_account()
    return {
        "equity": float(acct.equity),
        "status": acct.status.value if hasattr(acct.status, "value") else str(acct.status),
    }


def get_account_summary(api_key: str, secret_key: str, paper: bool) -> dict:
    client = get_trading_client(api_key, secret_key, paper)
    acct = client.get_account()
    return {
        "equity": float(acct.equity),
        "cash": float(acct.cash),
        "buying_power": float(acct.buying_power),
        "portfolio_value": float(acct.portfolio_value),
        "status": acct.status.value if hasattr(acct.status, "value") else str(acct.status),
        "paper": paper,
    }


def get_positions(api_key: str, secret_key: str, paper: bool) -> list[dict]:
    client = get_trading_client(api_key, secret_key, paper)
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


def get_quote(api_key: str, secret_key: str, symbol: str) -> dict:
    client = get_data_client(api_key, secret_key)
    req = StockLatestQuoteRequest(symbol_or_symbols=symbol)
    quote = client.get_stock_latest_quote(req)[symbol]
    return {
        "symbol": symbol,
        "bid": float(quote.bid_price),
        "ask": float(quote.ask_price),
        "mid": round((float(quote.bid_price) + float(quote.ask_price)) / 2, 2),
    }


def place_order(api_key: str, secret_key: str, paper: bool, symbol: str, side: str,
                 quantity: float, order_type: str = "MKT", limit_price: float = None) -> dict:
    """
    side: 'BUY' or 'SELL'
    order_type: 'MKT' or 'LMT' (LMT requires limit_price)

    IMPORTANT: if paper=False, this places a REAL order with REAL money
    against the user's live Alpaca account.
    """
    client = get_trading_client(api_key, secret_key, paper)
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
        "paper": paper,
    }
