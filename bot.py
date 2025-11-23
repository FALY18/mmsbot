# -*- coding: utf-8 -*-
import asyncio
import json
import re
import time
import random
import os
from urllib.parse import urlparse
from typing import Optional, Tuple, List, Dict, Any
from datetime import datetime

from telethon import TelegramClient
from telethon.tl.types import Message

from instagrapi import Client as InstaClient
from instagrapi.exceptions import (
    LoginRequired, PleaseWaitFewMinutes, ChallengeRequired,
    FeedbackRequired, ClientError, ClientConnectionError
)

# ======================
# CONFIG TELEGRAM (à adapter si besoin)
# ======================
API_ID = 21297856  # <-- Mets ton api_id
API_HASH = "8xxxxxxxxxxxxxxxx20b735d3"  # <-- Mets ton api_hash
BOT_USERNAME = "@SmmKingdomTasksBot"

# ======================
# CONFIGURATION
# ======================
MAX_RETRIES = 3
REQUEST_DELAY = (0.5, 1.5)
ACTION_DELAY = (0.5, 2.0)
MAX_TASKS_PER_ACCOUNT = 20

# Fenêtre pour accepter "tâches existantes" au démarrage (en secondes).
EXISTING_TASK_WINDOW_SECONDS = 120

LAST_ACCOUNT_FILE = "last_account.txt"
STATE_FILE = "state.json"

# ======================
# CHARGEMENT COMPTES IG
# ======================
try:
    with open("insta_info.json", "r") as f:
        INSTA_ACCOUNTS = json.load(f)
except FileNotFoundError:
    print("❌ Fichier insta_info.json introuvable")
    raise SystemExit(1)
except json.JSONDecodeError:
    print("❌ Erreur de format dans insta_info.json")
    raise SystemExit(1)

INSTA_PASSWORDS = {a["username"]: a["password"] for a in INSTA_ACCOUNTS}
INSTA_SESSIONS: Dict[str, InstaClient] = {}

SKIP_ACCOUNTS: dict[str, float] = {}
SKIP_DURATION = 3600

# persistent state for tasks/accounts to avoid skipping/reprocessing
STATE: Dict[str, Any] = {
    "accounts": {}  # username -> { last_msg_id, skip_until, consecutive_errors }
}


# ======================
# STATE PERSISTENCE
# ======================
def load_state():
    global STATE
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                STATE = json.load(f)
        except Exception:
            STATE = {"accounts": {}}


def save_state():
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(STATE, f)
    except Exception as e:
        print(f"⚠️ Impossible de sauvegarder l'état: {e}")


def ensure_account_state(username: str):
    acc = STATE.setdefault("accounts", {})
    if username not in acc:
        acc[username] = {"last_msg_id": 0, "skip_until": 0, "consecutive_errors": 0}
    return acc[username]


# ======================
# UTILITAIRES TELEGRAM
# ======================
def is_thankyou_message(text: str) -> bool:
    t = (text or "").lower()
    patterns = [
        r"^thank you for completing the task",
        r"your balance has been replenished",
        r"task completed successfully",
        r"merci d'avoir complété",
        r"votre solde a été rechargé",
        r"congratulations",
        r"félicitations",
        r"your balance has been replenished with \d+\.?\d* cashcoins",
        r"thank you for completing the task: leave the comment",
        r"link : https?://www\.instagram\.com/p/",
    ]
    return any(re.search(p, t) for p in patterns)


def looks_like_task_block(text: str) -> bool:
    if not text:
        return False
    if is_thankyou_message(text):
        return False
    tl = text.lower()
    patterns = [
        r"link\s*[:\-]",
        r"action\s*[:\-]",
        r"▪️\s*link",
        r"▪️\s*action",
        r"reward\s*[:\-]",
        r"cashcoins",
        r"https?://[^\s]+",
        r"instagram\.com/p/",
        r"leave the comment",
        r"copier",
    ]
    match_count = sum(1 for pattern in patterns if re.search(pattern, tl))
    return match_count >= 2


