"""
bot_registry.py
=============================================================================
SINGLE SOURCE OF TRUTH (SSOT) PLUG-AND-FARM BOT REGISTRY FOR MY AGY AI FLEET
=============================================================================
Defines all active legitimate fleet bots, their referral codes, WebApp URLs,
mandatory sponsor channels, and API farming parameters.

Adding ANY new bot to the fleet in the future requires ONLY adding one entry here!
The cloud token refresher, referral binder, and 24/7 cloud farming engine
automatically pick up new bots from this registry with ZERO per-account manual work.
"""

from typing import Dict, List, Any

ACTIVE_BOTS: Dict[str, Dict[str, Any]] = {
    "mrg": {
        "id": "mrg",
        "name": "MRG Miner",
        "bot_username": "mrgminerbot",
        "master_ref_code": "ref_IRN1G3XD",
        "app_url": "https://app.mrgtoken.xyz/",
        "token_key": "mrg_init_data",
        "short_names": ["app", "miniapp"],
        "api_base": "https://api.mrgtoken.xyz",
        "sponsor_channels": ["mrgminer", "mrgwithdrawal", "DurovKidney"],
        "requires_turnstile": True,
        "is_active": True,
    },
    "atf": {
        "id": "atf",
        "name": "ATF Miner",
        "bot_username": "ATF_AIRDROP_bot",
        "master_ref_code": "6727787768",
        "app_url": "https://atfminers.asloni.online/miner/index.html?entry=bot_start",
        "token_key": "atf_init_data",
        "short_names": ["app", "miner", "play"],
        "api_base": "https://atfminers.asloni.online/api",
        "sponsor_channels": ["atfminers"],
        "requires_turnstile": False,
        "is_active": True,
    },
    "victors": {
        "id": "victors",
        "name": "Victor's Company",
        "bot_username": "VictorsCompanybot",
        "master_ref_code": "ref_A20AA96F18",
        "app_url": "https://app.victors.company/",
        "token_key": "victors_init_data",
        "short_names": ["app", "play"],
        "api_base": "https://app.victors.company/api",
        "sponsor_channels": ["VictorsCompany", "victors_company", "VICWithdrawals", "TheBoss_Victor"],
        "requires_turnstile": True,
        "is_active": True,
    },
    "vyro": {
        "id": "vyro",
        "name": "VyroDrop",
        "bot_username": "vyrodrop_bot",
        "master_ref_code": "ref_myFjrqqE4WN_",
        "app_url": "https://vyro.run.place/",
        "token_key": "vyro_init_data",
        "short_names": ["app", "vyro", "play", "mine"],
        "api_base": "https://vyro.run.place/api",
        "sponsor_channels": ["vyrodrop"],
        "requires_turnstile": True,
        "is_active": True,
    },
    "kynex": {
        "id": "kynex",
        "name": "Kynex Network",
        "bot_username": "Kynex_miningbot",
        "master_ref_code": "6727787768",
        "app_url": "https://kynex.top/telegram-auth.html",
        "token_key": "kynex_init_data",
        "short_names": ["App", "app"],
        "api_base": "https://us-central1-keynex-e9511.cloudfunctions.net",
        "sponsor_channels": ["kynex_mining", "EarnVaulte", "solanamemes001", "Web3Primeteam"],
        "requires_turnstile": False,
        "is_active": True,
    },
}

def get_active_bots() -> Dict[str, Dict[str, Any]]:
    """Returns all active bots in the registry."""
    return {k: v for k, v in ACTIVE_BOTS.items() if v.get("is_active", True)}

def get_all_sponsor_channels() -> List[str]:
    """Returns a deduplicated list of all mandatory sponsor channels across all active bots."""
    channels = set()
    for b in ACTIVE_BOTS.values():
        if b.get("is_active", True):
            channels.update(b.get("sponsor_channels", []))
    return sorted(list(channels))

def get_token_keys() -> List[str]:
    """Returns the list of token keys (e.g. ['mrg_init_data', ...]) for active bots."""
    return [b["token_key"] for b in ACTIVE_BOTS.values() if b.get("is_active", True)]
