# 🤖 Novda Hisob-Kitob — Ishchilar Uchun Telegram Boti va Shaxsiy Web App

Ushbu papka (`worker-bot/`) fabrika/sex ishchilari (tikuvchilar, operatorlar) uchun mo'ljallangan to'liq mustaqil (standalone) Telegram boti va shaxsiy Web App portalini o'z ichiga oladi.

---

## 🔒 Maxfiylik va Xavfsizlik Kafolati (100% Shaxsiy)

1. **Faqat o'z statistikasi:** Ishchi botga kirganda faqat o'zining ID raqamiga tegishli ma'lumotlarni ko'radi:
   - Sof foyda (qo'lga tegadigan summa)
   - Jami ishlangan summa (ishbay tariflar bo'yicha)
   - Olingan avanslar
   - Jarima va chegirmalar
   - Bajarilgan operatsiyalar (qaysi modelda qaysi chokdan nechtadan tikkanligi va narxlari)
   - Skanerlangan pattalar tarixi
2. **Boshqalar mutlaqo ko'rinmaydi:** Boshqa ishchilarning ismlari yoki ularning oyliklari mutlaqo berkitilgan.
3. **Kompaniya ko'rsatkichlari bloklangan:** Korxonaning umumiy daromadi, oylik fondi, umumiy chiqimlar xodimga ko'rsatilmaydi.

---

## 📁 Papka Tarkibi

```
worker-bot/
├── bot.py             # Asosiy Python backend (Telegram Polling + Standalone Web App Server)
├── config.json        # Bot sozlamalari (Token, kompaniya kodi, WebApp URL)
├── render.yaml        # Render.com bulutiga 1-tugma bilan joylash konfiguratsiyasi
├── requirements.txt   # Python kutubxonalari
├── run.bat            # Windows uchun 1-bosishda ishga tushiruvchi fayl
├── webapp/
│   └── index.html     # Ishchining zamonaviy shaxsiy Web App (TMA) sahifasi
└── README.md          # Qo'llanma
```

---

## 🚀 Ishga Tushirish (3 oddiy qadam)

### 1-qadam: Telegramdan yangi bot ochish
1. Telegramda **`@BotFather`** ga kiring.
2. `/newbot` buyrug'ini yozing.
3. Botga nom bering (masalan: `Novda Ishchilar Boti`).
4. Botga username bering (masalan: `novda_ishchilar_bot`).
5. `@BotFather` bergan **HTTP API Token** ni nusxalab oling.

### 2-qadam: Tokenni kiritish
`worker-bot/config.json` faylini oching va tokenni yozing:
```json
{
  "bot_token": "SIZNING_BOT_TOKENINGIZ",
  "company_id": "comp_novda",
  "webapp_url": ""
}
```
*(Eslatma: agar `webapp_url` bo'sh qoldirilsa, bot o'zining ichki serveridagi `webapp/index.html` sahifasidan avtomatik foydalanadi).*

### 3-qadam: Ishga tushirish
Windows kompyuterda:
- `run.bat` faylini ikki marta bosing.

Yoki terminalda:
```bash
cd worker-bot
python bot.py
```

---

## ☁️ Render.com da 24/7 Bepul Joylash

1. Ushbu `worker-bot` papkasini yangi GitHub repozitoriyga yuklang (yoki alohida branch sifatida).
2. [Render.com](https://render.com) ga kiring: **New +** &rarr; **Web Service**.
3. Repozitoriyingizni ulang.
4. **Environment Variables** ga quyidagini kiriting:
   - `WORKER_BOT_TOKEN` = Sizning bot tokeningiz
   - `DEFAULT_COMPANY_ID` = `comp_novda`
   - `PORT` = `10000`
5. **Create Web Service** tugmasini bosing.
Bot 24/7 ishlaydi va o'zining Keep-Alive mexanizmi orqali uxlab qolmaydi!

---

## 📱 Bot Qanday Ishlaydi?

1. **Xodim ulanishi (Bir martalik):**
   - Xodim botga `/start` yuboradi.
   - Bot Ishchi ID raqamini kiritishni so'raydi (masalan `27`).
   - Bot bazadan xodim F.I.O sini topib tasdiqlatadi (`[ ✅ Ha, bu men ]`).
   - Tasdiqlangach, Telegram akkaunt doimiy ravishda xodimga birikadi.

2. **Tugmali Menyu:**
   - `[ 📱 Mening Hisobim (Web App) ]` &rarr; Telegram ichida to'liq ekranli shaxsiy hisobotni ochadi.
   - `[ 💰 Sof Foyda va Oylik ]` &rarr; Qo'lga tegadigan pul, avans va jarima hisob-kitobini chiqaradi.
   - `[ 📋 Bajargan Ishlarim ]` &rarr; Tikilgan kiyimlar va choklar ro'yxatini ko'rsatadi.
   - `[ 🎫 Oxirgi Pattalarim ]` &rarr; Xodim topshirgan chiptalar (pattalar) tarixini chiqaradi.
   - `[ 🚪 Chiqish (Hisobdan uzish) ]` &rarr; Boshqa xodim kirishi uchun hisobni uzish imkoniyati.
