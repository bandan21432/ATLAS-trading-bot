import numpy as np
import pandas as pd
import yfinance as yf
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import r2_score, mean_absolute_error

TRADING_DAYS_PER_HORIZON = {"1d": 1, "1w": 5, "1m": 21}


def _flatten_columns(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    close = df["Close"]
    feats = pd.DataFrame(index=df.index)

    feats["return_1d"] = close.pct_change(1)
    feats["return_3d"] = close.pct_change(3)
    feats["return_5d"] = close.pct_change(5)
    feats["return_10d"] = close.pct_change(10)
    feats["ma_5"] = close.rolling(5).mean() / close - 1
    feats["ma_20"] = close.rolling(20).mean() / close - 1
    feats["volatility_10d"] = close.pct_change().rolling(10).std()
    feats["rsi_14"] = _rsi(close, 14) / 100.0

    feats["target_next_return"] = close.pct_change().shift(-1)

    feats["close"] = close
    return feats.dropna()


def train_model(symbol: str, period: str = "2y"):
    raw = yf.download(symbol, period=period, progress=False)
    if raw.empty:
        raise ValueError(f"No data returned for {symbol}.")
    raw = _flatten_columns(raw)

    feats = build_features(raw)
    feature_cols = ["return_1d", "return_3d", "return_5d", "return_10d",
                     "ma_5", "ma_20", "volatility_10d", "rsi_14"]

    X = feats[feature_cols]
    y = feats["target_next_return"]

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, shuffle=False)

    model = GradientBoostingRegressor(n_estimators=100, max_depth=3, learning_rate=0.05, random_state=42)
    model.fit(X_train, y_train)

    preds = model.predict(X_test)
    r2 = r2_score(y_test, preds)
    mae = mean_absolute_error(y_test, preds)
    directional_accuracy = float(np.mean(np.sign(preds) == np.sign(y_test))) * 100

    return {
        "model": model,
        "feature_cols": feature_cols,
        "feats": feats,
        "raw": raw,
        "metrics": {
            "r2": round(r2, 4),
            "mae": round(mae, 5),
            "directional_accuracy_pct": round(directional_accuracy, 1),
            "test_samples": len(y_test),
        },
    }


def forecast(symbol: str, horizon: str = "1d", period: str = "2y") -> dict:
    if horizon not in TRADING_DAYS_PER_HORIZON:
        raise ValueError(f"horizon must be one of {list(TRADING_DAYS_PER_HORIZON.keys())} for the ML model")

    steps = TRADING_DAYS_PER_HORIZON[horizon]
    trained = train_model(symbol, period=period)
    model = trained["model"]
    feature_cols = trained["feature_cols"]
    feats = trained["feats"]
    close_history = trained["raw"]["Close"]

    
    window = close_history.copy()
    projection = []
    band = []
    current_price = float(window.iloc[-1])

    
    residual_std = trained["metrics"]["mae"] * 2.5  

    price = current_price
    for i in range(steps):
        latest_feats = build_features(pd.DataFrame({"Close": window}))
        if latest_feats.empty:
            break
        x_latest = latest_feats[feature_cols].iloc[[-1]]
        pred_return = float(model.predict(x_latest)[0])

        price = price * (1 + pred_return)
        window = pd.concat([window, pd.Series([price], index=[window.index[-1] + pd.Timedelta(days=1)])])

        spread = price * residual_std * np.sqrt(i + 1)
        projection.append({"value": round(price, 2)})
        band.append({"hi": round(price + spread, 2), "lo": round(max(0.01, price - spread), 2)})

    history_tail = [round(float(v), 2) for v in close_history.tail(40).tolist()]

    return {
        "history": history_tail,
        "projection": projection,
        "band": band,
        "current": round(current_price, 2),
        "target": projection[-1]["value"] if projection else current_price,
        "confidence": max(5, min(95, round(trained["metrics"]["directional_accuracy_pct"]))),
        "model": "ml_gbr",
        "horizon": horizon,
        "metrics": trained["metrics"],
    }


if __name__ == "__main__":
    import json
    result = forecast("AAPL", horizon="1w")
    print(json.dumps({k: v for k, v in result.items() if k != "history"}, indent=2))
    print(f"\nModel evaluation (held-out test set): {result['metrics']}")