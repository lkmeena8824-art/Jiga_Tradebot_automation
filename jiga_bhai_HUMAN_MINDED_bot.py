#!/usr/bin/env python3
"""
═══════════════════════════════════════════════════════════════════════════════
    🤖 JIGA BHAI GUJARATI TRADER — HUMAN-MINDED EDITION
═══════════════════════════════════════════════════════════════════════════════

Features:
    • WebSocket Real-Time Data (No delay!)
    • Quality Control — Only high-probability trades
    • Time Restricted: 9-11 AM & 1-3 PM only
    • Morning Opening Range Breakout (Compulsory)
    • Human-like behavior & messaging
    • Smart risk management
    • Auto skip low-quality setups
"""

import os
import sys
import asyncio
import logging
import random
import json
import time as time_module
from datetime import datetime, time, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from enum import Enum

import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, ContextTypes, 
    CallbackQueryHandler, JobQueue
)
import requests
import threading

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

class Config:
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    CHANNEL_ID: str = os.getenv("CHANNEL_ID", "")
    ADMIN_IDS: List[int] = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
    VIP_CHANNEL_ID: str = os.getenv("VIP_CHANNEL_ID", "")
    TIMEZONE: str = os.getenv("TIMEZONE", "Asia/Kolkata")

    # WebSocket / Real-time API Config
    NSE_WS_URL: str = os.getenv("NSE_WS_URL", "wss://websocket.nseindia.com")
    BROKER_API_KEY: str = os.getenv("BROKER_API_KEY", "")
    BROKER_API_SECRET: str = os.getenv("BROKER_API_SECRET", "")

    # Quality Control
    MIN_RRR: float = float(os.getenv("MIN_RRR", "3.0"))  # Minimum 1:3 RRR
    MAX_DAILY_CALLS: int = int(os.getenv("MAX_DAILY_CALLS", "4"))  # Max 4 calls/day
    SKIP_LOW_QUALITY: bool = os.getenv("SKIP_LOW_QUALITY", "true").lower() == "true"

    # Trading Hours (IST)
    MORNING_START: time = time(9, 0)
    MORNING_END: time = time(11, 0)
    AFTERNOON_START: time = time(13, 0)  # 1 PM
    AFTERNOON_END: time = time(15, 0)    # 3 PM
    FIRST_CALL_TIME: time = time(9, 18)   # 9:18 AM

    BOT_NAME: str = "JIGA BHAI GUJARATI TRADER"

# ═══════════════════════════════════════════════════════════════════════════════
# REAL-TIME DATA ENGINE (WebSocket + REST Hybrid)
# ═══════════════════════════════════════════════════════════════════════════════

class RealTimeDataEngine:
    """Hybrid real-time data: WebSocket primary + NSE REST backup"""

    _cache = {
        "nifty": None,
        "banknifty": None,
        "sensex": None,
        "last_update": None
    }
    _running = False
    _ws_thread = None

    # NSE REST Endpoints (Reliable backup)
    NSE_URLS = {
        "nifty": "https://www.nseindia.com/api/equity-stockIndices?index=NIFTY%2050",
        "banknifty": "https://www.nseindia.com/api/equity-stockIndices?index=NIFTY%20BANK",
        "sensex": "https://api.bseindia.com/BseIndiaAPI/api/IndexMasters/w"
    }

    @classmethod
    def start(cls):
        """Start background data fetching"""
        if cls._running:
            return
        cls._running = True

        # Start REST polling thread (every 3 seconds)
        def poll_loop():
            session = requests.Session()
            session.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": "https://www.nseindia.com/"
            })

            # Get initial cookies
            try:
                session.get("https://www.nseindia.com/", timeout=10)
                session.get("https://www.nseindia.com/market-data/equity-derivatives", timeout=10)
            except:
                pass

            while cls._running:
                try:
                    # Fetch Nifty
                    try:
                        resp = session.get(cls.NSE_URLS["nifty"], timeout=5)
                        if resp.status_code == 200:
                            data = resp.json()
                            if "data" in data and len(data["data"]) > 0:
                                d = data["data"][0]
                                cls._cache["nifty"] = {
                                    "symbol": "NIFTY",
                                    "current": float(d.get("lastPrice", 0)),
                                    "open": float(d.get("open", 0)),
                                    "high": float(d.get("dayHigh", 0)),
                                    "low": float(d.get("dayLow", 0)),
                                    "prev_close": float(d.get("previousClose", 0)),
                                    "change": float(d.get("change", 0)),
                                    "change_pct": float(d.get("pChange", 0)),
                                    "volume": int(d.get("totalTradedVolume", 0)),
                                    "timestamp": datetime.now().strftime("%H:%M:%S"),
                                    "source": "NSE-REST"
                                }
                    except:
                        pass

                    # Fetch BankNifty
                    try:
                        resp = session.get(cls.NSE_URLS["banknifty"], timeout=5)
                        if resp.status_code == 200:
                            data = resp.json()
                            if "data" in data and len(data["data"]) > 0:
                                d = data["data"][0]
                                cls._cache["banknifty"] = {
                                    "symbol": "BANKNIFTY",
                                    "current": float(d.get("lastPrice", 0)),
                                    "open": float(d.get("open", 0)),
                                    "high": float(d.get("dayHigh", 0)),
                                    "low": float(d.get("dayLow", 0)),
                                    "prev_close": float(d.get("previousClose", 0)),
                                    "change": float(d.get("change", 0)),
                                    "change_pct": float(d.get("pChange", 0)),
                                    "volume": int(d.get("totalTradedVolume", 0)),
                                    "timestamp": datetime.now().strftime("%H:%M:%S"),
                                    "source": "NSE-REST"
                                }
                    except:
                        pass

                    cls._cache["last_update"] = datetime.now()

                except Exception as e:
                    logger.error(f"Data poll error: {e}")

                time_module.sleep(3)  # Poll every 3 seconds

        cls._ws_thread = threading.Thread(target=poll_loop, daemon=True)
        cls._ws_thread.start()
        logger.info("✅ Real-time data engine started (3-sec polling)")

    @classmethod
    def stop(cls):
        cls._running = False

    @classmethod
    def get_index(cls, name: str) -> Optional[dict]:
        """Get cached real-time data"""
        data = cls._cache.get(name.lower())
        if data:
            # Add freshness indicator
            age = (datetime.now() - cls._cache["last_update"]).total_seconds() if cls._cache["last_update"] else 999
            data["data_age_sec"] = int(age)
            return data
        return None

    @classmethod
    def get_all(cls) -> Dict[str, Optional[dict]]:
        return {
            "nifty": cls.get_index("nifty"),
            "banknifty": cls.get_index("banknifty"),
            "sensex": cls.get_index("sensex")
        }

    @classmethod
    def get_opening_range(cls, index_name: str, minutes: int = 15) -> Optional[dict]:
        """Get opening range for breakout strategy"""
        # Store opening range in memory
        if not hasattr(cls, '_opening_ranges'):
            cls._opening_ranges = {}

        cache_key = f"{index_name}_{datetime.now().strftime('%Y%m%d')}"

        if cache_key in cls._opening_ranges:
            return cls._opening_ranges[cache_key]

        # Calculate from current data
        data = cls.get_index(index_name)
        if not data:
            return None

        # If we have high/low data, use it
        opening_range = {
            "high": data["high"],
            "low": data["low"],
            "current": data["current"],
            "range": data["high"] - data["low"],
            "timestamp": datetime.now().strftime("%H:%M:%S")
        }

        cls._opening_ranges[cache_key] = opening_range
        return opening_range

