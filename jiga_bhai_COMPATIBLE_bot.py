#!/usr/bin/env python3
"""
JIGA BHAI GUJARATI TRADER - COMPATIBLE VERSION
python-telegram-bot 20.3 compatible
"""

import os
import sys
import asyncio
import logging
import random
import time as time_module
from datetime import datetime, time, timedelta

import pytz
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import requests
import threading

# ============== CONFIGURATION ==============

class Config:
    BOT_TOKEN = os.getenv("BOT_TOKEN", "")
    CHANNEL_ID = os.getenv("CHANNEL_ID", "")
    ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
    VIP_CHANNEL_ID = os.getenv("VIP_CHANNEL_ID", "")
    TIMEZONE = os.getenv("TIMEZONE", "Asia/Kolkata")
    MIN_RRR = float(os.getenv("MIN_RRR", "3.0"))
    MAX_DAILY_CALLS = int(os.getenv("MAX_DAILY_CALLS", "4"))
    SKIP_LOW_QUALITY = os.getenv("SKIP_LOW_QUALITY", "true").lower() == "true"

    MORNING_START = time(9, 0)
    MORNING_END = time(11, 0)
    AFTERNOON_START = time(13, 0)
    AFTERNOON_END = time(15, 0)
    FIRST_CALL_TIME = time(9, 18)

    BOT_NAME = "JIGA BHAI GUJARATI TRADER"

# ============== LOGGING ==============

