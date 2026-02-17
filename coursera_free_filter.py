#!/usr/bin/env python3
import argparse
import csv
import html
import os
import re
import sqlite3
import sys
import webbrowser
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse


DB_FILE = "coursera_free_filter.db"

CLASS_TRULY_FREE = "TRULY_FREE"
CLASS_PAID_OR_PREVIEW = "PAID_OR_PREVIEW"
CLASS_UNKNOWN = "UNKNOWN"

STATUS_PENDING = "pending"
STATUS_OPENED = "opened"
STATUS_DONE = "done"

COURSE_PATH_PREFIXES = ("/learn/", "/specializations/", "/professional-certificates/")
REJECT_PHRASES = (
    "this course costs",
    "preview this course",
    "start free trial",
    "coursera plus",
    "subscribe",
)
PAYMENT_CONTEXT_NEAR_DOLLAR = (
    "cost",
    "costs",
    "per month",
    "month",
    "subscribe",
    "free trial",
    "trial",
)
TRACKING_PARAM_PREFIXES = ("utm_",)
TRACKING_PARAMS_EXACT = {"fbclid", "gclid", "ref", "referral", "trk"}


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []
        self.title_text: list[str] = []
        self.capture_title = False
        self.canonical_url = None
        self.og_url = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        if tag == "a":
            href = attrs_dict.get("href")
            if href:
                self.hrefs.append(href)
        elif tag == "title":
            self.capture_title = True
        elif tag == "link":
            rel = (attrs_dict.get("rel") or "").lower()
            href = attrs_dict.get("href")
            if "canonical" in rel and href:
                self.canonical_url = href
        elif tag == "meta":
            prop = (attrs_dict.get("property") or "").lower()
            name = (attrs_dict.get("name") or "").lower()
            content = attrs_dict.get("content")
            if content and (prop == "og:url" or name == "og:url"):
                self.og_url = content

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self.capture_title = False

    def handle_data(self, data: str) -> None:
        if self.capture_title:
            self.title_text.append(data)


