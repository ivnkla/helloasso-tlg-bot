#!/usr/bin/env python
# pylint: disable=unused-argument

import logging
import os
import re

from curl_cffi.requests import AsyncSession
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

HELLOASSO_BASE_URL = "https://www.helloasso.com"
URL_PATTERN = re.compile(r"helloasso\.com/associations/([^/\s]+)/evenements/([^/?\s]+)")

# Extrait chaque tier : capture remainingNumber et label dans le bloc JS embarqué
TIER_PATTERN = re.compile(r"\{remainingNumber:(\d+),[^}]*?label:\"([^\"]+)\"")


async def fetch_remaining_spots(org_slug: str, event_slug: str) -> str:
    url = f"{HELLOASSO_BASE_URL}/associations/{org_slug}/evenements/{event_slug}"

    async with AsyncSession() as session:
        response = await session.get(url, impersonate="firefox", timeout=15)
        response.raise_for_status()
        html = response.text

    tiers = TIER_PATTERN.findall(html)

    if not tiers:
        return "Impossible de récupérer les places (données introuvables dans la page)."

    lines = []
    for remaining, label in tiers:
        lines.append(f"• {label} : {remaining} place(s) restante(s)")

    return "\n".join(lines)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Envoie-moi un lien HelloAsso vers un événement et je te dirai combien de places restent.\n\n"
        "Exemple :\nhttps://www.helloasso.com/associations/mon-asso/evenements/mon-evenement"
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text or ""
    match = URL_PATTERN.search(text)

    if not match:
        await update.message.reply_text(
            "Lien HelloAsso non reconnu.\n"
            "Format attendu : helloasso.com/associations/{asso}/evenements/{evenement}"
        )
        return

    org_slug, event_slug = match.group(1), match.group(2)
    await update.message.reply_text("Recherche en cours…")

    try:
        result = await fetch_remaining_spots(org_slug, event_slug)
    except Exception as e:
        if hasattr(e, "response") and e.response is not None:
            result = f"Erreur HTTP {e.response.status_code} lors de la récupération de la page."
        else:
            result = "Une erreur inattendue s'est produite."
        logger.error("Erreur dans fetch_remaining_spots : %s", e)

    await update.message.reply_text(result)


def main() -> None:
    load_dotenv()
    token = os.getenv("TOKEN")

    application = Application.builder().token(token).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