async def send_with_retry(client: TelegramClient, entity: str, message: str, max_retries: int = 3) -> bool:
    for attempt in range(max_retries):
        try:
            await client.send_message(entity, message)
            await asyncio.sleep(random.uniform(*REQUEST_DELAY))
            return True
        except Exception as e:
            print(f"⚠️ Erreur envoi Telegram (tentative {attempt+1}): {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)
    return False


async def wait_next_bot_message(client: TelegramClient, bot: str, after_id: int, timeout_sec: int = 10) -> Optional[Message]:
    start = time.time()
    last_id = after_id
    while time.time() - start < timeout_sec:
        try:
            async for m in client.iter_messages(bot, limit=6, min_id=last_id):
                if m and m.id > after_id:
                    return m
        except Exception as e:
            print(f"⚠️ Erreur iter_messages: {e}")
        await asyncio.sleep(0.4)
    return None


async def get_recent_messages(client: TelegramClient, bot: str, limit: int = 10) -> List[Message]:
    try:
        messages = []
        async for message in client.iter_messages(bot, limit=limit):
            messages.append(message)
        return messages
    except Exception as e:
        print(f"⚠️ Erreur get_recent_messages: {e}")
        return []


# ======================
# EMOJI DETECTION HELPERS
# ======================
_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001F5FF"
    "\U0001F600-\U0001F64F"
    "\U0001F680-\U0001F6FF"
    "\U0001F1E0-\U0001F1FF"
    "\U00002700-\U000027BF"
    "\U00002600-\U000026FF"
    "\U0001F900-\U0001F9FF"
    "]+",
    flags=re.UNICODE,
)


def contains_emoji(s: str) -> bool:
    if not s:
        return False
    return bool(_EMOJI_RE.search(s))


# ======================
# Collecte rapide du texte de commentaire (maintenant accepte emoji-only)
# ======================
async def fast_collect_comment_text(client: TelegramClient, bot: str, after_id: int, timeout_sec: int = 20) -> Optional[str]:
    start = time.time()
    while time.time() - start < timeout_sec:
        recent_messages = await get_recent_messages(client, bot, 10)
        for msg in recent_messages:
            if msg.id <= after_id:
                continue
            body = (msg.message or "").strip()
            if not body:
                continue
            if is_thankyou_message(body) or looks_like_task_block(body):
                continue
            if body in {"Instagram", "📝Tasks📝", "🔙Back", "✅Completed", "❌Skip"} or body.startswith('@'):
                continue
            low = body.lower()
            if any(x in low for x in ["http", "www.", "instagram.com/p/", "link", "action", "reward", "cashcoins"]):
                continue
            if re.search(r"\w", body) or contains_emoji(body):
                print(f"✅ Texte de commentaire trouvé (next message id {msg.id}): {body}")
                return body
        await asyncio.sleep(0.4)
    print("❌ Timeout: Texte de commentaire non trouvé")
    return None


# ======================
# UTILITAIRES INSTAGRAM & PARSING
# ======================
def normalize_instagram_profile(link: str) -> str:
    if not link:
        return ""
    link = link.strip()
    if "instagram.com" not in link:
        return link.strip().lstrip("@")
    link = re.sub(r"\?.*$", "", link)
    u = urlparse(link.replace(" ", ""))
    username = u.path.strip("/").split("/")[0]
    return username.strip().lstrip("@")