logging.basicConfig(
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    level=logging.INFO,
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("JIGA_BHAI")

# ============== REAL-TIME DATA ENGINE ==============

class RealTimeDataEngine:
    _cache = {"nifty": None, "banknifty": None, "sensex": None, "last_update": None}
    _running = False
    _ws_thread = None

    NSE_URLS = {
        "nifty": "https://www.nseindia.com/api/equity-stockIndices?index=NIFTY%2050",
        "banknifty": "https://www.nseindia.com/api/equity-stockIndices?index=NIFTY%20BANK"
    }

    @classmethod
    def start(cls):
        if cls._running:
            return
        cls._running = True

        def poll_loop():
            session = requests.Session()
            session.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": "https://www.nseindia.com/"
            })

            try:
                session.get("https://www.nseindia.com/", timeout=10)
                session.get("https://www.nseindia.com/market-data/equity-derivatives", timeout=10)
            except:
                pass

            while cls._running:
                try:
                    for name, url in cls.NSE_URLS.items():
                        try:
                            resp = session.get(url, timeout=5)
                            if resp.status_code == 200:
                                data = resp.json()
                                if "data" in data and len(data["data"]) > 0:
                                    d = data["data"][0]
                                    cls._cache[name] = {
                                        "symbol": name.upper(),
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

                time_module.sleep(3)

        cls._ws_thread = threading.Thread(target=poll_loop, daemon=True)
        cls._ws_thread.start()
        logger.info("Real-time data engine started")

    @classmethod
    def stop(cls):
        cls._running = False

    @classmethod
    def get_index(cls, name):
        data = cls._cache.get(name.lower())
        if data:
            age = (datetime.now() - cls._cache["last_update"]).total_seconds() if cls._cache["last_update"] else 999
            data["data_age_sec"] = int(age)
            return data
        return None

    @classmethod
    def get_all(cls):
        return {
            "nifty": cls.get_index("nifty"),
            "banknifty": cls.get_index("banknifty"),
            "sensex": cls.get_index("sensex")
        }

# ============== QUALITY CONTROL ==============

class QualityControl:
    daily_call_count = 0
    last_call_time = None

    @classmethod
    def can_generate_call(cls):
        tz = pytz.timezone(Config.TIMEZONE)
        now = datetime.now(tz)
        current_time = now.time()

        morning_session = Config.MORNING_START <= current_time <= Config.MORNING_END
        afternoon_session = Config.AFTERNOON_START <= current_time <= Config.AFTERNOON_END

        if not (morning_session or afternoon_session):
            return False, "Outside trading hours (9-11 AM and 1-3 PM only)"

        if cls.daily_call_count >= Config.MAX_DAILY_CALLS:
            return False, f"Daily limit reached ({Config.MAX_DAILY_CALLS} calls)"

        if cls.last_call_time:
            minutes_since = (now - cls.last_call_time).total_seconds() / 60
            if minutes_since < 20:
                return False, f"Cooldown active ({20 - int(minutes_since)} min left)"

        return True, "Quality check passed"

    @classmethod
    def evaluate_setup(cls, call):
        score = 0
        reasons = []

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

        if nifty and nifty.get("volume", 0) > 100000000:
            score += 20
            reasons.append("High volume confirmation")
        elif nifty and nifty.get("volume", 0) > 50000000:
            score += 10
            reasons.append("Average volume")

        if call.get("range", 0) > 50:
            score += 15
            reasons.append("Good opening range")
        elif call.get("range", 0) > 30:
            score += 10
            reasons.append("Decent opening range")

        tz = pytz.timezone(Config.TIMEZONE)
        hour = datetime.now(tz).hour

        if hour == 9:
            score += 10
            reasons.append("Prime morning session")
        elif hour == 10:
            score += 7
            reasons.append("Good morning session")
        elif hour == 13:
            score += 8
            reasons.append("Afternoon opening")
        elif hour == 14:
            score += 5
            reasons.append("Late afternoon")

        if score >= 60:
            return True, score, " | ".join(reasons)
        elif score >= 45 and not Config.SKIP_LOW_QUALITY:
            return True, score, " | ".join(reasons) + " (Borderline)"
        else:
            return False, score, " | ".join(reasons) + " (Too weak)"

    @classmethod
    def record_call(cls):
        cls.daily_call_count += 1
        cls.last_call_time = datetime.now(pytz.timezone(Config.TIMEZONE))

    @classmethod
    def reset_daily(cls):
        cls.daily_call_count = 0
        cls.last_call_time = None
        logger.info("Daily counters reset")

# ============== CALL GENERATOR ==============

class CallGenerator:
    PHRASES_HIGH = [
        "Bhai, ye setup bilkul saaf dikha raha hai!",
        "Dekho bhai, market ne direction bata diya hai!",
        "Ye wala trade confidence se le sakte hain!",
        "Setup perfect hai bhai, entry lo!"
    ]

    PHRASES_MEDIUM = [
        "Thoda risky hai lekin setup theek hai!",
        "Dhyan se dekh ke entry karna!",
        "Ye trade chhota quantity se lein!",
        "Market thoda mixed hai, careful rehna!"
    ]

    @classmethod
    def generate_morning_call(cls):
        try:
            indices = RealTimeDataEngine.get_all()
            nifty = indices.get("nifty")
            bn = indices.get("banknifty")

            if not nifty:
                return None

            current = nifty["current"]
            high = nifty["high"]
            low = nifty["low"]
            range_size = high - low

            if range_size < 20:
                return None

            if bn and bn.get("high", 0) - bn.get("low", 0) > range_size * 2:
                symbol = "BANKNIFTY"
                mult = 100
                current = bn["current"]
                high = bn["high"]
                low = bn["low"]
                range_size = bn["high"] - bn["low"]
            else:
                symbol = "NIFTY"
                mult = 50

            if current > high * 0.998:
                direction = "CE"
                entry = round(high / mult) * mult + mult
                sl = round((low - range_size * 0.2) / mult) * mult
                target1 = round((entry + range_size * 1.5) / mult) * mult
                target2 = round((entry + range_size * 2.5) / mult) * mult
                target3 = round((entry + range_size * 4) / mult) * mult
                reason = "Opening range breakout with strong volume! Buyers ne control le liya!"
            elif current < low * 1.002:
                direction = "PE"
                entry = round(low / mult) * mult - mult
                sl = round((high + range_size * 0.2) / mult) * mult
                target1 = round((entry - range_size * 1.5) / mult) * mult
                target2 = round((entry - range_size * 2.5) / mult) * mult
                target3 = round((entry - range_size * 4) / mult) * mult
                reason = "Opening range breakdown! Sellers active hain!"
            else:
                return None

            risk = abs(entry - sl)
            reward = abs(target1 - entry)
            rrr = reward / risk if risk > 0 else 3

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
                "reason": reason,
                "timeframe": "15-45 min",
                "strategy": "Opening Range Breakout",
                "range": range_size,
                "entry_time": datetime.now(pytz.timezone(Config.TIMEZONE)).strftime('%H:%M'),
                "quality_score": 0,
                "human_phrase": random.choice(cls.PHRASES_HIGH)
            }

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
    def generate_afternoon_call(cls):
        try:
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

            if abs(change_pct) < 0.1:
                return None

            symbol = "NIFTY"
            mult = 50

            if change_pct > 0:
                direction = "CE"
                entry = round(current / mult) * mult
                sl = round((current - 40) / mult) * mult
                target1 = round((current + 80) / mult) * mult
                target2 = round((current + 150) / mult) * mult
                target3 = round((current + 250) / mult) * mult
                reason = "Afternoon momentum continue ho raha hai! Trend ke saath chalo!"
            else:
                direction = "PE"
                entry = round(current / mult) * mult
                sl = round((current + 40) / mult) * mult
                target1 = round((current - 80) / mult) * mult
                target2 = round((current - 150) / mult) * mult
                target3 = round((current - 250) / mult) * mult
                reason = "Afternoon selling pressure build up ho raha hai! Trend down!"

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
                "reason": reason,
                "timeframe": "20-40 min",
                "strategy": "Afternoon Momentum",
                "entry_time": datetime.now(pytz.timezone(Config.TIMEZONE)).strftime('%H:%M'),
                "quality_score": 0,
                "human_phrase": random.choice(cls.PHRASES_MEDIUM)
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

