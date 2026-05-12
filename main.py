#!/usr/bin/env python
# pylint: disable=unused-argument

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from curl_cffi.requests import AsyncSession
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

HELLOASSO_BASE_URL = "https://www.helloasso.com"
URL_PATTERN = re.compile(r"helloasso\.com/associations/([^/\s]+)/evenements/([^/?\s]+)")
TIER_PATTERN = re.compile(r"\{remainingNumber:(\d+),[^}]*?label:\"([^\"]+)\"")
SALE_END_PATTERN = re.compile(r'saleEndDate:"([^"]+)"')

SUBSCRIPTIONS_FILE = Path(os.getenv("SUBSCRIPTIONS_PATH", "subscriptions.json"))
POLL_INTERVAL = 300  # 5 minutes

WAITING_FOR_URL = 1


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def load_subscriptions() -> dict:
    if SUBSCRIPTIONS_FILE.exists():
        return json.loads(SUBSCRIPTIONS_FILE.read_text())
    return {}


def save_subscriptions(data: dict) -> None:
    SUBSCRIPTIONS_FILE.write_text(json.dumps(data, indent=2))


# ---------------------------------------------------------------------------
# HelloAsso scraping
# ---------------------------------------------------------------------------

async def _fetch_html(org_slug: str, event_slug: str) -> str:
    url = f"{HELLOASSO_BASE_URL}/associations/{org_slug}/evenements/{event_slug}"
    async with AsyncSession() as session:
        response = await session.get(url, impersonate="firefox", timeout=15)
        response.raise_for_status()
        return response.text


def _parse_tiers(html: str) -> dict[str, int]:
    """Retourne {label: remaining} pour chaque tier trouvé."""
    return {label: int(remaining) for remaining, label in TIER_PATTERN.findall(html)}


def _parse_sale_end(html: str) -> datetime | None:
    match = SALE_END_PATTERN.search(html)
    if not match:
        return None
    try:
        return datetime.fromisoformat(match.group(1))
    except ValueError:
        return None


def _format_tiers(tiers: dict[str, int]) -> str:
    if not tiers:
        return "Impossible de récupérer les places (données introuvables dans la page)."
    return "\n".join(f"• {label} : {remaining} place(s) restante(s)" for label, remaining in tiers.items())


# ---------------------------------------------------------------------------
# Handlers — consultation ponctuelle
# ---------------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    await update.message.reply_text(
        "Commandes disponibles :\n\n"
        "• /check <lien> → consulter les places d'un événement\n"
        "• /subscribe → s'abonner aux mises à jour d'un événement\n"
        "• /list → voir ses abonnements actifs\n"
        "• /unsubscribe → gérer ses abonnements\n"
        "• /help → afficher l'aide\n\n"
        "Exemple de lien :\n"
        "https://www.helloasso.com/associations/mon-asso/evenements/mon-evenement"
    )


async def check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    args = context.args or []
    if not args:
        await update.message.reply_text(
            "Usage : /check <lien HelloAsso>\n"
            "Exemple : /check https://www.helloasso.com/associations/mon-asso/evenements/mon-evenement"
        )
        return

    match = URL_PATTERN.search(args[0])
    if not match:
        await update.message.reply_text(
            "Lien HelloAsso non reconnu.\n"
            "Format attendu : helloasso.com/associations/{asso}/evenements/{evenement}"
        )
        return

    org_slug, event_slug = match.group(1), match.group(2)
    await update.message.reply_text("Recherche en cours…")

    try:
        html = await _fetch_html(org_slug, event_slug)
        result = _format_tiers(_parse_tiers(html))
    except Exception as e:
        http_response = getattr(e, "response", None)
        result = f"Erreur HTTP {http_response.status_code}." if http_response else "Erreur inattendue."
        logger.error("Erreur fetch /check : %s", e)

    await update.message.reply_text(result)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
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
        html = await _fetch_html(org_slug, event_slug)
        result = _format_tiers(_parse_tiers(html))
    except Exception as e:
        http_response = getattr(e, "response", None)
        result = f"Erreur HTTP {http_response.status_code}." if http_response else "Erreur inattendue."
        logger.error("Erreur fetch ponctuel : %s", e)

    await update.message.reply_text(result)


# ---------------------------------------------------------------------------
# Handlers — abonnement
# ---------------------------------------------------------------------------

async def subscribe_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message is None:
        return ConversationHandler.END
    await update.message.reply_text("Envoie le lien HelloAsso de l'événement à suivre :")
    return WAITING_FOR_URL


async def subscribe_receive_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message is None:
        return ConversationHandler.END
    text = update.message.text or ""
    match = URL_PATTERN.search(text)

    if not match:
        await update.message.reply_text(
            "Lien non reconnu. Réessaie ou /cancel pour annuler."
        )
        return WAITING_FOR_URL

    org_slug, event_slug = match.group(1), match.group(2)
    event_key = f"{org_slug}/{event_slug}"
    if update.effective_chat is None:
        return ConversationHandler.END
    chat_id = str(update.effective_chat.id)

    await update.message.reply_text("Vérification de l'événement…")

    try:
        html = await _fetch_html(org_slug, event_slug)
        tiers = _parse_tiers(html)
    except Exception as e:
        await update.message.reply_text("Impossible de récupérer l'événement. Abonnement annulé.")
        logger.error("Erreur fetch lors de l'abonnement : %s", e)
        return ConversationHandler.END

    if not tiers:
        await update.message.reply_text("Aucune donnée de places trouvée pour cet événement.")
        return ConversationHandler.END

    subs = load_subscriptions()
    subs.setdefault(chat_id, {})

    if event_key in subs[chat_id]:
        await update.message.reply_text("Tu es déjà abonné à cet événement.")
        return ConversationHandler.END

    subs[chat_id][event_key] = {"last_known": tiers}
    save_subscriptions(subs)

    await update.message.reply_text(
        f"Abonnement enregistré.\nÉtat actuel :\n{_format_tiers(tiers)}\n\n"
        "Tu seras notifié dès qu'une place change."
    )
    return ConversationHandler.END