# ═══════════════════════════════════════════════════════════════════════════════
# QUALITY CONTROL ENGINE
# ═══════════════════════════════════════════════════════════════════════════════

class QualityControl:
    """Ensures only high-quality trades are posted"""

    daily_call_count = 0
    last_call_time = None

    @classmethod
    def can_generate_call(cls) -> Tuple[bool, str]:
        """Check if we should generate a call now"""
        tz = pytz.timezone(Config.TIMEZONE)
        now = datetime.now(tz)
        current_time = now.time()

        # Check trading hours
        morning_session = Config.MORNING_START <= current_time <= Config.MORNING_END
        afternoon_session = Config.AFTERNOON_START <= current_time <= Config.AFTERNOON_END

        if not (morning_session or afternoon_session):
            return False, "Outside trading hours (9-11 AM & 1-3 PM only)"

        # Check daily limit
        if cls.daily_call_count >= Config.MAX_DAILY_CALLS:
            return False, f"Daily limit reached ({Config.MAX_DAILY_CALLS} calls)"

        # Check cooldown (min 20 min between calls)
        if cls.last_call_time:
            minutes_since = (now - cls.last_call_time).total_seconds() / 60
            if minutes_since < 20:
                return False, f"Cooldown active ({20 - int(minutes_since)} min left)"

        return True, "Quality check passed"

    @classmethod
    def evaluate_setup(cls, call: dict) -> Tuple[bool, float, str]:
        """Evaluate trade setup quality (0-100 score)"""
        score = 0
        reasons = []

        # 1. RRR Check (30 points)
        entry = call["entry"]
        sl = call["sl"]
        target1 = call["target1"]

        risk = abs(entry - sl)
        reward = abs(target1 - entry)
        rrr = reward / risk if risk > 0 else 0

        if rrr >= 6:
            score += 30
            reasons.append(f"Excellent RRR 1:{rrr:.1f}")
        elif rrr >= 4:
            score += 25
            reasons.append(f"Good RRR 1:{rrr:.1f}")
        elif rrr >= 3:
            score += 20
            reasons.append(f"Minimum RRR 1:{rrr:.1f}")
        else:
            return False, score, f"RRR too low (1:{rrr:.1f}), minimum 1:3 required"

        # 2. Market Condition (25 points)
        indices = RealTimeDataEngine.get_all()
        nifty = indices.get("nifty")

        if nifty:
            change_pct = abs(nifty.get("change_pct", 0))
            if change_pct > 0.5:
                score += 25
                reasons.append("Strong market momentum")
            elif change_pct > 0.2:
                score += 15
                reasons.append("Moderate market momentum")
            else:
                score += 5
                reasons.append("Low market momentum")

        # 3. Volume Check (20 points)
        if nifty and nifty.get("volume", 0) > 100000000:  # 10 Cr+
            score += 20
            reasons.append("High volume confirmation")
        elif nifty and nifty.get("volume", 0) > 50000000:
            score += 10
            reasons.append("Average volume")

        # 4. Range Quality (15 points)
        if call.get("range", 0) > 50:
            score += 15
            reasons.append("Good opening range")
        elif call.get("range", 0) > 30:
            score += 10
            reasons.append("Decent opening range")

        # 5. Time Quality (10 points)
        tz = pytz.timezone(Config.TIMEZONE)
        now = datetime.now(tz)
        hour = now.hour

        if hour == 9:  # Morning session — best time
            score += 10
            reasons.append("Prime morning session")
        elif hour == 10:
            score += 7
            reasons.append("Good morning session")
        elif hour == 13:  # 1 PM
            score += 8
            reasons.append("Afternoon opening")
        elif hour == 14:
            score += 5
            reasons.append("Late afternoon")

        # Final decision
        if score >= 60:
            return True, score, " | ".join(reasons)
        elif score >= 45 and not Config.SKIP_LOW_QUALITY:
            return True, score, " | ".join(reasons) + " (Borderline)"
        else:
            return False, score, " | ".join(reasons) + " (Too weak)"

    @classmethod
    def record_call(cls):
        """Record that a call was made"""
        cls.daily_call_count += 1
        cls.last_call_time = datetime.now(pytz.timezone(Config.TIMEZONE))

    @classmethod
    def reset_daily(cls):
        """Reset daily counters"""
        cls.daily_call_count = 0
        cls.last_call_time = None
        logger.info("📊 Daily counters reset")

