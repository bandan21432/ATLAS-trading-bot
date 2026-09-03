
import hashlib
import os
import random
import time
import uuid

import bcrypt
from dotenv import load_dotenv

load_dotenv()  # reads variables from a .env file in this same folder, if present

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel

import ibkr_client
import alpaca_client
import crypto_utils
import db
import ml_forecast

app = FastAPI(title="ATLAS Auto Trader API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

db.init_db()

# ---------------------------------------------------------------------
# Sessions stay in memory on purpose — a short-lived token doesn't
# need to survive a server restart the way users/trades do. Users and
# trade history are now persisted to SQLite via db.py (atlas.db).
# ---------------------------------------------------------------------
SESSIONS: dict[str, str] = {}  # token -> email


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


class SignupRequest(BaseModel):
    email: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


@app.post("/api/auth/signup")
def signup(req: SignupRequest):
    if db.user_exists(req.email):
        raise HTTPException(status_code=400, detail="Account already exists")
    if len(req.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

    salt = uuid.uuid4().hex  # kept in the table for backward compatibility, unused by bcrypt
    db.create_user(req.email, salt, hash_password(req.password))
    token = uuid.uuid4().hex
    SESSIONS[token] = req.email
    return {"success": True, "token": token, "email": req.email}


@app.post("/api/auth/login")
def login(req: LoginRequest):
    user = db.get_user(req.email)
    if not user or not verify_password(req.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = uuid.uuid4().hex
    SESSIONS[token] = req.email
    return {"success": True, "token": token, "email": req.email}


def current_user(token: str) -> str:
    email = SESSIONS.get(token)
    if not email:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    return email


# ---------------------------------------------------------------------
# Market data — replace this simulated walk with your real DataFeed /
# TradingBot from auto_trader_skeleton.py
# ---------------------------------------------------------------------
_last_price = 68204.50


@app.get("/api/market/tick")
def market_tick():
    global _last_price
    change = random.uniform(-30, 30)
    _last_price = max(1.0, _last_price + change)
    return {
        "symbol": "BTC-USD",
        "price": round(_last_price, 2),
        "change": round(change, 2),
        "timestamp": time.time(),
    }


@app.get("/api/account")
def account(token: str):
    email = current_user(token)
    user = db.get_user(email)
    return {"email": email, "capital": user["capital"]}


# ---------------------------------------------------------------------
# AI Assistant — real LLM call via Groq's API, which is free (no
# credit card required) and very fast. Uses open models like Llama.
#
# Setup:
#   1. pip install groq
#   2. Sign up free at https://console.groq.com
#   3. Create an API key: console.groq.com -> API Keys
#   4. Set it as an environment variable before starting the server:
#
#      Windows (PowerShell):
#          $env:GROQ_API_KEY="your_actual_key_here"
#      macOS/Linux:
#          export GROQ_API_KEY="your_actual_key_here"
#
# Never put this key in frontend code (HTML/JS) — it must stay on
# the backend only, which is exactly what this endpoint does.
#
# (If you ever want to switch to Anthropic's Claude models instead,
# the alternative code using `anthropic.Anthropic(...)` is the same
# shape — swap the client and the .create() call.)
# ---------------------------------------------------------------------
from groq import Groq

_groq_client = None


def get_groq_client():
    global _groq_client
    if _groq_client is None:
        key = os.environ.get("GROQ_API_KEY")
        if not key:
            raise RuntimeError(
                "GROQ_API_KEY is not set. Set it as an environment variable "
                "before starting the server. Get a free key at console.groq.com"
            )
        _groq_client = Groq(api_key=key)
    return _groq_client


ASSISTANT_SYSTEM_PROMPT = """You are the AI assistant embedded in ATLAS, a personal \
algorithmic trading dashboard built by a student as a learning project. You help the \
user understand their bot's strategy, current signals, risk settings, and general \
trading/finance concepts.

Context about this specific bot:
- Strategy: moving average crossover (fast MA vs slow MA, default 5-period/20-period)
- Buy signal: fast MA crosses above slow MA. Sell signal: fast MA crosses below slow MA.
- Risk management: caps any single position at 10% of account capital, with a 2% stop-loss
- Brokers connected: Alpaca (paper trading) and Interactive Brokers
- This is a PAPER/SIMULATED trading environment for learning purposes, not live trading with real money (unless the user says otherwise)

Keep answers concise (2-4 sentences typically, unless the user asks for depth), \
conversational, and grounded in how this specific bot actually works. Never give \
personalized financial advice framed as a recommendation to buy/sell a specific real \
asset with real money — you can explain concepts and how the bot's logic works, but \
frame anything forward-looking as educational, not investment advice."""


class ChatRequest(BaseModel):
    message: str


@app.post("/api/assistant/chat")
def assistant_chat(req: ChatRequest):
    try:
        client = get_groq_client()
        response = client.chat.completions.create(
            model="openai/gpt-oss-120b",  # Groq deprecated the old llama-3.3-70b-versatile model
            max_tokens=400,
            messages=[
                {"role": "system", "content": ASSISTANT_SYSTEM_PROMPT},
                {"role": "user", "content": req.message},
            ],
        )
        reply = response.choices[0].message.content
        return {"reply": reply}
    except RuntimeError as e:
        # API key not configured — fall back to a helpful message instead of crashing
        return {"reply": f"[Assistant not configured] {e}"}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Assistant request failed: {e}")


# ---------------------------------------------------------------------
# Notification history — stored in memory for this demo. Swap for a
# real database if you want history to persist across server restarts.
# ---------------------------------------------------------------------
class NotificationIn(BaseModel):
    type: str
    title: str
    desc: str = ""


NOTIFICATIONS: list[dict] = []


@app.post("/api/notifications")
def add_notification(note: NotificationIn):
    entry = {**note.dict(), "id": str(uuid.uuid4()), "timestamp": time.time()}
    NOTIFICATIONS.insert(0, entry)
    return entry


@app.get("/api/notifications")
def list_notifications():
    return NOTIFICATIONS[:100]


# ---------------------------------------------------------------------
# News — demo headlines. Replace with a real financial news API
# (e.g. NewsAPI, Finnhub, Alpha Vantage) using your own API key.
# ---------------------------------------------------------------------
@app.get("/api/news")
def get_news():
    return [
        {"src": "Reuters", "headline": "Fed signals rate path unchanged after latest meeting", "sentiment": "neutral"},
        {"src": "Bloomberg", "headline": "Bitcoin climbs as spot ETF inflows extend to a fifth day", "sentiment": "bullish"},
        {"src": "CNBC", "headline": "Tech shares slip on renewed chip export concerns", "sentiment": "bearish"},
    ]


# ---------------------------------------------------------------------
# Profit & loss — simulated equity curve. Replace with real trade
# history from your TradingBot once it's logging fills to a database.
# ---------------------------------------------------------------------
@app.get("/api/pnl")
def get_pnl():
    equity = 10_000.0
    curve = []
    now = time.time()
    for i in range(30):
        equity += random.uniform(-120, 160)
        curve.append({"t": now - (30 - i) * 3600, "equity": round(equity, 2)})
    total_pnl = curve[-1]["equity"] - 10_000.0
    return {
        "curve": curve,
        "total_pnl": round(total_pnl, 2),
        "total_pnl_pct": round(total_pnl / 10_000.0 * 100, 2),
        "win_rate": 61.4,
    }


# ---------------------------------------------------------------------
# Forecast — projects a price path forward over a chosen horizon.
#
# IMPORTANT: these are simple, illustrative statistical projections
# (EMA trend extrapolation, linear regression, and a basic Monte Carlo
# random walk), not a real predictive trading model. For anything used
# to make actual trading decisions, replace this with a properly
# validated model (e.g. ARIMA/Prophet on real historical data, or a
# trained ML model with backtested accuracy) and treat its output as
# one input among many — never as a guarantee.
# ---------------------------------------------------------------------
HORIZON_STEPS = {"1h": 12, "4h": 16, "1d": 24, "1w": 14, "1m": 20}
MODEL_CONFIDENCE = {"ema_trend": 62, "linear": 58, "monte_carlo": 71}


def simulate_history(n=40, start=68000.0):
    history = [start]
    for _ in range(n - 1):
        history.append(max(1.0, history[-1] + random.uniform(-40, 40)))
    return history


@app.get("/api/forecast")
def get_forecast(horizon: str = "1d", model: str = "ema_trend"):
    steps = HORIZON_STEPS.get(horizon, 20)
    history = simulate_history()
    current = history[-1]

    if model == "linear":
        # least-squares slope over the recent history
        n = len(history)
        xs = list(range(n))
        mean_x = sum(xs) / n
        mean_y = sum(history) / n
        slope = sum((xs[i] - mean_x) * (history[i] - mean_y) for i in range(n)) / \
            sum((xs[i] - mean_x) ** 2 for i in range(n))
        drift = slope
    elif model == "monte_carlo":
        # average drift across several simulated random-walk paths (GBM-style)
        paths_drift = []
        for _ in range(25):
            p = current
            for _ in range(5):
                p *= (1 + random.uniform(-0.004, 0.005))
            paths_drift.append((p - current) / 5)
        drift = sum(paths_drift) / len(paths_drift)
    else:  # ema_trend
        alpha = 0.3
        ema = history[0]
        for v in history[1:]:
            ema = alpha * v + (1 - alpha) * ema
        drift = (history[-1] - ema) / 5

    projection = []
    band = []
    cur = current
    for i in range(steps):
        cur += drift + random.uniform(-current * 0.001, current * 0.001)
        spread = current * 0.004 * (i + 1) / steps * 4
        projection.append({"value": round(cur, 2)})
        band.append({"hi": round(cur + spread, 2), "lo": round(max(0.01, cur - spread), 2)})

    return {
        "history": [round(h, 2) for h in history],
        "projection": projection,
        "band": band,
        "current": round(current, 2),
        "target": projection[-1]["value"],
        "confidence": MODEL_CONFIDENCE.get(model, 60),
        "model": model,
        "horizon": horizon,
    }


# ---------------------------------------------------------------------
# Real ML forecast — trained on actual historical data (see
# ml_forecast.py). Only supports daily+ horizons (1d/1w/1m) since it's
# trained on daily price bars, unlike the simulated endpoint above.
#
# This retrains on every request for simplicity, which takes a few
# seconds. For a production app you'd train once and cache/reload the
# model instead of refitting per request.
# ---------------------------------------------------------------------
@app.get("/api/forecast/ml")
def get_ml_forecast(symbol: str = "AAPL", horizon: str = "1w"):
    try:
        return ml_forecast.forecast(symbol.upper(), horizon=horizon)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"ML forecast failed: {e}")


# ---------------------------------------------------------------------
# IBKR — real broker connection via TWS/IB Gateway (through ibkr_client.py)
#
# These are defined as plain `def` (not `async def`) on purpose: FastAPI
# runs sync path functions in a threadpool automatically, which avoids
# clashing with ib_insync's own event loop handling.
#
# IMPORTANT: place_order sends a REAL order to whatever account is
# logged into TWS/Gateway. Use a paper trading account until you are
# confident in the bot's behavior.
# ---------------------------------------------------------------------
class OrderRequest(BaseModel):
    symbol: str
    side: str  # "BUY" or "SELL"
    quantity: float
    order_type: str = "MKT"
    limit_price: float | None = None
    token: str | None = None  # optional — associates the trade with a logged-in user


def _email_for_token(token: str | None) -> str:
    if token and token in SESSIONS:
        return SESSIONS[token]
    return "anonymous"  # order placed without being logged in (e.g. testing via curl)


@app.get("/api/ibkr/status")
def ibkr_status():
    try:
        ibkr_client.connect()
        return {"connected": ibkr_client.ib.isConnected()}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Could not reach TWS/IB Gateway: {e}")


@app.get("/api/ibkr/account")
def ibkr_account():
    try:
        return ibkr_client.get_account_summary()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.get("/api/ibkr/positions")
def ibkr_positions():
    try:
        return ibkr_client.get_positions()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.get("/api/ibkr/quote/{symbol}")
def ibkr_quote(symbol: str):
    try:
        return ibkr_client.get_quote(symbol.upper())
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.post("/api/ibkr/order")
def ibkr_order(req: OrderRequest):
    if req.side.upper() not in ("BUY", "SELL"):
        raise HTTPException(status_code=400, detail="side must be BUY or SELL")
    try:
        result = ibkr_client.place_order(
            symbol=req.symbol.upper(),
            side=req.side,
            quantity=req.quantity,
            order_type=req.order_type,
            limit_price=req.limit_price,
        )
        db.log_trade(
            email=_email_for_token(req.token), broker="ibkr", symbol=result["symbol"],
            side=result["side"], quantity=result["quantity"], order_type=result["order_type"],
            status=result["status"], fill_price=result.get("avg_fill_price"),
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


# ---------------------------------------------------------------------
# Alpaca — real broker connection via the alpaca-py REST API.
#
# MULTI-USER: each user connects their OWN Alpaca account (paper or
# live) through /api/broker/alpaca/connect. Credentials are encrypted
# (crypto_utils.py) and stored per-user in the database — nobody trades
# through anyone else's account, and keys are never exposed to the
# frontend after being saved.
# ---------------------------------------------------------------------
class BrokerConnectRequest(BaseModel):
    token: str
    api_key: str
    secret_key: str
    is_paper: bool = True


def _require_alpaca_creds(token: str) -> tuple[str, str, bool]:
    """Returns (api_key, secret_key, is_paper) for the logged-in user, decrypted.
    Raises a clear, actionable error if they haven't connected an account yet."""
    email = current_user(token)
    creds = db.get_broker_credentials(email, broker="alpaca")
    if not creds:
        raise HTTPException(
            status_code=400,
            detail="No Alpaca account connected. Go to Broker Settings to connect your Alpaca API keys first.",
        )
    api_key = crypto_utils.decrypt(creds["api_key_encrypted"])
    secret_key = crypto_utils.decrypt(creds["secret_key_encrypted"])
    return api_key, secret_key, bool(creds["is_paper"])


@app.post("/api/broker/alpaca/connect")
def alpaca_connect(req: BrokerConnectRequest):
    email = current_user(req.token)
    try:
        # Verify the keys actually work (and match the paper/live flag)
        # before saving anything — catches typos/wrong-mode mistakes early.
        result = alpaca_client.verify_credentials(req.api_key, req.secret_key, req.is_paper)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not verify these Alpaca credentials: {e}")

    db.save_broker_credentials(
        email=email, broker="alpaca",
        api_key_encrypted=crypto_utils.encrypt(req.api_key),
        secret_key_encrypted=crypto_utils.encrypt(req.secret_key),
        is_paper=req.is_paper,
    )
    return {"success": True, "is_paper": req.is_paper, "equity": result["equity"]}


@app.get("/api/broker/alpaca/status")
def alpaca_connect_status(token: str):
    email = current_user(token)
    creds = db.get_broker_credentials(email, broker="alpaca")
    if not creds:
        return {"connected": False}
    return {"connected": True, "is_paper": bool(creds["is_paper"])}


class BrokerDisconnectRequest(BaseModel):
    token: str


@app.post("/api/broker/alpaca/disconnect")
def alpaca_disconnect(req: BrokerDisconnectRequest):
    email = current_user(req.token)
    db.delete_broker_credentials(email, broker="alpaca")
    return {"success": True}


@app.get("/api/alpaca/account")
def alpaca_account(token: str):
    try:
        api_key, secret_key, is_paper = _require_alpaca_creds(token)
        return alpaca_client.get_account_summary(api_key, secret_key, is_paper)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.get("/api/alpaca/positions")
def alpaca_positions(token: str):
    try:
        api_key, secret_key, is_paper = _require_alpaca_creds(token)
        return alpaca_client.get_positions(api_key, secret_key, is_paper)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.get("/api/alpaca/quote/{symbol}")
def alpaca_quote(symbol: str, token: str):
    try:
        api_key, secret_key, is_paper = _require_alpaca_creds(token)
        return alpaca_client.get_quote(api_key, secret_key, symbol.upper())
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.post("/api/alpaca/order")
def alpaca_order(req: OrderRequest):
    if req.side.upper() not in ("BUY", "SELL"):
        raise HTTPException(status_code=400, detail="side must be BUY or SELL")
    try:
        api_key, secret_key, is_paper = _require_alpaca_creds(req.token)
        result = alpaca_client.place_order(
            api_key=api_key, secret_key=secret_key, paper=is_paper,
            symbol=req.symbol.upper(),
            side=req.side,
            quantity=req.quantity,
            order_type=req.order_type,
            limit_price=req.limit_price,
        )
        db.log_trade(
            email=_email_for_token(req.token), broker="alpaca", symbol=result["symbol"],
            side=result["side"], quantity=result["quantity"], order_type=result["order_type"],
            status=result["status"], order_id=result.get("order_id"),
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.get("/api/trades")
def trade_history(token: str = None, limit: int = 100):
    email = _email_for_token(token) if token else None
    return db.get_trades(email=email, limit=limit)


# ---------------------------------------------------------------------
# Bare root URL (http://127.0.0.1:8000/) redirects straight to the
# login page, so you don't have to remember "/login.html" every time.
# This route must be registered BEFORE the static mount below, since
# FastAPI checks routes in the order they were added.
# ---------------------------------------------------------------------
@app.get("/")
def root():
    return RedirectResponse(url="/login.html")


# ---------------------------------------------------------------------
# Serve the frontend files (login.html, auto_trader_dashboard.html)
# from the same folder as this script.
# ---------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app.mount("/", StaticFiles(directory=BASE_DIR, html=True), name="static")


# ---------------------------------------------------------------------
# Entrypoint for hosting platforms like Render, which assign a port
# dynamically via the PORT environment variable. Locally, you'll
# still normally run `uvicorn server:app --reload` instead of this —
# this block only matters when Render starts the app.
# ---------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
