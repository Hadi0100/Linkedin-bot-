import asyncio
import sqlite3
import re
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright
from win10toast import ToastNotifier


# ============================================================
# CONFIGURATION
# ============================================================

SEARCH_LOCATION = "New York City Metropolitan Area"

# How many results to inspect per search
MAX_RESULTS_PER_SEARCH = 25

# Your job searches
SEARCHES = [
    "IT Support",
    "IT Technician",
    "Help Desk",
    "Desktop Support",
    "Technical Support",
    "IT Support Specialist",
    "Network Support",
    "Network Technician",
    "Junior Network Engineer",
    "Network Administrator",
    "System Administrator",
    "Systems Administrator",
    "Junior System Administrator",
    "NOC Technician",
    "NOC Analyst",
    "Data Center Technician",
    "IT Operations",
    "IT Operations Technician",
    "Infrastructure Technician",
    "Service Desk",
    "Application Support",
    "Production Support",
    "Technical Operations",
]

# Keywords that increase relevance
HIGH_VALUE_KEYWORDS = [
    "network",
    "cisco",
    "tcp/ip",
    "dns",
    "dhcp",
    "active directory",
    "windows server",
    "linux",
    "azure",
    "powershell",
    "python",
    "sql",
    "help desk",
    "service desk",
    "desktop support",
    "technical support",
    "it support",
    "system administrator",
    "systems administrator",
    "network administrator",
    "network technician",
    "noc",
    "data center",
    "infrastructure",
]

# Keywords that can indicate a job isn't a good fit
EXCLUDE_KEYWORDS = [
    "senior director",
    "director of",
    "vice president",
    "vp of",
    "chief",
    "principal architect",
    "staff engineer",
    "10+ years",
    "15+ years",
    "6+ years",
]

# Portfolio/resume-related terms
PORTFOLIO_KEYWORDS = [
    "cisco",
    "networking",
    "security+",
    "network+",
    "jncia",
    "linux",
    "windows",
    "active directory",
    "powershell",
    "python",
    "sql",
    "azure",
    "technical support",
    "data center",
    "noc",
]

DATABASE = "job_alerts.db"

# Persistent browser profile.
# This lets you log into LinkedIn manually once.
BROWSER_PROFILE = Path("linkedin_browser_profile").absolute()


# ============================================================
# DATABASE
# ============================================================

def initialize_database():
    conn = sqlite3.connect(DATABASE)

    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT UNIQUE,
            title TEXT,
            company TEXT,
            location TEXT,
            url TEXT,
            score INTEGER,
            matched_keywords TEXT,
            discovered_at TEXT
        )
    """)

    conn.commit()

    return conn


def job_already_seen(conn, job_id):
    cursor = conn.cursor()

    cursor.execute(
        "SELECT 1 FROM jobs WHERE job_id = ?",
        (job_id,)
    )

    return cursor.fetchone() is not None


def save_job(conn, job):
    cursor = conn.cursor()

    cursor.execute("""
        INSERT OR IGNORE INTO jobs
        (
            job_id,
            title,
            company,
            location,
            url,
            score,
            matched_keywords,
            discovered_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        job["job_id"],
        job["title"],
        job["company"],
        job["location"],
        job["url"],
        job["score"],
        ", ".join(job["matched_keywords"]),
        datetime.now().isoformat()
    ))

    conn.commit()


# ============================================================
# JOB SCORING
# ============================================================

def calculate_score(title, description):
    text = f"{title} {description}".lower()

    score = 0
    matches = []

    # Strong matches in title
    for keyword in HIGH_VALUE_KEYWORDS:
        if keyword.lower() in title.lower():
            score += 10
            matches.append(keyword)

    # Matches anywhere in job description
    for keyword in HIGH_VALUE_KEYWORDS:
        if keyword.lower() in text and keyword not in matches:
            score += 3
            matches.append(keyword)

    # Portfolio matches
    for keyword in PORTFOLIO_KEYWORDS:
        if keyword.lower() in text:
            score += 2
            if keyword not in matches:
                matches.append(keyword)

    # Penalize obviously senior roles
    for keyword in EXCLUDE_KEYWORDS:
        if keyword.lower() in text:
            score -= 20

    # Entry/junior language
    entry_terms = [
        "entry level",
        "entry-level",
        "junior",
        "associate",
        "level 1",
        "level i",
        "technician",
        "trainee",
        "0-2 years",
        "1-2 years",
        "2 years",
    ]

    for keyword in entry_terms:
        if keyword in text:
            score += 5

    return max(score, 0), matches


# ============================================================
# NOTIFICATION
# ============================================================

