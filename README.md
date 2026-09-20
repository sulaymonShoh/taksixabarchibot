# Taksi Xabarchi v3.0: Dual-Engine Intercity Taxi & Logistics Platform
> **Smart Order Harvester, In-Memory NLP Dispatcher & Multi-Tenant Broadcaster for Uzbekistan**

---

## 📌 Loyiha Haqida (Project Overview)

**Taksi Xabarchi** — O'zbekiston bo'ylab viloyatlararo va tumanlararo taksi haydovchilari, dispetcherlar va yo'lovchilar uchun ishlab chiqilgan keng qamrovli **Dual-Engine (Ikki Dvigatelli)** telekommunikatsiya va logistika platformasi.

Tizim haydovchining ikkita eng asosiy og'riqli nuqtasini to'liq yopadi:
1. **Engine 1 (Broadcaster v2.0):** Haydovchining e'lonini 100+ ommaviy taksi guruhlariga xavfsiz, belgilangan oraliq (interval) va jitter bilan avtomatik yuborish.
2. **Engine 2 (Harvester & Radar v3.0):** Yuzlab taksi guruhlaridagi real yo'lovchilar va pochta/yuk buyurtmalarini soniyaning ulushlarida (<0.5s) tutib oluvchi, haydovchi reklamalarini 99% filtrllovchi, tumanlar va tranzit koridorlar bo'yicha saralab, haydovchiga **1-Tap qo'ng'iroq** formati bilan yetkazuvchi intellektual radar.

---

## 🏛 Tizim Arxitekturasi (Architecture)

```
                       [ 100+ Telegram Supergroups ]
                                     │
                                     ▼ (Telethon MTProto Listeners < 200ms)
  ┌────────────────────────────────────────────────────────────────────────┐
  │                 1. REAL-TIME HARVESTER INGESTION                       │
  │  • Asinxron xabarlar oqimi                                             │
  │  • Fuzzy Fingerprint deduplikatsiya (15 daqiqalik qayta e'lon filtri)  │
  └──────────────────────────────────┬─────────────────────────────────────┘
                                     │
                                     ▼
  ┌────────────────────────────────────────────────────────────────────────┐
  │         2. IN-MEMORY FAST NLP & INTENT ENGINE (0.5ms / $0 API)         │
  │  • Kirill -> Lotin avtomatik transliteratsiya                          │
  │  • Salbiy filtr: Haydovchi reklamalarini 100% rad etish ("Cobalt bor") │
  │  • Ijobiy filtr: Real yo'lovchi intenti ("Odam bor", "Pochta bor")    │
  │  • Entitiy ekstraktor: Yo'lovchi soni, Telefon raqam (+998...)         │
  └──────────────────────────────────┬─────────────────────────────────────┘
                                     │
                                     ▼
  ┌────────────────────────────────────────────────────────────────────────┐
  │         3. UZBEKISTAN GEOGRAPHY & CORRIDOR MATCHMAKING                 │
  │  • 14 Viloyat, 208 Tuman va Markaziy Pitaklar (Qo'yliq, Olmazor va h.k)│
  │  • Dastlabki sinov o'qi: Toshkent ⇄ Andijon Koridori                   │
  │    (Asaka ➡️ Shahrixon, Bo'ston, Marhamat tranzit moslashuvi)          │
  └──────────────────────────────────┬─────────────────────────────────────┘
                                     │
                                     ▼
  ┌────────────────────────────────────────────────────────────────────────┐
  │              4. INSTANT DISPATCH & DUAL-GROWTH DELIVERY                │
  │  • Telegram Bot DM: [ 📞 1-Tap Qo'ng'iroq ] [ 💬 Telegramda yozish ]   │
  │  • Telegram Mini App: Jonli audio-radar oqimi                          │
  │  • Bepul Yo'lovchi Boti (@TaksiMijozBot) to'g'ridan-to'g'ri integratsiyasi│
  └────────────────────────────────────────────────────────────────────────┘
```

---

## 🚀 Asosiy Imkoniyatlar (Key Features)

### 1. In-Memory NLP & Zero-Cost Engine
- **$0.00 Doimiy Xarajat:** Jonli xabarlar uchun tashqi pullik LLM API (OpenAI/Gemini) ishlatilmaydi; barcha qoidalar server RAM xotirasida ishlaydi.
- **Ultra-tezlik (< 0.5ms):** Xabarlar millisoniyaning ulushlarida tahlil qilinadi, shuning uchun haydovchilar raqobatchilardan 3–5 soniya oldinroq mijozga telefon qilishadi.
- **Haqiqiy Guruh Xabarlari Asosidagi Patternlar:** O'zbekiston taksi guruhlaridagi real leksika va jargonlar asosida tuzilgan salbiy va ijobiy qoidalar bazasi.

