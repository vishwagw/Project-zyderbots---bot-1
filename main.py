"""
main.py — Trading bot orchestrator.

Runs two scan loops:
  • Intraday loop  — every 5 minutes during market hours (5-min bars)
  • Swing loop     — once at 09:35 ET each day (daily bars)

Plus a position monitor that ticks every 60 seconds.

Pipeline for each symbol:
  DataLayer → AIBrain → MathLayer → ExecutionLayer → AlertSystem

Usage:
  python main.py

Environment: copy .env.example to .env and fill in your API keys.
Start with ALPACA_PAPER=true until you trust the system.
"""
