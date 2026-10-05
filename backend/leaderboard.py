"""
RiskPilot 排行榜与五行阵营系统
- 个人牛人榜：预置虚拟玩家 + 用户成绩插入，按盈利率排名
- 五行阵营榜：金木水火土，成员平均盈利率 + 人数加成
- 阵营天赋：每个阵营有独特的游戏内加成
"""

import json
import os
import time
import random
from typing import List, Dict, Any, Optional

# ============ 五行阵营定义 ============

FACTIONS = {
    "jin": {
        "name": "金",
        "icon": "🪙",
        "style": "稳健价值派",
        "desc": "落袋为安，不赚最后一个铜板。防御型选手的最爱。",
        "trait": "亏损预算放宽10%",
        "trait_desc": "最大可承受亏损 × 1.1，更抗跌",
        "color": "#fbbf24",
        "totem": "🐉",
    },
    "mu": {
        "name": "木",
        "icon": "🌳",
        "style": "成长长线派",
        "desc": "时间是最好的朋友，好公司值得长期陪伴。",
        "trait": "持有超过2关盈利加成5%",
        "trait_desc": "连续持有2关以上，最终盈利 × 1.05",
        "color": "#34d399",
        "totem": "🦚",
    },
    "shui": {
        "name": "水",
        "icon": "💧",
        "style": "灵活波段派",
        "desc": "上善若水，顺势而为。波段操作，积少成多。",
        "trait": "交易手续费减半",
        "trait_desc": "所有交易佣金 × 0.5，频繁操作更划算",
        "color": "#60a5fa",
        "totem": "🐋",
    },
    "huo": {
        "name": "火",
        "icon": "🔥",
        "style": "激进短线派",
        "desc": "生死看淡，不服就干。高风险高回报，心跳玩家首选。",
        "trait": "单票仓位上限提升至40%",
        "trait_desc": "最大持仓比例从30%提到40%，搏一把大的",
        "color": "#f87171",
        "totem": "🦄",
    },
    "tu": {
        "name": "土",
        "icon": "🛡️",
        "style": "保守定投派",
        "desc": "厚德载物，稳扎稳打。不追求暴利，只求不亏。",
        "trait": "强制清仓线延后1关",
        "trait_desc": "亏损超预算后多给1次机会，不会立刻清仓",
        "color": "#a78bfa",
        "totem": "🐢",
    },
}

FACTION_ORDER = ["jin", "mu", "shui", "huo", "tu"]


# ============ 预置虚拟玩家 ============

VIRTUAL_PLAYERS = [
    {"name": "韭菜本菜", "avatar": "🌱", "faction": "tu", "pnl_pct": -8.5, "games": 12},
    {"name": "巴菲特中国分特", "avatar": "🧓", "faction": "jin", "pnl_pct": 15.2, "games": 8},
    {"name": "追涨杀跌王", "avatar": "🏃", "faction": "huo", "pnl_pct": -3.2, "games": 15},
    {"name": "梭哈一时爽", "avatar": "🎰", "faction": "huo", "pnl_pct": 22.7, "games": 5},
    {"name": "定投老黄牛", "avatar": "🐂", "faction": "tu", "pnl_pct": 6.8, "games": 20},
    {"name": "K线占卜师", "avatar": "🔮", "faction": "shui", "pnl_pct": 11.3, "games": 9},
    {"name": "消息面大师", "avatar": "📰", "faction": "huo", "pnl_pct": -5.7, "games": 11},
    {"name": "价值投资者", "avatar": "💎", "faction": "mu", "pnl_pct": 18.9, "games": 7},
    {"name": "打板小能手", "avatar": "⚡", "faction": "huo", "pnl_pct": 4.2, "games": 14},
    {"name": "躺平学代表", "avatar": "😴", "faction": "tu", "pnl_pct": 2.1, "games": 3},
    {"name": "量化交易员", "avatar": "🤖", "faction": "shui", "pnl_pct": 13.6, "games": 18},
    {"name": "抄底急先锋", "avatar": "🪂", "faction": "jin", "pnl_pct": -1.8, "games": 10},
]


