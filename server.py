import hashlib
import os
import random
import time
import uuid

import bcrypt
import requests
from dotenv import load_dotenv

load_dotenv()  

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel

import ibkr_client
import alpaca_client
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

    salt = uuid.uuid4().hex 
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


class LogoutRequest(BaseModel):
    token: str | None = None


@app.post("/api/auth/logout")
def logout(req: LogoutRequest):
    if req.token:
        SESSIONS.pop(req.token, None)
    return {"success": True}


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
conversational, and grounded in how this specific bot actually works.  give \
personalized financial advice framed as a recommendation to buy/sell a specific real \
asset with real money — you can explain concepts and how the bot's logic works, but \
frame anything forward-looking as advice, including investment advice."""


class ChatRequest(BaseModel):
    message: str


@app.post("/api/assistant/chat")
def assistant_chat(req: ChatRequest):
    try:
        client = get_groq_client()
        response = client.chat.completions.create(
            model="openai/gpt-oss-120b", 
            max_tokens=400,
            messages=[
                {"role": "system", "content": ASSISTANT_SYSTEM_PROMPT},
                {"role": "user", "content": req.message},
            ],
        )
        reply = response.choices[0].message.content
        return {"reply": reply}
    except RuntimeError as e:
        return {"reply": f"[Assistant not configured] {e}"}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Assistant request failed: {e}")


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

FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY")
FINNHUB_BASE_URL = "https://finnhub.io/api/v1"


TICKER_SYMBOLS = [
    {"display": "BTC-USD", "finnhub": "BINANCE:BTCUSDT"},
    {"display": "ETH-USD", "finnhub": "BINANCE:ETHUSDT"},
    {"display": "SOL-USD", "finnhub": "BINANCE:SOLUSDT"},
    {"display": "AAPL", "finnhub": "AAPL"},
    {"display": "TSLA", "finnhub": "TSLA"},
    {"display": "NVDA", "finnhub": "NVDA"},
]


def _finnhub_get(path: str, params: dict | None = None) -> dict:
    if not FINNHUB_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="FINNHUB_API_KEY is not set. Add it to your .env file. "
                   "Get a free key at finnhub.io",
        )
    try:
        resp = requests.get(
            f"{FINNHUB_BASE_URL}{path}",
            params={**(params or {}), "token": FINNHUB_API_KEY},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        raise HTTPException(status_code=503, detail=f"Finnhub request failed: {e}")


def _time_ago(unix_ts: float) -> str:
    diff = time.time() - unix_ts
    if diff < 60:
        return "just now"
    if diff < 3600:
        return f"{int(diff // 60)}m ago"
    if diff < 86400:
        return f"{int(diff // 3600)}h ago"
    return f"{int(diff // 86400)}d ago"


@app.get("/api/ticker")
def get_ticker():
    items = []
    for entry in TICKER_SYMBOLS:
        quote = _finnhub_get("/quote", {"symbol": entry["finnhub"]})
        items.append({
            "symbol": entry["display"],
            "price": quote.get("c"),
            "changePct": quote.get("dp") or 0,
        })
    return {"items": items}


@app.get("/api/news")
def get_news():
    raw = _finnhub_get("/news", {"category": "general"})
    items = []
    for n in raw[:10]:
        items.append({
            "src": n.get("source", "Finnhub"),
            "time": _time_ago(n.get("datetime", time.time())),
            "headline": n.get("headline", ""),
            
            "sentiment": "neutral",
        })
    return items


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
        
        n = len(history)
        xs = list(range(n))
        mean_x = sum(xs) / n
        mean_y = sum(history) / n
        slope = sum((xs[i] - mean_x) * (history[i] - mean_y) for i in range(n)) / \
            sum((xs[i] - mean_x) ** 2 for i in range(n))
        drift = slope
    elif model == "monte_carlo":
    
        paths_drift = []
        for _ in range(25):
            p = current
            for _ in range(5):
                p *= (1 + random.uniform(-0.004, 0.005))
            paths_drift.append((p - current) / 5)
        drift = sum(paths_drift) / len(paths_drift)
    else:  
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



@app.get("/api/forecast/ml")
def get_ml_forecast(symbol: str = "AAPL", horizon: str = "1w"):
    try:
        return ml_forecast.forecast(symbol.upper(), horizon=horizon)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"ML forecast failed: {e}")


class OrderRequest(BaseModel):
    symbol: str
    side: str  
    quantity: float
    order_type: str = "MKT"
    limit_price: float | None = None
    token: str | None = None  


def _email_for_token(token: str | None) -> str:
    if token and token in SESSIONS:
        return SESSIONS[token]
    return "anonymous"  

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



@app.get("/api/alpaca/account")
def alpaca_account():
    try:
        return alpaca_client.get_account_summary()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.get("/api/alpaca/positions")
def alpaca_positions():
    try:
        return alpaca_client.get_positions()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.get("/api/alpaca/quote/{symbol}")
def alpaca_quote(symbol: str):
    try:
        return alpaca_client.get_quote(symbol.upper())
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.post("/api/alpaca/order")
def alpaca_order(req: OrderRequest):
    if req.side.upper() not in ("BUY", "SELL"):
        raise HTTPException(status_code=400, detail="side must be BUY or SELL")
    try:
        result = alpaca_client.place_order(
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
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.get("/api/trades")
def trade_history(token: str = None, limit: int = 100):
    email = _email_for_token(token) if token else None
    return db.get_trades(email=email, limit=limit)


@app.get("/")
def root():
    return RedirectResponse(url="/login.html")



BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app.mount("/", StaticFiles(directory=BASE_DIR, html=True), name="static")



if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)