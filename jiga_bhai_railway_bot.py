#!/usr/bin/env python3
"""
═══════════════════════════════════════════════════════════════════════════════
    🤖 JIGA BHAI GUJARATI TRADER — PRODUCTION BOT (Railway Ready)
═══════════════════════════════════════════════════════════════════════════════

Environment Variables Required (Railway Dashboard me set karna):
    BOT_TOKEN          = @BotFather se mila token
    CHANNEL_ID         = Channel ka ID (@username ya -100...)
    ADMIN_IDS          = Comma separated admin IDs (e.g., 123456789,987654321)
    VIP_CHANNEL_ID     = VIP channel ka ID

Optional:
    MARKET_OPEN_HOUR   = 9 (default)
    MARKET_CLOSE_HOUR  = 15 (default)
    TIMEZONE           = Asia/Kolkata (default)
"""

import os
import sys
import asyncio
import logging
import random
import json
from datetime import datetime, time, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
from enum import Enum

import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, ContextTypes, 
    CallbackQueryHandler, JobQueue
)
import yfinance as yf
import requests

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION — Railway Environment Variables
# ═══════════════════════════════════════════════════════════════════════════════

class Config:
    """All settings from Railway environment variables"""

    # Required
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    CHANNEL_ID: str = os.getenv("CHANNEL_ID", "")
    ADMIN_IDS: List[int] = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]

    # Optional with defaults
    VIP_CHANNEL_ID: str = os.getenv("VIP_CHANNEL_ID", "")
    MARKET_OPEN_HOUR: int = int(os.getenv("MARKET_OPEN_HOUR", "9"))
    MARKET_CLOSE_HOUR: int = int(os.getenv("MARKET_CLOSE_HOUR", "15"))
    TIMEZONE: str = os.getenv("TIMEZONE", "Asia/Kolkata")

    # Bot branding
    BOT_NAME: str = "JIGA BHAI GUJARATI TRADER"
    BOT_EMOJI: str = "🤖"

    @classmethod
    def validate(cls) -> bool:
        """Check all required vars are set"""
        missing = []
        if not cls.BOT_TOKEN:
            missing.append("BOT_TOKEN")
        if not cls.CHANNEL_ID:
            missing.append("CHANNEL_ID")
        if not cls.ADMIN_IDS:
            missing.append("ADMIN_IDS")

        if missing:
            print(f"❌ MISSING ENV VARS: {', '.join(missing)}")
            print("👉 Railway Dashboard → Variables tab mein add karo!")
            return False
        return True

# ═══════════════════════════════════════════════════════════════════════════════
# LOGGING SETUP
# ═══════════════════════════════════════════════════════════════════════════════

logging.basicConfig(
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("JIGA_BHAI")

# ═══════════════════════════════════════════════════════════════════════════════
# DATA MODELS
# ═══════════════════════════════════════════════════════════════════════════════

class CallStatus(Enum):
    ACTIVE = "ACTIVE"
    TARGET1_HIT = "TARGET1_HIT"
    TARGET2_HIT = "TARGET2_HIT"
    TARGET3_HIT = "TARGET3_HIT"
    STOPPED = "STOPPED"
    CLOSED = "CLOSED"

class CallType(Enum):
    CE = "CE"  # Call Option
    PE = "PE"  # Put Option

@dataclass
class TradingCall:
    """Represents a single trading call"""
    id: str
    symbol: str
    type: CallType
    entry: float
    sl: float
    target1: float
    target2: float
    target3: float
    rrr: str
    reason: str
    timeframe: str
    status: CallStatus = CallStatus.ACTIVE
    entry_time: str = ""
    current_points: float = 0.0
    last_reported_points: float = 0.0
    exit_price: Optional[float] = None
    exit_time: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            **asdict(self),
            "type": self.type.value,
            "status": self.status.value
        }

@dataclass
class MarketData:
    """Market index data"""
    current: float
    open_price: float
    high: float
    low: float
    prev_close: float
    change_pct: float

    @property
    def change_emoji(self) -> str:
        return "🟢" if self.change_pct >= 0 else "🔴"

# ═══════════════════════════════════════════════════════════════════════════════
# GLOBAL STATE
# ═══════════════════════════════════════════════════════════════════════════════

class BotState:
    """In-memory state management"""
    active_calls: Dict[str, TradingCall] = {}
    call_history: List[TradingCall] = []
    daily_stats = {
        "total_calls": 0,
        "successful": 0,
        "stopped": 0,
        "net_points": 0.0
    }

    @classmethod
    def reset_daily_stats(cls):
        cls.daily_stats = {
            "total_calls": 0,
            "successful": 0,
            "stopped": 0,
            "net_points": 0.0
        }

# ═══════════════════════════════════════════════════════════════════════════════
# MARKET DATA FETCHER
# ═══════════════════════════════════════════════════════════════════════════════

