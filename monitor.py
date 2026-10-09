
import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from futbin_sdk import FutbinClient, Platform

PLAYERS = [
    "Kika Nazareth",
    "Marcus Rashford",
    "Lamine Yamal",
    "Vinicius Jr",
    "Aurelien Tchouameni",
    "Mbappe",
]

HISTORY_FILE = Path("history.json")
MAX_CARD_PRICE = 72500
MIN_PROFIT = 10000
EA_TAX = 0.05


def send_telegram(message):
    import urllib.request
    import urllib.parse

    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": message,
    }).encode()

    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=data,
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        response.read()


def load_history():
    if HISTORY_FILE.exists():
        try:
            return json.loads(HISTORY_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


async def main():
    history = load_history()
    now = datetime.now(timezone.utc)
    timestamp = now.isoformat()
    messages = []

    async with FutbinClient() as client:
        for name in PLAYERS:
            try:
                results = await client.search_players(query=name)

                # Keep matching results; avoid unrelated search results.
                matches = [
                    p for p in results
                    if name.lower().split()[-1] in p.name.lower()
                ][:10]

                if not matches:
                    print(f"No matching card found: {name}")
                    continue

                for card in matches:
                    card_id = str(card.futbin_id)
                    card_name = card.name
                    try:
                        result = await client.get_player_price(
                            card.futbin_id, Platform.PS
                        )
                        price = int(result.price or 0)
                    except Exception as exc:
                        print(f"Price lookup failed for {card_name}: {exc}")
                        continue

                    if price <= 0:
                        continue

                    key = f"{card_id}"
                    samples = history.setdefault(key, [])
                    samples.append({
                        "time": timestamp,
                        "price": price,
                        "name": card_name,
                    })

                    # Keep eight days of observations.
                    cutoff = now.timestamp() - 8 * 86400
                    samples[:] = [
                        s for s in samples
                        if datetime.fromisoformat(s["time"]).timestamp()
                        >= cutoff
                    ]

                    recent24 = [
                        s["price"] for s in samples
                        if datetime.fromisoformat(s["time"]).timestamp()
                        >= now.timestamp() - 86400
                    ]
                    recent7d = [
                        s["price"] for s in samples
                        if datetime.fromisoformat(s["time"]).timestamp()
                        >= now.timestamp() - 7 * 86400
                    ]

                    # Need enough collected observations before alerting.
                    if len(recent24) < 4 or len(recent7d) < 12:
                        print(f"Collecting history: {card_name} = {price:,}")
                        continue

                    avg24 = sum(recent24) / len(recent24)
                    avg7d = sum(recent7d) / len(recent7d)

                    drop24 = (avg24 - price) / avg24
                    drop7d = (avg7d - price) / avg7d
                    potential_profit = int(avg7d * (1 - EA_TAX) - price)

                    if (
                        price <= MAX_CARD_PRICE
                        and (drop24 >= 0.12 or drop7d >= 0.15)
                        and potential_profit >= MIN_PROFIT
                    ):
                        messages.append(
                            f"FC 27 PS5 price alert\n"
                            f"{card_name}\n"
                            f"Current: {price:,} coins\n"
                            f"24h average: {avg24:,.0f}\n"
                            f"7d average: {avg7d:,.0f}\n"
                            f"Drop vs 24h: {drop24:.1%}\n"
                            f"Drop vs 7d: {drop7d:.1%}\n"
                            f"Estimated profit after 5% tax: "
                            f"{potential_profit:,} coins\n"
                            f"Check the market manually before buying."
                        )

                    print(f"{card_name}: {price:,} coins")

            except Exception as exc:
                print(f"Search failed for {name}: {exc}")

    HISTORY_FILE.write_text(
        json.dumps(history, ensure_ascii=False, indent=2)
    )

    for message in messages:
        try:
            send_telegram(message)
        except Exception as exc:
            print(f"Telegram notification failed: {exc}")


if __name__ == "__main__":
    asyncio.run(main())
