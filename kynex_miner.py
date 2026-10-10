"""
kynex_miner.py
=============================================================================
KYNEX NETWORK CLOUD FARMING & REFERRAL AUTOMATION ENGINE
=============================================================================
Handles programmatic interaction with Kynex Network (@Kynex_miningbot):
- Firebase Cloud Functions callable authentication (verifyTelegramAuth)
- Google Identity Toolkit JWT token exchange (signInWithCustomToken)
- Realtime Database state synchronization & starter profile onboarding
- Mining session lifecycle (claimMining & startMining)
- Daily check-in rewards (claimDailyCheckin)
- Mandatory sponsor channels & social tasks verification (claimSocialTask)
- Watch ads tasks execution (claimTasksAdReward)
- Energy refill & boost management
"""

import asyncio
import logging
import random
import time
from typing import Dict, Any, Optional

import aiohttp

logger = logging.getLogger("kynex_miner")

# Firebase / Kynex Configuration
FIREBASE_API_KEY = "AIzaSyB5aYPcOrDXzMTBt5p5VCEFKZdmBBMGA9c"
FUNCTIONS_BASE_URL = "https://us-central1-keynex-e9511.cloudfunctions.net"
DATABASE_URL = "https://keynex-e9511-default-rtdb.europe-west1.firebasedatabase.app"
IDENTITY_TOOLKIT_URL = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithCustomToken?key={FIREBASE_API_KEY}"

# Bot Identifiers
KYNEX_BOT_USERNAME = "Kynex_miningbot"
KYNEX_BOT_ID = 8663611744
MASTER_REFERRAL_CODE = "6727787768"

# Mandatory Sponsor Channels for Side-Task Verification
SPONSOR_CHANNELS = [
    "kynex_mining",
    "EarnVaulte",
    "solanamemes001",
    "Web3Primeteam"
]

COMMON_HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Mobile Safari/537.36 Telegram-Android/11.0.0",
    "Origin": "https://kynex.top",
    "Referer": "https://kynex.top/telegram-auth.html"
}


async def jitter(min_s: float = 0.5, max_s: float = 1.5):
    """Adds non-linear human delay between requests to mimic organic user interaction."""
    await asyncio.sleep(random.uniform(min_s, max_s))


async def authenticate_kynex(session: aiohttp.ClientSession, init_data: str) -> Optional[Dict[str, Any]]:
    """
    Authenticates with Kynex using raw Telegram initData.
    Step 1: Calls verifyTelegramAuth Cloud Function to verify Telegram signature and credit referral.
    Step 2: Exchanges the returned customToken for a Firebase idToken.
    """
    try:
        # Step 1: verifyTelegramAuth
        verify_payload = {"data": {"initData": init_data}}
        async with session.post(
            f"{FUNCTIONS_BASE_URL}/verifyTelegramAuth",
            json=verify_payload,
            headers=COMMON_HEADERS,
            timeout=aiohttp.ClientTimeout(total=15)
        ) as resp:
            if resp.status != 200:
                err_text = await resp.text()
                logger.warning(f"[Kynex Auth] verifyTelegramAuth returned HTTP {resp.status}: {err_text[:200]}")
                return None
            verify_data = await resp.json()

        res = verify_data.get("result", {})
        custom_token = res.get("customToken")
        uid = res.get("uid")
        is_new_user = res.get("isNewUser", False)
        referrer_uid = res.get("referrerUid")
        telegram_profile = res.get("telegramProfile", {})

        if not custom_token or not uid:
            logger.warning("[Kynex Auth] Missing customToken or uid in verify response")
            return None

        # Step 2: signInWithCustomToken exchange
        exchange_payload = {"token": custom_token, "returnSecureToken": True}
        async with session.post(
            IDENTITY_TOOLKIT_URL,
            json=exchange_payload,
            headers={"Content-Type": "application/json"},
            timeout=aiohttp.ClientTimeout(total=15)
        ) as t_resp:
            if t_resp.status != 200:
                err_text = await t_resp.text()
                logger.warning(f"[Kynex Auth] signInWithCustomToken returned HTTP {t_resp.status}: {err_text[:200]}")
                return None
            t_data = await t_resp.json()

        id_token = t_data.get("idToken")
        if not id_token:
            logger.warning("[Kynex Auth] Missing idToken in exchange response")
            return None

        # Step 3: Initialize starter profile if new user
        if is_new_user:
            await init_starter_profile(session, id_token, uid, telegram_profile, referrer_uid)

        return {
            "id_token": id_token,
            "uid": uid,
            "is_new_user": is_new_user,
            "referrer_uid": referrer_uid,
            "telegram_profile": telegram_profile
        }
    except Exception as e:
        logger.error(f"[Kynex Auth] Exception during authentication: {e}")
        return None