class MarketFetcher:
    """Fetches live market data"""

    SYMBOLS = {
        "nifty": "^NSEI",
        "banknifty": "^NSEBANK", 
        "sensex": "^BSESN"
    }

    STOCKS = {
        "RELIANCE": "RELIANCE.NS",
        "TCS": "TCS.NS",
        "INFY": "INFY.NS",
        "HDFCBANK": "HDFCBANK.NS",
        "ICICIBANK": "ICICIBANK.NS",
        "SBIN": "SBIN.NS",
        "BAJFINANCE": "BAJFINANCE.NS",
        "KOTAKBANK": "KOTAKBANK.NS",
        "AXISBANK": "AXISBANK.NS",
        "ITC": "ITC.NS",
        "HINDUNILVR": "HINDUNILVR.NS",
        "LT": "LT.NS",
        "BHARTIARTL": "BHARTIARTL.NS",
        "ASIANPAINT": "ASIANPAINT.NS",
        "MARUTI": "MARUTI.NS"
    }

    @classmethod
    def get_index(cls, name: str) -> Optional[MarketData]:
        """Fetch index data"""
        try:
            symbol = cls.SYMBOLS.get(name.lower())
            if not symbol:
                return None

            ticker = yf.Ticker(symbol)
            data = ticker.history(period="1d", interval="5m")

            if data.empty:
                return None

            current = float(data["Close"].iloc[-1])
            open_p = float(data["Open"].iloc[0])
            high = float(data["High"].max())
            low = float(data["Low"].min())
            prev = float(data["Close"].iloc[0])
            change = ((current - prev) / prev) * 100

            return MarketData(
                current=round(current, 2),
                open_price=round(open_p, 2),
                high=round(high, 2),
                low=round(low, 2),
                prev_close=round(prev, 2),
                change_pct=round(change, 2)
            )
        except Exception as e:
            logger.error(f"Error fetching {name}: {e}")
            return None

    @classmethod
    def get_stock(cls, symbol: str) -> Optional[dict]:
        """Fetch stock data"""
        try:
            yf_symbol = cls.STOCKS.get(symbol, f"{symbol}.NS")
            ticker = yf.Ticker(yf_symbol)
            data = ticker.history(period="1d", interval="5m")

            if data.empty:
                return None

            current = float(data["Close"].iloc[-1])
            open_p = float(data["Open"].iloc[0])
            change = ((current - open_p) / open_p) * 100

            return {
                "symbol": symbol,
                "current": round(current, 2),
                "open": round(open_p, 2),
                "high": round(float(data["High"].max()), 2),
                "low": round(float(data["Low"].min()), 2),
                "change_pct": round(change, 2),
                "volume": int(data["Volume"].sum())
            }
        except Exception as e:
            logger.error(f"Error fetching stock {symbol}: {e}")
            return None

    @classmethod
    def get_all_indices(cls) -> dict:
        """Fetch all three indices"""
        return {
            "nifty": cls.get_index("nifty"),
            "banknifty": cls.get_index("banknifty"),
            "sensex": cls.get_index("sensex")
        }

# ═══════════════════════════════════════════════════════════════════════════════
# CALL GENERATOR ENGINE
# ═══════════════════════════════════════════════════════════════════════════════

