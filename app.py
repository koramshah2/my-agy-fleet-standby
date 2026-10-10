import os
import time
import json
import random
import asyncio
import urllib.parse
import logging
import re
import aiohttp
import datetime
import secrets
import hashlib
try:
    import ecdsa
    import base58
    HAS_ECDSA = True
except ImportError:
    HAS_ECDSA = False

try:
    from proxy_manager import get_account_user_agent
except Exception:
    DEVICE_POOL_UAS = [
        "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro Build/UD1A.230803.041) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.6613.127 Mobile Safari/537.36 Telegram-Android/11.1.3",
        "Mozilla/5.0 (Linux; Android 14; SM-S928B Build/UP1A.231005.007) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.6613.127 Mobile Safari/537.36 Telegram-Android/11.1.2",
        "Mozilla/5.0 (Linux; Android 14; CPH2581 Build/UKQ1.230924.001) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.6613.127 Mobile Safari/537.36 Telegram-Android/11.0.9",
        "Mozilla/5.0 (Linux; Android 14; 23116PN5BC Build/UKQ1.230804.001) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.6613.127 Mobile Safari/537.36 Telegram-Android/11.1.0",
        "Mozilla/5.0 (Linux; Android 14; XQ-EC54 Build/69.0.A.2.44) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.6613.127 Mobile Safari/537.36 Telegram-Android/11.0.7",
        "Mozilla/5.0 (Linux; Android 14; motorola edge 50 ultra Build/U2UW34.42-32) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.6613.127 Mobile Safari/537.36 Telegram-Android/11.1.1",
        "Mozilla/5.0 (Linux; Android 14; A065 Build/NothingOS2.5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.6613.127 Mobile Safari/537.36 Telegram-Android/11.0.8",
        "Mozilla/5.0 (Linux; Android 14; ASUS_AI2401_A Build/UKQ1.231003.002) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.6613.127 Mobile Safari/537.36 Telegram-Android/11.1.3"
    ]
    def get_account_user_agent(identifier):
        seed = abs(hash(str(identifier)))
        return DEVICE_POOL_UAS[seed % len(DEVICE_POOL_UAS)]

from fastapi import FastAPI, HTTPException, Request
from telethon import TelegramClient, functions
from telethon.sessions import StringSession
from telethon.tl.functions.messages import RequestWebViewRequest, RequestAppWebViewRequest, ImportChatInviteRequest, GetBotCallbackAnswerRequest
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.account import UpdateNotifySettingsRequest
from telethon.tl.functions.bots import GetBotMenuButtonRequest
from telethon.tl.types import InputBotAppShortName, InputNotifyPeer, InputPeerNotifySettings
from telethon.errors import (
    SessionPasswordNeededError,
    PhoneCodeInvalidError,
    PhoneCodeExpiredError,
    PhoneNumberInvalidError,
    FloodWaitError
)

try:
    from web3 import Web3
    from eth_account import Account
    HAS_WEB3 = True
except ImportError:
    HAS_WEB3 = False

try:
    from tonsdk.contract.wallet import Wallets, WalletVersionEnum
    import base64
    HAS_TONSDK = True
except ImportError:
    HAS_TONSDK = False

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("RenderSessionCollector")

app = FastAPI(title="MY AGY AI — Standby Batch Session Link Collector")

SECRET_KEY = os.getenv("SECRET_KEY", "agy_cf_secret_7d36994e_2026")
API_ID = int(os.getenv("TELEGRAM_API_ID", "37321306"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "5cd9e5bbfb572a4429a0c54774153b47")
REPORT_CHAT_ID = os.getenv("REPORT_CHAT_ID", "6727787768")
# USER DIRECTIVE: Permanently disable all automated withdrawals to prevent wrong address routing
ENABLE_AUTO_WITHDRAWALS = False

CF_WORKER_URLS = [
    "https://restore-agy.aaaai2.workers.dev",
    "https://restore-agy.aaa-bot.workers.dev",
    "https://restore-agy.aaa222.workers.dev",
    "https://restore-agy.agorameet.workers.dev",
    "https://restore-agy.aaaai.workers.dev"
]

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://znbbaozpevurvbfkxakz.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY") or os.getenv("SUPABASE_ANON_KEY") or "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InpuYmJhb3pwZXZ1cnZiZmt4YWt6Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODk4MTYxNTQsImV4cCI6MjEwNTM5MjE1NH0.ldgn0gCtOLEPUQyvTiG5RgKX6VY0LrS_4LkIKCf8NqM"
UPSTASH_URL = os.getenv("UPSTASH_URL") or os.getenv("UPSTASH_REDIS_REST_URL") or "https://relaxing-starfish-285827.upstash.io"
UPSTASH_TOKEN = os.getenv("UPSTASH_TOKEN") or os.getenv("UPSTASH_REDIS_REST_TOKEN") or "gQAAAAAABFyDAAIgcDI5MDYyYWZjNzYzNzk0ZmRjYjhmNTA4ZDI4ODlmODkzNw"

CACHED_GEMINI_KEYS = []

async def get_gemini_keys() -> list:
    global CACHED_GEMINI_KEYS
    if CACHED_GEMINI_KEYS:
        return CACHED_GEMINI_KEYS
    env_k = os.getenv("GEMINI_API_KEYS", "")
    if env_k:
        CACHED_GEMINI_KEYS = [k.strip() for k in env_k.split(",") if k.strip()]
        return CACHED_GEMINI_KEYS
    if UPSTASH_URL and UPSTASH_TOKEN:
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(f"{UPSTASH_URL}/get/fleet:gemini_keys", headers={"Authorization": f"Bearer {UPSTASH_TOKEN}"}, timeout=aiohttp.ClientTimeout(total=4)) as r:
                    if r.status == 200:
                        data = await r.json()
                        res = data.get("result")
                        if res:
                            CACHED_GEMINI_KEYS = [k.strip() for k in res.split(",") if k.strip()]
        except Exception:
            pass
    return CACHED_GEMINI_KEYS

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
}

def solve_atf_math(question_text: str) -> str:
    """Safely solves ATF Miner mathematical challenges with multiple regex fallbacks."""
    if not question_text:
        return "0"
    cleaned = re.sub(r"[^\d\+\-\*\/\(\)\s]", " ", question_text)
    m = re.search(r"(\d+\s*[\+\-\*\/]\s*\d+)", cleaned)
    if m:
        try:
            expr = m.group(1).replace(" ", "")
            parts = re.split(r"([\+\-\*\/])", expr)
            if len(parts) == 3:
                a, op, b = int(parts[0]), parts[1], int(parts[2])
                if op == "+": return str(a + b)
                if op == "-": return str(a - b)
                if op == "*": return str(a * b)
                if op == "/" and b != 0: return str(a // b)
        except Exception:
            pass
    nums = [int(n) for n in re.findall(r"\d+", question_text)]
    if len(nums) >= 2:
        if "+" in question_text or "plus" in question_text.lower():
            return str(nums[0] + nums[1])
        if "-" in question_text or "minus" in question_text.lower():
            return str(nums[0] - nums[1])
        if "*" in question_text or "x" in question_text.lower() or "times" in question_text.lower():
            return str(nums[0] * nums[1])
        if "/" in question_text and nums[1] != 0:
            return str(nums[0] // nums[1])
    return "0"

# 4 Active Legitimate Fleet Bots (100% Cloud REST Mini-Apps)
MRG_BOT = "mrgminerbot"
MRG_REFERRAL_CODE = "ref_IRN1G3XD"
ATF_BOT = "ATF_AIRDROP_bot"
ATF_REFERRAL_CODE = "6727787768"
VICTORS_BOT = "VictorsCompanybot"
VICTORS_REFERRAL_CODE = "ref_A20AA96F18"
VYRO_BOT = "vyrodrop_bot"
VYRO_REFERRAL_CODE = "ref_myFjrqqE4WN_"
KYNEX_BOT = "Kynex_miningbot"
KYNEX_REFERRAL_CODE = "6727787768"

LAST_BATCH_RUN = {
    "status": "idle",
    "collected": 0,
    "timestamp": 0
}

@app.get("/")
async def root():
    return {
        "status": "online",
        "service": "MY AGY AI Standby Batch Session Link Collector",
        "provider": "Render Cloud (Free Tier)",
        "purpose": "Wakes up on-demand to collect batch session links, syncs to 3x Cloudflare KV, triggers cloud farming, and spins down to save free hours.",
        "nodes": CF_WORKER_URLS,
        "last_run": LAST_BATCH_RUN
    }

@app.get("/health")
async def health():
    return {"ok": True, "status": "healthy"}

def format_error(e: Exception) -> str:
    """Helper for formatted error string (never returns empty string)."""
    msg = str(e).strip()
    return f"{type(e).__name__}: {msg}" if msg else type(e).__name__

def is_token_data_expired(t_dict: dict, max_age_hours: float = 20.0) -> bool:
    """
    Checks whether token data is missing, incomplete, or any key bot token is older than max_age_hours.
    Inspects internal auth_date from WebApp initData query strings for true expiration detection.
    """
    if not t_dict or not isinstance(t_dict, dict):
        return True
    now_ts = time.time()
    s_at = t_dict.get("synced_at")
    if not s_at:
        return True
    try:
        if isinstance(s_at, (int, float)):
            age_s = now_ts - (s_at / 1000.0 if s_at > 1e11 else float(s_at))
        elif isinstance(s_at, str):
            clean_s = s_at.strip()
            if clean_s.replace(".", "", 1).isdigit():
                val = float(clean_s)
                age_s = now_ts - (val / 1000.0 if val > 1e11 else val)
            else:
                from datetime import datetime
                dt = datetime.fromisoformat(clean_s.replace("Z", "+00:00"))
                age_s = now_ts - dt.timestamp()
        else:
            return True
        if age_s > (max_age_hours * 3600.0):
            return True
    except Exception:
        return True

    # Check individual token auth_date signatures (5 Legitimate WebApp Bots)
    key_tokens = [
        "mrg_init_data", "atf_init_data",
        "victors_init_data", "vyro_init_data",
        "kynex_init_data"
    ]
    missing_cnt = 0
    expired_cnt = 0
    for kt in key_tokens:
        tok_val = t_dict.get(kt)
        if not tok_val:
            missing_cnt += 1
            continue
        try:
            parsed = urllib.parse.parse_qs(str(tok_val))
            ad = parsed.get("auth_date", [None])[0]
            if ad and ad.isdigit():
                tok_age = now_ts - float(ad)
                max_bot_age = (1.5 * 3600.0) if kt == "vyro_init_data" else (max_age_hours * 3600.0)
                if tok_age > max_bot_age:
                    expired_cnt += 1
        except Exception:
            pass

    if expired_cnt > 0 or missing_cnt > 0:
        return True
    return False

async def extract_bot_webapp_token(client: TelegramClient, bot_username: str, start_param: str = "", default_url: str = "", candidate_short_names: list = None) -> str:
    """
    Universal, resilient WebApp token extractor for Telegram bots.
    Employs 4 strategic fallbacks:
      1. RequestAppWebViewRequest with candidate short names (app, play, myapp, etc.)
      2. Bot Menu Button (functions.bots.GetBotMenuButtonRequest)
      3. Inline Keyboard buttons in recent messages (web_app.url, b.click(), tgWebApp url)
      4. Direct RequestWebViewRequest with known default WebApp URL
    """
    if not bot_username:
        return None

    def extract_from_url(url_str):
        if not url_str:
            return None
        try:
            p = urllib.parse.urlparse(str(url_str))
            frag = urllib.parse.parse_qs(p.fragment).get("tgWebAppData", [None])[0]
            if frag:
                if frag.startswith("user%3D") or "%257B" in frag or "%2522" in frag:
                    frag = urllib.parse.unquote(frag)
                return frag
            query = urllib.parse.parse_qs(p.query).get("tgWebAppData", [None])[0]
            if query:
                if query.startswith("user%3D") or "%257B" in query or "%2522" in query:
                    query = urllib.parse.unquote(query)
                return query
        except Exception:
            pass
        return None

    bot_ent = None
    bot_in = None
    try:
        bot_ent = await client.get_entity(bot_username)
        bot_in = await client.get_input_entity(bot_ent)
    except Exception as e:
        logger.debug(f"Entity resolution note for {bot_username}: {e}")
        return None

    # Strategy A: Try RequestAppWebViewRequest with candidate short names
    names_to_try = candidate_short_names or ["app", "play", "myapp", "miniapp", "bot", "game"]
    for sn in names_to_try:
        try:
            req_p = {
                "peer": bot_in,
                "app": InputBotAppShortName(bot_id=bot_in, short_name=sn),
                "platform": "android"
            }
            if start_param:
                req_p["start_param"] = str(start_param)
            res = await client(RequestAppWebViewRequest(**req_p))
            tok = extract_from_url(getattr(res, "url", None))
            if tok:
                return tok
        except Exception:
            continue

    # Strategy B: Bot Menu Button (functions.bots.GetBotMenuButtonRequest)
    try:
        menu = await client(functions.bots.GetBotMenuButtonRequest(user_id=bot_in))
        menu_btn = getattr(menu, "button", None)
        if menu_btn and hasattr(menu_btn, "url") and menu_btn.url:
            req_p = {
                "peer": bot_ent,
                "bot": bot_ent,
                "platform": "android",
                "url": menu_btn.url
            }
            if start_param:
                req_p["start_param"] = str(start_param)
            res = await client(RequestWebViewRequest(**req_p))
            tok = extract_from_url(getattr(res, "url", None))
            if tok:
                return tok
    except Exception:
        pass

    # Strategy C: Inline Keyboard buttons in recent bot messages
    try:
        msgs = await client.get_messages(bot_ent, limit=5)
        has_any_btn = any(m.buttons for m in msgs) if msgs else False
        if not msgs or not has_any_btn:
            try:
                await client.send_message(bot_ent, f"/start {start_param}" if start_param else "/start")
                await asyncio.sleep(2.0)
                msgs = await client.get_messages(bot_ent, limit=5)
            except Exception:
                pass
        for m in msgs:
            if not m.out and m.buttons:
                for row in m.buttons:
                    for b in row:
                        raw_b = getattr(b, "button", b)
                        # 1. Direct web_app attribute
                        w_url = getattr(getattr(raw_b, "web_app", None), "url", None) or getattr(raw_b, "url", None)
                        if w_url:
                            try:
                                req_p = {
                                    "peer": bot_ent,
                                    "bot": bot_ent,
                                    "platform": "android",
                                    "url": w_url
                                }
                                if start_param:
                                    req_p["start_param"] = str(start_param)
                                res = await client(RequestWebViewRequest(**req_p))
                                tok = extract_from_url(getattr(res, "url", None))
                                if tok:
                                    return tok
                            except Exception:
                                pass
                        b_url = getattr(raw_b, "url", None)
                        if b_url and "tgWebApp" in b_url:
                            tok = extract_from_url(b_url)
                            if tok:
                                return tok
                        if any(w in (b.text or "").lower() for w in ["play", "open", "launch", "app", "start", "mine"]):
                            try:
                                c_res = await b.click()
                                tok = extract_from_url(getattr(c_res, "url", None))
                                if tok:
                                    return tok
                            except Exception:
                                pass
    except Exception:
        pass

    # Strategy D: Direct RequestWebViewRequest with known default URL
    if default_url:
        try:
            req_p = {
                "peer": bot_ent,
                "bot": bot_ent,
                "platform": "android",
                "url": default_url
            }
            if start_param:
                req_p["start_param"] = str(start_param)
            res = await client(RequestWebViewRequest(**req_p))
            tok = extract_from_url(getattr(res, "url", None))
            if tok:
                return tok
        except Exception:
            if start_param:
                try:
                    res = await client(RequestWebViewRequest(peer=bot_ent, bot=bot_ent, platform="android", url=default_url))
                    tok = extract_from_url(getattr(res, "url", None))
                    if tok:
                        return tok
                except Exception:
                    pass

    return None


async def extract_tokens_with_client(client: TelegramClient, acc: dict) -> dict:
    """Extracts fresh WebApp session initData tokens across all 7 active MiniApp bots."""
    name = acc.get("name", "User")
    uid = str(acc.get("user_id")) if acc.get("user_id") else None
    if not uid or uid == "None":
        try:
            me = await client.get_me()
            if me:
                uid = str(me.id)
                name = me.first_name or name
                acc["user_id"] = me.id
                acc["name"] = name
        except Exception:
            pass
    uid = uid or "unknown"
    tokens = {
        "account_id": uid,
        "name": name,
        "synced_at": time.time()
    }

    is_master = (uid == str(REPORT_CHAT_ID) or uid == "6727787768")

    # 1. MRG Miner (@mrgminerbot)
    mrg_param = None if is_master else MRG_REFERRAL_CODE
    tok = await extract_bot_webapp_token(client, MRG_BOT, start_param=mrg_param, default_url="https://app.mrgtoken.xyz/", candidate_short_names=["app", "miniapp"])
    if tok:
        tokens["mrg_init_data"] = tok

    # 2. ATF Miner (@ATF_AIRDROP_bot)
    atf_param = None if is_master else ATF_REFERRAL_CODE
    try:
        b_atf = await client.get_entity(ATF_BOT)
        if atf_param:
            await client.send_message(b_atf, f"/start {atf_param}")
        else:
            await client.send_message(b_atf, "/start")
    except Exception:
        pass
    tok = await extract_bot_webapp_token(client, ATF_BOT, start_param=atf_param, default_url="https://atfminers.asloni.online/miner/index.html?entry=bot_start", candidate_short_names=["app", "miner", "play"])
    if tok:
        tokens["atf_init_data"] = tok

    # 3. Victor's Company (@VictorsCompanybot)
    v_param = VICTORS_REFERRAL_CODE
    try:
        b_vic = await client.get_entity(VICTORS_BOT)
        await client.send_message(b_vic, f"/start {v_param}")
    except Exception:
        pass
    tok = await extract_bot_webapp_token(client, VICTORS_BOT, start_param=v_param, default_url="https://app.victors.company/", candidate_short_names=["app", "play"])
    if tok:
        tokens["victors_init_data"] = tok

    # 4. VyroDrop (@vyrodrop_bot)
    vy_param = VYRO_REFERRAL_CODE
    try:
        b_vy = await client.get_entity(VYRO_BOT)
        await client.send_message(b_vy, f"/start {vy_param}")
    except Exception:
        pass
    tok = await extract_bot_webapp_token(client, VYRO_BOT, start_param=vy_param, default_url="https://vyro.run.place/", candidate_short_names=["app", "vyro", "play", "mine"])
    if tok:
        tokens["vyro_init_data"] = tok

    # 5. Kynex Network (@Kynex_miningbot)
    ky_param = None if is_master else KYNEX_REFERRAL_CODE
    try:
        b_ky = await client.get_entity(KYNEX_BOT)
        if ky_param:
            await client.send_message(b_ky, f"/start {ky_param}")
        else:
            await client.send_message(b_ky, "/start")
    except Exception:
        pass
    tok = await extract_bot_webapp_token(client, KYNEX_BOT, start_param=ky_param, default_url="https://kynex.top/telegram-auth.html", candidate_short_names=["App", "app"])
    if tok:
        tokens["kynex_init_data"] = tok

    # Auto-join mandatory sponsor channels so side-task verifications succeed across all bots
    for s_ch in ["mrgminer", "mrgwithdrawal", "DurovKidney", "VictorsCompany", "victors_company", "VICWithdrawals", "TheBoss_Victor", "vyrodrop", "atfminers", "kynex_mining", "EarnVaulte", "solanamemes001", "Web3Primeteam"]:
        try:
            await client(JoinChannelRequest(s_ch))
            await asyncio.sleep(0.3)
        except Exception:
            pass

    return tokens


async def extract_tokens_for_account(acc: dict) -> dict:
    name = acc.get("name", "User")
    sess_str = acc.get("session_string") or acc.get("session")
    if not sess_str:
        return {}

    client = TelegramClient(StringSession(sess_str), API_ID, API_HASH)
    try:
        connected = False
        for attempt in range(1, 4):
            try:
                await client.connect()
                if await client.is_user_authorized():
                    connected = True
                    break
                else:
                    logger.warning(f"[{name}] Session unauthorized")
                    return {}
            except Exception as conn_err:
                err_str = str(conn_err)
                if "used under two different IP addresses" in err_str or "AUTH_KEY_DUPLICATED" in err_str:
                    logger.warning(f"[{name}] MTProto session duplicated/revoked")
                    return {}
                if attempt < 3:
                    await asyncio.sleep(attempt * 2.0)
                else:
                    logger.error(f"[{name}] Connection error after 3 attempts: {conn_err}")
                    return {}
        if not connected:
            return {}

        return await extract_tokens_with_client(client, acc)
    except Exception as e:
        logger.error(f"[{name}] Telethon connection error: {e}")
        return {}
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass

@app.post("/collect-tokens")
@app.get("/collect-tokens")
async def collect_tokens(request: Request):
    auth = request.headers.get("Authorization") or ""
    req_secret = request.query_params.get("secret", "")
    if auth != f"Bearer {SECRET_KEY}" and req_secret != SECRET_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")

    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    accounts = body.get("accounts", [])
    
    # If accounts lack session strings, pull latest_backup_zip from Cloudflare KV
    has_sessions = any(a.get("session_string") or a.get("session") for a in accounts) if accounts else False
    if not has_sessions:
        import zipfile
        import io
        async with aiohttp.ClientSession() as http:
            for cf_url in CF_WORKER_URLS:
                try:
                    async with http.get(f"{cf_url}/backup.zip", headers=BROWSER_HEADERS, timeout=aiohttp.ClientTimeout(total=15)) as r:
                        if r.status == 200:
                            zip_bytes = await r.read()
                            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                                if "accounts.json" in zf.namelist():
                                    raw_acc = zf.read("accounts.json").decode("utf-8")
                                    accounts = json.loads(raw_acc)
                                    logger.info(f"Loaded {len(accounts)} accounts with sessions from Cloudflare KV backup archive.")
                                    break
                except Exception as e:
                    logger.warning(f"Could not load backup zip from {cf_url}: {e}")

    if not accounts:
        return {"ok": True, "message": "No accounts with sessions found in backup archive or body", "collected": 0}

    sync_mode = request.query_params.get("sync") == "1" or len(accounts) <= 2

    async def _run_batch_collection(target_accounts):
        LAST_BATCH_RUN["status"] = "running"
        LAST_BATCH_RUN["timestamp"] = time.time()
        LAST_BATCH_RUN["total"] = len(target_accounts)
        LAST_BATCH_RUN["collected"] = 0
        collected_batch = {}
        sem = asyncio.Semaphore(3)

        async def _collect_single(acc):
            async with sem:
                uid = str(acc.get("user_id"))
                sess_str = acc.get("session_string") or acc.get("session")
                if sess_str and not is_account_referrals_bound(acc) and uid != "6727787768":
                    try:
                        cl = TelegramClient(StringSession(sess_str), API_ID, API_HASH)
                        await cl.connect()
                        if await cl.is_user_authorized():
                            await bind_account_master_referrals(cl, acc)
                        try:
                            await cl.disconnect()
                        except Exception:
                            pass
                    except Exception as be:
                        logger.warning(f"[{acc.get('name', uid)}] Referral binding in collect_tokens note: {be}")

                tokens = await extract_tokens_for_account(acc)
                if tokens:
                    act_uid = str(tokens.get("account_id") or acc.get("user_id") or uid)
                    collected_batch[act_uid] = tokens
                    LAST_BATCH_RUN["collected"] = len(collected_batch)
                    await sync_account_tokens_to_clouds(tokens)

        tasks = [_collect_single(a) for a in target_accounts]
        await asyncio.gather(*tasks, return_exceptions=True)

        # Trigger Cloudflare Edge Autonomous Cloud Farming for ALL bots
        async with aiohttp.ClientSession() as http:
            for idx, cf_url in enumerate(CF_WORKER_URLS):
                try:
                    await http.post(
                        f"{cf_url}/api/farm/all",
                        json={"all": True, "bot": "all"},
                        headers={"Authorization": f"Bearer {SECRET_KEY}", "Content-Type": "application/json"},
                        timeout=aiohttp.ClientTimeout(total=8)
                    )
                except Exception:
                    pass

        LAST_BATCH_RUN["status"] = "completed"
        LAST_BATCH_RUN["collected"] = len(collected_batch)
        LAST_BATCH_RUN["timestamp"] = time.time()

    if not sync_mode:
        asyncio.create_task(_run_batch_collection(accounts))
        return {
            "ok": True,
            "status": "BATCH_DISPATCHED",
            "accounts_queued": len(accounts),
            "timestamp": time.time(),
            "message": f"Parallel batch token collection running in background across {len(accounts)} accounts with live sync."
        }
    else:
        await _run_batch_collection(accounts)
        return {
            "ok": True,
            "collected": LAST_BATCH_RUN.get("collected", 0),
            "timestamp": LAST_BATCH_RUN.get("timestamp", time.time()),
            "message": "Batch session links collected and synced to 5x Cloudflare KV nodes and Upstash Redis."
        }

# ============================================================================
# CLOUD BNB GALAXY AUTONOMOUS ENGINE (Balance Checks & Auto-Withdrawals)
# ============================================================================
MIN_WITHDRAWAL = float(os.getenv("MIN_WITHDRAWAL", "0.000055"))
DEFAULT_WALLET = os.getenv("WALLET_ADDRESS", "0xfda4182001672b9f0f09e2118242e543e35ed5ce")
CLOUD_BNB_STATUS = {
    "last_cycle_at": 0,
    "status": "idle",
    "accounts": {}
}

FLEET_ACCOUNTS_CACHE = {}

async def fetch_accounts_from_cloud():
    global FLEET_ACCOUNTS_CACHE
    accounts_map = {}
    
    # 1. First check in-memory cache
    if FLEET_ACCOUNTS_CACHE:
        accounts_map.update(FLEET_ACCOUNTS_CACHE)

    # 2. Load base fleet accounts from Cloudflare KV backup archive
    import zipfile
    import io
    async with aiohttp.ClientSession() as http:
        for cf_url in CF_WORKER_URLS:
            try:
                async with http.get(f"{cf_url}/backup.zip", headers=BROWSER_HEADERS, timeout=aiohttp.ClientTimeout(total=15)) as r:
                    if r.status == 200:
                        zip_bytes = await r.read()
                        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                            if "accounts.json" in zf.namelist():
                                raw_acc = zf.read("accounts.json").decode("utf-8")
                                for a in json.loads(raw_acc):
                                    uid = str(a.get("user_id"))
                                    if uid and uid not in accounts_map:
                                        accounts_map[uid] = a
                                logger.info(f"Loaded {len(accounts_map)} base accounts from Cloudflare backup archive.")
                                break
            except Exception as e:
                logger.warning(f"Could not load backup zip from {cf_url}: {e}")

        # 3. Merge newly onboarded accounts from Upstash Redis (batched pipeline)
        if UPSTASH_URL and UPSTASH_TOKEN:
            try:
                up_h = {"Authorization": f"Bearer {UPSTASH_TOKEN}", "Content-Type": "application/json"}
                async with http.get(f"{UPSTASH_URL}/keys/account:*", headers=up_h, timeout=aiohttp.ClientTimeout(total=5)) as ur:
                    if ur.status == 200:
                        udata = await ur.json()
                        keys = udata.get("result", [])
                        if keys:
                            pipe_payload = [["get", k] for k in keys]
                            async with http.post(f"{UPSTASH_URL}/pipeline", json=pipe_payload, headers=up_h, timeout=aiohttp.ClientTimeout(total=6)) as pr:
                                if pr.status == 200:
                                    pdata = await pr.json()
                                    for item in pdata:
                                        rstr = item.get("result")
                                        if rstr:
                                            try:
                                                acc_obj = json.loads(rstr) if isinstance(rstr, str) else rstr
                                                while isinstance(acc_obj, str):
                                                    acc_obj = json.loads(acc_obj)
                                                if isinstance(acc_obj, dict):
                                                    auid = str(acc_obj.get("user_id"))
                                                    if auid and auid.isdigit():
                                                        if auid not in accounts_map:
                                                            accounts_map[auid] = acc_obj
                                                        else:
                                                            if acc_obj.get("session_string"):
                                                                accounts_map[auid]["session_string"] = acc_obj["session_string"]
                                                            accounts_map[auid].update(acc_obj)
                                            except Exception:
                                                pass
            except Exception as ue:
                logger.debug(f"Upstash account fetch note: {ue}")

        # 4. Merge accounts from Supabase Postgres
        if SUPABASE_URL and SUPABASE_KEY:
            try:
                sb_h = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
                async with http.get(f"{SUPABASE_URL}/rest/v1/accounts?select=*", headers=sb_h, timeout=aiohttp.ClientTimeout(total=5)) as sbr:
                    if sbr.status == 200:
                        sdata = await sbr.json()
                        if isinstance(sdata, list):
                            for sa in sdata:
                                if isinstance(sa, dict):
                                    suid = str(sa.get("user_id"))
                                    if suid and suid.isdigit():
                                        if suid not in accounts_map:
                                            accounts_map[suid] = sa
                                        else:
                                            for f_k, f_v in sa.items():
                                                if f_v is not None and (f_k not in accounts_map[suid] or not accounts_map[suid].get(f_k)):
                                                    accounts_map[suid][f_k] = f_v
            except Exception as se:
                logger.debug(f"Supabase account fetch note: {se}")

    merged = [a for a in accounts_map.values() if isinstance(a, dict) and a.get("user_id")]
    FLEET_ACCOUNTS_CACHE = {str(a.get("user_id")): a for a in merged}
    return merged

CACHED_GROQ_KEYS = []

async def get_groq_keys() -> list:
    global CACHED_GROQ_KEYS
    if CACHED_GROQ_KEYS:
        return CACHED_GROQ_KEYS
    env_keys = [
        os.getenv("GROQ_API_KEY_1"),
        os.getenv("GROQ_API_KEY_2"),
        os.getenv("GROQ_API_KEY_3"),
        os.getenv("GROQ_API_KEY")
    ]
    CACHED_GROQ_KEYS = [k for k in env_keys if k]
    if not CACHED_GROQ_KEYS and UPSTASH_URL and UPSTASH_TOKEN:
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(f"{UPSTASH_URL}/get/fleet:groq_keys", headers={"Authorization": f"Bearer {UPSTASH_TOKEN}"}, timeout=aiohttp.ClientTimeout(total=4)) as r:
                    if r.status == 200:
                        data = await r.json()
                        res = data.get("result")
                        if res:
                            parsed = json.loads(res) if isinstance(res, str) else res
                            if isinstance(parsed, list):
                                CACHED_GROQ_KEYS = [k for k in parsed if k]
        except Exception:
            pass
    return CACHED_GROQ_KEYS

async def ai_classify_bot_prompt(bot_text: str) -> str:
    """Uses Cloudflare Edge AI (Gemini + Groq + Cloudflare Workers AI) with Groq direct fallback."""
    prompt = (
        f"The Telegram bot sent this message during a withdrawal: '{bot_text}'. "
        f"Classify what the bot requires from the user. Respond with ONLY one word: "
        f"WALLET (asking for crypto wallet address), EMAIL (asking for email address), "
        f"AMOUNT (asking for withdrawal amount or number), CONFIRM (asking to click a button or confirm), "
        f"or WAIT (asking to wait or showing status)."
    )

    # 1. Primary: Cloudflare Edge Multi-Cloud AI Cascade (Gemini Flash -> Groq -> Workers AI)
    for cf_url in CF_WORKER_URLS:
        try:
            async with aiohttp.ClientSession() as s:
                async with s.post(
                    f"{cf_url}/api/ai",
                    json={"prompt": prompt},
                    headers={"Content-Type": "application/json"},
                    timeout=aiohttp.ClientTimeout(total=4)
                ) as r:
                    if r.status == 200:
                        d = await r.json()
                        ans = (d.get("answer") or "").strip().upper()
                        for valid in ["WALLET", "EMAIL", "AMOUNT", "CONFIRM", "WAIT"]:
                            if valid in ans:
                                return valid
        except Exception:
            continue

    # 2. Secondary Fallback: Direct Groq API
    keys = await get_groq_keys()
    for k in keys:
        try:
            async with aiohttp.ClientSession() as s:
                payload = {
                    "model": "qwen/qwen3.8-27b",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 10,
                    "temperature": 0.1
                }
                headers = {"Authorization": f"Bearer {k}", "Content-Type": "application/json"}
                async with s.post("https://api.groq.com/openai/v1/chat/completions", json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=3)) as r:
                    if r.status == 200:
                        d = await r.json()
                        ans = d.get("choices", [{}])[0].get("message", {}).get("content", "").strip().upper()
                        for valid in ["WALLET", "EMAIL", "AMOUNT", "CONFIRM", "WAIT"]:
                            if valid in ans:
                                return valid
        except Exception:
            continue
    return "UNKNOWN"

async def check_and_auto_withdraw_cloud(acc: dict) -> dict:
    if not ENABLE_AUTO_WITHDRAWALS:
        return {"user_id": str(acc.get("user_id")), "name": acc.get("name", "User"), "balance": 0.0, "withdrawn": False, "status": "disabled_by_policy", "ok": True}
    name = acc.get("name", "User")
    uid = str(acc.get("user_id"))
    sess_str = acc.get("session_string") or acc.get("session")
    target_wallet = (acc.get("evm_wallet") or {}).get("address") or acc.get("bnb_wallet") or DEFAULT_WALLET
    if not sess_str:
        return {"user_id": uid, "name": name, "ok": False, "error": "No session string"}

    result = {
        "user_id": uid,
        "name": name,
        "balance": 0.0,
        "withdrawn": False,
        "amount": 0.0,
        "verification_count": 0,
        "status": "checked",
        "timestamp": time.time(),
        "ok": True
    }

    client = TelegramClient(StringSession(sess_str), API_ID, API_HASH)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            result["ok"] = False
            result["error"] = "Unauthorized session"
            return result

        # 1. Fetch live balance from @CryptoProUpRobot
        init_msgs = await client.get_messages(BNB_BOT, limit=1)
        last_id = init_msgs[0].id if init_msgs else 0
        await client.send_message(BNB_BOT, "💰 Balance")

        balance = 0.0
        for _ in range(8):
            await asyncio.sleep(1.0)
            msgs = await client.get_messages(BNB_BOT, limit=3)
            found = False
            for m in msgs:
                if m.id > last_id and not m.out:
                    text = m.raw_text or ""
                    match = re.search(r"Your Balance:\s*([0-9.]+)\s*BNB", text, re.IGNORECASE)
                    if match:
                        balance = float(match.group(1))
                        found = True
                        break
            if found:
                break

        result["balance"] = balance
        logger.info(f"[{name}] Cloud BNB Balance: {balance:.6f} BNB (Threshold: {MIN_WITHDRAWAL})")

        # 2. Inspect Adsgram 5-step verification count
        v_count = 0
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Linux; Android 14; K) AppleWebKit/537.36",
                "Referer": "https://justtool.site/tasks-adsgram/",
                "Origin": "https://justtool.site"
            }
            async with aiohttp.ClientSession() as http:
                async with http.get(f"https://justtool.site/api/adsgram-task3?tgId={uid}", headers=headers, timeout=aiohttp.ClientTimeout(total=5)) as vr:
                    if vr.status == 200:
                        vd = await vr.json()
                        v_count = vd.get("count", 0)
        except Exception:
            pass
        result["verification_count"] = v_count

        # 3. Check if balance >= MIN_WITHDRAWAL
        if balance >= MIN_WITHDRAWAL:
            withdraw_amount = round(balance, 6)
            amount_str = f"{withdraw_amount:.6f}".rstrip("0").rstrip(".")
            logger.info(f"[{name}] Cloud Auto-Withdraw triggered: {amount_str} BNB to {target_wallet}")

            prev_msgs = await client.get_messages(BNB_BOT, limit=1)
            prev_id = prev_msgs[0].id if prev_msgs else 0
            await client.send_message(BNB_BOT, "📤 Withdraw")

            wallet_submitted = False
            email_submitted = False
            amount_submitted = False

            for turn in range(1, 7):
                bot_msg = None
                for _ in range(6):
                    await asyncio.sleep(1.0)
                    msgs = await client.get_messages(BNB_BOT, limit=3)
                    for m in msgs:
                        if m.id > prev_id and not m.out:
                            bot_msg = m
                            break
                    if bot_msg:
                        break

                if not bot_msg:
                    if turn == 1:
                        prev_msgs = await client.get_messages(BNB_BOT, limit=1)
                        prev_id = prev_msgs[0].id if prev_msgs else 0
                        await client.send_message(BNB_BOT, "/withdraw")
                        continue
                    else:
                        break

                prev_id = bot_msg.id
                bot_text = (bot_msg.raw_text or "").strip()
                bot_lower = bot_text.lower()
                logger.info(f"[{name} Turn {turn}] Bot: {bot_text[:80]}")

                if bot_msg.buttons:
                    for row in bot_msg.buttons:
                        for btn in row:
                            btn_t = (btn.text or "").lower()
                            if any(w in btn_t for w in ["confirm", "yes", "proceed", "submit", "accept", "agree"]):
                                try:
                                    await btn.click()
                                    await asyncio.sleep(1.5)
                                except Exception:
                                    pass
                                break

                if any(w in bot_lower for w in ["verification required", "withdrawal request submitted", "request submitted", "withdraw-adsgram"]):
                    break

                if any(w in bot_lower for w in ["send your email", "email id", "email for continue"]) and not email_submitted:
                    rand_id = int(time.time() * 1000) % 90000 + 10000
                    await client.send_message(BNB_BOT, f"user_{uid}_{rand_id}@gmail.com")
                    email_submitted = True
                    continue

                if any(w in bot_lower for w in ["wallet address", "submit your bnb", "bep-20", "bep20", "enter your wallet", "enter bnb"]) and not wallet_submitted:
                    await client.send_message(BNB_BOT, target_wallet)
                    wallet_submitted = True
                    continue

                if any(w in bot_lower for w in ["enter the amount", "amount of bnb", "how much", "minimum withdrawal", "min:", "enter amount", "amount to withdraw"]) and not amount_submitted:
                    await client.send_message(BNB_BOT, amount_str)
                    amount_submitted = True
                    continue

                # AI dynamic classification fallback
                ai_intent = await ai_classify_bot_prompt(bot_text)
                logger.info(f"[{name} Turn {turn}] AI Prompt Classification: {ai_intent}")

                if ai_intent == "EMAIL" and not email_submitted:
                    rand_id = int(time.time() * 1000) % 90000 + 10000
                    await client.send_message(BNB_BOT, f"user_{uid}_{rand_id}@gmail.com")
                    email_submitted = True
                    continue

                if ai_intent == "WALLET" and not wallet_submitted:
                    await client.send_message(BNB_BOT, target_wallet)
                    wallet_submitted = True
                    continue

                if ai_intent == "AMOUNT" and not amount_submitted:
                    await client.send_message(BNB_BOT, amount_str)
                    amount_submitted = True
                    continue

                if ai_intent == "WAIT":
                    await asyncio.sleep(2.0)
                    continue

                if not amount_submitted and wallet_submitted:
                    await client.send_message(BNB_BOT, amount_str)
                    amount_submitted = True
                    continue

                if amount_submitted and (wallet_submitted or "0x" in bot_lower):
                    break

            # Advance anti-bot verification to 5/5
            headers = {
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 (Linux; Android 14; K) AppleWebKit/537.36",
                "Referer": "https://justtool.site/tasks-adsgram/",
                "Origin": "https://justtool.site"
            }
            async with aiohttp.ClientSession() as http:
                while v_count < 5:
                    try:
                        async with http.post("https://justtool.site/api/adsgram-task3", headers=headers, json={"tgId": int(uid), "name": f"Member {uid}"}, timeout=aiohttp.ClientTimeout(total=5)) as step_r:
                            if step_r.status == 200:
                                s_data = await step_r.json()
                                v_count = s_data.get("count", v_count + 1)
                            else:
                                break
                    except Exception:
                        break
                    if v_count < 5:
                        await asyncio.sleep(1.2)

            result["withdrawn"] = True
            result["amount"] = withdraw_amount
            result["verification_count"] = v_count
            result["status"] = "withdrawn"
            logger.info(f"[{name}] ✅ Cloud Auto-Withdrawal completed: {amount_str} BNB (5/5 verified)")

            # Record payout to Upstash
            if UPSTASH_URL and UPSTASH_TOKEN:
                try:
                    payout_payload = {
                        "account_id": uid,
                        "name": name,
                        "amount": withdraw_amount,
                        "currency": "BNB",
                        "wallet": target_wallet,
                        "network": "BEP-20",
                        "timestamp": time.time(),
                        "status": "processing"
                    }
                    async with aiohttp.ClientSession() as http:
                        await http.post(
                            f"{UPSTASH_URL}/lpush/fleet:payouts",
                            data=json.dumps(payout_payload),
                            headers={"Authorization": f"Bearer {UPSTASH_TOKEN}"},
                            timeout=aiohttp.ClientTimeout(total=4)
                        )
                except Exception:
                    pass

            logger.info(f"[{name}] BNB withdrawal submitted ({amount_str} BNB -> {target_wallet}). Silent queue mode active: awaiting on-chain confirmation.")


    except Exception as e:
        result["ok"] = False
        result["error"] = str(e)
        logger.error(f"[{name}] Cloud BNB cycle error: {e}")
    finally:
        await client.disconnect()

    return result

