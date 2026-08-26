import os
import sys

from dotenv import load_dotenv
load_dotenv() 

print("=" * 55)
print("ALPACA CONNECTION DIAGNOSTIC")
print("=" * 55)


try:
    import alpaca
    print("[OK] alpaca-py package is installed.")
except ImportError:
    print("[FAIL] alpaca-py is not installed.")
    print("       Fix: pip install alpaca-py")
    sys.exit(1)


api_key = os.environ.get("ALPACA_API_KEY")
secret_key = os.environ.get("ALPACA_SECRET_KEY")

if not api_key:
    print("[FAIL] ALPACA_API_KEY is not set in this terminal session.")
    print('       Fix (PowerShell): $env:ALPACA_API_KEY="your_key_here"')
    sys.exit(1)
else:
    print(f"[OK] ALPACA_API_KEY is set (starts with: {api_key[:4]}...)")

if not secret_key:
    print("[FAIL] ALPACA_SECRET_KEY is not set in this terminal session.")
    print('       Fix (PowerShell): $env:ALPACA_SECRET_KEY="your_secret_here"')
    sys.exit(1)
else:
    print(f"[OK] ALPACA_SECRET_KEY is set (starts with: {secret_key[:4]}...)")

try:
    from alpaca.trading.client import TradingClient
    client = TradingClient(api_key, secret_key, paper=True)
    account = client.get_account()
    print("[OK] Successfully connected to Alpaca!")
    print(f"     Account status: {account.status}")
    print(f"     Equity:         ${float(account.equity):,.2f}")
    print(f"     Buying power:   ${float(account.buying_power):,.2f}")
    print("\nEverything works. If the dashboard still says 'Not connected',")
    print("make sure you started 'uvicorn' in THIS SAME terminal session")
    print("(environment variables don't carry over to a different terminal window).")

except Exception as e:
    print(f"[FAIL] Connected to the package, but Alpaca rejected the request.")
    print(f"       Error: {e}")
    print()
    print("Common causes:")
    print("  - Keys copied incorrectly (extra space, missing character)")
    print("  - Using LIVE keys instead of PAPER keys (or vice versa)")
    print("  - Keys were regenerated/revoked on the Alpaca dashboard since you copied them")
    sys.exit(1)