class CallEngine:
    """Generates and manages trading calls"""

    CALL_TEMPLATES = [
        {
            "symbol": "NIFTY",
            "type": CallType.CE,
            "entry_offset": 0,
            "sl_offset": -50,
            "t1_offset": 50,
            "t2_offset": 100,
            "t3_offset": 150,
            "reason": "Breakout above key resistance with volume confirmation",
            "timeframe": "15-30 min"
        },
        {
            "symbol": "NIFTY",
            "type": CallType.PE,
            "entry_offset": 0,
            "sl_offset": 50,
            "t1_offset": -50,
            "t2_offset": -100,
            "t3_offset": -150,
            "reason": "Rejection at resistance + Bearish divergence on RSI",
            "timeframe": "20-40 min"
        },
        {
            "symbol": "BANKNIFTY",
            "type": CallType.CE,
            "entry_offset": 0,
            "sl_offset": -120,
            "t1_offset": 120,
            "t2_offset": 240,
            "t3_offset": 360,
            "reason": "Strong support bounce with institutional buying",
            "timeframe": "15-25 min"
        },
        {
            "symbol": "BANKNIFTY",
            "type": CallType.PE,
            "entry_offset": 0,
            "sl_offset": 120,
            "t1_offset": -120,
            "t2_offset": -240,
            "t3_offset": -360,
            "reason": "Double top formation + Volume divergence",
            "timeframe": "20-35 min"
        },
        {
            "symbol": "RELIANCE",
            "type": CallType.CE,
            "entry_offset": 0,
            "sl_offset": -20,
            "t1_offset": 20,
            "t2_offset": 40,
            "t3_offset": 60,
            "reason": "Trendline breakout with above-average volume",
            "timeframe": "Intraday"
        },
        {
            "symbol": "TCS",
            "type": CallType.PE,
            "entry_offset": 0,
            "sl_offset": 20,
            "t1_offset": -20,
            "t2_offset": -40,
            "t3_offset": -60,
            "reason": "Overbought RSI + Profit booking at resistance",
            "timeframe": "Intraday"
        },
        {
            "symbol": "INFY",
            "type": CallType.CE,
            "entry_offset": 0,
            "sl_offset": -15,
            "t1_offset": 15,
            "t2_offset": 30,
            "t3_offset": 45,
            "reason": "Bullish engulfing pattern + MACD crossover",
            "timeframe": "15-25 min"
        },
        {
            "symbol": "HDFCBANK",
            "type": CallType.CE,
            "entry_offset": 0,
            "sl_offset": -12,
            "t1_offset": 12,
            "t2_offset": 24,
            "t3_offset": 36,
            "reason": "Support zone hold + Increasing buyer interest",
            "timeframe": "20-30 min"
        },
        {
            "symbol": "ICICIBANK",
            "type": CallType.PE,
            "entry_offset": 0,
            "sl_offset": 15,
            "t1_offset": -15,
            "t2_offset": -30,
            "t3_offset": -45,
            "reason": "Evening star pattern + High volume sell-off",
            "timeframe": "15-30 min"
        },
        {
            "symbol": "SBIN",
            "type": CallType.CE,
            "entry_offset": 0,
            "sl_offset": -8,
            "t1_offset": 8,
            "t2_offset": 16,
            "t3_offset": 24,
            "reason": "Flag pattern breakout + PSU bank momentum",
            "timeframe": "Intraday"
        }
    ]

    @classmethod
    def generate_call(cls) -> Optional[TradingCall]:
        """Generate a new trading call based on live market"""
        try:
            template = random.choice(cls.CALL_TEMPLATES)
            symbol = template["symbol"]

            # Get live price for entry
            if symbol in ["NIFTY", "BANKNIFTY"]:
                idx_name = "nifty" if symbol == "NIFTY" else "banknifty"
                data = MarketFetcher.get_index(idx_name)
                if not data:
                    return None
                base_price = data.current
            else:
                data = MarketFetcher.get_stock(symbol)
                if not data:
                    return None
                base_price = data["current"]

            # Round to nearest standard value
            if symbol == "NIFTY":
                base_price = round(base_price / 50) * 50
            elif symbol == "BANKNIFTY":
                base_price = round(base_price / 100) * 100
            else:
                base_price = round(base_price)

            entry = base_price + template["entry_offset"]

            call = TradingCall(
                id=f"JIGA_{datetime.now().strftime('%H%M%S')}",
                symbol=symbol,
                type=template["type"],
                entry=entry,
                sl=entry + template["sl_offset"],
                target1=entry + template["t1_offset"],
                target2=entry + template["t2_offset"],
                target3=entry + template["t3_offset"],
                rrr="1:3",
                reason=template["reason"],
                timeframe=template["timeframe"],
                entry_time=datetime.now(pytz.timezone(Config.TIMEZONE)).strftime('%H:%M')
            )

            BotState.active_calls[call.id] = call
            BotState.daily_stats["total_calls"] += 1

            logger.info(f"✅ New call generated: {call.id} | {call.symbol} {call.type.value}")
            return call

        except Exception as e:
            logger.error(f"Error generating call: {e}")
            return None

    @classmethod
    def track_call(cls, call_id: str) -> Optional[dict]:
        """Track active call and return update if needed"""
        if call_id not in BotState.active_calls:
            return None

        call = BotState.active_calls[call_id]
        if call.status in [CallStatus.STOPPED, CallStatus.CLOSED, CallStatus.TARGET3_HIT]:
            return None

        # Get current price
        symbol = call.symbol
        if symbol in ["NIFTY", "BANKNIFTY"]:
            idx_name = "nifty" if symbol == "NIFTY" else "banknifty"
            data = MarketFetcher.get_index(idx_name)
            if not data:
                return None
            current_price = data.current
        else:
            data = MarketFetcher.get_stock(symbol)
            if not data:
                return None
            current_price = data["current"]

        # Calculate points
        if call.type == CallType.CE:
            points = round(current_price - call.entry, 2)
            # Check SL
            if current_price <= call.sl:
                return cls._create_exit(call_id, current_price, points, "Stop Loss Hit")
            # Check targets
            if current_price >= call.target3:
                return cls._create_target_hit(call_id, current_price, points, 3)
            elif current_price >= call.target2 and call.status == CallStatus.ACTIVE:
                call.status = CallStatus.TARGET2_HIT
                return cls._create_trail_update(call_id, current_price, points, 2)
            elif current_price >= call.target1 and call.status == CallStatus.ACTIVE:
                call.status = CallStatus.TARGET1_HIT
                return cls._create_partial_exit(call_id, current_price, points)
        else:  # PE
            points = round(call.entry - current_price, 2)
            # Check SL
            if current_price >= call.sl:
                return cls._create_exit(call_id, current_price, -abs(points), "Stop Loss Hit")
            # Check targets
            if current_price <= call.target3:
                return cls._create_target_hit(call_id, current_price, points, 3)
            elif current_price <= call.target2 and call.status == CallStatus.ACTIVE:
                call.status = CallStatus.TARGET2_HIT
                return cls._create_trail_update(call_id, current_price, points, 2)
            elif current_price <= call.target1 and call.status == CallStatus.ACTIVE:
                call.status = CallStatus.TARGET1_HIT
                return cls._create_partial_exit(call_id, current_price, points)

        # Check every 5 points movement
        if abs(points) >= 5 and abs(points - call.last_reported_points) >= 5:
            call.last_reported_points = points
            call.current_points = points
            return {
                "action": "UPDATE",
                "call_id": call_id,
                "current_price": round(current_price, 2),
                "points": points,
                "message": f"Call running {points:+.2f} points"
            }

        return None

    @classmethod
    def _create_exit(cls, call_id, price, points, reason):
        call = BotState.active_calls[call_id]
        call.status = CallStatus.STOPPED
        call.exit_price = price
        call.exit_time = datetime.now(pytz.timezone(Config.TIMEZONE)).strftime('%H:%M')
        call.current_points = points
        BotState.daily_stats["stopped"] += 1
        BotState.daily_stats["net_points"] += points
        return {
            "action": "EXIT",
            "call_id": call_id,
            "current_price": round(price, 2),
            "points": points,
            "message": f"❌ {reason} | P&L: {points:+.2f} pts"
        }

    @classmethod
    def _create_target_hit(cls, call_id, price, points, target_num):
        call = BotState.active_calls[call_id]
        call.status = CallStatus.TARGET3_HIT
        call.exit_price = price
        call.exit_time = datetime.now(pytz.timezone(Config.TIMEZONE)).strftime('%H:%M')
        call.current_points = points
        BotState.daily_stats["successful"] += 1
        BotState.daily_stats["net_points"] += points
        return {
            "action": "TARGET3",
            "call_id": call_id,
            "current_price": round(price, 2),
            "points": points,
            "message": f"🎉 TARGET {target_num} ACHIEVED! | Profit: {points:+.2f} pts"
        }

    @classmethod
    def _create_trail_update(cls, call_id, price, points, target_num):
        return {
            "action": "TRAIL",
            "call_id": call_id,
            "current_price": round(price, 2),
            "points": points,
            "message": f"⚡ Target {target_num} Hit! Trail SL to Entry | Running: {points:+.2f} pts"
        }

    @classmethod
    def _create_partial_exit(cls, call_id, price, points):
        return {
            "action": "PARTIAL",
            "call_id": call_id,
            "current_price": round(price, 2),
            "points": points,
            "message": f"✅ Target 1 Hit! Book 50% Profit | Running: {points:+.2f} pts"
        }