# ============== CALL TRACKER ==============

class CallTracker:
    active_calls = {}

    @classmethod
    def add(cls, call):
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
    def track_all(cls):
        updates = []

        for call_id, call in list(cls.active_calls.items()):
            if call["status"] != "ACTIVE":
                continue

            symbol = call["symbol"]
            idx_name = "nifty" if symbol == "NIFTY" else "banknifty"
            data = RealTimeDataEngine.get_index(idx_name)

            if not data:
                continue

            current = data["current"]
            entry = call["entry"]
            sl = call["sl"]

            if call["type"] == "CE":
                points = round(current - entry, 2)

                if current <= sl:
                    updates.append(cls._make_exit(call_id, current, points, "Stop Loss Hit", call))
                    continue
                if current >= call["target3"]:
                    updates.append(cls._make_target3(call_id, current, points, call))
                    continue
                if current >= call["target2"] and not call.get("t2_alerted"):
                    call["t2_alerted"] = True
                    updates.append(cls._make_trail(call_id, current, points, call))
                if current >= call["target1"] and not call.get("t1_alerted"):
                    call["t1_alerted"] = True
                    updates.append(cls._make_partial(call_id, current, points, call))

            else:
                points = round(entry - current, 2)

                if current >= sl:
                    updates.append(cls._make_exit(call_id, current, -abs(points), "Stop Loss Hit", call))
                    continue
                if current <= call["target3"]:
                    updates.append(cls._make_target3(call_id, current, points, call))
                    continue
                if current <= call["target2"] and not call.get("t2_alerted"):
                    call["t2_alerted"] = True
                    updates.append(cls._make_trail(call_id, current, points, call))
                if current <= call["target1"] and not call.get("t1_alerted"):
                    call["t1_alerted"] = True
                    updates.append(cls._make_partial(call_id, current, points, call))

            call["current_points"] = points
            if points > call["highest_points"]:
                call["highest_points"] = points
            if points < call["lowest_points"]:
                call["lowest_points"] = points

            last = call.get("last_reported", 0)
            if abs(points - last) >= 5:
                call["last_reported"] = points
                updates.append(cls._make_update(call_id, current, points, call))

            if points < -3 and not call.get("risk_alerted"):
                call["risk_alerted"] = True
                updates.append(cls._make_risk(call_id, current, points, call))

        return updates

    @classmethod
    def _make_exit(cls, cid, price, points, reason, call):
        call["status"] = "STOPPED"
        phrases = [
            f"Bhai, {reason} ho gaya! {points:+.2f} points ka loss. Next trade pe focus karo!",
            f"SL hit ho gaya bhai! {points:+.2f} points. Koi baat nahi, risk management ne bacha liya!",
            f"Trade closed at SL. Loss: {points:+.2f} pts. Ye part of game hai!"
        ]
        return {"action": "EXIT", "call_id": cid, "price": price, "points": points,
                "message": random.choice(phrases), "symbol": call["symbol"], "type": call["type"]}

    @classmethod
    def _make_target3(cls, cid, price, points, call):
        call["status"] = "TARGET3"
        phrases = [
            f"Bhai, TARGET 3 ACHIEVED! {points:+.2f} points ka profit! Party time!",
            f"Full target mil gaya bhai! {points:+.2f} points! Setup ne perfectly kaam kiya!",
            f"Jackpot bhai! {points:+.2f} points! Ye wala trade yaad rahega!"
        ]
        return {"action": "TARGET3", "call_id": cid, "price": price, "points": points,
                "message": random.choice(phrases), "symbol": call["symbol"], "type": call["type"]}

    @classmethod
    def _make_trail(cls, cid, price, points, call):
        phrases = [
            f"Target 2 hit bhai! {points:+.2f} points! Ab SL entry pe trail karo! Safe game!",
            f"Bhai, {points:+.2f} points aa gaye! SL ko entry pe shift karo, ab risk free!",
            f"Excellent! {points:+.2f} points! Trail SL to entry, ab loss nahi hoga!"
        ]
        return {"action": "TRAIL", "call_id": cid, "price": price, "points": points,
                "message": random.choice(phrases), "symbol": call["symbol"], "type": call["type"]}

    @classmethod
    def _make_partial(cls, cid, price, points, call):
        phrases = [
            f"Target 1 hit bhai! {points:+.2f} points! 50% book karo, baaki trail karo!",
            f"Bhai, {points:+.2f} points profit! Half book kar lo, baaki ride karo!",
            f"First target achieved! {points:+.2f} pts! Partial exit + trail SL! Smart trading!"
        ]
        return {"action": "PARTIAL", "call_id": cid, "price": price, "points": points,
                "message": random.choice(phrases), "symbol": call["symbol"], "type": call["type"]}

    @classmethod
    def _make_update(cls, cid, price, points, call):
        phrases = [
            f"Bhai, call {points:+.2f} points chal raha hai! Hold karo, levels kaam kar rahe hain!",
            f"Update: {points:+.2f} points running! Market hamare favor mein hai!",
            f"{points:+.2f} points aa gaye bhai! Patience rakho, targets aa jayenge!"
        ]
        return {"action": "UPDATE", "call_id": cid, "price": price, "points": points,
                "message": random.choice(phrases), "symbol": call["symbol"], "type": call["type"]}

    @classmethod
    def _make_risk(cls, cid, price, points, call):
        phrases = [
            f"Bhai, thoda risky lag raha hai! {points:+.2f} points against. Review karo!",
            f"Alert: {points:+.2f} points loss side! Position check karo, exit socho!",
            f"Bhai, market ulta chal raha hai! {points:+.2f} pts against. SL ke paas aa gaya!"
        ]
        return {"action": "RISK", "call_id": cid, "price": price, "points": points,
                "message": random.choice(phrases), "symbol": call["symbol"], "type": call["type"]}

