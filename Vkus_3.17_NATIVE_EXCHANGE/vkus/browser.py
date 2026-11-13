from pathlib import Path
import atexit
import shutil
import subprocess
import threading
import time
from datetime import datetime
import socket
import re

from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import TimeoutException, WebDriverException

ROOT = Path(__file__).resolve().parent.parent
PROFILE = (Path.home() / '.vkus' / 'firefox_profile').resolve()
LEGACY_PROFILE = (ROOT / 'data' / 'firefox_profile').resolve()
MARIONETTE_PORT = 2828
GECKODRIVER_PORT = 4444


class BrowserManager:
    """Keeps one real Firefox profile/session for all Vkus operations."""

    def __init__(self, logger):
        self.logger = logger
        self.driver = None
        self.lock = threading.RLock()
        self.session_number = 0
        self._stopping = False
        self._geckodriver = None
        self._migrated = False
        self._community_search_query = ""
        self._community_search_items = []
        atexit.register(self.stop)

    def _prepare_profile(self):
        PROFILE.parent.mkdir(parents=True, exist_ok=True)
        if not PROFILE.exists() and LEGACY_PROFILE.exists():
            self.logger.info('Migrating old Vkus Firefox profile: %s -> %s', LEGACY_PROFILE, PROFILE)
            shutil.copytree(LEGACY_PROFILE, PROFILE)
        PROFILE.mkdir(parents=True, exist_ok=True)

        # Vkus must use a direct network connection.  The first Selenium
        # version explicitly set this preference, but when Firefox is started
        # as a real standalone process the preference has to be written into
        # the profile itself before Firefox starts.  Otherwise an old/manual
        # proxy setting in the profile can make VK show "proxy server error".
        user_js = PROFILE / 'user.js'
        proxy_prefs = (
            'user_pref(\"network.proxy.type\", 0);\n'
            'user_pref(\"network.proxy.share_proxy_settings\", false);\n'
            'user_pref(\"network.proxy.no_proxies_on\", \"\");\n'
        )
        try:
            existing = user_js.read_text(encoding='utf-8') if user_js.exists() else ''
            if proxy_prefs not in existing:
                user_js.write_text(existing.rstrip() + ('\n' if existing.strip() else '') + proxy_prefs, encoding='utf-8')
        except OSError as exc:
            self.logger.warning('Could not update Firefox proxy preferences: %s', exc)

        self._migrated = True

    @staticmethod
    def _port_open(port):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.15)
            return s.connect_ex(('127.0.0.1', port)) == 0

    def _start_firefox_with_profile(self):
        """Start Firefox itself with the persistent profile and Marionette enabled."""
        self._prepare_profile()
        cmd = [
            'firefox',
            '--new-instance',
            '--no-remote',
            '--marionette',
            '--marionette-port', str(MARIONETTE_PORT),
            '-profile', str(PROFILE),
        ]
        self.logger.info('Starting Firefox with Vkus profile: %s', PROFILE)
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)

    def _connect_existing(self):
        """Connect geckodriver to Firefox already listening on Marionette."""
        service = Service()
        service.service_args = ['--connect-existing', '--marionette-port', str(MARIONETTE_PORT)]
        self.logger.info('Connecting Selenium to existing Firefox on Marionette port %s', MARIONETTE_PORT)
        self.driver = webdriver.Firefox(service=service)
        self._geckodriver = service
        self.session_number += 1
        self.driver.set_page_load_timeout(60)
        self.driver.set_script_timeout(30)
        try:
            self.driver.set_window_size(1280, 900)
        except Exception:
            pass
        self.logger.info('Firefox session #%s connected; profile=%s', self.session_number, PROFILE)
        return self.driver

    def start(self):
        with self.lock:
            if self.driver:
                try:
                    _ = self.driver.current_url
                    return self.driver
                except Exception:
                    self.driver = None

            self._prepare_profile()

            # First choice: use the Firefox instance that Vkus itself started.
            if self._port_open(MARIONETTE_PORT):
                try:
                    return self._connect_existing()
                except Exception as exc:
                    self.logger.warning('Existing Marionette Firefox connection failed: %s', exc)
                    self.driver = None

            # No managed Firefox is running: start it with the SAME persistent
            # profile, then connect Selenium to that browser.
            self._start_firefox_with_profile()
            deadline = time.monotonic() + 30
            last_error = None
            while time.monotonic() < deadline:
                if self._port_open(MARIONETTE_PORT):
                    try:
                        return self._connect_existing()
                    except Exception as exc:
                        last_error = exc
                time.sleep(0.25)

            raise RuntimeError(
                f'Firefox started but Marionette did not become available on port {MARIONETTE_PORT}: {last_error}'
            )

    def wait_ready(self, timeout=30):
        driver = self.start()
        WebDriverWait(driver, timeout, poll_frequency=0.25).until(
            lambda d: d.execute_script("return document.readyState") in ('interactive', 'complete')
        )
        WebDriverWait(driver, timeout, poll_frequency=0.25).until(
            lambda d: d.find_elements(By.TAG_NAME, 'body')
        )
        return driver

    def navigate(self, url, timeout=30):
        """Navigate without making a slow VM wait for every network resource."""
        with self.lock:
            driver = self.start()
            self.logger.info('Navigation start: %s | Firefox session #%s', url, self.session_number)
            page_timeout = min(max(int(timeout or 15), 5), 45)
            try:
                driver.set_page_load_timeout(page_timeout)
                driver.get(url)
            except TimeoutException:
                # VK is a heavy SPA; once the document shell exists we do not
                # need to wait for every image/analytics request to finish.
                self.logger.warning('Navigation timeout; stopping remaining network work: %s', url)
                try:
                    driver.execute_script('window.stop();')
                except Exception:
                    pass
            try:
                WebDriverWait(driver, min(20, page_timeout), poll_frequency=0.25).until(
                    lambda d: d.find_elements(By.TAG_NAME, 'body')
                )
            except Exception:
                pass
            current = driver.current_url
            self.logger.info('Navigation complete: %s | Firefox session #%s', current, self.session_number)
            return current

    def search_wall_posts(self, query, city='', region='', limit=0):
        """Backward-compatible wrapper for a post-only VK search."""
        return self.search_vk(query, city, region, mode='posts', limit=limit)

    def search_vk(self, query, city='', region='', mode='posts', limit=0, year='Все годы', month='Все месяцы'):
        """Search real VK posts/comments and keep the actual author attached to every hit."""
        from urllib.parse import quote_plus

        query = (query or '').strip()
        city = (city or '').strip()
        region = (region or '').strip()
        mode = (mode or 'posts').strip().lower()
        requested_limit = max(0, int(limit or 0))
        year = str(year or 'Все годы').strip()
        month = str(month or 'Все месяцы').strip()
        selected_year = int(year) if year.isdigit() else None
        month_names = {'январь': 1, 'февраль': 2, 'март': 3, 'апрель': 4, 'май': 5, 'июнь': 6, 'июль': 7, 'август': 8, 'сентябрь': 9, 'октябрь': 10, 'ноябрь': 11, 'декабрь': 12}
        selected_month = month_names.get(month.lower())
        if mode not in ('posts', 'comments'):
            raise ValueError('Неизвестный режим поиска VK')
        if not query and city and city not in ('Все города', 'Все'):
            query = city
        if not query:
            raise ValueError('Введите запрос для поиска VK')
        if not self.verify_authenticated(timeout=12):
            if not self.ensure_authenticated(timeout=90):
                raise RuntimeError('VK не авторизован. Войдите в VK в открывшемся Firefox и повторите поиск.')

        terms = query
        if mode == 'comments' and not re.search(r'(^|\s)type:reply(?:\s|$)', terms, re.I):
            terms = f'{terms} type:reply'
        if city and city not in ('Все города', 'Все') and city.lower() not in query.lower():
            terms = f'{terms} {city}'
        elif region and region != 'Все регионы' and region.lower() not in query.lower() and city in ('Все города', 'Все'):
            terms = f'{terms} {region}'
        encoded = quote_plus(terms)

        # VK has changed the search UI more than once.  For comments we first
        # try the dedicated comments feed, then the generic search page with
        # type:reply, and only then the statuses route.  We keep all three
        # because one may render a result shell while another renders the
        # actual comment nodes needed by Selenium.
        if mode == 'comments':
            routes = [
                'https://vk.ru/feed?section=comments&q=' + encoded,
                'https://vk.ru/feed?q=' + encoded + '&section=search',
                'https://vk.ru/search/statuses?c%5Bq%5D=' + encoded + '&q=' + encoded,
            ]
        else:
            routes = [
                'https://vk.ru/search/statuses?c%5Bq%5D=' + encoded + '&q=' + encoded,
                'https://vk.ru/feed?q=' + encoded + '&section=search',
            ]

        last_error = None
        for route_index, url in enumerate(routes):
            try:
                self.logger.info('VK %s search route %s/%s: %s', mode, route_index + 1, len(routes), url)
                self.navigate(url, timeout=15)
                driver = self.get()
                WebDriverWait(driver, 8, poll_frequency=.35).until(
                    lambda d: d.find_elements(By.TAG_NAME, 'body'))
                if self._looks_like_login(driver) or not self.has_vk_session_cookie():
                    raise RuntimeError('VK открыл страницу авторизации вместо результатов поиска')
                time.sleep(1.2)

                collected = {}
                stable_rounds = 0
                previous_count = -1
                started = time.monotonic()
                max_seconds = 65 if mode == 'comments' else 45
                max_rounds = 80 if mode == 'comments' else 55

                for round_no in range(max_rounds):
                    if time.monotonic() - started > max_seconds:
                        break
                    batch = driver.execute_script(r"""
                        const wallRe = /\/wall(-?\d+)_([0-9]+)/i;
                        const replyRe = /(?:[?&#](?:reply|reply_id|thread|comment)=\d+|#comment\d+|#reply\d+)/i;
                        const badPath = /\/(?:search|feed|im|groups|communities|settings|notifications|friends|photos|video|audio)(?:[\/?#]|$)/i;
                        const clean = v => { try { return new URL(v, location.href).href; } catch (_) { return String(v || ''); } };
                        const norm = v => (v || '').replace(/\s+/g, ' ').trim();
                        const wanted = norm(String(arguments[1] || '')).toLowerCase();
                        const wantedWords = wanted.split(/\s+/).filter(Boolean);

                        function sourceUrl(a) {
                            return clean(a.href || a.getAttribute('href') || a.getAttribute('data-href') || a.getAttribute('data-url') || '');
                        }
                        function wallInfo(href) {
                            let u = ''; try { u = new URL(href, location.href).href; } catch (_) { return null; }
                            const m = u.match(/\/wall(-?\d+)_([0-9]+)/i);
                            return m ? { owner: m[1], post: m[2], url: u } : null;
                        }
                        function dateInfo(node, card) {
                            const pools = [];
                            if (node) pools.push(node);
                            if (card && card !== node) pools.push(card);
                            const vals = [];
                            for (const pool of pools) {
                                try {
                                    for (const el of pool.querySelectorAll('time[datetime],[datetime],[data-time],[data-date],[title]')) {
                                        for (const attr of ['datetime','data-time','data-date','title']) {
                                            const v = el.getAttribute && el.getAttribute(attr);
                                            if (v) vals.push(v);
                                        }
                                    }
                                } catch (_) {}
                            }
                            for (const raw0 of vals) {
                                const raw = String(raw0).trim();
                                if (!raw) continue;
                                if (/^\d{9,13}$/.test(raw)) {
                                    let n = Number(raw);
                                    if (raw.length <= 10) n *= 1000;
                                    if (n > 0) return { ts: n, text: raw };
                                }
                                const parsed = Date.parse(raw);
                                if (!Number.isNaN(parsed)) return { ts: parsed, text: raw };
                                const m = raw.toLowerCase().match(/(\d{1,2})\s+(янв(?:аря)?|фев(?:раля)?|мар(?:та)?|апр(?:еля)?|ма[яй]|июн(?:я)?|июл(?:я)?|авг(?:уста)?|сен(?:тября)?|окт(?:ября)?|ноя(?:бря)?|дек(?:абря)?)\s+(\d{4})/i);
                                if (m) {
                                    const months = {'янв':0,'фев':1,'мар':2,'апр':3,'мая':4,'май':4,'июн':5,'июл':6,'авг':7,'сен':8,'окт':9,'ноя':10,'дек':11};
                                    const mon = Object.keys(months).find(k => m[2].startsWith(k));
                                    if (mon) return { ts: new Date(Number(m[3]), months[mon], Number(m[1]), 12, 0, 0).getTime(), text: raw };
                                }
                                const short = raw.toLowerCase().match(/(\d{1,2})\s+(янв(?:аря)?|фев(?:раля)?|мар(?:та)?|апр(?:еля)?|ма[яй]|июн(?:я)?|июл(?:я)?|авг(?:уста)?|сен(?:тября)?|окт(?:ября)?|ноя(?:бря)?|дек(?:абря)?)(?:\s*г\.)?/i);
                                if (short) {
                                    const months = {'янв':0,'фев':1,'мар':2,'апр':3,'мая':4,'май':4,'июн':5,'июл':6,'авг':7,'сен':8,'окт':9,'ноя':10,'дек':11};
                                    const mon = Object.keys(months).find(k => short[2].startsWith(k));
                                    if (mon) {
                                        const now = new Date();
                                        return { ts: new Date(now.getFullYear(), months[mon], Number(short[1]), 12, 0, 0).getTime(), text: raw };
                                    }
                                }
                                if (/^сегодня$/i.test(raw)) return { ts: Date.now(), text: raw };
                                if (/^вчера$/i.test(raw)) return { ts: Date.now() - 24*60*60*1000, text: raw };
                            }
                            return { ts: 0, text: '' };
                        }

                        function hasCommentMarker(node, href) {
                            if (replyRe.test(href || '')) return true;
                            let n = node;
                            for (let i = 0; i < 14 && n; i++, n = n.parentElement) {
                                if (!n) break;
                                const attrs = [
                                    n.getAttribute && n.getAttribute('data-comment-id'),
                                    n.getAttribute && n.getAttribute('data-reply-id'),
                                    n.getAttribute && n.getAttribute('data-reply'),
                                    n.getAttribute && n.getAttribute('data-comment'),
                                    n.getAttribute && n.getAttribute('data-item-id'),
                                    n.getAttribute && n.getAttribute('id')
                                ].filter(Boolean).join(' ');
                                if (/comment|reply/i.test(attrs)) return true;
                                const cls = typeof n.className === 'string' ? n.className : '';
                                if (/\b(?:comment|reply|replies|comments)\b/i.test(cls)) return true;
                                const aria = (n.getAttribute && (n.getAttribute('aria-label') || n.getAttribute('data-testid'))) || '';
                                if (/comment|reply/i.test(aria)) return true;
                            }
                            return false;
                        }
                        function commentNodeFrom(node, href) {
                            let n = node;
                            for (let i = 0; i < 14 && n; i++, n = n.parentElement) {
                                if (hasCommentMarker(n, href)) {
                                    const exact = n.querySelector && n.querySelector('[data-comment-id],[data-reply-id],[data-reply],[data-comment]');
                                    if (exact) return exact;
                                    if (/(?:comment|reply)/i.test(String(n.className || ''))) return n;
                                }
                            }
                            return null;
                        }
                        function cardFor(node) {
                            let n = node;
                            for (let i = 0; i < 12 && n; i++, n = n.parentElement) {
                                const t = norm(n.innerText);
                                if (t.length >= 15 && t.length <= 9000) {
                                    const wallLinks = Array.from(n.querySelectorAll('a[href]')).filter(x => wallInfo(sourceUrl(x)));
                                    if (wallLinks.length) return n;
                                }
                            }
                            return node.parentElement || node;
                        }
                        function profileLinks(node, source) {
                            if (!node) return [];
                            const links = Array.from(node.querySelectorAll('a[href]'));
                            const result = [];
                            for (const l of links) {
                                const h = sourceUrl(l);
                                if (!/^https?:\/\/(?:vk\.(?:com|ru))\//i.test(h)) continue;
                                let path = ''; try { path = new URL(h).pathname; } catch (_) { continue; }
                                if (h === source || wallRe.test(path) || badPath.test(path)) continue;
                                if (!/^\/(?:id\d+|[A-Za-z0-9_.-]{2,})\/?$/i.test(path)) continue;
                                const nm = norm(l.innerText || l.getAttribute('aria-label') || l.getAttribute('title') || '');
                                if (!nm) continue;
                                result.push({ name: nm, profile: h, el: l });
                            }
                            return result;
                        }
                        function authorFrom(commentNode, card, source, textAnchor) {
                            const pools = [];
                            if (commentNode) pools.push(commentNode);
                            if (textAnchor && textAnchor !== commentNode) pools.push(textAnchor);
                            if (card && card !== commentNode) pools.push(card);
                            for (const pool of pools) {
                                const found = profileLinks(pool, source);
                                if (found.length) return found[0];
                            }
                            return { name: '', profile: '' };
                        }
                        function findCommentText(anchor, card) {
                            // Prefer a small descendant/ancestor whose own text contains
                            // the requested phrase. This prevents returning the whole post
                            // as the comment text.
                            let best = null;
                            const nodes = [];
                            if (anchor) nodes.push(anchor);
                            if (card) {
                                try { nodes.push(...Array.from(card.querySelectorAll('span,div,p,a')).slice(0, 1200)); } catch (_) {}
                            }
                            for (const n of nodes) {
                                const t = norm(n.innerText || n.textContent || '');
                                if (t.length < wanted.length || t.length > 1800) continue;
                                if (!wanted || !t.toLowerCase().includes(wanted)) continue;
                                if (!best || t.length < best.text.length) best = { node: n, text: t };
                            }
                            return best;
                        }
                        function looksLikeCommentCandidate(node, href, card, textNode) {
                            if (hasCommentMarker(node, href)) return true;
                            if (replyRe.test(href || '')) return true;
                            const hay = norm([
                                node && node.innerText,
                                textNode && textNode.innerText,
                                card && card.innerText
                            ].filter(Boolean).join(' ')).toLowerCase();
                            // Search result cards often expose an explicit reply/comment
                            // action even when VK omits data-comment-* attributes.
                            return /(?:ответить|ответ|комментар(?:ий|ии)|reply|comment)/i.test(hay);
                        }

                        function extract(mode) {
                            const out = [];
                            const seen = new Set();
                            const anchors = Array.from(document.querySelectorAll('a[href], [data-href], [data-url]'));

                            for (const a of anchors) {
                                const absolute = sourceUrl(a);
                                const wi = wallInfo(absolute);
                                if (!wi) continue;
                                const card = cardFor(a);
                                const textHit = findCommentText(a, card);
                                const cnode = commentNodeFrom(a, absolute);
                                const isComment = looksLikeCommentCandidate(cnode || a, absolute, card, textHit && textHit.node);

                                if (mode === 'comments') {
                                    // A comments result must have a concrete comment signal.
                                    // Never fall back to a post merely because its post text
                                    // contains the query.
                                    if (!isComment) continue;
                                } else if (isComment) {
                                    continue;
                                }

                                const key = absolute.split('#')[0];
                                if (seen.has(key)) continue;

                                let text = '';
                                if (mode === 'comments') {
                                    if (textHit) text = textHit.text;
                                    else if (cnode) text = norm(cnode.innerText || cnode.textContent || '');
                                    else text = norm(a.innerText || '');
                                    if (!text || !wanted || !text.toLowerCase().includes(wanted)) continue;
                                } else {
                                    text = norm(card.innerText || a.innerText || '');
                                }
                                if (text.length < 2) continue;

                                const author = authorFrom(cnode, card, absolute, textHit && textHit.node);
                                const username = (author.profile.match(/\/(?:id)?([^/?#]+)\/?$/i) || [])[1] || '';
                                out.push({
                                    url: absolute,
                                    text,
                                    comment_text: mode === 'comments' ? text : '',
                                    profile: author.profile,
                                    author_name: author.name,
                                    username,
                                    kind: mode,
                                    owner_id: wi.owner,
                                    post_id: wi.post,
                                    date_ts: dateInfo(cnode || a, card).ts,
                                    date_text: dateInfo(cnode || a, card).text
                                });
                                seen.add(key);
                            }

                            // Second pass: VK can render a comment as a text block without
                            // making its wall link the nearest <a>. Find text blocks first,
                            // then climb to a parent containing a concrete wall URL.
                            if (mode === 'comments') {
                                const candidates = [];
                                try {
                                    for (const n of Array.from(document.querySelectorAll('span,div,p')).slice(0, 2500)) {
                                        const t = norm(n.innerText || n.textContent || '');
                                        if (!t || t.length > 1800 || !wanted || !t.toLowerCase().includes(wanted)) continue;
                                        candidates.push(n);
                                    }
                                } catch (_) {}
                                for (const n of candidates) {
                                    let parent = n;
                                    let wallHref = '';
                                    let commentSignal = false;
                                    for (let i = 0; i < 14 && parent; i++, parent = parent.parentElement) {
                                        const links = Array.from(parent.querySelectorAll ? parent.querySelectorAll('a[href]') : []);
                                        const wl = links.find(l => wallInfo(sourceUrl(l)));
                                        if (wl) {
                                            wallHref = sourceUrl(wl);
                                            commentSignal = hasCommentMarker(n, wallHref) || replyRe.test(wallHref) || /(?:ответить|ответ|комментар|reply|comment)/i.test(norm(parent.innerText || ''));
                                            if (commentSignal) break;
                                        }
                                    }
                                    if (!wallHref || !commentSignal) continue;
                                    const key = wallHref.split('#')[0] + '|' + norm(n.innerText || n.textContent || '').toLowerCase();
                                    if (seen.has(key)) continue;
                                    const wi = wallInfo(wallHref);
                                    if (!wi) continue;
                                    const card = cardFor(n);
                                    const cnode = commentNodeFrom(n, wallHref);
                                    const text = norm((cnode || n).innerText || (cnode || n).textContent || '');
                                    if (!text.toLowerCase().includes(wanted)) continue;
                                    const author = authorFrom(cnode, card, wallHref, n);
                                    const username = (author.profile.match(/\/(?:id)?([^/?#]+)\/?$/i) || [])[1] || '';
                                    out.push({
                                        url: wallHref,
                                        text,
                                        comment_text: text,
                                        profile: author.profile,
                                        author_name: author.name,
                                        username,
                                        kind: mode,
                                        owner_id: wi.owner,
                                        post_id: wi.post,
                                        date_ts: dateInfo(cnode || n, card).ts,
                                        date_text: dateInfo(cnode || n, card).text
                                    });
                                    seen.add(key);
                                }
                            }
                            return out;
                        }

                        return {
                            items: extract(arguments[0]),
                            url: location.href,
                            height: Math.max(document.documentElement.scrollHeight || 0, document.body.scrollHeight || 0)
                        };
                    """, mode, query) or {}

                    # Apply the selected year to both modes. In COMMENTS mode
                    # keep only comments from the last six months and reject
                    # undated items rather than guessing their age.
                    now_ts = time.time() * 1000.0
                    six_month_cutoff = now_ts - (183 * 24 * 60 * 60 * 1000)
                    raw_items = batch.get('items', []) if isinstance(batch, dict) else []
                    filtered_items = []
                    for item in raw_items:
                        try:
                            ts = float(item.get('date_ts') or 0)
                        except Exception:
                            ts = 0
                        if (selected_year is not None or selected_month is not None) and not ts:
                            continue
                        if selected_year is not None and datetime.fromtimestamp(ts / 1000.0).year != selected_year:
                            continue
                        if selected_month is not None and datetime.fromtimestamp(ts / 1000.0).month != selected_month:
                            continue
                        if mode == 'comments' and (not ts or ts < six_month_cutoff):
                            continue
                        filtered_items.append(item)

                    for item in filtered_items:
                        u = str(item.get('url', '')).strip()
                        txt = str(item.get('comment_text') or item.get('text') or '').strip()
                        if not u or not txt:
                            continue
                        # Comment mode is deliberately strict: the returned text itself
                        # must contain the user's query. This blocks false post matches.
                        if mode == 'comments' and query.lower() not in txt.lower():
                            continue
                        key = u + '|' + txt[:300]
                        if key not in collected:
                            collected[key] = item

                    count = len(collected)
                    if requested_limit and count >= requested_limit:
                        break
                    stable_rounds = stable_rounds + 1 if count == previous_count else 0
                    previous_count = count
                    scroll_state = driver.execute_script(r"""
                        const step=Math.max(900,Math.floor(window.innerHeight*.9)),before=window.scrollY;
                        window.scrollBy(0,step); let internal=0;
                        for(const sel of ['[role="main"]','main','[data-qa-type="main"]','[class*="scroll"]']){
                            let els=[]; try{els=Array.from(document.querySelectorAll(sel)).slice(0,12)}catch(_){continue}
                            for(const el of els){try{if(el.scrollHeight>el.clientHeight+120){const old=el.scrollTop;el.scrollTop=Math.min(el.scrollTop+step,el.scrollHeight);internal+=Math.abs(el.scrollTop-old)}}catch(_){}}
                        }
                        return {moved:Math.abs(window.scrollY-before),internal};
                    """) or {}
                    time.sleep(.5)
                    if stable_rounds >= 7 and not scroll_state.get('moved') and not scroll_state.get('internal'):
                        break

                raw = list(collected.values())
                if mode == 'comments':
                    raw = [x for x in raw if x.get('kind') == 'comments' and x.get('comment_text') and query.lower() in str(x.get('comment_text')).lower()]
                if raw:
                    self.logger.info('VK %s search collected %s real results', mode, len(raw))
                    return raw
                last_error = RuntimeError('VK открыл поиск, но реальные ' + ('комментарии' if mode == 'comments' else 'записи') + ' не появились.')
            except Exception as exc:
                last_error = exc
                self.logger.warning('VK %s search route %s failed: %s', mode, route_index + 1, exc)

        raise RuntimeError(str(last_error or 'VK поиск не вернул результатов'))

    def search_communities(self, query, limit=15):
        """Search VK communities through VK's real communities route."""
        from urllib.parse import quote_plus

        query = (query or '').strip()
        if not query:
            raise ValueError('Введите название сообщества или ключевую фразу')
        if not self.verify_authenticated(timeout=20):
            if not self.ensure_authenticated(timeout=90):
                raise RuntimeError('VK не авторизован. Войдите в VK и повторите поиск.')

        encoded = quote_plus(query)
        routes = [
            f'https://vk.ru/search/communities?q={encoded}',
            f'https://vk.com/search/communities?q={encoded}',
        ]
        last_error = None

        for route in routes:
            try:
                self.navigate(route, timeout=40)
                driver = self.get()
                WebDriverWait(driver, 25, poll_frequency=.3).until(
                    lambda d: d.find_elements(By.TAG_NAME, 'body') and
                              d.execute_script("return document.readyState") in ('interactive', 'complete')
                )
                if self._looks_like_login(driver) or not self.has_vk_session_cookie():
                    raise RuntimeError('VK открыл страницу авторизации вместо поиска сообществ')

                # VK is a heavy SPA: the URL can appear before the actual search
                # controls/results are mounted. Do not declare failure after a few
                # seconds. First give the route up to 45 s to render; if VK leaves
                # us on the generic search page, perform the same action a human
                # does: type into the search field and press Enter.
                def page_snapshot():
                    return driver.execute_script(r'''
                        const body = document.body;
                        const text = body ? (body.innerText || '') : '';
                        const inputs = Array.from(document.querySelectorAll('input')).map(el => ({
                            placeholder: el.getAttribute('placeholder') || '',
                            aria: el.getAttribute('aria-label') || '',
                            type: el.type || ''
                        }));
                        return {url: location.href, text: text.slice(0, 12000), inputs};
                    ''') or {}

                def route_is_community_search():
                    return '/search/communities' in (driver.current_url or '')

                # Allow the direct route time to finish its SPA transition.
                WebDriverWait(driver, 45, poll_frequency=.4).until(
                    lambda d: route_is_community_search() or
                              any('поиск' in str(x).lower() or 'search' in str(x).lower()
                                  for x in (page_snapshot().get('inputs') or []))
                )

                # If VK rendered the general search UI instead of applying q=...,
                # use the search input exactly as a user would.
                if not route_is_community_search() or 'q=' not in (driver.current_url or '').lower():
                    typed = driver.execute_script(r'''
                        const candidates = Array.from(document.querySelectorAll('input'));
                        const score = el => {
                            const s = [el.placeholder, el.getAttribute('aria-label'), el.name, el.type]
                                .filter(Boolean).join(' ').toLowerCase();
                            let n = 0;
                            if (s.includes('поиск') || s.includes('search')) n += 5;
                            if (el.type === 'search') n += 3;
                            if (el.offsetParent !== null) n += 2;
                            return n;
                        };
                        candidates.sort((a,b) => score(b)-score(a));
                        return candidates.length ? candidates[0] : null;
                    ''')
                    if typed:
                        try:
                            typed.clear()
                            typed.send_keys(query)
                            typed.send_keys(Keys.ENTER)
                        except Exception:
                            # JS fallback for controlled VK inputs.
                            driver.execute_script(r'''
                                const el = arguments[0], value = arguments[1];
                                const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
                                setter.call(el, value);
                                el.dispatchEvent(new Event('input', {bubbles:true}));
                                el.dispatchEvent(new Event('change', {bubbles:true}));
                            ''', typed, query)
                            try: typed.send_keys(Keys.ENTER)
                            except Exception: pass

                    try:
                        WebDriverWait(driver, 30, poll_frequency=.4).until(
                            lambda d: '/search/communities' in (d.current_url or '') and
                                      ('q=' in (d.current_url or '').lower() or query.lower() in (d.page_source or '').lower())
                        )
                    except Exception:
                        pass

                def collect():
                    return driver.execute_script(r'''                        const q = String(arguments[0] || '').trim().toLowerCase();
                        const limit = Number(arguments[1] || 15);
                        const norm = v => (v || '').replace(/\s+/g, ' ').trim();
                        const clean = v => { try { return new URL(v, location.href).href; } catch (_) { return String(v || ''); } };
                        const out = [], seen = new Set();
                        const bad = /^(id\d+|feed|search|im|settings|notifications|friends|photos|video|audio|wall|albums|groups|communities)$/i;
                        const isCommunityPath = path => /^(?:club|public)\d+$/i.test(path) ||
                            (/^[A-Za-z0-9_.-]{2,}$/.test(path) && !bad.test(path));

                        for (const a of Array.from(document.querySelectorAll('a[href]'))) {
                            const href = clean(a.href || a.getAttribute('href') || '');
                            if (!/^https?:\/\/(?:vk\.ru|vk\.com)\//i.test(href)) continue;
                            let path = '';
                            try { path = new URL(href).pathname.replace(/^\//, '').replace(/\/$/, ''); } catch (_) { continue; }
                            if (!isCommunityPath(path)) continue;
                            if (/^(?:search|feed|im|settings|notifications|friends|photos|video|audio|wall|albums|groups|communities)(?:\/|$)/i.test(path)) continue;

                            let card = a;
                            for (let i = 0; i < 8 && card; i++, card = card.parentElement) {
                                const t = norm(card.innerText || '');
                                if (t.length >= 2 && t.length <= 2500) break;
                            }
                            const anchorText = norm(a.innerText || a.getAttribute('aria-label') || a.getAttribute('title') || '');
                            const cardText = norm(card && card.innerText || anchorText);
                            const name = anchorText || (cardText.split('\n')[0] || '').trim();
                            if (!name || name.length < 2) continue;
                            if (q && !(name + ' ' + cardText).toLowerCase().includes(q)) continue;

                            const key = href.split('#')[0].replace(/\/$/, '');
                            if (seen.has(key)) continue;
                            let avatar = '';
                            try {
                                const img = card && card.querySelector('img[src]');
                                avatar = img ? (img.currentSrc || img.src || '') : '';
                            } catch (_) {}
                            out.push({name: name.slice(0, 180), url: key, description: cardText.slice(0, 420), avatar});
                            seen.add(key);
                            if (out.length >= limit) break;
                        }
                        return out;
                    ''', query, int(limit)) or []

                items = []
                # Results may be mounted well after the route itself. Poll for up
                # to 45 s instead of failing while VK is still rendering cards.
                deadline = time.time() + 45
                while time.time() < deadline:
                    items = collect()
                    if items:
                        break
                    time.sleep(.75)

                if items:
                    self._community_search_query = query
                    self._community_search_items = list(items)
                    self.logger.info('VK community search: %s results for %r | url=%s', len(items), query, driver.current_url)
                    return items

                last_error = RuntimeError(
                    f'VK открыл поиск сообществ, но результаты не появились.\nОткрытый адрес: {driver.current_url}'
                )
            except Exception as exc:
                last_error = exc
                self.logger.warning('VK community search route failed: %s', exc)

        raise RuntimeError(str(last_error or 'Ошибка поиска сообществ VK'))

    def load_more_communities(self, batch=10):
        """Scroll the current VK community search and return all loaded cards."""
        with self.lock:
            driver = self.get()
            query = self._community_search_query.strip().lower()
            if not driver or '/search/communities' not in (driver.current_url or ''):
                raise RuntimeError('Страница поиска сообществ VK уже закрыта или не открыта.')
            before = len(self._community_search_items)
            deadline = time.time() + 25
            while time.time() < deadline:
                driver.execute_script("window.scrollTo(0, Math.max(document.body.scrollHeight, document.documentElement.scrollHeight));")
                time.sleep(.8)
                found = driver.execute_script("""
                    const q = String(arguments[0] || '').trim().toLowerCase();
                    const norm = v => (v || '').replace(/\s+/g, ' ').trim();
                    const clean = v => { try { return new URL(v, location.href).href; } catch (_) { return String(v || ''); } };
                    const out = [], seen = new Set();
                    const bad = /^(id\d+|feed|search|im|settings|notifications|friends|photos|video|audio|wall|albums|groups|communities)$/i;
                    for (const a of Array.from(document.querySelectorAll('a[href]'))) {
                        const href = clean(a.href || a.getAttribute('href') || '');
                        if (!/^https?:\/\/(?:vk\.ru|vk\.com)\//i.test(href)) continue;
                        let path = '';
                        try { path = new URL(href).pathname.replace(/^\//, '').replace(/\/$/, ''); } catch (_) { continue; }
                        const community = /^(?:club|public)\d+$/i.test(path) || (/^[A-Za-z0-9_.-]{2,}$/.test(path) && !bad.test(path));
                        if (!community || /^(?:search|feed|im|settings|notifications|friends|photos|video|audio|wall|albums|groups|communities)(?:\/|$)/i.test(path)) continue;
                        let card = a;
                        for (let i = 0; i < 8 && card; i++, card = card.parentElement) {
                            const t = norm(card.innerText || '');
                            if (t.length >= 2 && t.length <= 2500) break;
                        }
                        const anchorText = norm(a.innerText || a.getAttribute('aria-label') || a.getAttribute('title') || '');
                        const cardText = norm(card && card.innerText || anchorText);
                        const name = anchorText || (cardText.split('\n')[0] || '').trim();
                        if (!name || name.length < 2) continue;
                        if (q && !(name + ' ' + cardText).toLowerCase().includes(q)) continue;
                        const key = href.split('#')[0].replace(/\/$/, '');
                        if (seen.has(key)) continue;
                        seen.add(key);
                        let avatar = '';
                        try { const img = card && card.querySelector('img[src]'); avatar = img ? (img.currentSrc || img.src || '') : ''; } catch (_) {}
                        out.push({name: name.slice(0, 180), url: key, description: cardText.slice(0, 420), avatar});
                    }
                    return out;
                """, query) or []
                merged, seen = [], set()
                for item in list(self._community_search_items) + list(found):
                    key = item.get('url', '').rstrip('/')
                    if not key or key in seen: continue
                    seen.add(key); merged.append(item)
                if len(merged) > before:
                    self._community_search_items = merged
                    return merged
                time.sleep(.8)
            return list(self._community_search_items)

    def search_community_comments(self, community_url, query, city='', region='', year='Все годы', month='Все месяцы', limit=0):
        """Search real comments inside one selected VK community by opening its real posts."""
        from urllib.parse import urlparse

        community_url = (community_url or '').strip()
        query = (query or '').strip()
        city = (city or '').strip()
        region = (region or '').strip()
        year = str(year or 'Все годы').strip()
        month = str(month or 'Все месяцы').strip()
        if not community_url:
            raise ValueError('Сначала выберите сообщество VK')
        if not query:
            raise ValueError('Введите запрос для поиска комментариев')
        if not self.verify_authenticated(timeout=20):
            if not self.ensure_authenticated(timeout=90):
                raise RuntimeError('VK не авторизован. Войдите в VK и повторите поиск.')

        month_names = {'январь':1,'февраль':2,'март':3,'апрель':4,'май':5,'июнь':6,'июль':7,'август':8,'сентябрь':9,'октябрь':10,'ноябрь':11,'декабрь':12}
        selected_year = int(year) if year.isdigit() else None
        selected_month = month_names.get(month.lower())
        now_ts = time.time() * 1000.0
        six_month_cutoff = now_ts - (183 * 24 * 60 * 60 * 1000)

        def date_ok(ts):
            if not ts:
                return selected_year is None and selected_month is None
            try:
                dt = datetime.fromtimestamp(float(ts) / 1000.0)
            except Exception:
                return False
            if selected_year is not None and dt.year != selected_year:
                return False
            if selected_month is not None and dt.month != selected_month:
                return False
            return ts >= six_month_cutoff

        # First collect real wall URLs from the selected community page.
        self.navigate(community_url, timeout=15)
        driver = self.get()
        time.sleep(1.0)
        if self._looks_like_login(driver) or not self.has_vk_session_cookie():
            raise RuntimeError('VK-сессия не авторизована')
        post_urls = []
        seen_posts = set()
        expected_owner = None
        try:
            m = re.search(r'/(?:club|public)(\d+)', urlparse(community_url).path, re.I)
            if m:
                expected_owner = '-' + m.group(1)
            else:
                # Custom community slugs (vk.ru/foo) do not contain a numeric id.
                # Resolve the real owner from the loaded page's canonical/wall URLs.
                resolved = driver.execute_script(r"""
                    const reWall=/\/wall(-?\d+)_\d+/i;
                    for(const a of Array.from(document.querySelectorAll('a[href]'))){
                        const h=String(a.href||''); const m=h.match(reWall);
                        if(m) return m[1];
                    }
                    for(const el of Array.from(document.querySelectorAll('[data-club-id],[data-group-id],[data-owner-id]'))){
                        const v=el.getAttribute('data-club-id')||el.getAttribute('data-group-id')||el.getAttribute('data-owner-id')||'';
                        if(/^-?\d+$/.test(v)) return String(v).startsWith('-') ? String(v) : '-'+String(v);
                    }
                    for(const el of Array.from(document.querySelectorAll('link[rel=canonical],meta[property="og:url"]'))){
                        const h=el.href || el.content || '';
                        const m=String(h).match(/\/(?:club|public)(\d+)/i);
                        if(m) return '-'+m[1];
                    }
                    const body=String(document.documentElement.innerHTML||'');
                    const m=body.match(/(?:club_id|group_id|owner_id)["':=\s]+(-?\d{3,})/i);
                    return m ? (String(m[1]).startsWith('-') ? String(m[1]) : '-'+String(m[1])) : '';
                """) or ''
                if resolved:
                    expected_owner = resolved if str(resolved).startswith('-') else '-'+str(resolved)
        except Exception:
            pass
        started = time.monotonic()
        for _ in range(24):
            batch = driver.execute_script(r"""
                const re=/\/wall(-?\d+)_([0-9]+)/i;
                const clean=v=>{try{return new URL(v,location.href).href}catch(_){return String(v||'')}};
                const out=[]; const seen=new Set();
                for(const a of Array.from(document.querySelectorAll('a[href]'))){
                    const h=clean(a.href||a.getAttribute('href')||'');
                    if(!re.test(h)) continue;
                    const u=h.split('#')[0]; if(seen.has(u)) continue;
                    seen.add(u); out.push(u);
                }
                return out;
            """) or []
            for u in batch:
                if expected_owner:
                    m = re.search(r'/wall(-?\d+)_', str(u), re.I)
                    if m and m.group(1) != expected_owner:
                        continue
                if u not in seen_posts:
                    seen_posts.add(u); post_urls.append(u)
            if len(post_urls) >= 30 or time.monotonic() - started > 35:
                break
            driver.execute_script("window.scrollBy(0, Math.max(900, Math.floor(window.innerHeight*.9)));")
            time.sleep(.7)
        if not post_urls:
            # VK can render the community wall without exposing wall links on the
            # first page. Retry through the explicit wall route before failing.
            try:
                current = driver.current_url.split('#')[0].rstrip('/')
                wall_url = current + '/wall'
                self.navigate(wall_url, timeout=15)
                driver = self.get(); time.sleep(1.0)
                batch = driver.execute_script(r"""
                    const re=/\/wall(-?\d+)_([0-9]+)/i, out=[], seen=new Set();
                    for(const a of Array.from(document.querySelectorAll('a[href]'))){
                        const h=String(a.href||a.getAttribute('href')||'');
                        if(!re.test(h)) continue;
                        const u=h.split('#')[0]; if(seen.has(u)) continue;
                        seen.add(u); out.push(u);
                    }
                    return out;
                """) or []
                for u in batch:
                    if expected_owner:
                        m=re.search(r'/wall(-?\d+)_',str(u),re.I)
                        if m and m.group(1)!=expected_owner: continue
                    if u not in seen_posts:
                        seen_posts.add(u); post_urls.append(u)
            except Exception as exc:
                self.logger.warning('Community wall fallback failed: %s', exc)
        if not post_urls:
            raise RuntimeError('В выбранном сообществе VK не удалось получить публикации для проверки комментариев.')

        results = []
        seen = set()
        # Newest posts first as VK presents them. A targeted community scan is much
        # smaller than a global comment search and is therefore practical in Selenium.
        for post_url in post_urls[:30]:
            if time.monotonic() - started > 90:
                break
            try:
                self.navigate(post_url, timeout=12)
                driver = self.get()
                time.sleep(.6)
                # Ask VK to reveal more comments where such controls are present.
                for _ in range(5):
                    clicked = driver.execute_script(r"""
                        let n=0;
                        for(const el of Array.from(document.querySelectorAll('button,a,[role="button"]'))){
                            try{
                                const t=((el.innerText||'')+' '+(el.getAttribute('aria-label')||'')+' '+(el.getAttribute('title')||'')).replace(/\s+/g,' ').trim().toLowerCase();
                                if(/показать (еще|ещё)|загрузить (еще|ещё)|все комментарии|комментарии|ответы|repl(?:y|ies)|comments|show more/i.test(t) && el.offsetParent){el.click();n++; if(n>=3) break;}
                            }catch(_){ }
                        }
                        return n;
                    """) or 0
                    if not clicked: break
                    time.sleep(.55)

                items = driver.execute_script(r"""
                    const wanted=String(arguments[0]||'').trim().toLowerCase();
                    const norm=v=>(v||'').replace(/\s+/g,' ').trim();
                    const wall=(location.href.match(/\/wall(-?\d+)_([0-9]+)/i)||[]);
                    const out=[]; const seen=new Set();
                    function tsOf(node){
                        const vals=[];
                        let n=node;
                        for(let i=0;i<10&&n;i++,n=n.parentElement){
                            for(const el of [n,...Array.from(n.querySelectorAll('time[datetime],[datetime],[data-time],[data-date],[title]')).slice(0,30)]){
                                for(const a of ['datetime','data-time','data-date','title']){try{const v=el.getAttribute&&el.getAttribute(a);if(v)vals.push(v)}catch(_){}}
                            }
                        }
                        for(const raw0 of vals){
                            const raw=String(raw0).trim(); if(!raw) continue;
                            if(/^\d{9,13}$/.test(raw)){let n=Number(raw);if(raw.length<=10)n*=1000;return {ts:n,text:raw};}
                            const p=Date.parse(raw); if(!Number.isNaN(p)) return {ts:p,text:raw};
                            const m=raw.toLowerCase().match(/(\d{1,2})\s+(янв(?:аря)?|фев(?:раля)?|мар(?:та)?|апр(?:еля)?|ма[яй]|июн(?:я)?|июл(?:я)?|авг(?:уста)?|сен(?:тября)?|окт(?:ября)?|ноя(?:бря)?|дек(?:абря)?)\s+(\d{4})/i);
                            if(m){const mm={'янв':0,'фев':1,'мар':2,'апр':3,'мая':4,'май':4,'июн':5,'июл':6,'авг':7,'сен':8,'окт':9,'ноя':10,'дек':11};const k=Object.keys(mm).find(x=>m[2].startsWith(x));if(k)return {ts:new Date(Number(m[3]),mm[k],Number(m[1]),12).getTime(),text:raw};}
                        }
                        return {ts:0,text:''};
                    }
                    function profile(node){
                        for(const a of Array.from((node&&node.querySelectorAll)?node.querySelectorAll('a[href]'):[])){
                            let h='';try{h=new URL(a.href,location.href).href}catch(_){continue}
                            let p='';try{p=new URL(h).pathname}catch(_){continue}
                            if(/^\/(?:id\d+|[A-Za-z0-9_.-]{2,})\/?$/i.test(p) && !/\/wall/i.test(p)) return {name:norm(a.innerText||a.getAttribute('aria-label')||''),url:h};
                        }
                        return {name:'',url:''};
                    }
                    const nodes=Array.from(document.querySelectorAll('[data-comment-id],[data-reply-id],[data-reply],[data-comment],*[class*="comment" i],*[class*="reply" i]'));
                    for(const n of nodes){
                        const text=norm(n.innerText||n.textContent||'');
                        if(!text || text.length>2200 || !text.toLowerCase().includes(wanted)) continue;
                        let parent=n; let marked=false;
                        for(let i=0;i<8&&parent;i++,parent=parent.parentElement){
                            const attrs=((parent.getAttribute&&parent.getAttribute('data-comment-id'))||'')+' '+((parent.getAttribute&&parent.getAttribute('data-reply-id'))||'')+' '+((typeof parent.className==='string')?parent.className:'');
                            if(/comment|reply/i.test(attrs)){marked=true;break;}
                        }
                        if(!marked) continue;
                        const key=text.toLowerCase(); if(seen.has(key)) continue;
                        const d=tsOf(n); const a=profile(n); const url=location.href.split('#')[0] + '#comment';
                        out.push({text,comment_text:text,profile_url:a.url,author_name:a.name,date_ts:d.ts,date_text:d.text,url,post_url:location.href.split('#')[0],kind:'comments'});
                        seen.add(key);
                    }
                    return out;
                """, query) or []
                for item in items:
                    if not date_ok(item.get('date_ts')):
                        continue
                    txt = str(item.get('comment_text') or '').strip()
                    if not txt or query.lower() not in txt.lower():
                        continue
                    key = (item.get('post_url','') + '|' + txt[:300]).lower()
                    if key not in seen:
                        item['city'] = city
                        item['region'] = region
                        results.append(item)
                        seen.add(key)
                        if limit and len(results) >= int(limit):
                            return results
            except Exception as exc:
                self.logger.warning('Community post scan failed for %s: %s', post_url, exc)
                continue
        if results:
            self.logger.info('VK community comment search: %s real results in %s', len(results), community_url)
            return results
        raise RuntimeError('В выбранном сообществе реальные комментарии по заданным параметрам не найдены.')

    def send_message(self, profile_url, text, timeout=30):
        """Open the real VK dialog for a concrete user and verify that the message appeared."""
        if not profile_url: return False,'У найденного контакта нет ссылки на профиль VK',''
        text=(text or '').strip()
        if not text: return False,'Пустое сообщение',profile_url
        try:
            self.navigate(profile_url,timeout=timeout);driver=self.get()
            if self._looks_like_login(driver) or not self.has_vk_session_cookie():
                return False,'VK-сессия не авторизована',driver.current_url
            m=re.search(r'/((?:id)?\d+)(?:[/?#]|$)',profile_url,re.I)
            direct='https://vk.ru/im?sel='+m.group(1).replace('id','',1) if m else ''
            if direct:
                self.navigate(direct,timeout=timeout);driver=self.get()
            WebDriverWait(driver,12,poll_frequency=.3).until(lambda d:d.find_elements(By.CSS_SELECTOR,'[contenteditable="true"],textarea,input[type="text"]'))
            fields=driver.find_elements(By.CSS_SELECTOR,'[contenteditable="true"],textarea,input[type="text"]')
            field=None
            for el in fields:
                try:
                    if not el.is_displayed() or not el.is_enabled(): continue
                    aria=((el.get_attribute('aria-label') or '')+' '+(el.get_attribute('placeholder') or '')).lower()
                    if el.tag_name=='input' and not any(k in aria for k in ('сообщ','message','напис')): continue
                    field=el
                    if 'сообщ' in aria or 'message' in aria: break
                except Exception: pass
            if field is None: return False,'Поле сообщения VK не найдено в диалоге',driver.current_url
            field.click();field.send_keys(text)
            buttons=driver.find_elements(By.CSS_SELECTOR,'button,[role="button"]')
            sent=False
            for b in buttons:
                try:
                    label=((b.text or '')+' '+(b.get_attribute('aria-label') or '')+' '+(b.get_attribute('title') or '')).strip().lower()
                    if any(k in label for k in ('отправить','send','послать')):
                        b.click();sent=True;break
                except Exception: pass
            if not sent: field.send_keys(Keys.ENTER)
            WebDriverWait(driver,8,poll_frequency=.3).until(lambda d: text in (d.find_element(By.TAG_NAME,'body').text or ''))
            time.sleep(.5)
            # If the composer still contains the exact unsent text, don't claim success.
            try:
                if (field.get_attribute('value') or field.text or '').strip()==text:
                    return False,'VK не подтвердил отправку сообщения',driver.current_url
            except Exception: pass
            return True,'Сообщение отправлено через реальный диалог VK',driver.current_url
        except Exception as exc:
            self.logger.exception('VK message send failed')
            return False,f'{type(exc).__name__}: {exc}',getattr(self.get(),'current_url',profile_url)

    def open_vk(self):
        return self.navigate('https://vk.ru/', timeout=30)

    def open_for_auth(self):
        driver = self.start()
        current = (driver.current_url or '').lower()
        if 'vk.com' not in current and 'vk.ru' not in current and 'id.vk.ru' not in current:
            try:
                driver.set_page_load_timeout(60)
                driver.get('https://vk.ru/')
            except TimeoutException:
                self.logger.warning('VK login page load timed out; keeping same Firefox session open')
        return driver

    def cookie_names(self):
        with self.lock:
            try:
                return sorted({str(c.get('name', '')) for c in self.start().get_cookies() if c.get('name')})
            except Exception as exc:
                self.logger.warning('Cookie inspection failed: %s', exc)
                return []

    def has_vk_session_cookie(self):
        names = [n.lower() for n in self.cookie_names()]
        return any(n.startswith(('remixsid', 'remixauth')) for n in names)

    def _looks_like_login(self, driver):
        url = (driver.current_url or '').lower()
        if any(x in url for x in ('/login', 'id.vk.ru/authorize', '/authorize')):
            return True
        try:
            text = driver.find_element(By.TAG_NAME, 'body').text.lower()
        except Exception:
            return False
        return ('войти в vk' in text or 'войти или зарегистрироваться' in text or
                'sign in to vk' in text)

    def verify_authenticated(self, timeout=20):
        with self.lock:
            driver = self.start()
            before = driver.current_url
            try:
                driver.set_page_load_timeout(timeout)
                driver.get('https://vk.ru/feed')
            except TimeoutException:
                self.logger.warning('VK feed probe timed out; checking loaded document')
            except Exception as exc:
                self.logger.warning('VK feed probe failed: %s', exc)
            try:
                self.wait_ready(timeout)
            except Exception:
                pass

            host_ok = any(h in (driver.current_url or '').lower() for h in ('vk.ru', 'vk.com', 'id.vk.ru'))
            login = self._looks_like_login(driver)
            signed = self.has_vk_session_cookie()
            try:
                body_len = len(driver.find_element(By.TAG_NAME, 'body').text.strip())
            except Exception:
                body_len = 0
            ok = host_ok and signed and not login and body_len > 20
            self.logger.info(
                'VK session probe: ok=%s signed_cookie=%s body=%s url=%s (before=%s)',
                ok, signed, body_len, driver.current_url, before)
            return ok

    def ensure_authenticated(self, timeout=180):
        if self.verify_authenticated(timeout=20):
            self.logger.info('Saved VK cookies are valid; using existing Firefox session')
            return True

        driver = self.open_for_auth()
        self.logger.info('No valid VK session found; waiting up to %s s for manual login in the SAME Firefox', timeout)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            time.sleep(1.0)
            try:
                if self.has_vk_session_cookie() and not self._looks_like_login(driver):
                    if self.verify_authenticated(timeout=20):
                        return True
            except Exception as exc:
                self.logger.warning('VK auth polling: %s', exc)
        return False

    def get(self):
        return self.start()

    def stop(self):
        with self.lock:
            if self._stopping:
                return
            self._stopping = True
            try:
                if self.driver:
                    try:
                        self.driver.quit()
                    except Exception as exc:
                        self.logger.warning('Firefox driver close: %s', exc)
                    finally:
                        self.driver = None
                        self.logger.info('Selenium disconnected; Firefox profile remains at %s', PROFILE)
            finally:
                self._stopping = False