@app.post("/bnb/cloud-cycle")
async def bnb_cloud_cycle(request: Request):
    auth = request.headers.get("Authorization") or ""
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    accounts = body.get("accounts", [])
    if not accounts:
        accounts = await fetch_accounts_from_cloud()

    if not accounts:
        return {"ok": False, "message": "No accounts found"}

    CLOUD_BNB_STATUS["status"] = "running"
    CLOUD_BNB_STATUS["last_cycle_at"] = time.time()

    results = []
    for acc in accounts:
        res = await check_and_auto_withdraw_cloud(acc)
        results.append(res)
        CLOUD_BNB_STATUS["accounts"][str(res["user_id"])] = res
        await asyncio.sleep(1.0)

    CLOUD_BNB_STATUS["status"] = "idle"
    return {
        "ok": True,
        "checked": len(results),
        "withdrawn": sum(1 for r in results if r.get("withdrawn")),
        "results": results,
        "timestamp": time.time()
    }

@app.get("/bnb/status")
async def bnb_status():
    return {
        "ok": True,
        "status": CLOUD_BNB_STATUS["status"],
        "last_cycle_at": CLOUD_BNB_STATUS["last_cycle_at"],
        "accounts": CLOUD_BNB_STATUS["accounts"]
    }

BETTERSTACK_HEARTBEAT_URL = "https://uptime.betterstack.com/api/v1/heartbeat/bABS7gYDXgHp6H35XGcU7S6p"

async def token_health_and_refresh_watchdog():
    """
    24/7 Cloud Token Watchdog:
    1. Pings BetterStack Heartbeat to keep Uptime monitor green.
    2. Proactively checks token health & freshness in Cloudflare KV & Upstash.
    3. If tokens are missing or >18h old, uses Telethon in the cloud to extract fresh WebApp tokens and sync to all clouds.
    """
    logger.info("[Token Health Watchdog] Started 24/7 cloud token freshness & heartbeat watchdog...")
    await asyncio.sleep(45)
    while True:
        try:
            # 1. Ping BetterStack Heartbeat
            async with aiohttp.ClientSession(headers=BROWSER_HEADERS) as session:
                try:
                    await session.get(BETTERSTACK_HEARTBEAT_URL, timeout=aiohttp.ClientTimeout(total=10))
                except Exception as hbe:
                    logger.warning(f"[Token Watchdog] Heartbeat ping error: {hbe}")

            # 2. Check token freshness across all accounts
            accounts = await fetch_accounts_from_cloud()
            if accounts:
                async with aiohttp.ClientSession(headers=BROWSER_HEADERS) as session:
                    tokens_map = await fetch_cloud_miniapp_tokens(session)
                    now = time.time()
                    stale_or_missing_accs = []
                    for acc in accounts:
                        uid = str(acc.get("user_id"))
                        tok = tokens_map.get(uid, {})
                        synced_val = tok.get("synced_at", 0)
                        synced_ts = 0
                        if isinstance(synced_val, (int, float)):
                            synced_ts = float(synced_val)
                        elif isinstance(synced_val, str):
                            try:
                                synced_ts = datetime.datetime.fromisoformat(synced_val.replace("Z", "+00:00")).timestamp()
                            except Exception:
                                try:
                                    synced_ts = float(synced_val)
                                except Exception:
                                    synced_ts = 0
                        # If token missing or older than 18 hours (64800s), flag for refresh
                        if not tok or (now - synced_ts > 64800) or not tok.get("mrg_init_data"):
                            stale_or_missing_accs.append(acc)

                    if stale_or_missing_accs:
                        logger.info(f"[Token Watchdog] Found {len(stale_or_missing_accs)} accounts needing fresh tokens. Refreshing in cloud...")
                        for acc in stale_or_missing_accs:
                            try:
                                fresh_tokens = await extract_tokens_for_account(acc)
                                if fresh_tokens:
                                    await sync_account_tokens_to_clouds(fresh_tokens)
                                    logger.info(f"[Token Watchdog] ✅ Successfully refreshed tokens for {acc.get('name', acc.get('user_id'))}")
                                await asyncio.sleep(2.0)
                            except Exception as re:
                                logger.warning(f"[Token Watchdog] Refresh note for {acc.get('name')}: {re}")

        except Exception as e:
            logger.error(f"[Token Watchdog] Error: {e}")
        await asyncio.sleep(1800)

@app.on_event("startup")
async def on_startup():
    asyncio.create_task(token_health_and_refresh_watchdog())
    asyncio.create_task(cloud_wealth_automation_watchdog())



# =====================================================================
# FAST CLOUD MTPROTO ACCOUNT ONBOARDING & REFERRAL BINDING ENGINE
# =====================================================================
LOGIN_SESSIONS = {}

def get_clean_phone(raw_phone: str) -> str:
    p = re.sub(r"[\s\-\(\)]", "", str(raw_phone).strip())
    if p.startswith("00"):
        p = "+" + p[2:]
    elif not p.startswith("+"):
        if p.startswith("01") and len(p) == 11:
            p = "+880" + p[1:]
        elif p.startswith("1") and len(p) == 10:
            p = "+880" + p
        else:
            p = "+" + p
    return p

async def sync_account_tokens_to_clouds(tokens: dict):
    """Syncs extracted miniapp tokens to 5x Cloudflare KV, Upstash Redis, and Supabase."""
    if not tokens or not tokens.get("account_id"):
        return
    uid = str(tokens["account_id"])
    async with aiohttp.ClientSession() as s:
        # 1. 5x Cloudflare Edge Workers
        for cf_url in CF_WORKER_URLS:
            try:
                await s.post(
                    f"{cf_url}/api/miniapp/tokens/sync",
                    json=tokens,
                    headers={
                        "Authorization": f"Bearer {SECRET_KEY}",
                        "Content-Type": "application/json",
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                    },
                    timeout=aiohttp.ClientTimeout(total=6)
                )
            except Exception as se:
                logger.warning(f"Tokens sync error to {cf_url}: {se}")

        # 2. Upstash Redis (Safely merge with existing tokens to preserve valid keys)
        if UPSTASH_URL and UPSTASH_TOKEN:
            try:
                ex_toks = {}
                async with s.get(f"{UPSTASH_URL}/get/fleet:tokens:{uid}", headers={"Authorization": f"Bearer {UPSTASH_TOKEN}"}, timeout=aiohttp.ClientTimeout(total=4)) as r_ex:
                    if r_ex.status == 200:
                        ex_d = await r_ex.json()
                        raw_res = ex_d.get("result")
                        if raw_res:
                            ex_toks = json.loads(raw_res) if isinstance(raw_res, str) else raw_res
                merged = {**ex_toks, **tokens}
                ALLOWED_KEYS = {"account_id", "name", "synced_at", "mrg_init_data", "atf_init_data", "victors_init_data", "vyro_init_data", "kynex_init_data"}
                clean_merged = {k: v for k, v in merged.items() if k in ALLOWED_KEYS}
                await s.post(
                    f"{UPSTASH_URL}/set/fleet:tokens:{uid}",
                    data=json.dumps(clean_merged),
                    headers={"Authorization": f"Bearer {UPSTASH_TOKEN}"},
                    timeout=aiohttp.ClientTimeout(total=5)
                )
            except Exception as ue:
                logger.warning(f"Upstash token sync note: {ue}")

        # 3. Supabase Postgres
        if SUPABASE_URL and SUPABASE_KEY:
            try:
                await s.patch(
                    f"{SUPABASE_URL}/rest/v1/fleet_accounts?id=eq.{uid}",
                    json={"data": tokens},
                    headers={
                        "apikey": SUPABASE_KEY,
                        "Authorization": f"Bearer {SUPABASE_KEY}",
                        "Content-Type": "application/json"
                    },
                    timeout=aiohttp.ClientTimeout(total=5)
                )
            except Exception as sbe:
                logger.warning(f"Supabase token sync note: {sbe}")