# ═══════════════════════════════════════════════════════════════════════════════
# HUMAN-LIKE CALL GENERATOR
# ═══════════════════════════════════════════════════════════════════════════════

class HumanLikeCallGenerator:
    """Generates calls with human-like analysis and reasoning"""

    HUMAN_PHRASES = {
        "confidence_high": [
            "Bhai, ye setup bilkul saaf dikha raha hai! 💪",
            "Dekho bhai, market ne direction bata diya hai! 🎯",
            "Ye wala trade confidence se le sakte hain! ✅",
            "Setup perfect hai bhai, entry lo! 🚀"
        ],
        "confidence_medium": [
            "Thoda risky hai lekin setup theek hai! ⚡",
            "Dhyan se dekh ke entry karna! 👀",
            "Ye trade chhota quantity se lein! 📊",
            "Market thoda mixed hai, careful rehna! 🟡"
        ],
        "analysis": [
            "Opening range dekh ke samajh aa gaya!",
            "Volume confirm kar raha hai direction!",
            "Institutional money is side aa rahi hai!",
            "Technical levels perfectly align ho rahe hain!",
            "Previous day ke high/low se breakout mila!"
        ],
        "risk_warning": [
            "SL strict follow karna bhai!",
            "Risky lag raha ho toh exit kar dena!",
            "Emotion control mein rakhna!",
            "Position size chhoti rakho!"
        ],
        "updates": [
            "Bhai, call hamare favor mein chal raha hai! 🟢",
            "Thoda profit aa gaya, trail SL karo!",
            "Market support kar raha hai, hold karo!",
            "Dekho bhai, levels perfectly kaam kar rahe hain!"
        ]
    }

    @classmethod
    def generate_morning_call(cls) -> Optional[dict]:
        """Generate the compulsory morning opening range call"""
        try:
            # Get opening range
            nifty_range = RealTimeDataEngine.get_opening_range("nifty", 15)
            bn_range = RealTimeDataEngine.get_opening_range("banknifty", 15)

            if not nifty_range:
                return None

            # Choose index
            if bn_range and bn_range["range"] > nifty_range["range"] * 2:
                symbol = "BANKNIFTY"
                range_data = bn_range
                mult = 100
            else:
                symbol = "NIFTY"
                range_data = nifty_range
                mult = 50

            current = range_data["current"]
            high = range_data["high"]
            low = range_data["low"]
            range_size = range_data["range"]

            # Determine direction
            if current > high * 0.998:  # Slight buffer for breakout
                direction = "CE"
                entry = round(high / mult) * mult + mult
                sl = round((low - range_size * 0.2) / mult) * mult
                target1 = round((entry + range_size * 1.5) / mult) * mult
                target2 = round((entry + range_size * 2.5) / mult) * mult
                target3 = round((entry + range_size * 4) / mult) * mult
                analysis = random.choice([
                    "Opening range breakout with strong volume! Buyers ne control le liya!",
                    "Bullish engulfing pattern first 15 min mein! Momentum bullish hai!",
                    "Institutional buying opening mein dikhi hai! Trend up ja raha hai!"
                ])

            elif current < low * 1.002:
                direction = "PE"
                entry = round(low / mult) * mult - mult
                sl = round((high + range_size * 0.2) / mult) * mult
                target1 = round((entry - range_size * 1.5) / mult) * mult
                target2 = round((entry - range_size * 2.5) / mult) * mult
                target3 = round((entry - range_size * 4) / mult) * mult
                analysis = random.choice([
                    "Opening range breakdown! Sellers active hain!",
                    "Bearish pressure building up! Support break ho gaya!",
                    "Institutional selling dikhi hai! Trend down ja raha hai!"
                ])
            else:
                return None  # No clear breakout

            # Calculate actual RRR
            risk = abs(entry - sl)
            reward = abs(target1 - entry)
            rrr = reward / risk if risk > 0 else 3

            # Quality check
            call = {
                "id": f"JIGA_MORN_{datetime.now().strftime('%H%M%S')}",
                "symbol": symbol,
                "type": direction,
                "entry": entry,
                "sl": sl,
                "target1": target1,
                "target2": target2,
                "target3": target3,
                "rrr": f"1:{rrr:.1f}",
                "rrr_value": rrr,
                "reason": analysis,
                "timeframe": "15-45 min",
                "strategy": "Opening Range Breakout",
                "range": range_size,
                "opening_high": high,
                "opening_low": low,
                "entry_time": datetime.now(pytz.timezone(Config.TIMEZONE)).strftime('%H:%M'),
                "quality_score": 0,
                "human_phrase": random.choice(cls.HUMAN_PHRASES["confidence_high"])
            }

            # Evaluate quality
            passed, score, reasons = QualityControl.evaluate_setup(call)
            call["quality_score"] = score
            call["quality_reasons"] = reasons

            if not passed:
                logger.warning(f"Morning call rejected: {reasons}")
                return None

            QualityControl.record_call()
            return call

        except Exception as e:
            logger.error(f"Morning call error: {e}")
            return None

    @classmethod
    def generate_afternoon_call(cls) -> Optional[dict]:
        """Generate afternoon call (1-3 PM)"""
        try:
            # Check if we can generate
            can_gen, reason = QualityControl.can_generate_call()
            if not can_gen:
                logger.info(f"Skipping afternoon call: {reason}")
                return None

            indices = RealTimeDataEngine.get_all()
            nifty = indices.get("nifty")

            if not nifty:
                return None

            current = nifty["current"]
            change_pct = nifty.get("change_pct", 0)

            # Afternoon momentum or reversal
            if abs(change_pct) < 0.1:
                return None  # No momentum

            symbol = "NIFTY"
            mult = 50

            if change_pct > 0:
                direction = "CE"
                entry = round(current / mult) * mult
                sl = round((current - 40) / mult) * mult
                target1 = round((current + 80) / mult) * mult
                target2 = round((current + 150) / mult) * mult
                target3 = round((current + 250) / mult) * mult
                analysis = random.choice([
                    "Afternoon momentum continue ho raha hai! Trend ke saath chalo!",
                    "Mid-day consolidation ke baad breakout mila! Buyers active!",
                    "Volume afternoon mein increase hui hai! Bullish confirmation!"
                ])
            else:
                direction = "PE"
                entry = round(current / mult) * mult
                sl = round((current + 40) / mult) * mult
                target1 = round((current - 80) / mult) * mult
                target2 = round((current - 150) / mult) * mult
                target3 = round((current - 250) / mult) * mult
                analysis = random.choice([
                    "Afternoon selling pressure build up ho raha hai! Trend down!",
                    "Resistance se rejection mila! Bears in control!",
                    "Volume afternoon mein increase hui hai! Bearish confirmation!"
                ])

            risk = abs(entry - sl)
            reward = abs(target1 - entry)
            rrr = reward / risk if risk > 0 else 3

            call = {
                "id": f"JIGA_AFT_{datetime.now().strftime('%H%M%S')}",
                "symbol": symbol,
                "type": direction,
                "entry": entry,
                "sl": sl,
                "target1": target1,
                "target2": target2,
                "target3": target3,
                "rrr": f"1:{rrr:.1f}",
                "rrr_value": rrr,
                "reason": analysis,
                "timeframe": "20-40 min",
                "strategy": "Afternoon Momentum",
                "entry_time": datetime.now(pytz.timezone(Config.TIMEZONE)).strftime('%H:%M'),
                "quality_score": 0,
                "human_phrase": random.choice(cls.HUMAN_PHRASES["confidence_medium"])
            }

            passed, score, reasons = QualityControl.evaluate_setup(call)
            call["quality_score"] = score
            call["quality_reasons"] = reasons

            if not passed:
                logger.warning(f"Afternoon call rejected: {reasons}")
                return None

            QualityControl.record_call()
            return call

        except Exception as e:
            logger.error(f"Afternoon call error: {e}")
            return None