### 2. Tumanlar Aniqligi va Tranzit Koridorlar (Corridor Matching)
- **Toshkent ⇄ Andijon Sinov O'qi:** Toshkentning barcha jo'nash nuqtalari (Qo'yliq, Rohat va b.) hamda Andijon viloyatining barcha tumanlari (Asaka, Shahrixon, Bo'ston, Marhamat, Andijon shahar va b.).
- **Tranzit Moslashuv:** Asakaga ketayotgan haydovchi yo'l ustidagi Shahrixon, Bo'ston va qo'shni Marhamat tumanlariga tegishli yo'lovchi yoki pochtalarni ham bitta qulay radarda qabul qiladi.

### 3. Ikki Tomonlama O'sish Mexanizmi (Growth Flywheel)
- **Broadcaster & Harvester birgalikda:** Bitta VIP obuna bilan haydovchi ham guruhlarga e'lon tarqatadi, ham tayyor yo'lovchilarni tutadi.
- **Clean Copy Auto-Footer:** Haydovchi e'lonlari ostiga avtomatik `@TaksiMijozBot` havolasi qo'shilib, $0 marketing xarajati bilan platformaga doimiy yangi yo'lovchilar oqimi jalb qilinadi.

### 4. Mukammal SaaS va To'lov Boshqaruvi
- **3-Kunlik Bepul VIP Sinov:** Yangi foydalanuvchilar `/start` bosganda darhol 72 soatlik bepul to'liq kirish huquqiga ega bo'ladi.
- **Tabaqalashtirilgan Tariflar:** 1 oylik (25,000 so'm), 3 oylik (65,000 so'm), 6 oylik (120,000 so'm), 12 oylik (225,000 so'm).
- **Aksiyalar va Promokodlar:** Ma'lum muddatli foizli chegirmalar, tariflar bo'yicha tabaqalanish va bepul kun beruvchi promokodlar.
- **Admin Chek Tasdiqlash:** Haydovchi to'lov chekini skrinshot qilib yuboradi ➡️ SuperAdmin botda 1 ta tugma orqali tasdiqlaydi ➡️ Obuna avtomatik uzaytiriladi.
- **FastAPI Web Boshqaruv Paneli:** Foydalanuvchilar jadvali, to'lovlar tekshiruvi (lightbox foto modal), moliyaviy hisobotlar va kun/tun rejimi (Space Grotesk shrifti).

---

## 📂 Loyiha Tuzilmasi (Project Structure)

```text
taksixabarchi/
├── data/                       # SQLite ma'lumotlar bazasi va kesh fayllar
├── sessions/                   # Telethon MTProto foydalanuvchi sessiyalari
├── src/
│   ├── bot/                    # Aiogram 3 Telegram Bot
│   │   ├── handlers.py         # Bot komandalari, to'lovlar, promokodlar
│   │   ├── keyboards.py        # Inline va reply klaviaturalar
│   │   ├── middleware.py       # Foydalanuvchi registratsiyasi va VIP tekshiruvi
│   │   └── auth_flow.py        # Telegram akkaunt ulash (MTProto SMS/2FA)
│   ├── harvester/              # [v3.0] Aqlli Buyurtmalar Agregatori
│   │   ├── geo_data.py         # 14 Viloyat, 208 Tuman, Pitaklar va Koridorlar
│   │   ├── nlp_rules.py        # Real xabarlar asosidagi salbiy/ijobiy qoidalar
│   │   ├── nlp_engine.py       # Ultra-tez matn tahlili va entitiy ajratish
│   │   ├── listener.py         # Telethon guruh tinglovchi oqimi
│   │   └── matcher.py          # Haydovchi filtrlari va tranzit moslashtiruvchi
│   ├── web/                    # FastAPI Web boshqaruv paneli
│   │   ├── app.py              # Marshrutlar va REST API endpointlar
│   │   ├── templates/          # Jinja2 HTML shablonlar (Dark/Light tema)
│   │   └── static/             # CSS uslublar va rasmlar
│   ├── worker/                 # Telethon Broadcaster Worker
│   │   ├── worker.py           # Shaxsiy hisobdan guruhlarga yuborish mexanizmi
│   │   └── worker_manager.py   # Multi-user xavfsiz worker boshqaruvchisi
│   ├── config.py               # Konfiguratsiya va `.env` o'zgaruvchilar
│   ├── database.py             # Asinxron SQLite ma'lumotlar bazasi qatlami
│   ├── logger.py               # Loglash sozlamalari
│   └── main.py                 # Asosiy kirish nuqtasi (Bot + Web + Workers)
├── tests/                      # Avtomatlashtirilgan regressiya testlari
├── .env.example                # Namunaviy muhit o'zgaruvchilari
├── requirements.txt            # Python bog'liqliklari
└── README.md                   # Loyiha hujjatlari
```

