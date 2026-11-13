from __future__ import annotations

import math


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

    def label(x, y, value, size=14, color="#edf3ff", weight="normal",
              anchor="nw", width=None, justify="left"):
        options = {
            "text": value, "anchor": anchor, "fill": color,
            "font": ("DejaVu Sans", max(7, int(size * scale)), weight),
            "justify": justify,
        }
        if width is not None:
            options["width"] = width * scale
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
        rounded(x, y, x + 112, y + 27, fill, color, 13, width)
        label(x + 56, y + 6, text_value, 10, color, "bold", "n")

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

    # Left brand rail.
    rounded(13, 13, 267, 928, "#070d25", "#30205f", 20, 1)
    label(38, 25, "♛", 36, "#bd76ff", "bold")
    label(84, 35, "Vkus", 35, "#f2edff", "bold")
    label(40, 91, "ПОИСК СПРОСА", 9, "#8295c7", "bold")
    rule(31, 119, 249, 119, "#1e2c58")
    # Tiger is the only retained raster decoration; all surrounding UI is native.
    if not hasattr(self, "exchange_tiger_photo"):
        try:
            reference = getattr(self, "exchange_reference", None)
            if reference is not None:
                try:
                    resampling = __import__("PIL.Image", fromlist=["Resampling"]).Resampling.LANCZOS
                except Exception:
                    from PIL import Image
                    resampling = Image.LANCZOS
                tiger = reference.crop((24, 165, 260, 370)).resize((188, 164), resampling)
                from PIL import ImageTk
                self.exchange_tiger_photo = ImageTk.PhotoImage(tiger)
            else:
                self.exchange_tiger_photo = None
        except Exception:
            self.exchange_tiger_photo = None
    if getattr(self, "exchange_tiger_photo", None):
        canvas.create_image(X(46), Y(129), image=self.exchange_tiger_photo, anchor="nw")

    nav_items = (
        ("●", "Сообщения"),
        ("⌕", "Поиск"),
        ("⇄", "Биржа"),
        ("▥", "Мониторинг"),
        ("⚙", "Настройки"),
    )
    for index, (symbol, name) in enumerate(nav_items):
        top = 322 + index * 59
        active = name == "Биржа"
        if active:
            rounded(22, top, 254, top + 49, "#211044", "#9b4dff", 13, 2)
        label(43, top + 11, symbol, 21,
              "#40d9ff" if active else "#9a78db", "bold")
        label(82, top + 15, name, 14,
              "#ffffff" if active else "#a9b7d8",
              "bold" if active else "normal")
    rounded(28, 640, 250, 802, "#0a1833", "#254a79", 14, 1)
    label(45, 657, "ВАШ СТАТУС", 9, "#8da6d8", "bold")
    dot(51, 690, 4, "#15e2b2")
    label(64, 681, "Активен", 14, "#d8fff5", "bold")
    rule(44, 715, 232, 715, "#20365f")
    label(45, 731, "Vkus 3.17", 12, "#b9c9eb", "bold")
    label(45, 756, "Биржа спроса", 10, "#788db9")

    # Header.
    label(300, 34, "Биржа спроса и предложений", 32, "#d78aff", "bold")
    label(302, 88,
          "Находите клиентов, исполнителей и актуальные задачи рядом с вами",
          14, "#c7d5f4")
    dot(1434, 43, 4, "#19e6a7")
    label(1447, 35, "ИНТЕРФЕЙС АКТИВЕН", 9, "#72e9c7", "bold")
    label(1444, 76, "Спрос есть.", 15, "#c58aff", "bold")
    label(1444, 98, "Найдём вместе!", 15, "#c58aff", "bold")

    # Five metric cards: retain hierarchy, never fabricate connected statistics.
    metrics = (
        ("01", "Заявки", "—", "Ожидают подключения источников", "#a65cff"),
        ("02", "Специалисты", "—", "Ожидают подключения источников", "#29bfff"),
        ("03", "Новые задачи", "—", "Ожидают подключения источников", "#d15cff"),
        ("04", "Анализ спроса", "—", "Рассчитывается после поиска", "#1eddb8"),
        ("05", "Релевантность", "—", "Рассчитывается по запросу", "#f4bd55"),
    )
    for index, (number, title, value, description, accent) in enumerate(metrics):
        left = 300 + index * 264
        right = left + 246
        rounded(left, 145, right, 315, "#0b1632", "#263c70", 16, 1)
        rounded(left + 1, 146, right - 1, 150, accent, accent, 2, 1)
        label(left + 17, 165, number, 9, accent, "bold")
        label(left + 17, 188, title, 13, "#e9efff", "bold")
        label(left + 17, 222, value, 31, "#ffffff", "bold")
        rule(left + 17, 269, right - 17, 269, "#20335f")
        label(left + 17, 281, description, 8, "#94a8d1", width=210)

    # Smart search panel. Keep the original hit-box coordinates.
    rounded(300, 337, 1345, 556, "#091632", "#263f79", 17, 1)
    label(322, 353, "⌕", 28, "#36cfff", "bold")
    label(366, 359, "Умный поиск", 19, "#f1f4ff", "bold")
    label(1138, 367, "РАСШИРЕННЫЙ ПОИСК  ⌄", 9, "#54baff", "bold")
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
        label(left + 31, 526, value + "  ⌄", 9, "#dce6fb")

    # Source selectors with brand-specific native wordmarks.
    label(303, 575, "ИСТОЧНИКИ ПОИСКА", 9, "#8da2d1", "bold")
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
        rounded(left, 602, left + 132, 688,
                "#17183b" if active else "#09142e",
                "#a94cff" if active else "#273b6d",
                14, 2 if active else 1)
        if active:
            rounded(left + 8, 610, left + 124, 614, accent, accent, 2, 1)
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
        label(left + 66, 658, name, 10, "#edf2ff", "bold", "n")
        label(left + 66, 674, "ВЫБРАН" if active else "ДОСТУПЕН",
              6, accent if active else "#7185b1", "bold", "n")

    rounded(1185, 602, 1343, 688, "#09142e", "#293e70", 14, 1)
    label(1264, 615, "+", 23, "#b9caff", "bold", "n")
    label(1264, 653, "Ещё источники", 8, "#c6d4f1", "bold", "n")
    label(1264, 670, "скоро", 7, "#8298c4", "normal", "n")

    # Right-hand category panel with real checkbox visuals, not a screenshot.
    rounded(1360, 337, 1618, 702, "#0b1632", "#55358e", 17, 1)
    label(1382, 356, "ЧТО ИЩЕМ", 10, "#d5c4ff", "bold")
    label(1382, 377, "Типы объявлений", 14, "#f0f3ff", "bold")
    rule(1382, 405, 1596, 405, "#26375f")
    categories = (
        "Заявки на услуги и ремонт",
        "Разовые задачи и подработка",
        "Вакансии и работа",
        "Товары и предложения",
        "Поиск помощи и специалистов",
    )
    for index, category in enumerate(categories):
 top = 423 + index * 43
        rounded(1383, top + 3, 1400, top + 20,
                "#102b43", "#24c9e7", 4, 1)
        # Check state is visual-only until category filtering is implemented.
        label(1391, top + 2, "✓", 10, "#43e7cb", "bold", "n")
        label(1412, top + 2, category, 8, "#d6e1f8", "normal",
 width=180)
    rounded(1381, 653, 1597, 685, "#211443", "#7340a9", 9, 1)
    label(1393, 661, "Источники пока не подключены", 8, "#d7b7ff", "bold")

    # Lower information area — honest empty states, no invented leads or map stats.
    rounded(300, 716, 855, 891, "#09152f", "#2b416f", 15, 1)
    label(322, 735, "ПОСЛЕДНИЕ НАХОДКИ", 9, "#9db3e3", "bold")
    dot(345, 800, 18, "#10274b")
    label(345, 789, "⌕", 19, "#46cfff", "bold", "n")
    label(377, 779, "Здесь появятся найденные публикации", 10,
          "#e1eaff", "bold", width=420)
    label(377, 802, "после подключения поисковых источников", 9,
          "#8299c6", width=420)
    badge(322, 847, "ОЖИДАЕТ ДАННЫХ", "#6f94c8", "#0c1b37")

    rounded(870, 716, 1332, 891, "#09152f", "#2b416f", 15, 1)
    label(892, 735, "РЕГИОНЫ И АКТИВНОСТЬ", 9, "#9db3e3", "bold")
    # Native abstract map-grid placeholder, not a fake activity chart.
    for gx in range(5):
        rule(902 + gx * 72, 776, 902 + gx * 72, 850, "#172c51")
    for gy in range(3):
        rule(902, 776 + gy * 37, 1190, 776 + gy * 37, "#172c51")
    label(1047, 813, "КАРТА ПОЯВИТСЯ ПОСЛЕ ПОИСКА", 8,
          "#8299c6", "bold", "center")

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
    label(326, 913, "Источники: ожидают подключения", 8, "#8fa4ce")
    label(1020, 913, "Данные и статистика появятся после интеграции", 8,
          "#7188b6", "normal", "center")
    label(1599, 913, "VKUS 3.17", 8, "#9b83c9", "bold", "ne")

 self.exchange_hit_scale = scale
