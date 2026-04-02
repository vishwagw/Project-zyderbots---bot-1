"""
alerts.py — Telegram notification system.

Sends structured alerts for every meaningful bot event:
  - Trade opened / target hit / stop hit
  - Trade skipped (with reason and EV)
  - Daily P&L summary
  - Runtime errors

Setup:
  1. Message @BotFather on Telegram → /newbot → copy the token
  2. Message @userinfobot → copy your chat_id
  3. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env
"""
from __future__ import annotations
import logging
import requests
from datetime import datetime, timezone
from typing import Optional

from config import Config

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


class AlertSystem:
    def __init__(self, cfg: Config):
        self.token   = cfg.TELEGRAM_BOT_TOKEN
        self.chat_id = cfg.TELEGRAM_CHAT_ID
        self.enabled = bool(self.token and self.chat_id)

        if not self.enabled:
            logger.warning("Telegram not configured — alerts disabled")

    # ─────────────────────────────────────────────────────────────────────────
    # Core send
    # ─────────────────────────────────────────────────────────────────────────

    def send(self, text: str) -> bool:
        """Send a plain message. Returns True on success."""
        if not self.enabled:
            logger.info(f"[ALERT] {text}")
            return False
        try:
            url  = TELEGRAM_API.format(token=self.token)
            resp = requests.post(
                url,
                json={
                    "chat_id":    self.chat_id,
                    "text":       text,
                    "parse_mode": "HTML",
                },
                timeout=10,
            )
            resp.raise_for_status()
            return True
        except Exception as exc:
            logger.error(f"Telegram send failed: {exc}")
            return False

    # ─────────────────────────────────────────────────────────────────────────
    # Trade events
    # ─────────────────────────────────────────────────────────────────────────

    def trade_opened(
        self,
        symbol: str,
        direction: str,
        entry: float,
        target: float,
        stop: float,
        shares: int,
        position_usd: float,
        ev: float,
        posterior: float,
        kelly_pct: float,
        rr: float,
        thesis: str,
        mode: str,
    ) -> None:
        emoji = "🟢" if direction == "long" else "🔴"
        tag   = "LONG" if direction == "long" else "SHORT"
        rr_pct = round((target - entry) / (entry - stop) if direction == "long"
                       else (entry - target) / (stop - entry), 2)

        msg = (
            f"{emoji} <b>TRADE OPENED — {symbol} {tag}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📋 Mode:       {mode.capitalize()}\n"
            f"💰 Entry:      ${entry:.2f}\n"
            f"🎯 Target:     ${target:.2f}  (+{(target/entry-1)*100:.2f}%)\n"
            f"🛑 Stop:       ${stop:.2f}   (-{(1-stop/entry)*100:.2f}%)\n"
            f"⚖️  R:R:        {rr_pct:.2f}x\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 EV:         {ev*100:.2f}%\n"
            f"🧠 Confidence: {posterior*100:.1f}%\n"
            f"📐 Kelly size: {kelly_pct*100:.2f}% of equity\n"
            f"🔢 Size:       {shares} shares (${position_usd:.0f})\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💡 <i>{thesis}</i>\n"
            f"🕐 {datetime.now(timezone.utc).strftime('%H:%M UTC')}"
        )
        self.send(msg)

    def target_hit(
        self,
        symbol: str,
        entry: float,
        exit_price: float,
        shares: int,
        pnl_usd: float,
        log_return: float,
    ) -> None:
        pct = (exit_price / entry - 1) * 100
        msg = (
            f"✅ <b>TARGET HIT — {symbol}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📈 Entry:      ${entry:.2f}\n"
            f"📈 Exit:       ${exit_price:.2f}  ({pct:+.2f}%)\n"
            f"💵 P&amp;L:        <b>${pnl_usd:+.2f}</b>   ({shares} shares)\n"
            f"📉 Log return: {log_return:.4f}\n"
            f"🕐 {datetime.now(timezone.utc).strftime('%H:%M UTC')}"
        )
        self.send(msg)

    def stop_hit(
        self,
        symbol: str,
        entry: float,
        exit_price: float,
        shares: int,
        pnl_usd: float,
        log_return: float,
    ) -> None:
        pct = (exit_price / entry - 1) * 100
        msg = (
            f"🛑 <b>STOP HIT — {symbol}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📉 Entry:      ${entry:.2f}\n"
            f"📉 Exit:       ${exit_price:.2f}  ({pct:+.2f}%)\n"
            f"💵 P&amp;L:        <b>${pnl_usd:+.2f}</b>   ({shares} shares)\n"
            f"📉 Log return: {log_return:.4f}\n"
            f"🕐 {datetime.now(timezone.utc).strftime('%H:%M UTC')}"
        )
        self.send(msg)

    def trade_skipped(
        self,
        symbol: str,
        reason: str,
        ev: Optional[float] = None,
        mode: str = "",
    ) -> None:
        ev_str = f"  |  EV={ev*100:.2f}%" if ev is not None else ""
        msg = f"⏭  <b>SKIP — {symbol}</b>{ev_str}\n<i>{reason}</i>"
        self.send(msg)

    # ─────────────────────────────────────────────────────────────────────────
    # Daily / session summary
    # ─────────────────────────────────────────────────────────────────────────

    def daily_summary(self, summary: dict, account: dict) -> None:
        win_rate_pct = summary["win_rate"] * 100
        pnl_emoji    = "📈" if summary["total_realised_pnl"] >= 0 else "📉"
        msg = (
            f"📊 <b>DAILY SUMMARY</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"{pnl_emoji} Realised P&amp;L:   <b>${summary['total_realised_pnl']:+.2f}</b>\n"
            f"📋 Trades closed:  {summary['closed_trades']}\n"
            f"🎯 Win rate:       {win_rate_pct:.1f}%\n"
            f"📐 Avg log return: {summary['avg_log_return']:.4f}\n"
            f"📂 Open positions: {summary['open_positions']}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💼 Portfolio:      ${account['portfolio_value']:,.0f}\n"
            f"💵 Buying power:   ${account['buying_power']:,.0f}\n"
            f"🕐 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
        )
        self.send(msg)

    def bot_started(self, watchlist: list[str], paper: bool) -> None:
        mode = "📄 PAPER" if paper else "🔴 LIVE"
        msg  = (
            f"🤖 <b>Trading bot started</b>  {mode}\n"
            f"Watching {len(watchlist)} symbols: {', '.join(watchlist[:8])}"
            f"{'...' if len(watchlist) > 8 else ''}"
        )
        self.send(msg)

    def error_alert(self, context: str, error: Exception) -> None:
        msg = f"⚠️ <b>ERROR</b> in {context}\n<code>{str(error)[:300]}</code>"
        self.send(msg)

  