def utc_now() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS courses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT NOT NULL UNIQUE,
            title TEXT,
            tags TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            classification TEXT NOT NULL DEFAULT 'UNKNOWN',
            class_reason TEXT,
            html_path TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_opened_at TEXT
        )
        """
    )
    conn.commit()


def get_conn(db_path: str = DB_FILE) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def _strip_fragment(url: str) -> str:
    parsed = urlparse(url)
    return urlunparse(parsed._replace(fragment=""))


def _is_tracking_param(key: str) -> bool:
    lk = key.lower()
    return any(lk.startswith(prefix) for prefix in TRACKING_PARAM_PREFIXES) or lk in TRACKING_PARAMS_EXACT


def normalize_url(url: str, base_url: str | None = None) -> str:
    if not url:
        raise ValueError("empty URL")
    url = html.unescape(url.strip())
    if base_url:
        url = urljoin(base_url, url)

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"unsupported URL scheme: {parsed.scheme or '(none)'}")
    if not parsed.netloc:
        raise ValueError("URL missing host")

    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]

    query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
    kept = [(k, v) for (k, v) in query_pairs if not _is_tracking_param(k)]
    query = urlencode(kept, doseq=True)

    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    normalized = urlunparse(
        (
            "https",
            host,
            path.rstrip("/") if path != "/" else path,
            "",
            query,
            "",
        )
    )
    return _strip_fragment(normalized)


def is_coursera_course_url(url: str) -> bool:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    if host != "coursera.org":
        return False
    return any(parsed.path.startswith(prefix) for prefix in COURSE_PATH_PREFIXES)


def extract_course_urls_from_html(html_text: str, base_url: str = "https://www.coursera.org") -> list[str]:
    parser = LinkParser()
    parser.feed(html_text)
    results = []
    seen = set()
    for href in parser.hrefs:
        try:
            normalized = normalize_url(href, base_url=base_url)
        except ValueError:
            continue
        if not is_coursera_course_url(normalized):
            continue
        if normalized not in seen:
            seen.add(normalized)
            results.append(normalized)
    return results


def parse_title_from_html(html_text: str) -> str | None:
    parser = LinkParser()
    parser.feed(html_text)
    title = " ".join(part.strip() for part in parser.title_text if part.strip()).strip()
    return title or None


def extract_course_url_from_course_html(html_text: str, strict_meta: bool = False) -> str | None:
    parser = LinkParser()
    parser.feed(html_text)
    candidates = [parser.canonical_url, parser.og_url]
    if not strict_meta:
        candidates.extend(parser.hrefs)
    for candidate in candidates:
        if not candidate:
            continue
        try:
            normalized = normalize_url(candidate, base_url="https://www.coursera.org")
        except ValueError:
            continue
        if is_coursera_course_url(normalized):
            return normalized
    return None


def _contains_phrase(text_l: str, phrase: str) -> bool:
    return phrase.lower() in text_l


def _dollar_payment_signal(text_l: str) -> bool:
    for match in re.finditer(r"\$[\d.,]+", text_l):
        start = max(match.start() - 50, 0)
        end = min(match.end() + 50, len(text_l))
        window = text_l[start:end]
        if any(term in window for term in PAYMENT_CONTEXT_NEAR_DOLLAR):
            return True
    return False


def classify_html(html_text: str) -> tuple[str, str]:
    text_l = re.sub(r"\s+", " ", html_text).lower()

    reject_hits = [phrase for phrase in REJECT_PHRASES if _contains_phrase(text_l, phrase)]
    dollar_hit = _dollar_payment_signal(text_l)
    if reject_hits or dollar_hit:
        reasons = []
        if reject_hits:
            reasons.extend(f"reject phrase: '{p}'" for p in reject_hits)
        if dollar_hit:
            reasons.append("payment pricing near '$' detected")
        return (CLASS_PAID_OR_PREVIEW, "; ".join(reasons))

    has_full_no_cert = "full course, no certificate" in text_l
    has_enroll_free = "enroll for free" in text_l
    has_no_cert = "no certificate" in text_l

    if has_full_no_cert:
        return (CLASS_TRULY_FREE, "matched 'Full Course, No Certificate' and no reject phrases")
    if has_enroll_free and has_no_cert:
        return (
            CLASS_TRULY_FREE,
            "matched 'Enroll for free' + 'No Certificate' and no reject phrases",
        )
    return (CLASS_UNKNOWN, "insufficient signals for truly-free or paid/preview")


def ensure_course(
    conn: sqlite3.Connection,
    url: str,
    title: str | None = None,
    tags: Iterable[str] | None = None,
    html_path: str | None = None,
) -> int:
    now = utc_now()
    tags_serialized = ",".join(sorted(set(tags or []))) if tags else None
    existing = conn.execute("SELECT id, tags, title, html_path FROM courses WHERE url = ?", (url,)).fetchone()
    if existing:
        merged_tags = set((existing["tags"] or "").split(",")) if existing["tags"] else set()
        merged_tags.update(tag for tag in (tags or []) if tag)
        final_tags = ",".join(sorted(tag for tag in merged_tags if tag)) or None
        final_title = title or existing["title"]
        final_html = html_path or existing["html_path"]
        conn.execute(
            """
            UPDATE courses
            SET title = ?, tags = ?, html_path = ?, updated_at = ?
            WHERE id = ?
            """,
            (final_title, final_tags, final_html, now, existing["id"]),
        )
        conn.commit()
        return int(existing["id"])

    cur = conn.execute(
        """
        INSERT INTO courses (url, title, tags, status, classification, class_reason, html_path, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (url, title, tags_serialized, STATUS_PENDING, CLASS_UNKNOWN, "not yet classified", html_path, now, now),
    )
    conn.commit()
    return int(cur.lastrowid)