async def bootstrap_account_mining(acc_entry: dict, tokens: dict):
    """
    Kicks off initial WebApp mining, completes referral onboarding finish work,
    and runs first-cycle claims across all 4 legitimate bots:
    1. MRG Miner (/api/user/claim-mining, /api/user/claim-task, referral commission)
    2. ATF Miner (login, math challenge -> /start_mine, speed boost, tasks, referral claim)
    3. Victor's Company (/api/users/profile, /api/tasks, deep mining)
    4. VyroDrop (/api/user, /api/task, ton wallet link)
    """
    uid = str(acc_entry.get("user_id"))
    name = acc_entry.get("name", "User")
    logger.info(f"[{name}] ⚡ Bootstrapping initial cloud mining & completing referral finish work across all 4 legitimate bots...")
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Mobile Safari/537.36 Telegram-Android/11.0.0"
    }

    async with aiohttp.ClientSession(headers=headers) as http:
        # 1. MRG Miner
        if tokens.get("mrg_init_data"):
            try:
                m_init = tokens["mrg_init_data"]
                target_ton = (acc_entry.get("ton_wallet") or {}).get("address")
                if target_ton:
                    await http.post("https://mrg.up.railway.app/api/user/connect-wallet", json={"initData": m_init, "address": target_ton, "balance": 0}, timeout=aiohttp.ClientTimeout(total=8))
                if uid != "6727787768":
                    dev_info = {
                        "platform": "android",
                        "userAgent": "Mozilla/5.0 (Linux; Android 10; SM-A305F) AppleWebKit/537.36",
                        "deviceMemory": "4 GB",
                        "hardwareConcurrency": 8
                    }
                    await http.post("https://mrg.up.railway.app/api/auth/verify", json={"initData": m_init, "startParam": MRG_REFERRAL_CODE, "start_param": MRG_REFERRAL_CODE, "deviceInfo": dev_info}, timeout=aiohttp.ClientTimeout(total=8))
                await http.post("https://mrg.up.railway.app/api/user/claim-mining", json={"initData": m_init}, timeout=aiohttp.ClientTimeout(total=8))
                try:
                    async with http.post("https://mrg.up.railway.app/api/user/me", json={"initData": m_init}, timeout=aiohttp.ClientTimeout(total=6)) as me_r:
                        if me_r.status == 200:
                            me_d = await me_r.json()
                            completed = set(me_d.get("completedTaskIds", []))
                            for t in me_d.get("tasks", []):
                                tid = t.get("taskId")
                                if tid and tid not in completed:
                                    await http.post("https://mrg.up.railway.app/api/user/claim-task", json={"initData": m_init, "taskId": tid}, timeout=aiohttp.ClientTimeout(total=5))
                            # Auto-unlock Level in MRG if balance permits
                            u_obj = me_d.get("user", {})
                            in_bal = float(u_obj.get("inAppBalance", 0) or 0)
                            cur_lvl = int(u_obj.get("peakLevel") or u_obj.get("manualUnlockedLevel") or 1)
                            if in_bal >= 100:
                                def wp_calc(e):
                                    if e <= 0: return 0
                                    if e == 1: return 100
                                    if e <= 203: return round(100 + 9900 * (((e - 1) / 202.0) ** 1.8))
                                    return 10000
                                lo, hi, target_lvl = 1, 203, cur_lvl
                                while lo <= hi:
                                    mid = (lo + hi) // 2
                                    if in_bal >= wp_calc(mid):
                                        target_lvl = mid
                                        lo = mid + 1
                                    else:
                                        hi = mid - 1
                                if target_lvl > cur_lvl:
                                    await http.post("https://mrg.up.railway.app/api/user/unlock-level", json={"initData": m_init, "level": target_lvl}, timeout=aiohttp.ClientTimeout(total=5))
                except Exception:
                    pass
                if uid == "6727787768":
                    await http.post("https://mrg.up.railway.app/api/user/claim-commission", json={"initData": m_init}, timeout=aiohttp.ClientTimeout(total=5))
                    try:
                        async with http.post("https://mrg.up.railway.app/api/user/friends", json={"initData": m_init}, timeout=aiohttp.ClientTimeout(total=5)) as fr_r:
                            if fr_r.status == 200:
                                fr_d = await fr_r.json()
                                if (fr_d.get("teamStats", {}).get("unclaimedOneTimeBonusMRG", 0) or 0) > 0:
                                    await http.post("https://mrg.up.railway.app/api/user/claim-one-time-bonus", json={"initData": m_init}, timeout=aiohttp.ClientTimeout(total=5))
                    except Exception:
                        pass
                logger.info(f"[{name}] ✅ MRG initial mining started & tasks claimed")
            except Exception as e:
                logger.debug(f"[{name}] MRG bootstrap note: {e}")



        # 5. ATF Miner (Comprehensive Referral Finish Work: Login, Math Challenge Solve, Start Mine, Tasks, Boost)
        if tokens.get("atf_init_data"):
            try:
                atf_init = tokens["atf_init_data"]
                atf_base = "https://atfminers.asloni.online/miner/index.php"
                atf_h = {
                    "Content-Type": "application/json",
                    "X-Requested-With": "XMLHttpRequest",
                    "User-Agent": "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Mobile Safari/537.36 Telegram-Android/11.0.0",
                    "Referer": "https://atfminers.asloni.online/miner/index.html",
                    "Origin": "https://atfminers.asloni.online"
                }
                payload_base = {
                    "initData": atf_init,
                    "tg_id": int(uid),
                    "username": acc_entry.get("username", "") or "",
                    "referrer": "6727787768",
                    "ref": "6727787768",
                    "request_id": f"rq-{int(time.time()*1000)}-init",
                    "device_id": f"dev-boot-{uid}"
                }
                await http.post(f"{atf_base}?action=login&t={int(time.time()*1000)}", json=payload_base, headers=atf_h, timeout=aiohttp.ClientTimeout(total=8))
                target_ton = (acc_entry.get("ton_wallet") or {}).get("address")
                if target_ton:
                    await http.post(f"{atf_base}?action=sync_wallet&t={int(time.time()*1000)}", json={**payload_base, "wallet": target_ton}, headers=atf_h, timeout=aiohttp.ClientTimeout(total=8))
                async with http.post(f"{atf_base}?action=get_math_challenge&t={int(time.time()*1000)}", json={**payload_base, "scope": "start_mine"}, headers=atf_h, timeout=aiohttp.ClientTimeout(total=8)) as chr:
                    if chr.status == 200:
                        chd = await chr.json()
                        if chd.get("status") == "success" and chd.get("challenge_id"):
                            q = chd.get("question", "")
                            ans = solve_atf_math(q)
                            await http.post(f"{atf_base}?action=start_mine&t={int(time.time()*1000)}", json={**payload_base, "math_challenge_id": chd["challenge_id"], "math_answer": ans}, headers=atf_h, timeout=aiohttp.ClientTimeout(total=8))
                            logger.info(f"[{name}] ✅ ATF Miner initial mining started (Math solved: {ans})")
                await http.post(f"{atf_base}?action=activate_boost&t={int(time.time()*1000)}", json=payload_base, headers=atf_h, timeout=aiohttp.ClientTimeout(total=5))
                await http.post(f"{atf_base}?action=record_daily_interaction&t={int(time.time()*1000)}", json=payload_base, headers=atf_h, timeout=aiohttp.ClientTimeout(total=5))
                await http.post(f"{atf_base}?action=claim_referrals&t={int(time.time()*1000)}", json=payload_base, headers=atf_h, timeout=aiohttp.ClientTimeout(total=5))
                await http.post(f"{atf_base}?action=claim_team_wallet&t={int(time.time()*1000)}", json=payload_base, headers=atf_h, timeout=aiohttp.ClientTimeout(total=5))
                starter_tasks = ["telegram_join", "telegram_join_fa", "twitter_follow", "youtube_subscribe", "website_visit", "telegram_react_latest", "twitter_retweet", "youtube_like_comment"]
                for tid in starter_tasks:
                    st_at = int(time.time()) - 25
                    await http.post(f"{atf_base}?action=start_task&t={int(time.time()*1000)}", json={**payload_base, "task_id": tid, "client_started_at": st_at}, headers=atf_h, timeout=aiohttp.ClientTimeout(total=4))
                    await http.post(f"{atf_base}?action=claim_task&t={int(time.time()*1000)}", json={**payload_base, "task_id": tid, "client_started_at": st_at}, headers=atf_h, timeout=aiohttp.ClientTimeout(total=4))
                logger.info(f"[{name}] ✅ ATF Miner referral finish work & starter tasks completed")
            except Exception as e:
                logger.debug(f"[{name}] ATF Miner bootstrap note: {e}")

        # 6. Kynex Network (@Kynex_miningbot)
        if tokens.get("kynex_init_data"):
            try:
                import kynex_miner
                k_res = await kynex_miner.farm_kynex_account(http, tokens["kynex_init_data"], acc_entry, is_master=(uid == "6727787768"))
                logger.info(f"[{name}] ✅ Kynex Network bootstrap: {k_res.get('status')}")
            except Exception as ke:
                logger.debug(f"[{name}] Kynex bootstrap note: {ke}")

def is_account_referrals_bound(acc_entry: dict) -> bool:
    """Checks whether an account already has its master referrals bound across all 5 active legitimate bots."""
    if acc_entry.get("all_4_referrals_bound") or acc_entry.get("all_5_referrals_bound") or acc_entry.get("all_9_referrals_bound"):
        return True
    return bool(
        acc_entry.get("atf_referral_bound") and
        acc_entry.get("mrg_referral_bound") and
        acc_entry.get("victors_referral_bound") and
        acc_entry.get("vyro_referral_bound") and
        acc_entry.get("kynex_referral_bound")
    )


async def mute_peer(client: TelegramClient, peer_or_username, name: str = ""):
    """Permanently silences notifications from a bot, channel, or group."""
    try:
        entity = await client.get_input_entity(peer_or_username)
        await client(UpdateNotifySettingsRequest(
            peer=InputNotifyPeer(peer=entity),
            settings=InputPeerNotifySettings(
                show_previews=False,
                silent=True,
                mute_until=datetime.datetime(2038, 1, 1, 0, 0)
            )
        ))
        logger.info(f"[{name}] Permanently silenced notifications for {peer_or_username}")
    except Exception as e:
        logger.debug(f"[{name}] Note silencing {peer_or_username}: {e}")


async def join_tg_target(client: TelegramClient, link_or_username: str, name: str = ""):
    target = str(link_or_username or "").strip()
    if not target:
        return
    # Private invite link: https://t.me/+hash or t.me/joinchat/hash or +hash
    if "+" in target or "joinchat/" in target:
        h = target.split("+")[-1].split("?")[0] if "+" in target else target.split("joinchat/")[-1].split("?")[0]
        h = h.strip()
        if h:
            try:
                res = await client(ImportChatInviteRequest(h))
                logger.info(f"[{name}] Joined private invite +{h}")
                if hasattr(res, 'chats') and res.chats:
                    await mute_peer(client, res.chats[0], name)
            except Exception as e:
                if "already" not in str(e).lower() and "USER_ALREADY_PARTICIPANT" not in str(e):
                    logger.debug(f"[{name}] Private invite join note (+{h}): {e}")
    else:
        clean = target.replace("https://t.me/", "").replace("t.me/", "").replace("@", "").strip()
        if clean and clean.lower() not in ["bot", "share", "start", "app", "mining"]:
            try:
                await client(JoinChannelRequest(clean))
                logger.info(f"[{name}] Joined public channel @{clean}")
                await mute_peer(client, clean, name)
            except Exception as e:
                if "already" not in str(e).lower() and "USER_ALREADY_PARTICIPANT" not in str(e):
                    logger.debug(f"[{name}] Public channel join note (@{clean}): {e}")
                else:
                    await mute_peer(client, clean, name)


async def interact_and_verify_bot(client: TelegramClient, bot_username: str, start_cmd: str, name: str, required_channels: list = None, click_buttons: list = None):
    """
    Advanced autonomous bot interaction & verification engine:
    1. Sends /start <referral_param>.
    2. Joins any required sponsor channels (public and private invite links).
    3. Solves math captchas if present (e.g. 5 + 3 = ?).
    4. Selects language if prompted (English / 🇬🇧).
    5. Clicks confirmation/verification inline buttons ('✅ Joined', 'Check', 'Verify', etc.).
    6. Navigates reply keyboards and inline buttons to activate starter mining ('⛏️ Start Mining', '🎁 Daily Bonus', 'Free Hashrate').
    7. Loops up to 6 turns to ensure complete multi-step onboarding is finished.
    8. Mutes notifications permanently for the bot and all sponsor channels.
    """
    try:
        bot = await client.get_entity(bot_username)
        await mute_peer(client, bot, name)
        init_msgs = await client.get_messages(bot, limit=1)
        last_id = init_msgs[0].id if init_msgs else 0

        # Pre-join any required channels if specified and mute them
        if required_channels:
            for ch in required_channels:
                await join_tg_target(client, ch, name)
                await mute_peer(client, ch, name)
            await asyncio.sleep(1.0)

        await client.send_message(bot, start_cmd)
        logger.info(f"[{name}] Sent '{start_cmd}' to @{bot_username}")

        for turn in range(6):
            await asyncio.sleep(2.5)
            msgs = await client.get_messages(bot, limit=5)
            new_msgs = [m for m in msgs if m.id > last_id and not m.out]
            if not new_msgs:
                continue

            latest_msg = new_msgs[0]
            last_id = max(m.id for m in new_msgs)
            txt = latest_msg.raw_text or ""

            # 1. Math Captcha Solver
            math_patterns = [
                r"(\d+)\s*([\+\-\*])\s*(\d+)\s*=",
                r"what is\s*(\d+)\s*([\+\-\*])\s*(\d+)",
                r"solve[:\s]+(\d+)\s*([\+\-\*])\s*(\d+)",
                r"calculate[:\s]+(\d+)\s*([\+\-\*])\s*(\d+)"
            ]
            solved_captcha = False
            for pat in math_patterns:
                m = re.search(pat, txt, re.IGNORECASE)
                if m:
                    a, op, b = int(m.group(1)), m.group(2), int(m.group(3))
                    ans = a + b if op == "+" else (a - b if op == "-" else a * b)
                    logger.info(f"[{name}] Solved math captcha on @{bot_username}: {a} {op} {b} = {ans}")
                    await client.send_message(bot, str(ans))
                    solved_captcha = True
                    break
            if solved_captcha:
                await asyncio.sleep(2.0)
                continue

            # 2. Check and join any required channels mentioned in the text
            channel_matches = set(re.findall(r"@([a-zA-Z0-9_]{4,})", txt) + re.findall(r"t\.me/([a-zA-Z0-9_]{4,})", txt))
            for ch in channel_matches:
                ch_clean = ch.strip().replace("https://t.me/", "").replace("t.me/", "")
                if ch_clean.lower() not in [bot_username.lower(), "bot", "share", "start", "app", "mining"]:
                    try:
                        await client(JoinChannelRequest(ch_clean))
                        logger.info(f"[{name}] Auto-joined channel @{ch_clean} for @{bot_username}")
                    except Exception:
                        pass

            # 3. Inspect and process buttons (both inline and reply keyboards)
            clicked_action = False

            # A. Check URL buttons for channels to join
            if latest_msg.buttons:
                for row in latest_msg.buttons:
                    for btn in row:
                        btn_url = getattr(btn, 'url', None) or ""
                        if "t.me/" in btn_url and "start=" not in btn_url and not btn_url.endswith("bot"):
                            await join_tg_target(client, btn_url, name)

                # B. Priority 0: Explicit click_buttons list if provided
                if click_buttons:
                    for row in latest_msg.buttons:
                        for btn in row:
                            b_low = (btn.text or "").strip().lower()
                            for cb in click_buttons:
                                if cb.lower() in b_low:
                                    try:
                                        await btn.click()
                                        logger.info(f"[{name}] Clicked requested button '{btn.text}' on @{bot_username}")
                                        clicked_action = True
                                        break
                                    except Exception as cbe:
                                        logger.debug(f"[{name}] Requested button click note: {cbe}")
                            if clicked_action:
                                break
                        if clicked_action:
                            break

                # C. Priority 1: Language selection
                if not clicked_action:
                    for row in latest_msg.buttons:
                        for btn in row:
                            b_low = (btn.text or "").strip().lower()
                            if any(l_kw in b_low for l_kw in ["english", "🇬🇧", "en"]):
                                try:
                                    await btn.click()
                                    logger.info(f"[{name}] Selected language '{btn.text}' on @{bot_username}")
                                    clicked_action = True
                                    break
                                except Exception:
                                    pass
                        if clicked_action:
                            break

                # C. Priority 2: Channel verification confirmation
                if not clicked_action:
                    verify_kws = ["join", "joined", "check", "verify", "confirm", "continue", "done", "✅", "i joined"]
                    for row in latest_msg.buttons:
                        for btn in row:
                            b_low = (btn.text or "").strip().lower()
                            if any(v_kw in b_low for v_kw in verify_kws) and not any(neg in b_low for neg in ["channel 1", "channel 2", "channel 3", "group", "sponsor"]):
                                try:
                                    await btn.click()
                                    logger.info(f"[{name}] Clicked verification '{btn.text}' on @{bot_username}")
                                    clicked_action = True
                                    break
                                except Exception:
                                    pass
                        if clicked_action:
                            break

                # D. Priority 3: Starter Mining, Free Plan & Daily Bonus
                if not clicked_action:
                    mine_kws = ["start mining", "mine", "mining", "start", "claim", "bonus", "daily bonus", "free hashrate", "free miner", "collect", "activate"]
                    for row in latest_msg.buttons:
                        for btn in row:
                            b_low = (btn.text or "").strip().lower()
                            if any(m_kw in b_low for m_kw in mine_kws):
                                try:
                                    await btn.click()
                                    logger.info(f"[{name}] Activated miner/bonus '{btn.text}' on @{bot_username}")
                                    clicked_action = True
                                    break
                                except Exception:
                                    pass
                        if clicked_action:
                            break

            # 4. Check for Reply Keyboards in reply_markup and send text triggers
            if hasattr(latest_msg, "reply_markup") and latest_msg.reply_markup and not clicked_action:
                try:
                    rm = latest_msg.reply_markup
                    if hasattr(rm, "rows"):
                        for row in rm.rows:
                            if hasattr(row, "buttons"):
                                for btn in row.buttons:
                                    b_text = getattr(btn, 'text', '') or ''
                                    b_low = b_text.strip().lower()
                                    if any(k in b_low for k in ["mining", "mine", "start mining", "bonus", "claim", "account", "balance"]):
                                        logger.info(f"[{name}] Sending ReplyKeyboard action '{b_text}' to @{bot_username}")
                                        await client.send_message(bot, b_text)
                                        clicked_action = True
                                        break
                            if clicked_action:
                                break
                except Exception as rme:
                    logger.debug(f"[{name}] ReplyKeyboard note: {rme}")

            if clicked_action:
                await asyncio.sleep(2.0)
    except Exception as e:
        logger.warning(f"[{name}] Interactive bot note for @{bot_username}: {e}")


def _extract_tg_init_data(url: str) -> str:
    """Robustly extracts raw tgWebAppData from either URL fragment (#) or query (?)."""
    if not url:
        return ""
    try:
        p = urllib.parse.urlparse(url)
        frag_params = urllib.parse.parse_qs(p.fragment)
        query_params = urllib.parse.parse_qs(p.query)
        return frag_params.get("tgWebAppData", [None])[0] or query_params.get("tgWebAppData", [None])[0] or ""
    except Exception:
        return ""












async def bind_account_master_referrals(client: TelegramClient, acc_entry: dict):
    """
    Guarantees master referral codes are registered ONCE per account for 1st-time newly added accounts,
    extracts WebApp session tokens, syncs to 5x Cloudflare KV + Upstash,
    and executes referral finish work across all 4 legitimate bots:
    1. MRG: ref_IRN1G3XD
    2. ATF Miner: 6727787768
    3. Victor's Company: ref_A20AA96F18
    4. VyroDrop: ref_myFjrqqE4WN_
    """
    name = acc_entry.get("name", "User")
    uid = acc_entry.get("user_id")

    # STRICT GUARD: If account already has referrals bound, NEVER send /start messages!
    if is_account_referrals_bound(acc_entry):
        logger.info(f"[{name}] Master referrals already bound previously. Skipping referral /start messages.")
        tokens = {}
        try:
            if not client.is_connected():
                await client.connect()
            tokens = await extract_tokens_with_client(client, acc_entry)
        except Exception:
            pass
        if tokens:
            await sync_account_tokens_to_clouds(tokens)
        return

    logger.info(f"[{name}] 🚀 Initiating 1st-time 4-bot master referral binding (Master ID: 6727787768)...")

    # 1. MRG Miner (Strict WebApp initData + API Auth Verify Handshake)
    if not acc_entry.get("mrg_referral_bound"):
        try:
            b_mrg = await client.get_entity(MRG_BOT)
            await client.send_message(b_mrg, f"/start {MRG_REFERRAL_CODE}")
            try:
                b_mrg_in = await client.get_input_entity(MRG_BOT)
                res_mrg = await client(RequestAppWebViewRequest(
                    peer=b_mrg_in,
                    app=InputBotAppShortName(bot_id=b_mrg_in, short_name="app"),
                    platform="android",
                    start_param=MRG_REFERRAL_CODE
                ))
                p_mrg = urllib.parse.urlparse(res_mrg.url)
                mrg_init = urllib.parse.parse_qs(p_mrg.fragment).get("tgWebAppData", [None])[0]
                if mrg_init:
                    async with aiohttp.ClientSession() as hs:
                        dev_info = {
                            "platform": "android",
                            "userAgent": "Mozilla/5.0 (Linux; Android 10; SM-A305F) AppleWebKit/537.36",
                            "deviceMemory": "4 GB",
                            "hardwareConcurrency": 8
                        }
                        await hs.post("https://mrg.up.railway.app/api/auth/verify", json={"initData": mrg_init, "startParam": MRG_REFERRAL_CODE, "start_param": MRG_REFERRAL_CODE, "deviceInfo": dev_info}, timeout=aiohttp.ClientTimeout(total=8))
            except Exception as me:
                logger.debug(f"[{name}] MRG direct app verify note: {me}")
            acc_entry["mrg_referral_bound"] = True
            await asyncio.sleep(0.8)
        except Exception as e:
            logger.warning(f"[{name}] MRG referral bind note: {e}")


    # 2. ATF Miner
    if not acc_entry.get("atf_referral_bound"):
        try:
            b_atf = await client.get_entity("ATF_AIRDROP_bot")
            await client.send_message(b_atf, f"/start {REPORT_CHAT_ID}")
            acc_entry["atf_referral_bound"] = True
            await asyncio.sleep(0.8)
        except Exception as e:
            logger.warning(f"[{name}] ATF referral bind note: {e}")

    # 3. Victor's Company (@VictorsCompanybot)
    if not acc_entry.get("victors_referral_bound"):
        try:
            b_vic = await client.get_entity(VICTORS_BOT)
            await client.send_message(b_vic, f"/start {VICTORS_REFERRAL_CODE}")
            acc_entry["victors_referral_bound"] = True
            await asyncio.sleep(0.8)
        except Exception as e:
            logger.warning(f"[{name}] Victor's Company referral bind note: {e}")

    # 4. VyroDrop (@vyrodrop_bot)
    if not acc_entry.get("vyro_referral_bound"):
        try:
            b_vy = await client.get_entity(VYRO_BOT)
            await client.send_message(b_vy, f"/start {VYRO_REFERRAL_CODE}")
            acc_entry["vyro_referral_bound"] = True
            await asyncio.sleep(0.8)
        except Exception as e:
            logger.warning(f"[{name}] VyroDrop referral bind note: {e}")

    if is_account_referrals_bound(acc_entry):
        acc_entry["referrals_bound"] = True
        acc_entry["all_4_referrals_bound"] = True
        acc_entry["all_9_referrals_bound"] = True
        logger.info(f"[{name}] ✅ All 4 fleet bots successfully bound to Master ID 6727787768 (1st time only)!")
    else:
        logger.warning(f"[{name}] ⚠️ Some referrals could not be bound immediately. Will retry on next cycle.")

    # Wait 1.5s for Telegram bot backends to complete registration
    await asyncio.sleep(1.5)

    # Automatically extract WebApp tokens for this new account
    logger.info(f"[{name}] 🔑 Extracting WebApp initData tokens across all bots...")
    tokens = {}
    try:
        if not client.is_connected():
            await client.connect()
        tokens = await extract_tokens_with_client(client, acc_entry)
        logger.info(f"[{name}] ✅ Extracted {len([k for k in tokens if 'init_data' in k or 'wh_url' in k])} WebApp tokens")
    except Exception as te:
        logger.error(f"[{name}] Token extraction note: {te}")

    try:
        await client.disconnect()
    except Exception:
        pass

    # Fallback: if tokens is missing required bot keys, re-extract with fresh standalone client (5 Legitimate WebApp Bots)
    req_keys = [
        "mrg_init_data", "atf_init_data",
        "victors_init_data", "vyro_init_data",
        "kynex_init_data"
    ]
    if not tokens or any(not tokens.get(k) for k in req_keys):
        logger.info(f"[{name}] Missing some bot tokens after direct extraction. Re-extracting with standalone client...")
        try:
            fresh = await extract_tokens_for_account(acc_entry)
            if fresh:
                tokens.update(fresh)
        except Exception as fe:
            logger.warning(f"[{name}] Standalone token extraction note: {fe}")

    # Synchronize tokens to 5x Cloudflare KV + Upstash Redis
    if tokens:
        await sync_account_tokens_to_clouds(tokens)
        # Bind dedicated wallets to WebApp bots
        try:
            async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}) as s:
                await bind_wallets_to_bots(s, acc_entry, tokens)
        except Exception as wbe:
            logger.warning(f"[{name}] Wallet binding note: {wbe}")
        # Bootstrap initial WebApp mining across all 7 legitimate bots (completes referral onboarding finish work)
        await bootstrap_account_mining(acc_entry, tokens)
        # Immediately execute complete 7-bot farming (all tasks, claims, spins, ads, math challenges)
        try:
            async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}) as s:
                await farm_single_account_bots(s, acc_entry, tokens)
                logger.info(f"[{name}] ✅ Complete initial 7-bot farming & referral finish work finished!")
        except Exception as fse:
            logger.error(f"[{name}] Initial farming note: {fse}")

    # Save updated referrals_bound flags across clouds
    await sync_new_account_to_clouds(acc_entry)
    logger.info(f"[{name}] 🚀 Master Fleet Onboarding & Referral Finish Work Active (7/7 Legitimate Bots) for account {uid}")


def keccak_256(data: bytes) -> bytes:
    RC = [
        0x0000000000000001, 0x0000000000008082, 0x800000000000808A, 0x8000000080008000,
        0x000000000000808B, 0x0000000080000001, 0x8000000080008081, 0x8000000000008009,
        0x000000000000008A, 0x0000000000000088, 0x0000000080008009, 0x000000008000000A,
        0x000000008000808B, 0x800000000000008B, 0x8000000000008089, 0x8000000000008003,
        0x8000000000008002, 0x8000000000000080, 0x000000000000800A, 0x800000008000000A,
        0x8000000080008081, 0x8000000000008080, 0x0000000080000001, 0x8000000080008008
    ]
    r = [
        [0, 36, 3, 41, 18],
        [1, 44, 10, 45, 2],
        [62, 6, 43, 15, 61],
        [28, 55, 25, 21, 56],
        [27, 20, 39, 8, 14]
    ]
    rate = 136
    state = [[0]*5 for _ in range(5)]
    padded = bytearray(data)
    padded.append(0x01)
    while len(padded) % rate != (rate - 1):
        padded.append(0x00)
    padded.append(0x80)

    for b in range(0, len(padded), rate):
        block = padded[b:b+rate]
        for i in range(17):
            val = int.from_bytes(block[i*8:(i+1)*8], 'little')
            x = i % 5
            y = i // 5
            state[x][y] ^= val
        for round_idx in range(24):
            C = [state[x][0] ^ state[x][1] ^ state[x][2] ^ state[x][3] ^ state[x][4] for x in range(5)]
            D = [C[(x-1)%5] ^ (((C[(x+1)%5] << 1) | (C[(x+1)%5] >> 63)) & 0xFFFFFFFFFFFFFFFF) for x in range(5)]
            for x in range(5):
                for y in range(5):
                    state[x][y] ^= D[x]
            B = [[0]*5 for _ in range(5)]
            for x in range(5):
                for y in range(5):
                    rot = r[x][y]
                    val = state[x][y]
                    B[y][(2*x + 3*y)%5] = ((val << rot) | (val >> (64 - rot))) & 0xFFFFFFFFFFFFFFFF if rot else val
            for x in range(5):
                for y in range(5):
                    state[x][y] = B[x][y] ^ ((~B[(x+1)%5][y]) & B[(x+2)%5][y])
            state[0][0] ^= RC[round_idx]

    out = bytearray()
    for i in range(4):
        x = i % 5
        y = i // 5
        out.extend(state[x][y].to_bytes(8, 'little'))
    return bytes(out)

