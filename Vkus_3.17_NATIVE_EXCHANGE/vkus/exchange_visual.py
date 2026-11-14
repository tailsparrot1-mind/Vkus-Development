from __future__ import annotations

import math
import tkinter.font as tkfont


def install_exchange_visuals():
    """Install the native Exchange renderer without changing search/data logic."""
    from .app import VkusApp
    VkusApp._exchange_redraw = _exchange_redraw


def _exchange_redraw(self, _event=None):
    """Draw the Vkus Exchange screen with native Tk Canvas primitives."""
    canvas = getattr(self, "exchange_canvas", None)
    if canvas is None:
        return

    w = max(1, canvas.winfo_width())
    h = max(1, canvas.winfo_height())
    scale = min(w / 1672.0, h / 941.0)
    rw, rh = int(1672 * scale), int(941 * scale)
    ox, oy = (w - rw) // 2, (h - rh) // 2
    self.exchange_geometry = (scale, ox, oy, rw, rh)
    canvas.delete("all")
    canvas.configure(bg="#030817")

    def X(value):
        return ox + value * scale

    def Y(value):
        return oy + value * scale

    def rounded(x1, y1, x2, y2, fill, outline="#203568", radius=14, width=1):
        radius = max(2, min(radius, (x2 - x1) / 4, (y2 - y1) / 4)) * scale
        points = []
        corners = (
            (X(x2) - radius, Y(y1) + radius, -90),
            (X(x2) - radius, Y(y2) - radius, 0),
            (X(x1) + radius, Y(y2) - radius, 90),
            (X(x1) + radius, Y(y1) + radius, 180),
        )
        for cx, cy, start in corners:
            for step in range(7):
                angle = math.radians(start + step * 15)
                points.extend((cx + radius * math.cos(angle),
                               cy + radius * math.sin(angle)))
        canvas.create_polygon(
            *points, fill=fill, outline=outline,
            width=max(1, int(width * scale)), smooth=True
        )

    font_cache = {}

    def label(x, y, value, size=14, color="#edf3ff", weight="normal",
              anchor="nw", width=None, justify="left", fit=False):
        font_size = max(7, int(size * scale))
        font_spec = ("DejaVu Sans", font_size, weight)
        if fit and width is not None and "\n" not in str(value):
            available = max(1, int(width * scale))
            while font_size > 7:
                key = (font_size, weight)
                if key not in font_cache:
                    font_cache[key] = tkfont.Font(
                        root=canvas, family="DejaVu Sans",
                        size=font_size, weight=weight
                    )
                if font_cache[key].measure(str(value)) <= available:
                    break
                font_size -= 1
            key = (font_size, weight)
            if key not in font_cache:
                font_cache[key] = tkfont.Font(
                    root=canvas, family="DejaVu Sans",
                    size=font_size, weight=weight
                )
            font_spec = font_cache[key]
        options = {
            "text": value, "anchor": anchor, "fill": color,
            "font": font_spec, "justify": justify,
        }
        if width is not None:
            options["width"] = max(1, int(width * scale))
        canvas.create_text(X(x), Y(y), **options)

    def rule(x1, y1, x2, y2, color="#1b2d58", width=1):
        canvas.create_line(X(x1), Y(y1), X(x2), Y(y2),
                           fill=color, width=max(1, int(width * scale)))

    def dot(x, y, radius, color, outline=""):
        canvas.create_oval(
            X(x - radius), Y(y - radius), X(x + radius), Y(y + radius),
            fill=color, outline=outline or color, width=max(1, int(scale))
        )

    def badge(x, y, text_value, color, fill="#0d1a38", width=1):
        rounded(x, y, x + 150, y + 27, fill, color, 13, width)
        label(x + 75, y + 6, text_value, 8, color, "bold", "n", width=142, fit=True)

    # Deep blue background with restrained native neon atmosphere.
    for index in range(48):
        t = index / 47
        r = int(3 + 5 * t)
        g = int(8 + 5 * t)
        b = int(22 + 20 * t)
        color = f"#{r:02x}{g:02x}{b:02x}"
        y1 = int(941 * index / 48)
        y2 = int(941 * (index + 1) / 48) + 1
        canvas.create_rectangle(X(0), Y(y1), X(1672), Y(y2),
                                fill=color, outline=color)
    rounded(7, 7, 1665, 934, "#050b1e", "#39206f", 23, 2)

    # Left brand rail and the exact supplied Vkus identity artwork.
    rounded(13, 13, 267, 928, "#070b22", "#49218f", 20, 1)
    reference = getattr(self, "exchange_reference", None)
    if not hasattr(self, "exchange_brand_photo"):
        self.exchange_brand_photo = None
        try:
            if reference is not None:
                from PIL import Image, ImageTk
                logo = reference.crop((28, 24, 238, 153)).convert("RGBA")
                pixels = logo.load()
                for py in range(logo.height):
                    for px in range(logo.width):
                        red, green, blue, alpha = pixels[px, py]
                        brightness = max(red, green, blue)
                        if brightness < 34:
                            pixels[px, py] = (red, green, blue, 0)
                        elif brightness < 70 and blue < 95:
                            pixels[px, py] = (red, green, blue, int((brightness - 34) * 7))
                resampling = getattr(Image, "Resampling", Image).LANCZOS
                self.exchange_brand_photo = ImageTk.PhotoImage(logo.resize((206, 126), resampling))
        except Exception:
            self.exchange_brand_photo = None
    if getattr(self, "exchange_brand_photo", None):
        canvas.create_image(X(30), Y(15), image=self.exchange_brand_photo, anchor="nw")
    else:
        label(38, 28, "♛", 36, "#bd76ff", "bold")
        label(84, 35, "Vkus", 35, "#f2edff", "bold")
    label(40, 141, "ПОИСК СПРОСА", 9, "#8295c7", "bold")
    rule(31, 164, 249, 164, "#28205b")
    if not hasattr(self, "exchange_tiger_photo"):
        self.exchange_tiger_photo = None
        try:
            if reference is not None:
                from PIL import Image, ImageTk
                tiger = reference.crop((17, 158, 260, 370)).convert("RGBA")
                pixels = tiger.load()
                for py in range(tiger.height):
                    for px in range(tiger.width):
                        red, green, blue, alpha = pixels[px, py]
                        if max(red, green, blue) < 22:
                            pixels[px, py] = (red, green, blue, 0)
                resampling = getattr(Image, "Resampling", Image).LANCZOS
                self.exchange_tiger_photo = ImageTk.PhotoImage(tiger.resize((238, 207), resampling))
        except Exception:
            self.exchange_tiger_photo = None
    if getattr(self, "exchange_tiger_photo", None):
        canvas.create_image(X(14), Y(166), image=self.exchange_tiger_photo, anchor="nw")

    nav_items = (
        ("☏", "Сообщения"),
        ("⌕", "Поиск"),
        ("⇄", "Биржа"),
        ("▥", "Мониторинг"),
        ("⚙", "Настройки"),
    )
    for index, (symbol, name) in enumerate(nav_items):
        top = 375 + index * 61
        active = name == "Биржа"
        if active:
            rounded(10, top - 2, 254, top + 55, "#24105b", "#9c35ff", 14, 3)
            rounded(13, top + 1, 251, top + 52, "#101c4a", "#168fe9", 12, 1)
        label(37, top + 12, symbol, 25,
              "#35dfff" if active else "#9c78ef", "bold")
        label(91, top + 17, name, 16,
              "#ffffff" if active else "#a9b7e5",
              "bold" if active else "normal")
    rounded(28, 728, 250, 855, "#0a1734", "#2d65aa", 17, 1)
    label(46, 746, "Ваш статус", 12, "#b7c8ed")
    dot(54, 774, 7, "#11e8b4")
    label(70, 761, "Активен", 15, "#00e5b4", "bold")
    rule(44, 800, 232, 800, "#20365f")
    label(46, 809, "Vkus 3.17", 14, "#dce7ff", "bold")
    label(46, 835, "Биржа спроса", 10, "#a6b6dc")
    label(36, 884, "Vkus 3.17", 12, "#8b9cc8")

    # Header and compact custom window controls.
    label(306, 43, "Биржа спроса и предложений", 38, "#cf74ff", "bold",
          width=1000, fit=True)
    label(307, 105,
          "Находите клиентов, исполнителей и актуальные задачи рядом с вами",
          18, "#e4eaff", width=980, fit=True)
    dot(1372, 42, 5, "#20e66c")
    label(1386, 30, "Онлайн", 13, "#49ed82", "bold", width=70, fit=True)
    rule(1464, 27, 1464, 57, "#543a87", 1)
    rule(1494, 42, 1513, 42, "#a78aff", 2)
    rounded(1544, 32, 1562, 50, "", "#a78aff", 2, 2)
    rule(1590, 33, 1608, 51, "#a78aff", 2)
    rule(1608, 33, 1590, 51, "#a78aff", 2)
    label(1445, 82, "Спрос есть.", 18, "#bd6cff", "bold", width=190, fit=True)
    label(1445, 109, "Найдём вместе!", 18, "#bd6cff", "bold", width=190, fit=True)
    rule(1464, 143, 1606, 143, "#7432bc", 2)

    # Five neon KPI cards. Values remain empty until real sources connect.
    metrics = (
        ("♙", "Заявки", "—", "Люди ищут услуги и решения", "#9b42ff"),
        ("▣", "Специалисты", "—", "Предлагают услуги и ищут заказы", "#18bfff"),
        ("◎", "Новые задачи", "—", "Разовые задания и подработка", "#b34bff"),
        ("▥", "Анализ спроса", "—", "Актуальные данные из источников", "#13dfb6"),
        ("☆", "Релевантность", "—", "Точные результаты по запросам", "#ffbf43"),
    )
    for index, (icon, title, value, description, accent) in enumerate(metrics):
        left = 300 + index * 264
        right = left + 245
        rounded(left - 2, 168, right + 2, 347, "#080f27", accent, 20, 2)
        rounded(left, 170, right, 345, "#0a1531", accent, 18, 1)
        dot(left + 43, 217, 24, accent)
        label(left + 43, 194, icon, 31, "#ffffff", "bold", "n")
        label(left + 97, 198, title, 14, "#edf3ff", "bold", width=130, fit=True)
        label(left + 97, 235, value, 27, "#ffffff", "bold")
        rule(left + 20, 283, right - 20, 283, "#263d76")
        label(left + 23, 295, description, 10, "#a9b9df",
              width=200, justify="center")

    # Smart search panel with a bright blue perimeter.
    rounded(297, 370, 1348, 559, "", "#185fbd", 22, 3)
    rounded(300, 373, 1345, 556, "#091633", "#3866bd", 20, 1)
    label(323, 388, "⌕", 35, "#20caff", "bold")
    label(373, 394, "Умный поиск", 23, "#f2f5ff", "bold")
    label(1137, 402, "Расширенный поиск  ⌄", 15, "#38aaff",
          width=190, fit=True)
    rounded(320, 435, 1165, 488, "#071129", "#405a91", 12, 1)
    entry = getattr(self, "exchange_entry", None)
    if entry is not None:
        entry.place(x=X(332), y=Y(441),
                    width=max(20, X(1150) - X(332)),
                    height=max(18, Y(482) - Y(441)))
        entry.configure(
            font=("DejaVu Sans", max(9, int(13 * scale))),
            bg="#071129", fg="#a9badc",
            insertbackground="#ffffff", relief="flat",
            highlightthickness=0, bd=0
        )
    rounded(1178, 435, 1325, 488, "#5420a3", "#a65aff", 12, 1)
    label(1251, 449, "⌕  Найти", 13, "#ffffff", "bold", "n")

    # Filter controls.
    label(320, 502, "ПАРАМЕТРЫ ПОИСКА", 8, "#849ac8", "bold")
    filters = (
        ("⌖", getattr(self, "exchange_city", "Оренбург"), 320, 478),
        ("◉", "Радиус: " + getattr(self, "exchange_radius", "50 км"), 490, 684),
        ("◷", getattr(self, "exchange_period", "За всё время"), 696, 889),
        ("▤", getattr(self, "exchange_category", "Все категории"), 901, 1094),
    )
    for symbol, value, left, right in filters:
        rounded(left, 518, right, 548, "#0a1734", "#293e70", 10, 1)
        label(left + 10, 525, symbol, 11, "#a6b9e8", "bold")
        label(left + 31, 526, value + "  ⌄", 9, "#dce6fb", width=right-left-42, fit=True)

    # Source selectors with brand-specific wordmarks and a neon Avito selection.
    label(307, 572, "◎  Источники поиска", 17, "#f0f4ff", "bold")
    sources = (
        ("VK", "vk", "#2788ff"),
        ("Telegram", "➤", "#31bdf5"),
        ("Avito", "avito", "#f18b42"),
        ("YouDo", "youdo", "#f4f5ff"),
        ("Профи.ру", "ПРОФИ", "#ff647e"),
        ("Форумы", "◎", "#9b8cff"),
    )
    selected = getattr(self, "exchange_sources_selected", set())
    for index, (name, wordmark, accent) in enumerate(sources):
        left = 301 + index * 147
        active = name in selected
        if active:
            rounded(left - 3, 607, left + 135, 694, "#0b1233", "#d344ff", 18, 3)
            rounded(left, 610, left + 132, 691, "#17183b", "#2488ec", 16, 1)
        else:
            rounded(left, 610, left + 132, 691, "#09132e", "#293c78", 16, 1)
        if name == "VK":
            dot(left + 66, 632, 15, "#1677e8")
            label(left + 66, 621, "vk", 14, "#ffffff", "bold", "n")
        elif name == "Telegram":
            dot(left + 66, 632, 15, "#159ed3")
            label(left + 66, 620, "➤", 15, "#ffffff", "bold", "n")
        elif name == "Avito":
            for dx, color in ((-8, "#ffb04e"), (0, "#e84f78"), (8, "#58b9ef")):
                dot(left + 66 + dx, 632, 5, color)
        elif name == "YouDo":
            label(left + 66, 620, "youdo", 13, "#f4f5ff", "bold", "n")
        elif name == "Профи.ру":
            label(left + 66, 620, "П", 20, "#ff647e", "bold", "n")
        else:
            label(left + 66, 619, "◎", 22, "#9b8cff", "bold", "n")
        label(left + 66, 658, name, 10, "#edf2ff", "bold", "n", width=116, fit=True)
        label(left + 66, 674, "ВЫБРАН" if active else "НЕ ПОДКЛЮЧЁН",
              6, accent if active else "#7185b1", "bold", "n", width=116, fit=True)

    rounded(1185, 610, 1343, 691, "#09132e", "#344d91", 16, 1)
    label(1264, 625, "+", 30, "#a8c4ff", "bold", "n")
    label(1264, 665, "Ещё 5", 13, "#eef2ff", "bold", "n")
    label(1264, 680, "скоро", 8, "#8298c4", "normal", "n")

    # Right-hand discovery panel, aligned with the search module.
    rounded(1360, 373, 1618, 702, "#0b1430", "#8e39e7", 18, 1)
    label(1384, 393, "▥  Что можно найти?", 17, "#f2f5ff", "bold",
          width=210, fit=True)
    categories = (
        "Заявки на услуги и ремонт",
        "Разовые задачи и подработка",
        "Вакансии и работу",
        "Товары и предложения",
        "Потребность в помощи и специалистах",
    )
    selected_categories = getattr(self, "exchange_categories_selected", set())
    for index, category in enumerate(categories):
        top = 438 + index * 39
        checked = category in selected_categories
        dot(1397, top + 9, 9, "#0c4c4a" if checked else "#10213d",
            "#13e3b2" if checked else "#405078")
        if checked:
            label(1397, top + 1, "✓", 12, "#13e3b2", "bold", "n")
        label(1417, top + 1, category, 11, "#dce6ff",
              width=182, fit=True)
    rounded(1372, 631, 1607, 688, "#21104d", "#9c35ff", 12, 1)
    label(1390, 643, "ϟ", 28, "#d98cff", "bold")
    label(1425, 640, "Vkus анализирует", 12, "#d98cff", "bold")
    label(1425, 662, "после подключения источников", 9,
          "#e2d9ff", width=170, fit=True)

    # Lower information area — honest empty states, no invented leads or map stats.
    rounded(300, 716, 855, 891, "#09152f", "#2b416f", 15, 1)
    label(322, 735, "ПОСЛЕДНИЕ НАХОДКИ", 9, "#9db3e3", "bold")
    dot(345, 800, 18, "#10274b")
    label(345, 789, "⌕", 19, "#46cfff", "bold", "n")
    label(377, 779, "Здесь появятся найденные публикации", 10,
          "#e1eaff", "bold", width=420, fit=True)
    label(377, 802, "после подключения поисковых источников", 9,
          "#8299c6", width=420, fit=True)
    badge(322, 847, "ОЖИДАЕТ ДАННЫХ", "#6f94c8", "#0c1b37")

    rounded(870, 716, 1332, 891, "#09152f", "#2b416f", 15, 1)
    label(892, 735, "РЕГИОНЫ И АКТИВНОСТЬ", 9, "#9db3e3", "bold")
    # Native abstract map-grid placeholder, not a fake activity chart.
    for gx in range(5):
        rule(902 + gx * 72, 776, 902 + gx * 72, 850, "#172c51")
    for gy in range(3):
        rule(902, 776 + gy * 37, 1190, 776 + gy * 37, "#172c51")
    label(1047, 813, "КАРТА ПОЯВИТСЯ ПОСЛЕ ПОИСКА", 8,
          "#8299c6", "bold", "center", width=270, fit=True)

    rounded(1347, 716, 1618, 891, "#09152f", "#2b416f", 15, 1)
    label(1368, 735, "АНАЛИЗ СПРОСА", 9, "#9db3e3", "bold")
    for index, title in enumerate((
        "Определение намерения",
        "Подбор направления",
        "Оценка релевантности",
        "Новые заявки",
    )):
        top = 774 + index * 26
        dot(1376, top + 7, 3, "#26d9b6")
        label(1388, top, title, 8, "#cbd8f2")

    # Bottom status strip.
    rule(300, 904, 1618, 904, "#24345f")
    dot(315, 920, 3, "#e9b85a")
    label(326, 913, "Источники: ожидают подключения", 8, "#8fa4ce", width=380, fit=True)
    label(1020, 913, "Данные и статистика появятся после интеграции", 8,
          "#7188b6", "normal", "center", width=540, fit=True)
    label(1599, 913, "VKUS 3.17", 8, "#9b83c9", "bold", "ne")

    self.exchange_hit_scale = scale
