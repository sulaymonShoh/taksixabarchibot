import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import asyncio
from datetime import datetime, timedelta
from src.bot.translit import to_cyrillic, to_latin, t
from src.bot import handlers
from src.bot import keyboards as kb
from src.harvester import matcher
from src import database as db

def test_transliteration_accuracy():
    # Test basic conversions
    assert to_cyrillic("Toshkent") == "Тошкент"
    assert to_cyrillic("Xayrli tong!") == "Хайрли тонг!"
    assert to_cyrillic("Buyurtmalar") == "Буюртмалар"
    assert to_cyrillic("E'lon tarqatish") == "Эълон тарқатиш"
    assert to_cyrillic("Yo'lovchi") == "Йўловчи"
    assert to_cyrillic("O'rnatilmagan") == "Ўрнатилмаган"

    # Test protected tokens (HTML tags, URLs, @usernames)
    html_sample = '<b>Buyurtma:</b> <a href="https://t.me/c/123/45">Asl xabarni ko\'rish</a> va @taksi_bot'
    cyr_res = t(html_sample, "cyr")
    assert "<b>Буюртма:</b>" in cyr_res
    assert 'href="https://t.me/c/123/45"' in cyr_res
    assert "@taksi_bot" in cyr_res
    assert "Асл хабарни кўриш" in cyr_res

def test_time_greeting():
    # Should return string without crashing for both scripts
    greet_lat = handlers.get_time_greeting("lat")
    greet_cyr = handlers.get_time_greeting("cyr")
    assert isinstance(greet_lat, str) and len(greet_lat) > 0
    assert isinstance(greet_cyr, str) and len(greet_cyr) > 0
    # No user-rejected words like "Go'zal tong"
    assert "Go'zal" not in greet_lat
    assert "Гўзал" not in greet_cyr

def test_subscription_string_format():
    # User rule: No "faol" word in subscription string!
    # Format: ⭐️ 34 kun 12 soat qoldi or 🔴 Muddati tugagan
    now = datetime.utcnow()
    future = (now + timedelta(days=34, hours=12)).strftime('%Y-%m-%d %H:%M:%S')
    past = (now - timedelta(days=2)).strftime('%Y-%m-%d %H:%M:%S')

    sub_lat, active_lat = handlers.check_subscription(future, "lat")
    assert active_lat is True
    assert "34 kun" in sub_lat
    assert "soat qoldi" in sub_lat
    assert "faol" not in sub_lat.lower()
    assert "vip" not in sub_lat.lower() # Clean display

    sub_cyr, active_cyr = handlers.check_subscription(future, "cyr")
    assert active_cyr is True
    assert "34 кун" in sub_cyr
    assert "соат қолди" in sub_cyr
    assert "фаол" not in sub_cyr.lower()

    # Expired
    exp_lat, exp_act_lat = handlers.check_subscription(past, "lat")
    assert exp_act_lat is False
    assert "Muddati tugagan" in exp_lat

    exp_cyr, exp_act_cyr = handlers.check_subscription(past, "cyr")
    assert exp_act_cyr is False
    assert "Муддати тугаган" in exp_cyr

def test_raw_order_text_untouched_in_radar():
    # CRITICAL: Raw text from customer must remain 100% authentic and untouched
    raw_customer_text = "Asaka dan 2 ta odam bor, Toshkentga tezroq ketamiz tel: 998901234567"
    order = {
        "order_type": "PASSENGER",
        "origin": {"name": "Asaka"},
        "destination": {"name": "Toshkent"},
        "passenger_count": 2,
        "phone_number": "+998901234567",
        "telegram_username": "@mijoz_99",
        "raw_text": raw_customer_text,
        "message_link": "https://t.me/c/999/88"
    }
    match_meta = {"match_type": "EXACT", "driver_district": "Asaka"}

    # Latin notification
    notif_lat = matcher.default_matcher.format_notification(order, match_meta, script="lat")
    assert "Yo'lovchi" in notif_lat
    assert raw_customer_text in notif_lat
    assert "Lichka:" in notif_lat and "@mijoz_99" in notif_lat
    assert "Tel:" in notif_lat and "+998901234567" in notif_lat
    assert "Asl xabarni" in notif_lat and "ko'rish" in notif_lat
    # No bluff text
    assert "VIP haydovchilar" not in notif_lat

    # Cyrillic notification
    notif_cyr = matcher.default_matcher.format_notification(order, match_meta, script="cyr")
    assert "Йўловчи" in notif_cyr
    # Raw customer text must NOT be transliterated! Must be verbatim!
    assert raw_customer_text in notif_cyr
    assert "Личка:" in notif_cyr and "@mijoz_99" in notif_cyr
    assert "Тел:" in notif_cyr and "+998901234567" in notif_cyr
    assert "Асл хабарни" in notif_cyr and "кўриш" in notif_cyr
    assert "VIP haydovchilar" not in notif_cyr

def test_keyboards_script_and_separation():
    # Main dashboard Latin
    kb_main_lat = kb.main_dashboard_kb(is_authenticated=True, script="lat")
    buttons_lat = [b.text for row in kb_main_lat.inline_keyboard for b in row]
    assert "🎯 Buyurtmalar" in buttons_lat
    assert "📢 E'lon tarqatish" in buttons_lat
    assert "💳 Obunani boshqarish" in buttons_lat
    assert "🔌 Akkauntni uzish" in buttons_lat
    assert "🌐 Alifbo: Lotin 🇺🇿" in buttons_lat

    # Main dashboard Cyrillic
    kb_main_cyr = kb.main_dashboard_kb(is_authenticated=True, script="cyr")
    buttons_cyr = [b.text for row in kb_main_cyr.inline_keyboard for b in row]
    assert "🎯 Буюртмалар" in buttons_cyr
    assert "📢 Эълон тарқатиш" in buttons_cyr
    assert "💳 Обунани бошқариш" in buttons_cyr
    assert "🔌 Аккаунтни узиш" in buttons_cyr
    assert "🌐 Алифбо: Кирилл 🇺🇿" in buttons_cyr

    # Persistent reply keyboards
    reply_lat = kb.main_reply_kb("lat")
    reply_lat_btns = [b.text for row in reply_lat.keyboard for b in row]
    assert "📖 Foydalanish qo'llanmasi" in reply_lat_btns
    assert "✍️ Adminga yozish" in reply_lat_btns

    reply_cyr = kb.main_reply_kb("cyr")
    reply_cyr_btns = [b.text for row in reply_cyr.keyboard for b in row]
    assert "📖 Фойдаланиш қўлланмаси" in reply_cyr_btns
    assert "✍️ Админга ёзиш" in reply_cyr_btns

async def test_database_script_persistence():
    await db.init_db()
    test_user_id = 999888777
    user, _ = await db.get_or_create_user(test_user_id, "Test User", "testuser")
    
    # Default is 'lat'
    script_default = await db.get_user_script(test_user_id)
    assert script_default == "lat"

    # Set to 'cyr'
    await db.set_user_script(test_user_id, "cyr")
    script_updated = await db.get_user_script(test_user_id)
    assert script_updated == "cyr"

    # Set back to 'lat'
    await db.set_user_script(test_user_id, "lat")
    assert await db.get_user_script(test_user_id) == "lat"

if __name__ == "__main__":
    test_transliteration_accuracy()
    test_time_greeting()
    test_subscription_string_format()
    test_raw_order_text_untouched_in_radar()
    test_keyboards_script_and_separation()
    asyncio.run(test_database_script_persistence())
    print("\n>>> ALL STANDALONE V3 UI & CYRILLIC TESTS PASSED PERFECTLY (100%)! <<<")