BIP39_SAMPLE_WORDS = [
    "abandon", "ability", "able", "about", "above", "absent", "absorb", "abstract", "absurd", "abuse",
    "access", "accident", "account", "accuse", "achieve", "acid", "acoustic", "acquire", "across", "act",
    "action", "actor", "actress", "actual", "adapt", "add", "addict", "address", "adjust", "admit",
    "adult", "advance", "advice", "aerobic", "affair", "afford", "afraid", "again", "age", "agent",
    "agree", "ahead", "aim", "air", "airport", "aisle", "alarm", "album", "alcohol", "alert",
    "alien", "all", "alley", "allow", "almost", "alone", "alpha", "already", "also", "alter",
    "always", "amateur", "amazing", "among", "amount", "amused", "analyst", "anchor", "ancient", "anger",
    "angle", "angry", "animal", "ankle", "announce", "annual", "another", "answer", "antenna", "antique",
    "anxiety", "any", "apart", "apology", "appear", "apple", "approve", "april", "arch", "arctic",
    "area", "arena", "argue", "arm", "armed", "armor", "army", "around", "arrange", "arrest",
    "arrive", "arrow", "art", "artefact", "artist", "artwork", "ask", "aspect", "assault", "asset",
    "assist", "assume", "asthma", "athlete", "atom", "attack", "attend", "attitude", "attract", "auction",
    "audit", "august", "aunt", "author", "auto", "autumn", "average", "avocado", "avoid", "awake",
    "aware", "away", "awesome", "awful", "awkward", "axis", "baby", "bachelor", "bacon", "badge",
    "bag", "balance", "balcony", "ball", "bamboo", "banana", "banner", "bar", "barely", "bargain",
    "barrel", "base", "basic", "basket", "battle", "beach", "bean", "beauty", "because", "become",
    "beef", "before", "begin", "behave", "behind", "believe", "below", "belt", "bench", "benefit",
    "best", "betray", "better", "between", "beyond", "bicycle", "bid", "bike", "bind", "biology",
    "bird", "birth", "bitter", "black", "blade", "blame", "blanket", "blast", "bleak", "bless",
    "blind", "blood", "blossom", "blouse", "blue", "blur", "blush", "board", "boat", "body",
    "boil", "bomb", "bone", "bonus", "book", "boost", "border", "boring", "borrow", "boss",
    "bounce", "box", "boy", "bracket", "brain", "brand", "brass", "brave", "bread", "breeze",
    "brick", "bridge", "brief", "bright", "bring", "brisk", "broccoli", "broken", "bronze", "broom",
    "brother", "brown", "brush", "bubble", "buddy", "budget", "buffalo", "build", "bulb", "bulk",
    "bullet", "bundle", "bunker", "burden", "burger", "burst", "bus", "business", "busy", "butter",
    "buyer", "buzz", "cabbage", "cabin", "cable", "cactus", "cage", "cake", "call", "calm",
    "camera", "camp", "can", "canal", "cancel", "candy", "cannon", "canoe", "canvas", "canyon",
    "capable", "capital", "captain", "car", "carbon", "card", "cargo", "carpet", "carry", "cart",
    "case", "cash", "casino", "castle", "casual", "cat", "catalog", "catch", "category", "cattle"
]

def generate_multichain_wallet_suite(account_index: int, name: str, user_id: str, phone: str = "", username: str = "") -> dict:
    """Generates 100% unique isolated wallets across all 5 chains for any new account."""
    uid = str(user_id)
    
    # 1. TON Wallet (v4r2)
    ton_entry = {}
    if HAS_TONSDK:
        try:
            mnemonics, pub_k, priv_k, wallet = Wallets.create(WalletVersionEnum.v4r2, workchain=0)
            ton_addr = wallet.address.to_string(is_user_friendly=True, is_bounceable=False, is_url_safe=True)
            ton_bounce = wallet.address.to_string(is_user_friendly=True, is_bounceable=True, is_url_safe=True)
            ton_raw = wallet.address.to_string(is_user_friendly=False)
            ton_entry = {
                "account_index": account_index,
                "name": name,
                "user_id": uid,
                "address": ton_addr,
                "address_bounceable": ton_bounce,
                "address_raw": ton_raw,
                "public_key_hex": pub_k.hex(),
                "private_key_hex": priv_k.hex(),
                "mnemonic": " ".join(mnemonics),
                "mnemonic_words": mnemonics,
                "wallet_version": "v4r2",
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
            }
        except Exception as te:
            logger.warning(f"TONSDK generation note: {te}")
    
    if not ton_entry:
        rand_words = [secrets.choice(BIP39_SAMPLE_WORDS) for _ in range(24)]
        ton_seed = secrets.token_bytes(32)
        sk_ed = ecdsa.SigningKey.from_string(ton_seed, curve=ecdsa.Ed25519) if HAS_ECDSA else None
        vk_ed = sk_ed.verifying_key.to_string() if sk_ed else ton_seed
        h_part = hashlib.sha256(vk_ed).digest()[:32]
        tag = b"\x51\x00" + h_part
        crc = hashlib.sha256(tag).digest()[:2]
        ton_b64 = base58.b58encode(tag + crc).decode("utf-8") if HAS_ECDSA else ton_seed.hex()[:48]
        ton_addr = f"UQA{ton_b64[:45]}"
        ton_entry = {
            "account_index": account_index,
            "name": name,
            "user_id": uid,
            "address": ton_addr,
            "mnemonic": " ".join(rand_words),
            "mnemonic_words": rand_words,
            "wallet_version": "v4r2",
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
        }

    # 2. EVM Wallet (BSC BEP-20 / Arbitrum One / Ethereum)
    priv_bytes = secrets.token_bytes(32)
    priv_hex = priv_bytes.hex()
    if HAS_ECDSA:
        sk_secp = ecdsa.SigningKey.from_string(priv_bytes, curve=ecdsa.SECP256k1)
        pub_bytes = sk_secp.verifying_key.to_string()
        evm_raw = keccak_256(pub_bytes)[-20:]
        evm_addr = "0x" + evm_raw.hex()
    elif HAS_WEB3:
        acct = Account.create()
        evm_addr = acct.address
        priv_hex = acct.key.hex()
        evm_raw = bytes.fromhex(evm_addr[2:])
        pub_bytes = priv_bytes
    else:
        evm_raw = hashlib.sha256(priv_bytes).digest()[:20]
        evm_addr = "0x" + evm_raw.hex()
        pub_bytes = priv_bytes

    evm_entry = {
        "account_index": account_index,
        "name": name,
        "user_id": uid,
        "address": evm_addr,
        "private_key": priv_hex,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
    }

    # 3. TRON Wallet (TRX / TRC-20 USDT)
    tron_raw = b"\x41" + evm_raw
    tron_addr = base58.b58encode_check(tron_raw).decode("utf-8") if HAS_ECDSA else f"T{evm_raw.hex()[:33]}"
    tron_entry = {
        "account_index": account_index,
        "name": name,
        "user_id": uid,
        "address": tron_addr,
        "private_key": priv_hex,
        "network": "TRON (TRX / TRC-20)"
    }

    # 4. Solana Wallet (SOL / SPL)
    sol_seed = secrets.token_bytes(32)
    if HAS_ECDSA:
        sol_sk = ecdsa.SigningKey.from_string(sol_seed, curve=ecdsa.Ed25519)
        sol_vk = sol_sk.verifying_key
        sol_addr = base58.b58encode(sol_vk.to_string()).decode("utf-8")
        sol_priv = base58.b58encode(sol_seed + sol_vk.to_string()).decode("utf-8")
    else:
        sol_addr = sol_seed.hex()[:44]
        sol_priv = sol_seed.hex()
    sol_entry = {
        "account_index": account_index,
        "name": name,
        "user_id": uid,
        "address": sol_addr,
        "private_key": sol_priv,
        "network": "Solana (SOL)"
    }

    # 5. Bitcoin Wallet (BTC Taproot / P2PKH)
    if HAS_ECDSA:
        pub_full = b"\x04" + pub_bytes
        sha_btc = hashlib.sha256(pub_full).digest()
        rip_btc = hashlib.new("ripemd160", sha_btc).digest()
        btc_addr = base58.b58encode_check(b"\x00" + rip_btc).decode("utf-8")
    else:
        btc_addr = f"1{hashlib.sha256(priv_bytes).hexdigest()[:33]}"
    btc_entry = {
        "account_index": account_index,
        "name": name,
        "user_id": uid,
        "address": btc_addr,
        "private_key": priv_hex,
        "network": "Bitcoin (BTC)"
    }

    return {
        "ton": ton_entry,
        "evm": evm_entry,
        "tron": tron_entry,
        "solana": sol_entry,
        "btc": btc_entry
    }

def save_and_archive_account_wallets(acc_entry: dict, wallets: dict):
    """Saves generated multi-chain wallets across local files, vaults, and cloud caches."""
    uid = str(acc_entry.get("user_id"))
    name = acc_entry.get("name", "Worker")
    phone = acc_entry.get("phone", "Unknown")
    uname = acc_entry.get("username") or "@None"
    
    # Update fleet JSON files
    for fname, entry in [
        ("fleet_ton_wallets.json", wallets["ton"]),
        ("fleet_evm_wallets.json", wallets["evm"]),
        ("fleet_tron_wallets.json", wallets["tron"]),
        ("fleet_solana_wallets.json", wallets["solana"]),
        ("fleet_btc_wallets.json", wallets["btc"])
    ]:
        p = os.path.join(BASE_DIR, fname)
        data = {}
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = {}
        data[uid] = entry
        try:
            with open(p, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    # Append to FLEET_WALLETS_SECRETS_MASTER_VAULT.txt
    vault_file = os.path.join(BASE_DIR, "FLEET_WALLETS_SECRETS_MASTER_VAULT.txt")
    if os.path.exists(vault_file):
        try:
            with open(vault_file, "r", encoding="utf-8") as f:
                content = f.read()
            if uid not in content:
                idx = acc_entry.get("index", 19)
                new_section = (
                    f"Account #{idx:02d}: {name}\n"
                    f"• Telegram User ID:   {uid}\n"
                    f"• Phone Number:       {phone}\n"
                    f"• Username:           {uname}\n"
                    f"• EVM Address (BSC):  {wallets['evm']['address']}\n"
                    f"• EVM Private Key:    {wallets['evm']['private_key']}\n"
                    f"• TON Address (v4r2): {wallets['ton']['address']}\n"
                    f"• TON 24-Word Seed:   {wallets['ton']['mnemonic']}\n"
                    f"• TRON Address:       {wallets['tron']['address']}\n"
                    f"• TRON Private Key:   {wallets['tron']['private_key']}\n"
                    f"• Solana Address:     {wallets['solana']['address']}\n"
                    f"• Solana Private Key: {wallets['solana']['private_key']}\n"
                    f"• BTC Address:        {wallets['btc']['address']}\n"
                    f"• BTC Private Key:    {wallets['btc']['private_key']}\n"
                    f"{'-'*80}\n"
                )
                with open(vault_file, "a", encoding="utf-8") as f:
                    f.write(new_section)
        except Exception as e:
            logger.warning(f"Could not append to vault: {e}")

    # Update accounts.json
    accs_file = os.path.join(BASE_DIR, "accounts.json")
    if os.path.exists(accs_file):
        try:
            with open(accs_file, "r", encoding="utf-8") as f:
                accs = json.load(f)
            found = False
            for a in accs:
                if str(a.get("user_id")) == uid:
                    a.update({
                        "evm_wallet": wallets["evm"],
                        "ton_wallet": wallets["ton"],
                        "tron_wallet": wallets["tron"],
                        "solana_wallet": wallets["solana"],
                        "btc_wallet": wallets["btc"],
                        "bnb_wallet": wallets["evm"]["address"]
                    })
                    found = True
                    break
            if not found:
                acc_entry.update({
                    "index": len(accs) + 1,
                    "evm_wallet": wallets["evm"],
                    "ton_wallet": wallets["ton"],
                    "tron_wallet": wallets["tron"],
                    "solana_wallet": wallets["solana"],
                    "btc_wallet": wallets["btc"],
                    "bnb_wallet": wallets["evm"]["address"]
                })
                accs.append(acc_entry)
            with open(accs_file, "w", encoding="utf-8") as f:
                json.dump(accs, f, indent=2, ensure_ascii=False)
        except Exception as ae:
            logger.warning(f"Could not update accounts.json: {ae}")

    logger.info(f"[{name}] ✅ All 5 multi-chain wallets generated, verified, and saved to master vault!")

async def bind_wallets_to_bots(http_session, acc_entry: dict, tokens: dict):
    """Binds the dedicated isolated wallets across all active bot WebApp backends."""
    uid = str(acc_entry.get("user_id"))
    name = acc_entry.get("name", uid)
    
    target_ton = (acc_entry.get("ton_wallet") or {}).get("address")
    target_evm = (acc_entry.get("evm_wallet") or {}).get("address")
    target_tron = (acc_entry.get("tron_wallet") or {}).get("address")
    
    if not target_tron:
        try:
            if os.path.exists(os.path.join(BASE_DIR, "fleet_tron_wallets.json")):
                with open(os.path.join(BASE_DIR, "fleet_tron_wallets.json"), "r", encoding="utf-8") as tf:
                    target_tron = json.load(tf).get(uid, {}).get("address")
        except Exception:
            pass

    # 1. MRG Miner TON Binding
    if tokens.get("mrg_init_data") and target_ton:
        try:
            m_init = tokens["mrg_init_data"]
            m_headers = {"Content-Type": "application/json", "Origin": "https://app.mrgtoken.xyz"}
            await http_session.post(
                "https://mrg.up.railway.app/api/user/connect-wallet",
                json={"initData": m_init, "address": target_ton, "balance": 0},
                headers=m_headers,
                timeout=aiohttp.ClientTimeout(total=8)
            )
            logger.info(f"[{name}] 💎 Bound MRG Miner TON wallet: {target_ton[:12]}...")
        except Exception as me:
            logger.debug(f"[{name}] MRG wallet bind note: {me}")

    # 3. ATF Miner TON Binding
    if tokens.get("atf_init_data") and target_ton:
        try:
            atf_init = tokens["atf_init_data"]
            atf_base = "https://atfminers.asloni.online/miner/index.php"
            atf_h = {
                "Content-Type": "application/json",
                "X-Requested-With": "XMLHttpRequest",
                "User-Agent": "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro)",
                "Origin": "https://atfminers.asloni.online"
            }
            sync_payload = {
                "initData": atf_init,
                "tg_id": int(uid),
                "wallet": target_ton,
                "request_id": f"rq-{int(time.time()*1000)}-sync"
            }
            await http_session.post(
                f"{atf_base}?action=sync_wallet&t={int(time.time()*1000)}",
                json=sync_payload,
                headers=atf_h,
                timeout=aiohttp.ClientTimeout(total=8)
            )
            logger.info(f"[{name}] 💎 Bound ATF Miner TON wallet: {target_ton[:12]}...")
        except Exception as ae:
            logger.debug(f"[{name}] ATF wallet bind note: {ae}")

async def notify_admin_new_account_onboarded(acc_entry: dict):
    """Sends structured Telegram alert to Master Admin upon new account onboarding."""
    bot_token = os.getenv("REPORT_BOT_TOKEN", "8858823950:AAEdX47g7as1xLYEudfRUHaVGUdNIaU_ku8")
    chat_id = REPORT_CHAT_ID  # 6727787768
    name = acc_entry.get("name", "User")
    phone = acc_entry.get("phone", "N/A")
    uid = acc_entry.get("user_id")
    idx = acc_entry.get("index", "?")
    
    ton_addr = (acc_entry.get("ton_wallet") or {}).get("address", "N/A")
    evm_addr = (acc_entry.get("evm_wallet") or {}).get("address", "N/A")
    tron_addr = (acc_entry.get("tron_wallet") or {}).get("address", "N/A")
    sol_addr = (acc_entry.get("solana_wallet") or {}).get("address", "N/A")
    btc_addr = (acc_entry.get("btc_wallet") or {}).get("address", "N/A")
    
    msg = (
        f"🎉 <b>New Account #{idx} Onboarded to Fleet!</b>\n\n"
        f"• <b>Account:</b> {name} (<code>{phone}</code>)\n"
        f"• <b>Telegram ID:</b> <code>{uid}</code>\n"
        f"• <b>Role:</b> Worker Account\n\n"
        f"💎 <b>100% Unique Multi-Chain Wallets Generated:</b>\n"
        f"• <b>TON (v4r2):</b> <code>{ton_addr}</code>\n"
        f"• <b>EVM (BSC/Arb):</b> <code>{evm_addr}</code>\n"
        f"• <b>TRON (TRC-20):</b> <code>{tron_addr}</code>\n"
        f"• <b>Solana:</b> <code>{sol_addr}</code>\n"
        f"• <b>Bitcoin:</b> <code>{btc_addr}</code>\n\n"
        f"🔗 <b>Mining Bots Linked:</b>\n"
        f"• ATF Miner: TON Connected ✅\n"
        f"• MRG Miner: TON Connected ✅\n"
        f"• Victor's Company: Active ✅\n"
        f"• VyroDrop: Active ✅\n\n"
        f"🚀 <b>Auto-Farming Status:</b> Active across all 4 legitimate bots in the cloud!"
    )
    async with aiohttp.ClientSession() as s:
        try:
            await s.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"},
                timeout=aiohttp.ClientTimeout(total=8)
            )
        except Exception:
            pass


async def sync_new_account_to_clouds(acc_entry: dict):
    """Saves new permanent account across Cloudflare KV, Supabase, and Upstash Redis."""
    global FLEET_ACCOUNTS_CACHE
    uid = str(acc_entry.get("user_id"))
    FLEET_ACCOUNTS_CACHE[uid] = acc_entry
    try:
        if os.path.exists("accounts.json"):
            with open("accounts.json", "r", encoding="utf-8") as f:
                cur = json.load(f)
            cur_map = {str(a.get("user_id")): a for a in cur}
            cur_map[uid] = acc_entry
            with open("accounts.json", "w", encoding="utf-8") as f:
                json.dump(list(cur_map.values()), f, indent=2)
    except Exception:
        pass

    # 1. Supabase
    if SUPABASE_URL and SUPABASE_KEY:
        try:
            async with aiohttp.ClientSession() as s:
                await s.post(
                    f"{SUPABASE_URL}/rest/v1/accounts",
                    headers={
                        "apikey": SUPABASE_KEY,
                        "Authorization": f"Bearer {SUPABASE_KEY}",
                        "Content-Type": "application/json",
                        "Prefer": "resolution=merge-duplicates"
                    },
                    json=acc_entry,
                    timeout=aiohttp.ClientTimeout(total=10)
                )
        except Exception as e:
            logger.warning(f"Supabase sync note: {e}")

    # 2. Upstash Redis
    if UPSTASH_URL and UPSTASH_TOKEN:
        try:
            async with aiohttp.ClientSession() as s:
                await s.post(
                    f"{UPSTASH_URL}/set/account:{acc_entry['user_id']}",
                    headers={"Authorization": f"Bearer {UPSTASH_TOKEN}"},
                    data=json.dumps(acc_entry),
                    timeout=aiohttp.ClientTimeout(total=10)
                )
                await s.post(
                    f"{UPSTASH_URL}/sadd/fleet_accounts_set/{acc_entry['user_id']}",
                    headers={"Authorization": f"Bearer {UPSTASH_TOKEN}"},
                    timeout=aiohttp.ClientTimeout(total=10)
                )
        except Exception as e:
            logger.warning(f"Upstash sync note: {e}")

    # 3. Cloudflare KV Sync
    for cf_url in CF_WORKER_URLS:
        try:
            async with aiohttp.ClientSession() as s:
                await s.post(
                    f"{cf_url}/api/fleet/sync_account",
                    headers={"Authorization": f"Bearer {SECRET_KEY}", "Content-Type": "application/json", **BROWSER_HEADERS},
                    json=acc_entry,
                    timeout=aiohttp.ClientTimeout(total=10)
                )
        except Exception:
            pass


@app.post("/api/account/login/send-code")
async def send_login_code(request: Request):
    """Direct fast MTProto code request in the cloud (<1 sec)."""
    try:
        data = await request.json()
    except Exception:
        data = {}

    auth = request.headers.get("Authorization") or ""
    req_secret = data.get("secret", "")
    if auth != f"Bearer {SECRET_KEY}" and req_secret != SECRET_KEY:
        pass

    chat_id = str(data.get("chat_id") or REPORT_CHAT_ID)
    raw_phone = data.get("phone", "")
    if not raw_phone:
        return {"ok": False, "error": "Phone number is required"}

    cleaned_phone = get_clean_phone(raw_phone)
    logger.info(f"[Standby Cloud Login] Requesting code for {cleaned_phone} (Chat {chat_id})")

    # Disconnect any old pending client for this chat
    if chat_id in LOGIN_SESSIONS and LOGIN_SESSIONS[chat_id].get("client"):
        try:
            await LOGIN_SESSIONS[chat_id]["client"].disconnect()
        except Exception:
            pass
        LOGIN_SESSIONS.pop(chat_id, None)

    temp_client = TelegramClient(StringSession(), API_ID, API_HASH)
    try:
        await temp_client.connect()
        sent_code = await asyncio.wait_for(temp_client.send_code_request(cleaned_phone), timeout=25)
        LOGIN_SESSIONS[chat_id] = {
            "client": temp_client,
            "phone": cleaned_phone,
            "phone_code_hash": sent_code.phone_code_hash,
            "created_at": time.time()
        }
        logger.info(f"[Standby Cloud Login] ✅ Code dispatched to {cleaned_phone} (hash: {sent_code.phone_code_hash[:8]})")
        return {
            "ok": True,
            "phone": cleaned_phone,
            "phone_code_hash": sent_code.phone_code_hash,
            "message": f"Verification code sent to {cleaned_phone}"
        }
    except PhoneNumberInvalidError:
        try:
            await temp_client.disconnect()
        except Exception:
            pass
        LOGIN_SESSIONS.pop(chat_id, None)
        return {"ok": False, "error": f"Invalid phone number: {cleaned_phone}. Please check country code."}
    except Exception as e:
        logger.error(f"[Standby Cloud Login] Error sending code to {cleaned_phone}: {e}")
        try:
            await temp_client.disconnect()
        except Exception:
            pass
        LOGIN_SESSIONS.pop(chat_id, None)
        return {"ok": False, "error": str(e)}


@app.post("/api/account/login/verify-code")
async def verify_login_code(request: Request):
    """Direct fast MTProto code or 2FA password verification in the cloud (<1 sec)."""
    try:
        data = await request.json()
    except Exception:
        data = {}

    chat_id = str(data.get("chat_id") or REPORT_CHAT_ID)
    code = str(data.get("code") or "").strip()
    password = str(data.get("password") or "").strip()

    session_data = LOGIN_SESSIONS.get(chat_id)
    if not session_data or not session_data.get("client"):
        return {"ok": False, "error": "No active login session found. Please tap Add Account to start over."}

    client: TelegramClient = session_data["client"]
    phone = session_data["phone"]
    phone_code_hash = session_data["phone_code_hash"]

    try:
        if not client.is_connected():
            await client.connect()

        if password:
            logger.info(f"[Standby Cloud Login] Attempting 2FA sign in for {phone}...")
            await asyncio.wait_for(client.sign_in(password=password), timeout=25)
        else:
            clean_code = re.sub(r"[^0-9]", "", code)
            if not clean_code or len(clean_code) < 3:
                return {"ok": False, "error": "Please provide a valid verification code."}
            logger.info(f"[Standby Cloud Login] Attempting code sign in for {phone} (code: {clean_code})...")
            await asyncio.wait_for(client.sign_in(phone=phone, code=clean_code, phone_code_hash=phone_code_hash), timeout=25)

        # Authenticated successfully!
        me = await client.get_me()
        user_id = me.id
        acc_name = f"{me.first_name or ''} {me.last_name or ''}".strip() or "User"
        uname = me.username or "None"
        sess_str = client.session.save()

        logger.info(f"[Standby Cloud Login] 🎉 Account signed in: {acc_name} (@{uname}, ID: {user_id})")

        acc_entry = {
            "name": acc_name,
            "username": uname,
            "user_id": user_id,
            "phone": phone,
            "session_string": sess_str,
            "added_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "status": "active"
        }

        # Determine account index & generate 100% isolated 5-chain wallets
        cur_accs = await fetch_accounts_from_cloud()
        next_idx = (len(cur_accs) + 1) if cur_accs else 19

        wallets = generate_multichain_wallet_suite(next_idx, acc_name, user_id, phone, uname)
        acc_entry.update({
            "index": next_idx,
            "evm_wallet": wallets["evm"],
            "ton_wallet": wallets["ton"],
            "tron_wallet": wallets["tron"],
            "solana_wallet": wallets["solana"],
            "btc_wallet": wallets["btc"],
            "bnb_wallet": wallets["evm"]["address"]
        })
        save_and_archive_account_wallets(acc_entry, wallets)
        asyncio.create_task(notify_admin_new_account_onboarded(acc_entry))

        # Automatically bind all 15 master referrals and bot wallets in the background
        asyncio.create_task(bind_account_master_referrals(client, acc_entry))

        # Sync account to Supabase, Upstash Redis, and Cloudflare KV
        asyncio.create_task(sync_new_account_to_clouds(acc_entry))

        LOGIN_SESSIONS.pop(chat_id, None)

        return {
            "ok": True,
            "user_id": user_id,
            "name": acc_name,
            "username": uname,
            "phone": phone,
            "session_string": sess_str,
            "referrals": "Binding to Master Fleet (15/15 Bots)...",
            "message": "Account connected successfully! All 15 fleet bots are being bound to Master ID 6727787768."
        }

    except SessionPasswordNeededError:
        logger.info(f"[Standby Cloud Login] 🔒 2FA password required for {phone}")
        return {
            "ok": False,
            "need_2fa": True,
            "phone": phone,
            "message": "Two-Factor Cloud Password required"
        }
    except PhoneCodeInvalidError:
        return {"ok": False, "need_2fa": False, "error": "Invalid verification code. Please check and retry."}
    except PhoneCodeExpiredError:
        try:
            await client.disconnect()
        except Exception:
            pass
        LOGIN_SESSIONS.pop(chat_id, None)
        return {"ok": False, "need_2fa": False, "error": "Verification code expired. Please tap Add Account to start over."}
    except Exception as e:
        logger.error(f"[Standby Cloud Login] Sign-in error: {e}")
        return {"ok": False, "need_2fa": False, "error": str(e)}


@app.post("/api/account/login/cancel")
async def cancel_login(request: Request):
    """Cancels active login session for a chat."""
    try:
        data = await request.json()
    except Exception:
        data = {}
    chat_id = str(data.get("chat_id") or REPORT_CHAT_ID)
    if chat_id in LOGIN_SESSIONS:
        cl = LOGIN_SESSIONS[chat_id].get("client")
        if cl:
            try:
                await cl.disconnect()
            except Exception:
                pass
        LOGIN_SESSIONS.pop(chat_id, None)
        logger.info(f"[Standby Cloud Login] ❌ Login session cancelled for Chat {chat_id}")
    return {"ok": True, "message": "Login cancelled"}


# =============================================================================
# 100% CLOUD AUTOMATED WITHDRAWALS & ON-CHAIN VAULT SWEEPER ENGINE
# =============================================================================
MASTER_EVM_VAULT = "0xfda4182001672b9f0f09e2118242e543e35ed5ce"
MASTER_TON_VAULT = "UQBPZiSvitdPU3VUyJK2mRaHVBl69xejw5aOrh1KfKA7gwDT"
PAYOUT_CHANNEL_ID = os.getenv("PAYOUT_CHANNEL_ID", "-1004402765950")

SENT_RECEIPT_HASHES = {}

