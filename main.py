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
from __future__ import annotations
import logging
import time
import signal
import sys
from datetime import datetime, timezone, time as dtime

import schedule

from config import config as cfg
from data_layer import DataLayer
from ai_brain import AIBrain
from math_layer import MathLayer
from execution_layer import ExecutionLayer
from alerts import AlertSystem

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("bot.log", mode="a"),
    ],
)
logger = logging.getLogger("main")