def parse_task_message(text: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    if not text:
        return None, None, None
    if is_thankyou_message(text):
        return None, None, None
    if "no active tasks" in text.lower():
        return None, None, None

    action_match = re.search(r"(?:^|\n)\s*(?:▪️\s*)?(action|task)\s*[:\-]\s*([^\n]+)", text, re.IGNORECASE)
    link_match = re.search(r"(?:^|\n)\s*(?:▪️\s*)?(link|url)\s*[:\-]\s*([^\s]+)", text, re.IGNORECASE)

    action = action_match.group(2).strip() if action_match else None
    link = link_match.group(2).strip() if link_match else None

    if link and not link.startswith(("http://", "https://", "@")):
        link = f"https://instagram.com/{link.lstrip('@')}"

    comment_text = None
    if action and ("comment" in action.lower() or "leave the comment" in action.lower()):
        copy_patterns = [
            r"(?:copier|copy)\s*[:\-]?\s*\n([^\n]+)",
            r"(?:copier|copy)\s*[:\-]?\s*([^\n]+)",
            r"\"([^\"]+)\"",
            r"'([^']+)'",
        ]
        for pattern in copy_patterns:
            comment_match = re.search(pattern, text, re.IGNORECASE)
            if comment_match:
                candidate = comment_match.group(1).strip()
                if candidate.startswith('@'):
                    continue
                if len(candidate) >= 3 or contains_emoji(candidate):
                    comment_text = candidate
                    print(f"✅ Texte de commentaire extrait (inline): {comment_text}")
                    break
    return action, link, comment_text


# ======================
# ERREURS IG
# ======================
def handle_instagram_error(username: str, error: Exception) -> bool:
    error_msg = str(error).lower()
    acc_state = ensure_account_state(username)
    # on challenge ou vérification -> skip durable
    if any(x in error_msg for x in ["challenge", "phone", "sms", "verify", "confirmation", "checkpoint"]):
        skip_until = time.time() + SKIP_DURATION
        acc_state["skip_until"] = skip_until
        save_state()
        print(f"❌ Challenge requis pour {username} - skip jusqu'à {datetime.utcfromtimestamp(skip_until)}")
        return False
    # throttling / wait messages -> backoff + skip short
    if any(x in error_msg for x in ["wait", "minutes", "temporarily", "temporary", "try again later"]):
        acc_state["skip_until"] = time.time() + 300  # 5 minutes
        save_state()
        print(f"⏳ Attente requise pour {username} - skip 5 minutes")
        return False
    if any(x in error_msg for x in ["problem with your request", "request", "connection", "network"]):
        print(f"⚠️ Problème réseau pour {username} - réessayer plus tard")
        return True
    print(f"⚠️ Erreur IG inconnue pour {username}: {error_msg[:120]} - réessayer plus tard")
    return True


def cleanup_skip_list():
    current_time = time.time()
    expired = [a for a, t in SKIP_ACCOUNTS.items() if current_time - t > SKIP_DURATION]
    for a in expired:
        del SKIP_ACCOUNTS[a]
        print(f"✅ Compte {a} retiré des skipés")
    # aussi nettoyer state skip_until expirés
    changed = False
    for user, st in STATE.get("accounts", {}).items():
        if st.get("skip_until", 0) and current_time > st["skip_until"]:
            st["skip_until"] = 0
            changed = True
            print(f"✅ Compte {user} retiré du skip persistant")
    if changed:
        save_state()


def save_last_account(username: str):
    try:
        with open(LAST_ACCOUNT_FILE, "w") as f:
            f.write(username)
    except:
        pass


def load_last_account() -> Optional[str]:
    if os.path.exists(LAST_ACCOUNT_FILE):
        try:
            with open(LAST_ACCOUNT_FILE, "r") as f:
                return f.read().strip()
        except:
            return None
    return None


# ======================
# SESSIONS INSTAGRAM
# ======================
def get_ig_session(username: str) -> Optional[InstaClient]:
    acc_state = ensure_account_state(username)
    # check persistent skip
    if acc_state.get("skip_until", 0) and time.time() < acc_state["skip_until"]:
        remaining = int((acc_state["skip_until"] - time.time()) / 60)
        print(f"⏭️ Compte {username} skipé (persistant, {remaining} minutes restants)")
        return None

    if username in SKIP_ACCOUNTS:
        skip_time = SKIP_ACCOUNTS[username]
        if time.time() - skip_time < SKIP_DURATION:
            remaining = int((SKIP_DURATION - (time.time() - skip_time)) / 60)
            print(f"⏭️ Compte {username} skipé ({remaining} minutes)")
            return None
        else:
            del SKIP_ACCOUNTS[username]

    if username in INSTA_SESSIONS:
        return INSTA_SESSIONS[username]

    pwd = INSTA_PASSWORDS.get(username)
    if not pwd:
        print(f"❌ Aucun mot de passe pour {username}")
        return None

    cl = InstaClient()
    try:
        cl.set_locale("fr_FR")
        cl.set_country("FR")
        cl.set_country_code(33)
        cl.set_timezone_offset(3600)
        cl.set_device({
            "app_version": "200.0.0.30.128",
            "android_version": 26,
            "android_release": "8.0.0",
            "dpi": "480dpi",
            "resolution": "1080x1920",
            "manufacturer": "samsung",
            "device": "SM-G935F",
            "model": "herolte",
            "cpu": "samsungexynos8890"
        })
        try:
            cl.load_settings(f"session_{username}.json")
        except:
            pass
        cl.login(username, pwd)
        cl.dump_settings(f"session_{username}.json")
        INSTA_SESSIONS[username] = cl
        print(f"✅ Connecté à Instagram: {username}")
        return cl
    except (ChallengeRequired, PleaseWaitFewMinutes) as e:
        print(f"❌ Challenge/Wait pour {username}: {e}")
        handle_instagram_error(username, e)
        return None
    except Exception as e:
        print(f"❌ Erreur connexion IG {username}: {e}")
        handle_instagram_error(username, e)
        return None


async def do_instagram_action(cl: InstaClient, action: str, link: str, comment_text: Optional[str]) -> bool:
    print(f"🛠️ Tentative d'action: {action} sur {link}")
    for attempt in range(3):
        try:
            a_low = (action or "").lower()
            await asyncio.sleep(random.uniform(*ACTION_DELAY))
            if "follow" in a_low:
                target = normalize_instagram_profile(link)
                if not target:
                    print("❌ Username introuvable")
                    return False
                try:
                    user_id = cl.user_id_from_username(target)
                    cl.user_follow(user_id)
                    print(f"👤 Follow réussi: @{target}")
                    return True
                except Exception as e1:
                    print(f"❌ Follow erreur: {e1}")
                    try:
                        info = cl.user_info_by_username(target)
                        user_id = info.pk
                        cl.user_follow(user_id)
                        print(f"👤 Follow réussi (fallback): @{target}")
                        return True
                    except Exception as e2:
                        print(f"❌ Follow fallback erreur: {e2}")
                        # certain errors indicate account problems
                        handle_instagram_error(getattr(cl, "username", "unknown"), e2)
                        return False

            if "like" in a_low:
                media_pk = cl.media_pk_from_url(link)
                cl.media_like(media_pk)
                print(f"❤️ Like réussi (pk={media_pk})")
                return True

            if "comment" in a_low or "leave the comment" in a_low:
                media_pk = cl.media_pk_from_url(link)
                text = (comment_text or "").strip()
                if not text:
                    print("⚠️ Commentaire vide: on annule")
                    return False
                cl.media_comment(media_pk, text)
                print(f"💬 Commentaire posté: {text[:140]}")
                return True

            print(f"⚠️ Action inconnue: {action}")
            return False

        except FeedbackRequired as e:
            print(f"❌ FeedbackRequired: {e}")
            if attempt == 0:
                await asyncio.sleep(3)
                continue
            else:
                return False
        except PleaseWaitFewMinutes as e:
            print(f"❌ PleaseWaitFewMinutes: {e}")
            handle_instagram_error(getattr(cl, "username", "unknown"), e)
            return False
        except ClientConnectionError as e:
            print(f"❌ ClientConnectionError: {e}")
            if attempt == 0:
                await asyncio.sleep(2 ** attempt)
                continue
            else:
                return False
        except Exception as e:
            print(f"❌ Erreur action IG: {e}")
            if attempt == 0:
                await asyncio.sleep(1)
                continue
            else:
                # escalate unknown errors to handler to possibly mark skip
                handle_instagram_error(getattr(cl, "username", "unknown"), e)
                return False
    return False


# ======================
# Recherche du bloc tâche précédent (entre baseline_id et after_msg_id)
# ======================
async def find_prev_task_before_message(
    client: TelegramClient,
    bot: str,
    after_msg_id: int,
    baseline_id: int = 0,
    lookback: int = 80,
    require_comment: bool = False
) -> Optional[Message]:
    try:
        msgs = []
        async for m in client.iter_messages(bot, limit=lookback, min_id=baseline_id + 1, max_id=after_msg_id - 1):
            msgs.append(m)
        if not msgs:
            return None
        msgs.sort(key=lambda x: x.id, reverse=True)
        for m in msgs:
            body = (m.message or "")
            if not body:
                continue
            if looks_like_task_block(body):
                if require_comment:
                    action, link, _ = parse_task_message(body)
                    if action and "comment" in (action or "").lower():
                        return m
                    else:
                        continue
                return m
        return None
    except Exception as e:
        print(f"⚠️ Erreur find_prev_task_before_message: {e}")
        return None


# ======================
# Vérification des tâches existantes au démarrage
# ======================
async def check_existing_tasks(client: TelegramClient) -> bool:
    print("🔍 Vérification des tâches existantes au démarrage...")
    try:
        messages = await client.get_messages(BOT_USERNAME, limit=80)
        now = datetime.utcnow()
        any_processed = False

        for msg in messages:
            if not msg.message:
                continue
            if not looks_like_task_block(msg.message):
                continue
            if EXISTING_TASK_WINDOW_SECONDS > 0:
                try:
                    age = (now - msg.date.replace(tzinfo=None)).total_seconds()
                except Exception:
                    age = 0
                if age > EXISTING_TASK_WINDOW_SECONDS:
                    continue

            print(f"✅ Tâche existante détectée (ID: {msg.id})")

            # essayer d'identifier le compte lié
            username_found = None
            async for prev in client.iter_messages(BOT_USERNAME, limit=30, max_id=msg.id - 1):
                if not prev.message:
                    continue
                body = (prev.message or "")
                if "please give us your profile's username" in body.lower() or "please give us your profile" in body.lower():
                    async for later in client.iter_messages(BOT_USERNAME, limit=10, min_id=prev.id, max_id=msg.id - 1):
                        body2 = (later.message or "").strip()
                        if not body2:
                            continue
                        if body2 in {"Instagram", "📝Tasks📝", "🔙Back", "✅Completed", "❌Skip"}:
                            continue
                        if body2 in INSTA_PASSWORDS:
                            username_found = body2
                            break
                        if re.match(r"^@?[A-Za-z0-9._]{3,30}$", body2):
                            cand = body2.lstrip("@")
                            if cand in INSTA_PASSWORDS:
                                username_found = cand
                                break
                    break

            if not username_found:
                last = load_last_account()
                if last and last in INSTA_PASSWORDS:
                    username_found = last

            if not username_found:
                print("⚠️ Impossible de déterminer le compte lié à la tâche existante")
                continue

            print(f"🔁 Utilisation du compte déterminé: {username_found}")

            action, link, comment_text = parse_task_message(msg.message or "")
            if not action or not link:
                print("⚠️ Impossible d'extraire action/link de la tâche existante")
                continue

            cl = get_ig_session(username_found)
            if not cl:
                print("⚠️ Pas de session IG valide pour ce compte -> envoi ❌Skip")
                await send_with_retry(client, BOT_USERNAME, "❌Skip")
                continue

            ok = await do_instagram_action(cl, action, link, comment_text)
            if ok:
                await send_with_retry(client, BOT_USERNAME, "✅Completed")
                print("✅ Completed envoyé pour la tâche existante")
                save_last_account(username_found)
                any_processed = True
                # update persistent state: last_msg_id processed
                acc = ensure_account_state(username_found)
                acc["last_msg_id"] = max(acc.get("last_msg_id", 0), msg.id)
                save_state()

                nxt = await wait_next_bot_message(client, BOT_USERNAME, msg.id, timeout_sec=8)
                if nxt and looks_like_task_block(nxt.message or ""):
                    print("🔁 Nouveau message reçu après Completed -> le main loop le traitera")
            else:
                await send_with_retry(client, BOT_USERNAME, "❌Skip")
                print("⏭️ Skip envoyé pour la tâche existante (échec action)")

        if any_processed:
            print("✅ Au moins une tâche existante traitée au démarrage")
        else:
            print("ℹ️ Aucune tâche existante traitée au démarrage")
        return any_processed
    except Exception as e:
        print(f"❌ Erreur check_existing_tasks: {e}")
        return False


# ======================
# Process per account
# ======================
async def process_account(client: TelegramClient, username: str, use_tasks_command: bool) -> bool:
    acc_state = ensure_account_state(username)
    # skip if persistent skip_until in future
    if acc_state.get("skip_until", 0) and time.time() < acc_state["skip_until"]:
        remaining = int((acc_state["skip_until"] - time.time()) / 60)
        print(f"⏭️ Compte {username} skipé (persistant, {remaining} minutes restants)")
        return False

    # envoyer menu si demandé
    if use_tasks_command:
        ok = await send_with_retry(client, BOT_USERNAME, "📝Tasks📝")
        if not ok:
            print("❌ Impossible d'envoyer '📝Tasks📝'")
            return False
        print("➡️ Envoyé: 📝Tasks📝")
        await asyncio.sleep(0.8)

    # baseline avant 'Instagram' - utiliser last_msg_id si présent pour éviter reprocess
    try:
        baseline_list = await client.get_messages(BOT_USERNAME, limit=1)
        baseline_id = baseline_list[0].id if baseline_list else 0
    except Exception as e:
        print(f"⚠️ Erreur récupération baseline id: {e}")
        baseline_id = 0

    # If we have a saved last_msg_id, use it as baseline to not reprocess older messages
    saved_last = acc_state.get("last_msg_id", 0)
    if saved_last and saved_last > baseline_id:
        baseline_id = saved_last
    print(f"📌 Baseline ID: {baseline_id}")

    # envoyer Instagram (toujours)
    ok = await send_with_retry(client, BOT_USERNAME, "Instagram")
    if not ok:
        print("❌ Impossible d'envoyer 'Instagram'")
        return False
    print("➡️ Envoyé: Instagram")
    await asyncio.sleep(0.8)

    # envoyer username
    sent_username_ok = await send_with_retry(client, BOT_USERNAME, username)
    if not sent_username_ok:
        print(f"❌ Impossible d'envoyer username {username}")
        return False
    print(f"➡️ Sélection du compte: {username}")

    # attendre réponse : 5s -> réessayer (resend username) -> wait 10s -> sinon next account
    response = await wait_next_bot_message(client, BOT_USERNAME, baseline_id, timeout_sec=5)
    if not response:
        print(f"⚠️ Pas de réponse après 5s suite à envoi username {username} -> réessai dans 10s")
        await asyncio.sleep(10)
        await send_with_retry(client, BOT_USERNAME, username)
        response = await wait_next_bot_message(client, BOT_USERNAME, baseline_id, timeout_sec=10)
        if not response:
            print(f"⚠️ Toujours pas de réponse après réessai -> on sort de ce compte")
            acc_state["consecutive_errors"] = acc_state.get("consecutive_errors", 0) + 1
            save_state()
            return False

    # récupérer messages après baseline_id
    try:
        msgs = []
        async for m in client.iter_messages(BOT_USERNAME, limit=80, min_id=baseline_id + 1):
            msgs.append(m)
    except Exception as e:
        print(f"⚠️ Erreur récupération messages: {e}")
        acc_state["consecutive_errors"] = acc_state.get("consecutive_errors", 0) + 1
        save_state()
        return False

    msgs.sort(key=lambda m: m.id, reverse=True)

    last_task_msg = None
    for m in msgs:
        if looks_like_task_block(m.message or ""):
            last_task_msg = m
            break

    if not last_task_msg:
        print("❌ Aucune tâche trouvée dans les nouveaux messages")
        for i, m in enumerate(msgs[:6]):
            print(f"Message {i} (ID:{m.id}): {(m.message or '')[:120]}")
        acc_state["consecutive_errors"] = 0
        save_state()
        return False

    print(f"🔍 Analyse du message (id {last_task_msg.id}):")
    print(f"{(last_task_msg.message or '')[:500]}")

    task_done_on_this_account = 0
    last_msg = last_task_msg

    while task_done_on_this_account < MAX_TASKS_PER_ACCOUNT:
        text = (last_msg.message or "")
        if "no active tasks" in text.lower() or "sorry, but there are no active tasks" in text.lower():
            print(f"ℹ️ Pas de tâche pour {username}")
            break

        if is_thankyou_message(text):
            print("🙏 Remerciement ignoré")
            nxt = await wait_next_bot_message(client, BOT_USERNAME, last_msg.id, timeout_sec=8)
            if not nxt:
                break
            last_msg = nxt
            continue

        action, link, comment_text_from_message = parse_task_message(text)

        if action and link:
            comment_text = None
            if "comment" in action.lower() or "leave the comment" in action.lower():
                if comment_text_from_message:
                    comment_text = comment_text_from_message
                    print(f"💬 Commentaire extrait du message: {comment_text[:120]}")
                else:
                    print("⏳ Tâche commentaire détectée -> recherche du texte de commentaire...")
                    comment_text = await fast_collect_comment_text(client, BOT_USERNAME, last_msg.id, timeout_sec=18)
                    if not comment_text:
                        print("⚠️ Impossible de récupérer le texte de commentaire -> debug recent messages:")
                        recent_msgs = await get_recent_messages(client, BOT_USERNAME, 8)
                        for m in recent_msgs:
                            if m.id > last_msg.id:
                                print(f"Msg (ID:{m.id}): {(m.message or '')[:140]}")

            cl = INSTA_SESSIONS.get(username) or get_ig_session(username)
            if not cl:
                print("⚠️ Pas de session IG valide -> envoi ❌Skip")
                await send_with_retry(client, BOT_USERNAME, "❌Skip")
                # mark skip in persistent state if repeated failures
                acc_state["consecutive_errors"] = acc_state.get("consecutive_errors", 0) + 1
                if acc_state["consecutive_errors"] >= 3:
                    acc_state["skip_until"] = time.time() + SKIP_DURATION
                    print(f"⏭️ {username} marqué skip pour {SKIP_DURATION//60} minutes (persistant)")
                save_state()
            else:
                ok = await do_instagram_action(cl, action, link, comment_text)
                if ok:
                    await send_with_retry(client, BOT_USERNAME, "✅Completed")
                    print("✅ Completed envoyé")
                    task_done_on_this_account += 1
                    save_last_account(username)
                    acc_state["consecutive_errors"] = 0
                    acc_state["last_msg_id"] = max(acc_state.get("last_msg_id", 0), last_msg.id)
                    save_state()
                else:
                    await send_with_retry(client, BOT_USERNAME, "❌Skip")
                    print("⏭️ Skip envoyé (échec action)")
                    acc_state["consecutive_errors"] = acc_state.get("consecutive_errors", 0) + 1
                    if acc_state["consecutive_errors"] >= 3:
                        acc_state["skip_until"] = time.time() + SKIP_DURATION
                        print(f"⏭️ {username} marqué skip pour {SKIP_DURATION//60} minutes (persistant)")
                    # still save last_msg_id to avoid infinite loop on same message
                    acc_state["last_msg_id"] = max(acc_state.get("last_msg_id", 0), last_msg.id)
                    save_state()

            nxt = await wait_next_bot_message(client, BOT_USERNAME, last_msg.id, timeout_sec=15)
            if not nxt:
                print("⌛️ Pas de nouveau message du bot -> sortie du compte")
                break
            last_msg = nxt
            continue

        # cas défaut -> attendre suivant
        nxt = await wait_next_bot_message(client, BOT_USERNAME, last_msg.id, timeout_sec=10)
        if not nxt:
            print("ℹ️ Rien de pertinent reçu -> sortie du compte")
            break
        last_msg = nxt

    if task_done_on_this_account >= MAX_TASKS_PER_ACCOUNT:
        print(f"⚠️ Limite locale atteinte ({MAX_TASKS_PER_ACCOUNT}) pour {username}")

    save_state()
    return True


# ======================
# INITIALISATION SESSIONS
# ======================
async def initialize_instagram_sessions():
    print("🔄 Initialisation des sessions Instagram...")
    for account in INSTA_ACCOUNTS:
        username = account["username"]
        acc_state = ensure_account_state(username)
        if acc_state.get("skip_until", 0) and time.time() < acc_state["skip_until"]:
            remaining = int((acc_state["skip_until"] - time.time()) / 60)
            print(f"⏭️ Compte {username} skipé ({remaining} minutes restants)")
            continue
        print(f"🔗 Connexion à Instagram: {username}")
        get_ig_session(username)
    print(f"✅ {len(INSTA_SESSIONS)} sessions Instagram initialisées")


# ======================
# BOUCLE PRINCIPALE
# ======================
async def main():
    load_state()
    client = TelegramClient("tg_session", API_ID, API_HASH)
    await client.start()
    print("✅ Connecté à Telegram")

    try:
        await client.get_entity(BOT_USERNAME)
    except Exception as e:
        print(f"❌ Impossible d'accéder au bot {BOT_USERNAME}: {e}")
        await client.disconnect()
        return

    await initialize_instagram_sessions()

    # vérifier tâches existantes au démarrage
    task_processed = await check_existing_tasks(client)

    idx = 0
    consecutive_errors = 0
    max_errors_before_pause = 3
    # si on a traité une tâche existante -> on commence directement par "Instagram" sans renvoyer "📝Tasks📝"
    use_tasks_command = not task_processed

    try:
        while True:
            cleanup_skip_list()
            if consecutive_errors >= max_errors_before_pause:
                print("⚠️ Trop d'erreurs consécutives -> pause 5s")
                await asyncio.sleep(5)
                consecutive_errors = 0
                use_tasks_command = True

            username = INSTA_ACCOUNTS[idx]["username"]
            print(f"\n=== Vérification du compte {username} ({idx+1}/{len(INSTA_ACCOUNTS)}) ===")

            acc_state = ensure_account_state(username)
            # skip if persistent skip set
            if acc_state.get("skip_until", 0) and time.time() < acc_state["skip_until"]:
                remaining = int((acc_state["skip_until"] - time.time()) / 60)
                print(f"⏭️ Compte {username} skipé ({remaining} minutes)")
                idx = (idx + 1) % len(INSTA_ACCOUNTS)
                continue

            try:
                ok = await process_account(client, username, use_tasks_command)
                if ok:
                    consecutive_errors = 0
                else:
                    consecutive_errors += 1
            except Exception as e:
                consecutive_errors += 1
                print(f"⚠️ Erreur durant traitement {username}: {e}")
                await asyncio.sleep(2)
                acc_state["consecutive_errors"] = acc_state.get("consecutive_errors", 0) + 1
                if acc_state["consecutive_errors"] >= 5:
                    acc_state["skip_until"] = time.time() + SKIP_DURATION
                    print(f"⏭️ {username} marqué skip (persistant) après erreurs répétées")
                save_state()

            use_tasks_command = False
            idx = (idx + 1) % len(INSTA_ACCOUNTS)
            if idx == 0:
                print("🔄 Fin de tour -> on recommence depuis le premier compte avec 'Instagram'")

            await asyncio.sleep(random.uniform(1.0, 2.0))

    except KeyboardInterrupt:
        print("\n⏹️ Arrêt demandé")
    finally:
        if client.is_connected():
            await client.disconnect()
            print("✅ Déconnecté de Telegram")


if __name__ == "__main__":
    asyncio.run(main())