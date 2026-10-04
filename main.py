import os
import telebot
from telebot import types
from supabase import create_client, Client

# 1. Load Configuration (Set these in your environment variables or paste them here for testing)
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL", "YOUR_SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "YOUR_SUPABASE_KEY")

bot = telebot.TeleBot(BOT_TOKEN)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- HELPER: Get or Create User Profile ---
def get_user_profile(telegram_id: int):
    response = supabase.table("profiles").select("*").eq("telegram_id", telegram_id).execute()
    if response.data:
        return response.data[0]
    else:
        # Create a new blank profile starting at ONBOARDING_NAME
        new_user = {"telegram_id": telegram_id, "state": "ONBOARDING_NAME"}
        res = supabase.table("profiles").insert(new_user).execute()
        return res.data[0]

def update_user_state(telegram_id: int, state: str, extra_data: dict = None):
    data = {"state": state}
    if extra_data:
        data.update(extra_data)
    supabase.table("profiles").update(data).eq("telegram_id", telegram_id).execute()


# --- USSD-STYLE ONBOARDING FLOW ---

@bot.message_handler(commands=['start'])
def handle_start(message):
    telegram_id = message.from_user.id
    profile = get_user_profile(telegram_id)
    
    # Reset or check state
    update_user_state(telegram_id, "ONBOARDING_NAME")
    bot.send_message(
        message.chat.id, 
        "Welcome to the Matchmaking Service! 💘\n\nLet's set up your profile quickly.\n\n1️⃣ Please enter your **Full Name**:"
    )

@bot.message_handler(func=lambda msg: get_user_profile(msg.from_user.id).get('state') == 'ONBOARDING_NAME')
def process_name(message):
    telegram_id = message.from_user.id
    full_name = message.text.strip()
    
    update_user_state(telegram_id, "ONBOARDING_AGE", {"full_name": full_name})
    bot.send_message(message.chat.id, "2️⃣ Great! How old are you? (Enter a number, e.g., 24):")

@bot.message_handler(func=lambda msg: get_user_profile(msg.from_user.id).get('state') == 'ONBOARDING_AGE')
def process_age(message):
    telegram_id = message.from_user.id
    try:
        age = int(message.text.strip())
        update_user_state(telegram_id, "ONBOARDING_GENDER", {"age": age})
        
        # Show Gender Buttons
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("Male 👨", callback_data="gender_Male"),
            types.InlineKeyboardButton("Female 👩", callback_data="gender_Female")
        )
        bot.send_message(message.chat.id, "3️⃣ Select your gender:", reply_markup=markup)
    except ValueError:
        bot.send_message(message.chat.id, "❌ Please enter a valid number for your age:")

@bot.callback_query_handler(func=lambda call: call.data.startswith("gender_"))
def process_gender(call):
    telegram_id = call.from_user.id
    gender = call.data.split("_")[1]
    
    update_user_state(telegram_id, "ONBOARDING_SEEKING", {"gender": gender})
    
    # Show Seeking Gender Buttons
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("Male 👨", callback_data="seeking_Male"),
        types.InlineKeyboardButton("Female 👩", callback_data="seeking_Female")
    )
    bot.edit_message_text("4️⃣ Who are you looking for?", call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("seeking_"))
def process_seeking(call):
    telegram_id = call.from_user.id
    seeking = call.data.split("_")[1]
    
    update_user_state(telegram_id, "ONBOARDING_PURPOSE", {"seeking_gender": seeking})
    
    # Show Purpose Buttons
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("Dating ❤️", callback_data="purpose_Dating"),
        types.InlineKeyboardButton("Friendship 🤝", callback_data="purpose_Friendship"),
        types.InlineKeyboardButton("Networking 💼", callback_data="purpose_Networking")
    )
    bot.edit_message_text("5️⃣ What is your primary purpose?", call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("purpose_"))
def process_purpose(call):
    telegram_id = call.from_user.id
    purpose = call.data.split("_")[1]
    
    update_user_state(telegram_id, "ONBOARDING_LOCATION", {"purpose": purpose})
    
    # Request GPS Location Button
    markup = types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
    location_button = types.KeyboardButton("📍 Share My GPS Location", request_location=True)
    markup.add(location_button)
    
    bot.delete_message(call.message.chat.id, call.message.message_id)
    bot.send_message(
        call.message.chat.id, 
        "6️⃣ To find matches near you, please share your exact location using the button below:", 
        reply_markup=markup
    )

