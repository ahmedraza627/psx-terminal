import os
import json
import random
import urllib.request
from datetime import datetime

OUTPUT_PATH = os.path.join("frontend", "public", "data", "latest.json")

# Core liquid PSX universe for institutional trading
UNIVERSE = [
    {"ticker": "OGDC", "name": "Oil & Gas Development Co", "base": 312.50, "sector": "E&P", "bias": "BUY"},
    {"ticker": "FFC",  "name": "Fauji Fertilizer Co",       "base": 386.00, "sector": "Fertilizer", "bias": "BUY"},
    {"ticker": "MARI", "name": "Mari Energies Ltd",          "base": 565.00, "sector": "E&P", "bias": "BUY"},
    {"ticker": "ATRL", "name": "Attock Refinery Ltd",        "base": 442.00, "sector": "Refinery", "bias": "BUY"},
    {"ticker": "AIRLINK", "name": "Air Link Communication",  "base": 146.50, "sector": "Tech", "bias": "BUY"},
    {"ticker": "LUCK", "name": "Lucky Cement Ltd",           "base": 1028.00, "sector": "Cement", "bias": "BUY"},
    {"ticker": "MCB",  "name": "MCB Bank Ltd",               "base": 262.00, "sector": "Banking", "bias": "BUY"},
    {"ticker": "EFERT", "name": "Engro Fertilizers",         "base": 198.50, "sector": "Fertilizer", "bias": "BUY"},
    {"ticker": "MEBL", "name": "Meezan Bank Ltd",            "base": 552.00, "sector": "Banking", "bias": "BUY"},
    {"ticker": "SYS",  "name": "Systems Limited",            "base": 115.20, "sector": "Tech", "bias": "BUY"},
    # Avoid Universe
    {"ticker": "CNERGY", "name": "Cnergyico PK Ltd",         "base": 3.82, "sector": "Refinery", "bias": "AVOID", "tag": "PENNY TRAP", "reason": "Heavy debt capital erosion with extreme retail float."},
    {"ticker": "WTL",    "name": "WorldCall Telecom",        "base": 1.14, "sector": "Tech/Telecom", "bias": "AVOID", "tag": "RETAIL TRAP", "reason": "Zero institutional sponsor holding; speculative volume trap."},
    {"ticker": "PRL",    "name": "Pakistan Refinery",        "base": 26.80, "sector": "Refinery", "bias": "AVOID", "tag": "POLICY RISK", "reason": "Refinery upgrade delay creating overhead distribution pressure."},
    {"ticker": "SILK",   "name": "Silkbank Limited",         "base": 1.22, "sector": "Banking", "bias": "AVOID", "tag": "CAPITAL RISK", "reason": "Negative capital adequacy ratio; continuous capital erosion."},
    {"ticker": "HASCOL", "name": "Hascol Petroleum",         "base": 17.10, "sector": "OMC", "bias": "AVOID", "tag": "SPECULATIVE TRAP", "reason": "Negative equity overhang; speculative momentum fading at resistance."},
    {"ticker": "PSO",    "name": "Pakistan State Oil",      "base": 361.00, "sector": "OMC", "bias": "AVOID", "tag": "CIRCULAR DEBT", "reason": "Receivables overhang blocking sustainable breakout above 370 resistance."},
    {"ticker": "HUBC",   "name": "Hub Power Company",        "base": 201.80, "sector": "Power", "bias": "AVOID", "tag": "DISTRIBUTION", "reason": "Smart money distributing into retail bids post-PPA settlement."}
]

def generate_market_payload():
    now = datetime.now()
    session_date = now.strftime("%A, %b %d, %Y")
    session_time = now.strftime("%H:%M PKT")

    # Use today's calendar day as seed for deterministic daily rotation
    day_seed = int(now.strftime("%Y%m%d"))
    rng = random.Random(day_seed)

    # Filter Buy candidates & select top 5
    buy_pool = [x for x in UNIVERSE if x["bias"] == "BUY"]
    rng.shuffle(buy_pool)
    selected_buys = buy_pool[:5]

    # Filter Avoid candidates & select top 5
    avoid_pool = [x for x in UNIVERSE if x["bias"] == "AVOID"]
    rng.shuffle(avoid_pool)
    selected_avoids = avoid_pool[:5]

    buys_formatted = []
    for idx, item in enumerate(selected_buys, 1):
        price = item["base"]
        stop = round(price * 0.958, 2)     # -4.2% support
        target = round(price * 1.084, 2)   # +8.4% target
        rr = "1:2.0"
        buys_formatted.append({
            "rank": idx,
            "ticker": item["ticker"],
            "entry": f"PKR {price:.2f}",
            "stop": f"PKR {stop:.2f}",
            "target": f"PKR {target:.2f}",
            "rr": rr,
            "notes": f"Institutional {item['sector']} accumulation defending key support floor into quarterly results."
        })

    avoids_formatted = []
    for idx, item in enumerate(selected_avoids, 1):
        price = item["base"]
        avoid_ref = round(price * 1.035, 2)
        downside = round(price * 0.885, 2)
        invalidation = round(price * 1.06, 2)
        avoids_formatted.append({
            "rank": idx,
            "ticker": item["ticker"],
            "avoidRef": f"PKR {avoid_ref:.2f}",
            "downside": f"PKR {downside:.2f}",
            "price": f"PKR {price:.2f}",
            "invalidation": f"PKR {invalidation:.2f}",
            "tag": item.get("tag", "DISTRIBUTION"),
            "notes": item["reason"]
        })

    payload = {
        "sessionDate": session_date,
        "sessionTime": session_time,
        "buys": buys_formatted,
        "avoids": avoids_formatted
    }

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(payload, f, indent=2)

    print(f"\n[OK] Generated fresh dynamic setups for {session_date} {session_time}:")
    print("BUYS  :", [b['ticker'] for b in buys_formatted])
    print("AVOIDS:", [a['ticker'] for a in avoids_formatted])

if __name__ == "__main__":
    generate_market_payload()