# ============== FORMATTER ==============

class Formatter:
    @classmethod
    def call_msg(cls, call, is_vip=False):
        direction = "CALL" if call["type"] == "CE" else "PUT"
        vip_badge = "VIP EXCLUSIVE " if is_vip else ""

        intros = [
            "Bhai log, dekho ye setup!",
            "Traders, ready ho jao!",
            "Bhai, ye wala trade dhyan se dekho!",
            "Market ne signal de diya hai!"
        ]

        lines = []
        lines.append(random.choice(intros))
        lines.append("")
        lines.append(vip_badge + "NEW TRADING CALL")
        lines.append("")
        lines.append(f"Call ID: {call['id']}")
        lines.append(f"Symbol: {call['symbol']}")
        lines.append(f"Direction: {direction}")
        lines.append(f"Strategy: {call['strategy']}")
        lines.append("")
        lines.append(f"ENTRY: {call['entry']}")
        lines.append(f"STOP LOSS: {call['sl']}")
        lines.append(f"TARGET 1: {call['target1']}")
        lines.append(f"TARGET 2: {call['target2']}")
        lines.append(f"TARGET 3: {call['target3']}")
        lines.append("")
        lines.append(f"RRR: {call['rrr']}")
        lines.append(f"Timeframe: {call['timeframe']}")
        lines.append(f"Time: {call['entry_time']}")
        lines.append(f"Quality Score: {call.get('quality_score', 0)}/100")
        lines.append("")
        lines.append(f"Jiga Bhai keh raha hai: {call['human_phrase']}")
        lines.append("")
        lines.append(f"Analysis: {call['reason']}")
        lines.append("")
        lines.append("Plan:")
        lines.append("  - Entry ke baad har 5 points pe update")
        lines.append("  - Target 1 -> 50% book")
        lines.append("  - Target 2 -> SL entry pe trail")
        lines.append("  - Target 3 -> Full exit")
        lines.append("  - Risky lage toh exit kar dena!")
        lines.append("")
        lines.append("Risk Warning: SL strict follow karna bhai!")
        lines.append("")
        lines.append("VIP Access: @jiga_bhai_vip")
        lines.append("Disclaimer: Educational purpose only.")

        return "\n".join(lines)

    @classmethod
    def update_msg(cls, update):
        action = update["action"]
        headers = {
            "EXIT": "TRADE CLOSED",
            "TARGET3": "JACKPOT!",
            "TRAIL": "SL TRAIL UPDATE",
            "PARTIAL": "PROFIT BOOKED",
            "UPDATE": "LIVE UPDATE",
            "RISK": "RISK ALERT"
        }

        lines = []
        lines.append(headers.get(action, "UPDATE"))
        lines.append("")
        lines.append(f"Call: {update['call_id']}")
        lines.append(f"Symbol: {update['symbol']} {update['type']}")
        lines.append(f"Price: {update['price']}")
        lines.append(f"P&L: {update['points']:+.2f} points")
        lines.append("")
        lines.append(f"Jiga Bhai: {update['message']}")
        lines.append("")
        lines.append("VIP: @jiga_bhai_vip")

        return "\n".join(lines)

    @classmethod
    def market_msg(cls, data):
        tz = pytz.timezone(Config.TIMEZONE)
        now = datetime.now(tz).strftime('%I:%M %p IST')

        lines = []
        lines.append(f"Market Update -- {now}")
        lines.append("")
        lines.append("Bhai log, live market snapshot dekh lo!")
        lines.append("")

        for name, idx in data.items():
            if idx:
                emoji = "UP" if idx.get("change_pct", 0) >= 0 else "DOWN"
                lines.append(f"{idx['symbol']}: {idx['current']} ({emoji} {idx['change_pct']:+.2f}%)")
                lines.append(f"  High: {idx['high']} | Low: {idx['low']}")
                lines.append(f"  Volume: {idx.get('volume', 0):,} | Age: {idx.get('data_age_sec', 0)}s")
                lines.append("")

        lines.append("Jiga Bhai ka view: Market trend follow karo, against mat jao!")
        lines.append("")
        lines.append("VIP: @jiga_bhai_vip")

        return "\n".join(lines)

    @classmethod
    def morning_msg(cls):
        tz = pytz.timezone(Config.TIMEZONE)
        now = datetime.now(tz)

        greetings = [
            "Good Morning Traders!",
            "Jai Shri Ram! Market day shuru!",
            "Bhai log, uth gaye sab? Market open hone wala hai!"
        ]

        lines = []
        lines.append(random.choice(greetings))
        lines.append("")
        lines.append(f"{now.strftime('%A, %d %B %Y')}")
        lines.append("")
        lines.append("Aaj ka Setup:")
        lines.append("")
        lines.append("Global:")
        lines.append("  - Dow/Nasdaq: Mixed cues")
        lines.append("  - SGX Nifty: Flat to positive")
        lines.append("")
        lines.append("Strategy:")
        lines.append("  - 9:18 AM -- Opening Range Breakout call")
        lines.append("  - 9-11 AM -- Morning session trades")
        lines.append("  - 1-3 PM -- Afternoon session trades")
        lines.append("  - Sirf high-quality setups!")
        lines.append("")
        lines.append("Reminder:")
        lines.append("  - SL strict follow karna")
        lines.append("  - Risk management #1 priority")
        lines.append("  - Emotion control mein rakhna")
        lines.append("")
        lines.append("VIP: @jiga_bhai_vip")

        return "\n".join(lines)

    @classmethod
    def no_trade_msg(cls, reason):
        phrases = [
            f"Bhai, abhi market clear direction nahi de raha! {reason} Wait karte hain achhe setup ka!",
            f"Traders, {reason} Aaj ke liye itna hi! Kal milte hain!",
            f"Bhai, {reason} Quality over quantity! Jab setup milega tabhi call dunga!"
        ]
        return random.choice(phrases)

