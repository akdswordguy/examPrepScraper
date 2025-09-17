"""
Universal Exam Info Fetcher
 - Query any exam name (e.g., "NEET", "JEE", "CLAT", "CUET", "NTSE", "SSC CGL", "UPSC")
 - Fetches Wikipedia overview, syllabus, exam pattern sections
 - Uses YouTube Data API to fetch video lectures (optional; set YOUTUBE_API_KEY)
 - Uses Google Books API to fetch suggested books
 - Scrapes Examsnet and Selfstudys for free solved PYQs
"""

import re
import requests
from bs4 import BeautifulSoup
from typing import Dict, List, Optional
from dotenv import dotenv_values


config = dotenv_values(".env")
try:
    import googleapiclient.discovery
    HAVE_YT = True
except Exception:
    HAVE_YT = False


YOUTUBE_API_KEY = config.get("YOUTUBE_API_KEY", "")
GOOGLE_BOOKS_BASE = "https://www.googleapis.com/books/v1/volumes"
WIKIPEDIA_SEARCH_API = "https://en.wikipedia.org/w/api.php"
WIKIPEDIA_REST_PAGE = "https://en.wikipedia.org/api/rest_v1/page/html/{}"  # slug


# ---------------------------
# Helper: Wikipedia search & fetch
# ---------------------------
def wiki_search_title(query: str) -> Optional[str]:
    """Search Wikipedia and return the best-matching page title."""
    params = {"action": "query", "list": "search", "srsearch": query, "format": "json", "srlimit": 5}
    try:
        r = requests.get(WIKIPEDIA_SEARCH_API, params=params, timeout=12)
        r.raise_for_status()
        results = r.json().get("query", {}).get("search", [])
        if not results:
            return None
        return results[0]["title"]
    except Exception:
        return None


def wiki_get_html(title: str) -> Optional[str]:
    """Fetch HTML content of a Wikipedia page by title."""
    slug = title.replace(" ", "_")
    url = WIKIPEDIA_REST_PAGE.format(slug)
    try:
        r = requests.get(url, timeout=12)
        return r.text if r.status_code == 200 else None
    except Exception:
        return None


def extract_sections_from_wiki_html(html: str) -> Dict[str, str]:
    """Parse Wikipedia HTML and extract headings & text."""
    soup = BeautifulSoup(html, "html.parser")
    for tb in soup.select("table"):
        tb.decompose()  
    sections = {}
    for header in soup.find_all(re.compile("^h[1-6]$")):
        head_text = header.get_text(separator=" ").strip()
        content_parts = []
        for sib in header.next_siblings:
            if getattr(sib, "name", None) and re.match("^h[1-6]$", sib.name):
                break
            if getattr(sib, "name", None) in ("p", "ul", "ol", "div"):
                txt = sib.get_text(separator=" ").strip()
                if txt:
                    content_parts.append(txt)
        if content_parts:
            sections[head_text.lower()] = "\n\n".join(content_parts)
  
    first_p = soup.find("p")
    lead_para = first_p.get_text(strip=True) if first_p else ""
    sections.setdefault("summary", lead_para)
    return sections


def find_relevant_wiki_info(query: str) -> Dict[str, Optional[str]]:
    """Fetch Wikipedia info: summary, syllabus, pattern, other sections."""
    out = {"title": None, "summary": None, "syllabus": None, "pattern": None, "other_sections": {}}
    title = wiki_search_title(query + " exam") or wiki_search_title(query)
    if title is None:
        return out
    out["title"] = title
    html = wiki_get_html(title)
    if html is None:
        return out
    sections = extract_sections_from_wiki_html(html)
    out["summary"] = sections.get("summary") or sections.get("introduction") or None


    syllabus_keys = ["syllabus", "curriculum", "exam syllabus", "syllabus and exam pattern", "syllabus and structure"]
    pattern_keys = ["exam pattern", "pattern", "format", "structure", "scheme"]
    for k in syllabus_keys:
        if k in sections:
            out["syllabus"] = sections[k]
            break
    for k in pattern_keys:
        if k in sections:
            out["pattern"] = sections[k]
            break
    if not out["syllabus"]:
        for secname, content in sections.items():
            if any(word in secname for word in ("syllabus", "curriculum", "subjects", "paper", "exam")):
                out["syllabus"] = content
                break
    if not out["pattern"]:
        for secname, content in sections.items():
            if any(word in secname for word in ("pattern", "structure", "format", "scheme", "paper")):
                out["pattern"] = content
                break
    out["other_sections"] = sections
    return out


