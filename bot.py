import os
import json
import time
import logging
import requests
import asyncio
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# ============================================================
TELEGRAM_TOKEN = "8169628717:AAHIag1akpSmkccr_BJyVz4Yp7L75YNZawo"
ETHERSCAN_API_KEY = "FS2V6JFGBBQH4RAMCJXNI64YVR8HH3APHS"
USDT_CONTRACT = "0xdAC17F958D2ee523a2206206994597C13D831ec7"
DATA_FILE = "data.json"
CHECK_INTERVAL = 30
# ============================================================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {"users": {}, "seen_txs": {}, "daily": {}, "labels": {}}

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

def get_user_data(data, user_id):
    uid = str(user_id)
    if uid not in data["users"]:
        data["users"][uid] = {}
    return data["users"][uid]

def add_address(data, user_id, address, label=""):
    uid = str(user_id)
    address = address.lower()
    if uid not in data["users"]:
        data["users"][uid] = {}
    if address not in data["users"][uid]:
        data["users"][uid][address] = label or address[:8] + "..."
        if address not in data["seen_txs"]:
            data["seen_txs"][address] = []
        save_data(data)
        return True
    return False

def remove_address(data, user_id, address):
    uid = str(user_id)
    address = address.lower()
    if uid in data["users"] and address in data["users"][uid]:
        del data["users"][uid][address]
        save_data(data)
        return True
    return False

def rename_address(data, user_id, address, label):
    uid = str(user_id)
    address = address.lower()
    if uid in data["users"] and address in data["users"][uid]:
        data["users"][uid][address] = label
        save_data(data)
        return True
    return False