def read_text_file(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return Path(path).read_text(encoding="utf-8", errors="replace")


def cmd_add_url(args: argparse.Namespace) -> int:
    conn = get_conn(args.db)
    try:
        normalized = normalize_url(args.url)
        if not is_coursera_course_url(normalized):
            print("Error: URL must be a coursera.org course/specialization/professional-certificate link.")
            return 2
        row_id = ensure_course(conn, normalized, tags=args.tag)
        print(f"Added/updated course id={row_id} url={normalized}")
        return 0
    except ValueError as exc:
        print(f"Error: {exc}")
        return 2
    finally:
        conn.close()


def cmd_import_urls(args: argparse.Namespace) -> int:
    conn = get_conn(args.db)
    path = Path(args.path)
    if not path.exists():
        print(f"Error: file not found: {path}")
        return 2

    added = 0
    skipped = 0
    try:
        if path.suffix.lower() == ".csv":
            with path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                for row in reader:
                    if not row:
                        continue
                    url = row[0].strip()
                    title = row[1].strip() if len(row) > 1 and row[1] else None
                    if url.lower() == "url":
                        continue
                    try:
                        normalized = normalize_url(url)
                        if not is_coursera_course_url(normalized):
                            skipped += 1
                            continue
                        ensure_course(conn, normalized, title=title)
                        added += 1
                    except ValueError:
                        skipped += 1
        else:
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    url = line.strip()
                    if not url or url.startswith("#"):
                        continue
                    try:
                        normalized = normalize_url(url)
                        if not is_coursera_course_url(normalized):
                            skipped += 1
                            continue
                        ensure_course(conn, normalized)
                        added += 1
                    except ValueError:
                        skipped += 1
    finally:
        conn.close()

    print(f"Imported URLs: added_or_updated={added} skipped={skipped}")
    return 0


def cmd_import_html(args: argparse.Namespace) -> int:
    conn = get_conn(args.db)
    path = Path(args.path)
    if not path.exists():
        print(f"Error: file not found: {path}")
        return 2

    html_text = read_text_file(str(path))
    urls = extract_course_urls_from_html(html_text)
    added = 0
    for url in urls:
        ensure_course(conn, url)
        added += 1
    conn.close()
    print(f"Imported listing HTML: extracted={len(urls)} added_or_updated={added}")
    return 0


def cmd_import_course_html(args: argparse.Namespace) -> int:
    conn = get_conn(args.db)
    path = Path(args.path)
    if not path.exists():
        print(f"Error: file not found: {path}")
        return 2

    html_text = read_text_file(str(path))
    url = extract_course_url_from_course_html(html_text)
    title = parse_title_from_html(html_text)
    if not url:
        print("Error: Could not find a Coursera course URL in the file (canonical/og:url/link).")
        return 2

    row_id = ensure_course(conn, url, title=title, html_path=str(path.resolve()))
    conn.close()
    print(f"Imported course HTML for id={row_id} url={url} html_path={path.resolve()}")
    return 0


def _classify_row(conn: sqlite3.Connection, row: sqlite3.Row) -> tuple[str, str]:
    html_path = row["html_path"]
    if not html_path:
        return (CLASS_UNKNOWN, "no imported course HTML (use import-course-html)")
    path = Path(html_path)
    if not path.exists():
        return (CLASS_UNKNOWN, f"html file missing: {html_path}")
    html_text = read_text_file(str(path))
    return classify_html(html_text)


def _iter_html_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path] if path.suffix.lower() in (".html", ".htm") else []
    if not path.is_dir():
        return []
    files = [p for p in path.rglob("*") if p.is_file() and p.suffix.lower() in (".html", ".htm")]
    files.sort(key=lambda p: str(p).lower())
    return files


def _classify_all_rows(conn: sqlite3.Connection) -> tuple[int, int, int]:
    rows = conn.execute("SELECT * FROM courses ORDER BY id ASC").fetchall()
    now = utc_now()
    for row in rows:
        classification, reason = _classify_row(conn, row)
        conn.execute(
            "UPDATE courses SET classification = ?, class_reason = ?, updated_at = ? WHERE id = ?",
            (classification, reason, now, row["id"]),
        )
    conn.commit()

    free_count = conn.execute(
        "SELECT COUNT(*) FROM courses WHERE classification = ?",
        (CLASS_TRULY_FREE,),
    ).fetchone()[0]
    paid_count = conn.execute(
        "SELECT COUNT(*) FROM courses WHERE classification = ?",
        (CLASS_PAID_OR_PREVIEW,),
    ).fetchone()[0]
    unknown_count = conn.execute(
        "SELECT COUNT(*) FROM courses WHERE classification = ?",
        (CLASS_UNKNOWN,),
    ).fetchone()[0]
    return int(free_count), int(paid_count), int(unknown_count)