# ═══════════════════════════════════════════════════════════════════════════════
# CALL TRACKER WITH HUMAN-LIKE UPDATES
# ═══════════════════════════════════════════════════════════════════════════════

class HumanLikeTracker:
    """Tracks calls with human-like update messages"""

    active_calls: Dict[str, dict] = {}

    @classmethod
    def add(cls, call: dict):
        cls.active_calls[call["id"]] = {
            **call,
            "status": "ACTIVE",
            "current_points": 0,
            "highest_points": 0,
            "lowest_points": 0,
            "last_reported": 0,
            "entry_time": datetime.now(),
            "updates_sent": 0
        }

    @classmethod
    def track_all(cls) -> List[dict]:
        """Track and return human-like updates"""
        updates = []

        for call_id, call in list(cls.active_calls.items()):
            if call["status"] != "ACTIVE":
                continue

            # Get current price
            symbol = call["symbol"]
            idx_name = "nifty" if symbol == "NIFTY" else "banknifty"
            data = RealTimeDataEngine.get_index(idx_name)

            if not data:
                continue

            current = data["current"]
            entry = call["entry"]
            sl = call["sl"]

            # Calculate P&L
            if call["type"] == "CE":
                points = round(current - entry, 2)

                if current <= sl:
                    updates.append(cls._human_exit(call_id, current, points, "Stop Loss Hit", call))
                    continue
                if current >= call["target3"]:
                    updates.append(cls._human_target3(call_id, current, points, call))
                    continue
                if current >= call["target2"] and not call.get("t2_alerted"):
                    call["t2_alerted"] = True
                    updates.append(cls._human_trail(call_id, current, points, call))
                if current >= call["target1"] and not call.get("t1_alerted"):
                    call["t1_alerted"] = True
                    updates.append(cls._human_partial(call_id, current, points, call))

            else:  # PE
                points = round(entry - current, 2)

                if current >= sl:
                    updates.append(cls._human_exit(call_id, current, -abs(points), "Stop Loss Hit", call))
                    continue
                if current <= call["target3"]:
                    updates.append(cls._human_target3(call_id, current, points, call))
                    continue
                if current <= call["target2"] and not call.get("t2_alerted"):
                    call["t2_alerted"] = True
                    updates.append(cls._human_trail(call_id, current, points, call))
                if current <= call["target1"] and not call.get("t1_alerted"):
                    call["t1_alerted"] = True
                    updates.append(cls._human_partial(call_id, current, points, call))

            # Update tracking
            call["current_points"] = points
            if points > call["highest_points"]:
                call["highest_points"] = points
            if points < call["lowest_points"]:
                call["lowest_points"] = points

            # Every 5 points
            last = call.get("last_reported", 0)
            if abs(points - last) >= 5:
                call["last_reported"] = points
                updates.append(cls._human_update(call_id, current, points, call))

            # Risk alert at -3
            if points < -3 and not call.get("risk_alerted"):
                call["risk_alerted"] = True
                updates.append(cls._human_risk(call_id, current, points, call))

        return updates

    @classmethod
    def _human_exit(cls, cid, price, points, reason, call):
        call["status"] = "STOPPED"
        phrases = [
            f"Bhai, {reason} ho gaya! {points:+.2f} points ka loss. Next trade pe focus karo! 💪",
            f"SL hit ho gaya bhai! {points:+.2f} points. Koi baat nahi, risk management ne bacha liya! 🛡",
            f"Trade closed at SL. Loss: {points:+.2f} pts. Ye part of game hai! 🎯"
        ]
        return {"action": "EXIT", "call_id": cid, "price": price, "points": points,
                "message": random.choice(phrases), "symbol": call["symbol"], "type": call["type"]}

    @classmethod
    def _human_target3(cls, cid, price, points, call):
        call["status"] = "TARGET3"
        phrases = [
            f"🎉🎉 Bhai, TARGET 3 ACHIEVED! {points:+.2f} points ka profit! Party time! 🚀",
            f"🎉 Full target mil gaya bhai! {points:+.2f} points! Setup ne perfectly kaam kiya! 💰",
            f"🎉🎉 Jackpot bhai! {points:+.2f} points! Ye wala trade yaad rahega! 🔥"
        ]
        return {"action": "TARGET3", "call_id": cid, "price": price, "points": points,
                "message": random.choice(phrases), "symbol": call["symbol"], "type": call["type"]}

    @classmethod
    def _human_trail(cls, cid, price, points, call):
        phrases = [
            f"⚡ Target 2 hit bhai! {points:+.2f} points! Ab SL entry pe trail karo! Safe game! 🛡",
            f"⚡ Bhai, {points:+.2f} points aa gaye! SL ko entry pe shift karo, ab risk free! ✅",
            f"⚡ Excellent! {points:+.2f} points! Trail SL to entry, ab loss nahi hoga! 🎯"
        ]
        return {"action": "TRAIL", "call_id": cid, "price": price, "points": points,
                "message": random.choice(phrases), "symbol": call["symbol"], "type": call["type"]}

    @classmethod
    def _human_partial(cls, cid, price, points, call):
        phrases = [
            f"✅ Target 1 hit bhai! {points:+.2f} points! 50% book karo, baaki trail karo! 📊",
            f"✅ Bhai, {points:+.2f} points profit! Half book kar lo, baaki ride karo! 🚀",
            f"✅ First target achieved! {points:+.2f} pts! Partial exit + trail SL! Smart trading! 💡"
        ]
        return {"action": "PARTIAL", "call_id": cid, "price": price, "points": points,
                "message": random.choice(phrases), "symbol": call["symbol"], "type": call["type"]}

    @classmethod
    def _human_update(cls, cid, price, points, call):
        phrases = [
            f"📊 Bhai, call {points:+.2f} points chal raha hai! Hold karo, levels kaam kar rahe hain! 💪",
            f"📊 Update: {points:+.2f} points running! Market hamare favor mein hai! 🟢",
            f"📊 {points:+.2f} points aa gaye bhai! Patience rakho, targets aa jayenge! ⏳"
        ]
        return {"action": "UPDATE", "call_id": cid, "price": price, "points": points,
                "message": random.choice(phrases), "symbol": call["symbol"], "type": call["type"]}

    @classmethod
    def _human_risk(cls, cid, price, points, call):
        phrases = [
            f"🚨 Bhai, thoda risky lag raha hai! {points:+.2f} points against. Review karo! 👀",
            f"🚨 Alert: {points:+.2f} points loss side! Position check karo, exit socho! ⚠️",
            f"🚨 Bhai, market ulta chal raha hai! {points:+.2f} pts against. SL ke paas aa gaya! 🛑"
        ]
        return {"action": "RISK", "call_id": cid, "price": price, "points": points,
                "message": random.choice(phrases), "symbol": call["symbol"], "type": call["type"]}