def get_usdt_transactions(address):
    url = "https://api.etherscan.io/api"
    params = {
        "module": "account",
        "action": "tokentx",
        "contractaddress": USDT_CONTRACT,
        "address": address,
        "sort": "desc",
        "page": 1,
        "offset": 20,
        "apikey": ETHERSCAN_API_KEY,
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        d = resp.json()
        if d["status"] == "1":
            return d["result"]
    except Exception as e:
        logger.error(f"查询失败: {e}")
    return []

def get_usdt_balance(address):
    url = "https://api.etherscan.io/api"
    params = {
        "module": "account",
        "action": "tokenbalance",
        "contractaddress": USDT_CONTRACT,
        "address": address,
        "tag": "latest",
        "apikey": ETHERSCAN_API_KEY,
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        d = resp.json()
        if d["status"] == "1":
            return int(d["result"]) / 1_000_000
    except:
        pass
    return 0

def get_today_key():
    return time.strftime("%Y-%m-%d", time.gmtime())

def update_daily(data, address, amount, is_income):
    today = get_today_key()
    if "daily" not in data:
        data["daily"] = {}
    if address not in data["daily"]:
        data["daily"][address] = {}
    if today not in data["daily"][address]:
        data["daily"][address][today] = {"income": 0, "outcome": 0}
    if is_income:
        data["daily"][address][today]["income"] += amount
    else:
        data["daily"][address][today]["outcome"] += amount

def get_daily_stats(data, address):
    today = get_today_key()
    stats = data.get("daily", {}).get(address, {}).get(today, {"income": 0, "outcome": 0})
    return stats["income"], stats["outcome"]

def format_amount(amount):
    if amount < 0:
        sign = "-"
        amount = abs(amount)
    else:
        sign = ""
    integer = int(amount)
    decimal = round((amount - integer) * 100)
    if decimal > 0:
        return f"{sign}{integer:,}点{decimal:02d}"
    return f"{sign}{integer:,}"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "👋 欢迎使用 ERC20 USDT 钱包监控Bot！\n\n"
        "📋 *可用命令：*\n"
        "➕ /add `地址` `备注名` — 添加监控地址（备注可选）\n"
        "✏️ /rename `地址` `新备注` — 修改地址备注\n"
        "➖ /remove `地址` — 删除监控地址\n"
        "📋 /list — 查看我的监控列表\n\n"
        "💡 示例：\n"
        "`/add 0x1234...abcd 军饷`\n"
        "`/rename 0x1234...abcd 新备注`"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def add_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    user_id = update.effective_user.id
    if not context.args:
        await update.message.reply_text(
            "❌ 请提供钱包地址\n示例：`/add 0x1234...abcd 军饷`", parse_mode="Markdown")
        return
    address = context.args[0].strip()
    label = " ".join(context.args[1:]) if len(context.args) > 1 else ""
    if not address.startswith("0x") or len(address) != 42:
        await update.message.reply_text("❌ 地址格式不正确，ERC20地址应以 `0x` 开头，共42位", parse_mode="Markdown")
        return
    user_addrs = data["users"].get(str(user_id), {})
    if len(user_addrs) >= 10:
        await update.message.reply_text("❌ 最多只能监控10个地址")
        return
    if add_address(data, user_id, address, label):
        display = label if label else address
        await update.message.reply_text(
            f"✅ 添加成功！\n\n📍 地址：`{address}`\n🏷 备注：{display}\n🔔 有新的USDT转账会立即通知你",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text("⚠️ 该地址已在监控列表中\n可用 `/rename 地址 新备注` 修改备注", parse_mode="Markdown")

async def rename_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    user_id = update.effective_user.id
    if len(context.args) < 2:
        await update.message.reply_text("❌ 示例：`/rename 0x1234...abcd 军饷`", parse_mode="Markdown")
        return
    address = context.args[0].strip()
    label = " ".join(context.args[1:])
    if rename_address(data, user_id, address, label):
        await update.message.reply_text(f"✅ 备注已更新：{label}", parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ 该地址不在你的监控列表中")

async def remove_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    user_id = update.effective_user.id
    if not context.args:
        await update.message.reply_text("❌ 示例：`/remove 0x1234...abcd`", parse_mode="Markdown")
        return
    address = context.args[0].strip()
    if remove_address(data, user_id, address):
        await update.message.reply_text(f"✅ 已删除：`{address}`", parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ 该地址不在你的监控列表中")

async def list_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    user_id = update.effective_user.id
    user_addrs = data["users"].get(str(user_id), {})
    if not user_addrs:
        await update.message.reply_text("📋 你还没有添加任何监控地址\n使用 `/add 地址 备注` 添加", parse_mode="Markdown")
        return
    lines = ["📋 *你的监控地址列表：*\n"]
    for i, (addr, label) in enumerate(user_addrs.items(), 1):
        lines.append(f"{i}. 🏷 *{label}*\n    `{addr}`")
    lines.append(f"\n共 {len(user_addrs)} 个地址")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def monitor_loop(app):
    logger.info("监控线程启动...")
    while True:
        try:
            data = load_data()
            # 收集所有地址和对应用户+备注
            address_info = {}  # addr -> [(uid, label), ...]
            for uid, addrs in data["users"].items():
                for addr, label in addrs.items():
                    if addr not in address_info:
                        address_info[addr] = []
                    address_info[addr].append((uid, label))

            for address, uid_labels in address_info.items():
                txs = get_usdt_transactions(address)
                seen = data["seen_txs"].get(address, [])

                for tx in txs:
                    tx_hash = tx["hash"]
                    if tx_hash in seen:
                        continue

                    seen.append(tx_hash)
                    data["seen_txs"][address] = seen[-200:]

                    to_addr = tx["to"].lower()
                    from_addr = tx["from"].lower()
                    amount = int(tx["value"]) / 1_000_000
                    is_income = (to_addr == address)

                    update_daily(data, address, amount, is_income)
                    save_data(data)

                    usdt_balance = get_usdt_balance(address)
                    today_income, today_outcome = get_daily_stats(data, address)
                    today_profit = today_income - today_outcome

                    if is_income:
                        tx_type = "收入 ⬇️"
                        counterpart_label = "支付地址"
                        counterpart = from_addr
                        amount_str = f"+ {format_amount(amount)} USDT"
                    else:
                        tx_type = "转出 ⬆️"
                        counterpart_label = "收款地址"
                        counterpart = to_addr
                        amount_str = f"- {format_amount(amount)} USDT"

                    short_hash = f"{tx_hash[:10]}...{tx_hash[-8:]}"
                    tx_time = time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(int(tx['timeStamp'])))
                    decoration = "✅✅✅✅✅✅✅✅✅✅"

                    for uid, label in uid_labels:
                        msg = (
                            f"交易金额：{amount_str}\n"
                            f"交易类型：{tx_type}\n"
                            f"收款地址：#{label.replace(' ','_')} `{address}`\n"
                            f"{counterpart_label}：`{counterpart}`\n"
                            f"交易哈希：`{short_hash}`\n"
                            f"USDT余额：{format_amount(usdt_balance)}\n"
                            f"转账时间：{tx_time}\n"
                            f"{decoration}\n"
                            f"今日收入(USDT)：{format_amount(today_income)}\n"
                            f"今日支出(USDT)：{format_amount(today_outcome)}\n"
                            f"今日利润(USDT)：{format_amount(today_profit)}"
                        )
                        try:
                            await app.bot.send_message(
                                chat_id=int(uid),
                                text=msg,
                                parse_mode="Markdown",
                                disable_web_page_preview=True
                            )
                        except Exception as e:
                            logger.error(f"发送消息失败: {e}")

                await asyncio.sleep(1)

        except Exception as e:
            logger.error(f"监控循环异常: {e}")

        await asyncio.sleep(CHECK_INTERVAL)

async def post_init(app):
    asyncio.create_task(monitor_loop(app))

def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(CommandHandler("add", add_cmd))
    app.add_handler(CommandHandler("rename", rename_cmd))
    app.add_handler(CommandHandler("remove", remove_cmd))
    app.add_handler(CommandHandler("list", list_cmd))
    logger.info("Bot 启动中...")
    app.run_polling()

if __name__ == "__main__":
    main()
