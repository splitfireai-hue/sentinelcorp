"""
Due Diligence Example — Check a batch of companies against SEBI debarred list.

Usage:
    pip install sentinelcorp
    python due_diligence.py
"""

import sys
sys.path.insert(0, "../sdk")

from sentinelcorp import SentinelCorp

API_URL = "https://sentinelcorp-production.up.railway.app"

companies = [
    "Sahara India",
    "Tata Consultancy Services",
    "Reliance Industries",
    "27AAACT1234A1Z5",  # GSTIN
    "L17110MH1973PLC019786",  # CIN (Reliance)
    "ABCPE1234F",  # PAN
]


def main():
    client = SentinelCorp(base_url=API_URL)

    print("Due Diligence Report")
    print("=" * 60)

    high_risk = []
    for company in companies:
        profile = client.profile(company)
        score = profile["overall_risk_score"]
        level = profile["risk_level"]
        debarred = profile["is_debarred"]

        flag = "!!" if score >= 65 else " >"
        print(f"  {flag} {company[:40]:40s}  score: {score:5.1f}  level: {level:8s}  debarred: {debarred}")

        if score >= 65:
            high_risk.append((company, profile))

    print("=" * 60)
    if high_risk:
        print(f"\n{len(high_risk)} HIGH RISK entities found — do NOT proceed:")
        for name, p in high_risk:
            print(f"  - {name}")
            for m in p.get("debarred_matches", [])[:2]:
                print(f"      Matched: {m['matched_name']}")
    else:
        print("\nAll entities cleared. Safe to proceed.")

    client.close()


if __name__ == "__main__":
    main()