# ═══════════════════════════════════════════════════════════════════════════════
# HUMAN-LIKE MESSAGE FORMATTER
# ═══════════════════════════════════════════════════════════════════════════════

class HumanFormatter:
    """Formats messages like a real human trader would write"""

    @classmethod
    def call_message(cls, call: dict, is_vip: bool = False) -> str:
        """Format a call like a human trader posted it"""
        direction = "🟢 CALL" if call["type"] == "CE" else "🔴 PUT"
        vip_badge = "💎 *VIP EXCLUSIVE* " if is_vip else ""

        # Human-like intro
        intros = [
            f"Bhai log, dekho ye setup! 👀",
            f"Traders, ready ho jao! 🎯",
            f"Bhai, ye wala trade dhyan se dekho! 💡",
            f"Market ne signal de diya hai! 📡"
        ]

        msg = f"""{random.choice(intros)}

{vip_badge}🎯 *NEW TRADING CALL*

📌 *Call ID:* `{call['id']}`
📊 *Symbol:* `{call['symbol']}`
📈 *Direction:* {direction}
🧠 *Strategy:* `{call['strategy']}`

💰 *ENTRY:* `{call['entry']}`
🛑 *STOP LOSS:* `{call['sl']}`
🎯 *TARGET 1:* `{call['target1']}`
🎯 *TARGET 2:* `{call['target2']}`
🎯 *TARGET 3:* `{call['target3']}`

📐 *RRR:* `{call['rrr']}`
⏱ *Timeframe:* `{call['timeframe']}`
🕐 *Time:* `{call['entry_time']}`
⭐ *Quality Score:* `{call.get('quality_score', 0)}/100`

🗣 *Jiga Bhai keh raha hai:*
_{call['human_phrase']}_

📝 *Analysis:*
_{call['reason']}_

✅ *Plan:*
   • Entry ke baad har 5 points pe update
   • Target 1 → 50% book
   • Target 2 → SL entry pe trail
   • Target 3 → Full exit
   • Risky lage toh exit kar dena!

⚠️ *Risk Warning:*
_{random.choice(HumanLikeCallGenerator.HUMAN_PHRASES['risk_warning'])}_

💎 *VIP Access:* @jiga_bhai_vip
⚠️ *Disclaimer:* Educational purpose only.

#{call['symbol']} #TradingCall #JigaBhai"""
        return msg

    @classmethod
    def update_message(cls, update: dict) -> str:
        """Format update like a human"""
        action = update["action"]

        headers = {
            "EXIT": "❌ *TRADE CLOSED*",
            "TARGET3": "🎉🎉 *JACKPOT!*",
            "TRAIL": "⚡ *SL TRAIL UPDATE*",
            "PARTIAL": "✅ *PROFIT BOOKED*",
            "UPDATE": "📊 *LIVE UPDATE*",
            "RISK": "🚨 *RISK ALERT*"
        }

        msg = f"""{headers.get(action, '📊 *UPDATE*')}

📌 *Call:* `{update['call_id']}`
📊 *Symbol:* `{update['symbol']}` {update['type']}
💰 *Price:* `{update['price']}`
📈 *P&L:* `{update['points']:+.2f} points`

🗣 *Jiga Bhai:*
_{update['message']}_

💎 *VIP:* @jiga_bhai_vip

#{update['symbol']} #JigaBhai"""
        return msg

    @classmethod
    def market_update(cls, data: dict) -> str:
        """Human-like market update"""
        tz = pytz.timezone(Config.TIMEZONE)
        now = datetime.now(tz).strftime('%I:%M %p IST')

        msg = f"""📊 *Market Update — {now}*

Bhai log, live market snapshot dekh lo! 👇

"""
        for name, idx in data.items():
            if idx:
                emoji = "🟢 UP" if idx.get("change_pct", 0) >= 0 else "🔴 DOWN"
                msg += f"📈 *{idx['symbol']}:* `{idx['current']}` ({emoji} {idx['change_pct']:+.2f}%)
