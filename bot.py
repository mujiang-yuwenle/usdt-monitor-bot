import os
import json
import time
import logging
import requests
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

# ============================================================
TELEGRAM_TOKEN = "8169628717:AAHIag1akpSmkccr_BJyVz4Yp7L75YNZawo"
ETHERSCAN_API_KEY = "FS2V6JFGBBQH4RAMCJXNI64YVR8HH3APHS"
USDT_CONTRACT = "0xdAC17F958D2ee523a2206206994597C13D831ec7"
DATA_FILE = "data.json"
CHECK_INTERVAL = 30
# ============================================================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 底部固定菜单
MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton("📋 监听列表"), KeyboardButton("💰 查询余额")],
        [KeyboardButton("➕ 添加地址"), KeyboardButton("➖ 删除地址")],
        [KeyboardButton("✏️ 修改备注"), KeyboardButton("📜 近期交易")],
    ],
    resize_keyboard=True,
    is_persistent=True
)

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {"users": {}, "seen_txs": {}, "daily": {}}

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

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

def get_usdt_transactions(address, offset=10):
    url = "https://api.etherscan.io/v2/api"
    params = {
        "chainid": 1,
        "module": "account",
        "action": "tokentx",
        "contractaddress": USDT_CONTRACT,
        "address": address,
        "sort": "desc",
        "page": 1,
        "offset": offset,
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
    url = "https://api.etherscan.io/v2/api"
    params = {
        "chainid": 1,
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

# ============================================================
# 发送监听列表
# ============================================================
async def send_list(message, user_id):
    data = load_data()
    user_addrs = data["users"].get(str(user_id), {})
    if not user_addrs:
        await message.reply_text(
            "📋 你还没有添加任何监控地址\n\n点击 ➕ 添加地址 或发送：\n`/add 0x地址 备注名`",
            parse_mode="Markdown",
            reply_markup=MAIN_KEYBOARD
        )
        return
    text = "📋 *监听地址列表*\n点击地址查看详情："
    keyboard = []
    for addr, label in user_addrs.items():
        short = f"{addr[:6]}...{addr[-4:]}"
        keyboard.append([InlineKeyboardButton(f"💰 {label} ({short})", callback_data=f"detail_{addr}")])
    await message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

# ============================================================
# 命令处理
# ============================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "👋 *欢迎使用 ERC20 USDT 钱包监控Bot！*\n\n"
        "使用下方菜单按钮操作，或直接发送命令：\n\n"
        "➕ `/add 地址 备注` — 添加监控地址\n"
        "✏️ `/rename 地址 新备注` — 修改备注\n"
        "➖ `/remove 地址` — 删除监控地址\n"
        "📋 `/list` — 查看监控列表\n"
        "💰 `/balance 地址` — 查询余额\n"
        "📜 `/txs 地址` — 查询近期交易"
    )
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=MAIN_KEYBOARD)

async def add_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    user_id = update.effective_user.id
    if not context.args:
        await update.message.reply_text(
            "➕ *添加监控地址*\n\n发送格式：\n`/add 0x地址 备注名`\n\n示例：\n`/add 0x1234...abcd 军饷`",
            parse_mode="Markdown", reply_markup=MAIN_KEYBOARD)
        return
    address = context.args[0].strip()
    label = " ".join(context.args[1:]) if len(context.args) > 1 else ""
    if not address.startswith("0x") or len(address) != 42:
        await update.message.reply_text("❌ 地址格式不正确，应以 `0x` 开头共42位", parse_mode="Markdown", reply_markup=MAIN_KEYBOARD)
        return
    user_addrs = data["users"].get(str(user_id), {})
    if len(user_addrs) >= 10:
        await update.message.reply_text("❌ 最多只能监控10个地址", reply_markup=MAIN_KEYBOARD)
        return
    if add_address(data, user_id, address, label):
        display = label if label else address
        await update.message.reply_text(
            f"✅ *添加成功！*\n\n📍 地址：`{address}`\n🏷 备注：{display}\n🔔 有新转账会立即通知",
            parse_mode="Markdown", reply_markup=MAIN_KEYBOARD)
    else:
        await update.message.reply_text("⚠️ 该地址已在监控列表中", reply_markup=MAIN_KEYBOARD)