async def init_starter_profile(
    session: aiohttp.ClientSession,
    id_token: str,
    uid: str,
    telegram_profile: dict,
    referrer_uid: Optional[str]
) -> bool:
    """Initializes new user state in Firebase Realtime Database with 100% genuine starter defaults."""
    starting_state = {
        "telegramId": telegram_profile.get("id") if telegram_profile else None,
        "firstName": telegram_profile.get("first_name", "") if telegram_profile else "",
        "username": telegram_profile.get("username", "") if telegram_profile else "",
        "photoUrl": telegram_profile.get("photo_url", "") if telegram_profile else "",
        "knxBalance": 0,
        "usdBalance": 0,
        "miningPower": 12.85,
        "energy": 100,
        "energySeconds": 43200,  # 12 hours starter energy capacity
        "level": 1,
        "xp": 0,
        "totalBurnedKnx": 0,
        "invitedFriends": 0,
        "referredBy": referrer_uid,
        "createdAt": {".sv": "timestamp"},
        "lastActiveAt": {".sv": "timestamp"}
    }
    try:
        url = f"{DATABASE_URL}/users/{uid}.json?auth={id_token}"
        async with session.put(url, json=starting_state, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status == 200:
                logger.info(f"[Kynex Starter] Initialized profile for {uid} with referrer {referrer_uid}")
                return True
            else:
                err_text = await resp.text()
                logger.warning(f"[Kynex Starter] Failed to write starter profile for {uid}: HTTP {resp.status} {err_text[:150]}")
                return False
    except Exception as e:
        logger.error(f"[Kynex Starter] Exception writing starter profile for {uid}: {e}")
        return False


async def get_user_profile(session: aiohttp.ClientSession, id_token: str, uid: str) -> Optional[Dict[str, Any]]:
    """Retrieves full authoritative user profile from Firebase Realtime Database."""
    try:
        url = f"{DATABASE_URL}/users/{uid}.json?auth={id_token}"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status == 200:
                return await resp.json()
    except Exception as e:
        logger.debug(f"[Kynex DB] Failed to fetch profile for {uid}: {e}")
    return None


async def call_kynex_function(
    session: aiohttp.ClientSession,
    id_token: str,
    function_name: str,
    data: Optional[Dict[str, Any]] = None
) -> Optional[Dict[str, Any]]:
    """Invokes a callable Firebase Cloud Function."""
    headers = {
        **COMMON_HEADERS,
        "Authorization": f"Bearer {id_token}"
    }
    payload = {"data": data or {}}
    url = f"{FUNCTIONS_BASE_URL}/{function_name}"
    try:
        async with session.post(url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            res_json = await resp.json()
            if resp.status == 200:
                return res_json.get("result", {})
            else:
                err = res_json.get("error", {})
                logger.debug(f"[Kynex Call] {function_name} returned HTTP {resp.status}: {err.get('message', res_json)}")
                return {"_error": err.get("message") or str(res_json), "_status": resp.status}
    except Exception as e:
        logger.debug(f"[Kynex Call] {function_name} exception: {e}")
        return {"_error": str(e), "_status": 500}


async def farm_kynex_account(
    session: aiohttp.ClientSession,
    init_data: str,
    acc_entry: dict,
    is_master: bool = False
) -> Dict[str, Any]:
    """
    Executes a comprehensive, autonomous farming cycle for a single fleet account on Kynex Network:
      1. Authenticates via Firebase callable function & retrieves JWT.
      2. Reads authoritative profile state (balance, energy, active session).
      3. Refills mining energy if depleted (using 12h starter/energyTask allowance).
      4. Claims accrued mining rewards (claimMining).
      5. Restarts mining session (startMining).
      6. Claims daily check-in bonus (claimDailyCheckin).
      7. Completes & claims all pending social channel tasks (claimSocialTask).
      8. Claims available watch ads tasks rewards (claimTasksAdReward).
    """
    name = acc_entry.get("name", "User")
    uid_raw = str(acc_entry.get("user_id"))
    result = {
        "status": "idle",
        "balance": 0.0,
        "level": 1,
        "energy_seconds": 0,
        "claimed_knx": 0.0,
        "mining_active": False,
        "notes": []
    }

    if not init_data:
        result["status"] = "skipped (no initData)"
        return result

    # 1. Authenticate
    auth_res = await authenticate_kynex(session, init_data)
    if not auth_res:
        result["status"] = "auth_failed"
        return result

    id_token = auth_res["id_token"]
    uid = auth_res["uid"]

    # 2. Fetch authoritative user profile
    await jitter(0.5, 1.2)
    profile = await get_user_profile(session, id_token, uid) or {}
    knx_bal = float(profile.get("knxBalance", 0.0) or 0.0)
    level = int(profile.get("level", 1) or 1)
    energy_sec = float(profile.get("energySeconds", 0.0) or 0.0)
    result["balance"] = knx_bal
    result["level"] = level
    result["energy_seconds"] = energy_sec

    # 3. Energy refill check: if energySeconds <= 0, refill to starter capacity (12h)
    if energy_sec <= 60:
        try:
            url = f"{DATABASE_URL}/users/{uid}/energySeconds.json?auth={id_token}"
            async with session.put(url, json=43200, timeout=aiohttp.ClientTimeout(total=8)) as r:
                if r.status == 200:
                    energy_sec = 43200.0
                    result["energy_seconds"] = energy_sec
                    result["notes"].append("energy_refilled_43200s")
        except Exception as e:
            logger.debug(f"[{name}] Kynex energy refill note: {e}")

    # 4. Claim pending mining rewards
    await jitter(0.8, 1.6)
    claim_res = await call_kynex_function(session, id_token, "claimMining")
    if claim_res and not claim_res.get("_error"):
        earned = float(claim_res.get("earnedKnx", 0.0) or 0.0)
        new_bal = float(claim_res.get("newBalance", knx_bal) or knx_bal)
        result["claimed_knx"] += earned
        result["balance"] = new_bal
        if earned > 0:
            result["notes"].append(f"claimed_{earned:.2f}_KNX")

    # 5. Start mining session
    await jitter(0.5, 1.2)
    start_res = await call_kynex_function(session, id_token, "startMining")
    if start_res and not start_res.get("_error"):
        if start_res.get("started"):
            result["mining_active"] = True
            result["notes"].append("mining_started")
    else:
        err_msg = (start_res or {}).get("_error", "")
        if "already active" in err_msg.lower():
            result["mining_active"] = True
        else:
            result["notes"].append(f"start_note: {err_msg[:60]}")

    # 6. Daily Check-in
    await jitter(0.6, 1.4)
    checkin_res = await call_kynex_function(session, id_token, "claimDailyCheckin")
    if checkin_res and not checkin_res.get("_error"):
        rew = float(checkin_res.get("rewardKnx", 0.0) or 0.0)
        streak = checkin_res.get("streak", 1)
        result["claimed_knx"] += rew
        result["balance"] = float(checkin_res.get("newBalance", result["balance"]) or result["balance"])
        result["notes"].append(f"daily_checkin_+{rew:.0f}_KNX_streak_{streak}")

    # 7. Social Tasks (channels auto-joined by Telethon token extractor)
    try:
        claimed_tasks = profile.get("tasksClaimed", {}) or {}
        # Fetch available social tasks from config
        async with session.get(f"{DATABASE_URL}/config/tasks/social.json?auth={id_token}", timeout=aiohttp.ClientTimeout(total=8)) as t_resp:
            if t_resp.status == 200:
                social_cfg = await t_resp.json() or {}
                for tid, tinfo in social_cfg.items():
                    if not claimed_tasks.get(tid):
                        await jitter(0.5, 1.0)
                        c_res = await call_kynex_function(session, id_token, "claimSocialTask", {"taskId": tid})
                        if c_res and not c_res.get("_error"):
                            t_rew = float((tinfo or {}).get("rewardKnx", 0.0) or 0.0)
                            result["claimed_knx"] += t_rew
                            result["notes"].append(f"social_{tid}_+{t_rew:.0f}_KNX")
    except Exception as e:
        logger.debug(f"[{name}] Kynex social tasks check note: {e}")

    # 8. Watch Ads Tasks (Enthusiasts Ad, Giga Ad, etc.)
    try:
        async with session.get(f"{DATABASE_URL}/config/tasksAds.json?auth={id_token}", timeout=aiohttp.ClientTimeout(total=8)) as ad_resp:
            if ad_resp.status == 200:
                ads_cfg = await ad_resp.json() or {}
                networks = ads_cfg.get("networks", [])
                for idx, net in enumerate(networks):
                    if net.get("enabled"):
                        await jitter(0.4, 0.9)
                        ad_res = await call_kynex_function(session, id_token, "claimTasksAdReward", {"networkIndex": idx})
                        if ad_res and not ad_res.get("_error"):
                            ad_rew = float(ad_res.get("rewardKnx", 0.0) or 0.0)
                            if ad_rew > 0:
                                result["claimed_knx"] += ad_rew
                                result["balance"] = float(ad_res.get("newBalance", result["balance"]) or result["balance"])
                                result["notes"].append(f"ad_{idx}_+{ad_rew:.0f}_KNX")
    except Exception as e:
        logger.debug(f"[{name}] Kynex ad tasks note: {e}")

    # Final summary status
    stat_parts = [f"bal: {result['balance']:.1f} KNX", f"lvl: {result['level']}"]
    if result["mining_active"]:
        stat_parts.append("mining: ACTIVE")
    if result["claimed_knx"] > 0:
        stat_parts.append(f"+{result['claimed_knx']:.1f} claimed")
    result["status"] = f"farmed ({', '.join(stat_parts)})"

    return result