def notify(job):
    toaster = ToastNotifier()

    message = (
        f'{job["title"]}\n'
        f'{job["company"]} — {job["location"]}\n'
        f'Match Score: {job["score"]}'
    )

    toaster.show_toast(
        "🚨 New LinkedIn Job Match",
        message,
        duration=10,
        threaded=True
    )


# ============================================================
# LINKEDIN SEARCH
# ============================================================

async def search_linkedin(page, search_term):

    encoded_keyword = search_term.replace(" ", "%20")
    encoded_location = SEARCH_LOCATION.replace(" ", "%20")

    url = (
        "https://www.linkedin.com/jobs/search/"
        f"?keywords={encoded_keyword}"
        f"&location={encoded_location}"
        "&f_TPR=r3600"
        "&sortBy=DD"
    )

    print(f"\nSearching: {search_term}")

    try:
        await page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=60000
        )

        await page.wait_for_timeout(3000)

    except Exception as e:
        print(f"Could not load LinkedIn search: {e}")
        return []

    # Check whether LinkedIn requires login
    current_url = page.url.lower()

    if "login" in current_url or "authwall" in current_url:
        print("\nLinkedIn requires login.")
        print("Log into LinkedIn in the browser window.")
        print("Then run the bot again.")
        return []

    jobs = []

    # LinkedIn job cards
    cards = await page.locator(
        "li.jobs-search-results__list-item"
    ).all()

    if not cards:
        cards = await page.locator(
            "div.job-card-container"
        ).all()

    print(f"Found approximately {len(cards)} job cards.")

    for card in cards[:MAX_RESULTS_PER_SEARCH]:

        try:

            # Job title
            title_locator = card.locator(
                ".base-search-card__title, "
                ".job-card-list__title, "
                "a.job-card-list__title"
            )

            title = ""

            if await title_locator.count():
                title = (
                    await title_locator.first.inner_text()
                )

            # Company
            company_locator = card.locator(
                ".base-search-card__subtitle, "
                ".job-card-container__company-name"
            )

            company = ""

            if await company_locator.count():
                company = (
                    await company_locator.first.inner_text()
                )

            # Location
            location_locator = card.locator(
                ".job-search-card__location, "
                ".job-card-container__metadata-item"
            )

            location = ""

            if await location_locator.count():
                location = (
                    await location_locator.first.inner_text()
                )

            # URL
            link_locator = card.locator("a")

            job_url = ""

            if await link_locator.count():
                job_url = await link_locator.first.get_attribute("href")

            if not title or not job_url:
                continue

            if job_url.startswith("/"):
                job_url = "https://www.linkedin.com" + job_url

            # Extract LinkedIn job ID
            match = re.search(
                r"/jobs/view/(\d+)",
                job_url
            )

            if match:
                job_id = match.group(1)
            else:
                job_id = job_url

            # Score using title/company/location
            description = (
                f"{title} {company} {location}"
            )

            score, matched = calculate_score(
                title,
                description
            )

            jobs.append({
                "job_id": job_id,
                "title": title.strip(),
                "company": company.strip(),
                "location": location.strip(),
                "url": job_url.split("?")[0],
                "score": score,
                "matched_keywords": matched
            })

        except Exception as e:
            print(f"Error reading job card: {e}")

    return jobs


# ============================================================
# MAIN BOT
# ============================================================

async def main():

    print("=" * 60)
    print("LINKEDIN JOB MONITOR")
    print("=" * 60)

    print(
        f"\nLocation: {SEARCH_LOCATION}"
    )

    print(
        f"Searches: {len(SEARCHES)}"
    )

    conn = initialize_database()

    async with async_playwright() as p:

        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(BROWSER_PROFILE),
            headless=False,
            viewport={
                "width": 1400,
                "height": 900
            }
        )

        page = await context.new_page()

        all_new_jobs = []

        for search_term in SEARCHES:

            jobs = await search_linkedin(
                page,
                search_term
            )

            for job in jobs:

                if job_already_seen(
                    conn,
                    job["job_id"]
                ):
                    continue

                save_job(conn, job)

                # Only alert for meaningful matches
                if job["score"] >= 15:

                    all_new_jobs.append(job)

                    notify(job)

                    print("\n🔥 NEW MATCH")
                    print("-----------------------------")
                    print(
                        f'Title: {job["title"]}'
                    )
                    print(
                        f'Company: {job["company"]}'
                    )
                    print(
                        f'Location: {job["location"]}'
                    )
                    print(
                        f'Score: {job["score"]}'
                    )
                    print(
                        f'Matches: {", ".join(job["matched_keywords"])}'
                    )
                    print(
                        f'URL: {job["url"]}'
                    )

            # Small delay between searches
            await asyncio.sleep(3)

        await context.close()

    conn.close()

    print("\n" + "=" * 60)
    print(
        f"NEW MATCHES THIS RUN: {len(all_new_jobs)}"
    )
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