async def rename_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    user_id = update.effective_user.id
    if len(context.args) < 2:
        await update.message.reply_text(
            "✏️ *修改备注*\n\n发送格式：\n`/rename 0x地址 新备注`",
            parse_mode="Markdown", reply_markup=MAIN_KEYBOARD)
        return
    address = context.args[0].strip()
    label = " ".join(context.args[1:])
    if rename_address(data, user_id, address, label):
        await update.message.reply_text(f"✅ 备注已更新：*{label}*", parse_mode="Markdown", reply_markup=MAIN_KEYBOARD)
    else:
        await update.message.reply_text("❌ 该地址不在你的监控列表中", reply_markup=MAIN_KEYBOARD)

async def remove_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    user_id = update.effective_user.id
    if not context.args:
        await update.message.reply_text(
            "➖ *删除监控地址*\n\n发送格式：\n`/remove 0x地址`",
            parse_mode="Markdown", reply_markup=MAIN_KEYBOARD)
        return
    address = context.args[0].strip()
    if remove_address(data, user_id, address):
        await update.message.reply_text(f"✅ 已删除：`{address}`", parse_mode="Markdown", reply_markup=MAIN_KEYBOARD)
    else:
        await update.message.reply_text("❌ 该地址不在你的监控列表中", reply_markup=MAIN_KEYBOARD)

async def list_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_list(update.message, update.effective_user.id)

async def balance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "💰 *查询余额*\n\n发送格式：\n`/balance 0x地址`",
            parse_mode="Markdown", reply_markup=MAIN_KEYBOARD)
        return
    address = context.args[0].strip().lower()
    await update.message.reply_text("⏳ 查询中...", reply_markup=MAIN_KEYBOARD)
    balance = get_usdt_balance(address)
    await update.message.reply_text(f"💰 USDT余额：*{format_amount(balance)}*", parse_mode="Markdown", reply_markup=MAIN_KEYBOARD)

async def txs_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "📜 *查询近期交易*\n\n发送格式：\n`/txs 0x地址`",
            parse_mode="Markdown", reply_markup=MAIN_KEYBOARD)
        return
    address = context.args[0].strip().lower()
    await show_txs(update.message, address)

async def show_txs(message, address, page=0):
    await message.reply_text("⏳ 查询近期交易中...")
    txs = get_usdt_transactions(address, offset=50)
    if not txs:
        await message.reply_text("❌ 暂无交易记录或地址有误", reply_markup=MAIN_KEYBOARD)
        return
    total = len(txs)
    start_idx = page * 5
    end_idx = min(start_idx + 5, total)
    page_txs = txs[start_idx:end_idx]
    lines = [f"📜 *近期交易记录* ({start_idx+1}-{end_idx} / 共{total}笔)\n"]
    for tx in page_txs:
        amount = int(tx["value"]) / 1_000_000
        to_addr = tx["to"].lower()
        is_income = (to_addr == address)
        direction = "📥" if is_income else "📤"
        tx_time = time.strftime('%m-%d %H:%M', time.gmtime(int(tx['timeStamp'])))
        short_hash = f"{tx['hash'][:8]}...{tx['hash'][-6:]}"
        lines.append(f"{direction} `{format_amount(amount)}` USDT\n   时间：{tx_time}\n   哈希：`{short_hash}`\n")
    keyboard = []
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"txs_{address}_{page-1}"))
    if end_idx < total:
        nav.append(InlineKeyboardButton("下一页 ➡️", callback_data=f"txs_{address}_{page+1}"))
    if nav:
        keyboard.append(nav)
    keyboard.append([InlineKeyboardButton("💰 查询余额", callback_data=f"bal_{address}")])
    await message.reply_text("\n".join(lines), parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else MAIN_KEYBOARD)

