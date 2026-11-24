import argparse
import json
import os
import re
import sqlite3
from base64 import b64encode
from contextlib import closing
from datetime import datetime, timedelta, timezone
from functools import partial
from getpass import getpass
from hmac import compare_digest
from html import escape
from http.client import HTTPException, HTTPSConnection
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Event, Thread
from time import time as unix_time
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

ROOT = Path(__file__).resolve().parent
DATA_DIR = Path.home() / ".bo-bo-local"
MOSCOW_TIME = timezone(timedelta(hours=3))
PHONE_FORMAT = re.compile(r"(?:\+7|8)[ -]*(?:\([0-9]{3}\)|[0-9]{3})[ -]*[0-9]{3}[ -]*[0-9]{2}[ -]*[0-9]{2}")


def server_settings():
    port_value = os.environ.get("BOBO_PORT", "8000").strip()
    if not re.fullmatch(r"[0-9]{1,5}", port_value) or not 1 <= int(port_value) <= 65535:
        raise ValueError("BOBO_PORT должен быть числом от 1 до 65535.")
    port = int(port_value)

    value = os.environ.get("BOBO_PUBLIC_ORIGIN", "").strip() or f"http://127.0.0.1:{port}"
    try:
        parsed = urlsplit(value)
        public_port = parsed.port
        hostname = parsed.hostname or ""
    except ValueError:
        raise ValueError("Проверьте адрес BOBO_PUBLIC_ORIGIN.") from None
    local = hostname in {"127.0.0.1", "localhost"}
    if (
        (parsed.scheme != "https" and not (local and parsed.scheme == "http"))
        or not re.fullmatch(r"[a-zA-Z0-9.-]+(?::[0-9]+)?", parsed.netloc)
        or parsed.path not in {"", "/"}
        or "?" in value or "#" in value or public_port == 0
    ):
        raise ValueError("BOBO_PUBLIC_ORIGIN должен содержать адрес сайта без пути. Для домена нужен HTTPS.")

    default_port = 443 if parsed.scheme == "https" else 80
    host = hostname if public_port in (None, default_port) else f"{hostname}:{public_port}"
    return port, host, f"{parsed.scheme}://{host}"


def connect():
    DATA_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    return sqlite3.connect(DATA_DIR / "bookings.sqlite3")


