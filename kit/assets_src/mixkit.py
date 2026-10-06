"""List Mixkit sound effects / music on a tag page: id, title, duration, preview + full-quality URLs."""
import html, json, re, subprocess, sys

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 Chrome/128 Safari/537.36"


def get(url):
    return subprocess.run(["curl", "-s", "-m", "30", "-L", "-A", UA, url], capture_output=True, text=True).stdout


def items(url, pages=1):
    out = []
    for p in range(1, pages + 1):
        h = get(url + (f"?page={p}" if p > 1 else ""))
        for card in h.split('class="item-grid-card ')[1:]:
            m = re.search(r'data-audio-player-item-id-value="(\d+)"', card)
            kind = re.search(r'data-audio-player-item-type-value="(\w+)"', card)
            prev = re.search(r'data-audio-player-preview-url-value="([^"]+)"', card)
            t = re.search(r'item-grid-card__title">\s*(.*?)\s*</h2>', card, re.S)
            dur = re.search(r'(\d+:\d\d)', card)
            by = re.search(r'item-grid-card__artist[^>]*>\s*(?:by\s*)?([^<]+)', card)
            if m and prev:
                out.append({"id": m.group(1), "kind": kind.group(1) if kind else "", "title": html.unescape(re.sub("<[^>]+>", "", t.group(1)).strip()) if t else "",
                            "dur": dur.group(1) if dur else "", "artist": by.group(1).strip() if by else "", "preview": prev.group(1)})
    return out


if __name__ == "__main__":
    print(json.dumps(items(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 1), indent=0))