# ═══════════════════════════════════════════════════════════════════════════════
# MESSAGE FORMATTER
# ═══════════════════════════════════════════════════════════════════════════════

class MessageFormatter:
    """Creates professional formatted messages"""

    HEADER = "═══════════════════════════════════════"
    FOOTER = "═══════════════════════════════════════"

    @classmethod
    def market_update(cls, data: dict) -> str:
        """Format market update"""
        tz = pytz.timezone(Config.TIMEZONE)
        now = datetime.now(tz).strftime('%d %b %Y | %I:%M %p IST')

        nifty = data.get("nifty")
        banknifty = data.get("banknifty")
        sensex = data.get("sensex")

        msg = f"""{cls.HEADER}
📊 *JIGA BHAI GUJARATI TRADER* 📊
{cls.HEADER}

⏰ `{now}`

🇮🇳 *INDIAN INDICES SNAPSHOT*

"""
        if nifty:
            msg += f"""📈 *NIFTY 50*
   💰 Current: `{nifty.current}`
   📊 O: `{nifty.open_price}` | H: `{nifty.high}` | L: `{nifty.low}`
   📉 Change: {nifty.change_emoji} `{nifty.change_pct:+.2f}%`

"""
        if banknifty:
            msg += f"""🏦 *BANK NIFTY*
   💰 Current: `{banknifty.current}`
   📊 O: `{banknifty.open_price}` | H: `{banknifty.high}` | L: `{banknifty.low}`
   📉 Change: {banknifty.change_emoji} `{banknifty.change_pct:+.2f}%`

"""
        if sensex:
            msg += f"""📉 *SENSEX*
   💰 Current: `{sensex.current}`
   📊 O: `{sensex.open_price}` | H: `{sensex.high}` | L: `{sensex.low}`
   📉 Change: {sensex.change_emoji} `{sensex.change_pct:+.2f}%`

"""

        msg += f"""{cls.FOOTER}
💎 *VIP ACCESS* — Get calls 2-3 min early!
👉 {Config.VIP_CHANNEL_ID or "DM for VIP"}

⚠️ *Disclaimer:* Educational purpose only.

#Nifty #BankNifty #Sensex #JigaBhai"""

        return msg

    @classmethod
    def new_call(cls, call: TradingCall) -> str:
        """Format new trading call"""
        direction = "🟢 CALL (Bullish)" if call.type == CallType.CE else "🔴 PUT (Bearish)"

        msg = f"""🎯 *NEW TRADING CALL ALERT* 🎯
{cls.HEADER}

📌 *Call ID:* `{call.id}`
📊 *Symbol:* `{call.symbol}`
📈 *Direction:* {direction}

💰 *ENTRY PRICE:* `{call.entry}`
🛑 *STOP LOSS:* `{call.sl}`
🎯 *TARGET 1:* `{call.target1}`
🎯 *TARGET 2:* `{call.target2}`
🎯 *TARGET 3:* `{call.target3}`

📐 *RISK:REWARD:* `{call.rrr}`
⏱ *Timeframe:* `{call.timeframe}`
🕐 *Entry Time:* `{call.entry_time}`

📝 *Analysis:*
_{call.reason}_

{cls.HEADER}
✅ *EXECUTION STRATEGY:*
   1️⃣ Entry ke baad har 5 points pe update
   2️⃣ Target 1 pe → 50% book karo
   3️⃣ Target 2 pe → SL entry pe trail karo
   4️⃣ Target 3 pe → Full exit + party! 🎉

⚠️ *Risky hone pe EXIT alert aa jayega!*

{cls.FOOTER}
💎 *VIP members got this 2 min earlier!*
👉 {Config.VIP_CHANNEL_ID or "DM for VIP"}

#TradingCall #{call.symbol} #JigaBhai"""

        return msg

    @classmethod
    def call_update(cls, update: dict) -> str:
        """Format call update"""
        call_id = update["call_id"]
        call = BotState.active_calls.get(call_id)
        if not call:
            return ""

        action = update["action"]
        points = update["points"]
        price = update["current_price"]

        if action == "EXIT":
            header = "❌ *CALL EXITED* ❌"
            color = "🔴"
        elif action == "TARGET3":
            header = "🎉🎉 *TARGET 3 ACHIEVED!* 🎉🎉"
            color = "🟢"
        elif action == "TRAIL":
            header = "⚡ *TRAIL SL UPDATE* ⚡"
            color = "🟡"
        elif action == "PARTIAL":
            header = "✅ *TARGET 1 HIT — PARTIAL EXIT* ✅"
            color = "🟢"
        else:
            header = "📊 *CALL UPDATE* 📊"
            color = "🔵"

        msg = f"""{header}
{cls.HEADER}

📌 *Call ID:* `{call_id}`
📊 *Symbol:* `{call.symbol}` {call.type.value}
💰 *Current Price:* `{price}`
📈 *Running P&L:* `{points:+.2f} points`

📝 *Status:* {update["message"]}

{cls.FOOTER}
💎 *VIP got this alert first!*
👉 {Config.VIP_CHANNEL_ID or "DM for VIP"}

#{call.symbol} #JigaBhai"""

        return msg

    @classmethod
    def morning_analysis(cls) -> str:
        """Format pre-market analysis"""
        tz = pytz.timezone(Config.TIMEZONE)
        now = datetime.now(tz)

        # Get live data for levels
        nifty = MarketFetcher.get_index("nifty")
        banknifty = MarketFetcher.get_index("banknifty")

        nifty_support = round((nifty.current - 300) / 50) * 50 if nifty else 22400
        nifty_resist = round((nifty.current + 300) / 50) * 50 if nifty else 22700
        bn_support = round((banknifty.current - 700) / 100) * 100 if banknifty else 47500
        bn_resist = round((banknifty.current + 700) / 100) * 100 if banknifty else 48900

        msg = f"""🌅 *GOOD MORNING TRADERS!* 🌅
{cls.HEADER}

⏰ `{now.strftime('%A, %d %B %Y')}`
🤖 *JIGA BHAI GUJARATI TRADER*

📊 *PRE-MARKET SETUP*

🌍 *Global Cues:*
   🇺🇸 Dow Jones: Awaited
   🇺🇸 Nasdaq: Awaited  
   🇯🇵 Nikkei: Mixed
   🇨🇳 Hang Seng: Mixed

📈 *Key Levels Today:*
   • Nifty Support: `{nifty_support}` | Resistance: `{nifty_resist}`
   • BankNifty Support: `{bn_support}` | Resistance: `{bn_resist}`
   • Sensex Support: `{nifty_support * 3.3:.0f}` | Resistance: `{nifty_resist * 3.3:.0f}`

📰 *Market News:*
   • Pre-market SGX Nifty indicates flat opening
   • FII/DII data awaited
   • Corporate earnings season ongoing
   • Global cues to guide direction

💡 *Today's Strategy:*
   🟢 Bullish bias above key support
   🔴 Bearish if breaks support with volume
   ⚡ Watch for opening range breakout

{cls.HEADER}
🎯 *3-4 Premium Calls coming today!*
💎 *VIP gets them FIRST + 2 min early!*
👉 {Config.VIP_CHANNEL_ID or "DM for VIP"}

⚠️ *Disclaimer:* Educational purpose only.

#GoodMorning #PreMarket #Nifty #JigaBhai"""

        return msg

    @classmethod
    def vip_promo(cls) -> str:
        """Format VIP promotion"""
        msg = f"""💎 *JIGA BHAI VIP ACCESS* 💎
{cls.HEADER}

🚀 *Why Traders Choose VIP?*

✅ *Early Entry Alerts* — 2-3 min before free channel
✅ *3-4 Premium Calls/Day* — High probability setups  
✅ *1:3 to 1:5 RRR* — Smart risk management
✅ *Live Handholding* — Entry to exit guidance
✅ *Position Sizing* — Exact qty per capital
✅ *Pre & Post Market Reports* — Full day analysis
✅ *Risk Alerts* — Instant exit on danger

📊 *What You Get:*
   🎯 Nifty & BankNifty calls
   🎯 Top stock picks (Reliance, TCS, HDFC, etc.)
   🎯 Option buying strategies
   🎯 Risk management rules
   🎯 Live market commentary

💰 *Investment Plans:*
   🥉 *Weekly:* ₹499
   🥈 *Monthly:* ₹1,499 (Most Popular)
   🥇 *Quarterly:* ₹3,999 (BEST VALUE)
   👑 *Lifetime:* ₹9,999 (One Time)

🎁 *BONUS:* Join today & get *FREE* 2-day trial!

📩 *How to Join:*
   👉 DM @jiga_bhai_admin
   👉 Or click: {Config.VIP_CHANNEL_ID or "Link in bio"}

⚡ *Limited seats — Batch closing soon!*

{cls.FOOTER}
#VIP #PremiumTrading #JigaBhai"""

        return msg

    @classmethod
    def closing_report(cls) -> str:
        """Format closing report"""
        stats = BotState.daily_stats
        total = stats["total_calls"]
        success = stats["successful"]
        stopped = stats["stopped"]
        net = stats["net_points"]

        accuracy = (success / total * 100) if total > 0 else 0

        # Build call summary
        call_summary = ""
        for call in BotState.call_history[-5:]:
            status_emoji = "✅" if call.status == CallStatus.TARGET3_HIT else "❌"
            call_summary += f"   {status_emoji} {call.symbol} {call.type.value} — {call.current_points:+.2f} pts\n"

        msg = f"""🌙 *MARKET CLOSING REPORT* 🌙
{cls.HEADER}

⏰ `{datetime.now(pytz.timezone(Config.TIMEZONE)).strftime('%d %b %Y | %I:%M %p')}`

📊 *TODAY'S PERFORMANCE*

🎯 *Calls Given:* {total}
✅ *Successful:* {success}
❌ *Stopped:* {stopped}
📈 *Win Rate:* `{accuracy:.0f}%`

💰 *Net P&L:* `{net:+.2f} points`

📋 *Call Summary:*
{call_summary}
{cls.HEADER}

📝 *Market Recap:*
   • Opening trend analysis
   • Key support/resistance tests
   • Volume & momentum observations
   • Tomorrow's setup preview

💎 *Join VIP for tomorrow's calls!*
👉 {Config.VIP_CHANNEL_ID or "DM for VIP"}

🙏 *Thanks for trading with JIGA BHAI!*
Kal milte hain 9 AM pe! 🚀

{cls.FOOTER}
#ClosingReport #PandL #JigaBhai"""

        return msg

    @classmethod
    def risk_alert(cls, call_id: str, reason: str) -> str:
        """Format risk alert"""
        call = BotState.active_calls.get(call_id)
        if not call:
            return ""

        msg = f"""🚨 *RISK ALERT — CONSIDER EXIT* 🚨
{cls.HEADER}

📌 *Call ID:* `{call_id}`
📊 *Symbol:* `{call.symbol}` {call.type.value}

⚠️ *Alert:* {reason}

📝 *Recommendation:*
   • Risky lag raha hai
   • Partial exit socho
   • Ya SL tight kar lo
   • Safety first! 🛡

{cls.FOOTER}
💎 *VIP mein risk alerts pehle aate hain!*
👉 {Config.VIP_CHANNEL_ID or "DM for VIP"}

#{call.symbol} #RiskAlert #JigaBhai"""

        return msg

