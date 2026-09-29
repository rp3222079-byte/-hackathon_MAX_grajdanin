# Сертификаты

`russian_trusted_root_ca.pem` — корневой сертификат Минцифры России (Russian Trusted Root CA).

MAX Bot API работает на домене `platform-api2.max.ru`, сертификат которого выпущен
этим удостоверяющим центром. В стандартном наборе `certifi` его нет, поэтому бот
объединяет `certifi` и этот файл (`app/bot/tls.py`).

- Источник: https://gu-st.ru/content/Other/doc/russian_trusted_root_ca.cer
  (портал Госуслуг, раздел о сертификатах Минцифры)
- Срок действия: 01.03.2022 — 27.02.2032
- SHA-256: `D2:6D:2D:02:31:B7:C3:9F:92:CC:73:85:12:BA:54:10:35:19:E4:40:5D:68:B5:BD:70:3E:97:88:CA:8E:CF:31`