@bot.message_handler(content_types=['location'])
def process_location(message):
    telegram_id = message.from_user.id
    lat = message.location.latitude
    lon = message.location.longitude
    
    update_user_state(telegram_id, "ONBOARDING_PHOTO", {"lat": lat, "lon": lon})
    
    # Remove reply keyboard
    remove_markup = types.ReplyKeyboardRemove()
    bot.send_message(
        message.chat.id, 
        "7️⃣ Almost done! Please upload a photo of yourself for your profile card:", 
        reply_markup=remove_markup
    )

@bot.message_handler(content_types=['photo'])
def process_photo(message):
    telegram_id = message.from_user.id
    # Get the highest resolution photo file ID
    photo_file_id = message.photo[-1].file_id
    
    # Complete onboarding and set state to IDLE / Active
    update_user_state(telegram_id, "IDLE", {"photo_file_id": photo_file_id, "is_active": True})
    
    bot.send_message(
        message.chat.id, 
        "🎉 **Profile Setup Complete!**\n\nYour profile is now active. Send /match to start finding people near you!"
    )
# --- MATCHING & DISCOVERY FLOW ---

@bot.message_handler(commands=['match'])
def handle_match(message):
    telegram_id = message.from_user.id
    profile = get_user_profile(telegram_id)
    
    if not profile.get('lat') or not profile.get('lon'):
        bot.send_message(message.chat.id, "⚠️ Please complete your profile setup and share your location first using /start.")
        return

    # Call Supabase RPC function 'get_nearby_matches'
    try:
        response = supabase.rpc(
            "get_nearby_matches", 
            {"current_profile_id": profile['id'], "max_distance_km": 50}
        ).execute()
        
        matches = response.data
        if not matches:
            bot.send_message(message.chat.id, "😔 No active matches found nearby right now. Try again later!")
            return
            
        # Get the closest match (first item in sorted distance)
        match = matches[0]
        
        # Save current browsing target in user state or session if needed
        # Format the profile card text
        card_text = (
            f"💘 **Match Found!**\n\n"
            f"👤 **{match['full_name']}**, {match['age']}\n"
            f"📍 Distance: **{match['distance_km']} km away**\n"
            f"🎯 Purpose: Looking for connection\n\n"
            f"💬 Bio: {match['bio'] or 'No bio provided.'}"
        )
        
        # Inline buttons for action
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("❤️ Like", callback_data=f"like_{match['id']}"),
            types.InlineKeyboardButton("⏭️ Skip", callback_data="skip_match")
        )
        
        # Send profile photo if available, otherwise text
        if match.get('photo_file_id'):
            bot.send_photo(message.chat.id, match['photo_file_id'], caption=card_text, reply_markup=markup, parse_mode="Markdown")
        else:
            bot.send_message(message.chat.id, card_text, reply_markup=markup, parse_mode="Markdown")
            
    except Exception as e:
        print(f"Error fetching matches: {e}")
        bot.send_message(message.chat.id, "⚠️ An error occurred while searching for matches. Please try again.")

@bot.callback_query_handler(func=lambda call: call.data.startswith("like_") or call.data == "skip_match")
def handle_match_action(call):
    telegram_id = call.from_user.id
    
    if call.data == "skip_match":
        bot.answer_callback_query(call.id, "Skipped!")
        bot.edit_message_caption("⏭️ Profile skipped. Send /match to see the next person.", call.message.chat.id, call.message.message_id)
        return
        
    if call.data.startswith("like_"):
        target_profile_id = call.data.split("_")[1]
        bot.answer_callback_query(call.id, "You liked this profile!")
        bot.edit_message_caption("❤️ Liked! Looking for mutual matches...", call.message.chat.id, call.message.message_id)
        
        # Here you can record the like/match in your supabase 'matches' table and check if it's mutual!
        # For now, let's prompt them to find another or simulate a match connection.
        bot.send_message(call.message.chat.id, "✨ Match request saved! Send /match to keep browsing.")
# --- RUN BOT ---
if __name__ == "__main__":
    print("Bot is polling...")
    bot.infinity_polling()
