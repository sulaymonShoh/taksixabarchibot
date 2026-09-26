"""
Automated Test Suite for Taksi Xabarchi v3.0 - Phase 1
Tests:
1. Real-world Passenger Order Extraction (Toshkent ⇄ Andijon Corridor).
2. Real-world Cargo / Pochta Order Extraction.
3. Driver Advertisement Rejection (100% Negative Filter).
4. Cyrillic & Slang Alias Resolution (Bo'z, Leninsk, Qo'yliq).
5. Highway Corridor Transit Matchmaking (Asaka -> Shahrixon, Bo'ston, Marhamat).
6. High-Speed Latency Benchmark (< 1.0 ms per message).
"""
import os
import sys
import time

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath("."))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from src.harvester.geo_data import resolve_location, is_in_corridor, get_corridor_districts
from src.harvester.nlp_engine import OrderParser

def run_phase1_tests():
    print("=" * 65)
    print("TEST SUITE: TAKSI XABARCHI v3.0 - STAGE 1 (GEO & FAST IN-MEMORY NLP)")
    print("=" * 65)

    parser = OrderParser()

    # ==================== 1. PASSENGER ORDER EXTRACTION ====================
    print("\n>>> 1. Testing Real-World Passenger Order Extraction (Toshkent ⇄ Andijon)...")
    
    msg1 = "Toshkentdan Asakaga 2 kishi bor, tel: 90 987 65 43"
    res1 = parser.parse(msg1)
    assert res1 is not None, "Failed to parse msg1"
    assert res1["order_type"] == "PASSENGER"
    assert res1["passenger_count"] == 2
    assert res1["destination"]["id"] == "asaka"
    assert res1["phone_number"] == "+998909876543"
    print("   [PASS] 'Toshkentdan Asakaga 2 kishi bor' -> Correctly extracted.")

    msg2 = "Qo'yliqdan Shahrixonga bitta odam bor hozir ketishga +998912345678"
    res2 = parser.parse(msg2)
    assert res2 is not None, "Failed to parse msg2"
    assert res2["order_type"] == "PASSENGER"
    assert res2["passenger_count"] == 1
    assert res2["origin"]["id"] == "quyliq"
    assert res2["origin"]["entity_type"] == "PITAK"
    assert res2["destination"]["id"] == "shahrixon"
    assert res2["phone_number"] == "+998912345678"
    print("   [PASS] 'Qo'yliqdan Shahrixonga bitta odam' -> Origin Pitak & Destination extracted.")

    # Cyrillic test
    msg3 = "Куйлюкдан Асакага 3 киши бор тел 99 888 77 66"
    res3 = parser.parse(msg3)
    assert res3 is not None, "Failed to parse msg3 (Cyrillic)"
    assert res3["order_type"] == "PASSENGER"
    assert res3["passenger_count"] == 3
    assert res3["origin"]["id"] == "quyliq"
    assert res3["destination"]["id"] == "asaka"
    assert res3["phone_number"] == "+998998887766"
    print("   [PASS] Cyrillic 'Куйлюкдан Асакага 3 киши' -> Transliterated and extracted.")

    # Historical alias: Leninsk -> Asaka
    msg4 = "Leninskga 4 kishi salon bor tel: 905554433"
    res4 = parser.parse(msg4)
    assert res4 is not None, "Failed to parse msg4 (Leninsk alias)"
    assert res4["destination"]["id"] == "asaka"
    assert res4["passenger_count"] == 4
    assert res4["phone_number"] == "+998905554433"
    print("   [PASS] Historical slang 'Leninskga 4 kishi' -> Resolved to Asaka.")

    # Slang alias: Bo'z -> Bo'ston
    msg5 = "Ertaga ertalab Toshkentdan Bo'zga 1 ta joy bormi? Tel: 93 111 22 33"
    res5 = parser.parse(msg5)
    assert res5 is not None, "Failed to parse msg5 (Bo'z alias)"
    assert res5["destination"]["id"] == "boston"
    assert res5["passenger_count"] == 1
    assert res5["phone_number"] == "+998931112233"
    print("   [PASS] Slang alias 'Bo'zga 1 ta joy bormi' -> Resolved to Bo'ston.")

    # Hyphen pattern
    msg6 = "Qo'yliq - Marhamat 2 kishi bor @mijoz_ali tel 97 765 43 21"
    res6 = parser.parse(msg6)
    assert res6 is not None, "Failed to parse msg6 (hyphen)"
    assert res6["origin"]["id"] == "quyliq"
    # Colloquial spelling: Marxamatdan toshkenga
    msg7 = "Marxamatdan toshkenga kechasiga 1 ta odam bor +998884784784"
    res7 = parser.parse(msg7)
    assert res7 is not None, "Failed to parse msg7"
    assert res7["origin"]["id"] == "marhamat"
    assert res7["destination"]["id"] == "toshkent_shahar_all"
    assert res7["passenger_count"] == 1
    assert res7["phone_number"] == "+998884784784"
    print("   [PASS] Colloquial 'Marxamatdan toshkenga 1 ta odam' -> Extracted Origin, Dest, Phone.")

    # ==================== 2. CARGO / POCHTA EXTRACTION ====================
    print("\n>>> 2. Testing Cargo / Pochta Order Extraction...")
    
    cargo_msg1 = "Qo'yliqdan Bo'stonga pochta bor, tel: 90 777 66 55"
    c_res1 = parser.parse(cargo_msg1)
    assert c_res1 is not None
    assert c_res1["order_type"] == "CARGO"
    assert c_res1["destination"]["id"] == "boston"
    assert c_res1["origin"]["id"] == "quyliq"
    assert c_res1["phone_number"] == "+998907776655"
    print("   [PASS] 'Qo'yliqdan Bo'stonga pochta bor' -> Categorized as CARGO.")

    cargo_msg2 = "Toshkentdan Shahrixonga kichik yuk bor berib yuborish kerak +998901234567"
    c_res2 = parser.parse(cargo_msg2)
    assert c_res2 is not None
    assert c_res2["order_type"] == "CARGO"
    assert c_res2["destination"]["id"] == "shahrixon"
    print("   [PASS] 'Shahrixonga kichik yuk bor berib yuborish kerak' -> Categorized as CARGO.")

    cargo_msg3 = "Асакага сумкочка почта бор тел 93 999 88 77"
    c_res3 = parser.parse(cargo_msg3)
    assert c_res3 is not None
    assert c_res3["order_type"] == "CARGO"
    assert c_res3["destination"]["id"] == "asaka"
    print("   [PASS] Cyrillic 'Асакага сумкочка почта бор' -> Categorized as CARGO.")

    # ==================== 3. DRIVER AD REJECTION (100% NEGATIVE FILTER) ====================
    print("\n>>> 3. Testing 100% Rejection of Driver Ads & Spam...")

    driver_ads = [
        "Cobalt bor, konditsioner bor, Toshkent ➡️ Andijon, tel: 90 123 45 67",
        "Gentra bor, salonda 2 ta joy bor, yurishga tayyor, tel: 91 234 56 78",
        "Nexia 3 bor, Qo'yliqdan Asakaga 1 kishi kerak to'laman 90 987 65 43",
        "Moshina tayyor, yurishga odam ovolaman, tel: 99 111 22 33",
        "Damas bor, arzon narxda yuk olaman 90 000 00 00",
        "Dispecher, zakaz olaman Toshkent-Vodiy 97 555 66 77",
        "Avtokredit, boshlang'ich to'lovsiz, lizing xizmati, tel: 90 123 45 67",
        "Lacetti bor yangi moshina, orqada 2 ta joy qoldi 90 111 22 33",
        "Kobalt bor yurishga tayyor 93 456 78 90",
        "Bo'sh mashina Toshkentdan Andijonga qaytyapti arzon narxda olib ketaman 90 555 44 33",
        "ШАХРИХОНДАН БУЗДАН ТОШКЕНТГА 2 TA KAM ОДАМ ПОЧТАЛАР БУЛСА ОЛАМИЗ ☎️ 917097779 956332000",
        "АНДИЖОН ХУЖАБОД ЖАЛАЛКУДУК КУРГОНТЕПА КОРАСУВ ДАРДОКДАН ТОШКЕНТГА 2.ТА КАМ АЁЛ КИШИ БОР ПОЧТА ОЛАМАН 10 : 11 ЛАРГА ЮРАМАН АВТО КОБЛЬТ ЯНГИ +998 88 440 46 46",
        "Андижондан Тошкентга 24/7 Одам почта оламан 4 та кам Келент вактига юраман Авто Коблт прапан Тел +998884404646",
        "ТОШКЕНТДАН АСАКА ШАХРИХОНГА СОАТ 18 19ЛАРГА 3ТА КАМ ОДАМ ПЧТА ОЛАМИЗ ТОМ БАГАЖ БОР М КОБУЛТ ТЕЛ 996748481",
        "Кувадан Тошкентга Пустой машина бор Келент вактига Караб Йурамиз Авто кобилт Тел.+998885010710.",
        # Production Order #13 (False positive analysis)
        "♦️♦️♦️ АНДИЖОНДАН ТОШКЕНТГА 4 та ОДАМ КАМ КИЛИЕНТ ВАКТИГА ЮРАМИЗ ЯНГИ КУБИЛТ 2026 ⛽️. БЕНЗИН ПУЧТА ХИЗМАТИ БОР 📞. +998884196789",
        # Production Order #11 & #12
        "АНДИЖОНДАН ТОШКЕНТГА СОАТ 23:00-24:00 ГА 1 ТА ОДАМ КАМ АЕЛЛАР БОР БИСНЕС КЛАСС МАШИНА KIA K5 +998930607714",
        "АНДИЖОН ДАН ТОШКЕНТ ГА СРОЧНИ ЮРАМИЗ 2 ТА ОДАМ КАМ П О Ч Т А   О Л А М И З ЯНГИ СОБАЛТ Бензин пропан +998930612121",
        # 27-Orders batch review edge cases
        "Андижон ва Пайтукдан тошкентга Сирушни йурамиз 1 та одам камдамиз 🚖. Кобилт тел. 971008687",
        "Андижон ва Пайтукдан тошкентга ⏱. 7. 8. Га 2 та одам камдамиз 🚖. Кобилт тел. 971008687",
        "Andijondan Toshkentga xarakaddamz odam pochta olamz 4 ta kamdamz mashina kobolt +998902003705",
        "ASSALOM ALLEYKUM ANDIJON SHAXRIXONDAN TOSHKENTGA XARKATAMIZ ODAM POCHTA OLAMZ Avto MALIBU 2 Tel +998932300505",
        "АНДИЖОНДАН ТОШКЕНТГА БУГУН ВА ХАР КУНИ ХИЗМАТДАМИЗ TRACKER 2 COMFORT+ +998505113388",
        "Тошкендан Андижон Шахар избоскан пайтуга сирочни 1 та камдамиз аел киши бор Олди Буш м коблт 941085181",
        "Анжондан Тошкенга сирошнига 1 та камдамиз олди буш 947090727",
        "Тошкент Чилонзорда ЯНГИ АРЗОН МЕХМОНХОНА. Обший хоналар 3-5-7-кишиликлар киши бошига 40 минг +998330055557",
        "Т О Ш К Е Н Т Д А Н... СОАТ 19:00.20:00 ГА ЙУЛГА ЧИКАМИЗ Авто ОНИКС.янги +998971139704",
        # Dialectal driver advertisement with multiple colloquial features
        "ТОШКЕНТГА     9:00  10:00  ДА     ЮУРАМИЗ     2  ТА    ОДАМ   ПОЧТА   БОЛСА   ОЛМИЗ  ТОМБАГАЖ   БОР   АЙОЛАР  БОР     ОЛДИ  МЕСТА    БОШ    АВТО    КОБОЛТ  ❄️❄️❄️❄️🛜🛜🛜  ТЕЛ    999043330    943853330   ОЛДИНДАН   РАХМАТ",
        "Toshkentga 9:00 - 10:00 da yuramiz. 2 ta odam, pochta bo'lsa olamiz. Tom bagaji bor. Ayol yo'lovchilar bor. Oldi o'rindiq bo'sh. Avtomobil - Cobalt. Telefon: 999043330, 943853330. Oldindan rahmat.",
        "Эрталаб. тошкенга харакатамиз  андижон хожаобод достлик таможнидан тошкенга одам почта болса олиб кэтамиз \n974853434",
        "anjondan toshknga siroshni ketamz. oldi mestamiz bosh poshtala ovolamz 999999999"
    ]

    for ad in driver_ads:
        res = parser.parse(ad)
        assert res is None, f"Driver ad leaked through filter: '{ad}'"
    print(f"   [PASS] All {len(driver_ads)} real driver advertisements were 100% safely rejected.")

    # ==================== 4. HIGHWAY CORRIDOR MATCHMAKING ====================
    print("\n>>> 4. Testing Highway Corridor Transit Matchmaking...")

    # Driver A operates the Tashkent -> Asaka route:
    driver_a_pref = {
        "is_radar_active": True,
        "origin_region": "toshkent_shahar",
        "dest_region": "andijon",
        "selected_districts": ["asaka"],  # Driver explicitly selected Asaka
        "allow_passenger": True,
        "allow_cargo": True
    }

    # 1. Order direct for Asaka
    order_asaka = {"is_order": True, "order_type": "PASSENGER", "origin": {"region_id": "toshkent_shahar"}, "destination": {"district_id": "asaka"}}
    assert parser.match_driver(order_asaka, driver_a_pref) is True
    print("   [PASS] Order for Asaka matches Asaka driver directly.")

    # 2. Order for Shahrixon (En-route corridor neighbor to Asaka)
    order_shahrixon = {"is_order": True, "order_type": "PASSENGER", "origin": {"region_id": "toshkent_shahar"}, "destination": {"district_id": "shahrixon"}}
    assert parser.match_driver(order_shahrixon, driver_a_pref) is True
    print("   [PASS] Order for Shahrixon matches Asaka driver via Highway Corridor.")

    # 3. Order for Bo'ston (En-route corridor neighbor to Asaka)
    order_boston = {"is_order": True, "order_type": "CARGO", "origin": {"region_id": "toshkent_shahar"}, "destination": {"district_id": "boston"}}
    assert parser.match_driver(order_boston, driver_a_pref) is True
    print("   [PASS] Order for Bo'ston matches Asaka driver via Highway Corridor.")

    # 4. Order for Marhamat (Adjacent corridor neighbor to Asaka)
    order_marhamat = {"is_order": True, "order_type": "PASSENGER", "origin": {"region_id": "toshkent_shahar"}, "destination": {"district_id": "marhamat"}}
    assert parser.match_driver(order_marhamat, driver_a_pref) is True
    print("   [PASS] Order for Marhamat matches Asaka driver via Highway Corridor.")

    # 5. Order for Xonobod (Far border district, NOT in Asaka corridor)
    order_xonobod = {"is_order": True, "order_type": "PASSENGER", "origin": {"region_id": "toshkent_shahar"}, "destination": {"district_id": "xonobod"}}
    assert parser.match_driver(order_xonobod, driver_a_pref) is False
    print("   [PASS] Order for distant Xonobod correctly rejected for Asaka driver.")

    # ==================== 5. SUB-MILLISECOND SPEED BENCHMARK ====================
    print("\n>>> 5. Benchmarking In-Memory Parsing Latency (1,000 iterations)...")
    sample_msgs = [
        "Toshkentdan Asakaga 2 kishi bor, tel: 90 123 45 67",
        "Cobalt bor, konditsioner bor, Toshkent ➡️ Andijon, tel: 90 123 45 67",
        "Qo'yliqdan Bo'stonga pochta bor, tel: 90 777 66 55",
        "Куйлюкдан Асакага 3 киши бор тел 99 888 77 66",
        "Gentra bor, salonda 2 ta joy bor, yurishga tayyor, tel: 91 234 56 78"
    ]

    iterations = 2000
    start_time = time.perf_counter()
    for i in range(iterations):
        m = sample_msgs[i % len(sample_msgs)]
        parser.parse(m)
    total_time = time.perf_counter() - start_time
    avg_latency_ms = (total_time / iterations) * 1000

    print(f"   [BENCHMARK] Parsed {iterations} messages in {total_time:.4f}s.")
    print(f"   [BENCHMARK] Average latency per message: {avg_latency_ms:.3f} ms.")
    assert avg_latency_ms < 1.0, f"Latency too high: {avg_latency_ms} ms"
    print("   [PASS] High-speed requirement met (< 1.0ms, actual: {:.3f}ms)".format(avg_latency_ms))

    print("=" * 65)
    print("ALL STAGE 1 GEOGRAPHY & NLP ENGINE TESTS PASSED CLEANLY (100%)")
    print("=" * 65)

if __name__ == "__main__":
    run_phase1_tests()
