![Python](https://img.shields.io/badge/python-3+-blue)
# helloasso-tlg-bot

Bot Telegram qui surveille la disponibilité des billets sur HelloAsso.

## Utiliser le bot

Le bot est disponible sur Telegram : [@hello_asso_alert_bot](https://t.me/hello_asso_alert_bot)

1. Envoie un lien HelloAsso - le bot répond avec les places restantes par tarif
2. `/subscribe` - active les notifications automatiques à chaque changement (vérification toutes les 5 min)
3. `/unsubscribe` - désactive les notifications pour ce lien

Le bot se désabonne automatiquement quand l'événement est complet ou que la billetterie est fermée.

---

## Héberger le projet soi-même

### En local

**Prérequis** : Python 3, un token de bot Telegram (obtenu via [@BotFather](https://t.me/botfather))

```bash
git clone https://github.com/ivnkla/helloasso-tlg-bot
cd helloasso-tlg-bot
pip install -r requirements.txt
```

Créer un fichier `.env` à la racine :

```
TOKEN=<token_telegram>
```

Lancer le bot :

```bash
python main.py
```

### Sur Railway (cloud)

**Prérequis** : un token de bot Telegram et un compte [Railway](https://railway.app)

1. Forker ce dépôt
2. Créer un nouveau projet Railway depuis le fork
3. Ajouter un **Volume** (Settings → Volumes → Add Volume, mount path : `/data`)
4. Configurer les variables d'environnement (Settings → Variables) :
   ```
   TOKEN=<token_telegram>
   SUBSCRIPTIONS_PATH=/data/subscriptions.json
   ```
5. Définir la commande de démarrage (Settings → Deploy → Start Command) :
   ```
   python main.py
   ```
6. Déployer - Railway installe les dépendances depuis `requirements.txt` automatiquement

## Stack

| Composant | Rôle |
|---|---|
| `python-telegram-bot` | Framework bot Telegram (avec job queue) |
| `curl_cffi` | Scraping avec impersonation TLS Firefox (contourne la protection anti-bot HelloAsso) |
| `python-dotenv` | Chargement des variables d'environnement |
