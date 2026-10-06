"""List NCS releases from ncs.io search (optionally instrumental-only) with slug, genre, moods, versions."""
import html, json, re, subprocess, sys
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 Chrome/128 Safari/537.36"


def get(url):
    return subprocess.run(["curl", "-s", "-m", "30", "-L", "-A", UA, url], capture_output=True, text=True).stdout


def search(query="", pages=2):
    out = []
    for p in range(1, pages + 1):
        h = get(f"https://ncs.io/music-search?{query}&page={p}")
        for row in h.split("<tr>")[1:]:
            a = re.search(r'data-artistraw="([^"]*)"\s+data-track="([^"]*)"', row)
            slug = re.search(r'<a href="/([^"/?]+)">\s*<p>', row)
            ver = re.search(r'data-versions="([^"]*)"', row)
            gen = re.search(r'data-genre="([^"]*)"', row)
            tags = re.findall(r'mood=\d+">([^<]+)</a>', row)
            date = re.search(r'<td style="width:15%;">(\d\d? \w{3} \d{4})</td>', row)
            if a and slug:
                out.append({"artist": html.unescape(a.group(1)), "title": html.unescape(a.group(2)), "slug": slug.group(1),
                            "versions": ver.group(1) if ver else "", "genre": gen.group(1) if gen else "", "moods": tags,
                            "date": date.group(1) if date else ""})
    return out


def track(slug):
    """Download links (regular / instrumental) and the credit text from a release page."""
    h = get(f"https://ncs.io/{slug}")
    links = re.findall(r'href="(/track/download/(i_)?[0-9a-f-]+)"', h)
    credit = re.search(r'please add the following to your description:\s*</p>\s*<p[^>]*>(.*?)</p>', h, re.S)
    txt = html.unescape(re.sub(r"<br\s*/?>", "\n", credit.group(1))) if credit else ""
    return {"regular": next((l for l, i in links if not i), None), "instrumental": next((l for l, i in links if i), None),
            "credit": re.sub(r"<[^>]+>", "", txt).strip()}


if __name__ == "__main__":
    print(json.dumps(search(sys.argv[1] if len(sys.argv) > 1 else ""), indent=0))