# ---------------------------
# YouTube search
# ---------------------------
def search_youtube_videos(query: str, max_results: int = 5) -> List[Dict]:
    """Search YouTube videos for exam preparation."""
    if not HAVE_YT or not YOUTUBE_API_KEY:
        return []
    try:
        youtube = googleapiclient.discovery.build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
        request = youtube.search().list(
            q=f"{query} preparation",
            part="snippet",
            maxResults=max_results,
            type="video",
            relevanceLanguage="en"
        )
        resp = request.execute()
        videos = []
        for item in resp.get("items", []):
            videos.append({
                "title": item["snippet"]["title"],
                "videoId": item["id"]["videoId"],
                "url": f"https://www.youtube.com/watch?v={item['id']['videoId']}"
            })
        return videos
    except Exception:
        return []

# ---------------------------
# YouTube search - Modified to fetch one playlist
# ---------------------------
def search_youtube_playlist(query: str) -> Optional[Dict]:
    """
    Requires google-api-python-client and a valid YOUTUBE_API_KEY set in env var or variable above.
    Searches for one relevant playlist (e.g., "NEET preparation playlist").
    Returns a dict: {title, playlistId, url} or None.
    """
    if not HAVE_YT or not YOUTUBE_API_KEY:
        return None
    try:
        youtube = googleapiclient.discovery.build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
        request = youtube.search().list(
            q=f"{query} preparation playlist",
            part="snippet",
            maxResults=1,
            type="playlist",
            relevanceLanguage="en"
        )
        resp = request.execute()
        items = resp.get("items", [])
        if not items:
            return None
        item = items[0]
        playlist_id = item["id"]["playlistId"]
        return {
            "title": item["snippet"]["title"],
            "playlistId": playlist_id,
            "url": f"https://www.youtube.com/playlist?list={playlist_id}"
        }
    except Exception:
        return None
    
# ---------------------------
# Google Books suggestions
# ---------------------------
def search_google_books(query: str, max_results: int = 6) -> List[Dict]:
    """Search Google Books API for exam prep books."""
    try:
        params = {"q": f"{query} preparation OR {query} syllabus OR {query} guide", "maxResults": max_results}
        r = requests.get(GOOGLE_BOOKS_BASE, params=params, timeout=12)
        r.raise_for_status()
        items = r.json().get("items", [])[:max_results]
        out = []
        for it in items:
            info = it.get("volumeInfo", {})
            out.append({
                "title": info.get("title"),
                "authors": info.get("authors"),
                "publisher": info.get("publisher"),
                "infoLink": info.get("infoLink")
            })
        return out
    except Exception:
        return []


