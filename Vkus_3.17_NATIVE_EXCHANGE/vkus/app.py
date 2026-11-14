import json
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime
from pathlib import Path

from vkus.browser import BrowserManager
from vkus.checks import build_checks
from vkus.check_runner import CheckRunner, CheckResult
from vkus.storage import load_settings, save_settings, setup_logging
from vkus.lock_screen import LockScreen
from vkus.splash import SplashScreen

try:
    from PIL import Image, ImageTk, ImageEnhance
except Exception:
    Image = ImageTk = ImageEnhance = None

BG = '#00030a'
PANEL = '#01050d'
PANEL2 = '#020914'
BORDER = '#0a2f67'
TEXT = '#eef5ff'
MUTED = '#58759f'
CYAN = '#16d9ff'
PURPLE = '#b02cff'
GREEN = '#16f0a1'
PINK = '#ff18e8'
BLUE = '#176dff'
RED = '#ff4f68'
WHITE = '#cfe3ff'


class GradientButton(tk.Canvas):
    def __init__(self, master, text, command, height=48, **kw):
        super().__init__(master, height=height, highlightthickness=0, bd=0, bg=BG, **kw)
        self.command = command
        self.text = text
        self.bind('<Button-1>', lambda e: command())
        self.bind('<Enter>', lambda e: self.itemconfig('label', fill='white'))
        self.bind('<Leave>', lambda e: self.itemconfig('label', fill=TEXT))
        self.bind('<Configure>', self.draw)

    def draw(self, _=None):
        self.delete('all')
        w = max(2, self.winfo_width())
        h = self.winfo_height()
        steps = max(1, w // 4)
        for i in range(steps):
            t = i / max(1, steps - 1)
            r = int(24 + (168 - 24) * t)
            g = int(215 + (60 - 215) * t)
            self.create_rectangle(i * 4, 0, i * 4 + 5, h, fill=f'#{r:02x}{g:02x}ff', outline='')
        self.create_text(w / 2, h / 2, text=self.text, fill=TEXT,
                         font=('TkDefaultFont', 11, 'bold'), tags='label')


class NeonMessageButton(tk.Canvas):
    def __init__(self, master, text, command, width=150, height=34, **kw):
        super().__init__(master, width=width, height=height, highlightthickness=0,
                         bd=0, bg=PANEL2, cursor='hand2', **kw)
        self.command = command
        self.text = text
        self.bind('<Button-1>', lambda e: command())
        self.bind('<Enter>', self._hover)
        self.bind('<Leave>', self._leave)
        self.bind('<Configure>', self.draw)

    def _hover(self, _=None):
        self._hot = True
        self.draw()

    def _leave(self, _=None):
        self._hot = False
        self.draw()

    def draw(self, _=None):
        self.delete('all')
        w = max(20, self.winfo_width())
        h = max(20, self.winfo_height())
        hot = getattr(self, '_hot', False)
        # Saturated reference-style neon button: magenta -> blue core with cyan edge.
        for pad, color in ((0, '#7d20ff'), (1, '#8c24ff'), (2, '#16d9ff')):
            self.create_rectangle(pad, pad, w-pad-1, h-pad-1, outline=color, width=2)
        steps=max(1, w//5)
        for i in range(steps):
            t=i/max(1,steps-1)
            r=int(175*(1-t)+15*t); g=int(35*(1-t)+155*t); b=255
            self.create_rectangle(4+i*5, 5, 9+i*5, h-6, fill=f'#{r:02x}{g:02x}{b:02x}', outline='')
        if hot:
            self.create_rectangle(5, 5, w-6, h-6, outline='#ffffff', width=1)
        self.create_text(w/2, h/2, text=self.text, fill='#ffffff',
                         font=('TkDefaultFont', 8, 'bold'), tags='label')


class VkusApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title('Vkus — VK client search')
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        width = max(1100, sw - 30)
        height = max(680, sh - 55)
        self.root.geometry(f'{width}x{height}')
        self.root.minsize(1000, 620)
        self.root.configure(bg=BG)
        self.settings = load_settings()
        self.logger = setup_logging()
        self.browser = BrowserManager(self.logger)
        self.checks = build_checks(self.browser, self.settings, self.logger)
        self.by_key = {c.key: c for c in self.checks}
        self.status = {c.key: None for c in self.checks}
        self.rows = {}
        self.log_lines = []
        self.message_contacts = self._load_message_contacts()
        self.chat_history = self._load_chat_history()
        self.search_results = self._load_search_results()
        self.chat_window = None
        self._search_generation = 0
        self._search_running = False
        self.setup_page = None
        self.search_page = None
        self.messages_page = None
        self.exchange_page = None
        self.community_picker = None
        self.community_results = []
        self.splash = None
        self.root.withdraw()
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        self._show_lock()

    def _show_lock(self):
        self.root.deiconify()
        # Do not force WM "zoomed": on Kali/VMware that can exceed the usable
        # desktop and hide the right panel. Use the calculated geometry above.
        asset = Path(__file__).resolve().parent.parent / 'assets' / 'panther_lock.png'
        self.lock = LockScreen(self.root, self.settings, asset, self._unlock, self.close,
                               lambda data: save_settings(data))

    def _unlock(self):
        if getattr(self, 'lock', None) is not None:
            try:
                self.lock.dispose()
            except Exception:
                try:
                    if self.lock.canvas is not None and self.lock.canvas.winfo_exists():
                        self.lock.canvas.destroy()
                except Exception:
                    pass
            self.lock = None
        self._build_style()
        self.root.bind_all('<MouseWheel>', self._global_results_wheel, add='+')
        self.root.bind_all('<Button-4>', self._global_results_wheel, add='+')
        self.root.bind_all('<Button-5>', self._global_results_wheel, add='+')
        splash = Path(__file__).resolve().parent.parent / 'assets' / SplashScreen.VIDEO_FILENAME
        self.splash = SplashScreen(self.root, splash, self._build_ui)
        self.splash.start()

    def _build_style(self):
        s = ttk.Style(self.root)
        s.theme_use('clam')
        s.configure('TEntry', fieldbackground='#07162d', foreground=TEXT,
                    insertcolor=TEXT, bordercolor='#07162d', lightcolor='#07162d', darkcolor='#07162d',
                    borderwidth=0, relief='flat', padding=6)
        s.configure('TCombobox', fieldbackground='#07162d', foreground=TEXT,
                    background='#07162d', arrowcolor=CYAN, bordercolor='#07162d',
                    lightcolor='#07162d', darkcolor='#07162d', borderwidth=0, relief='flat', padding=4)
        s.map('TCombobox', fieldbackground=[('readonly', '#07162d')],
              foreground=[('readonly', TEXT)], bordercolor=[('focus', '#07162d'), ('active', '#07162d')],
              lightcolor=[('focus', '#07162d')], darkcolor=[('focus', '#07162d')])
        s.configure('Vkus.Vertical.TScrollbar', troughcolor='#020713', background='#12345c', bordercolor='#020713', arrowcolor='#16d9ff', relief='flat', borderwidth=0, width=10)
        s.map('Vkus.Vertical.TScrollbar', background=[('active', '#1b5a8f')])

    def _add_neon_background(self, parent):
        """Place the reference neon PNG behind the application content.
        This is the main application background; the lock screen keeps its
        separate panther_lock.png asset.
        """
        canvas = tk.Canvas(parent, bg=BG, highlightthickness=0, bd=0)
        canvas.place(relx=0, rely=0, relwidth=1, relheight=1)
        asset = Path(__file__).resolve().parent.parent / 'assets' / 'neon_lion_desktop.png'
        canvas._bg_source = None
        canvas._bg_photo = None
        if Image is not None and asset.exists():
            try:
                canvas._bg_source = Image.open(asset).convert('RGB')
                def redraw(_=None):
                    w = max(1, canvas.winfo_width())
                    h = max(1, canvas.winfo_height())
                    # Cover the available area, preserving aspect ratio.
                    src = canvas._bg_source
                    scale = max(w / src.width, h / src.height)
                    size = (max(1, int(src.width * scale)), max(1, int(src.height * scale)))
                    img = src.resize(size, Image.LANCZOS)
                    left = max(0, (img.width - w) // 2)
                    top = max(0, (img.height - h) // 2)
                    img = img.crop((left, top, left + w, top + h))
                    # Keep the reference saturated while slightly deepening it
                    # so dark glass panels remain readable.
                    img = ImageEnhance.Brightness(img).enhance(0.92) if ImageEnhance else img
                    canvas._bg_photo = ImageTk.PhotoImage(img)
                    canvas.delete('bg')
                    canvas.create_image(0, 0, image=canvas._bg_photo, anchor='nw', tags='bg')
                    canvas.tag_lower('bg')
                canvas.bind('<Configure>', redraw)
                canvas.after(20, redraw)
            except Exception:
                pass
        # Keep the PNG strictly as a background layer. Raising it above the widgets
        # would cover the whole application (which is what the previous build did).
        canvas.tk.call('lower', canvas._w)
        return canvas

    def _build_ui(self):
        self._header()
        body = tk.Frame(self.root, bg=BG)
        body.pack(fill='both', expand=True)
        self._add_neon_background(body)
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(1, weight=1)
        body.grid_columnconfigure(2, weight=0)
        self.body = body
        self._sidebar(body)
        self.main = tk.Frame(body, bg=BG)
        self.main.grid(row=0, column=1, sticky='nsew', padx=(10, 10), pady=10)
        self.right = None
        self._main_panel(self.main)
        self._right_panel(body)
        self._footer()

    def _header(self):
        h = tk.Frame(self.root, bg='#07162f', height=72, highlightthickness=0)
        h.pack(fill='x')
        h.pack_propagate(False)

        logo = tk.Frame(h, bg='#07162f', width=180)
        logo.pack(side='left', fill='y', padx=(14, 8))
        logo.pack_propagate(False)
        tk.Label(logo, text='V', bg='#07162f', fg=PURPLE,
                 font=('TkDefaultFont', 32, 'bold')).pack(side='left', padx=(0, 4))
        tk.Label(logo, text='kus', bg='#07162f', fg='white',
                 font=('TkDefaultFont', 23, 'bold')).pack(side='left')

        tk.Label(h, text='УНИВЕРСАЛЬНЫЙ ИНСТРУМЕНТ ПОИСКА КЛИЕНТОВ В VK\n'
                      'Анализ  •  Поиск  •  Возможности',
                 bg='#07162f', fg=MUTED, justify='left',
                 font=('TkDefaultFont', 8)).pack(side='left')

        right = tk.Frame(h, bg='#07162f')
        right.pack(side='right', padx=14)
        tk.Label(right, text='VK', bg='#1688ff', fg='white', width=3, height=1,
                 font=('TkDefaultFont', 10, 'bold')).pack(side='left', padx=7)
        self.auth_header = tk.Label(right, text='●  Сессия не проверена', bg='#07162f',
                                    fg=MUTED, font=('TkDefaultFont', 9))
        self.auth_header.pack(side='left')

    def _sidebar(self, parent):
        side = tk.Frame(parent, bg='#061226', width=190, highlightthickness=0)
        side.grid(row=0, column=0, sticky='ns')
        side.grid_propagate(False)
        items = [
            ('⌂', 'Первичная настройка', self._show_setup),
            ('⌕', 'Поиск', self._show_search),
            ('▤', 'Сообщения', self._show_messages),
            ('⇄', 'Биржа', self._show_exchange),
            ('ⓘ', 'О программе', self._show_about),
        ]
        self.nav_buttons = {}
        for i, (icon, label, command) in enumerate(items):
            b = tk.Button(side, text=f'{icon}   {label}', anchor='w', relief='flat', bd=0,
                          bg='#0d2860' if i == 0 else '#061226', fg=TEXT,
                          highlightthickness=0, overrelief='flat',
                          activebackground='#173f89', activeforeground='white',
                          takefocus=0,
                          font=('TkDefaultFont', 9), padx=14, pady=8, command=command)
            b.pack(fill='x', padx=7, pady=(9 if i == 0 else 2, 2))
            self.nav_buttons[label] = b
        spacer = tk.Frame(side, bg='#061226')
        spacer.pack(fill='both', expand=True)
        tk.Label(side, text='Vkus —\nнайдите клиентов\nтам, где они уже есть',
                 bg='#061226', fg=MUTED, justify='left',
                 font=('TkDefaultFont', 8)).pack(anchor='w', padx=14, pady=10)
        tk.Label(side, text='(с) 2026\nавтор: Машин Александр Геннадьевич',
                 bg='#061226', fg=MUTED, justify='left',
                 font=('TkDefaultFont', 7)).pack(anchor='w', padx=14, pady=5)
        tk.Button(side, text='VK  Написать', command=lambda: self._open_url('https://m.vk.ru/mashin_a_g'),
                  bg='#12386c', fg=TEXT, relief='flat', bd=0, padx=7, pady=6,
                  font=('TkDefaultFont', 8)).pack(pady=5)

    def _clear_main(self):
        # Pages are cached instead of destroyed. A running Selenium search must
        # survive navigation between tabs and return to the same result feed.
        for child in self.main.winfo_children():
            try:
                child.pack_forget()
            except tk.TclError:
                pass

    def _set_nav_active(self, label):
        for name, button in getattr(self, 'nav_buttons', {}).items():
            button.configure(bg='#0d2860' if name == label else '#061226')

    def _show_setup(self):
        self._set_nav_active('Первичная настройка')
        if self.right is not None:
            self.right.grid()
        self.main.grid_configure(columnspan=1, padx=(10, 10))
        self._clear_main()
        if self.setup_page is None or not self.setup_page.winfo_exists():
            self._main_panel(self.main)
        else:
            self.setup_page.pack(fill='both', expand=True)

    def _show_search(self):
        self._set_nav_active('Поиск')
        if self.right is not None:
            self.right.grid_remove()
        self.main.grid_configure(columnspan=2, padx=(10, 10))
        self._clear_main()
        if self.search_page is None or not self.search_page.winfo_exists():
            self._search_page(self.main)
        else:
            self.search_page.pack(fill='both', expand=True)

    def _show_messages(self):
        self._set_nav_active('Сообщения')
        if self.right is not None:
            self.right.grid_remove()
        self.main.grid_configure(columnspan=2, padx=(10, 10))
        self._clear_main()
        if self.messages_page is None or not self.messages_page.winfo_exists():
            self._messages_page(self.main)
        else:
            self.messages_page.pack(fill='both', expand=True)

    def _show_exchange(self):
        """Show the approved Vkus Exchange reference as an interactive desktop view."""
        self._set_nav_active('Биржа')
        if getattr(self, 'exchange_window', None) is not None:
            try:
                if self.exchange_window.winfo_exists():
                    self.exchange_window.deiconify()
                    self.exchange_window.lift()
                    return
            except tk.TclError:
                pass
        if Image is None or ImageTk is None:
            messagebox.showerror('Vkus — Биржа', 'Для отображения интерфейса необходим Pillow.')
            return
        reference = Path(__file__).resolve().parent / 'assets' / 'birzha_reference.png'
        if not reference.exists():
            messagebox.showerror('Vkus — Биржа', 'Не найден утверждённый визуал: ' + str(reference))
            return
        win = tk.Toplevel(self.root)
        self.exchange_window = win
        win.title('Vkus — Биржа спроса и предложений')
        # Fit the complete approved reference inside the usable desktop area.
        # A fixed 1672x941 window was clipped on 1600x1000 VM desktops.
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        # Keep the reference aspect ratio exactly; use the largest centered size
        # that fits the screen with room for the desktop/taskbar.
        fit = min((sw - 24) / 1672, (sh - 80) / 941)
        width = max(1000, min(1672, int(1672 * fit)))
        height = max(620, min(941, int(941 * fit)))
        x = max(0, (sw - width) // 2)
        y = max(0, (sh - height) // 2)
        win.geometry(f'{width}x{height}+{x}+{y}')
        win.minsize(min(1100, width), min(620, height))
        win.configure(bg='#020516')
        canvas = tk.Canvas(win, bg='#020516', highlightthickness=0, bd=0)
        canvas.pack(fill='both', expand=True)
        self.exchange_canvas = canvas
        self.exchange_reference = Image.open(reference).convert('RGB')
        self.exchange_sources_selected = {'Avito'}
        self.exchange_categories_selected = {
            'Заявки на услуги и ремонт',
            'Разовые задачи и подработка',
            'Вакансии и работу',
            'Товары и предложения',
            'Потребность в помощи и специалистах',
        }
        self.exchange_city = 'Оренбург'
        self.exchange_radius = '50 км'
        self.exchange_period = 'За всё время'
        self.exchange_category = 'Все категории'
        self.exchange_query_var = tk.StringVar()
        self.exchange_entry = tk.Entry(win, textvariable=self.exchange_query_var,
            bg='#0a1531', fg='#9aaed6', insertbackground='#ffffff', relief='flat', bd=0,
            font=('DejaVu Sans', 15), highlightthickness=0)
        self.exchange_entry.insert(0, 'Например: ремонт компьютера, настройка рекламы, доставка...')
        self.exchange_entry.bind('<FocusIn>', self._exchange_entry_focus_in)
        self.exchange_entry.bind('<FocusOut>', self._exchange_entry_focus_out)
        self.exchange_canvas.bind('<Configure>', self._exchange_redraw)
        self.exchange_canvas.bind('<Button-1>', self._exchange_click)
        self.exchange_entry.bind('<Return>', lambda _e: self._exchange_find())
        win.protocol('WM_DELETE_WINDOW', self._exchange_close)
        self._exchange_redraw()

    def _exchange_close(self):
        try:
            if self.exchange_window is not None:
                self.exchange_window.destroy()
        except tk.TclError:
            pass
        self.exchange_window = None

    def _exchange_redraw(self, _event=None):
        """Render the Exchange screen from native canvas primitives (not a screenshot)."""
        if not getattr(self, 'exchange_canvas', None):
            return
        c = self.exchange_canvas
        w, h = max(1, c.winfo_width()), max(1, c.winfo_height())
        scale = min(w / 1672, h / 941)
        rw, rh = max(1, int(1672 * scale)), max(1, int(941 * scale))
        ox, oy = (w-rw)//2, (h-rh)//2
        self.exchange_geometry = (scale, ox, oy, rw, rh)
        c.delete('all')
        def xy(v): return ox + v * scale
        def yy(v): return oy + v * scale
        def rect(x1,y1,x2,y2,fill='#08132f',outline='#263b79',r=14,width=1):
            # One smooth native polygon avoids the doubled seams of overlapping rectangles.
            r=max(2,min(r,(x2-x1)/4,(y2-y1)/4))*scale
            pts=[]
            for cx,cy,a0 in [(xy(x2)-r,yy(y1)+r,-90),(xy(x2)-r,yy(y2)-r,0),(xy(x1)+r,yy(y2)-r,90),(xy(x1)+r,yy(y1)+r,180)]:
                for k in range(7):
                    import math
                    a=math.radians(a0+k*15)
                    pts.extend((cx+r*math.cos(a),cy+r*math.sin(a)))
            c.create_polygon(*pts,fill=fill,outline=outline,width=max(1,int(width*scale)),smooth=True)
        def txt(x,y,text,size=16,color='#edf3ff',weight='normal',anchor='nw'):
            c.create_text(xy(x),yy(y),text=text,anchor=anchor,fill=color,
                font=('DejaVu Sans',max(7,int(size*scale)),weight))
        def line(x1,y1,x2,y2,color='#283c78',width=1):
            c.create_line(xy(x1),yy(y1),xy(x2),yy(y2),fill=color,width=max(1,int(width*scale)))
        # Background and frame
        c.configure(bg='#020516')
        rect(8,8,1664,933,'#03091d','#5621a4',20,2)
        # Left brand/navigation rail
        rect(12,12,268,929,'#050a22','#49218f',20,1)
        txt(44,28,'♛',42,'#c45cff','bold'); txt(52,75,'Vkus',43,'#8e7bff','bold')
        txt(40,142,'◆',24,'#28d8ff','bold'); txt(38,178,'NEON SEARCH',9,'#8a9cc7','bold')
        # Tiger crop from the approved reference artwork only; all UI is native.
        if not hasattr(self,'exchange_tiger_photo'):
            try:
                tiger=self.exchange_reference.crop((24,165,260,370)).resize((205,205),Image.Resampling.LANCZOS)
                self.exchange_tiger_photo=ImageTk.PhotoImage(tiger)
            except Exception: self.exchange_tiger_photo=None
        if self.exchange_tiger_photo:
            c.create_image(xy(30),yy(135),image=self.exchange_tiger_photo,anchor='nw')
        nav=[('●','Сообщения'),('⌕','Поиск'),('⇄','Биржа'),('▥','Мониторинг'),('⚙','Настройки')]
        for i,(ico,label) in enumerate(nav):
            y=375+i*61
            if label=='Биржа': rect(13,y,253,y+57,'#24105b','#9c35ff',13,2)
            txt(36,y+13,ico,24,'#39d9ff' if label=='Биржа' else '#a96bff','bold')
            txt(82,y+17,label,16,'#ffffff' if label=='Биржа' else '#9aadd8','bold' if label=='Биржа' else 'normal')
        rect(28,728,250,855,'#071b35','#2d79b6',16,1)
        txt(46,746,'Ваш статус',13,'#b7c8ed'); txt(46,773,'● Активен',16,'#00e5b4','bold')
        txt(46,811,'★ Премиум',16,'#ffc34d','bold'); txt(46,836,'до 24.12.2026',11,'#a6b6dc')
        txt(36,884,'Vkus v3.16',12,'#8b9cc8')
        # Main title/header
        txt(306,43,'Биржа спроса и предложений',38,'#cf74ff','bold')
        txt(307,105,'Находите клиентов, исполнителей и актуальные задачи рядом с вами',18,'#e4eaff')
        txt(1364,27,'● Онлайн',13,'#20e66c','bold')
        txt(1465,82,'Спрос есть.',18,'#bd6cff','bold'); txt(1445,109,'Найдём вместе!',18,'#bd6cff','bold')
        # KPI cards: values are clearly labelled as demo placeholders.
        kpis=[('♙','Заявки','—','ожидают подключения данных','#8f39ff'),('▣','Специалисты','—','ожидают подключения данных','#19baff'),('◎','Новые задачи','—','ожидают подключения данных','#ad45ff'),('▥','Анализ спроса','—','после подключения источников','#12dcb5'),('☆','Релевантность','—','рассчитывается по запросу','#ffbd42')]
        for i,(ico,title,value,sub,col) in enumerate(kpis):
            x=300+i*264
            rect(x,170,x+245,345,'#0a1531',col,18,1)
            txt(x+20,193,ico,34,col,'bold'); txt(x+72,204,title,14,'#edf3ff','bold')
            txt(x+72,238,value,27,'#ffffff','bold'); txt(x+20,298,sub,10,'#a9b9df')
        # Search panel
        rect(300,373,1345,556,'#091633','#3866bd',20,1)
        txt(323,388,'⌕',35,'#20caff','bold'); txt(373,394,'Умный поиск',23,'#f2f5ff','bold')
        txt(1137,402,'Расширенный поиск  ⌄',15,'#38aaff')
        rect(320,435,1165,488,'#08132d','#536db3',13,1)
        self.exchange_entry.place(x=xy(330),y=yy(440),width=xy(1155)-xy(330),height=yy(483)-yy(440))
        self.exchange_entry.configure(font=('DejaVu Sans',max(9,int(15*scale))),bg='#08132d',fg=('#9aaed6' if self.exchange_entry.get().startswith('Например: ремонт компьютера') else '#f2f5ff'),insertbackground='#ffffff')
        rect(1178,435,1325,488,'#5314b7','#a943ff',13,1)
        txt(1202,448,'⌕  Найти',18,'#ffffff','bold')
        filters=[('⌖',getattr(self,'exchange_city','Оренбург'),320,478),('⚙','Радиус: '+getattr(self,'exchange_radius','50 км'),490,684),('▦',getattr(self,'exchange_period','За всё время'),696,889),('▦',getattr(self,'exchange_category','Все категории'),901,1094)]
        for ico,label,x1,x2 in filters:
            rect(x1,500,x2,541,'#08122d','#344a8b',18,1); txt(x1+13,510,ico,17,'#a9b7e9','bold'); txt(x1+40,511,label+'  ⌄',13,'#e7edff')
        # Sources
        txt(307,572,'◎  Источники поиска',17,'#f0f4ff','bold')
        sources=[('VK','VK','#168cff'),('Telegram','➤','#27caff'),('Avito','●','#e848c8'),('YouDo','Y','#ffffff'),('Профи.ру','P','#ff5478'),('Форумы','▣','#20caff')]
        for i,(name,logo,col) in enumerate(sources):
            x=301+i*147
            active=name in self.exchange_sources_selected
            rect(x,610,x+132,691,'#11183b' if active else '#09132e','#ce45ff' if active else '#293c78',16,2 if active else 1)
            txt(x+66,622,logo,26,col,'bold','n'); txt(x+66,662,name,14,'#eef2ff','bold','n')
        rect(1185,610,1343,691,'#09132e','#344d91',16,1); txt(1264,625,'+',30,'#a8c4ff','bold','n'); txt(1264,665,'Ещё 5',13,'#eef2ff','bold','n')
        # Right explainer
        rect(1360,373,1618,702,'#0b1430','#8e39e7',18,1)
        txt(1384,393,'▥ Что можно найти?',17,'#f2f5ff','bold')
        for j,t in enumerate(['Заявки на услуги','и ремонт','Разовые задачи','Вакансии и работу','Товары и предложения','Потребность в помощи','и специалистах']):
            txt(1390,438+j*30,'✓' if j in (0,2,4,5) else '·',15,'#13e3b2','bold'); txt(1417,438+j*30,t,13,'#dce6ff')
        rect(1372,631,1607,688,'#21104d','#9c35ff',12,1); txt(1390,643,'ϟ Vkus анализирует',13,'#d98cff','bold'); txt(1390,664,'после подключения источников',10,'#e2d9ff')
        # Lower cards: no fabricated live leads or maps.
        rect(300,716,855,897,'#08142f','#334e9c',17,1); txt(324,735,'◉  Последние находки',16,'#f2f5ff','bold')
        txt(324,780,'Здесь появятся найденные публикации',14,'#c1d0f2'); txt(324,808,'после подключения поисковых источников.',12,'#8fa4d5')
        rect(870,716,1332,897,'#08142f','#334e9c',17,1); txt(895,735,'⌖  Регионы и активность',16,'#f2f5ff','bold')
        txt(895,782,'География результатов',14,'#c1d0f2'); txt(895,811,'будет строиться по реальным данным',12,'#8fa4d5')
        rect(1347,716,1618,897,'#08142f','#334e9c',17,1); txt(1368,735,'▥ Опции анализа',15,'#f2f5ff','bold')
        for j,t in enumerate(['Определение намерения','Подбор ниши','Оценка спроса','Уведомления о новых заявках']):
            txt(1370,773+j*25,'✓',13,'#12dfb0','bold'); txt(1392,773+j*25,t,11,'#c7d5f4')
        txt(1480,873,'Настроить',12,'#c58cff','bold')
        self.exchange_hit_scale = scale

    def _exchange_entry_focus_in(self, _event=None):
        if self.exchange_entry.get().startswith('Например: ремонт компьютера'):
            self.exchange_entry.delete(0, 'end')
            self.exchange_entry.configure(fg='#f3f6ff')

    def _exchange_entry_focus_out(self, _event=None):
        if not self.exchange_entry.get().strip():
            self.exchange_entry.insert(0, 'Например: ремонт компьютера, настройка рекламы, доставка...')
            self.exchange_entry.configure(fg='#9aaed6')

    def _exchange_click(self, event):
        scale, ox, oy, rw, rh = self.exchange_geometry
        x, y = (event.x-ox)/scale, (event.y-oy)/scale
        if not (0 <= x <= 1672 and 0 <= y <= 941):
            return
        if 1175 <= x <= 1328 and 432 <= y <= 491:
            self._exchange_find(); return
        if 300 <= x <= 1345 and 608 <= y <= 692:
            boxes = [('VK',301,432),('Telegram',443,579),('Avito',590,727),
                     ('YouDo',737,875),('Профи.ру',886,1031),('Форумы',1042,1188)]
            for name, x1, x2 in boxes:
                if x1 <= x <= x2:
                    if name in self.exchange_sources_selected:
                        self.exchange_sources_selected.remove(name)
                    else:
                        self.exchange_sources_selected.add(name)
                    self._exchange_redraw(); return
            if 1198 <= x <= 1345:
                messagebox.showinfo('Vkus — источники',
                    'Дополнительные источники: Google, Яндекс, Работа.ру и отраслевые площадки. Подключение выполняется отдельными интеграциями.', parent=self.exchange_window)
                return
        if 320 <= x <= 478 and 498 <= y <= 541:
            self._exchange_menu(event, 'Город', ['Оренбург','Орск','Москва','Санкт-Петербург','Екатеринбург']); return
        if 489 <= x <= 684 and 498 <= y <= 541:
            self._exchange_menu(event, 'Радиус', ['10 км','25 км','50 км','100 км','Вся страна']); return
        if 695 <= x <= 889 and 498 <= y <= 541:
            self._exchange_menu(event, 'Период', ['За сутки','За 7 дней','За 30 дней','За 3 месяца','За всё время']); return
        if 901 <= x <= 1094 and 498 <= y <= 541:
            self._exchange_menu(event, 'Категория', ['Все категории','Услуги и ремонт','Работа и вакансии','Покупка и продажа','Разовые задачи','Помощь и специалисты']); return
        if 1380 <= x <= 1608 and 430 <= y < 630:
            categories = (
                'Заявки на услуги и ремонт',
                'Разовые задачи и подработка',
                'Вакансии и работу',
                'Товары и предложения',
                'Потребность в помощи и специалистах',
            )
            index = int((y - 438) // 39)
            if 0 <= index < len(categories):
                selected = getattr(self, 'exchange_categories_selected', set())
                category = categories[index]
                if category in selected:
                    selected.remove(category)
                else:
                    selected.add(category)
                self.exchange_categories_selected = selected
                self._exchange_redraw()
                return
        if 1360 <= x <= 1618 and 373 <= y <= 700:
            messagebox.showinfo('Что можно найти?',
                'Vkus предназначен для поиска заявок на услуги, разовых задач, вакансий, товаров, предложений и потребности в специалистах.', parent=self.exchange_window); return
        if 1360 <= x <= 1618 and 716 <= y <= 897:
            messagebox.showinfo('Анализ спроса',
                'В этом блоке показаны будущие параметры анализа. Реальная классификация и оценка спроса подключаются вместе с поисковыми источниками.', parent=self.exchange_window); return
        if 10 <= x <= 254 and 375 <= y <= 676:
            if 375 <= y < 432: self._exchange_info('Сообщения')
            elif 436 <= y < 493: self._exchange_info('Поиск')
            elif 497 <= y < 554: self._exchange_info('Биржа')
            elif 558 <= y < 615: self._exchange_info('Мониторинг')
            elif 619 <= y < 676: self._exchange_info('Настройки')
        if 1480 <= x <= 1525 and 20 <= y <= 58:
            self.exchange_window.iconify()
            return
        if 1530 <= x <= 1575 and 20 <= y <= 58:
            try:
                self.exchange_window.state('normal' if self.exchange_window.state() == 'zoomed' else 'zoomed')
            except tk.TclError:
                pass
            return
        if 1580 <= x <= 1628 and 20 <= y <= 58:
            self._exchange_close()
            return

    def _exchange_menu(self, event, title, options):
        menu = tk.Menu(self.exchange_window, tearoff=0, bg='#0a1531', fg='#edf3ff',
                       activebackground='#5525a5', activeforeground='white')
        for value in options:
            menu.add_command(label=value, command=lambda v=value: self._exchange_set_filter(title, v))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _exchange_set_filter(self, title, value):
        attr = {'Город':'exchange_city','Радиус':'exchange_radius','Период':'exchange_period','Категория':'exchange_category'}.get(title)
        if attr:
            setattr(self, attr, value)
            self._exchange_redraw()

    def _exchange_info(self, message):
        if message == 'Биржа':
            return
        messagebox.showinfo('Vkus', message + '\n\nЭтот экран уже выполнен в утверждённом визуальном стиле. Связь с остальными рабочими модулями будет подключена отдельно.', parent=self.exchange_window)

    def _exchange_find(self):
        query = self.exchange_query_var.get().strip()
        if query.startswith('Например: ремонт компьютера'):
            query = ''
        if not query:
            messagebox.showwarning('Vkus — поиск', 'Введите запрос: например, «ремонт компьютера».', parent=self.exchange_window)
            return
        if not self.exchange_sources_selected:
            messagebox.showwarning('Vkus — поиск', 'Выберите хотя бы один источник.', parent=self.exchange_window)
            return
        selected_categories = sorted(getattr(self, 'exchange_categories_selected', set()))
        category_text = ', '.join(selected_categories) if selected_categories else 'Все типы'
        messagebox.showinfo('Vkus — поиск',
            'Запрос: ' + query + '\nИсточники: ' + ', '.join(sorted(self.exchange_sources_selected)) +
            '\nТипы: ' + category_text +
            '\n\nВыбор параметров сохранён в интерфейсе. Реальные коннекторы и сбор актуальных объявлений ещё не подключены.',
            parent=self.exchange_window)

    def _show_about(self):
        messagebox.showinfo('Vkus', 'Vkus — универсальный локальный инструмент поиска клиентов в VK.\n\nСборка 3.1: Kali Linux + Firefox + Selenium. Реальный поиск VK и реальные сообщения без демо-данных.')

    def _main_panel(self, parent):
        left = tk.Frame(parent, bg=PANEL, highlightthickness=0)
        left.pack(fill='both', expand=True)
        self.setup_page = left
        top = tk.Frame(left, bg=PANEL)
        top.pack(fill='x', padx=14, pady=10)
        tk.Label(top, text='⚡  ПОЛНАЯ ПРОВЕРКА', bg=PANEL, fg=TEXT,
                 font=('TkDefaultFont', 13, 'bold')).pack(side='left')
        tk.Label(top, text='Автоматическая цепочка', bg=PANEL, fg=MUTED,
                 font=('TkDefaultFont', 8)).pack(side='left', padx=10)
        self.last = tk.Label(top, text='Последняя: —', bg=PANEL, fg=MUTED,
                             font=('TkDefaultFont', 8))
        self.last.pack(side='right')
        GradientButton(left, '▶  ПРОВЕРИТЬ', self.run_all, height=46).pack(fill='x', padx=14, pady=(0, 6))
        tk.Button(left, text='↺  СБРОСИТЬ РЕЗУЛЬТАТЫ', command=self.reset_results,
                  bg='#0d2545', fg=TEXT, activebackground='#173f76', activeforeground='white',
                  relief='flat', bd=0, padx=10, pady=7, cursor='hand2',
                  font=('TkDefaultFont', 8, 'bold')).pack(fill='x', padx=14, pady=(0, 8))
        self._config_panel(left)
        self.steps = tk.Frame(left, bg=PANEL)
        self.steps.pack(fill='both', expand=True, padx=14, pady=(0, 8))
        for c in self.checks:
            self._make_step(c)
        self._restore_persisted_status()
        summary = tk.Frame(left, bg='#071d2b', highlightthickness=0)
        summary.pack(fill='x', padx=14, pady=(0, 10))
        self.summary = tk.Label(summary, text=self._summary_text(), bg='#071d2b', fg=TEXT,
                                anchor='w', padx=12, pady=8,
                                font=('TkDefaultFont', 8, 'bold'))
        self.summary.pack(fill='x')

    def _config_panel(self, parent):
        box = tk.Frame(parent, bg='#06162c', highlightthickness=0)
        box.pack(fill='x', padx=14, pady=(0, 8))
        tk.Label(box, text='НАСТРОЙКИ VK', bg='#06162c', fg=CYAN,
                 font=('TkDefaultFont', 9, 'bold')).grid(row=0, column=0, columnspan=3, sticky='w', padx=10, pady=(7, 2))
        box.grid_columnconfigure(0, weight=1); box.grid_columnconfigure(1, weight=1); box.grid_columnconfigure(2, weight=1)
        self.setup_query_var = tk.StringVar(value=self.settings.get('search_query',''))
        self.setup_community_var = tk.StringVar(value=self.settings.get('community_url',''))
        self.setup_post_var = tk.StringVar(value=self.settings.get('post_url',''))
        fields = [
            ('Поисковый запрос', self.setup_query_var),
            ('URL сообщества для проверки', self.setup_community_var),
            ('URL поста для проверки', self.setup_post_var),
        ]
        for col, (label, var) in enumerate(fields):
            cell=tk.Frame(box,bg='#071d39',highlightthickness=0)
            cell.grid(row=1,column=col,sticky='ew',padx=4,pady=(0,7))
            tk.Label(cell,text=label,bg='#071d39',fg=MUTED,font=('TkDefaultFont',7)).pack(anchor='w',padx=7,pady=(4,0))
            tk.Entry(cell,textvariable=var,bg='#071d39',fg=TEXT,insertbackground=CYAN,relief='flat',bd=0,font=('TkDefaultFont',8)).pack(fill='x',padx=7,pady=(1,5))
        actions=tk.Frame(box,bg='#06162c'); actions.grid(row=2,column=0,columnspan=3,sticky='ew',padx=4,pady=(0,6))
        tk.Button(actions,text='СОХРАНИТЬ',command=self.save_config,bg='#174aa1',fg='white',activebackground='#2465d1',relief='flat',bd=0,padx=12,pady=5,font=('TkDefaultFont',8,'bold')).pack(side='left',padx=3)
        tk.Button(actions,text='VK / АВТОРИЗАЦИЯ',command=lambda:self.run_one('auth'),bg='#0d315f',fg=TEXT,activebackground='#1a4e8f',relief='flat',bd=0,padx=12,pady=5,font=('TkDefaultFont',8,'bold')).pack(side='left',padx=3)
        tk.Button(actions,text='ОТКРЫТЬ VK',command=self._open_vk_direct,bg='#0d315f',fg=TEXT,activebackground='#1a4e8f',relief='flat',bd=0,padx=12,pady=5,font=('TkDefaultFont',8,'bold')).pack(side='left',padx=3)

    def _open_vk_direct(self):
        def work():
            try:
                url=self.browser.open_vk()
                self.root.after(0,lambda:self.log.insert('end',f'[{datetime.now():%H:%M:%S}] VK открыт: {url}\n'))
            except Exception as exc:
                detail=str(exc); self.root.after(0,lambda d=detail:self.log.insert('end',f'[{datetime.now():%H:%M:%S}] Ошибка открытия VK: {d}\n'))
        threading.Thread(target=work,daemon=True).start()

    def _load_message_contacts(self):
        try:
            value = json.loads(self.settings.get('message_contacts_json', '[]'))
            return value if isinstance(value, list) else []
        except Exception:
            return []

    def _load_chat_history(self):
        try:
            value = json.loads(self.settings.get('chat_history_json', '{}'))
            return value if isinstance(value, dict) else {}
        except Exception:
            return {}

    def _load_search_results(self):
        try:
            value = json.loads(self.settings.get('search_results_json', '[]'))
            return value if isinstance(value, list) else []
        except Exception:
            return []

    def _save_persistent_state(self):
        payload = {}
        for key, result in self.status.items():
            if result is not None:
                payload[key] = {
                    'title': result.title,
                    'ok': bool(result.ok),
                    'detail': result.detail,
                    'url': result.url,
                    'duration': float(result.duration),
                }
        self.settings['last_results_json'] = json.dumps(payload, ensure_ascii=False)
        self.settings['last_check_at'] = datetime.now().isoformat(timespec='seconds')
        self.settings['message_contacts_json'] = json.dumps(self.message_contacts, ensure_ascii=False)
        self.settings['chat_history_json'] = json.dumps(self.chat_history, ensure_ascii=False)
        self.settings['search_results_json'] = json.dumps(self.search_results, ensure_ascii=False)
        self.settings['search_region'] = getattr(self, 'region_var', tk.StringVar(value=self.settings.get('search_region', 'Москва и область'))).get()
        self.settings['search_city'] = getattr(self, 'city_var', tk.StringVar(value=self.settings.get('search_city', 'Москва'))).get()
        self.settings['search_source'] = getattr(self, 'search_source_var', tk.StringVar(value=self.settings.get('search_source', 'Стены сообществ'))).get()
        self.settings['search_state'] = getattr(self, 'search_state_var', tk.StringVar(value=self.settings.get('search_state', 'Новые сообщения'))).get()
        self.settings['search_year'] = getattr(self, 'search_year_var', tk.StringVar(value=self.settings.get('search_year', 'Все годы'))).get()
        self.settings['search_month'] = getattr(self, 'search_month_var', tk.StringVar(value=self.settings.get('search_month', 'Все месяцы'))).get()
        save_settings(self.settings)

    def _restore_persisted_status(self):
        try:
            payload = json.loads(self.settings.get('last_results_json', '{}'))
            if not isinstance(payload, dict):
                return
            for key, data in payload.items():
                if key not in self.by_key or not isinstance(data, dict):
                    continue
                result = CheckResult(
                    key=key, title=data.get('title', self.by_key[key].title),
                    ok=bool(data.get('ok', False)), detail=str(data.get('detail', '')),
                    url=str(data.get('url', '')), duration=float(data.get('duration', 0.0)))
                self.status[key] = result
                self._set_row(result)
            stamp = self.settings.get('last_check_at', '')
            if stamp:
                try:
                    dt = datetime.fromisoformat(stamp)
                    self.last.config(text=f'Последняя: {dt:%d.%m.%Y %H:%M:%S}')
                except Exception:
                    self.last.config(text=f'Последняя: {stamp}')
        except Exception:
            return

    def _make_step(self, c):
        row = tk.Frame(self.steps, bg=PANEL2, highlightthickness=0, height=39)
        row.pack(fill='x', pady=2)
        row.pack_propagate(False)
        tk.Label(row, text=c.key.upper()[:2], bg='#103263', fg=WHITE, width=4,
                 font=('TkDefaultFont', 7, 'bold')).pack(side='left', padx=6, pady=5)
        tk.Label(row, text=c.title, bg=PANEL2, fg=TEXT, width=13, anchor='w',
                 font=('TkDefaultFont', 8, 'bold')).pack(side='left')
        detail = tk.Label(row, text='Не запускалось', bg=PANEL2, fg=MUTED,
                          anchor='w', font=('TkDefaultFont', 8))
        detail.pack(side='left', fill='x', expand=True)
        lamp = tk.Label(row, text='●', bg=PANEL2, fg='#7f8da5', font=('TkDefaultFont', 11))
        lamp.pack(side='right', padx=8)
        self.rows[c.key] = (row, detail, lamp)

    def _right_panel(self, parent):
        right = tk.Frame(parent, bg=BG, width=300, highlightthickness=0)
        right.grid(row=0, column=2, sticky='ns', padx=(0, 10), pady=10)
        self.right = right
        right.grid_propagate(False)

        box = tk.Frame(right, bg=PANEL, highlightthickness=0)
        box.pack(fill='x')
        tk.Label(box, text='ДОСТУПНЫЕ ТЕСТЫ', bg=PANEL, fg=TEXT,
                 font=('TkDefaultFont', 10, 'bold')).pack(anchor='w', padx=10, pady=(10, 1))
        tk.Label(box, text='Каждый этап запускается отдельно', bg=PANEL, fg=MUTED,
                 font=('TkDefaultFont', 7)).pack(anchor='w', padx=10, pady=(0, 6))
        for c in self.checks:
            b = tk.Button(box, text=f'  {c.title}', command=lambda key=c.key: self.run_one(key),
                          anchor='w', bg='#0b2344', fg=TEXT, activebackground='#153e76',
                          activeforeground='white', relief='flat', bd=0, padx=8, pady=4,
                          font=('TkDefaultFont', 8))
            b.pack(fill='x', padx=8, pady=1)

        logbox = tk.Frame(right, bg=PANEL, highlightthickness=0)
        logbox.pack(fill='both', expand=True, pady=(8, 0))
        tk.Label(logbox, text='ЛОГИ / РЕЗУЛЬТАТЫ', bg=PANEL, fg=TEXT,
                 font=('TkDefaultFont', 9, 'bold')).pack(anchor='w', padx=10, pady=(8, 4))
        self.log = tk.Text(logbox, bg='#061226', fg='#a9c8ec', insertbackground=TEXT,
                           relief='flat', bd=0, font=('TkFixedFont', 7), wrap='word')
        self.log.pack(fill='both', expand=True, padx=8, pady=(0, 7))
        buttons = tk.Frame(logbox, bg=PANEL)
        buttons.pack(fill='x', padx=8, pady=(0, 8))
        tk.Button(buttons, text='Очистить', command=lambda: self.log.delete('1.0', 'end'),
                  bg='#0d2545', fg=TEXT, relief='flat', bd=0, padx=9, pady=5,
                  font=('TkDefaultFont', 8)).pack(side='left')
        tk.Button(buttons, text='Сохранить', command=self.save_config,
                  bg='#0d2545', fg=TEXT, relief='flat', bd=0, padx=9, pady=5,
                  font=('TkDefaultFont', 8)).pack(side='right')

    def _search_page(self, parent):
        """Reference-style search workspace. Functional controls remain real; layout follows the neon reference."""
        page = tk.Frame(parent, bg=BG)
        page.pack(fill='both', expand=True)
        self.search_page = page
        # One background image for the whole search workspace. The hero and result
        # feed no longer paint their own copies, so the animal cannot be duplicated.
        self._add_neon_background(page)

        # --- compact neon hero: no boxed columns, only one continuous composition ---
        hero = tk.Canvas(page, height=154, bg=BG, highlightthickness=0, bd=0)
        hero.pack(fill='x', pady=(0, 7))
        hero.bind('<Configure>', lambda e: self._draw_search_hero(e.widget))
        self._draw_search_hero(hero)

        # --- search controls: one continuous glass strip ---
        controls = tk.Frame(page, bg='#020817', highlightthickness=0)
        controls.pack(fill='x', pady=(0, 8))
        controls.grid_columnconfigure(0, weight=1)
        controls.grid_columnconfigure(1, weight=0)
        self.search_query_var = tk.StringVar(value=self.settings.get('search_query', ''))
        qbox = tk.Frame(controls, bg='#020817')
        qbox.grid(row=0, column=0, sticky='ew', padx=12, pady=10)
        tk.Label(qbox, text='⌕', bg='#020817', fg=CYAN,
                 font=('TkDefaultFont', 22, 'bold')).pack(side='left', padx=(4, 8))
        entry = tk.Entry(qbox, textvariable=self.search_query_var, bg='#020817', fg=TEXT,
                         insertbackground=CYAN, relief='flat', bd=0,
                         font=('TkDefaultFont', 12), highlightthickness=0)
        entry.pack(side='left', fill='x', expand=True, ipady=8)
        entry.bind('<Return>', lambda _e: self._search_action())
        self.search_scope_label = tk.Label(qbox, text='ПОИСК ПО ПОСТАМ VK', bg='#020817', fg='#3f6293',
                 font=('TkDefaultFont', 7, 'bold'))
        self.search_scope_label.pack(side='right', padx=5)
        self.region_var = tk.StringVar(value=self.settings.get('search_region', 'Москва и область'))
        self.city_var = tk.StringVar(value=self.settings.get('search_city', 'Москва'))
        self.search_source_var = tk.StringVar(value=self.settings.get('search_source', 'Стены сообществ'))
        self.search_state_var = tk.StringVar(value=self.settings.get('search_state', 'Новые сообщения'))
        self.search_mode_var = tk.StringVar(value=self.settings.get('search_mode', 'posts'))
        self.search_year_var = tk.StringVar(value=self.settings.get('search_year', 'Все годы'))
        self.search_month_var = tk.StringVar(value=self.settings.get('search_month', 'Все месяцы'))
        self.community_url_var = tk.StringVar(value=self.settings.get('search_community_url', ''))
        self.community_name_var = tk.StringVar(value=self.settings.get('search_community_name', ''))
        GradientButton(controls, '⌕  НАЙТИ', self._search_action, height=48, width=164).grid(
            row=0, column=1, sticky='e', padx=(4, 12), pady=10)

        community_bar = tk.Frame(controls, bg='#06122a', highlightthickness=0)
        community_bar.grid(row=1, column=0, columnspan=2, sticky='ew', padx=12, pady=(0, 8))
        community_bar.grid_columnconfigure(1, weight=1)
        tk.Label(community_bar, text='СООБЩЕСТВО VK', bg='#06122a', fg=CYAN,
                 font=('TkDefaultFont', 7, 'bold')).grid(row=0, column=0, sticky='w', padx=(10, 8), pady=6)
        self.community_display = tk.Label(community_bar, textvariable=self.community_name_var,
                 bg='#06122a', fg=TEXT, anchor='w', font=('TkDefaultFont', 9, 'bold'))
        self.community_display.grid(row=0, column=1, sticky='ew', padx=5, pady=5)
        if not self.community_name_var.get():
            self.community_name_var.set('Не выбрано — для комментариев выберите целевое сообщество')
        tk.Button(community_bar, text='ВЫБРАТЬ', command=self._open_community_picker,
                  bg='#174aa1', fg='white', activebackground='#2465d1', relief='flat', bd=0,
                  padx=14, pady=6, cursor='hand2', font=('TkDefaultFont', 8, 'bold')).grid(row=0, column=2, padx=5, pady=5)
        tk.Button(community_bar, text='СБРОСИТЬ', command=self._clear_community,
                  bg='#10264b', fg=MUTED, activebackground='#163d72', relief='flat', bd=0,
                  padx=10, pady=6, cursor='hand2', font=('TkDefaultFont', 8)).grid(row=0, column=3, padx=(0, 8), pady=5)

        filters = tk.Frame(controls, bg='#020817')
        filters.grid(row=2, column=0, columnspan=2, sticky='ew', padx=12, pady=(0, 10))
        for c in range(5): filters.grid_columnconfigure(c, weight=1)
        self._filter_combo(filters, 0, 'РЕГИОН', self.region_var,
                           ['Москва и область', 'Санкт-Петербург и область', 'Краснодарский край',
                            'Свердловская область', 'Новосибирская область', 'Все регионы'])
        self._filter_combo(filters, 1, 'ГОРОД', self.city_var,
                           ['Москва', 'Санкт-Петербург', 'Екатеринбург', 'Новосибирск', 'Казань', 'Все города'])
        self._filter_combo(filters, 2, 'ГОД', self.search_year_var,
                           ['Все годы', '2026', '2025', '2024', '2023', '2022', '2021', '2020'])
        self._filter_combo(filters, 3, 'МЕСЯЦ', self.search_month_var,
                           ['Все месяцы', 'Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
                            'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь'])
        info = tk.Frame(filters, bg='#06122a', highlightthickness=0)
        info.grid(row=0, column=4, sticky='ew', padx=(8, 0))
        tk.Label(info, text='ИСКАТЬ В', bg='#06122a', fg=MUTED,
                 font=('TkDefaultFont', 7, 'bold')).pack(anchor='w', padx=10, pady=(5, 2))
        modebar=tk.Frame(info, bg='#06122a', highlightthickness=0)
        modebar.pack(fill='x', padx=8, pady=(0, 5))
        self.search_mode_buttons={}
        for key,label in (('posts','ПОСТЫ'),('comments','КОММЕНТАРИИ')):
            b=tk.Button(modebar,text=label,command=lambda k=key:self._set_search_mode(k),
                        relief='flat',bd=0,cursor='hand2',padx=10,pady=5,
                        bg='#10264b',fg=TEXT,font=('TkDefaultFont',7,'bold'),
                        activebackground='#163d72',activeforeground='#ffffff')
            b.pack(side='left',fill='x',expand=True,padx=2)
            self.search_mode_buttons[key]=b
        self._set_search_mode(self.search_mode_var.get(), persist=False)

        # --- results: one uninterrupted feed, no vertical filter/result split ---
        head = tk.Frame(page, bg=BG)
        head.pack(fill='x', pady=(2, 4))
        tk.Label(head, text='НАЙДЕННЫЕ ПОТЕНЦИАЛЬНЫЕ КЛИЕНТЫ', bg=BG, fg=TEXT,
                 font=('TkDefaultFont', 13, 'bold')).pack(side='left')
        self.results_count = tk.Label(head, text='Готово к поиску', bg=BG, fg=CYAN,
                                      font=('TkDefaultFont', 8, 'bold'))
        self.results_count.pack(side='right')

        results_shell = tk.Frame(page, bg='#020713', highlightthickness=0)
        results_shell.pack(fill='both', expand=True)
        results_shell.grid_columnconfigure(0, weight=1)
        results_shell.grid_columnconfigure(1, weight=0)
        results_shell.grid_rowconfigure(0, weight=1)

        # One scrollable result feed. The canvas owns the background and the
        # inner frame owns the real result cards, so the feed can be scrolled
        # without losing the neon background.
        self.results_canvas = tk.Canvas(results_shell, bg='#020713', highlightthickness=0, bd=0)
        self.results_canvas.grid(row=0, column=0, sticky='nsew')
        self.results_scroll = ttk.Scrollbar(results_shell, orient='vertical', command=self.results_canvas.yview, style='Vkus.Vertical.TScrollbar')
        self.results_scroll.grid(row=0, column=1, sticky='ns')
        self.results_canvas.configure(yscrollcommand=self.results_scroll.set)
        self.results_frame = tk.Frame(self.results_canvas, bg='#020713', highlightthickness=0)
        self.results_window = self.results_canvas.create_window((0, 0), window=self.results_frame, anchor='nw')
        self.results_frame.bind('<Configure>', self._results_frame_configure)
        self.results_canvas.bind('<Configure>', self._results_canvas_configure)
        self._bind_results_scroll(self.results_canvas)
        if self.search_results:
            self.results_count.config(text=f'Сохранено: {len(self.search_results)}')
        self._render_results(self.search_results)

    def _results_frame_configure(self, _event=None):
        if hasattr(self, 'results_canvas') and self.results_canvas.winfo_exists():
            bbox = self.results_canvas.bbox('all')
            if bbox:
                self.results_canvas.configure(scrollregion=bbox)

    def _results_canvas_configure(self, event=None):
        if hasattr(self, 'results_canvas') and hasattr(self, 'results_window'):
            width = max(1, event.width if event else self.results_canvas.winfo_width())
            self.results_canvas.itemconfigure(self.results_window, width=width)

    def _bind_results_scroll(self, widget):
        def wheel(event):
            delta = -1 if event.delta > 0 else 1
            widget.yview_scroll(delta * 3, 'units')
            return 'break'
        widget.bind('<MouseWheel>', wheel, add='+')
        widget.bind('<Button-4>', lambda e: (widget.yview_scroll(-3, 'units'), 'break')[1], add='+')
        widget.bind('<Button-5>', lambda e: (widget.yview_scroll(3, 'units'), 'break')[1], add='+')

    def _global_results_wheel(self, event):
        canvas = getattr(self, 'results_canvas', None)
        if canvas is None or not canvas.winfo_exists():
            return
        try:
            x1 = canvas.winfo_rootx(); y1 = canvas.winfo_rooty()
            x2 = x1 + canvas.winfo_width(); y2 = y1 + canvas.winfo_height()
            if x1 <= event.x_root <= x2 and y1 <= event.y_root <= y2:
                delta = -1 if (getattr(event, 'delta', 0) > 0 or getattr(event, 'num', None) == 4) else 1
                canvas.yview_scroll(delta * 3, 'units')
                return 'break'
        except tk.TclError:
            return

    def _draw_search_hero(self, canvas, _=None):
        w=max(1, canvas.winfo_width()); h=max(1, canvas.winfo_height())
        canvas.delete('all')
        # The animal artwork is deliberately NOT repeated inside the hero.
        # The single application-wide neon background is already behind this page.
        canvas.create_rectangle(0, 0, w, h, fill='#030817', outline='')
        # Saturated neon atmosphere; deliberately no grey/white panels.
        for y in range(18, h, 34):
            canvas.create_line(0, y, w, y, fill='#071a39', width=1)
        for x in range(0, w, 70):
            canvas.create_line(x, 0, x+90, h, fill='#03102a', width=1)
        canvas.create_text(18, 22, text='V', anchor='w', fill=PURPLE,
                           font=('TkDefaultFont', 30, 'bold'))
        canvas.create_text(47, 25, text='kus', anchor='w', fill='#f5f7ff',
                           font=('TkDefaultFont', 23, 'bold'))
        canvas.create_text(18, 66, text='НАЙДЕННЫЕ', anchor='w', fill='#f3f7ff',
                           font=('TkDefaultFont', 18, 'bold'))
        canvas.create_text(18, 91, text='ПОТЕНЦИАЛЬНЫЕ КЛИЕНТЫ', anchor='w', fill=CYAN,
                           font=('TkDefaultFont', 18, 'bold'))
        canvas.create_text(18, 119, text='Реальные люди. Реальные запросы.  •  Поиск выполняется автоматически.',
                           anchor='w', fill='#7796bd', font=('TkDefaultFont', 8))

        # Keep the reference composition: neon image behind the dark UI, with saturated strokes on top.
        glow_x = max(260, int(w * 0.62))
        canvas.create_line(glow_x, h-18, w-30, 22, fill='#071d46', width=10)
        canvas.create_line(glow_x, h-18, w-30, 22, fill='#073d9a', width=2)
        canvas.create_line(glow_x+90, h-10, w-55, 54, fill='#3b0b83', width=8)
        canvas.create_line(glow_x+90, h-10, w-55, 54, fill='#9c20ff', width=2)
        canvas.create_text(w-22, 25, text='◎  УМНЫЙ ПОИСК', anchor='ne', fill='#e6ecff',
                           font=('TkDefaultFont', 9, 'bold'))
        canvas.create_text(w-22, 47, text='Анализирует и находит нужные сообщения', anchor='ne', fill='#6987b4',
                           font=('TkDefaultFont', 7))
        canvas.create_line(18,h-3,w-18,h-3,fill=PURPLE,width=2)

    def _messages_page(self, parent):
        page = tk.Frame(parent, bg=BG)
        page.pack(fill='both', expand=True)
        self.messages_page = page

        header = tk.Frame(page, bg=PANEL, highlightthickness=0)
        header.pack(fill='x', pady=(0, 10))
        tk.Label(header, text='СООБЩЕНИЯ', bg=PANEL, fg=TEXT,
                 font=('TkDefaultFont', 15, 'bold')).pack(side='left', padx=16, pady=12)
        tk.Label(header, text='Переписки с контактами, которым уже был отправлен отклик',
                 bg=PANEL, fg=MUTED, font=('TkDefaultFont', 8)).pack(side='left')
        tk.Label(header, text='●  Selenium / VK', bg=PANEL, fg=GREEN,
                 font=('TkDefaultFont', 8, 'bold')).pack(side='right', padx=16)

        workspace = tk.Frame(page, bg=BG)
        workspace.pack(fill='both', expand=True)
        workspace.grid_columnconfigure(0, weight=0, minsize=285)
        workspace.grid_columnconfigure(1, weight=1)
        workspace.grid_rowconfigure(0, weight=1)

        list_panel = tk.Frame(workspace, bg=PANEL, highlightthickness=0)
        list_panel.grid(row=0, column=0, sticky='nsew', padx=(0, 10))
        tk.Label(list_panel, text='ПЕРЕПИСКИ', bg=PANEL, fg=TEXT,
                 font=('TkDefaultFont', 10, 'bold')).pack(anchor='w', padx=12, pady=(12, 3))
        tk.Label(list_panel, text='Только контакты, которым уже написали', bg=PANEL, fg=MUTED,
                 font=('TkDefaultFont', 7)).pack(anchor='w', padx=12, pady=(0, 8))

        self.message_contact_buttons = {}
        if not self.message_contacts:
            tk.Label(list_panel, text='Пока нет сохранённых контактов.', bg=PANEL, fg=MUTED,
                     font=('TkDefaultFont', 9), justify='left', wraplength=245).pack(anchor='w', padx=14, pady=(18, 4))
            tk.Label(list_panel, text='Нажмите «СООБЩЕНИЕ» у реальной записи VK в разделе поиска.',
                     bg=PANEL, fg='#7898c3', font=('TkDefaultFont', 8), justify='left',
                     wraplength=245).pack(anchor='w', padx=14, pady=2)
        else:
            for idx, item in enumerate(self.message_contacts):
                name = item.get('name', 'Контакт')
                self._make_contact_item(list_panel, idx, name, item.get('preview',''), item.get('stamp',''), item.get('interest',''))

        chat = tk.Frame(workspace, bg=PANEL, highlightthickness=0)
        chat.grid(row=0, column=1, sticky='nsew')
        chat.grid_rowconfigure(1, weight=1)
        chat.grid_columnconfigure(0, weight=1)

        self.chat_header = tk.Frame(chat, bg='#07162f')
        self.chat_header.grid(row=0, column=0, sticky='ew')
        initial_name = self.message_contacts[0].get('name', 'Нет выбранного контакта') if self.message_contacts else 'Нет выбранного контакта'
        self.chat_name = tk.Label(self.chat_header, text=initial_name, bg='#07162f', fg=TEXT,
                                  font=('TkDefaultFont', 11, 'bold'))
        self.chat_name.pack(side='left', padx=14, pady=(10, 1))
        self.chat_status = tk.Label(self.chat_header, text='●  VK / Selenium', bg='#07162f', fg=GREEN,
                                    font=('TkDefaultFont', 7, 'bold'))
        self.chat_status.pack(side='left', padx=8, pady=(10, 1))
        self.chat_source = tk.Label(self.chat_header, text='Реальный VK / Selenium', bg='#07162f', fg=MUTED,
                                    font=('TkDefaultFont', 7))
        self.chat_source.pack(side='right', padx=14, pady=(10, 1))

        self.chat_body = tk.Frame(chat, bg='#061226')
        self.chat_body.grid(row=1, column=0, sticky='nsew', padx=1, pady=1)
        self.chat_body.grid_columnconfigure(0, weight=1)
        self._render_chat(initial_name if self.message_contacts else '')

        compose = tk.Frame(chat, bg=PANEL)
        compose.grid(row=2, column=0, sticky='ew', padx=10, pady=10)
        compose.grid_columnconfigure(0, weight=1)
        self.message_entry = tk.Entry(compose, bg='#07162f', fg=TEXT, insertbackground=TEXT,
                                      relief='flat', bd=0, font=('TkDefaultFont', 9))
        self.message_entry.grid(row=0, column=0, sticky='ew', ipady=10, padx=(0, 8))
        tk.Button(compose, text='➤  ОТПРАВИТЬ', command=self._send_message_ui,
                  bg='#174aa1', fg='white', activebackground='#2465d1', activeforeground='white',
                  relief='flat', bd=0, padx=14, pady=9,
                  font=('TkDefaultFont', 8, 'bold')).grid(row=0, column=1)
        tk.Label(chat, text='Отправка будет проходить через текущий авторизованный Firefox/Selenium-сеанс VK.',
                 bg=PANEL, fg=MUTED, font=('TkDefaultFont', 7)).grid(row=3, column=0, sticky='w', padx=12, pady=(0, 8))

    def _make_contact_item(self, parent, idx, name, preview, stamp, interest):
        btn = tk.Button(parent, text=f'●  {name}\n    {preview}\n    {stamp}  •  {interest}',
                        anchor='w', justify='left', relief='flat', bd=0,
                        bg='#0d2860' if idx == 0 else '#07162f', fg=TEXT,
                        activebackground='#173f89', activeforeground='white',
                        font=('TkDefaultFont', 8), padx=10, pady=9,
                        command=lambda n=name: self._select_conversation(n))
        btn.pack(fill='x', padx=8, pady=3)
        self.message_contact_buttons[name] = btn

    def _select_conversation(self, name):
        for contact, btn in self.message_contact_buttons.items():
            btn.configure(bg='#0d2860' if contact == name else '#07162f')
        self._render_chat(name)

    def _render_chat(self, name):
        if not hasattr(self, 'chat_body'):
            return
        for child in self.chat_body.winfo_children():
            child.destroy()
        self.chat_name.config(text=name or 'Нет выбранного контакта')
        if not name:
            tk.Label(self.chat_body, text='Выберите контакт из результатов поиска.', bg='#061226', fg=MUTED,
                     font=('TkDefaultFont', 10)).pack(expand=True)
            return
        contact = next((c for c in self.message_contacts if c.get('name') == name), None)
        if not contact:
            return
        history = self.chat_history.get(name, [])
        if not history:
            row = tk.Frame(self.chat_body, bg='#061226')
            row.pack(fill='x', padx=14, pady=12)
            tk.Label(row, text='ИСТОЧНИК VK', bg='#102d59', fg=CYAN, anchor='w',
                     font=('TkDefaultFont', 8, 'bold'), padx=12, pady=8).pack(fill='x')
            tk.Label(row, text=contact.get('preview',''), bg='#102d59', fg=TEXT, justify='left',
                     anchor='w', wraplength=560, font=('TkDefaultFont', 9), padx=12, pady=9).pack(fill='x')
            if contact.get('post_url'):
                tk.Button(row, text='Открыть публикацию VK', command=lambda u=contact['post_url']: self._open_url(u),
                          bg='#174aa1', fg='white', relief='flat', bd=0, padx=10, pady=6,
                          font=('TkDefaultFont', 8, 'bold')).pack(anchor='w', pady=(8,0))
        else:
            for item in history:
                side = item.get('side','me')
                text_value = item.get('text','')
                stamp = item.get('stamp','')
                row = tk.Frame(self.chat_body, bg='#061226')
                row.pack(fill='x', padx=14, pady=6)
                bubble_bg = '#102d59' if side == 'them' else '#26377c'
                anchor = 'w' if side == 'them' else 'e'
                bubble = tk.Label(row, text=text_value, bg=bubble_bg, fg=TEXT, justify='left',
                                  anchor='w', wraplength=560, font=('TkDefaultFont', 9), padx=12, pady=9)
                bubble.pack(anchor=anchor, padx=(0,100) if side == 'them' else (100,0))
                tk.Label(row, text=stamp, bg='#061226', fg=MUTED, font=('TkDefaultFont', 7)).pack(
                    anchor=anchor, padx=(8 if side == 'them' else 0, 8 if side == 'me' else 0))

    def _send_message_ui(self):
        text_value = self.message_entry.get().strip()
        if not text_value:
            return
        name = self.chat_name.cget('text') if hasattr(self, 'chat_name') else ''
        contact = next((c for c in self.message_contacts if c.get('name') == name), None)
        if not contact:
            self.log.insert('end', f'[{datetime.now():%H:%M:%S}] Нет выбранного контакта.\n'); self.log.see('end'); return
        profile_url = contact.get('profile_url','')
        if not profile_url:
            self.log.insert('end', f'[{datetime.now():%H:%M:%S}] У контакта нет ссылки на профиль VK — сообщение не отправлено.\n'); self.log.see('end'); return
        self.message_entry.delete(0, 'end')
        self.chat_status.config(text='●  Отправка…', fg='#ffd24d')
        threading.Thread(target=self._send_main_message_worker, args=(name, profile_url, text_value), daemon=True).start()

    def _send_main_message_worker(self, name, profile_url, text_value):
        ok, detail, url = self.browser.send_message(profile_url, text_value)
        self.root.after(0, lambda: self._send_main_message_finished(name, text_value, ok, detail, url))

    def _send_main_message_finished(self, name, text_value, ok, detail, url):
        self.chat_status.config(text='●  VK / Selenium' if ok else '●  Не отправлено', fg=GREEN if ok else RED)
        self.log.insert('end', f'[{datetime.now():%H:%M:%S}] {"✓" if ok else "✗"} {detail}' + (f' | {url}' if url else '') + '\n')
        self.log.see('end')
        if ok:
            self.chat_history.setdefault(name, []).append({'side':'me','text':text_value,'stamp':f'{datetime.now():%H:%M}'})
            self._save_persistent_state()
            self._render_chat(name)

    def _filter_combo(self, parent, col, label, variable, values):
        box = tk.Frame(parent, bg='#07162f', highlightthickness=0)
        box.grid(row=0, column=col, sticky='ew', padx=(0 if col == 0 else 5, 0))
        tk.Label(box, text=label, bg='#07162f', fg=MUTED,
                 font=('TkDefaultFont', 7)).pack(anchor='w', padx=10, pady=(6, 0))
        combo = ttk.Combobox(box, textvariable=variable, values=values, state='readonly')
        combo.pack(fill='x', padx=8, pady=(1, 7))
        combo.configure(font=('TkDefaultFont', 9))

    def _mini_filter(self, parent, label, value):
        box = tk.Frame(parent, bg='#07162f', highlightthickness=0)
        box.pack(fill='x', padx=10, pady=4)
        tk.Label(box, text=label, bg='#07162f', fg=MUTED,
                 font=('TkDefaultFont', 7)).pack(anchor='w', padx=8, pady=(5, 0))
        tk.Label(box, text=value, bg='#07162f', fg=TEXT,
                 font=('TkDefaultFont', 8, 'bold')).pack(anchor='w', padx=8, pady=(1, 6))

    def _set_search_mode(self, mode, persist=True):
        mode = mode if mode in ('posts','comments') else 'posts'
        self.search_mode_var.set(mode)
        if hasattr(self, 'search_mode_buttons'):
            for key, button in self.search_mode_buttons.items():
                if key == mode:
                    button.configure(bg='#0ccff5', fg='#03101d', activebackground='#22e5ff', activeforeground='#03101d')
                else:
                    button.configure(bg='#10264b', fg='#b9c9e8', activebackground='#163d72', activeforeground='#ffffff')
        if persist:
            self.settings['search_mode'] = mode
            self._save_persistent_state()
        if hasattr(self, 'search_scope_label'):
            self.search_scope_label.config(text='ПОИСК ПО КОММЕНТАРИЯМ VK' if mode=='comments' else 'ПОИСК ПО ПОСТАМ VK')
        if hasattr(self, 'results_count') and not getattr(self, '_search_running', False):
            self.results_count.config(text='Режим: ' + ('КОММЕНТАРИИ' if mode=='comments' else 'ПОСТЫ'))

    def _clear_community(self):
        self.community_url_var.set('')
        self.community_name_var.set('Не выбрано — для комментариев выберите целевое сообщество')
        self.settings['search_community_url'] = ''
        self.settings['search_community_name'] = ''
        self._save_persistent_state()

    def _open_community_picker(self):
        if self.community_picker is not None and self.community_picker.winfo_exists():
            self.community_picker.lift(); self.community_picker.focus_force(); return
        win = tk.Toplevel(self.root)
        self.community_picker = win
        win.title('Vkus — выбор сообщества VK')
        win.geometry('720x560')
        win.minsize(620, 460)
        win.configure(bg='#020713')
        win.transient(self.root)
        win.grab_set()
        head = tk.Frame(win, bg='#06122a')
        head.pack(fill='x', padx=10, pady=10)
        tk.Label(head, text='ВЫБОР ЦЕЛЕВОГО СООБЩЕСТВА', bg='#06122a', fg=CYAN,
                 font=('TkDefaultFont', 12, 'bold')).pack(anchor='w', padx=12, pady=(10, 2))
        tk.Label(head, text='Ищем реальные сообщества VK внутри текущей авторизованной сессии.',
                 bg='#06122a', fg=MUTED, font=('TkDefaultFont', 8)).pack(anchor='w', padx=12, pady=(0, 8))
        bar = tk.Frame(win, bg='#020713'); bar.pack(fill='x', padx=10, pady=(0, 8))
        var = tk.StringVar()
        entry = tk.Entry(bar, textvariable=var, bg='#07162f', fg=TEXT, insertbackground=CYAN,
                         relief='flat', bd=0, font=('TkDefaultFont', 10))
        entry.pack(side='left', fill='x', expand=True, ipady=9, padx=(0, 7))
        status = tk.Label(win, text='Введите название или ключевую фразу.', bg='#020713', fg=MUTED,
                          anchor='w', font=('TkDefaultFont', 8))
        status.pack(fill='x', padx=14, pady=(0, 4))
        urlbar = tk.Frame(win, bg='#020713')
        urlbar.pack(fill='x', padx=10, pady=(0, 7))
        url_var = tk.StringVar()
        url_entry = tk.Entry(urlbar, textvariable=url_var, bg='#07162f', fg=TEXT, insertbackground=CYAN,
                             relief='flat', bd=0, font=('TkDefaultFont', 8))
        url_entry.pack(side='left', fill='x', expand=True, ipady=7, padx=(0, 7))
        def use_url():
            value = url_var.get().strip()
            if not value.startswith(('https://vk.ru/', 'https://vk.com/')):
                status.config(text='Нужна реальная ссылка сообщества VK (vk.ru или vk.com).', fg=RED); return
            self.community_url_var.set(value.rstrip('/'))
            self.community_name_var.set(value.rstrip('/').rsplit('/', 1)[-1] or 'Сообщество VK')
            self.settings['search_community_url'] = self.community_url_var.get()
            self.settings['search_community_name'] = self.community_name_var.get()
            self._save_persistent_state()
            try: win.grab_release(); win.destroy()
            except Exception: pass
            self.community_picker = None
        tk.Button(urlbar, text='ИСПОЛЬЗОВАТЬ URL', command=use_url, bg='#10264b', fg=TEXT,
                  activebackground='#163d72', relief='flat', bd=0, padx=10, pady=6,
                  font=('TkDefaultFont', 7, 'bold')).pack(side='left')
        listbox = tk.Listbox(win, bg='#071426', fg=TEXT, selectbackground='#174aa1',
                             selectforeground='white', relief='flat', bd=0, highlightthickness=0,
                             font=('TkDefaultFont', 9), activestyle='none')
        listbox.pack(fill='both', expand=True, padx=10, pady=(0, 10))
        self.community_results = []

        def choose(_=None):
            sel = listbox.curselection()
            if not sel or sel[0] >= len(self.community_results): return
            item = self.community_results[sel[0]]
            self.community_url_var.set(item.get('url',''))
            self.community_name_var.set(item.get('name','Сообщество VK'))
            self.settings['search_community_url'] = item.get('url','')
            self.settings['search_community_name'] = item.get('name','Сообщество VK')
            self._save_persistent_state()
            try: win.grab_release(); win.destroy()
            except Exception: pass
            self.community_picker = None

        def do_search():
            q = var.get().strip()
            if not q:
                status.config(text='Введите название сообщества или ключевую фразу.', fg=RED); return
            listbox.delete(0, 'end')
            status.config(text='Ищем сообщества VK…', fg=CYAN)
            def worker():
                try:
                    found = self.browser.search_communities(q, limit=10)
                    self.root.after(0, lambda f=found: show_results(f))
                except Exception as exc:
                    self.root.after(0, lambda e=str(exc): status.config(text='Ошибка поиска сообществ: '+e[:260], fg=RED))
            threading.Thread(target=worker, daemon=True).start()

        def show_results(found):
            self.community_results = found or []
            listbox.delete(0, 'end')
            if not self.community_results:
                status.config(text='Сообщества не найдены.', fg=MUTED); return
            status.config(text=f'Загружено: {len(self.community_results)}. Нажмите «ЕЩЁ 10», чтобы догрузить следующие.', fg=GREEN)
            for item in self.community_results:
                name = item.get('name','Сообщество VK')
                desc = (item.get('description') or '').replace('\n',' ')[:150]
                listbox.insert('end', f'  {name}   —   {desc}')
            more_btn.config(state='normal')

        def load_more():
            more_btn.config(state='disabled')
            status.config(text='Догружаем следующие сообщества VK…', fg=CYAN)
            def worker_more():
                try:
                    found = self.browser.load_more_communities(batch=10)
                    self.root.after(0, lambda f=found: show_results(f))
                except Exception as exc:
                    self.root.after(0, lambda e=str(exc): status.config(text='Не удалось догрузить: '+e[:220], fg=RED))
                    self.root.after(0, lambda: more_btn.config(state='normal'))
            threading.Thread(target=worker_more, daemon=True).start()

        tk.Button(bar, text='ПОИСК', command=do_search, bg='#174aa1', fg='white', activebackground='#2465d1',
                  relief='flat', bd=0, padx=16, pady=7, cursor='hand2', font=('TkDefaultFont', 8, 'bold')).pack(side='left')
        more_btn = tk.Button(win, text='ЕЩЁ 10', command=load_more, state='disabled', bg='#10264b', fg=TEXT, activebackground='#163d72', relief='flat', bd=0, padx=16, pady=7, font=('TkDefaultFont', 8, 'bold'))
        more_btn.pack(pady=(0, 6))
        tk.Button(win, text='ВЫБРАТЬ', command=choose, bg='#12386c', fg=TEXT, activebackground='#1b5799',
                  relief='flat', bd=0, padx=16, pady=7, font=('TkDefaultFont', 8, 'bold')).pack(pady=(0, 10))
        listbox.bind('<Double-Button-1>', choose)
        entry.bind('<Return>', lambda _e: do_search())
        win.protocol('WM_DELETE_WINDOW', lambda: (win.grab_release(), win.destroy(), setattr(self, 'community_picker', None)))
        entry.focus_set()

    def _search_action(self):
        q = self.search_query_var.get().strip()
        region = self.region_var.get()
        city = self.city_var.get()
        self.settings['search_query'] = q
        self.settings['search_region'] = region
        self.settings['search_city'] = city
        self.settings['search_source'] = self.search_source_var.get()
        self.settings['search_state'] = self.search_state_var.get()
        self.settings['search_year'] = self.search_year_var.get()
        self.settings['search_month'] = self.search_month_var.get()
        mode = self.search_mode_var.get()
        year = self.search_year_var.get()
        month = self.search_month_var.get()
        self.settings['search_mode'] = mode
        self._save_persistent_state()

        if not q and city in ('Все города', 'Все'):
            self.results_count.config(text='Нужен запрос')
            self._render_results([])
            return

        self._search_generation += 1
        generation = self._search_generation
        community_url = self.community_url_var.get().strip()
        community_name = self.community_name_var.get().strip()
        if mode == 'comments' and not community_url:
            self.results_count.config(text='Выберите сообщество')
            self._render_results([], status='ВЫБЕРИТЕ СООБЩЕСТВО VK')
            return
        self.settings['search_community_url'] = community_url
        self.settings['search_community_name'] = community_name
        self._save_persistent_state()
        self._search_running = True
        self.results_count.config(text='Идёт поиск… ' + ('КОММЕНТАРИИ' if mode=='comments' else 'ПОСТЫ'))
        self._render_results([], status='ИДЁТ ПОИСК…')
        if hasattr(self, 'log'):
            self.log.insert('end', f'[{datetime.now():%H:%M:%S}] VK поиск: запрос={q or "—"}, регион={region}, город={city}…\\n')
            self.log.see('end')

        threading.Thread(
            target=self._search_worker,
            args=(q, region, city, mode, generation, year, month, community_url),
            daemon=True
        ).start()

    def _search_worker(self, q, region, city, mode='posts', generation=None, year='Все годы', month='Все месяцы', community_url=''):
        try:
            if mode == 'comments' and community_url:
                found = self.browser.search_community_comments(community_url, q, city, region, year=year, month=month, limit=0)
            else:
                found = self.browser.search_vk(q, city, region, mode=mode, limit=0, year=year, month=month)
            self.root.after(0, lambda: self._search_finished(found, q, region, city, mode, generation))

        except Exception as exc:
            detail = f'{type(exc).__name__}: {exc}'
            self.logger.exception('VK search failed')
            self.root.after(0, lambda d=detail, g=generation: self._search_failed(d, g))

    def _search_finished(self, found, q, region, city, mode, generation):
        if generation is not None and generation != self._search_generation:
            return
        self._search_running = False

        # UI updates are kept on Tk's main thread.
        self.search_results = [
            (item.get('comment_text') or item.get('text', ''), item.get('interest', 'Не определена'),
             item.get('date_text') or item.get('age', 'VK'), item.get('url', ''), item.get('profile_url', ''),
             item.get('kind', mode), item.get('author_name', ''), item.get('username', ''),
             item.get('city', city), item.get('post_url', ''))
            for item in found
        ]
        self.settings['search_results_json'] = json.dumps(self.search_results, ensure_ascii=False)
        self._save_persistent_state()
        self.results_count.config(text=f'{"Комментарии" if mode=="comments" else "Посты"}: {len(self.search_results)}')
        self._render_results(self.search_results)
        if hasattr(self, 'log'):
            self.log.insert('end', f'[{datetime.now():%H:%M:%S}] VK поиск завершён: результатов={len(self.search_results)}\\n')
            self.log.see('end')

    def _search_failed(self, detail, generation=None):
        if generation is not None and generation != self._search_generation:
            return
        self._search_running = False
        self.search_results = []
        self.results_count.config(text='Ошибка VK поиска')
        self._render_results([], error=detail)
        if hasattr(self, 'log'):
            self.log.insert('end', f'[{datetime.now():%H:%M:%S}] Ошибка VK поиска: {detail}\n')
            self.log.see('end')

    def _render_results(self, results, error=None, status=None):
        for child in self.results_frame.winfo_children(): child.destroy()
        self.results_canvas.delete('empty_state'); self._empty_state_active=not bool(results)
        if not results:
            def redraw_empty(_=None):
                if not getattr(self,'_empty_state_active',False): return
                w=max(1,self.results_canvas.winfo_width());h=max(1,self.results_canvas.winfo_height());self.results_canvas.delete('empty_state')
                if error:
                    self.results_canvas.create_text(w/2,max(70,h/2-45),text='VK / ОШИБКА ПОИСКА',fill=RED,font=('TkDefaultFont',13,'bold'),tags='empty_state')
                    self.results_canvas.create_text(w/2,max(110,h/2),text=str(error)[:360],fill='#d9e7ff',width=max(360,w-100),justify='center',font=('TkDefaultFont',8),tags='empty_state')
                elif status:
                    self.results_canvas.create_text(w/2,h/2-26,text='⌕',fill=CYAN,font=('TkDefaultFont',42,'bold'),tags='empty_state')
                    self.results_canvas.create_text(w/2,h/2+25,text=status,fill='#d9e7ff',font=('TkDefaultFont',11,'bold'),tags='empty_state')
                else:
                    self.results_canvas.create_text(w/2,h/2-24,text='⌕',fill='#1766b8',font=('TkDefaultFont',42,'bold'),tags='empty_state')
                    self.results_canvas.create_text(w/2,h/2+24,text='ГОТОВ К ПОИСКУ VK',fill='#d9e7ff',font=('TkDefaultFont',11,'bold'),tags='empty_state')
            self.results_canvas.bind('<Configure>',redraw_empty,add='+');self.results_canvas.after(30,redraw_empty);return
        self.results_canvas.yview_moveto(0)
        for idx,result in enumerate(results):
            text_value=result[0] if len(result)>0 else ''
            age=result[2] if len(result)>2 else 'VK';source_url=result[3] if len(result)>3 else ''
            profile_url=result[4] if len(result)>4 else '';kind=result[5] if len(result)>5 else self.search_mode_var.get()
            author=result[6] if len(result)>6 else '';username=result[7] if len(result)>7 else ''
            city=result[8] if len(result)>8 else self.city_var.get();post_url=result[9] if len(result)>9 else ''
            card=tk.Frame(self.results_frame,bg='#071426',highlightthickness=0);card.pack(fill='x',pady=4)
            accent=tk.Frame(card,bg=CYAN if idx%2==0 else PURPLE,width=4);accent.pack(side='left',fill='y')
            avatar=tk.Canvas(card,width=46,height=46,bg='#071426',highlightthickness=0);avatar.pack(side='left',padx=(11,9),pady=10)
            avatar.create_oval(4,4,42,42,outline=CYAN if idx%2==0 else PURPLE,width=2)
            initials=''.join(x[0] for x in author.split()[:2]) or 'VK';avatar.create_text(23,23,text=initials[:3],fill='#fff',font=('TkDefaultFont',7,'bold'))
            body=tk.Frame(card,bg='#071426');body.pack(side='left',fill='both',expand=True,padx=(0,10),pady=9)
            name_line=author or 'Автор VK не определён'; name_line += (f'  @{username}' if username and username.lower()!=author.lower() else '')
            tk.Label(body,text=name_line,bg='#071426',fg='#edf4ff',anchor='w',font=('TkDefaultFont',10,'bold')).pack(fill='x')
            tk.Label(body,text=f'⌖ {city or "Город не указан"}   •   VK   •   {"КОММЕНТАРИЙ" if kind=="comments" else "ПОСТ"}   •   {age}',bg='#071426',fg='#6f93c3',anchor='w',font=('TkDefaultFont',7)).pack(fill='x',pady=(2,0))
            tk.Label(body,text=text_value,bg='#071426',fg='#d9e7ff',anchor='w',justify='left',wraplength=760,font=('TkDefaultFont',9)).pack(fill='x',pady=(7,0))
            NeonMessageButton(card,text='✈  СООБЩЕНИЕ',command=lambda r=result:self._add_search_contact(r),width=158,height=38).pack(side='right',padx=10,pady=10)
        self._results_frame_configure()

    def _add_search_contact(self, result):
        vals=list(result) if isinstance(result,(tuple,list)) else [str(result)]
        text_value=vals[0] if len(vals)>0 else ''
        post_url=vals[9] if len(vals)>9 and vals[9] else (vals[3] if len(vals)>3 else '')
        profile_url=vals[4] if len(vals)>4 else ''
        author=vals[6] if len(vals)>6 else ''
        username=vals[7] if len(vals)>7 else ''
        city=vals[8] if len(vals)>8 else self.city_var.get()
        existing=next((c for c in self.message_contacts if (profile_url and c.get('profile_url')==profile_url) or (post_url and c.get('post_url')==post_url and c.get('preview')==text_value)),None)
        if existing: self._open_chat_popup(existing);return
        name=author or (f'@{username}' if username else 'Контакт VK')
        contact={'name':name,'username':username,'preview':text_value[:240],'stamp':vals[2] if len(vals)>2 else 'сейчас','interest':'','post_url':post_url,'source_url':vals[3] if len(vals)>3 else '','profile_url':profile_url,'city':city,'source_type':vals[5] if len(vals)>5 else self.search_mode_var.get()}
        self.message_contacts.insert(0,contact);self._save_persistent_state()
        if self.messages_page is not None and self.messages_page.winfo_exists(): self.messages_page.destroy();self.messages_page=None
        self._open_chat_popup(contact)

    def _open_chat_popup(self, contact):
        if self.chat_window is not None and self.chat_window.winfo_exists():
            self.chat_window.deiconify()
            self.chat_window.lift()
            self.chat_window.focus_force()
            self._populate_chat_popup(contact)
            return

        win = tk.Toplevel(self.root)
        self.chat_window = win
        win.title(f'Vkus — {contact["name"]}')
        win.geometry('520x620')
        win.minsize(420, 480)
        win.configure(bg=BG)
        win.transient(self.root)
        win.protocol('WM_DELETE_WINDOW', win.withdraw)

        header = tk.Frame(win, bg='#07162f')
        header.pack(fill='x')
        self.popup_name = tk.Label(header, text=contact['name'], bg='#07162f', fg=TEXT,
                                   font=('TkDefaultFont', 11, 'bold'))
        self.popup_name.pack(side='left', padx=12, pady=10)
        tk.Label(header, text='● VK / Selenium', bg='#07162f', fg=GREEN,
                 font=('TkDefaultFont', 7, 'bold')).pack(side='left')
        tk.Button(header, text='×', command=win.withdraw, bg='#07162f', fg=MUTED,
                  activebackground='#102d59', activeforeground='white', relief='flat', bd=0,
                  font=('TkDefaultFont', 16, 'bold')).pack(side='right', padx=8)

        self.popup_body = tk.Canvas(win, bg='#061226', highlightthickness=0, bd=0)
        self.popup_body.pack(fill='both', expand=True, padx=1, pady=1)
        self.popup_body.bind('<Configure>', self._draw_popup_background)
        self.popup_bg_photo = None

        compose = tk.Frame(win, bg=PANEL)
        compose.pack(fill='x', padx=8, pady=8)
        compose.grid_columnconfigure(0, weight=1)
        self.popup_entry = tk.Entry(compose, bg='#07162f', fg=TEXT, insertbackground=TEXT,
                                    relief='flat', bd=0, font=('TkDefaultFont', 9))
        self.popup_entry.grid(row=0, column=0, sticky='ew', ipady=9, padx=(0, 7))
        tk.Button(compose, text='➤', command=self._send_popup_message, bg='#174aa1', fg='white',
                  activebackground='#2465d1', activeforeground='white', relief='flat', bd=0,
                  padx=12, pady=8, font=('TkDefaultFont', 9, 'bold')).grid(row=0, column=1)
        tk.Label(win, text='Чат остаётся отдельным окном: его можно закрыть и снова открыть, не теряя поиск.',
                 bg=PANEL, fg=MUTED, font=('TkDefaultFont', 7)).pack(fill='x', padx=10, pady=(0, 7))
        self._populate_chat_popup(contact)

    def _draw_popup_background(self, _=None):
        if not hasattr(self, 'popup_body') or not self.popup_body.winfo_exists():
            return
        w = max(1, self.popup_body.winfo_width())
        h = max(1, self.popup_body.winfo_height())
        self.popup_body.delete('bg')
        # No animal/image in the application workspace.
        # The panther/tiger is intentionally used only by LockScreen.
        self.popup_body.create_rectangle(0, 0, w, h, fill=BG, outline='', tags='bg')
        self.popup_body.create_line(0, h-70, w, 35, fill='#061a42', width=5, tags='bg')
        self.popup_body.create_line(0, h-70, w, 35, fill='#092f78', width=1, tags='bg')
        self.popup_body.tag_lower('bg')
        if hasattr(self, 'chat_contact'):
            self._draw_popup_messages()

    def _draw_popup_messages(self):
        if not self.chat_window or not self.chat_window.winfo_exists():
            return
        c=self.popup_body; c.delete('msg'); w=max(300,c.winfo_width())
        contact=getattr(self,'chat_contact',{}); y=24
        width=min(410,max(240,w-50))
        c.create_rectangle(18,y,18+width,y+100,fill='#0b2345',outline='#18d7ff',width=1,tags='msg')
        c.create_text(30,y+10,text='ИСТОЧНИК VK',fill=CYAN,anchor='nw',font=('TkDefaultFont',8,'bold'),tags='msg')
        c.create_text(30,y+32,text=contact.get('preview','Сообщение из найденной публикации VK.'),fill=TEXT,anchor='nw',width=width-24,font=('TkDefaultFont',9),tags='msg')
        y+=122
        for item in self.chat_history.get(contact.get('name',''),[]):
            side=item.get('side','me'); text_value=item.get('text',''); stamp=item.get('stamp','')
            width=min(410,max(220,w-70)); x0=18 if side=='them' else max(18,w-width-18); x1=x0+width
            fill='#0b2345' if side=='them' else '#30205d'; outline='#18d7ff' if side=='them' else '#a83cff'
            c.create_rectangle(x0,y,x1,y+66,fill=fill,outline=outline,width=1,tags='msg')
            c.create_text(x0+12,y+10,text=text_value,fill=TEXT,anchor='nw',width=width-24,font=('TkDefaultFont',9),tags='msg')
            c.create_text(x1-10,y+51,text=stamp,fill=MUTED,anchor='e',font=('TkDefaultFont',7),tags='msg'); y+=86

    def _populate_chat_popup(self, contact):
        if not self.chat_window or not self.chat_window.winfo_exists():
            return
        self.chat_contact = contact
        self.popup_name.config(text=contact['name'])
        self.popup_bg_photo = None
        self._draw_popup_background()

    def _send_popup_message(self):
        text_value = self.popup_entry.get().strip()
        if not text_value:
            return
        contact = getattr(self, 'chat_contact', {})
        profile_url = contact.get('profile_url', '')
        if not profile_url:
            self.log.insert('end',
                f'[{datetime.now():%H:%M:%S}] Сообщение не отправлено: у контакта нет ссылки на профиль VK.\\n')
            self.log.see('end')
            return

        self.log.insert('end',
            f'[{datetime.now():%H:%M:%S}] Отправка сообщения через VK/Selenium…\\n')
        self.log.see('end')
        self._last_popup_text = text_value
        self.popup_entry.delete(0, 'end')
        threading.Thread(
            target=self._send_popup_worker,
            args=(profile_url, text_value),
            daemon=True
        ).start()

    def _send_popup_worker(self, profile_url, text_value):
        ok, detail, url = self.browser.send_message(profile_url, text_value)
        self.root.after(0, lambda: self._send_popup_finished(ok, detail, url))

    def _send_popup_finished(self, ok, detail, url):
        prefix='✓' if ok else '✗'
        self.log.insert('end', f'[{datetime.now():%H:%M:%S}] {prefix} {detail}' + (f' | {url}' if url else '') + '\n')
        self.log.see('end')
        if ok and hasattr(self,'popup_body'):
            name=self.chat_contact.get('name',''); text_value=getattr(self,'_last_popup_text','')
            if text_value:
                self.chat_history.setdefault(name,[]).append({'side':'me','text':text_value,'stamp':f'{datetime.now():%H:%M}'})
                self._save_persistent_state()
            self._draw_popup_messages()

    def _footer(self):
        f = tk.Frame(self.root, bg='#07162f', height=27, highlightthickness=0)
        f.pack(fill='x')
        f.pack_propagate(False)
        tk.Label(f, text='Vkus  |  Версия 3.1  |  Kali Linux', bg='#07162f', fg=MUTED,
                 font=('TkDefaultFont', 7)).pack(side='left', padx=14)
        tk.Label(f, text='УНИВЕРСАЛЬНЫЙ ИНСТРУМЕНТ', bg='#07162f', fg=MUTED,
                 font=('TkDefaultFont', 7)).pack(side='right', padx=14)

    def _summary_text(self):
        total = len(self.checks)
        ok = sum(1 for r in self.status.values() if r and r.ok)
        bad = sum(1 for r in self.status.values() if r and not r.ok)
        return f'✓  ИТОГ ПРОВЕРКИ     Успешно: {ok}     Ошибки: {bad}     Не выполнено: {total-ok-bad}'

    def _set_row(self, result, running=False):
        row, detail, lamp = self.rows[result.key]
        if running:
            lamp.config(fg='#ffd24d')
            detail.config(text='Выполняется…', fg='#ffd24d')
            return
        lamp.config(fg=GREEN if result.ok else RED)
        detail.config(text=f'{result.detail[:88]}  [{result.duration:.1f} с]', fg=GREEN if result.ok else RED)

    def _start_ui(self, key):
        if key in self.rows:
            _, detail, lamp = self.rows[key]
            lamp.config(fg='#ffd24d')
            detail.config(text='Выполняется…', fg='#ffd24d')

    def _result_ui(self, result):
        self._set_row(result)
        stamp = datetime.now().strftime('%H:%M:%S')
        self.log.insert('end', f'[{stamp}] {result.title:<14} — {"Успешно" if result.ok else "Ошибка"} — {result.duration:.1f} с\n')
        self.log.see('end')
        self.status[result.key] = result
        self._save_persistent_state()
        self.summary.config(text=self._summary_text())
        if result.key == 'auth':
            self.auth_header.config(
                text='●  Авторизован' if result.ok else '●  Авторизация не подтверждена',
                fg=GREEN if result.ok else RED)

    def _log(self, text):
        self.logger.info(text)

    def run_all(self):
        self.log.insert('end', f'\n[{datetime.now():%H:%M:%S}] === ПОЛНАЯ ПРОВЕРКА ===\n')
        self.log.insert('end', 'Авторизация является блокирующим этапом: после открытия Firefox Vkus ждёт завершения входа.\n')
        self.log.see('end')
        self.last.config(text=f'Последняя: {datetime.now():%d.%m.%Y %H:%M:%S}')
        def work():
            runner = CheckRunner(
                self.checks,
                on_start=lambda k: self.root.after(0, self._start_ui, k),
                on_result=lambda r: self.root.after(0, self._result_ui, r),
                on_log=self._log)
            started = datetime.now()
            runner.run_all()
            total = (datetime.now() - started).total_seconds()
            self.root.after(0, lambda: self.log.insert('end',
                f'[{datetime.now():%H:%M:%S}] === ЦЕПОЧКА ЗАВЕРШЕНА: {total:.1f} с ===\n'))
        threading.Thread(target=work, daemon=True).start()

    def run_one(self, key):
        def work():
            runner = CheckRunner(
                [self.by_key[key]],
                on_start=lambda k: self.root.after(0, self._start_ui, k),
                on_result=lambda r: self.root.after(0, self._result_ui, r),
                on_log=self._log)
            runner.run_all()
        threading.Thread(target=work, daemon=True).start()

    def reset_results(self):
        if not messagebox.askyesno('Сброс результатов',
                                   'Сбросить сохранённые результаты проверки?\n\n'
                                   'Логи при этом не будут удалены.'):
            return
        self.status.clear()
        self.settings.pop('last_results_json', None)
        self.settings.pop('last_check_at', None)
        save_settings(self.settings)
        for key, (row, detail, lamp) in self.rows.items():
            detail.config(text='Не запускалось', fg=MUTED)
            lamp.config(fg='#7f8da5')
        self.last.config(text='Последняя: —')
        self.summary.config(text=self._summary_text())
        self.auth_header.config(text='●  Сессия не проверена', fg=MUTED)
        self.log.insert('end', f'[{datetime.now():%H:%M:%S}] Результаты проверки сброшены. Логи сохранены.\n')
        self.log.see('end')

    def save_config(self):
        if hasattr(self, 'setup_query_var'):
            self.settings['search_query'] = self.setup_query_var.get().strip()
            self.settings['community_url'] = self.setup_community_var.get().strip()
            self.settings['post_url'] = self.setup_post_var.get().strip()
        if hasattr(self, 'search_query_var'):
            self.settings['search_query'] = self.search_query_var.get().strip()
        self._save_persistent_state()
        self.log.insert('end', f'[{datetime.now():%H:%M:%S}] Настройки сохранены.\n')
        self.log.see('end')

    def _open_url(self, url):
        import webbrowser
        webbrowser.open(url)

    def close(self):
        try:
            if self.splash is not None:
                self.splash.stop()
        except Exception:
            pass
        try:
            if getattr(self, 'lock', None) is not None:
                self.lock.dispose()
        except Exception:
            pass
        self.browser.stop()
        self.root.destroy()

    def run(self):
        self.root.mainloop()
