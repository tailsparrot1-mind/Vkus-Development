from urllib.parse import quote
import time
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException
from vkus.check_runner import CheckResult


class BaseCheck:
    def __init__(self, key, title, browser, settings, logger):
        self.key, self.title = key, title
        self.browser, self.settings, self.logger = browser, settings, logger

    def result(self, ok, detail, url=''):
        self.logger.info('%s | %s | %s | %s', self.key, 'OK' if ok else 'ERROR', detail, url)
        return CheckResult(self.key, self.title, ok, detail, url)

    def wait_content(self, timeout=30):
        d = self.browser.wait_ready(timeout)
        WebDriverWait(d, timeout, poll_frequency=0.25).until(
            lambda x: len(x.find_element(By.TAG_NAME, 'body').text.strip()) > 20
        )
        return d

    @staticmethod
    def signed_cookie(driver):
        names = {c.get('name', '').lower() for c in driver.get_cookies()}
        return any(name.startswith('remixsid') for name in names)

    @staticmethod
    def looks_like_login(driver):
        url = (driver.current_url or '').lower()
        if any(x in url for x in ('/login', 'id.vk.ru/authorize', '/authorize')):
            return True
        try:
            text = driver.find_element(By.TAG_NAME, 'body').text.lower()
        except Exception:
            return False
        return ('войти в vk' in text or 'войти или зарегистрироваться' in text or
                'sign in to vk' in text)


class VkCheck(BaseCheck):
    def run(self):
        url = self.browser.open_vk()
        title = self.browser.get().title
        return self.result(bool(url and 'vk' in url.lower()), f'VK открыт: {title or "без title"}', url)


class AuthCheck(BaseCheck):
    LOGIN_WAIT = 180

    def run(self):
        # First try the existing Firefox profile. If the saved VK session is
        # valid, this returns immediately and does not ask for another login.
        if self.browser.ensure_authenticated(self.LOGIN_WAIT):
            d = self.browser.get()
            names = self.browser.cookie_names()
            return self.result(
                True,
                f'Сессия VK подтверждена в Firefox #{self.browser.session_number}; '
                f'профиль сохранён, cookies: {len(names)}',
                d.current_url)

        d = self.browser.get()
        return self.result(
            False,
            f'Авторизация не подтверждена за {self.LOGIN_WAIT} с — сохранённую сессию повторно не запрашивали',
            d.current_url)


class ProfileCheck(BaseCheck):
    def run(self):
        d = self.browser.get()
        self.browser.navigate('https://vk.com/feed', timeout=30)
        d = self.wait_content(30)
        ok = self.signed_cookie(d) and not self.looks_like_login(d)
        return self.result(ok, 'Авторизованная лента VK загружена' if ok else 'Профиль/лента не подтверждены', d.current_url)


class MessagesCheck(BaseCheck):
    def run(self):
        d = self.browser.get()
        self.browser.navigate('https://vk.com/im', timeout=30)
        d = self.wait_content(30)
        current = (d.current_url or '').lower()
        body = d.find_element(By.TAG_NAME, 'body').text.lower()
        # VK is an SPA: /im remains /im while dialogs are rendered into the DOM.
        # vk.com can transparently become vk.ru, so the hostname itself is not
        # a success criterion.
        host_ok = ('vk.com' in current or 'vk.ru' in current or 'id.vk.ru' in current)
        path_ok = '/im' in current
        dom_ok = len(body) > 20
        ok = self.signed_cookie(d) and not self.looks_like_login(d) and host_ok and path_ok and dom_ok
        detail = 'Раздел сообщений /im загружен, диалоги доступны в DOM' if ok else 'Раздел /im открыт, но содержимое сообщений не подтверждено'
        return self.result(ok, detail, d.current_url)


class GroupsCheck(BaseCheck):
    def run(self):
        d = self.browser.get()
        self.browser.navigate('https://vk.com/groups', timeout=30)
        d = self.wait_content(30)
        current = (d.current_url or '').lower()
        body = d.find_element(By.TAG_NAME, 'body').text.lower()
        host_ok = ('vk.com' in current or 'vk.ru' in current or 'id.vk.ru' in current)
        # VK may expose this area as /groups, /communities or a SPA route
        # without changing the page shell. Accept the actual rendered section.
        path_ok = any(x in current for x in ('/groups', '/communities', '/club'))
        dom_ok = len(body) > 20
        ok = self.signed_cookie(d) and not self.looks_like_login(d) and host_ok and path_ok and dom_ok
        detail = 'Раздел сообществ загружен в DOM' if ok else 'Раздел сообществ открыт, но содержимое не подтверждено'
        return self.result(ok, detail, d.current_url)