# ---------------------------
# Free PYQs from Examsnet & Selfstudys
# ---------------------------
def fetch_free_pyqs_links(exam_query: str) -> List[Dict]:
    """
    Web-scrape solved PYQs from Examsnet and Selfstudys.
    """
    exam_query_lower = exam_query.lower()
    links = []


    examsnet_base = "https://www.examsnet.com"
    if "neet" in exam_query_lower:
        neet_url = f"{examsnet_base}/exams/neet-chapterwise-previous-question-papers-online"
        links.append({"site": "Examsnet", "exam": "NEET", "link": neet_url})
    elif "jee" in exam_query_lower:
        jee_url = f"{examsnet_base}/exams/jee-mains-chapterwise-previous-year-questions-online"
        links.append({"site": "Examsnet", "exam": "JEE Mains", "link": jee_url})


    selfstudys_base = "https://www.selfstudys.com"
    if "neet" in exam_query_lower:
        neet_self = f"{selfstudys_base}/books/neet-previous-year-paper/page/year-wise"
        links.append({"site": "Selfstudys", "exam": "NEET", "link": neet_self})
    elif "jee" in exam_query_lower:
        jee_self = f"{selfstudys_base}/books/jee-main-previous-year-paper/page/year-wise"
        links.append({"site": "Selfstudys", "exam": "JEE Mains", "link": jee_self})


    scraped_links = []
    for item in links:
        try:
            r = requests.get(item["link"], timeout=12)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
        
            for a in soup.find_all("a", href=True):
                href = a['href']
                text = a.get_text(strip=True)
                if "pdf" in href.lower() or "previous" in text.lower() or "paper" in text.lower():
                 
                    if not href.startswith("http"):
                        href = item["link"].rstrip("/") + "/" + href.lstrip("/")
                    scraped_links.append({"site": item["site"], "exam": item["exam"], "title": text, "link": href})
        except Exception:
            continue

    return scraped_links[:5]


# ---------------------------
# Main fetch function
# ---------------------------
def fetch_exam_info_universal(exam_query: str, include_videos: bool = True, include_books: bool = True) -> Dict:
    """Fetch Wikipedia info, YouTube videos, YouTube playlist, Google Books, and free PYQs."""
    result = {
        "query": exam_query,
        "wikipedia": find_relevant_wiki_info(exam_query),
        "videos": search_youtube_videos(exam_query, max_results=6) if include_videos else [],
        "playlist": search_youtube_playlist(exam_query) if include_videos else None,
        "books": search_google_books(exam_query, max_results=6) if include_books else [],
        "free_pyqs": fetch_free_pyqs_links(exam_query) if include_books else []
    }
    return result

# ---------------------------
# CLI demonstration
# ---------------------------
if __name__ == "__main__":
    print("Universal Exam Info Fetcher (Wikipedia + YouTube + Google Books + Solved PYQs)")
    q = input("Enter exam name (e.g., NEET, JEE Main, CLAT, UPSC, CUET, SSC CGL): ").strip()
    if not q:
        print("No query entered. Exiting.")
        exit(0)

    info = fetch_exam_info_universal(q)
    
    print("\n=== Result Summary ===\n")
    print("Query:", info["query"])
    
    w = info["wikipedia"]
    if w.get("title"):
        print("Wikipedia Page Title:", w["title"])
    if w.get("summary"):
        print("\nSummary (lead):\n", w["summary"][:1000], "..." if len(w["summary"]) > 1000 else "")
    if w.get("pattern"):
        print("\nExam Pattern / Format:\n", w["pattern"][:1500])
    if w.get("syllabus"):
        print("\nSyllabus / Curriculum (excerpt):\n", w["syllabus"][:1500])
    
    if w.get("other_sections"):
        print("\nOther sections found on Wikipedia (headings):")
        for k in list(w["other_sections"].keys())[:15]:
            print(" -", k)
    
    if info["videos"]:
        print("\nSuggested Videos:")
        for v in info["videos"]:
            print(f" - {v['title']}  ({v['url']})")
    else:
        print("\nYouTube results not available (no API key or google client).")
    if info["playlist"]:
        p = info["playlist"]
        print(f"\nSuggested YouTube Playlist:\n - {p['title']} ({p['url']})")
    else:
        print("\nYouTube playlist not available (no API key, google client, or no results).")

    if info["books"]:
        print("\nSuggested Books:")
        for b in info["books"]:
            print(f" - {b.get('title')} | {', '.join(b.get('authors') or [])} - {b.get('infoLink')}")
    else:
        print("\nNo book suggestions found.")
    
    if info["free_pyqs"]:
        print("\nFree Solved PYQs Links (Examsnet / Selfstudys):")
        for pyq in info["free_pyqs"]:
            title = pyq.get("title") or pyq["exam"]
            print(f" - {title} | {pyq['site']}: {pyq['link']}")
    else:
        print("\nNo free PYQs links found.")
    
    print("\n--- End ---\n")
