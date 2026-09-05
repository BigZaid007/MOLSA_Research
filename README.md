# Research Data Fetcher

A local research assistant that collects publicly accessible information about topics (focused on Iraq’s Ministry of Labour) from web, news, and social sources.

## Quick Start

```bash
cd research-fetcher
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cd app
python main.py
```

Open http://127.0.0.1:8000 and use **Sign up** in the navbar to create your first Clerk account. After you are signed in, a profile button appears in the header.

Switch the interface to Arabic with **ع** in the header.

## What it searches

| Group | Sources |
|-------|---------|
| Social | Facebook, Instagram, LinkedIn, X (Twitter), TikTok, Reddit |
| Web / News | Google/web (`ddgs`), Bing (`ddgs`), News, RSS |

Social connectors look for **posts, hashtags, mentions, and threads** via the open-source [`ddgs`](https://github.com/deedy5/ddgs) metasearch library (`site:facebook.com …`, `inurl:status`, etc.), not only news articles.

## Honest limits (keyless)

Public tools can find **indexed** social content. They cannot guarantee full private Facebook/LinkedIn feeds without login or official APIs.

- If a platform blocks anonymous access, that connector returns empty/partial results instead of crashing.
- Prefer **Social only** in the UI when you want posts/tags/threads.
- Short date ranges (e.g. 5 days) may return few social hits; use **Any time** or **Last 30 days** if needed.

## Optional Reddit credentials

Anonymous Reddit JSON is often rate-limited. For better thread search, create a free Reddit app at https://www.reddit.com/prefs/apps and add to `.env`:

```env
REDDIT_CLIENT_ID=your_client_id
REDDIT_CLIENT_SECRET=your_client_secret
REDDIT_USER_AGENT=ResearchDataFetcher/1.0
```

Then install PRAW (optional):

```bash
pip install praw
```

## Technology Stack

**Backend:** Python 3.13+, FastAPI, Uvicorn, `ddgs`, httpx, BeautifulSoup4, feedparser, Playwright  
**Frontend:** HTML5, TailwindCSS, Alpine.js  
**Auth:** Clerk (sign-in / sign-up in the navbar)  
**i18n:** English and Arabic (RTL)  
**Architecture:** Connector-based (`search` / `fetch` / `is_available`)

## Project structure

```
research-fetcher/
├── app/
│   ├── connectors/     # google, news, facebook, x, reddit, …
│   ├── services/       # processor, ministry focus helpers
│   ├── templates/      # Jinja2 UI
│   └── main.py
├── requirements.txt
└── .env
```

## License

MIT
# MOLSA_Research
