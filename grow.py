
# Created By Itz_Akbar
# AKBAR GROW BOT
# Console: Finglish | Rubika Messages: Persian

import asyncio
import json
import logging
import os
import random
import secrets
import sqlite3
import time
from pathlib import Path

from rubka.asynco import Robot, filters


# ==================== CONFIG ====================

BOT_TOKEN = "CECDDC0IJKZYTSPZUPFKKNIGLOSMFGZGKIKBEDXDRQGSHXAGDTNUORWMSURFCRGN"

if not BOT_TOKEN:
    BOT_TOKEN = input("Lotfan token robot ro vared konid: ").strip()

if not BOT_TOKEN:
    raise ValueError("Token vared nashode!")

bot = Robot(BOT_TOKEN)

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "akbargrow.db"
USERS_PATH = BASE_DIR / "users.json"

COOLDOWN = 7200
MIN_GROW = 1
MAX_GROW = 10
STARTING_SIZE = 10

PVP_TIMEOUT = 600

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger("AkbarGrow")


# ==================== DATABASE ====================

def get_db():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_database():
    with get_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS pvp_challenges (
                code TEXT PRIMARY KEY,
                group_id TEXT NOT NULL,
                challenger_id TEXT NOT NULL,
                challenger_name TEXT NOT NULL,
                bet INTEGER NOT NULL,
                created_at REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
            )
        """)

        db.execute("""
            CREATE INDEX IF NOT EXISTS idx_pvp_group
            ON pvp_challenges(group_id, status)
        """)

    logger.info("Database amade ast.")


# ==================== USERS JSON ====================

def load_users():
    if not USERS_PATH.exists():
        return {"users": {}}

    try:
        with open(USERS_PATH, "r", encoding="utf-8") as file:
            data = json.load(file)

        if not isinstance(data, dict):
            raise ValueError("Format JSON eshtebah ast.")

        if not isinstance(data.get("users"), dict):
            data["users"] = {}

        return data

    except (json.JSONDecodeError, OSError, ValueError) as error:
        logger.error(f"Khata dar khondan users.json: {error}")

        backup_path = USERS_PATH.with_name("users_backup.json")

        try:
            if USERS_PATH.exists() and not backup_path.exists():
                USERS_PATH.replace(backup_path)
                logger.warning("Backup az users.json sakhte shod.")
        except OSError as backup_error:
            logger.error(f"Backup anjam nashod: {backup_error}")

        return {"users": {}}


user_data = load_users()


def save_users():
    temporary_path = USERS_PATH.with_suffix(".tmp")

    with open(temporary_path, "w", encoding="utf-8") as file:
        json.dump(
            user_data,
            file,
            ensure_ascii=False,
            indent=4
        )

    temporary_path.replace(USERS_PATH)


def get_user(user_id):
    user_id = str(user_id)

    if user_id not in user_data["users"]:
        user_data["users"][user_id] = {
            "username": f"user_{secrets.token_hex(3)}",
            "groups": {}
        }
        save_users()

    user = user_data["users"][user_id]

    # Baraye sazegar boodan ba JSON haye ghadimi
    if not user.get("username"):
        user["username"] = f"user_{secrets.token_hex(3)}"

    if not isinstance(user.get("groups"), dict):
        user["groups"] = {}

    return user


def get_username(user_id):
    return get_user(user_id)["username"]


def get_group_name(message, group_id):
    """
    Age esm group dar raw_data mojood bashe,
    save mishe. Dar gheire in surat az esm pishfarz estefade mishe.
    """
    raw_data = getattr(message, "raw_data", None)

    possible_keys = (
        "group_name",
        "group_title",
        "chat_name",
        "chat_title",
        "title",
        "name"
    )

    def search_name(value):
        if isinstance(value, dict):
            for key in possible_keys:
                found = value.get(key)
                if isinstance(found, str) and found.strip():
                    return found.strip()

            for nested in value.values():
                result = search_name(nested)
                if result:
                    return result

        elif isinstance(value, list):
            for nested in value:
                result = search_name(nested)
                if result:
                    return result

        return None

    name = search_name(raw_data)

    if name:
        return name

    # Agar ghablan esm group save shode, hamoon ro negah dar.
    for user in user_data["users"].values():
        group_info = user.get("groups", {}).get(str(group_id), {})
        saved_name = group_info.get("group_name")

        if saved_name and not saved_name.startswith("Group "):
            return saved_name

    return f"Group {group_id}"


def get_group_profile(user_id, group_id, group_name=None):
    """
    Username sarasar yekta ast.
    Size, cooldown va total_grows baraye har group joda ast.
    """
    user_id = str(user_id)
    group_id = str(group_id)

    user = get_user(user_id)
    groups = user["groups"]

    if group_id not in groups:
        groups[group_id] = {
            "group_name": group_name or f"Group {group_id}",
            "size": STARTING_SIZE,
            "total_grows": 0,
            "last_grow": 0
        }

    profile = groups[group_id]

    # Field haye zaroori ro baraye profile haye ghadimi ezafe mikonim.
    profile.setdefault("group_name", group_name or f"Group {group_id}")
    profile.setdefault("size", STARTING_SIZE)
    profile.setdefault("total_grows", 0)
    profile.setdefault("last_grow", 0)

    if group_name and profile["group_name"].startswith("Group "):
        profile["group_name"] = group_name

    return profile


def register_player(user_id, group_id, group_name=None):
    profile = get_group_profile(user_id, group_id, group_name)
    save_users()
    return profile


# ==================== OLD DATA MIGRATION ====================

def migrate_old_players():
    """
    Age database ghadimi jadval players dashte bashe,
    size va cooldown ghadimi ro be users.json montaghel mikone.
    Field coins estefade nemishe.
    """
    try:
        with get_db() as db:
            table = db.execute("""
                SELECT name
                FROM sqlite_master
                WHERE type='table' AND name='players'
            """).fetchone()

            if not table:
                return

            columns = {
                row["name"]
                for row in db.execute("PRAGMA table_info(players)").fetchall()
            }

            required = {
                "group_id",
                "user_id",
                "size",
                "total_grows",
                "last_grow"
            }

            if not required.issubset(columns):
                logger.warning(
                    "Jadval players schema motefavet dare; migration anjam nashod."
                )
                return

            rows = db.execute("""
                SELECT group_id, user_id, size, total_grows, last_grow
                FROM players
            """).fetchall()

        changed = False

        for row in rows:
            user_id = str(row["user_id"])
            group_id = str(row["group_id"])

            user = get_user(user_id)
            groups = user["groups"]

            if group_id not in groups:
                groups[group_id] = {
                    "group_name": f"Group {group_id}",
                    "size": int(row["size"] or STARTING_SIZE),
                    "total_grows": int(row["total_grows"] or 0),
                    "last_grow": float(row["last_grow"] or 0)
                }
                changed = True

        if changed:
            save_users()
            logger.info("Etelaate ghadimi be users.json montaghel shod.")

    except sqlite3.Error as error:
        logger.error(f"Migration anjam nashod: {error}")


# ==================== MESSAGE HELPERS ====================

async def reply_message(message, text):
    await bot.send_message(
        str(message.chat_id),
        text,
        reply_to_message_id=str(message.message_id)
    )


async def send_message(chat_id, text):
    await bot.send_message(str(chat_id), text)


def get_message_text(message):
    text = getattr(message, "text", None)
    return text.strip() if isinstance(text, str) else ""


def get_sender_id(message):
    sender_id = getattr(message, "sender_id", None)

    if sender_id is None:
        return None

    return str(sender_id)


def get_chat_id(message):
    chat_id = getattr(message, "chat_id", None)

    if chat_id is None:
        return None

    return str(chat_id)


def format_time(seconds):
    seconds = max(0, int(seconds))
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    remaining_seconds = seconds % 60

    if hours:
        return f"{hours} ساعت و {minutes} دقیقه"

    if minutes:
        return f"{minutes} دقیقه و {remaining_seconds} ثانیه"

    return f"{remaining_seconds} ثانیه"


# ==================== LEADERBOARD ====================

def get_group_players(group_id):
    group_id = str(group_id)
    result = []

    for user_id, user in user_data["users"].items():
        profile = user.get("groups", {}).get(group_id)

        if profile is None:
            continue

        result.append({
            "user_id": user_id,
            "username": user.get("username", "user_unknown"),
            "size": int(profile.get("size", STARTING_SIZE)),
            "total_grows": int(profile.get("total_grows", 0))
        })

    result.sort(
        key=lambda player: player["size"],
        reverse=True
    )

    return result


# ==================== COMMANDS ====================


async def handle_send(message, sender_id, group_id, profile, command_parts):
    if len(command_parts) != 3:
        await reply_message(
            message,
            "📤 روش استفاده:\n/send username amount\n\n"
            "مثال:\n/send user_sdffd 10"
        )
        return

    target_username = command_parts[1].strip().lstrip("@")

    try:
        amount = int(command_parts[2])
    except ValueError:
        await reply_message(message, "❌ هوی کله کی.ری مقدار انتقال باید عدد صحیح باشه!")
        return

    if amount <= 0:
        await reply_message(message, "❌ هوی کله کی.ری مقدار انتقال باید بیشتر از صفر باشه!")
        return

    sender_id = str(sender_id)
    group_id = str(group_id)

    sender_username = get_username(sender_id)

    if target_username == sender_username:
        await reply_message(message, "❌ خب ادم خوب میخوای از سانت خودت برای خودت بفرستی؟! کصخل.ی ؟")
        return

    target_id = None

    for uid, user in user_data["users"].items():
        if user.get("username", "").lower() == target_username.lower():
            if group_id in user.get("groups", {}):
                target_id = str(uid)
                break

    if target_id is None:
        await reply_message(
            message,
            "❌ این کاربر در بازی همین گروه پیدا نشد!"
        )
        return

    sender_size = int(profile.get("size", STARTING_SIZE))

    if sender_size < amount:
        await reply_message(
            message,
            f"❌ کله کی.ری انقد دول نداری هنوز!\n"
            f"📏 اندازه فعلی تو: {sender_size}"
        )
        return

    target_profile = get_group_profile(target_id, group_id)

    # Enteghal faghat dar hamin group anjam mishe.
    profile["size"] = sender_size - amount
    target_profile["size"] = int(target_profile.get("size", STARTING_SIZE)) + amount

    save_users()

    await reply_message(
        message,
        "✅ انتقال اندازه با موفقیت انجام شد!\n\n"
        f"👤 فرستنده: {sender_username}\n"
        f"👤 گیرنده: {target_username}\n"
        f"📤 مقدار انتقال: {amount}\n\n"
        f"📏 اندازه تو: {profile['size']}\n"
        f"📏 اندازه گیرنده: {target_profile['size']}"
    )







@bot.on_message(filters.text)
async def handle_message(bot, message):
    try:
        text = get_message_text(message)

        if not text:
            return

        chat_id = get_chat_id(message)
        user_id = get_sender_id(message)

        if not chat_id or not user_id:
            return

        command_parts = text.split()
        command = command_parts[0].lower()

        # Baghiye code ghabli az inja edame mishe



        # -------------------- START --------------------

        if command == "/start":
            await reply_message(
                message,
                "سلام! 👋\n\n"
                "به بازی AKBAR GROW خوش اومدی! 🌱\n\n"
                "دستورهای بازی:\n"
                "🌱 /grow - بزرگ شدن\n"
                "📊 /stats - آمار تو\n"
                "🏆 /top - رتبه‌بندی همین گروه\n"
                "⚔️ /pvp <اندازه> - دعوت به مبارزه\n"
                "✅ /accept <کد> - قبول مبارزه\n"
                "❓ /help - راهنما\n\n"
                "اطلاعات بازی هر گروه جداست."
            )
            return

        # -------------------- HELP --------------------

        if command in ("/help", "راهنما"):
            await reply_message(
                message,
                "📚 راهنمای بازی AKBAR GROW\n\n"
                "🌱 /grow\n"
                "اندازه‌ات رو افزایش می‌ده. هر ۲ ساعت یک بار می‌تونی رشد کنی.\n\n"
                "📊 /stats\n"
                "اندازه و آمار خودت در همین گروه.\n\n"
                "🏆 /top\n"
                "نمایش ۱۰ نفر برتر همین گروه.\n\n"
                "⚔️ /pvp 5\n"
                "دعوت به مبارزه با شرط ۵ واحد اندازه.\n\n"
                "✅ /accept CODE\n"
                "قبول کردن دعوت مبارزه.\n\n"
                "نکته: اندازه و زمان رشد هر گروه جداگانه محاسبه می‌شه."
            )
            return

        # -------------------- REGISTER --------------------

        group_name = get_group_name(message, chat_id)
        profile = register_player(user_id, chat_id, group_name)
        username = get_username(user_id)
        
        if command == "/send":
            await handle_send(
                message,
                user_id,
                chat_id,
                profile,
                command_parts
            )
            return


        # -------------------- GROW --------------------

        if command == "/grow":
            now = time.time()
            last_grow = float(profile.get("last_grow", 0))
            remaining = COOLDOWN - (now - last_grow)

            if remaining > 0:
                await reply_message(
                    message,
                    "⏳ هوی اروم اروم میخوای ختنت کنم؟!\n\n"
                    f"⏰ زمان باقی‌مونده: {format_time(remaining)}"
                )
                return

            growth = random.randint(MIN_GROW, MAX_GROW)

            profile["size"] = int(profile.get("size", STARTING_SIZE)) + growth
            profile["total_grows"] = int(
                profile.get("total_grows", 0)
            ) + 1
            profile["last_grow"] = now

            save_users()

            await reply_message(
                message,
                "🌱 رشد کردی!\n\n"
                f"👤 نام: {username}\n"
                f"📏 میزان رشد: +{growth}\n"
                f"📐 اندازه فعلی: {profile['size']}\n"
                f"🌿 تعداد رشدها در این گروه: {profile['total_grows']}\n\n"
                "⏰ برای رشد بعدی باید ۲ ساعت صبر کنی."
            )
            return

        # -------------------- STATS --------------------

        if command == "/stats":
            size = int(profile.get("size", STARTING_SIZE))
            total_grows = int(profile.get("total_grows", 0))
            last_grow = float(profile.get("last_grow", 0))
            remaining = COOLDOWN - (time.time() - last_grow)

            if remaining > 0:
                cooldown_text = format_time(remaining)
            else:
                cooldown_text = "آماده رشد ✅"

            players = get_group_players(chat_id)
            rank = next(
                (
                    index
                    for index, player in enumerate(players, start=1)
                    if player["user_id"] == user_id
                ),
                "-"
            )

            await reply_message(
                message,
                "📊 آمار تو در این گروه\n\n"
                f"👤 نام کاربری: {username}\n"
                f"🏷️ گروه: {profile['group_name']}\n"
                f"📏 اندازه: {size}\n"
                f"🌱 تعداد رشدها: {total_grows}\n"
                f"🏆 رتبه در گروه: {rank}\n"
                f"⏰ وضعیت رشد: {cooldown_text}"
            )
            return

        # -------------------- TOP --------------------

        if command == "/top":
            players = get_group_players(chat_id)

            if not players:
                await reply_message(
                    message,
                    "هنوز کسی در این گروه وارد بازی نشده!"
                )
                return

            lines = ["🏆 رتبه‌بندی AKBAR GROW\n"]

            for index, player in enumerate(players[:10], start=1):
                medal = {
                    1: "🥇",
                    2: "🥈",
                    3: "🥉"
                }.get(index, f"{index}.")

                lines.append(
                    f"{medal} {player['username']} — "
                    f"اندازه: {player['size']}"
                )

            lines.append("\n📍 این رتبه‌بندی فقط برای همین گروه است.")

            await reply_message(message, "\n".join(lines))
            return

        # -------------------- PVP CREATE --------------------

        if command == "/pvp":
            if len(command_parts) < 2:
                await reply_message(
                    message,
                    "⚔️ روش استفاده:\n"
                    "/pvp <اندازه>\n\n"
                    "مثال: /pvp 5"
                )
                return

            try:
                bet = int(command_parts[1])
            except ValueError:
                await reply_message(
                    message,
                    "❌ هوی عدد بنویس فهمیدی؟"
                )
                return

            if bet <= 0:
                await reply_message(
                    message,
                    "❌ د "
                )
                return

            current_size = int(profile.get("size", STARTING_SIZE))

            if current_size < bet:
                await reply_message(
                    message,
                    f"❌ دو.لت کمه بیشتر کن بعد\n"
                    f"📏 اندازه فعلی: {current_size}"
                )
                return

            code = secrets.token_hex(3).upper()

            with get_db() as db:
                db.execute("""
                    UPDATE pvp_challenges
                    SET status = 'expired'
                    WHERE group_id = ?
                      AND status = 'pending'
                      AND created_at < ?
                """, (chat_id, time.time() - PVP_TIMEOUT))

                db.execute("""
                    INSERT INTO pvp_challenges (
                        code,
                        group_id,
                        challenger_id,
                        challenger_name,
                        bet,
                        created_at,
                        status
                    )
                    VALUES (?, ?, ?, ?, ?, ?, 'pending')
                """, (
                    code,
                    chat_id,
                    user_id,
                    username,
                    bet,
                    time.time()
                ))

            await reply_message(
                message,
                "⚔️ دعوت مبارزه ساخته شد!\n\n"
                f"👤 مبارز: {username}\n"
                f"📏 اندازه شرط: {bet}\n"
                f"🔑 کد مبارزه: {code}\n\n"
                f"برای قبول کردن:\n"
                f"/accept {code}\n\n"
                "⏰ این دعوت تا ۱۰ دقیقه معتبره.\n"
                "🏆 برنده به اندازه شرط از بازنده اندازه می‌گیره."
            )
            return

        # -------------------- PVP ACCEPT --------------------

        if command == "/accept":
            if len(command_parts) < 2:
                await reply_message(
                    message,
                    "❌ کد مبارزه رو وارد کن.\n"
                    "مثال: /accept A1B2C3"
                )
                return

            code = command_parts[1].upper()

            with get_db() as db:
                challenge = db.execute("""
                    SELECT *
                    FROM pvp_challenges
                    WHERE code = ?
                      AND group_id = ?
                      AND status = 'pending'
                """, (code, chat_id)).fetchone()

                if challenge is None:
                    await reply_message(
                        message,
                        "❌ مبارزه پیدا نشد یا قبلاً تموم شده."
                    )
                    return

                if time.time() - float(challenge["created_at"]) > PVP_TIMEOUT:
                    db.execute("""
                        UPDATE pvp_challenges
                        SET status = 'expired'
                        WHERE code = ?
                    """, (code,))

                    await reply_message(
                        message,
                        "⌛ زمان این دعوت تموم شده!"
                    )
                    return

                challenger_id = str(challenge["challenger_id"])
                bet = int(challenge["bet"])

                if challenger_id == user_id:
                    await reply_message(
                        message,
                        "❌ نمی‌تونی دعوت خودت رو قبول کنی!"
                    )
                    return

                challenger_profile = get_group_profile(
                    challenger_id,
                    chat_id,
                    group_name
                )

                opponent_profile = profile

                challenger_size = int(
                    challenger_profile.get("size", STARTING_SIZE)
                )
                opponent_size = int(
                    opponent_profile.get("size", STARTING_SIZE)
                )

                if challenger_size < bet:
                    db.execute("""
                        UPDATE pvp_challenges
                        SET status = 'cancelled'
                        WHERE code = ?
                    """, (code,))

                    await reply_message(
                        message,
                        "❌ مبارزه لغو شد؛ اندازه مبارز برای شرط کافی نیست."
                    )
                    return

                if opponent_size < bet:
                    await reply_message(
                        message,
                        f"❌ هنوز انقد نداری\n"
                        f"📏 اندازه تو: {opponent_size}\n"
                        f"📏 اندازه موردنیاز: {bet}"
                    )
                    return

                # Challenge faghat yek bar mitone ejra beshe.
                db.execute("""
                    UPDATE pvp_challenges
                    SET status = 'completed'
                    WHERE code = ?
                      AND status = 'pending'
                """, (code,))

            # Barande entekhab mishe va bet az bazande kam mishe.
            challenger_wins = random.choice([True, False])

            challenger_name = challenge["challenger_name"]
            opponent_name = username

            if challenger_wins:
                challenger_profile["size"] = challenger_size + bet
                opponent_profile["size"] = opponent_size - bet
                winner_name = challenger_name
                loser_name = opponent_name
            else:
                opponent_profile["size"] = opponent_size + bet
                challenger_profile["size"] = challenger_size - bet
                winner_name = opponent_name
                loser_name = challenger_name

            save_users()

            await reply_message(
                message,
                "⚔️ نتیجه مبارزه!\n\n"
                f"👤 مبارز اول: {challenger_name}\n"
                f"👤 مبارز دوم: {opponent_name}\n\n"
                f"🏆 برنده: {winner_name}\n"
                f"💔 بازنده: {loser_name}\n"
                f"📏 اندازه منتقل‌شده: {bet}\n\n"
                f"📐 اندازه {challenger_name}: "
                f"{challenger_profile['size']}\n"
                f"📐 اندازه {opponent_name}: "
                f"{opponent_profile['size']}"
            )
            return

    except Exception as error:
        logger.exception(f"Khata dar handle_message: {error}")

        try:
            await reply_message(
                message,
                "❌ یه خطای داخلی رخ داد. دوباره امتحان کن."
            )
        except Exception:
            pass


# ==================== STARTUP ====================


async def main():
    init_database()
    migrate_old_players()

    logger.info("AKBAR GROW BOT dar hale ejra ast.")

    await bot.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot motوقف shod.")