# ============ 数据持久化 ============

DATA_FILE = os.path.join(os.path.dirname(__file__), "leaderboard_data.json")


def _load_data() -> Dict[str, Any]:
    """加载排行榜数据，不存在则初始化"""
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    # 初始化：虚拟玩家 + 空用户列表
    return {
        "virtual_players": VIRTUAL_PLAYERS,
        "user_scores": [],
        "faction_bonuses": {},
    }


def _save_data(data: Dict[str, Any]):
    """保存排行榜数据"""
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ============ 个人排行榜 ============

def get_leaderboard(limit: int = 20) -> Dict[str, Any]:
    """
    获取个人牛人榜
    返回：按盈利率降序排列的玩家列表，包含排名、是否前十等
    """
    data = _load_data()
    all_players = []

    # 虚拟玩家
    for p in data["virtual_players"]:
        all_players.append({
            "name": p["name"],
            "avatar": p["avatar"],
            "faction": p["faction"],
            "pnl_pct": p["pnl_pct"],
            "games": p["games"],
            "is_virtual": True,
            "is_user": False,
        })

    # 用户成绩（取每个用户最好成绩）
    user_best = {}
    for s in data["user_scores"]:
        name = s.get("name", "匿名玩家")
        if name not in user_best or s["pnl_pct"] > user_best[name]["pnl_pct"]:
            user_best[name] = s
    for name, s in user_best.items():
        all_players.append({
            "name": name,
            "avatar": s.get("avatar", "🎮"),
            "faction": s.get("faction", "jin"),
            "pnl_pct": s["pnl_pct"],
            "games": s.get("games", 1),
            "is_virtual": False,
            "is_user": True,
        })

    # 按盈利率降序
    all_players.sort(key=lambda x: x["pnl_pct"], reverse=True)

    # 标注排名和前十
    for i, p in enumerate(all_players):
        p["rank"] = i + 1
        p["is_top10"] = i < 10

    return {
        "players": all_players[:limit],
        "total_players": len(all_players),
        "top10_cutoff": all_players[9]["pnl_pct"] if len(all_players) >= 10 else None,
    }


def submit_score(name: str, avatar: str, faction: str, pnl_pct: float,
                 capital: float, pnl: float, stock_name: str,
                 games: int = 1) -> Dict[str, Any]:
    """
    提交用户成绩，返回排名变动信息
    """
    data = _load_data()

    # 记录成绩
    score = {
        "name": name or "匿名玩家",
        "avatar": avatar or "🎮",
        "faction": faction or "jin",
        "pnl_pct": round(pnl_pct, 2),
        "capital": capital,
        "pnl": pnl,
        "stock_name": stock_name,
        "games": games,
        "timestamp": int(time.time()),
    }
    data["user_scores"].append(score)
    _save_data(data)

    # 计算新排名
    board = get_leaderboard(limit=100)
    user_rank = None
    for p in board["players"]:
        if p["name"] == name and p["is_user"]:
            user_rank = p["rank"]
            break

    # 判断是否进入前十
    entered_top10 = user_rank is not None and user_rank <= 10
    previous_10th = board["players"][9]["name"] if len(board["players"]) >= 10 else None
    beat_player = None
    if entered_top10 and previous_10th and previous_10th != name:
        beat_player = previous_10th

    # 生成恭喜文案
    congrats = None
    if entered_top10:
        if user_rank == 1:
            congrats = "👑 股神附体！你把「{}」拉下了神坛，登顶牛人榜第一名！".format(
                board["players"][1]["name"] if len(board["players"]) > 1 else "所有人")
        elif user_rank <= 3:
            congrats = "🔥 三甲就位！大吉大利，今晚吃肉！你击败了「{}」，成为牛人榜第{}名！".format(
                beat_player or "对手", user_rank)
        else:
            congrats = "🎉 恭喜进入牛人榜！你击败了「{}」，成为第{}名！继续加油，冲击三甲！".format(
                beat_player or "对手", user_rank)

    return {
        "score": score,
        "rank": user_rank,
        "entered_top10": entered_top10,
        "beat_player": beat_player,
        "congrats": congrats,
        "top10_cutoff": board["top10_cutoff"],
    }


