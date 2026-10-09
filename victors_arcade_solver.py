#!/usr/bin/env python3
"""
victors_arcade_solver.py
Autonomous Solver for Victor's Company (@VictorsCompanybot) Deep Mine Arcade Minigame (/api/arcade/mine/*).

Mathematical & Game-Engine Strategy:
- Tool: Shovel (Cost: 25 VIC, Energy: 25, Hearts: 3, Power: 1).
- Safe Rows: Rows 0 and 1 have Ue.safeRows = 2 (strictly ZERO hazards, 0% bust chance).
- Reachability: Row 0 is directly reachable; Row 1 is reachable once the tile directly above is opened.
- Optimization: Prioritizes sparkle tiles (hint & 1 != 0) on soft dirt (cost = 1) over boulders (cost = 2).
- Cash Out: Safely calls /api/arcade/mine/end before energy runs out or when bag hits cap (~28.8 VIC),
  ensuring 100% bag retention + 90% energy refund with zero risk of heart loss.
"""

import os
import sys
import json
import time
import asyncio
import aiohttp
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("victors_arcade")

VICTORS_API = "https://server.victors.company/api"
VICTORS_ORIGIN = "https://app.victors.company"


async def solve_deep_mine_expeditions(session: aiohttp.ClientSession, headers: dict, account_name: str, max_runs: int = 3) -> dict:
    """
    Executes safe Deep Mine expeditions for an authenticated account.
    Returns summary of games played and balance changes.
    """
    stats = {"runs_played": 0, "net_vic": 0.0, "total_paid": 0.0, "final_balance": None}

    # 1. Fetch current user state & balance
    try:
        async with session.get(f"{VICTORS_API}/me", headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status != 200:
                logger.warning(f"[{account_name}] /me returned HTTP {resp.status}")
                return stats
            me_data = await resp.json()
            user = me_data.get("state", {}).get("user", {})
            balance = user.get("inAppBalance", 0.0)
            stats["final_balance"] = balance
    except Exception as e:
        logger.error(f"[{account_name}] Failed to fetch /me: {e}")
        return stats

    for run_idx in range(max_runs):
        # 2. Check arcade status
        try:
            async with session.get(f"{VICTORS_API}/arcade", headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    break
                arc_data = await resp.json()
        except Exception as e:
            logger.error(f"[{account_name}] Failed to check arcade: {e}")
            break

        active_run = arc_data.get("mine")
        games = {g.get("id"): g for g in arc_data.get("games", []) if isinstance(g, dict)}
        mine_game = games.get("mine")
        plays_left = mine_game.get("playsLeft", 0) if mine_game else 0

        # Check eligibility
        if not active_run:
            if plays_left <= 0:
                logger.info(f"[{account_name}] 🎮 Deep Mine: No plays left today ({plays_left}/10).")
                break
            if balance < 25.0:
                logger.info(f"[{account_name}] 🎮 Deep Mine: Balance ({balance:.2f} VIC) < 25 VIC shovel cost. Skipping.")
                break

            # Start new expedition with shovel
            try:
                start_payload = {"tool": "shovel", "items": {}}
                async with session.post(f"{VICTORS_API}/arcade/mine/start", json=start_payload, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    start_data = await resp.json()
                    if resp.status != 200 or not start_data.get("success"):
                        err_msg = start_data.get("error", f"HTTP {resp.status}")
                        logger.warning(f"[{account_name}] 🎮 Deep Mine start failed: {err_msg}")
                        break
                    active_run = start_data.get("run")
                    balance = max(0.0, balance - 25.0)
                    logger.info(f"[{account_name}] 🎮 Expedition #{run_idx + 1} started! Shovel equipped (-25 VIC).")
            except Exception as e:
                logger.error(f"[{account_name}] Error starting expedition: {e}")
                break

        if not active_run or active_run.get("status") != "active":
            logger.warning(f"[{account_name}] No active expedition to play.")
            break

        # 3. Autonomous Digging Loop (Rows 0 & 1 only: strictly 0 hazards)
        run_state = active_run
        grid_w = 9
        dig_count = 0

        while run_state.get("status") == "active":
            open_str = run_state.get("open", "0" * 360)
            rock_str = run_state.get("rock", "0" * 360)
            hint_str = run_state.get("hint", "0" * 360)
            energy = run_state.get("energy", 0)
            bag = run_state.get("bag", 0.0)
            hearts = run_state.get("hearts", 3)

            # Cash out conditions:
            # - Energy <= 1 (can't dig further soft tiles)
            # - Hearts <= 1 (safety cushion, though rows 0-1 have 0 hazards)
            # - Bag >= 28.5 VIC (bag cap reached bp(25) = 28.75)
            if energy <= 1 or hearts <= 1 or bag >= 28.5:
                logger.info(f"[{account_name}] 🎮 Ready to cash out: Energy={energy}, Bag={bag:.1f} VIC, Hearts={hearts}")
                break

            # Find all reachable candidate tiles in rows 0 and 1
            candidates = []
            for y in range(2):  # Only safeRows: y=0, y=1
                for x in range(grid_w):
                    idx = y * grid_w + x
                    if idx >= len(open_str) or open_str[idx] == "1":
                        continue  # Already opened

                    # Reachability check:
                    # y == 0 is reachable from surface
                    # y == 1 is reachable if tile above (x, 0) is opened
                    if y == 1 and (open_str[x] != "1"):
                        continue

                    is_rock = (idx < len(rock_str) and rock_str[idx] == "1")
                    cost = 2 if is_rock else 1
                    if energy < cost:
                        continue

                    # Hint evaluation: bit 0 is sparkle (loot indicator)
                    hint_char = hint_str[idx] if idx < len(hint_str) else "0"
                    hint_val = int(hint_char) if hint_char.isdigit() else 0
                    has_sparkle = bool(hint_val & 1)

                    # Score priority:
                    # Sparkle soft dirt: 100
                    # Sparkle rock: 75
                    # Plain soft dirt: 50
                    # Plain rock: 20
                    priority = (100 if has_sparkle else 50) - (25 if is_rock else 0)
                    candidates.append({"x": x, "y": y, "cost": cost, "priority": priority, "sparkle": has_sparkle, "rock": is_rock})

            if not candidates:
                logger.info(f"[{account_name}] 🎮 All safe row tiles exhausted. Cashing out bag.")
                break

            # Pick highest priority candidate
            candidates.sort(key=lambda c: c["priority"], reverse=True)
            chosen = candidates[0]

            # Dig tile
            try:
                await asyncio.sleep(0.15)
                dig_payload = {"x": chosen["x"], "y": chosen["y"]}
                async with session.post(f"{VICTORS_API}/arcade/mine/dig", json=dig_payload, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    dig_res = await resp.json()
                    if resp.status != 200 or not dig_res.get("success"):
                        logger.warning(f"[{account_name}] Dig failed at ({chosen['x']}, {chosen['y']}): {dig_res.get('error')}")
                        break
                    dig_count += 1
                    run_state = dig_res.get("run") or run_state
                    cell = dig_res.get("cell", {})
                    found = cell.get("found")
                    if found and isinstance(found, dict) and found.get("coins", 0) > 0:
                        logger.info(f"[{account_name}] 💰 Found loot at ({chosen['x']},{chosen['y']})! +{found['coins']} VIC. Bag now: {run_state.get('bag')} VIC")

                    # If server concluded the game automatically (e.g. energy depleted or cap reached)
                    if dig_res.get("result"):
                        res_obj = dig_res.get("result", {})
                        paid = res_obj.get("paid", run_state.get("bag", 0.0))
                        refund = res_obj.get("refund", 0.0)
                        net = res_obj.get("net", paid - 25.0)
                        balance = dig_res.get("state", {}).get("user", {}).get("inAppBalance", balance + paid)
                        stats["runs_played"] += 1
                        stats["total_paid"] += paid
                        stats["net_vic"] += net
                        stats["final_balance"] = balance
                        logger.info(f"[{account_name}] 🏆 Expedition #{run_idx + 1} auto-concluded: {dig_count} digs | Bag: {run_state.get('bag', 0):.1f} | Refund: {refund:.1f} | Paid: {paid:.1f} VIC (Net: {net:+.1f} VIC) | New Balance: {balance:.2f} VIC")
                        run_state["status"] = "ended"
                        break
            except Exception as e:
                logger.error(f"[{account_name}] Dig network error: {e}")
                break

        # 4. Cash Out safely with /api/arcade/mine/end if run is still active
        if run_state.get("status") == "active":
            try:
                async with session.post(f"{VICTORS_API}/arcade/mine/end", json={}, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    end_res = await resp.json()
                    if resp.status == 200 and end_res.get("success"):
                        res_obj = end_res.get("result", {})
                        paid = res_obj.get("paid", run_state.get("bag", 0.0))
                        refund = res_obj.get("refund", 0.0)
                        net = res_obj.get("net", paid - 25.0)
                        balance = end_res.get("state", {}).get("user", {}).get("inAppBalance", balance + paid)
                        stats["runs_played"] += 1
                        stats["total_paid"] += paid
                        stats["net_vic"] += net
                        stats["final_balance"] = balance
                        logger.info(f"[{account_name}] 🏆 Expedition #{run_idx + 1} cashed out: {dig_count} digs | Bag: {run_state.get('bag', 0):.1f} | Refund: {refund:.1f} | Paid: {paid:.1f} VIC (Net: {net:+.1f} VIC) | New Balance: {balance:.2f} VIC")
                    else:
                        logger.warning(f"[{account_name}] Cash out response: {end_res}")
            except Exception as e:
                logger.error(f"[{account_name}] Error cashing out: {e}")

        # Short pause between expeditions
        await asyncio.sleep(0.5)

    return stats
