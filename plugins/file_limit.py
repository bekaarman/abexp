from datetime import datetime, timedelta
from pyrogram import Client, filters
from pyrogram.types import Message
from info import ADMINS
from database.users_chats_db import db

# Tier limits mapping
LIMITS = {
    "regular": 2,
    "premium": 3,
    "advanced": 5,
    "vip": float("inf")
}

# --- Database Limit Helper ---
async def check_and_update_limit(user_id: int):
    now = datetime.utcnow()
    user = await db.col.find_one({"id": int(user_id)})

    if not user:
        await db.col.insert_one({
            "id": int(user_id),
            "plan_tier": "regular",
            "daily_count": 1,
            "reset_time": now
        })
        return True, 1, LIMITS["regular"], 24

    tier = user.get("plan_tier", "regular")
    limit = LIMITS.get(tier, 2)
    reset_time = user.get("reset_time", now)

    # Reset counter if 24 hours have elapsed
    if now - reset_time > timedelta(hours=24):
        await db.col.update_one(
            {"id": int(user_id)},
            {"$set": {"reset_time": now, "daily_count": 1}}
        )
        return True, 1, limit, 24

    current_count = user.get("daily_count", 0)

    # Block if limit reached
    if current_count >= limit:
        hours_left = max(1, int((reset_time + timedelta(hours=24) - now).total_seconds() // 3600))
        return False, current_count, limit, hours_left

    # Increment counter for valid download
    await db.col.update_one(
        {"id": int(user_id)},
        {"$inc": {"daily_count": 1}}
    )
    hours_left = max(1, int((reset_time + timedelta(hours=24) - now).total_seconds() // 3600))
    return True, current_count + 1, limit, hours_left


# --- High-Priority Interceptor for /start deep-links ---
# group=-1 ensures this runs BEFORE standard start handlers in commands.py
@Client.on_message(filters.command("start") & filters.private, group=-1)
async def intercept_file_delivery(client: Client, message: Message):
    # Only intercept if start includes deep-link payload (e.g. /start file_id)
    if len(message.command) <= 1:
        return  # Lets default welcome message handle standard /start

    user_id = message.from_user.id
    allowed, count, limit, hours_left = await check_and_update_limit(user_id)

    if not allowed:
        limit_text = (
            f"❌ <b>Daily Limit Reached!</b>\n\n"
            f"Files used: <b>{count}/{limit}</b>\n"
            f"Reset in: <b>{hours_left} hour(s)</b>\n\n"
            f"💳 <b>Available Plans:</b>\n"
            f"• Regular: 2 files/24h\n"
            f"• Premium: 3 files/24h\n"
            f"• Advanced: 5 files/24h\n"
            f"• VIP: Unlimited\n\n"
            f"Contact Admin to upgrade your tier."
        )
        await message.reply_text(limit_text, parse_mode="html")
        # Halts further handlers from triggering file sending
        message.stop_propagation()


# --- Admin Management Helper ---
async def manage_tier(client: Client, message: Message, target_tier: str, limit_str: str):
    if message.from_user.id not in ADMINS:
        return await message.reply_text("❌ Only admins can execute this command.")

    args = message.text.split()[1:]
    if not args or args[0].lower() == "list":
        cursor = db.col.find({"plan_tier": target_tier})
        users = [f"<code>{u.get('id')}</code>" async for u in cursor]
        text = (
            f"📋 <b>{target_tier.upper()} Tier Users ({limit_str}):</b>\n\n" +
            ("\n".join(users) if users else "No active users in this tier.")
        )
        return await message.reply_text(text, parse_mode="html")

    action = args[0].lower()
    if len(args) < 2 or not args[1].isdigit():
        return await message.reply_text(
            f"Usage: <code>/{target_tier} add &lt;user_id&gt;</code> or <code>/{target_tier} remove &lt;user_id&gt;</code>"
        )

    target_id = int(args[1])
    if action == "add":
        await db.col.update_one({"id": target_id}, {"$set": {"plan_tier": target_tier}}, upsert=True)
        await message.reply_text(f"✅ User <code>{target_id}</code> moved to <b>{target_tier.upper()}</b> ({limit_str}).")
        try:
            await client.send_message(
                target_id,
                f"🎉 <b>Plan Updated!</b>\nYou are now in the <b>{target_tier.upper()}</b> tier ({limit_str})."
            )
        except Exception:
            pass
    elif action == "remove":
        await db.col.update_one({"id": target_id}, {"$set": {"plan_tier": "regular"}})
        await message.reply_text(f"✅ User <code>{target_id}</code> reset to <b>Regular Tier</b> (2 files/24h).")
    else:
        await message.reply_text("❌ Invalid action. Use: <code>add</code>, <code>remove</code>, or <code>list</code>.")


# --- Admin Commands ---
@Client.on_message(filters.command("premium"))
async def premium_handler(client: Client, message: Message):
    await manage_tier(client, message, "premium", "3 files/24h")

@Client.on_message(filters.command("advanced"))
async def advanced_handler(client: Client, message: Message):
    await manage_tier(client, message, "advanced", "5 files/24h")

@Client.on_message(filters.command("vip"))
async def vip_handler(client: Client, message: Message):
    await manage_tier(client, message, "vip", "Unlimited")