def initialize():
    with closing(connect()) as db, db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS bookings (
                id INTEGER PRIMARY KEY,
                request_id TEXT NOT NULL UNIQUE,
                date TEXT NOT NULL,
                time TEXT NOT NULL,
                guests INTEGER NOT NULL,
                phone TEXT NOT NULL
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS telegram_outbox (
                booking_id INTEGER PRIMARY KEY REFERENCES bookings (id),
                chat_id INTEGER NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                next_attempt_at INTEGER NOT NULL DEFAULT 0,
                sent_at INTEGER
            )
        """)


def validate(data):
    if not isinstance(data, dict):
        raise ValueError("Проверьте данные заявки.")

    date, time, guests, phone, request_id = (
        data.get(key) for key in ("date", "time", "guests", "phone", "requestId")
    )
    if (
        not isinstance(date, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", date)
        or not isinstance(time, str) or not re.fullmatch(r"[0-9]{2}:[0-9]{2}", time)
    ):
        raise ValueError("Укажите дату и время.")

    try:
        datetime.fromisoformat(f"{date}T{time}")
    except ValueError:
        raise ValueError("Проверьте дату и время.") from None

    if type(guests) is not int or not 1 <= guests <= 9_007_199_254_740_991:
        raise ValueError("Укажите целое количество гостей от 1.")

    if not isinstance(phone, str) or len(phone) > 26 or not PHONE_FORMAT.fullmatch(phone.strip()):
        raise ValueError("Введите телефон в формате +7 или 8 и ещё 10 цифр.")

    try:
        if not isinstance(request_id, str) or len(request_id) != 36:
            raise ValueError
        request_id = str(UUID(request_id))
    except ValueError:
        raise ValueError("Обновите страницу и отправьте заявку снова.") from None

    digits = re.sub(r"[^0-9]", "", phone)
    return request_id, date, time, guests, "+7" + digits[1:]


def save_booking(request_id, date, time, guests, phone, telegram_chat_id=None):
    with closing(connect()) as db, db:
        # Lock before checking the key so concurrent retries return one booking ID.
        db.execute("BEGIN IMMEDIATE")
        existing = db.execute(
            "SELECT id, date, time, guests, phone FROM bookings WHERE request_id = ?",
            (request_id,),
        ).fetchone()
        if existing:
            if existing[1:] != (date, time, guests, phone):
                raise ValueError("Данные заявки изменились. Обновите страницу.")
            return existing[0], False

        appointment = datetime.fromisoformat(f"{date}T{time}").replace(tzinfo=MOSCOW_TIME)
        if appointment <= datetime.now(MOSCOW_TIME):
            raise ValueError("Выберите дату и время в будущем.")

        result = db.execute(
            "INSERT INTO bookings (request_id, date, time, guests, phone) VALUES (?, ?, ?, ?, ?)",
            (request_id, date, time, guests, phone),
        )
        booking_id = result.lastrowid
        if telegram_chat_id is not None:
            db.execute(
                "INSERT INTO telegram_outbox (booking_id, chat_id) VALUES (?, ?)",
                (booking_id, telegram_chat_id),
            )
        return booking_id, True


class TelegramError(Exception):
    pass


def telegram_call(token, method, payload):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    timeout = 15 if method == "getUpdates" else 4
    with closing(HTTPSConnection("api.telegram.org", timeout=timeout)) as connection:
        try:
            connection.request(
                "POST",
                f"/bot{token}/{method}",
                body=body,
                headers={"Content-Type": "application/json"},
            )
            response = connection.getresponse()
            result = json.loads(response.read())
        except (OSError, HTTPException, ValueError):
            raise TelegramError("Нет ответа от Telegram.") from None

    if response.status != 200 or not isinstance(result, dict) or result.get("ok") is not True:
        raise TelegramError(f"Telegram отклонил запрос (HTTP {response.status}).")
    if "result" not in result:
        raise TelegramError("Telegram вернул неполный ответ.")
    return result["result"]


def configure_telegram():
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if bool(token) != bool(chat_id):
        raise TelegramError("Задайте TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID вместе.")

    token = token or getpass("Токен тестового бота: ").strip()
    if not re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]+", token):
        raise TelegramError("Проверьте формат токена бота.")

    if chat_id:
        if not re.fullmatch(r"-?[0-9]{1,16}", chat_id) or not 0 < abs(int(chat_id)) < 2**52:
            raise TelegramError("TELEGRAM_CHAT_ID должен содержать числовой ID чата.")
        return token, int(chat_id)

    updates = telegram_call(token, "getUpdates", {"allowed_updates": ["message"]})
    chats = {}
    for update in updates:
        chat = update.get("message", {}).get("chat", {})
        chat_type = chat.get("type")
        if chat_type == "private" or (
            chat_type in {"group", "supergroup"} and not chat.get("username")
        ):
            chats[chat["id"]] = chat.get("title") or "Личный чат"

    if not chats:
        raise TelegramError(
            "Тестовый чат не найден. Отправьте боту /start в личном чате "
            "или /start@имя_бота в закрытой тестовой группе и запустите сервер снова."
        )

    print("Чаты, в которых тестовый бот получил сообщения:")
    for chat_id, title in chats.items():
        print(f"{chat_id} | {title}")

    try:
        chat_id = int(input("ID тестового чата: ").strip())
    except ValueError:
        raise TelegramError("Введите ID из списка.") from None
    if chat_id not in chats:
        raise TelegramError("Выберите тестовый чат из списка.")
    return token, chat_id


def deliver_next_notification(token, chat_id):
    now = int(unix_time())
    with closing(connect()) as db, db:
        # Save a lease before calling Telegram so concurrent workers do not send the same row.
        db.execute("BEGIN IMMEDIATE")
        entry = db.execute("""
            SELECT b.id, b.date, b.time, b.guests, b.phone, q.attempts
            FROM telegram_outbox AS q
            JOIN bookings AS b ON b.id = q.booking_id
            WHERE q.chat_id = ? AND q.sent_at IS NULL AND q.next_attempt_at <= ?
            ORDER BY q.next_attempt_at, q.booking_id
            LIMIT 1
        """, (chat_id, now)).fetchone()
        if entry is None:
            return False
        booking_id, date, time, guests, phone, attempts = entry
        attempt = attempts + 1
        db.execute("""
            UPDATE telegram_outbox SET attempts = ?, next_attempt_at = ?
            WHERE booking_id = ?
        """, (attempt, now + 120, booking_id))

    date_label = datetime.strptime(date, "%Y-%m-%d").strftime("%d.%m.%Y")
    message = (
        f"bo-bo · Тестовая заявка №{booking_id}\n"
        f"Дата и время: {date_label} в {time}\n"
        f"Гостей: {guests}\n"
        f"Телефон: {phone}"
    )
    sent_at = None
    try:
        telegram_call(token, "sendMessage", {
            "chat_id": chat_id,
            "text": message,
            "protect_content": True,
        })
        sent_at = int(unix_time())
    except TelegramError as error:
        print(f"Заявка №{booking_id} сохранена. Повтор уведомления запланирован. {error}", flush=True)

    # Start at 5 seconds and cap the delay at 5 minutes.
    delay = min(5 * 2 ** min(attempt - 1, 6), 300)
    with closing(connect()) as db, db:
        db.execute("""
            UPDATE telegram_outbox SET sent_at = ?, next_attempt_at = ?
            WHERE booking_id = ? AND attempts = ?
        """, (sent_at, int(unix_time()) + delay, booking_id, attempt))
    return True


def run_notifications(stop, telegram):
    while not stop.is_set():
        try:
            if deliver_next_notification(*telegram):
                continue
        except sqlite3.Error:
            print("Не удалось обновить очередь уведомлений. Повторим попытку.", flush=True)
        stop.wait(1)


JOURNAL_PAGE = """<!doctype html>
<html lang="ru">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Журнал заявок — bo-bo</title>
<style>
  body {{ margin: 0; background: #171615; color: #e8dcc9; font: 1rem/1.5 system-ui, sans-serif; }}
  main {{ max-width: 56rem; margin: auto; padding: 1.25rem; }}
  h1 {{ margin: 0 0 1rem; }}
  ol {{ list-style: none; margin: 0; padding: 0; display: grid; gap: .75rem; }}
  li {{ background: #26221e; padding: .875rem 1rem; border-radius: .5rem; }}
  dl {{ display: flex; flex-wrap: wrap; gap: .75rem 2rem; margin: .5rem 0 0; }}
  dt {{ color: #c6baab; }}
  dd {{ margin: 0; overflow-wrap: anywhere; }}
  a {{ color: #e6bc7a; }}
  nav {{ display: flex; flex-wrap: wrap; gap: 1.5rem; margin-top: 1rem; }}
</style>
<main>
  <h1>Заявки с сайта bo-bo</h1>
  {entries}
  {navigation}
</main>
</html>
"""
JOURNAL_PAGE_SIZE = 50


def render_journal(before):
    with closing(connect()) as db:
        rows = db.execute("""
            SELECT id, date, time, guests, phone
            FROM bookings WHERE id < ?
            ORDER BY id DESC LIMIT ?
        """, (before, JOURNAL_PAGE_SIZE + 1)).fetchall()

    entries = []
    for booking_id, date, time, guests, phone in rows[:JOURNAL_PAGE_SIZE]:
        day = escape(".".join(reversed(date.split("-"))))
        phone_text = escape(phone)
        if re.fullmatch(r"\+7[0-9]{10}", phone):
            phone_text = f'<a href="tel:{phone}">{phone_text}</a>'
        entries.append(f"""
            <li><strong>Заявка №{booking_id}</strong><dl>
                <div><dt>Дата и время визита</dt><dd>{day} в {escape(time)}</dd></div>
                <div><dt>Гостей</dt><dd>{guests}</dd></div>
                <div><dt>Телефон</dt><dd>{phone_text}</dd></div>
            </dl></li>
        """)

    links = []
    if before < 2**63 - 1:
        links.append('<a href="/journal/">К последним заявкам</a>')
    if len(rows) > JOURNAL_PAGE_SIZE:
        next_before = rows[JOURNAL_PAGE_SIZE - 1][0]
        links.append(f'<a href="/journal/?before={next_before}">Более ранние заявки</a>')

    return JOURNAL_PAGE.format(
        entries=f'<ol>{"".join(entries)}</ol>' if entries else '<p>Заявок пока нет.</p>',
        navigation=f'<nav aria-label="Страницы журнала">{"".join(links)}</nav>' if links else '',
    )


class BookingHandler(SimpleHTTPRequestHandler):
    def __init__(
        self, *args, public_host, public_origin, telegram_chat_id=None, journal_credentials=None, **kwargs
    ):
        self.public_host = public_host
        self.public_origin = public_origin
        self.telegram_chat_id = telegram_chat_id
        self.journal_credentials = journal_credentials
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def matches_host(self):
        return self.headers.get("Host", "").lower() == self.public_host

    def do_GET(self):
        address = urlsplit(self.path)
        if address.path == "/journal/":
            self.show_journal(address.query)
            return
        if self.path == "/api/bookings/status":
            if self.matches_host():
                self.reply(200, bookingAvailable=True)
            else:
                self.reply(403, error="Откройте форму с адреса сайта.")
            return
        super().do_GET()

    def show_journal(self, query):
        if not self.journal_credentials or not self.matches_host():
            self.send_error(404)
            return

        scheme, _, credentials = self.headers.get("Authorization", "").partition(" ")
        if scheme.lower() != "basic" or not compare_digest(
            credentials.encode("latin-1"), self.journal_credentials
        ):
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="bo-bo journal", charset="UTF-8"')
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        cursor = parse_qs(query).get("before", [str(2**63 - 1)])[0]
        if not re.fullmatch(r"[0-9]{1,19}", cursor) or not 0 < int(cursor) < 2**63:
            self.send_error(400)
            return

        try:
            body = render_journal(int(cursor)).encode("utf-8")
        except sqlite3.Error:
            self.send_error(503)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def send_head(self):
        if not self.matches_host():
            self.send_error(403)
            return None

        path = urlsplit(self.path).path
        if path in {"/", "/index.html", "/script.js", "/style.css"}:
            return super().send_head()

        assets_dir = ROOT / "assets"
        target = Path(self.translate_path(path)).resolve()
        if path.startswith("/assets/") and assets_dir in target.parents and target.is_file():
            return super().send_head()

        self.send_error(404)
        return None

    def do_POST(self):
        if not self.matches_host() or self.headers.get("Origin") not in (None, self.public_origin):
            self.reply(403, error="Откройте форму с адреса сайта.")
            return
        if self.path != "/api/bookings":
            self.reply(404, error="Адрес формы не найден.")
            return
        if self.headers.get_content_type() != "application/json":
            self.reply(415, error="Ожидались данные в формате JSON.")
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 4096:
                raise ValueError
            data = json.loads(self.rfile.read(length))
        except (ValueError, RecursionError):
            self.reply(400, error="Не удалось прочитать данные формы.")
            return

        try:
            booking = validate(data)
            booking_id, created = save_booking(*booking, telegram_chat_id=self.telegram_chat_id)
        except ValueError as error:
            self.reply(400, error=str(error))
            return
        except sqlite3.Error:
            self.log_error("Local booking database write failed.")
            self.reply(500, error="Не удалось сохранить заявку. Попробуйте ещё раз.")
            return

        self.reply(201 if created else 200, id=booking_id)

    def reply(self, status, **payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def main():
    global DATA_DIR
    parser = argparse.ArgumentParser(description="Запуск тестовой формы bo-bo.")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--list", action="store_true", help="Показать тестовые заявки.")
    modes.add_argument("--telegram", action="store_true", help="Включить уведомления в тестовый чат.")
    parser.add_argument("--journal", action="store_true", help="Включить локальный журнал заявок.")
    args = parser.parse_args()
    if args.list and args.journal:
        parser.error("--list и --journal нельзя использовать вместе.")
    configured_dir = os.environ.get("BOBO_DATA_DIR", "").strip()
    if configured_dir:
        DATA_DIR = Path(configured_dir).expanduser().resolve()
    assets_dir = (ROOT / "assets").resolve()
    if DATA_DIR == assets_dir or assets_dir in DATA_DIR.parents:
        parser.exit(1, "Папка BOBO_DATA_DIR должна находиться вне публичной папки assets.\n")
    try:
        initialize()
    except (OSError, sqlite3.Error):
        parser.exit(1, "Не удалось открыть базу. Проверьте папку и права записи BOBO_DATA_DIR.\n")

    if args.list:
        with closing(connect()) as db:
            rows = db.execute("SELECT id, date, time, guests FROM bookings ORDER BY id")
            for booking_id, date, time, guests in rows:
                print(f"#{booking_id} | {date} {time} | Гостей: {guests}")
        return

    try:
        port, public_host, public_origin = server_settings()
    except ValueError as error:
        parser.exit(1, f"Настройка сервера: {error}\n")

    journal_credentials = None
    if args.journal:
        if public_origin != f"http://127.0.0.1:{port}":
            parser.error("--journal доступен только при локальном запуске на 127.0.0.1.")
        password = getpass("Придумайте пароль для тестового журнала (не меньше 12 символов): ")
        if not 12 <= len(password) <= 128 or not password.isprintable() or not password.strip():
            parser.error("Укажите пароль журнала из 12–128 печатных символов.")
        journal_credentials = b64encode(f"bo-bo:{password}".encode("utf-8"))
        del password

    try:
        telegram = configure_telegram() if args.telegram else None
    except (TelegramError, EOFError) as error:
        parser.exit(1, f"Настройка Telegram: {error}\n")

    handler = partial(
        BookingHandler,
        public_host=public_host,
        public_origin=public_origin,
        telegram_chat_id=telegram[1] if telegram else None,
        journal_credentials=journal_credentials,
    )
    with ThreadingHTTPServer(("127.0.0.1", port), handler) as server:
        stop = Event()
        worker = None
        if telegram:
            worker = Thread(target=run_notifications, args=(stop, telegram), daemon=True)
            worker.start()
        print(f"Откройте {public_origin}/ в браузере.", flush=True)
        if journal_credentials:
            print(f"Журнал: {public_origin}/journal/ (логин bo-bo).", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            stop.set()
            if worker:
                worker.join(timeout=5)


if __name__ == "__main__":
    main()
