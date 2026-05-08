#!/usr/bin/env python
# pylint: disable=unused-argument

import logging
import os
import re

import httpx
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

HELLOASSO_AUTH_URL = "https://api.helloasso.com/oauth2/token"
HELLOASSO_API_URL = "https://api.helloasso.com/v5"
URL_PATTERN = re.compile(r"helloasso\.com/associations/([^/\s]+)/evenements/([^/?\s]+)")


async def _get_access_token(client_id: str, client_secret: str) -> str:
    async with httpx.AsyncClient() as client:
        response = await client.post(
            HELLOASSO_AUTH_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
            },
        )
        response.raise_for_status()
        return response.json()["access_token"]


async def fetch_remaining_spots(org_slug: str, event_slug: str) -> str:
    client_id = os.getenv("HELLOASSO_CLIENT_ID")
    client_secret = os.getenv("HELLOASSO_CLIENT_SECRET")

    if not client_id or not client_secret:
        return (
            "Credentials HelloAsso non configurés.\n"
            "Renseigne HELLOASSO_CLIENT_ID et HELLOASSO_CLIENT_SECRET dans le .env"
        )

    token = await _get_access_token(client_id, client_secret)

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{HELLOASSO_API_URL}/organizations/{org_slug}/forms/Event/{event_slug}/items",
            headers={"Authorization": f"Bearer {token}"},
        )
        response.raise_for_status()
        items = response.json().get("data", [])

    if not items:
        return "Aucun billet trouvé pour cet événement."

    lines = []
    for item in items:
        name = item.get("name", "Billet")
        remaining = item.get("remainingEntries")
        if remaining is None:
            lines.append(f"• {name} : données non disponibles")
        else:
            lines.append(f"• {name} : {remaining} place(s) restante(s)")

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
    except httpx.HTTPStatusError as e:
        result = f"Erreur API HelloAsso : {e.response.status_code}."
        logger.error("HTTPStatusError : %s", e)
    except Exception:
        result = "Une erreur inattendue s'est produite."
        logger.exception("Erreur inattendue dans fetch_remaining_spots")

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