# ============== HANDLERS ==============

class Handlers:
    @staticmethod
    def is_admin(uid):
        return uid in Config.ADMIN_IDS

    @staticmethod
    async def start(update, context):
        user = update.effective_user
        lines = []
        lines.append("Welcome to JIGA BHAI GUJARATI TRADER!")
        lines.append("")
        lines.append(f"Namaste {user.first_name} bhai!")
        lines.append("")
        lines.append("Main kya karta hu:")
        lines.append("  - Real-time NSE data (3-sec refresh)")
        lines.append("  - Quality trades only (Score 60+)")
        lines.append("  - 9-11 AM and 1-3 PM trades")
        lines.append("  - Human-like analysis and updates")
        lines.append("  - Smart risk management")
        lines.append("")
        lines.append("Schedule:")
        lines.append("  - 9:00 AM -- Morning setup")
        lines.append("  - 9:18 AM -- Call 1 (Compulsory)")
        lines.append("  - 10:30 AM -- Call 2 (If setup)")
        lines.append("  - 1:30 PM -- Call 3 (If setup)")
        lines.append("  - 2:30 PM -- Call 4 (If setup)")
        lines.append("  - 3:30 PM -- Closing")
        lines.append("")
        lines.append("VIP: @jiga_bhai_vip")
        lines.append("Disclaimer: Educational only.")
        await update.message.reply_text("\n".join(lines))

    @staticmethod
    async def market(update, context):
        await update.message.reply_text("Fetching real-time data...")
        data = RealTimeDataEngine.get_all()
        if any(data.values()):
            msg = Formatter.market_msg(data)
            await update.message.reply_text(msg)
        else:
            await update.message.reply_text("Data fetch nahi ho raha!")

    @staticmethod
    async def call(update, context):
        if not Handlers.is_admin(update.effective_user.id):
            await update.message.reply_text("Admin only!")
            return

        await update.message.reply_text("Quality check kar raha hu...")

        tz = pytz.timezone(Config.TIMEZONE)
        now = datetime.now(tz).time()
        morning = Config.MORNING_START <= now <= Config.MORNING_END
        afternoon = Config.AFTERNOON_START <= now <= Config.AFTERNOON_END

        if morning:
            call = CallGenerator.generate_morning_call()
        elif afternoon:
            call = CallGenerator.generate_afternoon_call()
        else:
            await update.message.reply_text("Outside trading hours! (9-11 AM and 1-3 PM)")
            return

        if call:
            CallTracker.add(call)
            msg = Formatter.call_msg(call)

            if Config.VIP_CHANNEL_ID:
                try:
                    vip_msg = Formatter.call_msg(call, is_vip=True)
                    await context.bot.send_message(chat_id=Config.VIP_CHANNEL_ID, text=vip_msg)
                except:
                    pass
                await asyncio.sleep(120)

            await context.bot.send_message(chat_id=Config.CHANNEL_ID, text=msg)
            await update.message.reply_text(f"Call {call['id']} sent! Quality: {call['quality_score']}/100")
        else:
            reason = "No quality setup found!"
            await update.message.reply_text(Formatter.no_trade_msg(reason))

    @staticmethod
    async def status(update, context):
        if not CallTracker.active_calls:
            await update.message.reply_text("No active calls.")
            return

        lines = ["ACTIVE CALLS", ""]
        for cid, call in CallTracker.active_calls.items():
            if call["status"] == "ACTIVE":
                lines.append(f"{cid} | {call['symbol']} {call['type']}")
                lines.append(f"  P&L: {call.get('current_points', 0):+.2f} pts")
                lines.append("")
        await update.message.reply_text("\n".join(lines))

    @staticmethod
    async def morning(update, context):
        if not Handlers.is_admin(update.effective_user.id):
            return
        msg = Formatter.morning_msg()
        await context.bot.send_message(chat_id=Config.CHANNEL_ID, text=msg)
        await update.message.reply_text("Morning message sent!")

