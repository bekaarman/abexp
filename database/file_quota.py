import datetime
import motor.motor_asyncio

from info import OTHER_DB_URI, DATABASE_NAME

client = motor.motor_asyncio.AsyncIOMotorClient(OTHER_DB_URI)
db = client[DATABASE_NAME]
quota_col = db["file_quota"]

PLAN_LIMITS = {
    "regular": 2,
    "premium": 3,
    "advanced": 5,
    "vip": None,  # unlimited
}

LIMIT_MESSAGE = (
    "<b>⛔ Your 24-hour file limit has been reached.</b>\n\n"
    "Please contact @Abv_384 to upgrade your plan."
)


async def get_plan(user_id):
    data = await quota_col.find_one({"_id": int(user_id)})

    if not data:
        return "regular"

    plan = data.get("plan", "regular")

    if plan not in PLAN_LIMITS:
        return "regular"

    return plan


async def set_plan(user_id, plan):
    plan = plan.lower()

    if plan not in PLAN_LIMITS:
        return False

    await quota_col.update_one(
        {"_id": int(user_id)},
        {
            "$set": {
                "plan": plan
            }
        },
        upsert=True
    )

    return True


async def remove_plan(user_id):
    await quota_col.update_one(
        {"_id": int(user_id)},
        {
            "$set": {
                "plan": "regular"
            }
        },
        upsert=True
    )


async def check_file(user_id):
    """
    Returns True if the user is allowed to receive one file.
    Returns False if the 24-hour limit has been reached.
    """

    user_id = int(user_id)
    plan = await get_plan(user_id)
    limit = PLAN_LIMITS[plan]

    # VIP = unlimited
    if limit is None:
        return True

    now = datetime.datetime.utcnow()
    cutoff = now - datetime.timedelta(hours=24)

    data = await quota_col.find_one({"_id": user_id})

    timestamps = []

    if data:
        timestamps = data.get("downloads", [])

    # Remove timestamps older than 24 hours
    timestamps = [
        t for t in timestamps
        if isinstance(t, datetime.datetime) and t > cutoff
    ]

    # Limit reached
    if len(timestamps) >= limit:
        await quota_col.update_one(
            {"_id": user_id},
            {
                "$set": {
                    "downloads": timestamps
                }
            },
            upsert=True
        )
        return False

    # Consume one file
    timestamps.append(now)

    await quota_col.update_one(
        {"_id": user_id},
        {
            "$set": {
                "downloads": timestamps,
                "plan": plan
            }
        },
        upsert=True
    )

    return True


async def get_quota(user_id):
    user_id = int(user_id)

    plan = await get_plan(user_id)
    limit = PLAN_LIMITS[plan]

    if limit is None:
        return plan, "Unlimited", 0

    now = datetime.datetime.utcnow()
    cutoff = now - datetime.timedelta(hours=24)

    data = await quota_col.find_one({"_id": user_id})

    timestamps = []

    if data:
        timestamps = data.get("downloads", [])

    timestamps = [
        t for t in timestamps
        if isinstance(t, datetime.datetime) and t > cutoff
    ]

    used = len(timestamps)
    remaining = max(0, limit - used)

    return plan, remaining, used