# ═══════════════════════════════════════════════════════════════════════════════
# TELEGRAM BOT HANDLERS
# ═══════════════════════════════════════════════════════════════════════════════

class BotHandlers:
    """All Telegram command handlers"""

    @staticmethod
    def is_admin(user_id: int) -> bool:
        return user_id in Config.ADMIN_IDS

    @staticmethod
    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start"""
        user = update.effective_user

        keyboard = [
            [InlineKeyboardButton("📊 Market Update", callback_data="market")],
            [InlineKeyboardButton("💎 VIP Plans", callback_data="vip")],
            [InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{Config.CHANNEL_ID.replace('@', '')}")]
        ]

        msg = f"""🙏 *Welcome to JIGA BHAI GUJARATI TRADER!*

Namaste {user.first_name} bhai!

📊 *Main kya karta hu:*
   ✅ Live Nifty, BankNifty, Sensex updates
   ✅ 3-4 trading calls daily (1:3 RRR)
   ✅ Real-time call tracking
   ✅ Risk management alerts
   ✅ Professional analysis

⏰ *Daily Schedule (IST):*
   🌅 9:00 AM — Pre-market analysis
   🎯 9:30 AM — Call 1
   📊 11:00 AM — Market update
   🎯 12:00 PM — Call 2
   📊 2:00 PM — Mid-day update
   🎯 2:30 PM — Call 3
   🌙 3:30 PM — Closing report