async def subscribe_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message is None:
        return ConversationHandler.END
    await update.message.reply_text("Abonnement annulé.")
    return ConversationHandler.END


async def list_subscriptions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    if update.effective_chat is None:
        return
    chat_id = str(update.effective_chat.id)
    subs = load_subscriptions()
    user_subs = subs.get(chat_id, {})

    if not user_subs:
        await update.message.reply_text("Tu n'as aucun abonnement actif.")
        return

    lines = [f"• {HELLOASSO_BASE_URL}/associations/{key}" for key in user_subs]
    await update.message.reply_text("Tes abonnements actifs :\n" + "\n".join(lines))


async def unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    if update.effective_chat is None:
        return
    chat_id = str(update.effective_chat.id)
    subs = load_subscriptions()
    user_subs = subs.get(chat_id, {})

    if not user_subs:
        await update.message.reply_text("Tu n'as aucun abonnement actif.")
        return

    keyboard = [
        [InlineKeyboardButton(key, callback_data=f"unsub:{key}")]
        for key in user_subs
    ]
    keyboard.append([InlineKeyboardButton("Annuler", callback_data="unsub:__cancel__")])

    await update.message.reply_text(
        "Choisis l'abonnement à supprimer :",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def unsubscribe_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return
    await query.answer()

    data = (query.data or "").removeprefix("unsub:")
    if data == "__cancel__":
        await query.edit_message_text("Annulé.")
        return

    if update.effective_chat is None:
        return
    chat_id = str(update.effective_chat.id)
    subs = load_subscriptions()

    if chat_id in subs and data in subs[chat_id]:
        del subs[chat_id][data]
        if not subs[chat_id]:
            del subs[chat_id]
        save_subscriptions(subs)
        await query.edit_message_text(f"Abonnement supprimé : {data}")
    else:
        await query.edit_message_text("Abonnement introuvable.")


# ---------------------------------------------------------------------------
# Job de polling
# ---------------------------------------------------------------------------

async def poll_subscriptions(context: ContextTypes.DEFAULT_TYPE) -> None:
    subs = load_subscriptions()
    if not subs:
        return

    now = datetime.now(timezone.utc)
    changed = False

    for chat_id, events in list(subs.items()):
        for event_key, data in list(events.items()):
            org_slug, event_slug = event_key.split("/", 1)
            try:
                html = await _fetch_html(org_slug, event_slug)
                tiers = _parse_tiers(html)
                sale_end = _parse_sale_end(html)
            except Exception as e:
                logger.error("Erreur polling %s : %s", event_key, e)
                continue

            last_known = data["last_known"]
            all_sold_out = tiers and all(v == 0 for v in tiers.values())
            sale_ended = sale_end is not None and sale_end.astimezone(timezone.utc) < now

            if tiers != last_known:
                lines = []
                for label, remaining in tiers.items():
                    prev = last_known.get(label)
                    arrow = f" (était {prev})" if prev is not None and prev != remaining else ""
                    lines.append(f"• {label} : {remaining} place(s) restante(s){arrow}")
                msg = f"Mise à jour — {event_key} :\n" + "\n".join(lines)
                await context.bot.send_message(chat_id=int(chat_id), text=msg)
                subs[chat_id][event_key]["last_known"] = tiers
                changed = True

            if all_sold_out or sale_ended:
                reason = "complet" if all_sold_out else "ventes terminées"
                await context.bot.send_message(
                    chat_id=int(chat_id),
                    text=f"Abonnement supprimé automatiquement ({reason}) : {event_key}",
                )
                del subs[chat_id][event_key]
                if not subs[chat_id]:
                    del subs[chat_id]
                changed = True

    if changed:
        save_subscriptions(subs)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    load_dotenv()
    token = os.getenv("TOKEN")
    if not token:
        raise ValueError("La variable d'environnement TOKEN est manquante.")

    application = Application.builder().token(token).build()

    subscribe_conv = ConversationHandler(
        entry_points=[CommandHandler("subscribe", subscribe_start)],
        states={
            WAITING_FOR_URL: [MessageHandler(filters.TEXT & ~filters.COMMAND, subscribe_receive_url)],
        },
        fallbacks=[CommandHandler("cancel", subscribe_cancel)],
    )

    application.add_handler(CommandHandler(["start", "help"], start))
    application.add_handler(CommandHandler("check", check))
    application.add_handler(subscribe_conv)
    application.add_handler(CommandHandler("list", list_subscriptions))
    application.add_handler(CommandHandler("unsubscribe", unsubscribe))
    application.add_handler(CallbackQueryHandler(unsubscribe_callback, pattern=r"^unsub:"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    if application.job_queue is None:
        raise RuntimeError("Job queue non disponible — installe le paquet 'python-telegram-bot[job-queue]'.")
    application.job_queue.run_repeating(poll_subscriptions, interval=POLL_INTERVAL, first=10)

    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