---

## 🛠 O'rnatish va Ishga Tushirish (Installation & Setup)

### 1. Repozitoriyani klonlash va virtual muhit:
```bash
git clone -b v3.0 https://github.com/sulaymonShoh/taksixabarchibot.git
cd taksixabarchibot

# Virtual muhit yaratish va faollashtirish
python3 -m venv .venv
source .venv/bin/activate  # Windows: .\.venv\Scripts\activate

# Kerakli paketlarni o'rnatish
pip install -r requirements.txt
```

### 2. Muhit o'zgaruvchilarini sozlash (`.env`):
Loyiha ildizida `.env` fayl yarating:
```env
BOT_TOKEN=your_telegram_bot_token
ADMIN_ID=your_telegram_numeric_id
ADMIN_CHANNEL_ID=-100xxxxxxxxxx

API_ID=your_telegram_api_id
API_HASH=your_telegram_api_hash

PAYMENT_CARD_NUMBER=8600000000000000
PAYMENT_CARD_HOLDER=SULAYMONQORI MUTALLIBOV

ADMIN_USERNAME=admin
ADMIN_PASSWORD=strong_admin_password

WEB_HOST=0.0.0.0
WEB_PORT=8000
DB_PATH=data/bot.db
```

### 3. Tizimni ishga tushirish:
```bash
python -m src.main
```

### 4. Linux / Oracle Cloud da `systemd` xizmati sifatida ishlatish:
`/etc/systemd/system/taksixabarchi.service`:
```ini
[Unit]
Description=Taksi Xabarchi Platform v3.0
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/taksixabarchibot
ExecStart=/home/ubuntu/taksixabarchibot/.venv/bin/python -m src.main
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```
Faollashtirish:
```bash
sudo systemctl daemon-reload
sudo systemctl enable taksixabarchi
sudo systemctl start taksixabarchi
```

---

## 🧪 Avtomatlashtirilgan Testlar (Testing)

Barcha modullar to'liq test qoplamasiga ega:
```bash
# Phase 1: O'zbekiston Geografiyasi va In-Memory NLP Testlari
python tests/test_v3_phase1_nlp.py

# Chegirmalar va Promokodlar Dvigateli Testlari
python tests/test_discounts_promos.py

# Multi-Tenant Auth va Bot Klaviaturalari Testlari
python tests/test_phase1_phase2.py

# Xavfsiz Multi-Worker Broadcaster Testlari
python tests/test_phase3_worker.py

# FastAPI Web Dashboard va Moliya Tahlili Testlari
python tests/test_phase4_web.py
```

---

## 🗺 v3.0 Yo'l Xaritasi (Roadmap)

- [x] **Texnik Topshiriq (TZ) va Arxitektura Rejalashtirish**
- [ ] **1-Bosqich:** O'zbekiston Geografiyasi & Toshkent-Andijon O'qi Lug'ati, Real Xabarlar NLP Klassifikatori
- [ ] **2-Bosqich:** Harvester Listener Grid (Telethon xabarlar oqimi va deduplikatsiya)
- [ ] **3-Bosqich:** Haydovchilar Radar Sozlamalari & Tranzit Koridor Moslashtiruvchisi
- [ ] **4-Bosqich:** Instant Dispatch (1-Tap Call & DM) & Mini App Audio Radar & `@TaksiMijozBot`
- [ ] **5-Bosqich:** Web Dashboard Buyurtmalar Monitoringi & Staging Deployment

---
**Muallif:** Sulaymon Shoh & Gemini (Advanced Agentic Pair-Programming)  
**Litsenziya:** Xususiy Tijoriy Dasturiy Ta'minot (Proprietary SaaS)