# ============================================================
# 菜单按钮文字处理
# ============================================================
async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id
    if text == "📋 监听列表":
        await send_list(update.message, user_id)
    elif text == "➕ 添加地址":
        await update.message.reply_text(
            "➕ *添加监控地址*\n\n发送格式：\n`/add 0x地址 备注名`\n\n示例：\n`/add 0x1234...abcd 军饷`",
            parse_mode="Markdown", reply_markup=MAIN_KEYBOARD)
    elif text == "➖ 删除地址":
        await update.message.reply_text(
            "➖ *删除监控地址*\n\n发送格式：\n`/remove 0x地址`",
            parse_mode="Markdown", reply_markup=MAIN_KEYBOARD)
    elif text == "✏️ 修改备注":
        await update.message.reply_text(
            "✏️ *修改备注*\n\n发送格式：\n`/rename 0x地址 新备注名`",
            parse_mode="Markdown", reply_markup=MAIN_KEYBOARD)
    elif text == "💰 查询余额":
        await update.message.reply_text(
            "💰 *查询余额*\n\n发送格式：\n`/balance 0x地址`",
            parse_mode="Markdown", reply_markup=MAIN_KEYBOARD)
    elif text == "📜 近期交易":
        await update.message.reply_text(
            "📜 *查询近期交易*\n\n发送格式：\n`/txs 0x地址`",
            parse_mode="Markdown", reply_markup=MAIN_KEYBOARD)

# ============================================================
# 内联按钮回调
# ============================================================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data_str = query.data

    if data_str.startswith("detail_"):
        address = data_str[7:]
        data = load_data()
        balance = get_usdt_balance(address)
        today_income, today_outcome = get_daily_stats(data, address)
        today_profit = today_income - today_outcome
        uid = str(query.from_user.id)
        label = data["users"].get(uid, {}).get(address, address[:8]+"...")
        text = (
            f"📍 *{label}*\n`{address}`\n\n"
            f"💰 USDT余额：*{format_amount(balance)}*\n\n"
            f"📊 今日统计：\n"
            f"  收入：{format_amount(today_income)} USDT\n"
            f"  支出：{format_amount(today_outcome)} USDT\n"
            f"  利润：{format_amount(today_profit)} USDT"
        )
        keyboard = [
            [InlineKeyboardButton("📜 近期交易", callback_data=f"txs_{address}_0")],
            [InlineKeyboardButton("🔄 刷新余额", callback_data=f"detail_{address}")],
        ]
        await query.message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data_str.startswith("txs_"):
        parts = data_str.split("_")
        address = parts[1]
        page = int(parts[2])
        await show_txs(query.message, address, page)

    elif data_str.startswith("bal_"):
        address = data_str[4:]
        balance = get_usdt_balance(address)
        await query.message.reply_text(f"💰 USDT余额：*{format_amount(balance)}*", parse_mode="Markdown")

# ============================================================
# 监控线程
# ============================================================
async def monitor_loop(app):
    logger.info("监控线程启动...")
    while True:
        try:
            data = load_data()
            address_info = {}
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
                        keyboard = [[
                            InlineKeyboardButton("📜 查看交易记录", callback_data=f"txs_{address}_0"),
                            InlineKeyboardButton("💰 查询余额", callback_data=f"bal_{address}"),
                        ]]
                        try:
                            await app.bot.send_message(
                                chat_id=int(uid),
                                text=msg,
                                parse_mode="Markdown",
                                disable_web_page_preview=True,
                                reply_markup=InlineKeyboardMarkup(keyboard)
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
    app.add_handler(CommandHandler("balance", balance_cmd))
    app.add_handler(CommandHandler("txs", txs_cmd))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, menu_handler))
    logger.info("Bot 启动中...")
    app.run_polling()

if __name__ == "__main__":
    main()