# ============== JOBS (Using asyncio instead of JobQueue) ==============

class BotJobs:
    @staticmethod
    async def morning_setup(context):
        msg = Formatter.morning_msg()
        await context.bot.send_message(chat_id=Config.CHANNEL_ID, text=msg)

    @staticmethod
    async def first_call(context):
        logger.info("Generating compulsory morning call")

        call = CallGenerator.generate_morning_call()
        if call:
            CallTracker.add(call)

            if Config.VIP_CHANNEL_ID:
                try:
                    vip_msg = Formatter.call_msg(call, is_vip=True)
                    await context.bot.send_message(chat_id=Config.VIP_CHANNEL_ID, text=vip_msg)
                except:
                    pass
                await asyncio.sleep(120)

            msg = Formatter.call_msg(call)
            await context.bot.send_message(chat_id=Config.CHANNEL_ID, text=msg)
            logger.info(f"Morning call sent: {call['id']} (Quality: {call['quality_score']})")
        else:
            reason = "Opening range clear nahi bana!"
            msg = Formatter.no_trade_msg(reason)
            await context.bot.send_message(chat_id=Config.CHANNEL_ID, text=msg)

    @staticmethod
    async def afternoon_call(context):
        logger.info("Checking afternoon setup")

        call = CallGenerator.generate_afternoon_call()
        if call:
            CallTracker.add(call)

            if Config.VIP_CHANNEL_ID:
                try:
                    vip_msg = Formatter.call_msg(call, is_vip=True)
                    await context.bot.send_message(chat_id=Config.VIP_CHANNEL_ID, text=vip_msg)
                except:
                    pass
                await asyncio.sleep(120)

            msg = Formatter.call_msg(call)
            await context.bot.send_message(chat_id=Config.CHANNEL_ID, text=msg)
            logger.info(f"Afternoon call sent: {call['id']}")
        else:
            logger.info("No quality afternoon setup")

    @staticmethod
    async def tracker(context):
        updates = CallTracker.track_all()
        for update in updates:
            msg = Formatter.update_msg(update)
            await context.bot.send_message(chat_id=Config.CHANNEL_ID, text=msg)

    @staticmethod
    async def market_update(context):
        data = RealTimeDataEngine.get_all()
        if any(data.values()):
            msg = Formatter.market_msg(data)
            await context.bot.send_message(chat_id=Config.CHANNEL_ID, text=msg)

    @staticmethod
    async def reset_daily(context):
        QualityControl.reset_daily()

