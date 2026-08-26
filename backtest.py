import argparse
import pandas as pd
import yfinance as yf
import matplotlib.pyplot as plt


def fetch_data(symbol: str, start: str, end: str) -> pd.DataFrame:
    df = yf.download(symbol, start=start, end=end, progress=False)
    if df.empty:
        raise ValueError(f"No data returned for {symbol}. Check the symbol and date range.")

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    return df


def run_backtest(df: pd.DataFrame, fast: int = 5, slow: int = 20,
                  starting_capital: float = 10_000.0, position_pct: float = 0.5):
    """
    Same logic as MovingAverageStrategy in auto_trader_skeleton.py, but
    run against a full historical DataFrame instead of live ticks.
    """
    close = df["Close"]
    if isinstance(close, pd.DataFrame):  
        close = close.iloc[:, 0]
    df = df.copy()
    df["fast_ma"] = close.rolling(fast).mean()
    df["slow_ma"] = close.rolling(slow).mean()

    cash = starting_capital
    shares = 0.0
    equity_curve = []
    trades = []
    in_position = False

    for i in range(len(df)):
        price = float(close.iloc[i])
        fast_ma = df["fast_ma"].iloc[i]
        slow_ma = df["slow_ma"].iloc[i]

        if pd.notna(fast_ma) and pd.notna(slow_ma):
            if fast_ma > slow_ma and not in_position:
                spend = cash * position_pct
                shares = spend / price
                cash -= spend
                in_position = True
                trades.append({"date": df.index[i], "side": "BUY", "price": price, "shares": shares})

            elif fast_ma < slow_ma and in_position:
                cash += shares * price
                trades.append({"date": df.index[i], "side": "SELL", "price": price, "shares": shares})
                shares = 0.0
                in_position = False

        equity = cash + shares * price
        equity_curve.append(equity)

    df["equity"] = equity_curve

    final_price = float(close.iloc[-1])
    final_equity = cash + shares * final_price

    total_return_pct = (final_equity - starting_capital) / starting_capital * 100

    
    completed = []
    open_buy = None
    for t in trades:
        if t["side"] == "BUY":
            open_buy = t
        elif t["side"] == "SELL" and open_buy is not None:
            pnl = (t["price"] - open_buy["price"]) * t["shares"]
            completed.append(pnl)
            open_buy = None

    wins = [p for p in completed if p > 0]
    win_rate = (len(wins) / len(completed) * 100) if completed else 0.0

    
    running_max = df["equity"].cummax()
    drawdown = (df["equity"] - running_max) / running_max
    max_drawdown_pct = drawdown.min() * 100


    bh_shares = starting_capital / float(close.iloc[0])
    bh_final = bh_shares * final_price
    bh_return_pct = (bh_final - starting_capital) / starting_capital * 100

    return {
        "df": df,
        "trades": trades,
        "final_equity": final_equity,
        "total_return_pct": total_return_pct,
        "num_trades": len(completed),
        "win_rate": win_rate,
        "max_drawdown_pct": max_drawdown_pct,
        "buy_hold_return_pct": bh_return_pct,
    }


def print_report(symbol: str, fast: int, slow: int, result: dict):
    print("=" * 50)
    print(f"BACKTEST REPORT — {symbol}  (MA{fast}/MA{slow} crossover)")
    print("=" * 50)
    print(f"Final equity:          ${result['final_equity']:,.2f}")
    print(f"Total return:          {result['total_return_pct']:+.2f}%")
    print(f"Buy & hold return:     {result['buy_hold_return_pct']:+.2f}%  (benchmark)")
    print(f"Completed trades:      {result['num_trades']}")
    print(f"Win rate:              {result['win_rate']:.1f}%")
    print(f"Max drawdown:          {result['max_drawdown_pct']:.2f}%")
    print("=" * 50)
    edge = result["total_return_pct"] - result["buy_hold_return_pct"]
    if edge > 0:
        print(f"Strategy beat buy-and-hold by {edge:.2f} percentage points over this period.")
    else:
        print(f"Strategy underperformed buy-and-hold by {abs(edge):.2f} percentage points over this period.")
    print("Note: past performance on this window does not guarantee future results.")


def plot_results(symbol: str, result: dict, save_path: str = "backtest_chart.png"):
    df = result["df"]
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 7), sharex=True,
                                    gridspec_kw={"height_ratios": [2, 1]})

    ax1.plot(df.index, df["Close"], label="Price", color="#333333", linewidth=1)
    ax1.plot(df.index, df["fast_ma"], label="Fast MA", color="#3FBF7F", linewidth=1)
    ax1.plot(df.index, df["slow_ma"], label="Slow MA", color="#E5484D", linewidth=1)

    buys = [t for t in result["trades"] if t["side"] == "BUY"]
    sells = [t for t in result["trades"] if t["side"] == "SELL"]
    if buys:
        ax1.scatter([t["date"] for t in buys], [t["price"] for t in buys],
                    marker="^", color="#3FBF7F", s=80, zorder=5, label="Buy")
    if sells:
        ax1.scatter([t["date"] for t in sells], [t["price"] for t in sells],
                    marker="v", color="#E5484D", s=80, zorder=5, label="Sell")

    ax1.set_title(f"{symbol} — Price & Signals")
    ax1.legend(loc="upper left")
    ax1.grid(alpha=0.2)

    ax2.plot(df.index, df["equity"], color="#F2A93B", linewidth=1.5)
    ax2.set_title("Equity Curve")
    ax2.grid(alpha=0.2)

    plt.tight_layout()
    plt.savefig(save_path, dpi=150)
    print(f"\nChart saved to {save_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backtest the moving-average strategy on real historical data.")
    parser.add_argument("--symbol", default="BTC-USD")
    parser.add_argument("--start", default="2022-01-01")
    parser.add_argument("--end", default="2024-01-01")
    parser.add_argument("--fast", type=int, default=5)
    parser.add_argument("--slow", type=int, default=20)
    parser.add_argument("--capital", type=float, default=10_000.0)
    args = parser.parse_args()

    data = fetch_data(args.symbol, args.start, args.end)
    result = run_backtest(data, fast=args.fast, slow=args.slow, starting_capital=args.capital)
    print_report(args.symbol, args.fast, args.slow, result)
    plot_results(args.symbol, result)