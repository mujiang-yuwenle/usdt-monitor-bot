import os
import json
import time
import logging
import requests
import threading
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes
)

# ============================================================
# 配置
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
    return {"users": {}, "seen_txs": {}}

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

def add_address(data, user_id, address):
    uid = str(user_id)
    address = address.lower()
    if uid not in data["users"]:
        data["users"][uid] = []
    if address not in data["users"][uid]:
        data["users"][uid].append(address)
        if address not in data["seen_txs"]:
            data["seen_txs"][address] = []
        save_data(data)
        return True
    return False

def remove_address(data, user_id, address):
    uid = str(user_id)
    address = address.lower()
    if uid in data["users"] and address in data["users"][uid]:
        data["users"][uid].remove(address)
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
        "offset": 10,
        "apikey": ETHERSCAN_API_KEY,
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        if data["status"] == "1":
            return data["result"]
    except Exception as e:
        logger.error(f"查询失败: {e}")
    return []

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "👋 欢迎使用 ERC20 USDT 钱包监控Bot！\n\n"
        "📋 *可用命令：*\n"
        "➕ /add `地址` — 添加监控地址\n"
        "➖ /remove `地址` — 删除监控地址\n"
        "📋 /list — 查看我的监控列表\n\n"
        "💡 示例：\n`/add 0x1234...abcd`"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def add_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    user_id = update.effective_user.id
    if not context.args:
        await update.message.reply_text("❌ 请提供钱包地址\n示例：`/add 0x1234...abcd`", parse_mode="Markdown")
        return
    address = context.args[0].strip()
    if not address.startswith("0x") or len(address) != 42:
        await update.message.reply_text("❌ 地址格式不正确，ERC20地址应以 `0x` 开头，共42位", parse_mode="Markdown")
        return
    addresses = data["users"].get(str(user_id), [])
    if len(addresses) >= 10:
        await update.message.reply_text("❌ 最多只能监控10个地址")
        return
    if add_address(data, user_id, address):
        await update.message.reply_text(
            f"✅ 添加成功！\n\n📍 监控地址：`{address}`\n🔔 有新的USDT转账会立即通知你",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text("⚠️ 该地址已在监控列表中")

async def remove_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    user_id = update.effective_user.id
    if not context.args:
        await update.message.reply_text("❌ 请提供要删除的地址\n示例：`/remove 0x1234...abcd`", parse_mode="Markdown")
        return
    address = context.args[0].strip()
    if remove_address(data, user_id, address):
        await update.message.reply_text(f"✅ 已删除监控地址：\n`{address}`", parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ 该地址不在你的监控列表中")

async def list_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    user_id = update.effective_user.id
    addresses = data["users"].get(str(user_id), [])
    if not addresses:
        await update.message.reply_text("📋 你还没有添加任何监控地址\n使用 `/add 地址` 添加", parse_mode="Markdown")
        return
    lines = ["📋 *你的监控地址列表：*\n"]
    for i, addr in enumerate(addresses, 1):
        lines.append(f"{i}. `{addr}`")
    lines.append(f"\n共 {len(addresses)} 个地址")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

def monitor_loop(app):
    import asyncio
    logger.info("监控线程启动...")
    while True:
        try:
            data = load_data()
            address_users = {}
            for uid, addresses in data["users"].items():
                for addr in addresses:
                    if addr not in address_users:
                        address_users[addr] = []
                    address_users[addr].append(uid)

            for address, user_ids in address_users.items():
                txs = get_usdt_transactions(address)
                seen = data["seen_txs"].get(address, [])
                for tx in txs:
                    tx_hash = tx["hash"]
                    if tx_hash in seen:
                        continue
                    seen.append(tx_hash)
                    data["seen_txs"][address] = seen[-200:]
                    save_data(data)

                    to_addr = tx["to"].lower()
                    from_addr = tx["from"].lower()
                    amount = int(tx["value"]) / 1_000_000

                    if to_addr == address:
                        direction = "📥 收入"
                        counterpart_label = "付款方"
                        counterpart = from_addr
                    else:
                        direction = "📤 支出"
                        counterpart_label = "收款方"
                        counterpart = to_addr

                    msg = (
                        f"🔔 *ERC20 USDT 交易通知*\n\n"
                        f"{direction}：`{amount:,.2f}` USDT\n"
                        f"📍 监控地址：`{address}`\n"
                        f"👤 {counterpart_label}：`{counterpart}`\n"
                        f"🔗 [查看交易](https://etherscan.io/tx/{tx_hash})\n"
                        f"⏰ 时间：{time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(int(tx['timeStamp'])))}"
                    )

                    for uid in user_ids:
                        try:
                            asyncio.run_coroutine_threadsafe(
                                app.bot.send_message(
                                    chat_id=int(uid),
                                    text=msg,
                                    parse_mode="Markdown",
                                    disable_web_page_preview=True
                                ),
                                app.loop
                            )
                        except Exception as e:
                            logger.error(f"发送消息失败: {e}")
                time.sleep(1)
        except Exception as e:
            logger.error(f"监控循环异常: {e}")
        time.sleep(CHECK_INTERVAL)

def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(CommandHandler("add", add_cmd))
    app.add_handler(CommandHandler("remove", remove_cmd))
    app.add_handler(CommandHandler("list", list_cmd))

    monitor_thread = threading.Thread(target=monitor_loop, args=(app,), daemon=True)
    monitor_thread.start()

    logger.info("Bot 启动中...")
    app.run_polling()

if __name__ == "__main__":
    main()