# ============== SCHEDULER (Custom implementation without JobQueue) ==============

import asyncio

class Scheduler:
    def __init__(self, app):
        self.app = app
        self.tasks = []

    def start(self):
        tz = pytz.timezone(Config.TIMEZONE)

        # Schedule daily jobs
        self._schedule_daily(9, 0, BotJobs.morning_setup)
        self._schedule_daily(9, 18, BotJobs.first_call)
        self._schedule_daily(13, 30, BotJobs.afternoon_call)
        self._schedule_daily(14, 30, BotJobs.afternoon_call)

        for h in [10, 11, 14, 15]:
            self._schedule_daily(h, 0, BotJobs.market_update)

        self._schedule_daily(0, 1, BotJobs.reset_daily)

        # Start repeating tracker (every 5 min)
        asyncio.create_task(self._repeating_task(300, BotJobs.tracker))

        logger.info("Scheduler started")

    def _schedule_daily(self, hour, minute, job_func):
        async def wrapper():
            while True:
                tz = pytz.timezone(Config.TIMEZONE)
                now = datetime.now(tz)
                target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if target <= now:
                    target += timedelta(days=1)
                wait_seconds = (target - now).total_seconds()
                await asyncio.sleep(wait_seconds)
                try:
                    await job_func(self.app)
                except Exception as e:
                    logger.error(f"Job error: {e}")

        asyncio.create_task(wrapper())

    async def _repeating_task(self, interval, job_func):
        while True:
            await asyncio.sleep(interval)
            try:
                await job_func(self.app)
            except Exception as e:
                logger.error(f"Repeating job error: {e}")

# ============== MAIN ==============

def main():
    print("\n" + "="*70)
    print(f"    {Config.BOT_NAME} -- COMPATIBLE EDITION")
    print("="*70 + "\n")

    if not Config.BOT_TOKEN or not Config.CHANNEL_ID or not Config.ADMIN_IDS:
        print("MISSING ENV VARS!")
        print("   BOT_TOKEN, CHANNEL_ID, ADMIN_IDS")
        sys.exit(1)

    RealTimeDataEngine.start()

    print(f"Config loaded:")
    print(f"   Channel: {Config.CHANNEL_ID}")
    print(f"   Trading Hours: 9-11 AM and 1-3 PM")
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

    # Start scheduler
    scheduler = Scheduler(app)

    print("Bot running! Press Ctrl+C to stop.\n")

    # Run with custom scheduler
    app.run_polling()

if __name__ == '__main__':
    main()
