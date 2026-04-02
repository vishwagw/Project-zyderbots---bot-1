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

class TradingBot:
    def __init__(self):
        logger.info("Initialising trading bot…")
        self.data      = DataLayer(cfg)
        self.brain     = AIBrain(cfg)
        self.math      = MathLayer(cfg)
        self.executor  = ExecutionLayer(cfg, self.math)
        self.alerts    = AlertSystem(cfg)
        self.running   = True

    # ─────────────────────────────────────────────────────────────────────────
    # Core pipeline — one symbol, one mode
    # ─────────────────────────────────────────────────────────────────────────

    def process_symbol(self, symbol: str, mode: str) -> None:
        """Full data→brain→math→execution pipeline for a single symbol."""
        try:
            # Skip if already in a position for this symbol
            pos = self.executor.positions.get(symbol)
            if pos and pos.status == "open":
                return

            # ── 1. Data Layer ─────────────────────────────────────────────────
            context = self.data.get_context(symbol, mode)
            if context is None:
                logger.debug(f"[{symbol}] No context data — skipping")
                return

            # ── 2. AI Brain ───────────────────────────────────────────────────
            hypothesis = self.brain.analyze(context)
            if hypothesis is None:
                logger.debug(f"[{symbol}] AI brain returned no hypothesis")
                return

            if not hypothesis.get("should_trade"):
                logger.info(
                    f"[{symbol}] AI SKIP — {hypothesis.get('skip_reason', 'no reason given')}"
                )
                return  # Quiet skips — don't spam Telegram for every no-trade

            logger.info(
                f"[{symbol}] AI SIGNAL — {hypothesis['direction'].upper()}  "
                f"entry=${hypothesis['entry_price']}  "
                f"conf={hypothesis['confidence']:.2f}  "
                f"thesis: {hypothesis.get('thesis', '')}"
            )

            # ── 3. Math Layer ─────────────────────────────────────────────────
            acc          = self.executor.get_account()
            math_result  = self.math.run(
                hypothesis,
                context["technicals"],
                acc["equity"],
            )

            if not math_result.passes:
                self.alerts.trade_skipped(
                    symbol,
                    reason=math_result.skip_reason,
                    ev=math_result.expected_value,
                    mode=mode,
                )
                return

            # ── 4. Execution Layer ────────────────────────────────────────────
            position = self.executor.place_trade(hypothesis, math_result)
            if position is None:
                return

            # ── 5. Alert ──────────────────────────────────────────────────────
            self.alerts.trade_opened(
                symbol=symbol,
                direction=hypothesis["direction"],
                entry=hypothesis["entry_price"],
                target=hypothesis["target_price"],
                stop=hypothesis["stop_price"],
                shares=math_result.shares,
                position_usd=math_result.position_size_usd,
                ev=math_result.expected_value,
                posterior=math_result.posterior_confidence,
                kelly_pct=math_result.kelly_fraction,
                rr=math_result.reward_risk_ratio,
                thesis=hypothesis.get("thesis", ""),
                mode=mode,
            )

        except Exception as exc:
            logger.error(f"[{symbol}] Pipeline error: {exc}", exc_info=True)
            self.alerts.error_alert(f"process_symbol({symbol})", exc)

    # ─────────────────────────────────────────────────────────────────────────
    # Scheduled jobs
    # ─────────────────────────────────────────────────────────────────────────

    def run_intraday_scan(self) -> None:
        """Scan all watchlist symbols on 5-minute bars."""
        if not self._market_is_open():
            return
        logger.info("── Intraday scan ──────────────────────────────────────")
        for symbol in cfg.WATCHLIST:
            self.process_symbol(symbol, mode="intraday")
            time.sleep(1)  # Small pause between symbols to respect rate limits

    def run_swing_scan(self) -> None:
        """Scan all watchlist symbols on daily bars (run once per day)."""
        logger.info("── Swing scan ─────────────────────────────────────────")
        for symbol in cfg.WATCHLIST:
            self.process_symbol(symbol, mode="swing")
            time.sleep(1)

    def monitor_positions(self) -> None:
        """Check open positions for target/stop hits."""
        events = self.executor.monitor_positions()
        for ev in events:
            if ev["type"] in ("target_hit", "stop_hit"):
                pos = self.executor.positions.get(ev["symbol"])
                if pos:
                    fn = (
                        self.alerts.target_hit
                        if ev["type"] == "target_hit"
                        else self.alerts.stop_hit
                    )
                    fn(
                        symbol=ev["symbol"],
                        entry=pos.entry_price,
                        exit_price=ev["exit_price"],
                        shares=pos.shares,
                        pnl_usd=ev["pnl"],
                        log_return=ev["log_return"],
                    )

    def send_daily_summary(self) -> None:
        """Send end-of-day summary via Telegram."""
        summary = self.executor.portfolio_summary()
        account = self.executor.get_account()
        self.alerts.daily_summary(summary, account)

    # ─────────────────────────────────────────────────────────────────────────
    # Market hours helper
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _market_is_open() -> bool:
        """
        Rough check: US market hours 09:30–16:00 ET (UTC−4 or UTC−5).
        For production, replace with Alpaca's clock endpoint.
        """
        now_utc  = datetime.now(timezone.utc)
        weekday  = now_utc.weekday()          # 0=Mon … 6=Sun
        if weekday >= 5:                       # Weekend
            return False
        hour_utc = now_utc.hour
        # 09:30–16:00 ET ≈ 13:30–20:00 UTC (EDT) or 14:30–21:00 UTC (EST)
        return 13 <= hour_utc < 21

    # ─────────────────────────────────────────────────────────────────────────
    # Signal handling
    # ─────────────────────────────────────────────────────────────────────────

    def _shutdown(self, signum, frame) -> None:
        logger.info("Shutdown signal received — stopping gracefully")
        self.running = False

    # ─────────────────────────────────────────────────────────────────────────
    # Main entry point
    # ─────────────────────────────────────────────────────────────────────────

    def run(self) -> None:
        signal.signal(signal.SIGINT,  self._shutdown)
        signal.signal(signal.SIGTERM, self._shutdown)

        logger.info("Trading bot starting…")
        self.alerts.bot_started(cfg.WATCHLIST, cfg.ALPACA_PAPER)

        # ── Schedule ─────────────────────────────────────────────────────────
        schedule.every(cfg.INTRADAY_SCAN_INTERVAL).seconds.do(self.run_intraday_scan)
        schedule.every(cfg.POSITION_CHECK_INTERVAL).seconds.do(self.monitor_positions)
        schedule.every().day.at("09:35").do(self.run_swing_scan)    # ET market open + 5min
        schedule.every().day.at("15:55").do(self.send_daily_summary)  # 5 min before close

        # Run immediately on start
        self.run_intraday_scan()

        logger.info("Scheduler running. Press Ctrl+C to stop.")
        while self.running:
            schedule.run_pending()
            time.sleep(5)

        logger.info("Bot stopped.")