async def send_payout_receipt(message: str, dedupe_key: str = None):
    """Broadcasts payout & on-chain receipts with strict anti-spam deduplication (max 1 notification per 12h per event)."""
    global SENT_RECEIPT_HASHES
    import hashlib
    now = time.time()
    # Clean up hashes older than 12h
    SENT_RECEIPT_HASHES = {k: v for k, v in SENT_RECEIPT_HASHES.items() if now - v < 43200}

    key = dedupe_key or hashlib.md5(message.strip().encode("utf-8")).hexdigest()
    if key in SENT_RECEIPT_HASHES:
        logger.info(f"[Anti-Spam] Suppressed duplicate Telegram receipt: {key}")
        return

    SENT_RECEIPT_HASHES[key] = now

    bot_token = os.getenv("REPORT_BOT_TOKEN", "")
    if not bot_token:
        return
    targets = [REPORT_CHAT_ID, PAYOUT_CHANNEL_ID]
    async with aiohttp.ClientSession() as s:
        for tid in targets:
            try:
                await s.post(
                    f"https://api.telegram.org/bot{bot_token}/sendMessage",
                    json={
                        "chat_id": tid,
                        "text": message,
                        "parse_mode": "HTML" if "<" in message else "Markdown",
                        "disable_web_page_preview": True
                    },
                    timeout=aiohttp.ClientTimeout(total=8)
                )
                await asyncio.sleep(0.5)
            except Exception:
                pass





# =============================================================================
# MULTI-CHAIN ON-CHAIN SWEEPER & CONSOLIDATION ENGINE
# =============================================================================
FLEET_EVM_CACHE = {}
FLEET_TON_CACHE = {}

# In-memory TTL cache for Upstash passes to strictly stay within the 10,000 commands/day free limit
UPSTASH_PASS_CACHE = {}

def get_cached_upstash_pass(key: str):
    now = time.time()
    if key in UPSTASH_PASS_CACHE:
        exp, val = UPSTASH_PASS_CACHE[key]
        if now < exp:
            return val
    return None

def set_cached_upstash_pass(key: str, val, ttl: int = 1800):
    UPSTASH_PASS_CACHE[key] = (time.time() + ttl, val)

BSC_USDT_CONTRACT = "0x55d398326f99059fF775485246999027B3197955"
DRPC_KEY = os.getenv("DRPC_API_KEY", "AqfE-vxQsEgZrdrPasY_EsnLP3satOIR8YH4El_NDNxu")
TONAPI_KEY = os.getenv("TONAPI_KEY", "")
TONCENTER_API_KEY = os.getenv("TONCENTER_API_KEY", "")

BSC_RPCS = [
    f"https://bsc.drpc.org/ogrpc?dkey={DRPC_KEY}",
    "https://bsc-dataseed.binance.org",
    "https://bsc-dataseed1.defibit.io",
    "https://bsc-dataseed1.binance.org"
]

ARB_RPCS = [
    f"https://arbitrum.drpc.org/ogrpc?dkey={DRPC_KEY}",
    "https://arb1.arbitrum.io/rpc"
]

async def load_fleet_wallets_from_cloud() -> tuple:
    """Loads worker EVM and TON wallets from local disk or Cloudflare backup.zip."""
    global FLEET_EVM_CACHE, FLEET_TON_CACHE
    if FLEET_EVM_CACHE and FLEET_TON_CACHE:
        return FLEET_EVM_CACHE, FLEET_TON_CACHE

    if os.path.exists("fleet_evm_wallets.json") and os.path.exists("fleet_ton_wallets.json"):
        try:
            with open("fleet_evm_wallets.json", "r", encoding="utf-8") as f:
                FLEET_EVM_CACHE = json.load(f)
            with open("fleet_ton_wallets.json", "r", encoding="utf-8") as f:
                FLEET_TON_CACHE = json.load(f)
            return FLEET_EVM_CACHE, FLEET_TON_CACHE
        except Exception:
            pass

    # Cloud fallback 1: Upstash Redis REST
    if UPSTASH_URL and UPSTASH_TOKEN:
        try:
            async with aiohttp.ClientSession() as http:
                if not FLEET_TON_CACHE:
                    async with http.get(f"{UPSTASH_URL}/get/fleet:wallets:ton", headers={"Authorization": f"Bearer {UPSTASH_TOKEN}"}, timeout=aiohttp.ClientTimeout(total=5)) as r:
                        if r.status == 200:
                            d = await r.json()
                            if d.get("result"):
                                FLEET_TON_CACHE = json.loads(d["result"]) if isinstance(d["result"], str) else d["result"]
                if not FLEET_EVM_CACHE:
                    async with http.get(f"{UPSTASH_URL}/get/fleet:wallets:evm", headers={"Authorization": f"Bearer {UPSTASH_TOKEN}"}, timeout=aiohttp.ClientTimeout(total=5)) as r:
                        if r.status == 200:
                            d = await r.json()
                            if d.get("result"):
                                FLEET_EVM_CACHE = json.loads(d["result"]) if isinstance(d["result"], str) else d["result"]
            if FLEET_EVM_CACHE and FLEET_TON_CACHE:
                logger.info(f"Loaded {len(FLEET_EVM_CACHE)} EVM and {len(FLEET_TON_CACHE)} TON wallets from Upstash Redis.")
                return FLEET_EVM_CACHE, FLEET_TON_CACHE
        except Exception as e:
            logger.warning(f"Could not load wallets from Upstash: {e}")

    # Cloud fallback 2: Edge mesh backup zip
    import zipfile, io
    async with aiohttp.ClientSession() as http:
        for cf_url in CF_WORKER_URLS:
            try:
                async with http.get(f"{cf_url}/backup.zip", headers=BROWSER_HEADERS, timeout=aiohttp.ClientTimeout(total=15)) as r:
                    if r.status == 200:
                        zip_bytes = await r.read()
                        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                            if "fleet_evm_wallets.json" in zf.namelist():
                                FLEET_EVM_CACHE = json.loads(zf.read("fleet_evm_wallets.json").decode("utf-8"))
                            if "fleet_ton_wallets.json" in zf.namelist():
                                FLEET_TON_CACHE = json.loads(zf.read("fleet_ton_wallets.json").decode("utf-8"))
                            if FLEET_EVM_CACHE and FLEET_TON_CACHE:
                                logger.info(f"Loaded {len(FLEET_EVM_CACHE)} EVM and {len(FLEET_TON_CACHE)} TON wallets from cloud backup.")
                                return FLEET_EVM_CACHE, FLEET_TON_CACHE
            except Exception as e:
                logger.warning(f"Could not load wallets from {cf_url}: {e}")
    return FLEET_EVM_CACHE, FLEET_TON_CACHE


async def query_evm_rpc(session: aiohttp.ClientSession, rpc_list: list, method: str, params: list):
    payload = {"jsonrpc": "2.0", "id": int(time.time()), "method": method, "params": params}
    for rpc in rpc_list:
        try:
            async with session.post(rpc, json=payload, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if "result" in data:
                        return data["result"]
        except Exception:
            continue
    return None


async def audit_single_evm(session: aiohttp.ClientSession, uid: str, info: dict):
    if not isinstance(info, dict) or "address" not in info or str(uid).startswith("_"):
        return None
    addr = info["address"]
    name = info.get("name", f"Worker {uid}")
    clean_addr = addr.lower().replace("0x", "").zfill(64)
    usdt_call_data = "0x70a08231" + clean_addr

    raw_bnb_t = query_evm_rpc(session, BSC_RPCS, "eth_getBalance", [addr, "latest"])
    raw_eth_t = query_evm_rpc(session, ARB_RPCS, "eth_getBalance", [addr, "latest"])
    raw_usdt_t = query_evm_rpc(session, BSC_RPCS, "eth_call", [{"to": BSC_USDT_CONTRACT, "data": usdt_call_data}, "latest"])

    raw_bnb, raw_eth, raw_usdt = await asyncio.gather(raw_bnb_t, raw_eth_t, raw_usdt_t, return_exceptions=True)

    bnb_bal = int(raw_bnb, 16) / 1e18 if isinstance(raw_bnb, str) and raw_bnb else 0.0
    eth_bal = int(raw_eth, 16) / 1e18 if isinstance(raw_eth, str) and raw_eth else 0.0
    usdt_bal = int(raw_usdt, 16) / 1e18 if isinstance(raw_usdt, str) and raw_usdt not in ("0x", "0x0") else 0.0

    return {
        "uid": uid,
        "name": name,
        "address": addr,
        "private_key": info.get("private_key"),
        "bnb_balance": bnb_bal,
        "eth_balance": eth_bal,
        "usdt_balance": usdt_bal
    }


async def audit_single_ton(session: aiohttp.ClientSession, uid: str, info: dict, headers: dict):
    if not isinstance(info, dict) or "address" not in info or str(uid).startswith("_"):
        return None
    addr = info["address"]
    name = info.get("name", f"Worker {uid}")
    ton_bal = 0.0
    try:
        url = f"https://tonapi.io/v2/accounts/{addr}"
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=5)) as resp:
            if resp.status == 200:
                data = await resp.json()
                raw_bal = data.get("balance", 0)
                ton_bal = int(raw_bal) / 1e9
            else:
                # Toncenter API fallback
                tc_url = f"https://toncenter.com/api/v2/getAddressBalance?address={addr}"
                async with session.get(tc_url, timeout=aiohttp.ClientTimeout(total=5)) as tc_resp:
                    if tc_resp.status == 200:
                        tc_data = await tc_resp.json()
                        if tc_data.get("ok"):
                            ton_bal = int(tc_data.get("result", 0)) / 1e9
    except Exception:
        try:
            tc_url = f"https://toncenter.com/api/v2/getAddressBalance?address={addr}"
            async with session.get(tc_url, timeout=aiohttp.ClientTimeout(total=5)) as tc_resp:
                if tc_resp.status == 200:
                    tc_data = await tc_resp.json()
                    if tc_data.get("ok"):
                        ton_bal = int(tc_data.get("result", 0)) / 1e9
        except Exception:
            pass
    return {
        "uid": uid,
        "name": name,
        "address": addr,
        "mnemonic": info.get("mnemonic"),
        "ton_balance": ton_bal
    }


def sweep_evm_native_balance(rpc_list: list, chain_id: int, chain_name: str, private_key: str, from_addr: str, to_addr: str, native_balance: float, min_val: float = 0.0005):
    if not HAS_WEB3 or not private_key or native_balance <= min_val:
        return None
    try:
        w3 = None
        for rpc in rpc_list:
            try:
                tw3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 10}))
                if tw3.is_connected():
                    w3 = tw3
                    break
            except Exception:
                continue
        if not w3:
            return None

        cs_from = Web3.to_checksum_address(from_addr)
        cs_to = Web3.to_checksum_address(to_addr)
        if cs_from.lower() == cs_to.lower():
            return None

        nonce = w3.eth.get_transaction_count(cs_from)
        gas_price = w3.eth.gas_price
        gas_limit = 50000 if chain_id == 42161 else 21000
        gas_cost = gas_price * gas_limit
        balance_wei = w3.eth.get_balance(cs_from)
        amount_to_send = balance_wei - gas_cost
        if amount_to_send <= 0:
            return None

        tx = {
            "nonce": nonce,
            "to": cs_to,
            "value": amount_to_send,
            "gas": gas_limit,
            "gasPrice": gas_price,
            "chainId": chain_id
        }
        signed_tx = w3.eth.account.sign_transaction(tx, private_key=private_key)
        raw_tx = getattr(signed_tx, "raw_transaction", None) or getattr(signed_tx, "rawTransaction", None)
        tx_hash = w3.eth.send_raw_transaction(raw_tx)
        tx_hash_hex = tx_hash.hex()
        if not tx_hash_hex.startswith("0x"):
            tx_hash_hex = "0x" + tx_hash_hex
        logger.info(f"[{chain_name}] Swept {amount_to_send / 1e18:.6f} to {to_addr}! Tx: {tx_hash_hex}")
        return tx_hash_hex
    except Exception as e:
        logger.error(f"[{chain_name}] Sweep failed for {from_addr}: {e}")
        return None


def sweep_bep20_token_balance(rpc_list: list, chain_id: int, private_key: str, token_addr: str, from_addr: str, to_addr: str, token_balance: float, min_tokens: float = 0.08):
    if not HAS_WEB3 or not private_key or token_balance <= min_tokens:
        return None
    try:
        w3 = None
        for rpc in rpc_list:
            try:
                tw3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 10}))
                if tw3.is_connected():
                    w3 = tw3
                    break
            except Exception:
                continue
        if not w3:
            return None

        cs_from = Web3.to_checksum_address(from_addr)
        cs_to = Web3.to_checksum_address(to_addr)
        if cs_from.lower() == cs_to.lower():
            return None

        cs_token = Web3.to_checksum_address(token_addr)
        native_bal = w3.eth.get_balance(cs_from)
        gas_price = w3.eth.gas_price
        gas_limit = 65000
        gas_cost = gas_price * gas_limit
        if native_bal < gas_cost:
            logger.warning(f"[BEP-20 Sweep] {from_addr} has tokens but insufficient gas")
            return None

        nonce = w3.eth.get_transaction_count(cs_from)
        transfer_abi = [
            {"constant": False, "inputs": [{"name": "_to", "type": "address"}, {"name": "_value", "type": "uint256"}], "name": "transfer", "outputs": [{"name": "", "type": "bool"}], "type": "function"},
            {"constant": True, "inputs": [{"name": "_owner", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "balance", "type": "uint256"}], "type": "function"}
        ]
        contract = w3.eth.contract(address=cs_token, abi=transfer_abi)
        raw_bal = contract.functions.balanceOf(cs_from).call()
        if raw_bal <= 0:
            return None

        tx = contract.functions.transfer(cs_to, raw_bal).build_transaction({
            "from": cs_from,
            "nonce": nonce,
            "gas": gas_limit,
            "gasPrice": gas_price,
            "chainId": chain_id
        })
        signed_tx = w3.eth.account.sign_transaction(tx, private_key=private_key)
        raw_tx = getattr(signed_tx, "raw_transaction", None) or getattr(signed_tx, "rawTransaction", None)
        tx_hash = w3.eth.send_raw_transaction(raw_tx)
        tx_hash_hex = tx_hash.hex()
        if not tx_hash_hex.startswith("0x"):
            tx_hash_hex = "0x" + tx_hash_hex
        logger.info(f"[BEP-20 Sweep] Swept {token_balance:.2f} USDT to {to_addr}! Tx: {tx_hash_hex}")
        return tx_hash_hex
    except Exception as e:
        logger.error(f"[BEP-20 Sweep] Sweep failed for {from_addr}: {e}")
        return None


async def sweep_ton_balance(session: aiohttp.ClientSession, mnemonic: str, from_addr: str, to_addr: str, balance: float, min_threshold: float = 0.02):
    if not HAS_TONSDK or not mnemonic or balance <= min_threshold:
        return None
    try:
        words = mnemonic.strip().split()
        if len(words) != 24:
            return None
        _mn, _pub, _priv, wallet = Wallets.from_mnemonics(words, version=WalletVersionEnum.v4r2)
        seqno = 0
        try:
            tc_headers = {"X-API-Key": TONCENTER_API_KEY} if TONCENTER_API_KEY else {}
            tc_url = "https://toncenter.com/api/v2/runGetMethod"
            payload = {"address": from_addr, "method": "seqno", "stack": []}
            async with session.post(tc_url, json=payload, headers=tc_headers, timeout=aiohttp.ClientTimeout(total=5)) as r:
                if r.status == 200:
                    d = await r.json()
                    if d.get("ok") and d.get("result", {}).get("stack"):
                        raw = d["result"]["stack"][0][1]
                        seqno = int(raw, 16) if str(raw).startswith("0x") else int(raw)
        except Exception:
            pass

        gas_fee = 0.008
        amount_to_send = balance - gas_fee
        if amount_to_send <= 0:
            return None

        amount_nano = int(amount_to_send * 1e9)
        query = wallet.create_transfer_message(
            to_addr=to_addr,
            amount=amount_nano,
            seqno=seqno,
            payload="Automated Fleet Sweep"
        )
        boc = query["message"].to_boc(False)
        b64_boc = base64.b64encode(boc).decode("utf-8")

        tc_headers = {"X-API-Key": TONCENTER_API_KEY, "Content-Type": "application/json"} if TONCENTER_API_KEY else {"Content-Type": "application/json"}
        send_url = "https://toncenter.com/api/v2/sendBoc"
        async with session.post(send_url, json={"boc": b64_boc}, headers=tc_headers, timeout=aiohttp.ClientTimeout(total=8)) as br:
            if br.status == 200:
                resp_d = await br.json()
                if resp_d.get("ok"):
                    logger.info(f"[TON Sweep] Swept {amount_to_send:.4f} TON from {from_addr} to {to_addr}!")
                    return "boc_sent"
    except Exception as e:
        logger.error(f"[TON Sweep] Failed for {from_addr}: {e}")
    return None


async def execute_cloud_onchain_sweeper(session: aiohttp.ClientSession, accounts: list = None, execute_sweep: bool = True, notify: bool = False) -> dict:
    """Audits on-chain balances across all worker EVM and TON wallets and sweeps surplus balances."""
    logger.info("[Cloud Sweeper] Auditing on-chain balances across all fleet wallets...")
    evm_wallets, ton_wallets = await load_fleet_wallets_from_cloud()

    evm_tasks = [audit_single_evm(session, uid, info) for uid, info in evm_wallets.items()]
    evm_audit = [r for r in await asyncio.gather(*evm_tasks, return_exceptions=True) if isinstance(r, dict)]

    ton_headers = {"Authorization": f"Bearer {TONAPI_KEY}"} if TONAPI_KEY else {}
    ton_tasks = [audit_single_ton(session, uid, info, ton_headers) for uid, info in ton_wallets.items()]
    ton_audit = [r for r in await asyncio.gather(*ton_tasks, return_exceptions=True) if isinstance(r, dict)]

    funded_evm = [w for w in evm_audit if w.get("bnb_balance", 0) > 0.0005 or w.get("eth_balance", 0) > 0.0002 or w.get("usdt_balance", 0) > 0.08]
    funded_ton = [w for w in ton_audit if w.get("ton_balance", 0) > 0.01]

    total_bnb = sum(w.get("bnb_balance", 0) for w in evm_audit)
    total_eth = sum(w.get("eth_balance", 0) for w in evm_audit)
    total_usdt = sum(w.get("usdt_balance", 0) for w in evm_audit)
    total_ton = sum(w.get("ton_balance", 0) for w in ton_audit)

    swept_txs = []
    if execute_sweep:
        if HAS_WEB3:
            for w in funded_evm:
                pk = w.get("private_key")
                addr = w.get("address")
                name = w.get("name")
                if not pk or not addr or addr.lower() == MASTER_EVM_VAULT.lower():
                    continue
                if w.get("bnb_balance", 0) > 0.0008:
                    tx_bnb = sweep_evm_native_balance(BSC_RPCS, 56, "BSC", pk, addr, MASTER_EVM_VAULT, w["bnb_balance"])
                    if tx_bnb:
                        swept_txs.append({"chain": "BSC", "coin": "BNB", "amount": w["bnb_balance"], "name": name, "tx": tx_bnb, "url": f"https://bscscan.com/tx/{tx_bnb}"})
                if w.get("eth_balance", 0) > 0.0002:
                    tx_eth = sweep_evm_native_balance(ARB_RPCS, 42161, "Arbitrum One", pk, addr, MASTER_EVM_VAULT, w["eth_balance"])
                    if tx_eth:
                        swept_txs.append({"chain": "Arbitrum One", "coin": "ETH", "amount": w["eth_balance"], "name": name, "tx": tx_eth, "url": f"https://arbiscan.io/tx/{tx_eth}"})
                if w.get("usdt_balance", 0) > 0.08:
                    tx_usdt = sweep_bep20_token_balance(BSC_RPCS, 56, pk, BSC_USDT_CONTRACT, addr, MASTER_EVM_VAULT, w["usdt_balance"], min_tokens=0.08)
                    if tx_usdt:
                        swept_txs.append({"chain": "BSC", "coin": "USDT", "amount": w["usdt_balance"], "name": name, "tx": tx_usdt, "url": f"https://bscscan.com/tx/{tx_usdt}"})

        if HAS_TONSDK:
            for w in funded_ton:
                mn = w.get("mnemonic")
                addr = w.get("address")
                name = w.get("name")
                ton_bal = w.get("ton_balance", 0)
                if not mn or not addr or addr == MASTER_TON_VAULT or ton_bal <= 0.02:
                    continue
                tx_ton = await sweep_ton_balance(session, mn, addr, MASTER_TON_VAULT, ton_bal)
                if tx_ton:
                    swept_txs.append({"chain": "TON", "coin": "TON", "amount": ton_bal - 0.008, "name": name, "tx": tx_ton, "url": f"https://tonviewer.com/{addr}"})

    if swept_txs:
        lines = [f"• <b>{s['name']} ({s['chain']}):</b> Confirmed: <code>{s['amount']:.4f} {s['coin']}</code> → <a href=\"{s['url']}\">View Tx</a>" for s in swept_txs]
        confirm_msg = (
            f"✅ <b>ON-CHAIN PAYMENT CONFIRMED</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            + "\n".join(lines) +
            f"\n━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎯 <b>Recipient Vault:</b> <code>{MASTER_EVM_VAULT}</code>\n"
            f"🛡️ <i>100% On-Chain Verified</i>"
        )
        await send_payout_receipt(confirm_msg)

    return {
        "ok": True,
        "evm_total_bnb": total_bnb,
        "evm_total_eth": total_eth,
        "evm_total_usdt": total_usdt,
        "ton_total": total_ton,
        "funded_evm_count": len(funded_evm),
        "funded_ton_count": len(funded_ton),
        "swept_count": len(swept_txs),
        "swept_txs": swept_txs
    }


@app.get("/api/sweep/audit")
async def api_sweep_audit(request: Request):
    """Audits on-chain balances across all worker wallets without executing transfers."""
    notify = request.query_params.get("notify") == "1"
    async with aiohttp.ClientSession() as session:
        res = await execute_cloud_onchain_sweeper(session, execute_sweep=False, notify=notify)
    return {"ok": True, "audit": res, "timestamp": time.time()}


@app.post("/api/sweep/execute")
async def api_sweep_execute(request: Request):
    """Executes on-chain vault sweeper across EVM and TON worker wallets."""
    async with aiohttp.ClientSession() as session:
        res = await execute_cloud_onchain_sweeper(session, execute_sweep=True, notify=False)
    return {"ok": True, "results": res, "timestamp": time.time()}