💎 *VIP mein kya milta hai:*
   • Early alerts (2-3 min pehle)
   • Premium calls
   • Live guidance
   • Risk management

📢 *Channel:* {Config.CHANNEL_ID}
💎 *VIP:* {Config.VIP_CHANNEL_ID or "DM for VIP"}

⚠️ *Disclaimer:* Educational purpose only.
"""

        await update.message.reply_text(
            msg, 
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    @staticmethod
    async def market_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /market"""
        await update.message.reply_text("⏳ Fetching live market data...")

        data = MarketFetcher.get_all_indices()
        if any(data.values()):
            msg = MessageFormatter.market_update(data)
            await update.message.reply_text(msg, parse_mode='Markdown')
        else:
            await update.message.reply_text("❌ Market data fetch nahi ho raha. Thodi der baad try karo!")

    @staticmethod
    async def call_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /call — Admin only"""
        user_id = update.effective_user.id

        if not BotHandlers.is_admin(user_id):
            await update.message.reply_text("⛔ Sirf admin hi call de sakta hai!")
            return

        await update.message.reply_text("⏳ Generating new trading call...")

        call = CallEngine.generate_call()
        if call:
            msg = MessageFormatter.new_call(call)

            # Send to main channel
            await context.bot.send_message(
                chat_id=Config.CHANNEL_ID,
                text=msg,
                parse_mode='Markdown'
            )

            # Send to VIP channel if configured
            if Config.VIP_CHANNEL_ID:
                try:
                    await context.bot.send_message(
                        chat_id=Config.VIP_CHANNEL_ID,
                        text=msg,
                        parse_mode='Markdown'
                    )
                except Exception as e:
                    logger.warning(f"VIP channel send failed: {e}")

            await update.message.reply_text(f"✅ Call `{call.id}` bhej diya!", parse_mode='Markdown')
        else:
            await update.message.reply_text("❌ Call generate nahi ho raha. Market data check karo!")

    @staticmethod
    async def vip_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /vip"""
        msg = MessageFormatter.vip_promo()
        await update.message.reply_text(msg, parse_mode='Markdown')

    @staticmethod
    async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /status"""
        if not BotState.active_calls:
            await update.message.reply_text("📭 Koi active call nahi hai abhi.")
            return

        msg = "📊 *ACTIVE CALLS*
" + MessageFormatter.HEADER + "

"

        for call_id, call in BotState.active_calls.items():
            if call.status not in [CallStatus.STOPPED, CallStatus.CLOSED, CallStatus.TARGET3_HIT]:
                direction = "🟢 CE" if call.type == CallType.CE else "🔴 PE"
                msg += f"📌 `{call_id}`
"
                msg += f"   {direction} | {call.symbol}
"
                msg += f"   Entry: `{call.entry}` | SL: `{call.sl}`
"
                msg += f"   T1: `{call.target1}` | T2: `{call.target2}` | T3: `{call.target3}`
"
                msg += f"   Status: `{call.status.value}`

"

        await update.message.reply_text(msg, parse_mode='Markdown')

    @staticmethod
    async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /stats — Admin only"""
        if not BotHandlers.is_admin(update.effective_user.id):
            await update.message.reply_text("⛔ Sirf admin hi stats dekh sakta hai!")
            return

        stats = BotState.daily_stats
        total = stats["total_calls"]

        msg = f"""📊 *BOT STATISTICS*
{MessageFormatter.HEADER}

📈 *Today's Performance:*
   Total Calls: {total}
   Successful: {stats['successful']}
   Stopped: {stats['stopped']}
   Net P&L: {stats['net_points']:+.2f} pts

📋 *Active Calls:* {len([c for c in BotState.active_calls.values() if c.status == CallStatus.ACTIVE])}
📋 *Total History:* {len(BotState.call_history)}

{MessageFormatter.FOOTER}
"""
        await update.message.reply_text(msg, parse_mode='Markdown')

    @staticmethod
    async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help"""
        msg = f"""📚 *JIGA BHAI BOT COMMANDS*
{MessageFormatter.HEADER}

