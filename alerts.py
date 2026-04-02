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
