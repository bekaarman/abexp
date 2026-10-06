from datetime import datetime, timedelta, timezone
from pymongo import MongoClient

from info import OTHER_DB_URI, DATABASE_NAME

client = MongoClient(OTHER_DB_URI)
db = client[DATABASE_NAME]

quota_col = db["FILE_QUOTA"]

PLAN_LIMITS = {
    "regular": 2,
    "premium": 3,
    "advanced": 5,
    "vip": None,  # unlimited
}

LIMIT_MESSAGE = (
    "⚠️ <b>Your 24-hour file limit has been reached.</b>\n\n"
    "Please contact <a href='https://t.me/Abv_384'>@Abv_384</a> "
    "to upgrade your plan."
)


def _now():
    return datetime.now(timezone.utc)


def _clean_timestamps(timestamps):
    cutoff = _now() - timedelta(hours=24)
    return [t for t in timestamps if t > cutoff]


async def get_user_plan(user_id):
    data = quota_col.find_one({"_id": int(user_id)})

    if not data:
        return "regular"

    return data.get("plan", "regular").lower()


async def set_user_plan(user_id, plan):
    plan = plan.lower()

    if plan not in PLAN_LIMITS:
        return False

    quota_col.update_one(
        {"_id": int(user_id)},
        {
            "$set": {
                "plan": plan
            },
            "$setOnInsert": {
                "timestamps": []
            }
        },
        upsert=True
    )

    return True


async def remove_user_plan(user_id):
    quota_col.update_one(
        {"_id": int(user_id)},
        {
            "$set": {
                "plan": "regular"
            }
        },
        upsert=True
    )

    return True


async def check_and_consume_file(user_id):
    """
    Returns:
        True  -> user can receive the file
        False -> 24-hour limit reached
    """

    user_id = int(user_id)
    plan = await get_user_plan(user_id)
    limit = PLAN_LIMITS.get(plan, 2)

    # VIP = unlimited
    if limit is None:
        return True

    data = quota_col.find_one({"_id": user_id}) or {}
    timestamps = data.get("timestamps", [])

    timestamps = _clean_timestamps(timestamps)

    if len(timestamps) >= limit:
        quota_col.update_one(
            {"_id": user_id},
            {
                "$set": {
                    "timestamps": timestamps,
                    "plan": plan
                }
            },
            upsert=True
        )
        return False

    timestamps.append(_now())

    quota_col.update_one(
        {"_id": user_id},
        {
            "$set": {
                "timestamps": timestamps,
                "plan": plan
            }
        },
        upsert=True
    )

    return True


async def get_quota(user_id):
    user_id = int(user_id)

    plan = await get_user_plan(user_id)
    limit = PLAN_LIMITS.get(plan, 2)

    data = quota_col.find_one({"_id": user_id}) or {}
    timestamps = _clean_timestamps(data.get("timestamps", []))

    used = len(timestamps)

    if limit is None:
        remaining = "Unlimited"
    else:
        remaining = max(0, limit - used)

    return {
        "plan": plan,
        "limit": limit,
        "used": used,
        "remaining": remaining
    }


async def quota_message_if_blocked(user_id):
    allowed = await check_and_consume_file(user_id)

    if not allowed:
        return LIMIT_MESSAGE

    return None