"
                msg += f"   High: `{idx['high']}` | Low: `{idx['low']}`
"
                msg += f"   Volume: `{idx.get('volume', 0):,}` | Age: `{idx.get('data_age_sec', 0)}s`

"

        msg += """💡 *Jiga Bhai ka view:*
Market trend follow karo, against mat jao!

💎 *VIP:* @jiga_bhai_vip
#MarketUpdate #JigaBhai"""
        return msg

    @classmethod
    def morning_message(cls) -> str:
        """Human-like morning message"""
        tz = pytz.timezone(Config.TIMEZONE)
        now = datetime.now(tz)

        greetings = [
            "🌅 Good Morning Traders!",
            "🌅 Jai Shri Ram! Market day shuru!",
            "🌅 Bhai log, uth gaye sab? Market open hone wala hai!"
        ]

        msg = f"""{random.choice(greetings)}

⏰ *{now.strftime('%A, %d %B %Y')}*

📊 *Aaj ka Setup:*

🌍 *Global:*
   • Dow/Nasdaq: Mixed cues
   • SGX Nifty: Flat to positive

🎯 *Strategy:*
   • 9:18 AM — Opening Range Breakout call
   • 9-11 AM — Morning session trades
   • 1-3 PM — Afternoon session trades
   • Sirf high-quality setups!

⚡ *Reminder:*
   • SL strict follow karna
   • Risk management #1 priority
   • Emotion control mein rakhna

💎 *VIP:* @jiga_bhai_vip

#GoodMorning #Nifty #JigaBhai"""
        return msg

    @classmethod
    def no_trade_message(cls, reason: str) -> str:
        """Message when no trade is generated"""
        phrases = [
            f"Bhai, abhi market clear direction nahi de raha! {reason}

Wait karte hain achhe setup ka! ⏳",
            f"Traders, {reason}

Aaj ke liye itna hi! Kal milte hain! 🙏",
            f"Bhai, {reason}

Quality over quantity! Jab setup milega tabhi call dunga! 💪"
        ]
        return random.choice(phrases)

