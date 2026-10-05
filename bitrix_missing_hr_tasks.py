from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(f"Не заполнена настройка {name}. Проверьте файл .env")
    return value


def parse_int_list(value: str) -> list[int]:
    result: list[int] = []
    for item in value.split(","):
        item = item.strip()
        if item:
            result.append(int(item))
    return result


def parse_str_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


class BitrixClient:
    def __init__(self, webhook_url: str) -> None:
        self.webhook_url = webhook_url.rstrip("/") + "/"

    def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = urllib.parse.urljoin(self.webhook_url, method)
        payload = json.dumps(params or {}).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )

        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                with urllib.request.urlopen(request, timeout=90) as response:
                    data = response.read().decode("utf-8")
                break
            except Exception as exc:
                last_error = exc
                if attempt == 3:
                    raise RuntimeError(f"Ошибка запроса Bitrix24 метода {method}: {exc}") from exc
                time.sleep(attempt * 2)
        else:
            raise RuntimeError(f"Ошибка запроса Bitrix24 метода {method}: {last_error}")

        result = json.loads(data)
        if "error" in result:
            description = result.get("error_description") or result["error"]
            raise RuntimeError(f"Bitrix24 вернул ошибку {method}: {description}")
        return result

    def list_all(
        self,
        method: str,
        params: dict[str, Any],
        max_items: int | None = None,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        start = 0

        while True:
            page_params = dict(params)
            page_params["start"] = start
            response = self.call(method, page_params)
            result = response.get("result", [])

            if method == "tasks.task.list" and isinstance(result, dict):
                page_items = result.get("tasks", [])
            else:
                page_items = result

            items.extend(page_items)
            if max_items is not None and len(items) >= max_items:
                return items[:max_items]

            next_start = response.get("next")
            if next_start is None:
                break
            start = int(next_start)

        return items


class MaxClient:
    def __init__(self, token: str) -> None:
        self.token = token

    def send_message(self, user_id: str, text: str) -> None:
        query = urllib.parse.urlencode({"user_id": user_id})
        url = f"https://platform-api2.max.ru/messages?{query}"
        payload = json.dumps({"text": text, "disable_link_preview": True}).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Authorization": self.token,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            response.read()

    def get_updates(
        self,
        marker: int | None = None,
        limit: int = 100,
        timeout: int = 30,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "limit": limit,
            "timeout": timeout,
        }
        if marker is not None:
            params["marker"] = marker

        url = "https://platform-api2.max.ru/updates?" + urllib.parse.urlencode(params)
        request = urllib.request.Request(
            url,
            headers={
                "Authorization": self.token,
                "Accept": "application/json",
            },
            method="GET",
        )
        with urllib.request.urlopen(request, timeout=timeout + 15) as response:
            return json.loads(response.read().decode("utf-8"))


def parse_bitrix_date(value: Any) -> date | None:
    if not value:
        return None

    if isinstance(value, list):
        value = value[0] if value else None
    if not value:
        return None

    text = str(value).strip()
    for parser in (
        lambda item: datetime.fromisoformat(item.replace("Z", "+00:00")).date(),
        lambda item: datetime.strptime(item[:10], "%Y-%m-%d").date(),
        lambda item: datetime.strptime(item[:10], "%d.%m.%Y").date(),
    ):
        try:
            return parser(text)
        except ValueError:
            continue
    return None


def normalize_project_value(value: Any) -> str:
    if isinstance(value, list):
        value = value[0] if value else ""
    if isinstance(value, dict):
        return str(value.get("VALUE") or value.get("value") or value.get("ID") or value)
    return str(value or "").strip()


def get_company_title(client: BitrixClient, company_id: str, cache: dict[str, str]) -> str:
    if not company_id:
        return ""
    if company_id in cache:
        return cache[company_id]

    response = client.call("crm.company.get", {"id": company_id})
    company = response.get("result") or {}
    title = str(company.get("TITLE") or company_id)
    cache[company_id] = title
    return title


def get_deal(client: BitrixClient, deal_id: int) -> dict[str, Any]:
    response = client.call(
        "crm.item.get",
        {
            "entityTypeId": 2,
            "id": deal_id,
            "useOriginalUfNames": "Y",
        },
    )
    return response["result"]["item"]


def inspect_deal(client: BitrixClient, deal_id: int) -> None:
    deal = get_deal(client, deal_id)
    fields = client.call("crm.deal.fields", {})["result"]

    print(f"Сделка {deal_id}: {deal.get('title') or deal.get('TITLE')}")
    print()
    print("Поля сделки, где есть значение:")

    for key in sorted(deal):
        value = deal[key]
        if value in (None, "", [], {}):
            continue

        title = fields.get(key, {}).get("title") or fields.get(key, {}).get("formLabel") or ""
        if key.startswith("UF_") or "date" in key.lower() or "title" in key.lower():
            print(f"- {key}: {title} = {value}")


def find_users(client: BitrixClient, names: list[str]) -> None:
    for name in names:
        response = client.call("user.search", {"FILTER": {"%NAME": name}})
        users = response.get("result", [])
        print(f"\n{name}:")
        if not users:
            print("- не найдено")
            continue
        for user in users:
            full_name = " ".join(
                str(user.get(part, "")).strip()
                for part in ("LAST_NAME", "NAME", "SECOND_NAME")
                if user.get(part)
            )
            print(f"- ID {user.get('ID')}: {full_name}")


def task_exists_for_deal(client: BitrixClient, deal_id: int, responsible_ids: list[int]) -> bool:
    crm_link = f"D_{deal_id}"
    task_filter: dict[str, Any] = {
        "UF_CRM_TASK": crm_link,
    }
    if responsible_ids:
        task_filter["@RESPONSIBLE_ID"] = responsible_ids

    tasks = client.list_all(
        "tasks.task.list",
        {
            "filter": task_filter,
            "select": ["ID", "TITLE", "STATUS", "RESPONSIBLE_ID", "UF_CRM_TASK"],
        },
    )
    return bool(tasks)


def load_object_owners(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def find_object_owner(project_id: str, project: str, object_owners: dict[str, str]) -> str:
    if project_id in object_owners:
        return object_owners[project_id]
    if project in object_owners:
        return object_owners[project]

    project_lower = project.lower()
    for key, owner in object_owners.items():
        key_lower = key.lower()
        if key_lower and (key_lower in project_lower or project_lower in key_lower):
            return owner

    return "не назначено"


def format_alert_message(owner: str, items: list[dict[str, Any]]) -> str:
    lines = [
        "Сделки без задачи в кадры",
        "",
        f"Найдено: {len(items)}",
        "",
    ]
    for index, item in enumerate(items, start=1):
        lines.append(
            f"{index}. {item['title']} | {item['project']} | "
            f"заселение {item['settlement_date']}"
        )
        lines.append(f"https://crm.complect.org/crm/deal/details/{item['deal_id']}/")
        lines.append("")
    return "\n".join(lines)


def format_admin_report(
    checked_count: int,
    missing: list[dict[str, Any]],
    delivery_status: list[str],
) -> str:
    owner_titles = {
        "ivan": "Иван",
        "andrey": "Андрей",
        "husan_aleksey": "Хусан и Алексей",
        "не назначено": "Не назначено",
    }
    counts: dict[str, int] = {}
    for item in missing:
        owner = item["notify_to"]
        counts[owner] = counts.get(owner, 0) + 1

    lines = [
        "Отчёт по проверке сделок",
        "",
        f"Проверено сделок: {checked_count}",
        f"Найдено без задачи в кадры: {len(missing)}",
        "",
        "По получателям:",
    ]

    if counts:
        for owner, count in sorted(counts.items()):
            lines.append(f"{owner_titles.get(owner, owner)}: {count}")
    else:
        lines.append("Нет целевых сделок")

    lines.append("")
    lines.append("Рассылка:")
    if delivery_status:
        lines.extend(delivery_status)
    else:
        lines.append("не выполнялась")

    return "\n".join(lines)


def send_admin_report(
    max_client: MaxClient,
    checked_count: int,
    missing: list[dict[str, Any]],
    delivery_status: list[str],
) -> None:
    admin_user_id = os.getenv("MAX_ADMIN_USER_ID", "").strip()
    if not admin_user_id:
        print("MAX_ADMIN_USER_ID не заполнен, админский отчёт не отправлен.")
        return

    max_client.send_message(admin_user_id, format_admin_report(checked_count, missing, delivery_status))
    print("Админский отчёт отправлен.")


def send_notifications(missing: list[dict[str, Any]], checked_count: int) -> None:
    token = require_env("MAX_BOT_TOKEN")
    recipients = {
        "andrey": [os.getenv("MAX_ANDREY_USER_ID", "").strip()],
        "ivan": [os.getenv("MAX_IVAN_USER_ID", "").strip()],
        "husan_aleksey": [
            os.getenv("MAX_HUSAN_USER_ID", "").strip(),
            os.getenv("MAX_ALEKSEY_USER_ID", "").strip(),
        ],
    }
    max_client = MaxClient(token)
    delivery_status: list[str] = []

    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in missing:
        owner = item["notify_to"]
        if owner in recipients:
            grouped.setdefault(owner, []).append(item)

    if not grouped:
        print("Нет сделок с назначенным получателем для MAX.")
        send_admin_report(max_client, checked_count, missing, ["не выполнялась, нет сделок с назначенным получателем"])
        return

    for owner, items in grouped.items():
        filled_recipients = [recipient for recipient in recipients[owner] if recipient]
        if not filled_recipients:
            message = f"{owner}: не отправлено, не заполнены MAX user_id"
            delivery_status.append(message)
            print(message)
            continue
        for recipient in filled_recipients:
            max_client.send_message(recipient, format_alert_message(owner, items))
        message = f"{owner}: отправлено, {len(items)} сделок"
        delivery_status.append(message)
        print(message)

    send_admin_report(max_client, checked_count, missing, delivery_status)


def collect_user_objects(value: Any) -> list[dict[str, Any]]:
    users: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if "user_id" in value:
            users.append(value)
        for child in value.values():
            users.extend(collect_user_objects(child))
    elif isinstance(value, list):
        for item in value:
            users.extend(collect_user_objects(item))
    return users


def print_max_updates(watch_seconds: int | None) -> None:
    token = require_env("MAX_BOT_TOKEN")
    max_client = MaxClient(token)
    marker: int | None = None
    seen_users: set[str] = set()

    if watch_seconds:
        deadline = time.time() + watch_seconds
        print("Жду сообщения боту MAX.")
        print("Попросите нужных людей написать боту любое сообщение.")
    else:
        deadline = time.time()
        print("Читаю последние события MAX-бота.")

    while True:
        if watch_seconds:
            remaining = max(1, int(deadline - time.time()))
        else:
            remaining = 1

        if watch_seconds and remaining <= 0:
            break

        response = max_client.get_updates(marker=marker, timeout=min(30, remaining))
        marker = response.get("marker", marker)
        updates = response.get("updates", [])

        for update in updates:
            update_type = update.get("update_type") or update.get("type") or "unknown"
            for user in collect_user_objects(update):
                user_id = str(user.get("user_id") or "")
                if not user_id or user_id in seen_users:
                    continue
                seen_users.add(user_id)
                name = user.get("name") or " ".join(
                    str(user.get(part, "")).strip()
                    for part in ("first_name", "last_name")
                    if user.get(part)
                )
                username = user.get("username") or ""
                print(
                    f"- user_id: {user_id} | имя: {name or 'без имени'} | "
                    f"username: {username or '-'} | событие: {update_type}"
                )

        if not watch_seconds or time.time() >= deadline:
            break

    if not seen_users:
        print("Пользователей не увидела. Проверьте, что люди написали именно этому боту.")


def get_reassignment_source_ids(client: BitrixClient) -> set[str]:
    sources = client.list_all("crm.status.list", {"filter": {"ENTITY_ID": "SOURCE"}})
    source_ids = {
        str(source["STATUS_ID"]).strip()
        for source in sources
        if str(source.get("NAME") or "").strip().casefold() == "перевахтовка"
        and source.get("STATUS_ID")
    }
    if not source_ids:
        raise RuntimeError('В справочнике источников не найдена "Перевахтовка". Рассылка остановлена.')
    return source_ids


def audit_missing_tasks(
    client: BitrixClient,
    max_deals: int | None = None,
    notify: bool = False,
    created_since: str | None = None,
) -> None:
    settlement_field = require_env("SETTLEMENT_DATE_FIELD")
    project_field = require_env("PROJECT_FIELD")
    exclude_filled_fields = parse_str_list(os.getenv("EXCLUDE_FILLED_FIELDS", ""))
    responsible_ids = parse_int_list(os.getenv("HR_RESPONSIBLE_IDS", ""))
    older_than_days = int(os.getenv("OLDER_THAN_DAYS", "5"))
    cutoff = date.today() - timedelta(days=older_than_days)
    lookback_days_text = os.getenv("AUDIT_LOOKBACK_DAYS", "").strip()
    lookback_days = int(lookback_days_text) if lookback_days_text else None
    object_owners = load_object_owners(ROOT / "object_owners.json")
    company_cache: dict[str, str] = {}
    deal_filter: dict[str, Any] = {}
    if created_since:
        deal_filter[">=DATE_CREATE"] = created_since
    elif lookback_days:
        deal_filter[">=DATE_MODIFY"] = (date.today() - timedelta(days=lookback_days)).isoformat()

    excluded_source_ids = get_reassignment_source_ids(client)
    deals = client.list_all(
        "crm.deal.list",
        {
            "select": ["ID", "TITLE", "DATE_CREATE", "SOURCE_ID", settlement_field, project_field, *exclude_filled_fields],
            "filter": deal_filter,
            "order": {"DATE_CREATE" if created_since else "DATE_MODIFY": "DESC"},
        },
        max_items=max_deals,
    )

    missing: list[dict[str, Any]] = []
    for deal in deals:
        if str(deal.get("SOURCE_ID") or "").strip() in excluded_source_ids:
            continue
        deal_id = int(deal["ID"])
        settlement_date = parse_bitrix_date(deal.get(settlement_field))
        if not settlement_date or settlement_date > cutoff:
            continue
        if any(deal.get(field) for field in exclude_filled_fields):
            continue

        if task_exists_for_deal(client, deal_id, responsible_ids):
            continue

        project_id = normalize_project_value(deal.get(project_field))
        project = get_company_title(client, project_id, company_cache) if project_id else ""
        missing.append(
            {
                "deal_id": deal_id,
                "title": deal.get("TITLE"),
                "settlement_date": settlement_date.isoformat(),
                "project_id": project_id,
                "project": project,
                "notify_to": find_object_owner(project_id, project, object_owners),
            }
        )

    if not missing:
        print("Проблемных сделок не найдено.")
        if notify:
            token = require_env("MAX_BOT_TOKEN")
            send_admin_report(MaxClient(token), len(deals), missing, ["не выполнялась, целевых сделок нет"])
        return

    print(f"Проверено сделок: {len(deals)}")
    print("Найдены сделки с датой заселения старше порога, но без задачи в кадры:")
    for item in missing:
        print(
            f"- Сделка {item['deal_id']}: {item['title']} | "
            f"заселение {item['settlement_date']} | "
            f"объект: {item['project']} ({item['project_id']}) | "
            f"кому: {item['notify_to']}"
        )

    if notify:
        send_notifications(missing, len(deals))


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")

    load_dotenv(ROOT / ".env")

    parser = argparse.ArgumentParser(
        description="Проверка сделок Bitrix24, где есть заселение, но нет задачи в кадры."
    )
    parser.add_argument("--inspect-deal", type=int, help="Показать заполненные поля одной сделки")
    parser.add_argument("--find-users", nargs="*", help="Найти пользователей Bitrix24 по имени")
    parser.add_argument("--audit", action="store_true", help="Запустить проверку проблемных сделок")
    parser.add_argument("--max-deals", type=int, help="Ограничить количество сделок для тестового аудита")
    parser.add_argument("--created-since", help="Проверять только сделки, созданные с даты YYYY-MM-DD")
    parser.add_argument("--notify", action="store_true", help="Отправить найденные сделки в MAX")
    parser.add_argument("--max-updates", action="store_true", help="Показать user_id людей, которые пишут MAX-боту")
    parser.add_argument("--watch-seconds", type=int, help="Сколько секунд ждать новые MAX-сообщения")
    args = parser.parse_args()

    client = BitrixClient(require_env("BITRIX_WEBHOOK_URL"))

    if args.inspect_deal:
        inspect_deal(client, args.inspect_deal)
        return

    if args.find_users is not None:
        names = args.find_users or ["Анна", "Юлия"]
        find_users(client, names)
        return

    if args.audit:
        audit_missing_tasks(client, args.max_deals, args.notify, args.created_since)
        return

    if args.max_updates:
        print_max_updates(args.watch_seconds)
        return

    parser.print_help()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(error, file=sys.stderr)
        raise SystemExit(1)
