# مكتبة لخلف - نظام إدارة المكتبة

نظام إدارة مكتبة متطور مبني بـ Python Flask مع واجهة عربية جميلة.

## المميزات

- 📦 إدارة المخزون
- 💵 نقطة البيع (POS)
- 🧾 إدارة الفواتير
- 👥 إدارة العملاء
- 🚚 إدارة الموردين
- 📥 إدارة المشتريات
- 💰 إدارة الديون

## التقنيات المستخدمة

- **Backend**: Python Flask
- **Database**: SQLite
- **Frontend**: HTML, CSS, JavaScript
- **Styling**: Hyperspace Template
- **Font**: Cairo (عربي)

## التشغيل المحلي

```bash
pip install -r requirements.txt
python lekhleftest.py
```

## النشر على الإنترنت

### Render.com (موصى به)

1. إنشاء حساب على [Render.com](https://render.com)
2. ربط حساب GitHub
3. إنشاء Web Service جديد
4. اختيار المستودع
5. النشر التلقائي

## متغيرات البيئة

- `FLASK_ENV`: production للخادم
- `PORT`: منفذ التشغيل (افتراضي: 5000)

## قاعدة البيانات

يستخدم SQLite محلياً ويمكن ترقيته إلى PostgreSQL في الإنتاج.

## الدعم

للمساعدة أو الاستفسارات، يرجى فتح issue في المستودع.
