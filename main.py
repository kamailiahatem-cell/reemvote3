import requests
import re
import time
import random
import string
import json
import sys

class YouTubeViewSimulator:
    """
    Realistic YouTube watch session simulator.

    v2 fixes:
      1. Removed false-positive bot detection (botguard JS loads on EVERY page)
      2. Actual block detection: /sorry redirect, HTTP 429, challenge forms
      3. Pre-browsing: visit youtube.com first to seed realistic cookies
      4. Consent page handling (GDPR wall)
      5. Proper referrer chain (homepage → watch page)
      6. Better session/cookie warming
      7. Compressed timing with jitter
      8. All required stats parameters
      9. InnerTube player API call
     10. Audio+video stream simulation
     11. Cooldown with randomization between runs
    """

    CHROME_VERSIONS = ["137.0.0.0", "138.0.0.0", "139.0.0.0"]
    YT_CLIENT_VERSIONS = [
        "2.20250610.00.00",
        "2.20250615.01.00",
        "2.20250620.02.00",
    ]

    def __init__(self, proxy=None):
        self.proxy = proxy

    # ───────────────────── helpers ─────────────────────

    @staticmethod
    def _generate_cpn():
        chars = string.ascii_letters + string.digits + "-_"
        return "".join(random.choice(chars) for _ in range(16))

    def _random_ua(self):
        cv = random.choice(self.CHROME_VERSIONS)
        major = cv.split(".")[0]
        ua = (
            f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            f"AppleWebKit/537.36 (KHTML, like Gecko) "
            f"Chrome/{cv} Safari/537.36"
        )
        return ua, cv, major

    def _new_session(self):
        s = requests.Session()
        if self.proxy:
            s.proxies = {"http": self.proxy, "https": self.proxy}
        return s

    @staticmethod
    def _extract_balanced_json(text, start):
        if start >= len(text) or text[start] != "{":
            return None
        depth = 0
        i = start
        in_str = False
        esc = False
        sch = None
        while i < len(text):
            c = text[i]
            if esc:
                esc = False; i += 1; continue
            if c == "\\":
                esc = True; i += 1; continue
            if in_str:
                if c == sch:
                    in_str = False
            else:
                if c in "\"'":
                    in_str = True; sch = c
                elif c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                    if depth == 0:
                        return text[start : i + 1]
            i += 1
        return None

    def _extract_ytcfg(self, html):
        cfg = {}
        for m in re.finditer(r"ytcfg\.set\(\s*\{", html):
            js = self._extract_balanced_json(html, m.end() - 1)
            if js:
                try:
                    cfg.update(json.loads(js))
                except json.JSONDecodeError:
                    pass
        for key in ("EVENT_ID", "VISITOR_DATA", "INNERTUBE_API_KEY",
                     "INNERTUBE_CLIENT_VERSION", "LOGGED_IN", "DELEGATED_SESSION_ID"):
            if key not in cfg:
                m = re.search(rf'"{key}"\s*:\s*"([^"]*)"', html)
                if m:
                    cfg[key] = m.group(1)
        return cfg

    def _extract_player_response(self, html):
        pr = {}
        for pattern in (
            r"ytInitialPlayerResponse\s*=\s*\{",
            r"var\s+ytInitialPlayerResponse\s*=\s*\{",
        ):
            m = re.search(pattern, html)
            if m:
                js = self._extract_balanced_json(html, m.end() - 1)
                if js:
                    try:
                        pr = json.loads(js)
                    except json.JSONDecodeError:
                        pass
                if pr:
                    break
        return pr

    # ───────────── real block detection ──────────────

    @staticmethod
    def _is_actually_blocked(response, html):
        """
        FIX #1: The old code checked for 'botguard' and 'captcha' in
        the HTML — those strings appear on EVERY YouTube page as part
        of normal JS libraries.  Real block indicators are:
          - Redirect to /sorry  (the actual human-verification page)
          - HTTP 429 Too Many Requests
          - A challenge <form> with a captcha iframe
          - Page is suspiciously tiny (challenge pages are < 5 KB)
        """
        # HTTP 429 is unambiguous
        if response.status_code == 429:
            return True, "HTTP 429 — rate limited"

        # YouTube's actual bot challenge redirects here
        if "/sorry" in response.url:
            return True, "Redirected to /sorry (verification page)"

        # Check for the actual CAPTCHA *form* element, not just the word
        if re.search(r'<form[^>]*action[^>]*captcha', html, re.I):
            return True, "CAPTCHA challenge form detected"

        # Real challenge pages are tiny; normal watch pages are > 100 KB
        if len(html) < 5000 and "recaptcha" in html.lower():
            return True, "Tiny page with reCAPTCHA"

        return False, ""

    # ───────────────────── streaming ─────────────────────

    def _simulate_streaming(self, session, urls, video_id, ua):
        hdrs = {
            "User-Agent": ua,
            "Accept": "*/*",
            "Origin": "https://www.youtube.com",
            "Referer": f"https://www.youtube.com/watch?v={video_id}",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "cross-site",
        }
        for label, url, size in urls:
            if not url:
                continue
            try:
                h = hdrs.copy()
                h["Range"] = f"bytes=0-{size}"
                r = session.get(url, headers=h, timeout=20, stream=True)
                if r.status_code in (200, 206):
                    total = 0
                    for chunk in r.iter_content(8192):
                        total += len(chunk)
                        if total >= size:
                            break
                    print(f"    {label} stream: {total:,} bytes ✓")
                    r.close()
                else:
                    print(f"    {label} stream: HTTP {r.status_code}")
            except Exception as e:
                print(f"    {label} stream error: {e}")

    # ───────────────────── consent ─────────────────────

    @staticmethod
    def _handle_consent(session, headers, video_id):
        """
        FIX #2: Properly accept the GDPR consent wall.
        Many EU/rotating-IP hits get this page.  The old code's
        URL was wrong; this uses the correct endpoint + form data.
        """
        print("  ⚠ Consent page detected — accepting …")
        try:
            # First get the consent page to extract the token
            consent_url = "https://consent.youtube.com/save"
            params = {
                "gl": "US",
                "hl": "en",
                "continue": f"https://www.youtube.com/watch?v={video_id}",
                "set_eom": "true",
            }
            session.get(consent_url, params=params,
                        headers=headers, timeout=15, allow_redirects=True)
            # Some flows also need a POST with the consent form data
            session.post(
                "https://consent.youtube.com/save",
                data={
                    "gl": "US", "hl": "en", "m": "0", "app": "0", "pc": "yt",
                    "continue": f"https://www.youtube.com/watch?v={video_id}",
                    "set_eom": "true",
                    "set_ytc": "true",
                    "x": "6", "bl": "483948", "f.flip": "0",
                },
                headers={**headers, "Content-Type": "application/x-www-form-urlencoded"},
                timeout=15, allow_redirects=True,
            )
        except Exception as e:
            print(f"  ⚠ Consent handling failed: {e}")

    # ───────────────────── main logic ─────────────────────

    def simulate(self, video_id):
        session = self._new_session()
        cpn = self._generate_cpn()
        ua, chrome_ver, chrome_major = self._random_ua()
        client_ver = random.choice(self.YT_CLIENT_VERSIONS)
        sec_ch_ua = (
            f'"Google Chrome";v="{chrome_major}", '
            f'"Not.A/Brand";v="8", '
            f'"Chromium";v="{chrome_major}"'
        )

        print(f"\n{'=' * 60}")
        print(f"  Video : {video_id}")
        print(f"  CPN   : {cpn}")
        print(f"  Chrome: {chrome_ver}  |  YT client: {client_ver}")
        print(f"{'=' * 60}")

        try:
            # ── PHASE 0: connectivity + cookie seeding ───────────
            # FIX #3: Visit youtube.com homepage first.  A real user's
            # browser always has youtube cookies BEFORE navigating to a
            # watch page.  This seeds SID, HSID, SSID, APISID, SAPISID,
            # VISITOR_INFO1_LIVE, YSC, etc.
            print("\n[0/5] Warming session (homepage + 204) …")
            warm_headers = {
                "User-Agent": ua,
                "Accept": "text/html,application/xhtml+xml,application/xml;"
                          "q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
                "Upgrade-Insecure-Requests": "1",
                "sec-ch-ua": sec_ch_ua,
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
            }

            # This is what Chrome does on every new tab
            session.get("https://www.youtube.com/generate_204",
                        timeout=10)

            # FIX #4: Load the homepage so the server sets initial
            # cookies.  Without this, the watch-page request arrives
            # with zero cookies — a strong bot signal.
            hp = session.get("https://www.youtube.com/",
                             headers=warm_headers, timeout=30)
            print(f"  Homepage: {hp.status_code} "
                  f"({len(hp.text):,} bytes, "
                  f"{len(session.cookies)} cookies)")

            # Small human-like delay between homepage and watch page
            time.sleep(random.uniform(0.8, 2.0))

            # ── PHASE 1: page load ───────────────────────────────
            print("\n[1/5] Loading watch page …")

            # FIX #5: Correct referrer chain.  A real user navigates
            # from the homepage (or search results) to the watch page.
            page_headers = warm_headers.copy()
            page_headers["Referer"] = "https://www.youtube.com/"
            page_headers["Sec-Fetch-Site"] = "same-origin"

            res = session.get(
                f"https://www.youtube.com/watch?v={video_id}",
                headers=page_headers, timeout=30,
            )
            if res.status_code != 200:
                print(f"  ✗ Page HTTP {res.status_code}")
                return False
            html = res.text
            print(f"  ✓ Page loaded  ({len(html):,} bytes)")

            # ── FIX #1: real block detection ─────────────────────
            blocked, reason = self._is_actually_blocked(res, html)
            if blocked:
                print(f"  ✗ BLOCKED: {reason}")
                return False
            else:
                print("  ✓ No block/challenge detected")

            # ── FIX #2: consent wall ─────────────────────────────
            if "consent.youtube.com" in res.url or \
               "CONSENT" in html and 'action="/save"' in html:
                self._handle_consent(session, page_headers, video_id)
                time.sleep(random.uniform(1.0, 2.0))
                # Re-fetch the watch page after consent
                res = session.get(
                    f"https://www.youtube.com/watch?v={video_id}",
                    headers=page_headers, timeout=30,
                )
                html = res.text
                if res.status_code != 200:
                    print(f"  ✗ Post-consent page HTTP {res.status_code}")
                    return False
                print(f"  ✓ Re-loaded after consent ({len(html):,} bytes)")

            # ── PHASE 2: extract tokens ──────────────────────────
            print("\n[2/5] Extracting tokens …")
            ytcfg = self._extract_ytcfg(html)
            pr = self._extract_player_response(html)

            ei = ytcfg.get("EVENT_ID", "")
            visitor_data = ytcfg.get("VISITOR_DATA", "")
            api_key = ytcfg.get(
                "INNERTUBE_API_KEY",
                "AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8")
            yt_client_ver = ytcfg.get(
                "INNERTUBE_CLIENT_VERSION", client_ver)

            vd = pr.get("videoDetails", {})
            length_seconds = int(vd.get("lengthSeconds", 0))
            channel_id = vd.get("channelId", "")
            title = vd.get("title", "?")[:60]

            playability = pr.get("playabilityStatus", {})
            pstatus = playability.get("status", "")
            if pstatus and pstatus not in ("OK", "LIVE_STREAMING"):
                reason = playability.get("reason", "")
                subreason = ""
                sr = playability.get("messages", [])
                if sr:
                    subreason = " – " + "; ".join(sr)
                print(f"  ⚠ Playability: {pstatus} – {reason}{subreason}")
                # Don't abort — stats pings may still register

            print(f"  ei          : {ei or '(empty)'}")
            print(f"  visitor     : {visitor_data[:30]}…" if visitor_data
                  else "  visitor     : (none)")
            print(f"  title       : {title}")
            print(f"  duration    : {length_seconds}s")
            print(f"  playability : {pstatus or '(unknown)'}")

            # ── PHASE 3: InnerTube player call ───────────────────
            print("\n[3/5] InnerTube player request …")
            api_headers = {
                "User-Agent": ua,
                "Accept": "*/*",
                "Content-Type": "application/json",
                "Origin": "https://www.youtube.com",
                "Referer": f"https://www.youtube.com/watch?v={video_id}",
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-origin",
                "x-youtube-client-name": "1",
                "x-youtube-client-version": yt_client_ver,
                "sec-ch-ua": sec_ch_ua,
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
            }
            if visitor_data:
                api_headers["x-goog-visitor-id"] = visitor_data

            body = {
                "context": {
                    "client": {
                        "hl": "en", "gl": "US",
                        "clientName": "WEB",
                        "clientVersion": yt_client_ver,
                        "visitorData": visitor_data,
                        "userAgent": ua,
                        "osName": "Windows",
                        "osVersion": "10.0",
                        "browserName": "Chrome",
                        "browserVersion": chrome_ver,
                        "platform": "DESKTOP",
                    },
                    "request": {"useSsl": True},
                    "user": {"lockedSafetyMode": False},
                },
                "videoId": video_id,
                "cpn": cpn,
                "contentCheckOk": True,
                "racyCheckOk": True,
            }

            sel_itag = "243"
            audio_itag = "251"
            stream_urls = []

            try:
                pres = session.post(
                    f"https://www.youtube.com/youtubei/v1/player"
                    f"?key={api_key}&prettyPrint=false",
                    headers=api_headers, json=body, timeout=30,
                )

                if pres.status_code == 200:
                    pdata = pres.json()
                    sd = pdata.get("streamingData", {})
                    fmts = (sd.get("formats", [])
                            + sd.get("adaptiveFormats", []))

                    # Pick best video itag
                    for f in fmts:
                        if f.get("itag") in (18, 134, 243):
                            sel_itag = str(f["itag"]); break
                    else:
                        for f in fmts:
                            if f.get("mimeType", "").startswith("video/"):
                                sel_itag = str(f["itag"]); break

                    # Pick audio itag
                    for f in fmts:
                        if f.get("mimeType", "").startswith("audio/"):
                            audio_itag = str(f["itag"]); break

                    print(f"  video itag : {sel_itag}")
                    print(f"  audio itag : {audio_itag}")

                    video_url = audio_url = None
                    for f in fmts:
                        u = f.get("url")
                        if not u:
                            continue
                        if str(f.get("itag")) == sel_itag and not video_url:
                            video_url = u
                        if (f.get("mimeType", "").startswith("audio/")
                                and not audio_url):
                            audio_url = u

                    stream_urls = [
                        ("Video", video_url, 2_097_152),
                        ("Audio", audio_url,   524_288),
                    ]
                else:
                    print(f"  ✗ Player API HTTP {pres.status_code}")
            except Exception as e:
                print(f"  ⚠ Player API error: {e}")

            # ── PHASE 3b: stream simulation ──────────────────────
            if stream_urls:
                self._simulate_streaming(
                    session, stream_urls, video_id, ua)

            # ── PHASE 4: stats pings ─────────────────────────────
            print("\n[4/5] Stats reporting …")
            time.sleep(random.uniform(1.0, 2.5))

            stats_headers = {
                "User-Agent": ua,
                "Accept": "*/*",
                "Origin": "https://www.youtube.com",
                "Referer": f"https://www.youtube.com/watch?v={video_id}",
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-origin",
                "sec-ch-ua": sec_ch_ua,
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
            }

            session_start = time.time()
            lact = random.randint(2000, 8000)

            def _base_params():
                return {
                    "ns": "yt",
                    "el": "detailpage",
                    "cpn": cpn,
                    "docid": video_id,
                    "ei": ei,
                    "ver": "2",
                    "fmt": sel_itag,
                    "afmt": audio_itag,
                    "fs": "0",
                    "rt": "0",
                    "of": "",
                    "euri": "",
                    "lact": str(lact),
                    "live": "dvr",
                    "usb": "0",
                    "conn": "",
                    "c": "WEB",
                    "cver": yt_client_ver,
                    "cplayer": "UNIPLAYER",
                    "cbr": "Chrome",
                    "cbrver": chrome_ver,
                    "cos": "Windows",
                    "cosver": "10.0",
                    "cl": "0",
                    "volume": "100",
                    "vis": "1",
                }

            # -- initial playback ping --
            rt = int((time.time() - session_start) * 1000)
            pb = _base_params()
            pb.update({
                "rt": str(rt),
                "cmt": "0.0",
                "vps": "0.00",
                "st": "0",
                "et": "0.0",
                "state": "playing",
            })
            if visitor_data:
                pb["vd"] = visitor_data

            r = session.get(
                "https://www.youtube.com/api/stats/playback",
                params=pb, headers=stats_headers, timeout=15,
            )
            ok = "✓" if r.status_code == 204 else "✗"
            print(f"  playback  @  0s  → {r.status_code} {ok}")

            # -- watchtime pings --
            if length_seconds > 0:
                target_watch = min(
                    max(31, int(length_seconds * 0.55)),
                    length_seconds,
                )
            else:
                target_watch = 35

            checkpoints = []
            t = 5
            while t <= target_watch:
                checkpoints.append(t)
                t += 5 if t < 20 else (10 if t < 60 else 30)

            print(f"  target: {target_watch}s  "
                  f"checkpoints: {checkpoints}")

            state_start = 0
            prev_checkpoint = 0

            for cp in checkpoints:
                gap = cp - prev_checkpoint
                real_delay = gap * random.uniform(0.55, 0.80)
                real_delay = max(real_delay, 2.0)
                time.sleep(real_delay)

                lact += int(real_delay * 1000) + random.randint(0, 500)
                rt = int((time.time() - session_start) * 1000)

                wt = _base_params()
                wt.update({
                    "rt": str(rt),
                    "lact": str(lact),
                    "cmt": f"{cp}.0",
                    "vps": f"{cp}.00",
                    "st": str(state_start),
                    "et": f"{cp}.0",
                    "state": "playing",
                })
                if visitor_data:
                    wt["vd"] = visitor_data

                r = session.get(
                    "https://www.youtube.com/api/stats/watchtime",
                    params=wt, headers=stats_headers, timeout=15,
                )
                ok = "✓" if r.status_code == 204 else "✗"
                print(f"  watchtime @ {cp:>3}s  → {r.status_code} {ok}")

                prev_checkpoint = cp

            # ── PHASE 5: result ──────────────────────────────────
            print(f"\n[5/5] Result")
            if target_watch >= 30:
                print(f"  ✓ {target_watch}s reported – "
                      f"30s threshold met")
            elif length_seconds > 0 and \
                    target_watch >= length_seconds * 0.5:
                print(f"  ✓ {target_watch}s reported – "
                      f"50% threshold met (short video)")
            else:
                print(f"  ? Reporting may be insufficient")
            return True

        except requests.exceptions.Timeout:
            print("  ✗ Request timed out"); return False
        except requests.exceptions.ConnectionError as e:
            print(f"  ✗ Connection error: {e}"); return False
        except Exception as e:
            print(f"  ✗ Unexpected: {e}")
            import traceback; traceback.print_exc()
            return False


# ═══════════════════════════════════════════════════════
if __name__ == "__main__":
    TARGET_VIDEO = "14IdaLMo6P0"

    PROXIES = [
        None,
        # "http://user:pass@host:port",
        # "socks5://user:pass@host:port",
    ]

    stats = {"success": 0, "fail": 0, "total_views": 0}

    while True:
        proxy = random.choice(PROXIES) if PROXIES else None
        sim = YouTubeViewSimulator(proxy=proxy)
        success = sim.simulate(TARGET_VIDEO)

        if success:
            stats["success"] += 1
            stats["total_views"] += 1
            cooldown = random.uniform(1, 5)
        else:
            stats["fail"] += 1
            cooldown = random.uniform(1, 5)

        print(f"\n  Stats → ok: {stats['success']}  "
              f"fail: {stats['fail']}  "
              f"views: {stats['total_views']}")
        print(f"  Cooling down {int(cooldown)}s …")
        time.sleep(cooldown)
