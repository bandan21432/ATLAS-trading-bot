import time
import logging
from dataclasses import dataclass
from enum import Enum

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("auto_trader")


class Signal(Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class MarketData:
    symbol: str
    price: float
    timestamp: float


@dataclass
class Position:
    symbol: str
    quantity: float
    entry_price: float

class DataFeed:


    def __init__(self, symbol: str):
        self.symbol = symbol
        self.price_history = []

    def get_latest_price(self) -> MarketData:

        import random
        last = self.price_history[-1] if self.price_history else 100.0
        price = last + random.uniform(-1, 1)
        data = MarketData(self.symbol, price, time.time())
        self.price_history.append(price)
        return data

class MovingAverageStrategy:
    """Simple crossover strategy: fast MA vs slow MA."""

    def __init__(self, fast_window=5, slow_window=20):
        self.fast_window = fast_window
        self.slow_window = slow_window

    def generate_signal(self, price_history: list[float]) -> Signal:
        if len(price_history) < self.slow_window:
            return Signal.HOLD

        fast_ma = sum(price_history[-self.fast_window:]) / self.fast_window
        slow_ma = sum(price_history[-self.slow_window:]) / self.slow_window

        if fast_ma > slow_ma:
            return Signal.BUY
        elif fast_ma < slow_ma:
            return Signal.SELL
        return Signal.HOLD

class RiskManager:
    def __init__(self, max_position_pct=0.1, stop_loss_pct=0.02):
        self.max_position_pct = max_position_pct  # max % of capital per trade
        self.stop_loss_pct = stop_loss_pct

    def position_size(self, capital: float, price: float) -> float:
        allocation = capital * self.max_position_pct
        return round(allocation / price, 6)

    def should_stop_out(self, position: Position, current_price: float) -> bool:
        loss_pct = (position.entry_price - current_price) / position.entry_price
        return loss_pct >= self.stop_loss_pct

class ExecutionClient:
    """Replace with real broker SDK calls (Alpaca, IBKR, ccxt, etc.)"""

    def place_order(self, symbol: str, side: Signal, quantity: float, price: float):
        # TODO: call broker.submit_order(...)
        log.info(f"ORDER {side.value} {quantity} {symbol} @ {price:.2f}")
        return {"status": "filled", "symbol": symbol, "side": side.value,
                "quantity": quantity, "price": price}

class TradingBot:
    def __init__(self, symbol: str, capital: float):
        self.feed = DataFeed(symbol)
        self.strategy = MovingAverageStrategy()
        self.risk = RiskManager()
        self.execution = ExecutionClient()
        self.capital = capital
        self.position: Position | None = None

    def run_once(self):
        data = self.feed.get_latest_price()
        signal = self.strategy.generate_signal(self.feed.price_history)

        if self.position and self.risk.should_stop_out(self.position, data.price):
            self.execution.place_order(data.symbol, Signal.SELL, self.position.quantity, data.price)
            self.position = None
            return

        if signal == Signal.BUY and not self.position:
            qty = self.risk.position_size(self.capital, data.price)
            self.execution.place_order(data.symbol, Signal.BUY, qty, data.price)
            self.position = Position(data.symbol, qty, data.price)

        elif signal == Signal.SELL and self.position:
            self.execution.place_order(data.symbol, Signal.SELL, self.position.quantity, data.price)
            self.position = None

    def run(self, iterations=50, interval_sec=1):
        for _ in range(iterations):
            self.run_once()
            time.sleep(interval_sec)


if __name__ == "__main__":
    bot = TradingBot(symbol="BTC-USD", capital=10_000)
    bot.run(iterations=30, interval_sec=1)