# ============ 阵营榜 ============

def get_faction_ranking() -> Dict[str, Any]:
    """
    获取五行阵营榜
    阵营总分 = 成员平均盈利率 × (1 + 参与人数×0.5%)，人数加成最多10%
    """
    data = _load_data()
    faction_stats = {fid: {"members": [], "total_pnl": 0, "count": 0} for fid in FACTION_ORDER}

    # 虚拟玩家
    for p in data["virtual_players"]:
        fid = p.get("faction", "jin")
        if fid in faction_stats:
            faction_stats[fid]["members"].append(p["name"])
            faction_stats[fid]["total_pnl"] += p["pnl_pct"]
            faction_stats[fid]["count"] += 1

    # 用户成绩（取每个用户最好成绩）
    user_best = {}
    for s in data["user_scores"]:
        name = s.get("name", "匿名玩家")
        if name not in user_best or s["pnl_pct"] > user_best[name]["pnl_pct"]:
            user_best[name] = s
    for name, s in user_best.items():
        fid = s.get("faction", "jin")
        if fid in faction_stats:
            faction_stats[fid]["members"].append(name)
            faction_stats[fid]["total_pnl"] += s["pnl_pct"]
            faction_stats[fid]["count"] += 1

    # 计算每个阵营的分数
    rankings = []
    for fid in FACTION_ORDER:
        info = FACTIONS[fid]
        stat = faction_stats[fid]
        if stat["count"] > 0:
            avg_pnl = stat["total_pnl"] / stat["count"]
            member_bonus = min(stat["count"] * 0.005, 0.10)  # 最多10%
            score = avg_pnl * (1 + member_bonus)
        else:
            avg_pnl = 0
            member_bonus = 0
            score = 0

        rankings.append({
            "faction_id": fid,
            "name": info["name"],
            "icon": info["icon"],
            "style": info["style"],
            "color": info["color"],
            "totem": info["totem"],
            "avg_pnl": round(avg_pnl, 2),
            "member_count": stat["count"],
            "member_bonus": round(member_bonus * 100, 1),
            "score": round(score, 2),
            "members": stat["members"][:5],  # 只显示前5个成员
        })

    # 按分数降序
    rankings.sort(key=lambda x: x["score"], reverse=True)
    for i, r in enumerate(rankings):
        r["rank"] = i + 1

    # 前三名奖励信息
    rewards = {
        1: {"title": "五行至尊", "theme": "gold", "avatar_frame": "gold"},
        2: {"title": "二象守护者", "theme": "silver", "avatar_frame": "silver"},
        3: {"title": "三界行者", "theme": "bronze", "avatar_frame": "bronze"},
    }
    for r in rankings:
        if r["rank"] in rewards:
            r["reward"] = rewards[r["rank"]]

    return {
        "factions": rankings,
        "leader": rankings[0] if rankings else None,
        "rewards": rewards,
    }


def get_faction_trait(faction_id: str) -> Optional[Dict[str, Any]]:
    """获取阵营天赋详情"""
    return FACTIONS.get(faction_id)


def apply_faction_trait(faction_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """
    应用阵营天赋到模拟参数
    返回修改后的参数
    """
    result = dict(params)
    trait = FACTIONS.get(faction_id, {})

    if faction_id == "jin":
        # 金：亏损预算放宽10%
        result["max_loss"] = params.get("max_loss", 0) * 1.1
    elif faction_id == "huo":
        # 火：仓位上限提升到40%（前端控制，这里标记）
        result["position_limit"] = 0.40
    elif faction_id == "shui":
        # 水：手续费减半（前端控制，这里标记）
        result["fee_multiplier"] = 0.5
    elif faction_id == "tu":
        # 土：清仓线延后1关（前端控制，这里标记）
        result["stop_delay"] = 1
    elif faction_id == "mu":
        # 木：持有超过2关盈利加成5%（结算时处理）
        result["holding_bonus"] = True

    result["faction_trait"] = trait.get("trait", "")
    result["faction_trait_desc"] = trait.get("trait_desc", "")
    return result