def cmd_quick_free_list(args: argparse.Namespace) -> int:
    conn = get_conn(args.db)
    target = Path(args.path)
    if not target.exists():
        print(f"Error: path not found: {target}")
        conn.close()
        return 2

    if args.fresh:
        conn.execute("DELETE FROM courses")
        conn.commit()

    html_files = _iter_html_files(target)
    if not html_files:
        print("Error: no .html/.htm files found at provided path.")
        conn.close()
        return 2

    listing_links = 0
    course_pages_linked = 0
    for file_path in html_files:
        html_text = read_text_file(str(file_path))

        urls = extract_course_urls_from_html(html_text)
        for url in urls:
            ensure_course(conn, url)
        listing_links += len(urls)

        course_url = extract_course_url_from_course_html(html_text, strict_meta=True)
        if course_url:
            title = parse_title_from_html(html_text)
            ensure_course(conn, course_url, title=title, html_path=str(file_path.resolve()))
            course_pages_linked += 1

    free_count, paid_count, unknown_count = _classify_all_rows(conn)
    free_rows = conn.execute(
        "SELECT id, url, title FROM courses WHERE classification = ? ORDER BY id ASC",
        (CLASS_TRULY_FREE,),
    ).fetchall()

    print(
        f"Scanned HTML files={len(html_files)} listing_links={listing_links} "
        f"course_pages_with_meta_url={course_pages_linked}"
    )
    print(f"Classified: TRULY_FREE={free_count} PAID_OR_PREVIEW={paid_count} UNKNOWN={unknown_count}")
    if free_rows:
        print("\nTRULY_FREE courses:")
        for row in free_rows:
            title_suffix = f" | {row['title']}" if row["title"] else ""
            print(f"{row['id']:>4} | {row['url']}{title_suffix}")
    else:
        print("\nNo TRULY_FREE courses found yet.")
        print("Tip: save course pages after clicking 'Enroll for free' and showing the enroll modal.")

    if args.output:
        output_path = Path(args.output)
        with output_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["id", "url", "title", "classification"])
            for row in free_rows:
                writer.writerow([row["id"], row["url"], row["title"], CLASS_TRULY_FREE])
        print(f"Wrote TRULY_FREE CSV: {output_path}")

    conn.close()
    return 0


def cmd_classify(args: argparse.Namespace) -> int:
    conn = get_conn(args.db)
    if args.target == "all":
        rows = conn.execute("SELECT * FROM courses ORDER BY id ASC").fetchall()
    else:
        rows = conn.execute("SELECT * FROM courses WHERE id = ?", (args.target,)).fetchall()

    if not rows:
        print("No matching courses.")
        conn.close()
        return 0

    now = utc_now()
    for row in rows:
        classification, reason = _classify_row(conn, row)
        conn.execute(
            "UPDATE courses SET classification = ?, class_reason = ?, updated_at = ? WHERE id = ?",
            (classification, reason, now, row["id"]),
        )
        print(f"id={row['id']} class={classification} reason={reason} url={row['url']}")
    conn.commit()
    conn.close()
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    conn = get_conn(args.db)
    where = []
    params: list[str] = []
    if args.status:
        where.append("status = ?")
        params.append(args.status)
    if args.classification:
        where.append("classification = ?")
        params.append(args.classification)
    query = "SELECT * FROM courses"
    if where:
        query += " WHERE " + " AND ".join(where)
    query += " ORDER BY id ASC"

    rows = conn.execute(query, params).fetchall()
    conn.close()
    if not rows:
        print("No courses found.")
        return 0

    for row in rows:
        print(
            f"{row['id']:>4} | {row['status']:<7} | {row['classification']:<16} | {row['url']}"
            f"{' | ' + row['title'] if row['title'] else ''}"
        )
        if row["class_reason"]:
            print(f"      reason: {row['class_reason']}")
    return 0


def cmd_open_next(args: argparse.Namespace) -> int:
    conn = get_conn(args.db)
    query = "SELECT * FROM courses WHERE status = ?"
    params: list[str] = [STATUS_PENDING]
    if args.only_free:
        query += " AND classification = ?"
        params.append(CLASS_TRULY_FREE)
    query += " ORDER BY id ASC LIMIT 1"

    row = conn.execute(query, params).fetchone()
    if not row:
        print("No matching pending course to open.")
        conn.close()
        return 0

    try:
        opened = webbrowser.open(row["url"])
    except Exception as exc:
        print(f"Error opening browser: {exc}")
        conn.close()
        return 2
    if not opened:
        print("Warning: webbrowser could not confirm opening, but command was issued.")

    now = utc_now()
    conn.execute(
        "UPDATE courses SET status = ?, updated_at = ?, last_opened_at = ? WHERE id = ?",
        (STATUS_OPENED, now, now, row["id"]),
    )
    conn.commit()
    conn.close()
    print(f"Opened id={row['id']} url={row['url']}")
    return 0


def cmd_mark_done(args: argparse.Namespace) -> int:
    conn = get_conn(args.db)
    row = conn.execute("SELECT id FROM courses WHERE id = ?", (args.id,)).fetchone()
    if not row:
        print(f"Error: course id {args.id} not found.")
        conn.close()
        return 2
    now = utc_now()
    conn.execute(
        "UPDATE courses SET status = ?, updated_at = ? WHERE id = ?",
        (STATUS_DONE, now, args.id),
    )
    conn.commit()
    conn.close()
    print(f"Marked id={args.id} as done.")
    return 0


