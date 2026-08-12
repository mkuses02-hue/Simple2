import os
import time
import threading
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from smsbower import SMSBowerAPI

# 🔐 Environment Variable থেকে API Key নেওয়া (Railway-এর জন্য নিরাপদ)
BOT_TOKEN = os.environ.get("BOT_TOKEN")
SMS_API_KEY = os.environ.get("SMS_API_KEY")

if not BOT_TOKEN or not SMS_API_KEY:
    raise ValueError("⚠️ BOT_TOKEN or SMS_API_KEY environment variable is missing!")

bot = telebot.TeleBot(BOT_TOKEN)
sms_api = SMSBowerAPI(SMS_API_KEY)

TIMEOUT_SECONDS = 130

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    balance = sms_api.get_balance()
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("💰 চেক ব্যালেন্স", callback_data="check_balance"),
        InlineKeyboardButton("📱 Caddy নাম্বার নিন", callback_data="buy_caddy")
    )
    
    welcome_text = (
        f"👋 **স্বাগতম! Caddy OTP বোট-এ।**\n\n"
        f"💳 **আপনার বর্তমান ব্যালেন্স:** `${balance:.4f}`\n\n"
        f"নিচের বাটন চেপে কাজ শুরু করুন:"
    )
    bot.send_message(message.chat.id, welcome_text, parse_mode="Markdown", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: True)
def callback_listener(call):
    chat_id = call.message.chat.id
    
    if call.data == "check_balance":
        balance = sms_api.get_balance()
        bot.answer_callback_query(call.id, f"আপনার বর্তমান ব্যালেন্স: ${balance:.4f}", show_alert=True)

    elif call.data == "buy_caddy":
        bot.edit_message_text("🔍 স্টকে থাকা দেশ ও প্রাইস লিস্ট লোড হচ্ছে...", chat_id, call.message.message_id)
        countries = sms_api.get_available_countries()
        
        if not countries:
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton("🔄 রিফ্রেশ করুন", callback_data="buy_caddy"))
            bot.send_message(chat_id, "❌ বর্তমানে Caddy এর জন্য কোনো দেশের নাম্বার স্টকে নেই।", reply_markup=markup)
            return

        markup = InlineKeyboardMarkup(row_width=1)
        for c in countries[:10]:
            btn_text = f"{c['name']} - ${c['cost']:.3f} (স্টক: {c['count']}টি)"
            markup.add(InlineKeyboardButton(btn_text, callback_data=f"getnum_{c['id']}"))

        markup.add(InlineKeyboardButton("🔙 প্রধান মেনু", callback_data="main_menu"))
        bot.send_message(chat_id, "🌎 **কোন দেশের নাম্বার নিতে চান বেছে নিন:**", parse_mode="Markdown", reply_markup=markup)

    elif call.data.startswith("getnum_"):
        country_id = call.data.split("_")[1]
        bot.answer_callback_query(call.id, "নাম্বার রিকোয়েস্ট করা হচ্ছে...")
        
        act_id, phone = sms_api.get_number(country_id)
        
        if not act_id:
            bot.send_message(chat_id, "❌ স্টক শেষ হয়ে গেছে বা নাম্বার পাওয়া যায়নি। অন্য দেশ চেষ্টা করুন।")
            return

        balance = sms_api.get_balance()
        markup = InlineKeyboardMarkup()
        markup.add(
            InlineKeyboardButton("🔄 OTP চেক করুন", callback_data=f"checkotp_{act_id}"),
            InlineKeyboardButton("🚫 ক্যানসেল করুন", callback_data=f"cancel_{act_id}")
        )

        msg_text = (
            f"✅ **নাম্বার নেওয়া হয়েছে!**\n\n"
            f"📱 **নম্বর:** `+{phone}`\n"
            f"🆔 **ID:** `{act_id}`\n"
            f"💰 **অবশিষ্ট ব্যালেন্স:** `${balance:.4f}`\n\n"
            f"⏳ *বোট ব্যাকগ্রাউন্ডে ২ মিনিট ১০ সেকেন্ড OTP এর জন্য অপেক্ষা করছে...*"
        )
        msg = bot.send_message(chat_id, msg_text, parse_mode="Markdown", reply_markup=markup)
        threading.Thread(target=auto_otp_worker, args=(chat_id, msg.message_id, act_id)).start()

    elif call.data.startswith("checkotp_"):
        act_id = call.data.split("_")[1]
        status = sms_api.check_status(act_id)
        if status.startswith("STATUS_OK:"):
            otp = status.split(":", 1)[1]
            sms_api.set_status(act_id, 6)
            balance = sms_api.get_balance()
            bot.edit_message_text(f"🎉 **OTP পেয়ে গেছেন:** `{otp}`\n\n💰 বর্তমান ব্যালেন্স: `${balance:.4f}`", chat_id, call.message.message_id, parse_mode="Markdown")
        else:
            bot.answer_callback_query(call.id, "এখনো OTP আসেনি! অপেক্ষা করুন...", show_alert=True)

    elif call.data.startswith("cancel_"):
        act_id = call.data.split("_")[1]
        res = sms_api.set_status(act_id, 8)
        if res == "ACCESS_CANCEL":
            balance = sms_api.get_balance()
            bot.edit_message_text(f"🚫 নাম্বারটি ক্যানসেল করা হয়েছে। টাকা রিফান্ড দেওয়া হয়েছে।\n💰 নতুন ব্যালেন্স: `${balance:.4f}`", chat_id, call.message.message_id)
        elif res == "EARLY_CANCEL_DENIED":
            bot.answer_callback_query(call.id, "⚠️ নাম্বার নেওয়ার ২ মিনিটের মধ্যে ক্যানসেল করা যায় না!", show_alert=True)

    elif call.data == "main_menu":
        send_welcome(call.message)

def auto_otp_worker(chat_id, message_id, act_id):
    start_time = time.time()
    while time.time() - start_time < TIMEOUT_SECONDS:
        status = sms_api.check_status(act_id)
        if status.startswith("STATUS_OK:"):
            otp = status.split(":", 1)[1]
            sms_api.set_status(act_id, 6)
            balance = sms_api.get_balance()
            bot.edit_message_text(
                f"🎉 **OTP রিসিভ হয়েছে!**\n\n🔑 **OTP:** `{otp}`\n💰 **বর্তমান ব্যালেন্স:** `${balance:.4f}`",
                chat_id, message_id, parse_mode="Markdown"
            )
            return
        elif status == "STATUS_CANCEL":
            return
        time.sleep(5)

    cancel_res = sms_api.set_status(act_id, 8)
    balance = sms_api.get_balance()
    if cancel_res == "ACCESS_CANCEL":
        bot.edit_message_text(
            f"⏰ **টাইমআউট!** নির্দিষ্ট সময়ের মধ্যে OTP না আসায় নাম্বারটি ক্যানসেল করা হয়েছে।\n💰 **বর্তমান ব্যালেন্স:** `${balance:.4f}`",
            chat_id, message_id, parse_mode="Markdown"
        )

if __name__ == "__main__":
    print("🤖 Telegram Bot is running...")
    bot.infinity_polling()