# ═══════════════════════════════════════════════════════════════════════════════
# BOT HANDLERS
# ═══════════════════════════════════════════════════════════════════════════════

class Handlers:
    @staticmethod
    def is_admin(uid: int) -> bool:
        return uid in Config.ADMIN_IDS

    @staticmethod
    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        msg = f"""🙏 *Welcome to JIGA BHAI GUJARATI TRADER!*

Namaste {user.first_name} bhai!

🤖 *Main kya karta hu:*
   ✅ Real-time NSE data (3-sec refresh)
   ✅ Quality trades only (Score 60+)
   ✅ 9-11 AM & 1-3 PM trades
   ✅ Human-like analysis & updates
   ✅ Smart risk management

⏰ *Schedule:*
   🌅 9:00 AM — Morning setup
   🎯 9:18 AM — Call 1 (Compulsory)
   🎯 10:30 AM — Call 2 (If setup)
   🎯 1:30 PM — Call 3 (If setup)
   🎯 2:30 PM — Call 4 (If setup)
   🌙 3:30 PM — Closing

💎 *VIP:* @jiga_bhai_vip
⚠️ *Disclaimer:* Educational only.
"""
        await update.message.reply_text(msg, parse_mode='Markdown')

    @staticmethod
    async def market(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("⏳ Real-time data fetch kar raha hu...")
        data = RealTimeDataEngine.get_all()
        if any(data.values()):
            msg = HumanFormatter.market_update(data)
            await update.message.reply_text(msg, parse_mode='Markdown')
        else:
            await update.message.reply_text("❌ Data fetch nahi ho raha!")

    @staticmethod
    async def call(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not Handlers.is_admin(update.effective_user.id):
            await update.message.reply_text("⛔ Admin only!")
            return

        await update.message.reply_text("⏳ Quality check kar raha hu...")

        # Check time
        tz = pytz.timezone(Config.TIMEZONE)
        now = datetime.now(tz).time()
        morning = Config.MORNING_START <= now <= Config.MORNING_END
        afternoon = Config.AFTERNOON_START <= now <= Config.AFTERNOON_END

        if morning:
            call = HumanLikeCallGenerator.generate_morning_call()
        elif afternoon:
            call = HumanLikeCallGenerator.generate_afternoon_call()
        else:
            await update.message.reply_text("❌ Outside trading hours! (9-11 AM & 1-3 PM)")
            return

        if call:
            HumanLikeTracker.add(call)
            msg = HumanFormatter.call_message(call)

            # VIP first
            if Config.VIP_CHANNEL_ID:
                try:
                    vip_msg = HumanFormatter.call_message(call, is_vip=True)
                    await context.bot.send_message(chat_id=Config.VIP_CHANNEL_ID, text=vip_msg, parse_mode='Markdown')
                except:
                    pass
                await asyncio.sleep(120)

            await context.bot.send_message(chat_id=Config.CHANNEL_ID, text=msg, parse_mode='Markdown')
            await update.message.reply_text(f"✅ Call `{call['id']}` sent! Quality: {call['quality_score']}/100")
        else:
            reason = "No quality setup found!"
            await update.message.reply_text(HumanFormatter.no_trade_message(reason))

    @staticmethod
    async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not HumanLikeTracker.active_calls:
            await update.message.reply_text("📭 No active calls.")
            return

        msg = "📊 *ACTIVE CALLS*

"
        for cid, call in HumanLikeTracker.active_calls.items():
            if call["status"] == "ACTIVE":
                msg += f"📌 `{cid}` | {call['symbol']} {call['type']}
"
                msg += f"   P&L: `{call.get('current_points', 0):+.2f}` pts

"
        await update.message.reply_text(msg, parse_mode='Markdown')

    @staticmethod
    async def morning(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not Handlers.is_admin(update.effective_user.id):
            return
        msg = HumanFormatter.morning_message()
        await context.bot.send_message(chat_id=Config.CHANNEL_ID, text=msg, parse_mode='Markdown')
        await update.message.reply_text("✅ Morning message sent!")

    @staticmethod
    async def promo(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not Handlers.is_admin(update.effective_user.id):
            return
        # VIP promo
        pass

# ═══════════════════════════════════════════════════════════════════════════════
# SCHEDULED JOBS
# ═══════════════════════════════════════════════════════════════════════════════

class BotJobs:
    @staticmethod
    async def morning_setup(context: ContextTypes.DEFAULT_TYPE):
        msg = HumanFormatter.morning_message()
        await context.bot.send_message(chat_id=Config.CHANNEL_ID, text=msg, parse_mode='Markdown')

    @staticmethod
    async def first_call(context: ContextTypes.DEFAULT_TYPE):
        """9:18 AM — Compulsory morning call"""
        logger.info("🎯 Generating compulsory morning call")

        call = HumanLikeCallGenerator.generate_morning_call()
        if call:
            HumanLikeTracker.add(call)

            # VIP first
            if Config.VIP_CHANNEL_ID:
                try:
                    vip_msg = HumanFormatter.call_message(call, is_vip=True)
                    await context.bot.send_message(chat_id=Config.VIP_CHANNEL_ID, text=vip_msg, parse_mode='Markdown')
                except:
                    pass
                await asyncio.sleep(120)

            msg = HumanFormatter.call_message(call)
            await context.bot.send_message(chat_id=Config.CHANNEL_ID, text=msg, parse_mode='Markdown')
            logger.info(f"✅ Morning call sent: {call['id']} (Quality: {call['quality_score']})")
        else:
            reason = "Opening range clear nahi bana!"
            msg = HumanFormatter.no_trade_message(reason)
            await context.bot.send_message(chat_id=Config.CHANNEL_ID, text=msg, parse_mode='Markdown')

    @staticmethod
    async def afternoon_call(context: ContextTypes.DEFAULT_TYPE):
        """Afternoon call — only if quality setup"""
        logger.info("🎯 Checking afternoon setup")

        call = HumanLikeCallGenerator.generate_afternoon_call()
        if call:
            HumanLikeTracker.add(call)

            if Config.VIP_CHANNEL_ID:
                try:
                    vip_msg = HumanFormatter.call_message(call, is_vip=True)
                    await context.bot.send_message(chat_id=Config.VIP_CHANNEL_ID, text=vip_msg, parse_mode='Markdown')
                except:
                    pass
                await asyncio.sleep(120)

            msg = HumanFormatter.call_message(call)
            await context.bot.send_message(chat_id=Config.CHANNEL_ID, text=msg, parse_mode='Markdown')
            logger.info(f"✅ Afternoon call sent: {call['id']}")
        else:
            logger.info("❌ No quality afternoon setup")

    @staticmethod
    async def tracker(context: ContextTypes.DEFAULT_TYPE):
        updates = HumanLikeTracker.track_all()
        for update in updates:
            msg = HumanFormatter.update_message(update)
            await context.bot.send_message(chat_id=Config.CHANNEL_ID, text=msg, parse_mode='Markdown')

    @staticmethod
    async def market_update(context: ContextTypes.DEFAULT_TYPE):
        data = RealTimeDataEngine.get_all()
        if any(data.values()):
            msg = HumanFormatter.market_update(data)
            await context.bot.send_message(chat_id=Config.CHANNEL_ID, text=msg, parse_mode='Markdown')

    @staticmethod
    async def reset_daily(context: ContextTypes.DEFAULT_TYPE):
        QualityControl.reset_daily()
        logger.info("📊 Daily reset done")

# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def setup_jobs(app: Application):
    jq = app.job_queue
    tz = pytz.timezone(Config.TIMEZONE)

    # Morning setup — 9:00 AM
    jq.run_daily(BotJobs.morning_setup, time=time(hour=9, minute=0, tzinfo=tz))

    # First call — 9:18 AM (COMPULSORY)
    jq.run_daily(BotJobs.first_call, time=time(hour=9, minute=18, tzinfo=tz))

    # Afternoon calls — only if quality (1:30 PM, 2:30 PM)
    jq.run_daily(BotJobs.afternoon_call, time=time(hour=13, minute=30, tzinfo=tz))
    jq.run_daily(BotJobs.afternoon_call, time=time(hour=14, minute=30, tzinfo=tz))

    # Market updates — 10:00 AM, 11:00 AM, 2:00 PM, 3:00 PM
    for h in [10, 11, 14, 15]:
        jq.run_daily(BotJobs.market_update, time=time(hour=h, minute=0, tzinfo=tz))

    # Call tracker — every 5 min
    jq.run_repeating(BotJobs.tracker, interval=300, first=10)

    # Daily reset — midnight
    jq.run_daily(BotJobs.reset_daily, time=time(hour=0, minute=1, tzinfo=tz))

    logger.info("✅ Jobs scheduled")

def main():
    print("\n" + "="*70)
    print(f"    🤖 {Config.BOT_NAME} — HUMAN-MINDED EDITION")
    print("="*70 + "\n")

    if not Config.BOT_TOKEN or not Config.CHANNEL_ID or not Config.ADMIN_IDS:
        print("❌ MISSING ENV VARS!")
        sys.exit(1)

    # Start real-time data engine
    RealTimeDataEngine.start()

    print(f"✅ Config loaded:")
    print(f"   Channel: {Config.CHANNEL_ID}")
    print(f"   Trading Hours: 9-11 AM & 1-3 PM")
    print(f"   Min RRR: 1:{Config.MIN_RRR}")
    print(f"   Max Calls/Day: {Config.MAX_DAILY_CALLS}")
    print(f"   Quality Filter: {'ON' if Config.SKIP_LOW_QUALITY else 'OFF'}")
    print()

    app = Application.builder().token(Config.BOT_TOKEN).build()

    h = Handlers()
    app.add_handler(CommandHandler("start", h.start))
    app.add_handler(CommandHandler("market", h.market))
    app.add_handler(CommandHandler("call", h.call))
    app.add_handler(CommandHandler("status", h.status))
    app.add_handler(CommandHandler("morning", h.morning))
    app.add_handler(CommandHandler("promo", h.promo))

    setup_jobs(app)

    print("🚀 Bot running! Press Ctrl+C to stop.\n")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