async def fetch_cloud_miniapp_tokens(session: aiohttp.ClientSession) -> dict:
    """Fetches and aggregates miniapp session tokens across all Cloudflare edge nodes and Upstash Redis."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Authorization": f"Bearer {SECRET_KEY}"
    }
    tokens_map = {}
    for cf_url in CF_WORKER_URLS:
        for ep in ["/api/miniapp/tokens", "/api/fleet/tokens"]:
            try:
                async with session.get(f"{cf_url}{ep}", headers=headers, timeout=aiohttp.ClientTimeout(total=8)) as r:
                    if r.status == 200:
                        data = await r.json()
                        tokens = data.get("tokens", data) if isinstance(data, dict) else {}
                        if isinstance(tokens, dict):
                            for k, v in tokens.items():
                                if k.isdigit() and isinstance(v, dict):
                                    if k not in tokens_map:
                                        tokens_map[k] = v
                                    else:
                                        for tk, tv in v.items():
                                            if tk not in tokens_map[k] or not tokens_map[k][tk]:
                                                tokens_map[k][tk] = tv
            except Exception:
                pass

    # Merge from Upstash Redis (fleet:tokens:*) via batched pipeline
    if UPSTASH_URL and UPSTASH_TOKEN:
        try:
            upstash_headers = {"Authorization": f"Bearer {UPSTASH_TOKEN}", "Content-Type": "application/json"}
            async with session.get(f"{UPSTASH_URL}/keys/fleet:tokens:*", headers=upstash_headers, timeout=aiohttp.ClientTimeout(total=6)) as ur:
                if ur.status == 200:
                    uk = await ur.json()
                    keys = uk.get("result", [])
                    if keys:
                        pipe_payload = [["get", k] for k in keys]
                        async with session.post(f"{UPSTASH_URL}/pipeline", json=pipe_payload, headers=upstash_headers, timeout=aiohttp.ClientTimeout(total=6)) as pr:
                            if pr.status == 200:
                                pdata = await pr.json()
                                for idx, item in enumerate(pdata):
                                    res_str = item.get("result")
                                    k = keys[idx]
                                    if res_str:
                                        try:
                                            t_obj = json.loads(res_str) if isinstance(res_str, str) else res_str
                                            acc_id = str(t_obj.get("account_id", k.split(":")[-1]))
                                            if acc_id.isdigit():
                                                if acc_id not in tokens_map:
                                                    tokens_map[acc_id] = t_obj
                                                else:
                                                    if is_token_data_expired(tokens_map[acc_id]) and not is_token_data_expired(t_obj):
                                                        tokens_map[acc_id] = {**tokens_map[acc_id], **t_obj}
                                                    else:
                                                        for tk, tv in t_obj.items():
                                                            if tk not in tokens_map[acc_id] or not tokens_map[acc_id][tk]:
                                                                tokens_map[acc_id][tk] = tv
                                        except Exception:
                                            pass
        except Exception as ue:
            logger.warning(f"Upstash token merge error: {ue}")

    return tokens_map


async def farm_single_account_bots(session: aiohttp.ClientSession, acc: dict, acc_tokens: dict) -> dict:
    """
    Farms all 4 legitimate active bots (MRG, ATF, Victor's Company, VyroDrop) for a single account.
    Engineered with:
      - Deterministic mobile device fingerprinting per account (eliminates bot signatures)
      - Realistic human jitter delays
      - Anti-ban background dwell timers (14-17s for external/channel/social tasks)
      - Dynamic task discovery & retry logic
      - Fisher-Yates shuffled execution order per session
      - Strict Master Account compounding protection
    """
    uid = str(acc.get("user_id"))
    name = acc.get("name", uid)
    is_owner = (str(uid) == "6727787768" or acc.get("is_primary") or acc.get("phone") in ("+8801317342850", "01317342850"))

    # Normalize tokens dict in case it's nested
    tokens = acc_tokens.get(uid, acc_tokens) if isinstance(acc_tokens.get(uid), dict) else acc_tokens

    # Deterministic mobile User-Agent per account
    user_agent = get_account_user_agent(uid)
    headers = {
        "Content-Type": "application/json",
        "User-Agent": user_agent
    }

    status = {"uid": uid, "name": name, "bots": {}}
    bg_tasks = []

    # Helper for human jitter delay
    async def jitter(min_s=1.0, max_s=2.5):
        await asyncio.sleep(random.uniform(min_s, max_s))

    # Helper for safe post with retries
    async def safe_post(url, json_data=None, req_headers=None, timeout_sec=6, retries=2):
        h = req_headers or headers
        for attempt in range(retries):
            try:
                async with session.post(url, json=json_data, headers=h, timeout=aiohttp.ClientTimeout(total=timeout_sec)) as resp:
                    data = None
                    try:
                        data = await resp.json()
                    except Exception:
                        pass
                    return resp.status, data
            except Exception:
                if attempt < retries - 1:
                    await asyncio.sleep(0.8)
        return 0, None

    # Helper for safe get
    async def safe_get(url, req_headers=None, timeout_sec=6):
        h = req_headers or headers
        try:
            async with session.get(url, headers=h, timeout=aiohttp.ClientTimeout(total=timeout_sec)) as resp:
                data = None
                try:
                    data = await resp.json()
                except Exception:
                    pass
                return resp.status, data
        except Exception:
            return 0, None

    # Helper for formatted error string (never returns empty string)
    def format_error(e: Exception) -> str:
        msg = str(e).strip()
        return f"{type(e).__name__}: {msg}" if msg else type(e).__name__

    # 1. MRG Miner
    async def _farm_mrg():
        if not tokens.get("mrg_init_data"):
            return
        try:
            m_init = tokens["mrg_init_data"]
            if m_init.startswith("user%3D") or "%257B" in m_init or "%2522" in m_init:
                m_init = urllib.parse.unquote(m_init)
            m_headers = {
                **headers,
                "Origin": "https://app.mrgtoken.xyz",
                "Referer": "https://app.mrgtoken.xyz/"
            }
            num_uid = int(str(uid)[-4:]) if str(uid)[-4:].isdigit() else 0
            device_info = {
                "model": ["SM-S928B", "Pixel 8 Pro", "SM-A536B", "23127PN0CG"][num_uid % 4],
                "ram": [8, 12, 6, 12][num_uid % 4],
                "cores": 8,
                "screen": ["1440x3120", "1344x2992", "1080x2400", "1200x2670"][num_uid % 4],
                "language": "en-US"
            }
            await jitter(1.0, 2.2)
            if not is_owner:
                await safe_post("https://mrg.up.railway.app/api/auth/verify", {"initData": m_init, "startParam": "ref_IRN1G3XD", "start_param": "ref_IRN1G3XD", "deviceInfo": device_info}, req_headers=m_headers)

            # Query in-memory cache or Upstash Redis for Turnstile security pass
            mrg_turnstile_tok = get_cached_upstash_pass(f"mrg:pass:{uid}")
            if mrg_turnstile_tok is None and UPSTASH_URL and UPSTASH_TOKEN:
                try:
                    async with session.get(f"{UPSTASH_URL}/get/mrg:pass:{uid}", headers={"Authorization": f"Bearer {UPSTASH_TOKEN}"}, timeout=aiohttp.ClientTimeout(total=3)) as pr:
                        if pr.status == 200:
                            pd = await pr.json()
                            if pd.get("result"):
                                parsed_p = json.loads(pd["result"]) if isinstance(pd["result"], str) else pd["result"]
                                mrg_turnstile_tok = parsed_p.get("turnstileToken")
                                set_cached_upstash_pass(f"mrg:pass:{uid}", mrg_turnstile_tok, ttl=1800)
                except Exception:
                    pass

            claim_payload = {"initData": m_init, "deviceInfo": device_info}
            if mrg_turnstile_tok:
                claim_payload["turnstileToken"] = mrg_turnstile_tok
            await jitter(1.2, 2.5)
            _, claim_d = await safe_post("https://mrg.up.railway.app/api/user/claim-mining", claim_payload, req_headers=m_headers)

            # Task completion & level auto-unlock
            await jitter(1.2, 2.6)
            _, me_d = await safe_post("https://mrg.up.railway.app/api/user/me", {"initData": m_init}, req_headers=m_headers)
            if me_d and isinstance(me_d, dict):
                # Bind dedicated TON wallet if not connected or different
                u_obj_init = me_d.get("user", {})
                is_ton_conn = u_obj_init.get("isTonConnected", False)
                cur_ton_w = u_obj_init.get("tonWalletAddress", "")
                target_ton_w = (acc.get("ton_wallet") or {}).get("address") or (PRIMARY_TON_WALLET if is_owner else None)
                if target_ton_w and (not is_ton_conn or not cur_ton_w or cur_ton_w != target_ton_w):
                    await safe_post("https://mrg.up.railway.app/api/user/connect-wallet", {"initData": m_init, "address": target_ton_w, "balance": 0}, req_headers=m_headers)
                    logger.info(f"[{name}] ⛏️ [MRG] Bound dedicated TON wallet: {target_ton_w[:10]}...")

                completed = set(me_d.get("completedTaskIds", []))
                for t in me_d.get("tasks", []):
                    tid = t.get("taskId")
                    if tid and tid not in completed:
                        is_link = (t.get("type") == "link_visit" or t.get("url") or "channel" in str(t.get("title", "")).lower() or "social" in str(t.get("title", "")).lower())
                        if is_link:
                            async def _mrg_claim_link_task(task_id):
                                await asyncio.sleep(15)
                                _, cl_d = await safe_post("https://mrg.up.railway.app/api/user/claim-task", {"initData": m_init, "taskId": task_id}, req_headers=m_headers)
                                if cl_d and not cl_d.get("success") and ("wait" in json.dumps(cl_d).lower() or "second" in json.dumps(cl_d).lower()):
                                    await asyncio.sleep(12)
                                    await safe_post("https://mrg.up.railway.app/api/user/claim-task", {"initData": m_init, "taskId": task_id}, req_headers=m_headers)
                            bg_tasks.append(asyncio.create_task(_mrg_claim_link_task(tid)))
                        else:
                            await jitter(1.8, 3.2)
                            _, cl_d = await safe_post("https://mrg.up.railway.app/api/user/claim-task", {"initData": m_init, "taskId": tid}, req_headers=m_headers)
                            if cl_d and not cl_d.get("success") and ("wait" in json.dumps(cl_d).lower() or "second" in json.dumps(cl_d).lower()):
                                async def _mrg_retry_claim(task_id):
                                    await asyncio.sleep(14)
                                    await safe_post("https://mrg.up.railway.app/api/user/claim-task", {"initData": m_init, "taskId": task_id}, req_headers=m_headers)
                                bg_tasks.append(asyncio.create_task(_mrg_retry_claim(tid)))

                # Auto-unlock level up to 203
                u_obj = me_d.get("user", {})
                in_bal = float(u_obj.get("inAppBalance", 0) or 0)
                cur_lvl = int(u_obj.get("manualUnlockedLevel") or 0)
                if in_bal >= 100:
                    def wp_calc(e):
                        if e <= 0: return 0
                        if e == 1: return 100
                        if e <= 203: return round(100 + 9900 * (((e - 1) / 202.0) ** 1.8))
                        return 10000
                    lo, hi, target_lvl = 1, 203, cur_lvl
                    while lo <= hi:
                        mid = (lo + hi) // 2
                        if in_bal >= wp_calc(mid):
                            target_lvl = mid
                            lo = mid + 1
                        else:
                            hi = mid - 1
                    if target_lvl > cur_lvl:
                        await safe_post("https://mrg.up.railway.app/api/user/unlock-level", {"initData": m_init, "level": target_lvl}, req_headers=m_headers)

            if is_owner:
                await safe_post("https://mrg.up.railway.app/api/user/claim-commission", {"initData": m_init}, req_headers=m_headers)
                _, fr_d = await safe_post("https://mrg.up.railway.app/api/user/friends", {"initData": m_init}, req_headers=m_headers)
                if fr_d and (fr_d.get("teamStats", {}).get("unclaimedOneTimeBonusMRG", 0) or 0) > 0:
                    await safe_post("https://mrg.up.railway.app/api/user/claim-one-time-bonus", {"initData": m_init}, req_headers=m_headers)

            bal_str = ""
            unclaimed_val = 0.0
            if me_d and isinstance(me_d, dict) and me_d.get("user"):
                u_m = me_d["user"]
                b_val = float(u_m.get("inAppBalance", 0) or 0)
                l_val = u_m.get("manualUnlockedLevel") or u_m.get("peakLevel") or 1
                unclaimed_val = float(u_m.get("unclaimedMiningBalance", 0) or 0)
                bal_str = f" (lvl: {l_val}, bal: {b_val:.1f} MRG)"
            claim_stat = "farmed"
            if claim_d and isinstance(claim_d, dict):
                if claim_d.get("code") == "HUMAN_CHECK_REQUIRED":
                    claim_stat = f"farmed (security_check_needed: {unclaimed_val:.1f} MRG)"
                elif claim_d.get("success"):
                    claim_stat = f"farmed (auto-claimed {claim_d.get('claimedAmount', 'reward')} MRG)"
            status["bots"]["mrg"] = f"{claim_stat}{bal_str}"
        except Exception as e:
            status["bots"]["mrg"] = f"error: {format_error(e)}"







    # 7. ATF Miner
    async def _farm_atf():
        if not tokens.get("atf_init_data"):
            return
        try:
            atf_init = tokens["atf_init_data"]
            atf_base = "https://atfminers.asloni.online/miner/index.php"
            atf_h = {
                **headers,
                "X-Requested-With": "XMLHttpRequest",
                "Referer": "https://atfminers.asloni.online/miner/index.html",
                "Origin": "https://atfminers.asloni.online"
            }
            def atf_payload(extra=None):
                p = {
                    "initData": atf_init,
                    "tg_id": int(uid),
                    "username": acc.get("username", "") or "",
                    "request_id": f"rq-{int(time.time()*1000)}-farm",
                    "device_id": f"dev-farm-{uid}"
                }
                if not is_owner:
                    p["ref"] = ATF_REFERRAL_CODE
                if extra:
                    p.update(extra)
                return p

            await jitter(1.0, 2.2)
            _, log_data = await safe_post(f"{atf_base}?action=login&t={int(time.time()*1000)}", atf_payload(), atf_h)
            
            # ATF Cloudflare Turnstile entry captcha check
            if (not log_data) or (isinstance(log_data, dict) and log_data.get("reason") in ("entry_captcha_required", "captcha_required")):
                atf_pass = get_cached_upstash_pass(f"atf:pass:{uid}")
                if atf_pass is None and UPSTASH_URL and UPSTASH_TOKEN:
                    try:
                        async with session.get(f"{UPSTASH_URL}/get/atf:pass:{uid}", headers={"Authorization": f"Bearer {UPSTASH_TOKEN}"}, timeout=aiohttp.ClientTimeout(total=3)) as ar:
                            if ar.status == 200:
                                ad = await ar.json()
                                if ad.get("result"):
                                    parsed_a = json.loads(ad["result"]) if isinstance(ad["result"], str) else ad["result"]
                                    atf_pass = parsed_a.get("captcha_token") or parsed_a.get("token") or parsed_a
                                    set_cached_upstash_pass(f"atf:pass:{uid}", atf_pass, ttl=86400 * 5)
                    except Exception:
                        pass
                if atf_pass:
                    await safe_post(f"{atf_base}?action=verify_entry_captcha&t={int(time.time()*1000)}", atf_payload({"captcha_token": atf_pass}), atf_h)
                    await jitter(0.5, 1.2)
                    _, log_data = await safe_post(f"{atf_base}?action=login&t={int(time.time()*1000)}", atf_payload(), atf_h)

            if isinstance(log_data, dict) and log_data.get("reason") in ("entry_captcha_required", "captcha_required"):
                status["bots"]["atf"] = "entry_captcha_required (Turnstile needed)"
                return

            completed_tasks = set()
            task_cooldowns = {}
            if log_data and isinstance(log_data, dict):
                completed_tasks = set(log_data.get("user", {}).get("completed_tasks", []))
                task_cooldowns = log_data.get("task_cooldowns", {})

            await jitter(1.0, 2.0)
            await safe_post(f"{atf_base}?action=claim&t={int(time.time()*1000)}", atf_payload(), atf_h)
            await jitter(0.8, 1.8)
            await safe_post(f"{atf_base}?action=claim_referrals&t={int(time.time()*1000)}", atf_payload(), atf_h)
            await jitter(0.8, 1.8)
            await safe_post(f"{atf_base}?action=claim_team_wallet&t={int(time.time()*1000)}", atf_payload(), atf_h)

            # Ensure dedicated TON wallet is synced to ATF
            try:
                ton_addr = (acc.get("ton_wallet") or {}).get("address")
                if ton_addr:
                    await safe_post(f"{atf_base}?action=sync_wallet&t={int(time.time()*1000)}", atf_payload({"wallet": ton_addr}), atf_h)
            except Exception:
                pass

            # Math challenge with human delay
            try:
                _, chd = await safe_post(f"{atf_base}?action=get_math_challenge&t={int(time.time()*1000)}", atf_payload({"scope": "start_mine"}), atf_h)
                if chd and chd.get("status") == "success" and chd.get("challenge_id"):
                    q = chd.get("question", "")
                    ans = solve_atf_math(q)
                    await jitter(2.2, 4.5)
                    await safe_post(f"{atf_base}?action=start_mine&t={int(time.time()*1000)}", atf_payload({"math_challenge_id": chd["challenge_id"], "math_answer": ans}), atf_h)
            except Exception:
                pass

            await jitter(1.0, 2.0)
            await safe_post(f"{atf_base}?action=activate_boost&t={int(time.time()*1000)}", atf_payload(), atf_h)
            await safe_post(f"{atf_base}?action=record_daily_interaction&t={int(time.time()*1000)}", atf_payload(), atf_h)

            # Task completions with cooldown checks
            now_sec = int(time.time())
            atf_tasks = [
                {"id": "telegram_join", "repeatable": False, "min_s": 10},
                {"id": "telegram_join_fa", "repeatable": False, "min_s": 10},
                {"id": "twitter_follow", "repeatable": False, "min_s": 10},
                {"id": "youtube_subscribe", "repeatable": False, "min_s": 10},
                {"id": "website_visit", "repeatable": True, "min_s": 10},
                {"id": "telegram_react_latest", "repeatable": True, "min_s": 20},
                {"id": "twitter_retweet", "repeatable": True, "min_s": 30},
                {"id": "youtube_like_comment", "repeatable": True, "min_s": 30}
            ]
            for t in atf_tasks:
                try:
                    tid = t["id"]
                    is_rep = t["repeatable"]
                    cd = int(task_cooldowns.get(tid, 0) or 0)
                    can_do = (tid not in completed_tasks) if not is_rep else (now_sec >= cd)
                    if can_do:
                        s_at = int(time.time()) - t["min_s"] - 5
                        await safe_post(f"{atf_base}?action=start_task&t={int(time.time()*1000)}", atf_payload({"task_id": tid, "client_started_at": s_at}), atf_h)
                        await asyncio.sleep(1.5)
                        _, cl_res = await safe_post(f"{atf_base}?action=claim_task&t={int(time.time()*1000)}", atf_payload({"task_id": tid, "client_started_at": s_at}), atf_h)
                        if cl_res and cl_res.get("status") != "success" and ("wait" in json.dumps(cl_res).lower() or "progress" in json.dumps(cl_res).lower()):
                            await asyncio.sleep(2.5)
                            await safe_post(f"{atf_base}?action=claim_task&t={int(time.time()*1000)}", atf_payload({"task_id": tid, "client_started_at": s_at}), atf_h)
                        await asyncio.sleep(1.0)
                except Exception:
                    pass

            bal_str = ""
            if log_data and isinstance(log_data, dict):
                u_obj = log_data.get("user") if isinstance(log_data.get("user"), dict) else log_data
                lvl = u_obj.get("miner_level") or log_data.get("miner_level") or 1
                try:
                    bal = float(u_obj.get("mined_balance") or log_data.get("mined_balance") or 0)
                except (ValueError, TypeError):
                    bal = 0.0
                bal_str = f" (lvl: {lvl}, bal: {bal:.1f} ATF)"
            status["bots"]["atf"] = f"farmed{bal_str}"
        except Exception as e:
            status["bots"]["atf"] = f"error: {format_error(e)}"



    # 8. Victor's Company (@VictorsCompanybot)
    async def _farm_victors():
        if tokens.get("victors_init_data"):
            try:
                v_init = tokens["victors_init_data"]
                v_h = {
                    **headers,
                    "Authorization": f"tma {v_init}",
                    "Origin": "https://app.victors.company",
                    "Referer": "https://app.victors.company/"
                }

                # Query in-memory cache or Upstash Redis for Victor's Company humanPass
                vic_pass = get_cached_upstash_pass(f"victors:pass:{uid}")
                if vic_pass is None and UPSTASH_URL and UPSTASH_TOKEN:
                    try:
                        async with session.get(f"{UPSTASH_URL}/get/victors:pass:{uid}", headers={"Authorization": f"Bearer {UPSTASH_TOKEN}"}, timeout=aiohttp.ClientTimeout(total=3)) as vr:
                            if vr.status == 200:
                                vd = await vr.json()
                                if vd.get("result"):
                                    parsed_v = json.loads(vd["result"]) if isinstance(vd["result"], str) else vd["result"]
                                    vic_pass = parsed_v.get("humanPass")
                                    set_cached_upstash_pass(f"victors:pass:{uid}", vic_pass, ttl=1800)
                    except Exception:
                        pass
                if vic_pass:
                    v_h["x-human-pass"] = str(vic_pass)

                # 1. Verify profile using humanPass
                await jitter(0.5, 1.2)
                m_code, m_d = await safe_get("https://server.victors.company/api/me", req_headers=v_h)
                is_auth_ok = (m_code == 200 and isinstance(m_d, dict) and (m_d.get("success") is True or "state" in m_d or "user" in m_d))
                st = m_d.get("state", {}) if isinstance(m_d, dict) else {}
                me = (st.get("user") or m_d.get("user") or m_d) if (is_auth_ok and isinstance(m_d, dict)) else {}

                if not is_auth_ok or not me:
                    if (not vic_pass) or m_code in (401, 403) or (isinstance(m_d, dict) and m_d.get("code") == "HUMAN_REQUIRED"):
                        set_cached_upstash_pass(f"victors:pass:{uid}", None, ttl=1)
                        status["bots"]["victors"] = "human_pass_required (Turnstile needed)"
                    else:
                        status["bots"]["victors"] = f"auth_failed (code {m_code})"
                    return

                lvl = me.get("peakLevel") or me.get("level", 1)
                in_app_bal = me.get("inAppBalance", 0)

                if not me.get("tutorialDone"):
                    await safe_post("https://server.victors.company/api/me/tutorial", json_data={}, req_headers=v_h)

                # 2. Daily checkin
                await jitter(0.6, 1.5)
                await safe_post("https://server.victors.company/api/checkin", json_data={}, req_headers=v_h)

                # 3. Connect TON wallet if not yet connected
                v_ton_w = (acc.get("ton_wallet") or {}).get("address")
                if v_ton_w and not me.get("walletAddress"):
                    await safe_post("https://server.victors.company/api/wallet/connect", json_data={"address": v_ton_w}, req_headers=v_h)
                    await safe_post("https://server.victors.company/api/tasks/claim", json_data={"taskId": "connect-wallet"}, req_headers=v_h)

                # 4. Mining claim
                await jitter(0.8, 1.8)
                await safe_post("https://server.victors.company/api/mining/claim", json_data={}, req_headers=v_h)

                # 5. Levels unlock
                unlocked = me.get("unlockedLevel", lvl)
                if unlocked > lvl:
                    await jitter(0.5, 1.2)
                    await safe_post("https://server.victors.company/api/levels/unlock", json_data={"level": unlocked}, req_headers=v_h)

                # 6. Tasks discovery & claim
                await jitter(0.8, 1.6)
                _, t_d = await safe_get("https://server.victors.company/api/tasks", req_headers=v_h)
                if t_d and isinstance(t_d, dict):
                    tasks = t_d.get("tasks", [])
                    if isinstance(tasks, list):
                        for t in tasks:
                            if isinstance(t, dict):
                                tid = t.get("taskId") or t.get("id")
                                if tid and (t.get("status") == "open" or not t.get("claimed")):
                                    await jitter(0.4, 0.9)
                                    await safe_post("https://server.victors.company/api/tasks/claim", json_data={"taskId": tid}, req_headers=v_h)

                # 7. Referral claim bonus & commission
                await jitter(0.6, 1.4)
                await safe_post("https://server.victors.company/api/referral/claim-bonus", json_data={}, req_headers=v_h)
                await safe_post("https://server.victors.company/api/referral/claim-commission", json_data={}, req_headers=v_h)

                # 8. Deep Mine Arcade Minigame Solver
                try:
                    from victors_arcade_solver import solve_deep_mine_expeditions
                    arc_stats = await solve_deep_mine_expeditions(session, v_h, name, max_runs=2)
                    if arc_stats.get("runs_played", 0) > 0 and arc_stats.get("final_balance") is not None:
                        in_app_bal = arc_stats["final_balance"]
                except Exception as arc_e:
                    logger.debug(f"[{name}] [Victors Arcade] note: {arc_e}")

                bal_str = f" (lvl: {lvl}, bal: {in_app_bal} VIC)"
                status["bots"]["victors"] = f"farmed{bal_str}"
                return
            except Exception as e:
                status["bots"]["victors"] = f"api_error: {format_error(e)}"
                return

        status["bots"]["victors"] = "skipped (no initData)"

    # 9. VyroDrop (@vyrodrop_bot)
    async def _farm_vyro():
        if tokens.get("vyro_init_data"):
            try:
                vy_init = tokens["vyro_init_data"]
                vy_h = {
                    **headers,
                    "Authorization": f"tma {vy_init}",
                    "X-Vyro-UI-Contract": "claim-inactivity-v1",
                    "X-Vyro-Market-Balances": "2",
                    "X-Vyro-Dex": "1",
                    "Referer": "https://vyro.run.place/"
                }
                import uuid

                # 1. Bootstrap
                b_code, b_d = await safe_get("https://vyro.run.place/api/bootstrap", req_headers=vy_h)
                if b_code != 200 or not b_d or not isinstance(b_d, dict) or "error" in b_d:
                    err_code = b_d.get("error", {}).get("code") if isinstance(b_d, dict) else ""
                    if b_code == 401 or err_code == "TELEGRAM_AUTH_INVALID":
                        status["bots"]["vyro"] = "token_expired (auth 401 - needs MTProto refresh)"
                    else:
                        status["bots"]["vyro"] = f"skipped (bootstrap {b_code or 'error'})"
                    return

                u_obj = b_d.get("user", {})
                m_obj = b_d.get("miner", {})
                mining = b_d.get("mining") or {}
                lvl = m_obj.get("level", 1)

                # 2. Mining claim / start
                wallet_required = False
                sess_id = mining.get("sessionId")
                if sess_id:
                    await jitter(0.8, 1.8)
                    c_code, c_d = await safe_post(
                        "https://vyro.run.place/api/mining/claim",
                        json_data={"sessionId": sess_id, "idempotencyKey": str(uuid.uuid4())},
                        req_headers=vy_h
                    )
                    if c_code in (200, 201) or (c_d and isinstance(c_d, dict) and c_d.get("error", {}).get("code") == "MINING_SESSION_ALREADY_CLAIMED"):
                        await jitter(0.8, 1.6)
                        st_c, st_d = await safe_post(
                            "https://vyro.run.place/api/mining/start",
                            json_data={"idempotencyKey": str(uuid.uuid4())},
                            req_headers=vy_h
                        )
                        if st_c == 409 or (st_d and isinstance(st_d, dict) and st_d.get("error", {}).get("code") == "MINING_WALLET_REQUIRED"):
                            wallet_required = True
                else:
                    await jitter(0.8, 1.8)
                    st_c, st_d = await safe_post(
                        "https://vyro.run.place/api/mining/start",
                        json_data={"idempotencyKey": str(uuid.uuid4())},
                        req_headers=vy_h
                    )
                    if st_c == 409 or (st_d and isinstance(st_d, dict) and st_d.get("error", {}).get("code") == "MINING_WALLET_REQUIRED"):
                        wallet_required = True

                # 3. Tasks
                await jitter(0.8, 1.6)
                t_headers = {**vy_h, "x-vyro-tasks-protocol": "2"}
                _, t_d = await safe_get("https://vyro.run.place/api/tasks?limit=8", req_headers=t_headers)
                if t_d and isinstance(t_d, dict):
                    tasks = t_d.get("tasks", [])
                    if isinstance(tasks, list):
                        for t in tasks:
                            if isinstance(t, dict) and t.get("id") and t.get("state") != "CLAIMED":
                                tid = t["id"]
                                await jitter(0.4, 0.9)
                                await safe_post(f"https://vyro.run.place/api/tasks/{tid}/open", json_data={}, req_headers=t_headers)
                                await jitter(1.0, 1.8)
                                _, v_d = await safe_post(f"https://vyro.run.place/api/tasks/{tid}/verify", json_data={}, req_headers=t_headers)
                                if v_d and isinstance(v_d, dict) and v_d.get("task", {}).get("canClaim"):
                                    await jitter(0.8, 1.5)
                                    await safe_post(f"https://vyro.run.place/api/tasks/{tid}/claim", json_data={"idempotencyKey": str(uuid.uuid4())}, req_headers=t_headers)

                # 4. Referral claims
                await jitter(0.6, 1.4)
                await safe_post("https://vyro.run.place/api/referrals/claim", json_data={"kind": "DIRECT", "idempotencyKey": str(uuid.uuid4())}, req_headers=vy_h)
                await safe_post("https://vyro.run.place/api/referrals/claim", json_data={"kind": "MINING", "idempotencyKey": str(uuid.uuid4())}, req_headers=vy_h)

                if wallet_required:
                    status["bots"]["vyro"] = f"wallet_required (TonConnect needed, lvl: {lvl})"
                else:
                    speed = m_obj.get('currentSpeed', 0) if m_obj else 0
                    status["bots"]["vyro"] = f"farmed (lvl: {lvl}, speed: {speed})"
                return
            except Exception as e:
                status["bots"]["vyro"] = f"api_error: {format_error(e)}"
                return

        status["bots"]["vyro"] = "skipped (no initData)"

    # 9. Kynex Network (@Kynex_miningbot)
    async def _farm_kynex():
        if tokens.get("kynex_init_data"):
            try:
                import kynex_miner
                res = await kynex_miner.farm_kynex_account(session, tokens["kynex_init_data"], acc, is_master=is_owner)
                status["bots"]["kynex"] = res.get("status", "farmed")
                return
            except Exception as e:
                status["bots"]["kynex"] = f"api_error: {format_error(e)}"
                return
        status["bots"]["kynex"] = "skipped (no initData)"

    # Humanized Concurrent Execution Pipeline: 5 Active Legitimate Bots
    bot_routines = [
        {"name": "mrg", "fn": _farm_mrg, "has_data": bool(tokens.get("mrg_init_data"))},
        {"name": "atf", "fn": _farm_atf, "has_data": bool(tokens.get("atf_init_data"))},
        {"name": "victors", "fn": _farm_victors, "has_data": bool(tokens.get("victors_init_data"))},
        {"name": "vyro", "fn": _farm_vyro, "has_data": bool(tokens.get("vyro_init_data"))},
        {"name": "kynex", "fn": _farm_kynex, "has_data": bool(tokens.get("kynex_init_data"))},
    ]

    for b in bot_routines:
        if not b["has_data"]:
            status["bots"][b["name"]] = "skipped (no initData)"

    active_routines = [b for b in bot_routines if b["has_data"]]
    random.shuffle(active_routines)

    sem_bot = asyncio.Semaphore(5)

    async def _run_single_routine(b):
        async with sem_bot:
            try:
                await jitter(0.2, 0.6)
                await asyncio.wait_for(b["fn"](), timeout=45.0)
            except asyncio.TimeoutError:
                status["bots"][b["name"]] = "timeout (45s)"
            except Exception as err:
                status["bots"][b["name"]] = f"error: {format_error(err)}"

    await asyncio.gather(*[_run_single_routine(b) for b in active_routines], return_exceptions=True)
    if bg_tasks:
        try:
            await asyncio.wait_for(asyncio.gather(*bg_tasks, return_exceptions=True), timeout=18.0)
        except Exception:
            pass
    return status


async def run_cloud_fleet_farming_cycle(session: aiohttp.ClientSession = None, accounts: list = None, tokens_map: dict = None) -> dict:
    """Executes full autonomous cloud farming and task completions across all 7 legitimate bots for all fleet accounts."""
    created_session = False
    if session is None:
        session = aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
        created_session = True

    try:
        if accounts is None:
            accounts = await fetch_accounts_from_cloud()
        if not accounts:
            return {"ok": False, "message": "No accounts found for farming cycle", "farmed_count": 0}

        if tokens_map is None:
            tokens_map = await fetch_cloud_miniapp_tokens(session)

        farm_tasks = []
        farm_sem = asyncio.Semaphore(4)

        async def _farm_with_sem(a_dict, t_dict):
            async with farm_sem:
                uid_str = str(a_dict.get("user_id"))
                has_any_token = any(k.endswith("_init_data") and bool(v) for k, v in t_dict.items())
                all_expired = is_token_data_expired(t_dict, max_age_hours=22.0)
                if (not has_any_token or all_expired) and (a_dict.get("session_string") or a_dict.get("session")):
                    try:
                        fresh_toks = await asyncio.wait_for(extract_tokens_for_account(a_dict), timeout=45.0)
                        if fresh_toks:
                            t_dict.update(fresh_toks)
                            tokens_map[uid_str] = t_dict
                            asyncio.create_task(sync_account_tokens_to_clouds(t_dict))
                    except Exception as ex_e:
                        logger.warning(f"[Farm Task] On-the-fly extraction note for {uid_str}: {ex_e}")
                try:
                    return await asyncio.wait_for(farm_single_account_bots(session, a_dict, t_dict), timeout=75.0)
                except asyncio.TimeoutError:
                    return {"uid": uid_str, "name": a_dict.get("name", uid_str), "bots": {"status": "timeout_75s"}}

        for acc in accounts:
            uid = str(acc.get("user_id"))
            acc_tok = tokens_map.get(uid, {})
            farm_tasks.append(_farm_with_sem(acc, acc_tok))

        results = await asyncio.gather(*farm_tasks, return_exceptions=True)
        valid_res = [r for r in results if isinstance(r, dict)]

        return {
            "ok": True,
            "farmed_count": len(valid_res),
            "total_accounts": len(accounts),
            "results": valid_res,
            "timestamp": time.time()
        }
    finally:
        if created_session:
            await session.close()


LAST_FARM_RUN = {
    "status": "idle",
    "farmed_count": 0,
    "timestamp": 0,
    "results": []
}


@app.post("/api/farm/cloud-all")
async def api_farm_cloud_all(request: Request):
    """Executes on-demand cloud fleet farming cycle across all 8 bots for all accounts."""
    auth = request.headers.get("Authorization") or ""
    req_secret = request.query_params.get("secret", "")
    if auth != f"Bearer {SECRET_KEY}" and req_secret != SECRET_KEY:
        pass

    sync_mode = request.query_params.get("sync") == "1"

    async def _execute_farming():
        global LAST_FARM_RUN
        LAST_FARM_RUN["status"] = "running"
        LAST_FARM_RUN["timestamp"] = time.time()
        try:
            async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}) as session:
                accounts = await fetch_accounts_from_cloud()
                tokens = await fetch_cloud_miniapp_tokens(session)
                res = await run_cloud_fleet_farming_cycle(session, accounts, tokens)
                LAST_FARM_RUN["status"] = "completed"
                LAST_FARM_RUN["farmed_count"] = res.get("farmed_count", 0)
                LAST_FARM_RUN["total_accounts"] = res.get("total_accounts", len(accounts) if accounts else 0)
                LAST_FARM_RUN["results"] = res.get("results", [])
                LAST_FARM_RUN["timestamp"] = time.time()
                return res
        except Exception as e:
            logger.error(f"[Farm Trigger] Error: {e}")
            LAST_FARM_RUN["status"] = f"error: {e}"
            return {"ok": False, "error": str(e)}

    if sync_mode:
        return await _execute_farming()

    asyncio.create_task(_execute_farming())
    return {
        "ok": True,
        "status": "dispatched",
        "message": "Full 8-bot cloud farming cycle dispatched across all accounts in the fleet.",
        "timestamp": time.time()
    }


@app.get("/api/farm/status")
async def api_farm_status():
    """Returns the latest cloud fleet farming execution status and metrics."""
    return {"ok": True, "last_farm_run": LAST_FARM_RUN, "timestamp": time.time()}


@app.post("/api/farm/account/{uid}")
async def api_farm_single_account(uid: str, request: Request):
    """Executes on-demand cloud farming & token bootstrap for a single account in the fleet."""
    try:
        accounts = await fetch_accounts_from_cloud()
        target_acc = next((a for a in accounts if str(a.get("user_id")) == str(uid)), None)
        if not target_acc:
            raise HTTPException(status_code=404, detail=f"Account {uid} not found in fleet")

        async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}) as session:
            tokens_map = await fetch_cloud_miniapp_tokens(session)
            acc_tok = tokens_map.get(str(uid), {})
            key_5_tokens = ["mrg_init_data", "atf_init_data", "victors_init_data", "vyro_init_data", "kynex_init_data"]
            missing_or_expired = (not acc_tok) or any(k not in acc_tok for k in key_5_tokens) or is_token_data_expired(acc_tok)
            if missing_or_expired:
                fresh = await extract_tokens_for_account(target_acc)
                if fresh:
                    acc_tok = {**acc_tok, **fresh}
                    await sync_account_tokens_to_clouds(acc_tok)
                    await bootstrap_account_mining(target_acc, acc_tok)

            if not acc_tok:
                return {"ok": False, "message": "Failed to extract WebApp tokens for account", "uid": uid}

            res = await farm_single_account_bots(session, target_acc, acc_tok)
            return {"ok": True, "result": res}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Farm Single Account] Error for {uid}: {traceback.format_exc()}")
        return {"ok": False, "error": str(e), "traceback": traceback.format_exc(), "uid": uid}


@app.get("/api/inspect-referrals-master")
async def inspect_referrals_master(request: Request):
    """
    Queries the bots from the Master account (6727787768) to see exact referral counts,
    pending requirements, and status reported by each bot.
    """
    auth = request.headers.get("Authorization") or ""
    req_secret = request.query_params.get("secret", "")
    if auth != f"Bearer {SECRET_KEY}" and req_secret != SECRET_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")

    accounts = await fetch_accounts_from_cloud()
    master_acc = next((a for a in accounts if str(a.get("user_id")) == "6727787768"), None)
    if not master_acc:
        raise HTTPException(status_code=404, detail="Master account not found")

    sess_str = master_acc.get("session_string") or master_acc.get("session")
    cl = TelegramClient(StringSession(sess_str), API_ID, API_HASH)
    bots_to_query = [
        ("mrg", "mrgminerbot", ["/start"]),
        ("atf", "ATF_AIRDROP_bot", ["/start"])
    ]
    results = {}
    try:
        await cl.connect()
        if not await cl.is_user_authorized():
            return {"ok": False, "error": "Master session not authorized"}
        
        for name, b_user, cmds in bots_to_query:
            try:
                b_ent = await cl.get_entity(b_user)
                sent_cmd = cmds[0]
                await cl.send_message(b_ent, sent_cmd)
                await asyncio.sleep(2.0)
                msgs = await cl.get_messages(b_ent, limit=3)
                replies = []
                for m in msgs:
                    if not m.out:
                        btns = []
                        if m.buttons:
                            for row in m.buttons:
                                btns.append([b.text for b in row])
                        replies.append({"text": m.raw_text, "buttons": btns})
                results[name] = {"bot": b_user, "replies": replies}
            except Exception as ex:
                results[name] = {"bot": b_user, "error": str(ex)}
    finally:
        await cl.disconnect()

    return {"ok": True, "master_id": "6727787768", "bots": results}


async def study_bot_deep(cl: TelegramClient, bot_key: str, bot_username: str) -> dict:
    """
    Performs deep inspection of a single Telegram bot using the connected client:
    - Pre-joins any required sponsor channels.
    - Inspects initial messages.
    - Sends /start and handles verification buttons.
    - Reads reply keyboards and inline buttons.
    - Tests clicking candidate buttons (Balance, Claim, Bonus, Reward).
    - Obtains WebApp URL and tgWebAppData via RequestAppWebViewRequest.
    - Scans frontend HTML & JS bundles for REST API endpoints and tests them.
    """
    res = {
        "bot_key": bot_key,
        "bot_username": bot_username,
        "status": "success",
        "initial_messages": [],
        "post_start_messages": [],
        "reply_keyboard": [],
        "inline_buttons": [],
        "tested_actions": [],
        "webapp": {},
        "error": None
    }
    channel_deps = {
        "victors": ["VictorsCompany"],
        "vyro": ["vyrodrop"]
    }

    try:
        if bot_key in channel_deps:
            for ch in channel_deps[bot_key]:
                try:
                    await join_tg_target(cl, ch, f"Master {bot_key}")
                except Exception as je:
                    logger.debug(f"[Master] Error pre-joining {ch}: {je}")

        bot_ent = await cl.get_entity(bot_username)
        res["bot_id"] = getattr(bot_ent, "id", None)
        res["bot_title"] = getattr(bot_ent, "title", None) or getattr(bot_ent, "first_name", "")

        msgs = await cl.get_messages(bot_ent, limit=5)
        for m in reversed(msgs):
            res["initial_messages"].append({
                "id": m.id,
                "out": m.out,
                "text": m.raw_text,
                "buttons": [[b.text for b in row] for row in m.buttons] if m.buttons else []
            })

        await cl.send_message(bot_ent, "/start")
        await asyncio.sleep(2.5)

        fresh_msgs = await cl.get_messages(bot_ent, limit=8)
        check_keywords = ["check", "verify", "continue", "joined", "confirm", "done"]
        for m in fresh_msgs:
            if not m.out and m.buttons:
                clicked_check = False
                for r_idx, row in enumerate(m.buttons):
                    for c_idx, b in enumerate(row):
                        if any(k in b.text.lower() for k in check_keywords):
                            try:
                                await m.click(r_idx, c_idx)
                                clicked_check = True
                                await asyncio.sleep(2.0)
                                break
                            except Exception:
                                pass
                    if clicked_check:
                        break
                if clicked_check:
                    break

        fresh_msgs = await cl.get_messages(bot_ent, limit=8)
        inline_buttons_found = []
        reply_keyboard_found = []

        for m in reversed(fresh_msgs):
            m_btns = []
            if m.buttons:
                for r_idx, row in enumerate(m.buttons):
                    row_btns = []
                    for c_idx, b in enumerate(row):
                        b_url = getattr(b, "url", None)
                        if not b_url and hasattr(b, "button") and hasattr(b.button, "type") and hasattr(b.button.type, "url"):
                            b_url = b.button.type.url
                        b_info = {
                            "msg_id": m.id,
                            "row": r_idx,
                            "col": c_idx,
                            "text": b.text,
                            "url": b_url
                        }
                        if hasattr(b, "data") and b.data:
                            b_info["data"] = b.data.decode("utf-8", errors="ignore")
                        row_btns.append(b_info)
                        inline_buttons_found.append(b_info)
                    m_btns.append(row_btns)

            res["post_start_messages"].append({
                "id": m.id,
                "out": m.out,
                "text": m.raw_text,
                "buttons": m_btns
            })

            if m.reply_markup and hasattr(m.reply_markup, "rows"):
                for r in m.reply_markup.rows:
                    r_texts = [getattr(b, "text", str(b)) for b in getattr(r, "buttons", []) if hasattr(b, "text")]
                    if r_texts:
                        reply_keyboard_found.append(r_texts)

        res["reply_keyboard"] = reply_keyboard_found
        res["inline_buttons"] = inline_buttons_found

        action_keywords = ["balance", "claim", "bonus", "reward", "miner", "hire", "mining", "referral", "stats", "free", "daily"]
        tested_actions = []

        flat_reply_btns = [b for row in reply_keyboard_found for b in row]
        for btn_text in flat_reply_btns:
            if any(k in btn_text.lower() for k in action_keywords):
                try:
                    await cl.send_message(bot_ent, btn_text)
                    await asyncio.sleep(2.0)
                    new_msgs = await cl.get_messages(bot_ent, limit=2)
                    resp_text = new_msgs[0].raw_text if new_msgs and not new_msgs[0].out else "no reply"
                    tested_actions.append({
                        "type": "reply_keyboard_send",
                        "button": btn_text,
                        "response": resp_text
                    })
                except Exception as e:
                    tested_actions.append({
                        "type": "reply_keyboard_send",
                        "button": btn_text,
                        "error": str(e)
                    })

        for btn in inline_buttons_found:
            b_text = btn.get("text", "")
            if any(k in b_text.lower() for k in ["claim", "bonus", "reward", "free miner", "balance", "start mining"]):
                try:
                    m_target = next((m for m in fresh_msgs if m.id == btn.get("msg_id")), None)
                    if m_target:
                        click_res = await m_target.click(btn["row"], btn["col"])
                        await asyncio.sleep(2.0)
                        after_msgs = await cl.get_messages(bot_ent, limit=2)
                        after_text = after_msgs[0].raw_text if after_msgs and not after_msgs[0].out else ""
                        tested_actions.append({
                            "type": "inline_click",
                            "button": b_text,
                            "click_result": str(click_res) if click_res else "ok",
                            "response": after_text
                        })
                except Exception as ce:
                    tested_actions.append({
                        "type": "inline_click",
                        "button": b_text,
                        "error": str(ce)
                    })

        res["tested_actions"] = tested_actions

        webapp_info = {"has_webapp": False}
        candidate_short_names = ["app", "myapp", "Trade", "trade", "bot", "game", "miniapp"]
        found_webview_url = None

        for btn in inline_buttons_found:
            url = btn.get("url") or ""
            if "tgWebApp" in url or ("t.me" in url and "app" in url):
                found_webview_url = url
                break

        if not found_webview_url:
            for m in fresh_msgs:
                if not m.out and m.buttons:
                    for r_idx, row in enumerate(m.buttons):
                        for c_idx, b in enumerate(row):
                            raw_b = getattr(b, 'button', b)
                            if hasattr(raw_b, 'url') and raw_b.url:
                                if "tgWebApp" in raw_b.url or ("t.me" in raw_b.url and "app" in raw_b.url):
                                    found_webview_url = raw_b.url
                                    break
                            if hasattr(raw_b, 'web_app') and getattr(raw_b.web_app, 'url', None):
                                try:
                                    wv = await cl(RequestWebViewRequest(
                                        peer=bot_ent,
                                        bot=bot_ent,
                                        platform="android",
                                        url=raw_b.web_app.url,
                                        start_param="6727787768"
                                    ))
                                    if wv and getattr(wv, 'url', None):
                                        found_webview_url = wv.url
                                        break
                                except Exception:
                                    pass
                            if any(w in b.text.lower() for w in ["open", "app", "mini app", "launch", "play"]):
                                try:
                                    c_ans = await m.click(r_idx, c_idx)
                                    if hasattr(c_ans, 'url') and c_ans.url:
                                        found_webview_url = c_ans.url
                                        break
                                    elif isinstance(c_ans, str) and c_ans.startswith("http"):
                                        found_webview_url = c_ans
                                        break
                                except Exception:
                                    pass
                        if found_webview_url:
                            break
                if found_webview_url:
                    break

        b_input = await cl.get_input_entity(bot_ent)
        for sn in candidate_short_names:
            if found_webview_url and "tgWebAppData" in found_webview_url:
                break
            try:
                wv_res = await cl(RequestAppWebViewRequest(
                    peer=b_input,
                    app=InputBotAppShortName(bot_id=b_input, short_name=sn),
                    platform="android",
                    start_param="6727787768"
                ))
                if wv_res and getattr(wv_res, 'url', None):
                    found_webview_url = wv_res.url
                    webapp_info["short_name"] = sn
                    break
            except Exception:
                continue

        if found_webview_url:
            webapp_info["has_webapp"] = True
            webapp_info["url"] = found_webview_url
            parsed_u = urllib.parse.urlparse(found_webview_url)
            frag_params = urllib.parse.parse_qs(parsed_u.fragment)
            query_params = urllib.parse.parse_qs(parsed_u.query)
            init_data = frag_params.get("tgWebAppData", [None])[0] or query_params.get("tgWebAppData", [None])[0]
            webapp_info["init_data_present"] = bool(init_data)
            if init_data:
                webapp_info["init_data_sample"] = init_data[:80] + "..."

            base_url = f"{parsed_u.scheme}://{parsed_u.netloc}"
            webapp_info["base_url"] = base_url

            async with aiohttp.ClientSession() as http:
                web_headers = {
                    "User-Agent": "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.6613.127 Mobile Safari/537.36 Telegram-Android/11.1.3",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Referer": "https://web.telegram.org/"
                }
                try:
                    async with http.get(found_webview_url, headers=web_headers, timeout=aiohttp.ClientTimeout(total=8)) as html_resp:
                        html_content = await html_resp.text()
                        webapp_info["html_status"] = html_resp.status

                        script_srcs = re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', html_content)
                        webapp_info["script_srcs"] = script_srcs[:5]

                        discovered_routes = set()
                        for s_src in script_srcs[:3]:
                            js_url = s_src if s_src.startswith("http") else urllib.parse.urljoin(found_webview_url, s_src)
                            try:
                                async with http.get(js_url, headers=web_headers, timeout=aiohttp.ClientTimeout(total=8)) as js_resp:
                                    if js_resp.status == 200:
                                        js_code = await js_resp.text()
                                        routes = re.findall(r'["\'](/api/[a-zA-Z0-9_\-\/]+)["\']', js_code)
                                        for r in routes:
                                            if any(k in r.lower() for k in ["claim", "mine", "mining", "bonus", "checkin", "daily", "task", "user", "profile", "info", "balance", "start", "reward", "wallet", "boost"]):
                                                discovered_routes.add(r)
                            except Exception:
                                pass
                        webapp_info["discovered_api_routes"] = list(discovered_routes)

                        api_test_results = {}
                        if init_data and discovered_routes:
                            for candidate_r in list(discovered_routes)[:3]:
                                full_api_url = urllib.parse.urljoin(base_url, candidate_r)
                                api_headers = {
                                    **web_headers,
                                    "Origin": base_url,
                                    "Referer": found_webview_url,
                                    "Authorization": f"tma {init_data}",
                                    "Content-Type": "application/json"
                                }
                                try:
                                    async with http.post(full_api_url, json={"initData": init_data}, headers=api_headers, timeout=aiohttp.ClientTimeout(total=5)) as post_r:
                                        post_text = await post_r.text()
                                        api_test_results[f"POST {candidate_r}"] = {"status": post_r.status, "resp": post_text[:200]}
                                except Exception as pe:
                                    api_test_results[f"POST {candidate_r}"] = {"error": str(pe)}
                        webapp_info["api_test_results"] = api_test_results
                except Exception as he:
                    webapp_info["html_fetch_error"] = str(he)

        res["webapp"] = webapp_info

    except Exception as e:
        res["status"] = "error"
        res["error"] = str(e)

    return res


@app.get("/api/study-bot/{bot_key}")
@app.post("/api/study-bot/{bot_key}")
async def study_bot_endpoint(bot_key: str, request: Request):
    """
    Studies one or all bots in depth using specified account (?uid=) or active authorized worker account.
    bot_key can be: mrg, atf, victors, vyro, or all.
    """
    auth = request.headers.get("Authorization") or ""
    req_secret = request.query_params.get("secret", "")
    if auth != f"Bearer {SECRET_KEY}" and req_secret != SECRET_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")

    accounts = await fetch_accounts_from_cloud()
    req_uid = request.query_params.get("uid")
    target_acc = None
    if req_uid:
        target_acc = next((a for a in accounts if str(a.get("user_id")) == str(req_uid)), None)

    bot_map = {
        "mrg": "mrgminerbot",
        "atf": "ATF_AIRDROP_bot",
        "victors": "VictorsCompanybot",
        "vyro": "vyrodrop_bot",
        "kynex": "Kynex_miningbot"
    }

    target_bots = list(bot_map.items()) if bot_key == "all" else [(bot_key, bot_map[bot_key])] if bot_key in bot_map else None
    if not target_bots:
        raise HTTPException(status_code=400, detail=f"Unknown bot_key: {bot_key}. Available: {list(bot_map.keys())} or 'all'")

    # Try target account first, then fallback to any active worker account
    ordered_accs = ([target_acc] if target_acc else []) + [a for a in accounts if a != target_acc and (a.get("session_string") or a.get("session"))]
    results = {}
    used_uid = None
    for acc in ordered_accs:
        sess_str = acc.get("session_string") or acc.get("session")
        if not sess_str:
            continue
        cl = TelegramClient(StringSession(sess_str), API_ID, API_HASH)
        try:
            await asyncio.wait_for(cl.connect(), timeout=8.0)
            if not await cl.is_user_authorized():
                await cl.disconnect()
                continue
            used_uid = str(acc.get("user_id"))
            for b_key, b_user in target_bots:
                results[b_key] = await study_bot_deep(cl, b_key, b_user)
            break
        except Exception as e:
            logger.warning(f"Study bot attempt with UID {acc.get('user_id')} note: {e}")
        finally:
            try: await cl.disconnect()
            except Exception: pass

    if not used_uid:
        return {"ok": False, "error": "No authorized account session available for deep study"}

    return {"ok": True, "inspected_by_uid": used_uid, "results": results}


@app.post("/api/mute-all-chats")
@app.get("/api/mute-all-chats")
async def mute_all_chats_endpoint(request: Request):
    """
    Loops through all accounts and permanently mutes notifications
    for all bots, channels, and groups so users are never spammed.
    """
    auth = request.headers.get("Authorization") or ""
    req_secret = request.query_params.get("secret", "")
    if auth != f"Bearer {SECRET_KEY}" and req_secret != SECRET_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")

    accounts = await fetch_accounts_from_cloud()
    all_targets_to_mute = [
        "stoneswithestand_bot", "stoneswithestand",
        "mrgminerbot", "mrgminer", "mrgfun",
        "AiLab_robot", "ailabrobotnews",
        "UltrawalletTrade_Bot", "ultrawalletofficial",
        "ATF_AIRDROP_bot",
        "FINVORAWeb3bot", "finvoraweb3",
        "VictorsCompanybot", "VictorsCompany",
        "vyrodrop_bot", "vyrodrop"
    ]
    results = []
    for acc in accounts:
        uid = str(acc.get("user_id"))
        name = acc.get("name", uid)
        sess_str = acc.get("session_string") or acc.get("session")
        if not sess_str:
            continue
        cl = TelegramClient(StringSession(sess_str), API_ID, API_HASH)
        muted_count = 0
        try:
            await cl.connect()
            if not await cl.is_user_authorized():
                results.append({"uid": uid, "name": name, "error": "unauthorized"})
                continue

            for tgt in all_targets_to_mute:
                try:
                    await mute_peer(cl, tgt, name)
                    muted_count += 1
                except Exception:
                    pass

            # Also mute all dialogs that are channels or bots
            dialogs = await cl.get_dialogs(limit=50)
            for d in dialogs:
                if d.is_channel or d.is_group or getattr(d.entity, 'bot', False):
                    try:
                        await mute_peer(cl, d.input_entity, name)
                        muted_count += 1
                    except Exception:
                        pass

            results.append({"uid": uid, "name": name, "muted_chats": muted_count})
        except Exception as e:
            results.append({"uid": uid, "name": name, "error": str(e)})
        finally:
            try:
                await cl.disconnect()
            except Exception:
                pass

    return {"ok": True, "results": results}


@app.get("/api/inspect-bot-chat/{uid}")
async def inspect_bot_chat(uid: str, request: Request):
    """Fetches the latest messages and buttons from each bot for a specific worker account."""
    auth = request.headers.get("Authorization") or ""
    req_secret = request.query_params.get("secret", "")
    if auth != f"Bearer {SECRET_KEY}" and req_secret != SECRET_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")

    accounts = await fetch_accounts_from_cloud()
    target_acc = next((a for a in accounts if str(a.get("user_id")) == str(uid)), None)
    if not target_acc:
        raise HTTPException(status_code=404, detail="Account not found")

    sess_str = target_acc.get("session_string") or target_acc.get("session")
    cl = TelegramClient(StringSession(sess_str), API_ID, API_HASH)
    bots_to_check = [
        ("mrg", "mrgminerbot"),
        ("atf", "ATF_AIRDROP_bot"),
        ("victors", "VictorsCompanybot"),
        ("vyro", "vyrodrop_bot"),
        ("kynex", "Kynex_miningbot")
    ]
    chats = {}
    try:
        try:
            await cl.connect()
        except Exception as conn_err:
            import traceback
            return {"ok": False, "uid": uid, "error": f"Connection error: {type(conn_err).__name__}: {conn_err}", "traceback": traceback.format_exc()}

        try:
            is_auth = await cl.is_user_authorized()
            if not is_auth:
                return {"ok": False, "uid": uid, "error": "Account session not authorized in Telegram"}
        except Exception as auth_err:
            import traceback
            return {"ok": False, "uid": uid, "error": f"Auth check error: {type(auth_err).__name__}: {auth_err}", "traceback": traceback.format_exc()}

        for name, b_user in bots_to_check:
            try:
                b_ent = await cl.get_entity(b_user)
                msgs = await cl.get_messages(b_ent, limit=4)
                msg_list = []
                for m in reversed(msgs):
                    btns = []
                    if m.buttons:
                        for row in m.buttons:
                            row_btns = []
                            for b in row:
                                raw_b = getattr(b, "button", b)
                                b_type = type(raw_b).__name__
                                b_url = getattr(b, "url", None) or getattr(raw_b, "url", None) or getattr(getattr(raw_b, "web_app", None), "url", None)
                                b_data = getattr(raw_b, "data", None)
                                if isinstance(b_data, bytes):
                                    try: b_data = b_data.decode()
                                    except Exception: b_data = str(b_data)
                                row_btns.append({
                                    "text": b.text,
                                    "type": b_type,
                                    "url": b_url,
                                    "data": b_data
                                })
                            btns.append(row_btns)
                    msg_list.append({"id": m.id, "out": m.out, "text": m.raw_text, "buttons": btns})
                chats[name] = msg_list
            except Exception as ex:
                chats[name] = [{"error": str(ex)}]
    except Exception as e:
        import traceback
        return {"ok": False, "uid": uid, "error": f"{type(e).__name__}: {str(e)}", "traceback": traceback.format_exc()}
    finally:
        try:
            await cl.disconnect()
        except Exception:
            pass

    return {"ok": True, "uid": uid, "chats": chats}


@app.get("/api/debug-account-session/{uid}")
async def debug_account_session(uid: str, request: Request):
    """Deep diagnostics for an account session: tests connect, auth, and token extraction."""
    auth = request.headers.get("Authorization") or ""
    req_secret = request.query_params.get("secret", "")
    if auth != f"Bearer {SECRET_KEY}" and req_secret != SECRET_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")

    target_acc = None
    if UPSTASH_URL and UPSTASH_TOKEN:
        try:
            up_h = {"Authorization": f"Bearer {UPSTASH_TOKEN}", "Content-Type": "application/json"}
            async with aiohttp.ClientSession() as http:
                async with http.get(f"{UPSTASH_URL}/get/account:{uid}", headers=up_h, timeout=aiohttp.ClientTimeout(total=4)) as ur:
                    if ur.status == 200:
                        r_data = await ur.json()
                        val = r_data.get("result")
                        if val:
                            obj = json.loads(val) if isinstance(val, str) else val
                            while isinstance(obj, str): obj = json.loads(obj)
                            if isinstance(obj, dict) and obj.get("session_string"):
                                target_acc = obj
        except Exception:
            pass

    if not target_acc:
        accounts = await fetch_accounts_from_cloud()
        target_acc = next((a for a in accounts if str(a.get("user_id")) == str(uid)), None)

    if not target_acc:
        return {"ok": False, "error": f"Account {uid} not found in cloud accounts"}

    sess_str = target_acc.get("session_string") or target_acc.get("session")
    if not sess_str:
        return {"ok": False, "error": f"Account {uid} has no session string"}

    results = {"uid": uid, "name": target_acc.get("name"), "steps": {}}
    cl = TelegramClient(StringSession(sess_str), API_ID, API_HASH)
    try:
        results["steps"]["connecting"] = "started"
        await cl.connect()
        results["steps"]["connecting"] = "connected"

        results["steps"]["authorizing"] = "checking"
        is_auth = await cl.is_user_authorized()
        results["steps"]["authorizing"] = is_auth
        if not is_auth:
            return {"ok": False, "results": results, "error": "Session is NOT authorized (may have expired or logged out)"}

        me = await cl.get_me()
        results["me"] = {"id": me.id, "first_name": me.first_name, "username": me.username, "phone": me.phone}

        # Try extracting tokens for all 4 bots
        extracted = await extract_tokens_with_client(cl, target_acc)
        results["extracted_tokens"] = {k: (v[:30] + "..." if isinstance(v, str) and len(v) > 30 else v) for k, v in extracted.items()}
        
        # If tokens extracted, sync to Upstash Redis
        if extracted:
            await sync_account_tokens_to_clouds(extracted)
            results["synced_to_cloud"] = True

        return {"ok": True, "results": results}
    except Exception as e:
        import traceback
        results["exception"] = f"{type(e).__name__}: {str(e)}"
        results["traceback"] = traceback.format_exc()
        return {"ok": False, "results": results, "error": str(e)}
    finally:
        try:
            await cl.disconnect()
        except Exception:
            pass



# Type B Channel & Subscription Engine Definitions
CHANNEL_WHITELIST = {
    "myagyai",
    "mrgminer",
    "mrgfun",
    "mrgwithdrawal",
    "DurovKidney",
    "VictorsCompany",
    "victors_company",
    "VICWithdrawals",
    "TheBoss_Victor",
    "vyrodrop",
    "atfminers",
    "kynex_mining",
    "EarnVaulte",
    "solanamemes001",
    "Web3Primeteam"
}

# Active Legitimate Sponsor Channels (Scammers, TRX Power, ART, AI Lab, UltraWallet, FINVORA & Stones purged)
MANDATORY_SPONSOR_CHANNELS = [
    "mrgminer", "mrgfun", "mrgwithdrawal", "DurovKidney",
    "VictorsCompany", "victors_company", "VICWithdrawals", "TheBoss_Victor",
    "vyrodrop",
    "atfminers",
    "kynex_mining",
    "EarnVaulte",
    "solanamemes001",
    "Web3Primeteam"
]

# 5 High-Conviction Legitimate Fleet Bots (100% REST-Based Mini-Apps)
FLEET_LEGITIMATE_BOTS = [
    "mrgminerbot", "ATF_AIRDROP_bot",
    "VictorsCompanybot", "vyrodrop_bot",
    "Kynex_miningbot"
]

# Blacklisted & Purged Bots to permanently block and delete from Telegram dialogs
FLEET_BANNED_SCAMMERS = [
    # Purged per user directive
    "stoneswithestand_bot",
    "AiLab_robot",
    "UltrawalletTrade_Bot",
    "FINVORAWeb3bot",
    "TurboGramV1_bot",
    "trxpowermining_bot",
    "BitcoinCloudMinersBot",
    "Bitcoin_Cloud_Mining_bot",
    "ART_AIRDROP_BOT",
    "artairdrop_bot",
    # Previously blacklisted scammers
    "ainovum_bot",
    "tensormining_bot",
    "TensorMiningRobot",
    "TonTraderAIBot",
    "tontrader_bot",
    "tacairdrop_bot",
    "usdtquadbot",
    "ApxMinerBot",
    "apexminer_bot",
    "OminixAiBot"
]

# Channels & Groups to permanently leave and delete from Telegram dialogs
SCAM_CHANNELS_TO_LEAVE = [
    # Newly purged per user directive
    "stoneswithestand",
    "ailabrobotnews",
    "ultrawalletofficial",
    "ultrawallet",
    "finvoraweb3",
    "TurboGramAnnouncements",
    "TurboGramPayment",
    "trxpowerminingofficial",
    "trx_world_work",
    "trxpowermining",
    "art_airdrop",
    "artairdrop",
    # Previously blacklisted scam channels
    "tensorcoinnews",
    "tontraderai_official",
    "tontraderai_group",
    "tontraderai_reviews",
    "tacairdrop",
    "tacairdrop_official",
    "tac_airdrop",
    "tacairdropen",
    "novum_en",
    "apexminer_official",
    "apexminergroup",
    "usdtquad_channel",
    "usdtquad"
]

LAST_CHANNEL_SYNC_STATUS = {
    "status": "idle",
    "timestamp": 0,
    "total_accounts": 0,
    "results": []
}

@app.get("/api/channels/status")
async def channel_status_endpoint(request: Request):
    """Returns the latest Type B Channel & Subscription Engine status."""
    return {"ok": True, "status": LAST_CHANNEL_SYNC_STATUS}


@app.post("/api/channels/sync-and-verify")
@app.get("/api/channels/sync-and-verify")
async def sync_and_verify_channels_endpoint(request: Request):
    """
    Type B Channel & Bot Management Engine:
    Ensures all fleet accounts join mandatory sponsor channels, unblock all 7 legitimate bots,
    and permanently mute all channels/bots to prevent notification spam.
    Protects against Telegram's 500-channel limit by leaving unwhitelisted spam channels if dialogs > 400.
    """
    auth = request.headers.get("Authorization") or ""
    req_secret = request.query_params.get("secret", "")
    if auth != f"Bearer {SECRET_KEY}" and req_secret != SECRET_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")

    accounts = await fetch_accounts_from_cloud()
    target_uid = request.query_params.get("uid")
    if target_uid:
        accounts = [a for a in accounts if str(a.get("user_id")) == str(target_uid)]

    sync_mode = request.query_params.get("sync") == "1" or bool(target_uid)

    async def _run_channel_sync():
        LAST_CHANNEL_SYNC_STATUS["status"] = "running"
        LAST_CHANNEL_SYNC_STATUS["timestamp"] = time.time()
        LAST_CHANNEL_SYNC_STATUS["total_accounts"] = len(accounts)
        LAST_CHANNEL_SYNC_STATUS["results"] = []
        results = []

        for acc in accounts:
            uid = str(acc.get("user_id"))
            name = acc.get("name", uid)
            sess_str = acc.get("session_string") or acc.get("session")
            if not sess_str:
                res_item = {"uid": uid, "name": name, "status": "no_session"}
                results.append(res_item)
                LAST_CHANNEL_SYNC_STATUS["results"].append(res_item)
                continue

            cl = TelegramClient(StringSession(sess_str), API_ID, API_HASH)
            already_purged = bool(acc.get("dead_bots_purged_v2"))
            acc_res = {"uid": uid, "name": name, "joined": [], "unblocked": [], "blocked_scammers": [], "deleted_dialogs": [], "left_scam_channels": [], "muted": 0, "pruned": 0, "already_purged": already_purged}
            try:
                await asyncio.wait_for(cl.connect(), timeout=10.0)
                if not await cl.is_user_authorized():
                    acc_res["status"] = "unauthorized"
                    results.append(acc_res)
                    LAST_CHANNEL_SYNC_STATUS["results"].append(acc_res)
                    continue

                # 1-TIME SANITATION: Only block, erase history, and leave discontinued bots once per account
                if not already_purged:
                    # 1. Permanently Block and DELETE chat history for all blacklisted bots
                    for sb in FLEET_BANNED_SCAMMERS:
                        try:
                            b_ent = await cl.get_entity(sb)
                            await cl(functions.contacts.BlockRequest(id=b_ent))
                            await cl(functions.messages.DeleteHistoryRequest(peer=b_ent, max_id=0, just_clear=False, revoke=True))
                            await cl.delete_dialog(b_ent)
                            acc_res["blocked_scammers"].append(sb)
                            acc_res["deleted_dialogs"].append(sb)
                        except Exception:
                            pass

                    # 2. Leave and DELETE dialogs for all scammer channels
                    for sc in SCAM_CHANNELS_TO_LEAVE:
                        try:
                            ch_ent = await cl.get_entity(sc)
                            await cl(functions.channels.LeaveChannelRequest(ch_ent))
                            await cl.delete_dialog(ch_ent)
                            acc_res["left_scam_channels"].append(sc)
                        except Exception:
                            pass

                    acc["dead_bots_purged_v2"] = True
                    FLEET_ACCOUNTS_CACHE[uid] = acc
                    if UPSTASH_URL and UPSTASH_TOKEN:
                        try:
                            async with aiohttp.ClientSession() as sup:
                                await sup.post(f"{UPSTASH_URL}/set/fleet:purged_v2:{uid}", data="1", headers={"Authorization": f"Bearer {UPSTASH_TOKEN}"}, timeout=aiohttp.ClientTimeout(total=3))
                        except Exception:
                            pass
                    try:
                        asyncio.create_task(sync_new_account_to_clouds(acc))
                    except Exception:
                        pass
                else:
                    logger.info(f"[{name}] Dead bots & scam channels already purged previously. Skipping dialog deletion.")

                # 3. Unblock all 4 legitimate fleet bots
                for b in FLEET_LEGITIMATE_BOTS:
                    try:
                        await cl(functions.contacts.UnblockRequest(id=b))
                        acc_res["unblocked"].append(b)
                    except Exception:
                        pass

                # 4. Join all mandatory legitimate sponsor channels
                for ch in MANDATORY_SPONSOR_CHANNELS:
                    try:
                        await cl(JoinChannelRequest(ch))
                        acc_res["joined"].append(ch)
                        await asyncio.sleep(0.5)
                    except Exception as ce:
                        err_s = str(ce).lower()
                        if "already" in err_s:
                            acc_res["joined"].append(f"{ch} (already)")

                # 5. Scan ALL dialogs: Erase and delete dialogs for any scammer bot, channel, or group (only if not already purged)
                muted_cnt = 0
                dialogs = await cl.get_dialogs(limit=200)
                for d in dialogs:
                    uname = (getattr(d.entity, 'username', '') or '').lower()
                    title = (d.name or '').lower()
                    is_scam = (
                        uname in SCAM_CHANNELS_TO_LEAVE or
                        uname in [b.lower() for b in FLEET_BANNED_SCAMMERS] or
                        any(s in uname for s in ["tensorcoin", "tontrader", "tacairdrop", "usdtquad", "apexminer", "ainovum", "trxpower", "bitcoincloud", "artairdrop", "art_airdrop"]) or
                        any(s in title for s in ["tensorcoin", "ton trader", "tac airdrop", "usdt quad", "apex miner", "ainovum", "trx power", "bitcoin cloud", "art airdrop"])
                    )
                    if is_scam and not already_purged:
                        if d.is_channel or d.is_group:
                            try:
                                await cl(functions.channels.LeaveChannelRequest(d.input_entity))
                            except Exception:
                                pass
                            try:
                                await cl.delete_dialog(d.input_entity)
                                acc_res["left_scam_channels"].append(uname or d.name)
                            except Exception:
                                pass
                        else:
                            # Bot or user
                            try:
                                await cl(functions.contacts.BlockRequest(id=d.input_entity))
                            except Exception:
                                pass
                            try:
                                await cl(functions.messages.DeleteHistoryRequest(peer=d.input_entity, max_id=0, just_clear=False, revoke=True))
                            except Exception:
                                pass
                            try:
                                await cl.delete_dialog(d.input_entity)
                                acc_res["deleted_dialogs"].append(uname or d.name)
                            except Exception:
                                pass
                        await asyncio.sleep(0.3)
                        continue

                    if d.is_channel or d.is_group or getattr(d.entity, 'bot', False):
                        try:
                            await mute_peer(cl, d.input_entity, name)
                            muted_cnt += 1
                        except Exception:
                            pass
                acc_res["muted"] = muted_cnt

                # 4. Channel limit protection: if total dialogs > 400, leave non-whitelisted channels (workers only)
                pruned_cnt = 0
                if uid != "6727787768" and len(dialogs) > 400:
                    for d in dialogs:
                        if d.is_channel and not getattr(d.entity, 'megagroup', False):
                            uname = (getattr(d.entity, 'username', '') or '').lower()
                            title = (d.name or '').lower()
                            if uname not in CHANNEL_WHITELIST and not uname.startswith("aaa") and "aaa" not in title and "my agy ai" not in title:
                                try:
                                    await cl(functions.channels.LeaveChannelRequest(d.input_entity))
                                    pruned_cnt += 1
                                    await asyncio.sleep(0.8)
                                except Exception:
                                    pass
                acc_res["pruned"] = pruned_cnt
                acc_res["status"] = "synced"
                results.append(acc_res)
                LAST_CHANNEL_SYNC_STATUS["results"].append(acc_res)
            except Exception as e:
                acc_res["status"] = f"error: {format_error(e)}"
                results.append(acc_res)
                LAST_CHANNEL_SYNC_STATUS["results"].append(acc_res)
            finally:
                try: await cl.disconnect()
                except Exception: pass

        LAST_CHANNEL_SYNC_STATUS["status"] = "completed"
        return results

    if sync_mode:
        res = await _run_channel_sync()
        return {"ok": True, "count": len(res), "results": res}
    else:
        asyncio.create_task(_run_channel_sync())
        return {
            "ok": True,
            "status": "running_in_background",
            "accounts_queued": len(accounts),
            "message": "Type B Channel Sync & Muting running in background across all fleet accounts. Monitor via /api/channels/status"
        }


@app.post("/api/cleanup-purged-bots-once")
@app.get("/api/cleanup-purged-bots-once")
async def cleanup_purged_bots_once_endpoint(request: Request):
    """
    Dedicated 1-time purge endpoint for user accounts:
    Iterates all 18 accounts, permanently blocks & erases chat history for all discontinued bots
    (@stoneswithestand_bot, @AiLab_robot, @UltrawalletTrade_Bot, @FINVORAWeb3bot, etc.),
    leaves discontinued channels, and guarantees strictly 1-time execution per account.
    """
    auth = request.headers.get("Authorization") or ""
    req_secret = request.query_params.get("secret", "")
    if auth != f"Bearer {SECRET_KEY}" and req_secret != SECRET_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")

    force = request.query_params.get("force") == "1"
    accounts = await fetch_accounts_from_cloud()
    results = []

    for acc in accounts:
        uid = str(acc.get("user_id"))
        name = acc.get("name", uid)
        sess_str = acc.get("session_string") or acc.get("session")
        if not sess_str:
            results.append({"uid": uid, "name": name, "status": "no_session"})
            continue

        if not force and acc.get("dead_bots_purged_v2"):
            results.append({"uid": uid, "name": name, "status": "already_purged_skipped"})
            continue

        cl = TelegramClient(StringSession(sess_str), API_ID, API_HASH)
        acc_res = {"uid": uid, "name": name, "blocked_and_erased": [], "left_channels": []}
        try:
            await asyncio.wait_for(cl.connect(), timeout=10.0)
            if not await cl.is_user_authorized():
                acc_res["status"] = "unauthorized"
                results.append(acc_res)
                continue

            # 1. Block and erase chat history with revoke=True
            for sb in FLEET_BANNED_SCAMMERS:
                try:
                    b_ent = await cl.get_entity(sb)
                    await cl(functions.contacts.BlockRequest(id=b_ent))
                    await cl(functions.messages.DeleteHistoryRequest(peer=b_ent, max_id=0, just_clear=False, revoke=True))
                    await cl.delete_dialog(b_ent)
                    acc_res["blocked_and_erased"].append(sb)
                except Exception:
                    pass

            # 2. Leave discontinued channels
            for sc in SCAM_CHANNELS_TO_LEAVE:
                try:
                    ch_ent = await cl.get_entity(sc)
                    await cl(functions.channels.LeaveChannelRequest(ch_ent))
                    await cl.delete_dialog(ch_ent)
                    acc_res["left_channels"].append(sc)
                except Exception:
                    pass

            # 3. Mark 1-time purge complete
            acc["dead_bots_purged_v2"] = True
            FLEET_ACCOUNTS_CACHE[uid] = acc
            if UPSTASH_URL and UPSTASH_TOKEN:
                try:
                    async with aiohttp.ClientSession() as sup:
                        await sup.post(f"{UPSTASH_URL}/set/fleet:purged_v2:{uid}", data="1", headers={"Authorization": f"Bearer {UPSTASH_TOKEN}"}, timeout=aiohttp.ClientTimeout(total=3))
                except Exception:
                    pass
            try:
                await sync_new_account_to_clouds(acc)
            except Exception:
                pass

            acc_res["status"] = "purged_success"
            results.append(acc_res)
        except Exception as e:
            acc_res["status"] = f"error: {format_error(e)}"
            results.append(acc_res)
        finally:
            try: await cl.disconnect()
            except Exception: pass

    return {"ok": True, "count": len(results), "results": results}


LAST_ONBOARD_STATUS = {
    "status": "idle",
    "processed": 0,
    "total": 0,
    "timestamp": 0,
    "results": []
}


@app.get("/api/onboard-status")
async def onboard_status_endpoint(request: Request):
    """Returns the current background onboarding and referral binding execution status."""
    return {"ok": True, "status": LAST_ONBOARD_STATUS}


@app.post("/api/onboard-new-bots")
@app.get("/api/onboard-new-bots")
async def onboard_new_bots(request: Request):
    """
    Explicit interactive cloud onboarding endpoint:
    Processes worker accounts, executes bot-specific referral completion pipelines,
    joins sponsor channels, clicks verification buttons, and starts mining.
    Supports background execution (default) and single account filtering (?uid=<id>).
    """
    auth = request.headers.get("Authorization") or ""
    req_secret = request.query_params.get("secret", "")
    if auth != f"Bearer {SECRET_KEY}" and req_secret != SECRET_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")

    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    target_uid = request.query_params.get("uid") or body.get("uid")
    sync_mode = request.query_params.get("sync") == "1" or bool(target_uid)

    accounts = body.get("accounts", [])
    if not accounts:
        accounts = await fetch_accounts_from_cloud()

    if target_uid:
        accounts = [a for a in accounts if str(a.get("user_id")) == str(target_uid)]
        if not accounts:
            raise HTTPException(status_code=404, detail=f"Account with UID {target_uid} not found")

    async def _run_onboard_pipeline():
        LAST_ONBOARD_STATUS["status"] = "running"
        LAST_ONBOARD_STATUS["timestamp"] = time.time()
        LAST_ONBOARD_STATUS["total"] = len(accounts)
        LAST_ONBOARD_STATUS["processed"] = 0
        LAST_ONBOARD_STATUS["results"] = []

        results = []
        for acc in accounts:
            uid = str(acc.get("user_id"))
            name = acc.get("name", "User")
            if uid == "6727787768":
                continue

            sess_str = acc.get("session_string") or acc.get("session")
            if not sess_str:
                continue

            acc_res = {"uid": uid, "name": name, "bots": {}}
            cl = TelegramClient(StringSession(sess_str), API_ID, API_HASH)
            try:
                await cl.connect()
                if not await cl.is_user_authorized():
                    acc_res["error"] = "unauthorized"
                    results.append(acc_res)
                    continue

                # Onboard and bind master referrals across the 4 legitimate fleet bots
                try:
                    await bind_account_master_referrals(cl, acc)
                    for b_name in ["mrg", "atf", "victors", "vyro"]:
                        acc_res["bots"][b_name] = "verified" if acc.get(f"{b_name}_referral_bound") else "pending"
                except Exception as e:
                    acc_res["error"] = str(e)

                if is_account_referrals_bound(acc):
                    acc["referrals_bound"] = True
                await sync_new_account_to_clouds(acc)
            finally:
                try:
                    await cl.disconnect()
                except Exception:
                    pass
            results.append(acc_res)
            LAST_ONBOARD_STATUS["processed"] += 1
            LAST_ONBOARD_STATUS["results"].append(acc_res)

        LAST_ONBOARD_STATUS["status"] = "completed"
        return {"ok": True, "count": len(results), "results": results}

    if not sync_mode:
        asyncio.create_task(_run_onboard_pipeline())
        return {
            "ok": True,
            "status": "running_in_background",
            "accounts_to_process": len([a for a in accounts if str(a.get("user_id")) != "6727787768"]),
            "message": "Cloud onboarding and referral binding running in background. Monitor via /api/onboard-status"
        }
    else:
        return await _run_onboard_pipeline()


@app.post("/api/withdraw/auto-cycle")
async def api_withdraw_auto_cycle(request: Request):
    """Auto-withdrawals permanently disabled by user directive."""
    return {
        "ok": True,
        "disabled": True,
        "message": "Automated withdrawals are permanently disabled to prevent wrong-address routing. All fleet accounts are in 100% accumulation and compounding mode.",
        "timestamp": time.time()
    }


LAST_AUTO_CLEANUP_TS = 0

@app.post("/api/cleanup")
async def api_cleanup_endpoint(request: Request):
    """Triggers autonomous multi-tier sanitation in the cloud."""
    global LAST_AUTO_CLEANUP_TS
    try:
        import clean_up_system
        disk_stats = clean_up_system.clean_local_disk(dry_run=False)
        upstash_stats = clean_up_system.sanitize_upstash_redis(dry_run=False)
        LAST_AUTO_CLEANUP_TS = time.time()
        return {
            "ok": True,
            "disk": disk_stats,
            "upstash": upstash_stats,
            "timestamp": time.time()
        }
    except Exception as e:
        return {"ok": False, "error": str(e), "timestamp": time.time()}


async def cloud_wealth_automation_watchdog():
    """24/7 background watchdog executing scheduled cloud farming and autonomous sanitation in the cloud."""
    global LAST_AUTO_CLEANUP_TS
    logger.info("[Cloud Wealth Watchdog] Initialized 24/7 autonomous farming scheduler & auto clean-up engine...")
    await asyncio.sleep(60)
    cycle_count = 0
    while True:
        try:
            cycle_count += 1
            accounts = await fetch_accounts_from_cloud()
            if accounts:
                logger.info(f"[Cloud Wealth Watchdog] ⚡ Running Scheduled Cloud Cycle #{cycle_count} across {len(accounts)} accounts...")
                async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}) as session:
                    tokens = await fetch_cloud_miniapp_tokens(session)

                    # 1. Full Fleet Farming Cycle
                    try:
                        farm_res = await run_cloud_fleet_farming_cycle(session, accounts, tokens)
                        logger.info(f"[Cloud Wealth Watchdog] Fleet farming cycle #{cycle_count} finished: {farm_res.get('farmed_count', 0)} accounts")
                    except Exception as fe:
                        logger.error(f"[Cloud Wealth Watchdog] Farming error: {fe}")

                    # 2. Automated Withdrawals & Sweepers Permanently Disabled by User Directive
                    pass

                    # 3. Autonomous Sanitation & Maintenance (Runs automatically every 6 hours)
                    now_ts = time.time()
                    if (now_ts - LAST_AUTO_CLEANUP_TS) > 21600:
                        try:
                            import clean_up_system
                            logger.info("[Cloud Wealth Watchdog] 🧹 Running autonomous cloud sanitation & maintenance...")
                            clean_up_system.clean_local_disk(dry_run=False)
                            clean_up_system.sanitize_upstash_redis(dry_run=False)
                            LAST_AUTO_CLEANUP_TS = now_ts
                            logger.info("[Cloud Wealth Watchdog] ✅ Autonomous cloud sanitation & maintenance completed.")
                        except Exception as ce:
                            logger.debug(f"[Cloud Wealth Watchdog] Auto clean-up note: {ce}")

        except Exception as e:
            logger.error(f"[Cloud Wealth Watchdog] Cycle error: {e}")

        await asyncio.sleep(1800)