def cmd_export_csv(args: argparse.Namespace) -> int:
    conn = get_conn(args.db)
    rows = conn.execute("SELECT * FROM courses ORDER BY id ASC").fetchall()
    conn.close()
    output_path = Path(args.output)
    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "id",
                "url",
                "title",
                "tags",
                "status",
                "classification",
                "class_reason",
                "html_path",
                "created_at",
                "updated_at",
                "last_opened_at",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    row["id"],
                    row["url"],
                    row["title"],
                    row["tags"],
                    row["status"],
                    row["classification"],
                    row["class_reason"],
                    row["html_path"],
                    row["created_at"],
                    row["updated_at"],
                    row["last_opened_at"],
                ]
            )
    print(f"Exported {len(rows)} rows to {output_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="coursera_free_filter.py",
        description="Coursera Truly-Free Course Filter + Opener (local HTML only, compliant workflow).",
    )
    parser.add_argument("--db", default=DB_FILE, help=f"SQLite database path (default: {DB_FILE})")
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add-url", help="Add a course URL to shortlist.")
    p_add.add_argument("url")
    p_add.add_argument("--tag", action="append", default=[], help="Tag (repeatable).")
    p_add.set_defaults(func=cmd_add_url)

    p_import_urls = sub.add_parser("import-urls", help="Import URLs from txt/csv.")
    p_import_urls.add_argument("path")
    p_import_urls.set_defaults(func=cmd_import_urls)

    p_import_html = sub.add_parser("import-html", help="Import listing/search HTML and extract Coursera course links.")
    p_import_html.add_argument("path")
    p_import_html.set_defaults(func=cmd_import_html)

    p_import_course_html = sub.add_parser(
        "import-course-html",
        help="Import a locally saved course page HTML for accurate classification.",
    )
    p_import_course_html.add_argument("path")
    p_import_course_html.set_defaults(func=cmd_import_course_html)

    p_quick = sub.add_parser(
        "quick-free-list",
        help="One-command flow: scan local HTML files, classify, and print TRULY_FREE courses.",
    )
    p_quick.add_argument("path", help="HTML file or directory containing saved Coursera HTML pages.")
    p_quick.add_argument("--fresh", action="store_true", help="Clear existing DB entries before import.")
    p_quick.add_argument(
        "--output",
        default="truly_free_courses.csv",
        help="Output CSV path for TRULY_FREE list (default: truly_free_courses.csv).",
    )
    p_quick.set_defaults(func=cmd_quick_free_list)

    p_classify = sub.add_parser("classify", help="Classify one id or all.")
    p_classify.add_argument("target", help="Course id or 'all'.")
    p_classify.set_defaults(func=cmd_classify)

    p_list = sub.add_parser("list", help="List shortlist entries.")
    p_list.add_argument("--status", choices=[STATUS_PENDING, STATUS_OPENED, STATUS_DONE])
    p_list.add_argument("--class", dest="classification", choices=[CLASS_TRULY_FREE, CLASS_PAID_OR_PREVIEW, CLASS_UNKNOWN])
    p_list.set_defaults(func=cmd_list)

    p_open = sub.add_parser("open-next", help="Open next pending URL in default browser.")
    p_open.add_argument("--only-free", action="store_true", help="Only open TRULY_FREE entries.")
    p_open.set_defaults(func=cmd_open_next)

    p_done = sub.add_parser("mark-done", help="Mark a course as done.")
    p_done.add_argument("id", type=int)
    p_done.set_defaults(func=cmd_mark_done)

    p_export = sub.add_parser("export", help="Export data.")
    p_export.add_argument("format", choices=["csv"], help="Export format.")
    p_export.add_argument("--output", default="courses_export.csv", help="Output CSV path.")
    p_export.set_defaults(func=cmd_export_csv)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "classify" and args.target != "all":
        try:
            args.target = int(args.target)
        except ValueError:
            print("Error: classify target must be an integer id or 'all'.")
            return 2
    if args.command == "export" and args.format != "csv":
        print("Error: only CSV export is supported.")
        return 2

    try:
        return int(args.func(args))
    except sqlite3.Error as exc:
        print(f"Database error: {exc}")
        return 2
    except OSError as exc:
        print(f"I/O error: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