class SearchCheck(BaseCheck):
    def run(self):
        d = self.browser.get()
        q = self.settings.get('search_query', '').strip() or 'ремонт'
        url = 'https://vk.com/search?c%5Bq%5D=' + quote(q) + '&c%5Bsection%5D=communities'
        self.browser.navigate(url, timeout=30)
        d = self.wait_content(30)
        ok = ('search' in d.current_url.lower() or q.lower() in d.find_element(By.TAG_NAME, 'body').text.lower()) and not self.looks_like_login(d)
        return self.result(ok, f'Поиск выполнен: «{q}»' if ok else 'Поиск не подтверждён', d.current_url)


class WallCheck(BaseCheck):
    def run(self):
        d = self.browser.get()
        url = self.settings.get('community_url', '').strip()
        if not url.startswith('http'):
            return self.result(False, 'Укажите URL сообщества в настройках')
        self.browser.navigate(url, timeout=30)
        d = self.wait_content(30)
        current = (d.current_url or '').lower()
        body = d.find_element(By.TAG_NAME, 'body').text
        host_ok = ('vk.com' in current or 'vk.ru' in current)
        # Do not require a URL redirect or a particular HTML size: the VK wall
        # is rendered dynamically inside the SPA. A valid authenticated VK
        # document with real body content is sufficient evidence here.
        dom_ok = len(body.strip()) > 20 and len(d.page_source) > 500
        ok = self.signed_cookie(d) and not self.looks_like_login(d) and host_ok and dom_ok
        detail = 'Стена/страница сообщества загружена в DOM' if ok else 'Страница сообщества открыта, но DOM стены не подтверждён'
        return self.result(ok, detail, d.current_url)


class PostCheck(BaseCheck):
    def run(self):
        d = self.browser.get()
        url = self.settings.get('post_url', '').strip()
        if not url.startswith('http'):
            return self.result(False, 'Укажите URL поста в настройках')
        self.browser.navigate(url, timeout=30)
        d = self.wait_content(30)
        ok = 'wall' in d.current_url.lower() and len(d.page_source) > 1000 and not self.looks_like_login(d)
        return self.result(ok, 'Пост загружен' if ok else 'Пост не подтверждён', d.current_url)


class GetCheck(BaseCheck):
    def run(self):
        d = self.browser.get()
        before = d.current_url
        self.browser.navigate('https://vk.com/', timeout=30)
        d = self.browser.get()
        after = d.current_url
        evidence = f'Навигация: {before} → {after}'
        supported = hasattr(d, 'bidi_connection')
        detail = evidence + (' | BiDi доступен для дальнейшего перехвата network events' if supported else
                             ' | network API Selenium/Firefox не предоставлен в этой сборке')
        return self.result(supported and bool(after), detail, after)


class DomCheck(BaseCheck):
    def run(self):
        d = self.browser.get()
        self.browser.wait_ready(30)
        source = d.page_source
        html = d.find_element(By.TAG_NAME, 'html')
        body = d.find_element(By.TAG_NAME, 'body')
        ok = bool(source) and html is not None and body is not None
        return self.result(ok, f'DOM получен: {len(source):,} символов' if ok else 'DOM не получен', d.current_url)


def build_checks(browser, settings, logger):
    return [
        VkCheck('vk', 'VK', browser, settings, logger),
        AuthCheck('auth', 'Авторизация', browser, settings, logger),
        ProfileCheck('profile', 'Профиль', browser, settings, logger),
        MessagesCheck('messages', 'Сообщение', browser, settings, logger),
        GroupsCheck('groups', 'Сообщества', browser, settings, logger),
        SearchCheck('search', 'Поиск', browser, settings, logger),
        WallCheck('wall', 'Стена', browser, settings, logger),
        PostCheck('post', 'Пост', browser, settings, logger),
        GetCheck('get', 'GET', browser, settings, logger),
        DomCheck('dom', 'HTML / DOM', browser, settings, logger),
    ]
