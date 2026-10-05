# Проверка сделок Bitrix24 без задач в кадры

Скрипт ищет сделки, где:

- заполнена дата `Дата (заселён)`;
- источник не «Перевахтовка» (код определяется по справочнику источников CRM);
- с этой даты прошло больше 5 дней;
- нет задачи, привязанной к сделке, на Минакову Анну или Турчину Юлию.

Отправка в MAX включается через флаг `--notify`. На Timeweb настроен ежедневный запуск в 12:00 по Москве.

Если источник «Перевахтовка» не найден в справочнике, проверка останавливается до отправки уведомлений.

## Настройки

Скопировать пример настроек:

```bash
cp .env.example .env
```

В `.env` должны быть заполнены:

- `BITRIX_WEBHOOK_URL`;
- `SETTLEMENT_DATE_FIELD`;
- `PROJECT_FIELD`;
- `HR_RESPONSIBLE_IDS`;
- `MAX_BOT_TOKEN`;
- `MAX_ANDREY_USER_ID`;
- `MAX_IVAN_USER_ID`;
- `MAX_HUSAN_USER_ID`;
- `MAX_ALEKSEY_USER_ID`.

Распределение объектов хранится в `object_owners.json`.

Пример:

```json
{
  "СДТ": "andrey",
  "Агама": "ivan",
  "Название объекта из третьей группы": "husan_aleksey"
}
```

Ключ — ID или название объекта из Bitrix24. Значение — `andrey`, `ivan` или `husan_aleksey`.

## Команды

Посмотреть заполненные поля одной сделки:

```bash
python bitrix_missing_hr_tasks.py --inspect-deal 49282
```

Безопасная проверка без отправки:

```bash
python bitrix_missing_hr_tasks.py --audit
```

Тестовая проверка по ограниченному числу сделок:

```bash
python bitrix_missing_hr_tasks.py --audit --max-deals 200
```

Проверка с отправкой уведомлений в MAX:

```bash
python bitrix_missing_hr_tasks.py --audit --notify
```

## Восстановление и сервер

Требуется Python 3.10 или новее. Дополнительные пакеты не нужны.
Код, тесты, изображения и распределение объектов сохранены в GitHub.
Файл `.env`, архивы, журналы и список пользователей MAX в GitHub не включаются.
Для восстановления нужна отдельная защищённая копия актуального `.env` с Timeweb.
Не заменяйте рабочий `.env` пустым примером при обновлении кода.

Папка на сервере: `/var/www/mailing_comp_usr/data/www/mailing.complect.org`.
Сервер использует UTC. Задание в crontab пользователя root (09:00 UTC = 12:00 Москва):

```cron
0 9 * * * cd /var/www/mailing_comp_usr/data/www/mailing.complect.org && /usr/bin/env -u MAX_BOT_TOKEN /usr/bin/flock -n /var/lock/mailing_hr.lock /usr/bin/python3 bitrix_missing_hr_tasks.py --audit --created-since 2026-09-01 --notify >> /var/log/mailing_hr.log 2>&1
```

При переносе на другой сервер задание нужно установить отдельно, сохранив остальные задания cron и проверив часовой пояс. Не добавляйте повторное задание на текущем сервере.
Для первичной проверки без сообщений:

```bash
python3 bitrix_missing_hr_tasks.py --audit --created-since 2026-09-01
```

Webhook MAX: `https://mailing.complect.org/max_webhook.php`. Для него требуется PHP 8+ и корректный HTTPS-сертификат. При переносе нужно сохранить настройки сайта и подписку MAX.

Локальные тесты без обращения к CRM и без отправки сообщений:

```bash
python -m unittest test_source_filter -v
```