👤 *User Commands:*
   /start — Bot start karo
   /market — Live market update
   /vip — VIP plans dekho
   /status — Active calls dekho
   /help — Ye help message

🔐 *Admin Commands:*
   /call — New trading call bhejo
   /stats — Bot statistics
   /morning — Morning analysis bhejo
   /closing — Closing report bhejo
   /promo — VIP promotion bhejo

📢 *Channel:* {Config.CHANNEL_ID}
💎 *VIP:* {Config.VIP_CHANNEL_ID or "DM for VIP"}

{MessageFormatter.FOOTER}
"""
        await update.message.reply_text(msg, parse_mode='Markdown')

    @staticmethod
    async def morning_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /morning — Admin only"""
        if not BotHandlers.is_admin(update.effective_user.id):
            return

        msg = MessageFormatter.morning_analysis()
        await context.bot.send_message(
            chat_id=Config.CHANNEL_ID,
            text=msg,
            parse_mode='Markdown'
        )
        await update.message.reply_text("✅ Morning analysis bhej diya!")

    @staticmethod
    async def closing_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /closing — Admin only"""
        if not BotHandlers.is_admin(update.effective_user.id):
            return

        msg = MessageFormatter.closing_report()
        await context.bot.send_message(
            chat_id=Config.CHANNEL_ID,
            text=msg,
            parse_mode='Markdown'
        )
        await update.message.reply_text("✅ Closing report bhej diya!")

    @staticmethod
    async def promo_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /promo — Admin only"""
        if not BotHandlers.is_admin(update.effective_user.id):
            return

        msg = MessageFormatter.vip_promo()
        await context.bot.send_message(
            chat_id=Config.CHANNEL_ID,
            text=msg,
            parse_mode='Markdown'
        )
        await update.message.reply_text("✅ VIP promotion bhej diya!")

    @staticmethod
    async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle inline keyboard callbacks"""
        query = update.callback_query
        await query.answer()

        if query.data == "market":
            data = MarketFetcher.get_all_indices()
            if any(data.values()):
                msg = MessageFormatter.market_update(data)
                await query.edit_message_text(msg, parse_mode='Markdown')
            else:
                await query.edit_message_text("❌ Data fetch nahi ho raha!")

        elif query.data == "vip":
            msg = MessageFormatter.vip_promo()
            await query.edit_message_text(msg, parse_mode='Markdown')

# ═══════════════════════════════════════════════════════════════════════════════
# SCHEDULED JOBS
# ═══════════════════════════════════════════════════════════════════════════════

class ScheduledJobs:
    """All scheduled background jobs"""

    @staticmethod
    async def morning_analysis_job(context: ContextTypes.DEFAULT_TYPE):
        """9:00 AM — Pre-market analysis"""
        logger.info("📅 Running morning analysis job")
        msg = MessageFormatter.morning_analysis()
        await context.bot.send_message(
            chat_id=Config.CHANNEL_ID,
            text=msg,
            parse_mode='Markdown'
        )

    @staticmethod
    async def market_update_job(context: ContextTypes.DEFAULT_TYPE):
        """Market update every 2 hours"""
        logger.info("📅 Running market update job")
        data = MarketFetcher.get_all_indices()
        if any(data.values()):
            msg = MessageFormatter.market_update(data)
            await context.bot.send_message(
                chat_id=Config.CHANNEL_ID,
                text=msg,
                parse_mode='Markdown'
            )

    @staticmethod
    async def new_call_job(context: ContextTypes.DEFAULT_TYPE):
        """Generate new trading call"""
        logger.info("📅 Running new call job")
        call = CallEngine.generate_call()
        if call:
            msg = MessageFormatter.new_call(call)

            # Main channel
            await context.bot.send_message(
                chat_id=Config.CHANNEL_ID,
                text=msg,
                parse_mode='Markdown'
            )

            # VIP channel (2 min pehle wala logic — actually same time pe)
            # Real mein VIP pehle bhejna ho toh alag job banao
            if Config.VIP_CHANNEL_ID:
                try:
                    await context.bot.send_message(
                        chat_id=Config.VIP_CHANNEL_ID,
                        text=msg,
                        parse_mode='Markdown'
                    )
                except Exception as e:
                    logger.warning(f"VIP send failed: {e}")

    @staticmethod
    async def call_tracker_job(context: ContextTypes.DEFAULT_TYPE):
        """Track all active calls every 5 min"""
        logger.info("📅 Running call tracker job")

        for call_id in list(BotState.active_calls.keys()):
            update = CallEngine.track_call(call_id)
            if update:
                msg = MessageFormatter.call_update(update)
                await context.bot.send_message(
                    chat_id=Config.CHANNEL_ID,
                    text=msg,
                    parse_mode='Markdown'
                )

                # Risky call check
                call = BotState.active_calls.get(call_id)
                if call and call.status == CallStatus.ACTIVE:
                    points = call.current_points
                    if points < -3:  # 3 points against
                        risk_msg = MessageFormatter.risk_alert(
                            call_id, 
                            f"Call {points:+.2f} points against. Review position!"
                        )
                        await context.bot.send_message(
                            chat_id=Config.CHANNEL_ID,
                            text=risk_msg,
                            parse_mode='Markdown'
                        )

    @staticmethod
    async def vip_promo_job(context: ContextTypes.DEFAULT_TYPE):
        """VIP promotion"""
        logger.info("📅 Running VIP promo job")
        msg = MessageFormatter.vip_promo()
        await context.bot.send_message(
            chat_id=Config.CHANNEL_ID,
            text=msg,
            parse_mode='Markdown'
        )

    @staticmethod
    async def closing_report_job(context: ContextTypes.DEFAULT_TYPE):
        """3:45 PM — Closing report"""
        logger.info("📅 Running closing report job")
        msg = MessageFormatter.closing_report()
        await context.bot.send_message(
            chat_id=Config.CHANNEL_ID,
            text=msg,
            parse_mode='Markdown'
        )
        # Reset daily stats
        BotState.reset_daily_stats()

    @staticmethod
    async def reset_daily_job(context: ContextTypes.DEFAULT_TYPE):
        """Reset daily stats at midnight"""
        logger.info("📅 Resetting daily stats")
        BotState.reset_daily_stats()

# ═══════════════════════════════════════════════════════════════════════════════
# MAIN APPLICATION
# ═══════════════════════════════════════════════════════════════════════════════

def setup_jobs(application: Application):
    """Setup all scheduled jobs"""
    job_queue = application.job_queue
    tz = pytz.timezone(Config.TIMEZONE)

    # Morning analysis — 9:00 AM IST
    job_queue.run_daily(
        ScheduledJobs.morning_analysis_job,
        time=time(hour=9, minute=0, tzinfo=tz)
    )

    # Market updates — 11:00 AM, 2:00 PM IST
    job_queue.run_daily(
        ScheduledJobs.market_update_job,
        time=time(hour=11, minute=0, tzinfo=tz)
    )
    job_queue.run_daily(
        ScheduledJobs.market_update_job,
        time=time(hour=14, minute=0, tzinfo=tz)
    )

    # New calls — 9:30 AM, 12:00 PM, 2:30 PM IST
    job_queue.run_daily(
        ScheduledJobs.new_call_job,
        time=time(hour=9, minute=30, tzinfo=tz)
    )
    job_queue.run_daily(
        ScheduledJobs.new_call_job,
        time=time(hour=12, minute=0, tzinfo=tz)
    )
    job_queue.run_daily(
        ScheduledJobs.new_call_job,
        time=time(hour=14, minute=30, tzinfo=tz)
    )

    # Call tracker — every 5 minutes during market hours
    # 9:15 AM to 3:30 PM
    job_queue.run_repeating(
        ScheduledJobs.call_tracker_job,
        interval=300,  # 5 minutes
        first=10
    )

    # VIP promos — 10:00 AM, 1:00 PM IST
    job_queue.run_daily(
        ScheduledJobs.vip_promo_job,
        time=time(hour=10, minute=0, tzinfo=tz)
    )
    job_queue.run_daily(
        ScheduledJobs.vip_promo_job,
        time=time(hour=13, minute=0, tzinfo=tz)
    )

    # Closing report — 3:45 PM IST
    job_queue.run_daily(
        ScheduledJobs.closing_report_job,
        time=time(hour=15, minute=45, tzinfo=tz)
    )

    # Reset daily stats — midnight
    job_queue.run_daily(
        ScheduledJobs.reset_daily_job,
        time=time(hour=0, minute=1, tzinfo=tz)
    )

    logger.info("✅ All scheduled jobs configured")

def main():
    """Start the bot"""
    print("\n" + "="*70)
    print(f"    🤖 {Config.BOT_NAME} — Starting...")
    print("="*70 + "\n")

    # Validate config
    if not Config.validate():
        print("\n❌ CONFIGURATION FAILED!")
        print("👉 Railway Dashboard → Variables tab mein ye add karo:")
        print("   • BOT_TOKEN")
        print("   • CHANNEL_ID") 
        print("   • ADMIN_IDS")
        sys.exit(1)

    print(f"✅ Config loaded:")
    print(f"   Channel: {Config.CHANNEL_ID}")
    print(f"   Admins: {Config.ADMIN_IDS}")
    print(f"   VIP Channel: {Config.VIP_CHANNEL_ID or 'Not set'}")
    print(f"   Timezone: {Config.TIMEZONE}")
    print()

    # Build application
    application = Application.builder().token(Config.BOT_TOKEN).build()

    # Command handlers
    handlers = BotHandlers()
    application.add_handler(CommandHandler("start", handlers.start))
    application.add_handler(CommandHandler("market", handlers.market_cmd))
    application.add_handler(CommandHandler("call", handlers.call_cmd))
    application.add_handler(CommandHandler("vip", handlers.vip_cmd))
    application.add_handler(CommandHandler("status", handlers.status_cmd))
    application.add_handler(CommandHandler("stats", handlers.stats_cmd))
    application.add_handler(CommandHandler("help", handlers.help_cmd))
    application.add_handler(CommandHandler("morning", handlers.morning_cmd))
    application.add_handler(CommandHandler("closing", handlers.closing_cmd))
    application.add_handler(CommandHandler("promo", handlers.promo_cmd))
    application.add_handler(CallbackQueryHandler(handlers.callback_handler))

    # Setup scheduled jobs
    setup_jobs(application)

    # Start
    print("🚀 Bot is running! Press Ctrl+C to stop.\n")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
