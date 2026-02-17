# Coursera Truly-Free Course Filter + Opener

This repo includes:

- A Chrome extension (`chrome_extension/`) for quick in-browser detection and opening of free-course candidates.
- A Python CLI (`coursera_free_filter.py`) for local HTML import/classification workflows.

## Compliance boundaries

This project does **not**:

- automate login
- auto-click enroll/continue
- crawl `coursera.org` with automated HTTP/headless scraping

This project does:

- open URLs in your browser
- classify from visible page content (extension) or local HTML files (CLI)

## Quick start (from scratch)

### 1. Get the code

Option A (Git):

```bash
git clone <your-repo-url>
cd coursera
```

Option B (ZIP):

1. Download ZIP from GitHub.
2. Extract it.
3. Open the extracted `coursera` folder.

### 2. Install the Chrome extension (no Web Store required)

1. Open `chrome://extensions`
2. Turn on **Developer mode**
3. Click **Load unpacked**
4. Select the repo folder `chrome_extension` (example: `...\coursera\chrome_extension`)

You should see: `Coursera Truly-Free Scanner`.

### 3. Use the extension

1. Open a Coursera search page.
2. Apply Coursera filters (for example, Free) if desired.
3. Open the extension popup.
4. Click `Scan Current Page`.
5. If free results are detected, click `Direct Me To Free Courses`.

Important:

- Detection on listing pages uses card-level `Free` badge signals and reject phrases.
- Final confirmation is still manual on course page: click `Enroll for free` and verify `Full Course, No Certificate`.

## Update after pulling changes

If you pull new commits, go to `chrome://extensions` and click **Reload** on `Coursera Truly-Free Scanner`.

## Troubleshooting extension

- If popup shows connection errors, ensure the active tab is a Coursera URL (`https://www.coursera.org/...`).
- If extension does not appear, re-run **Load unpacked** and select `chrome_extension`.
- Extensions are profile-specific. Use the same Chrome profile where you installed it.

## Python CLI (optional, local HTML workflow)

Python 3.11+ required.

```bash
python coursera_free_filter.py --help
```

Common flow:

```bash
python coursera_free_filter.py import-course-html .\saved_course_page.html
python coursera_free_filter.py classify all
python coursera_free_filter.py list --class TRULY_FREE
python coursera_free_filter.py open-next --only-free
```

One-command local HTML scan:

```bash
python coursera_free_filter.py quick-free-list .\saved_html_folder --fresh
```

## CLI commands

- `add-url <url> [--tag <tag>]`
- `import-urls <txt_or_csv_path>`
- `import-html <local_file.html>`
- `import-course-html <local_course_page.html>`
- `quick-free-list <file_or_folder> [--fresh] [--output truly_free_courses.csv]`
- `classify <id|all>`
- `list [--status pending|opened|done] [--class TRULY_FREE|PAID_OR_PREVIEW|UNKNOWN]`
- `open-next [--only-free]`
- `mark-done <id>`
- `export csv [--output courses_export.csv]`

## Classification logic (CLI)

`TRULY_FREE` if:

- contains `Full Course, No Certificate`
- OR contains `Enroll for free` and `No Certificate`
- and does not contain reject/payment signals

`PAID_OR_PREVIEW` if reject/payment signals found, including:

- `This course costs`
- `Preview this course`
- `Start free trial`
- `Coursera Plus`
- `Subscribe`
- contextual `$` pricing near terms like `cost`, `per month`, `subscribe`, `free trial`

Otherwise: `UNKNOWN`.

## Tests

```bash
python -m unittest discover -s tests -v
```
