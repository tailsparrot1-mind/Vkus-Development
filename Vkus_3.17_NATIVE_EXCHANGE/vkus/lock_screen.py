import hashlib
import json
import shutil
import subprocess
import threading
from pathlib import Path
import tkinter as tk
from tkinter import messagebox

try:
    from PIL import Image, ImageTk
except ImportError:
    Image = ImageTk = None

BG = '#020714'
TEXT = '#eef5ff'
MUTED = '#9bb0d1'
CYAN = '#19d8ff'
PURPLE = '#a83cff'
GREEN = '#18e99a'
RED = '#ff4f68'
YELLOW = '#ffd24d'


def hash_value(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def fingerprint_available() -> tuple[bool, str]:
    verify = shutil.which('fprintd-verify')
    listing = shutil.which('fprintd-list')
    if not verify or not listing:
        return False, 'fprintd не установлен'
    try:
        user = subprocess.run([listing, '-l', str(__import__('getpass').getuser())], capture_output=True, text=True, timeout=5)
        if user.returncode != 0:
            return False, 'fprintd не видит пользователя/устройство'
        out = (user.stdout + user.stderr).lower()
        if 'no devices' in out or 'нет устройств' in out:
            return False, 'Сканер отпечатка не найден'
        return True, 'Сканер отпечатка доступен'
    except Exception as exc:
        return False, f'Проверка fprintd: {exc}'


class LockScreen:
    """Multi-method local lock: password, PIN, graphical pattern, touch gesture and Linux fprintd."""
    def __init__(self, root, settings, asset_path, on_unlock, on_close, save_settings):
        self.root = root
        self.settings = settings
        self.asset_path = Path(asset_path)
        self.on_unlock = on_unlock
        self.on_close = on_close
        self.save_settings = save_settings
        self.canvas = None
        self.bg_image = None
        self.message = None
        self.entry = None
        self.mode = 'password'
        self.pattern = []
        self.touch_sequence = []
        self.touch_active = False
        self.touch_buttons = {}
        self.pin_buttons = {}
        self.fp_button = None
        self._disposed = False
        self._return_binding = None
        self._escape_binding = None
        self._after_jobs = set()
        self._build()

    def _build(self):
        self.root.configure(bg=BG)
        self.root.title('Vkus — Заблокировано')
        self.root.protocol('WM_DELETE_WINDOW', self.on_close)
        self._return_binding = self.root.bind('<Return>', lambda _e: self.try_password())
        self._escape_binding = self.root.bind('<Escape>', lambda _e: self.on_close())
        self.canvas = tk.Canvas(self.root, bg=BG, highlightthickness=0, bd=0)
        self.canvas.pack(fill='both', expand=True)
        self.canvas.bind('<Configure>', self._redraw)

    def _redraw(self, _event=None):
        w = max(900, self.root.winfo_width())
        h = max(600, self.root.winfo_height())
        self.canvas.delete('all')
        self.entry = None
        self.pin_buttons.clear(); self.touch_buttons.clear(); self.fp_button = None
        if Image is not None and self.asset_path.exists():
            try:
                img = Image.open(self.asset_path).convert('RGB')
                src_w, src_h = img.size
                scale = max(w / src_w, h / src_h)
                nw, nh = int(src_w * scale), int(src_h * scale)
                img = img.resize((nw, nh), Image.Resampling.LANCZOS)
                left, top = (nw - w) // 2, (nh - h) // 2
                img = img.crop((left, top, left + w, top + h))
                self.bg_image = ImageTk.PhotoImage(img)
                self.canvas.create_image(0, 0, image=self.bg_image, anchor='nw')
            except Exception:
                self.canvas.create_rectangle(0, 0, w, h, fill=BG, outline='')
        else:
            self.canvas.create_rectangle(0, 0, w, h, fill=BG, outline='')
        self.canvas.create_rectangle(0, 0, w, h, fill='#020714', stipple='gray50', outline='')
        self._draw_panel(w, h)

    def _draw_panel(self, w, h):
        panel_w = min(570, int(w * 0.42)); panel_h = 610
        x = int(w * 0.265); y = int(h * 0.55)
        x0, y0 = x - panel_w // 2, y - panel_h // 2
        self.canvas.create_rectangle(x0, y0, x0 + panel_w, y0 + panel_h, fill='#061229', outline='#264f96', width=1)
        self.canvas.create_rectangle(x0 + 1, y0 + 1, x0 + panel_w - 1, y0 + panel_h - 1, outline='#5f2cff', width=1)
        self.canvas.create_text(x, y0 + 50, text='🔒', fill=CYAN, font=('TkDefaultFont', 25, 'bold'))
        self.canvas.create_text(x, y0 + 88, text='ДОСТУП К VKUS', fill=TEXT, font=('TkDefaultFont', 18, 'bold'))
        self.canvas.create_text(x, y0 + 115, text='Выберите способ разблокировки', fill=MUTED, font=('TkDefaultFont', 9))

        tabs = [('password','Пароль'), ('pin','PIN'), ('pattern','Графический'), ('touch','Тач'), ('fingerprint','Отпечаток')]
        tab_y = y0 + 145
        tab_w = (panel_w - 40) // len(tabs)
        for i, (key, label) in enumerate(tabs):
            tx = x0 + 20 + i * tab_w
            active = key == self.mode
            b = tk.Button(self.canvas, text=label, command=lambda k=key: self.set_mode(k), bg='#183a70' if active else '#0a1c35', fg='white' if active else MUTED, activebackground='#2559a8', activeforeground='white', relief='flat', bd=0, font=('TkDefaultFont', 8, 'bold'), cursor='hand2')
            self.canvas.create_window(tx, tab_y, width=tab_w-4, height=34, window=b, anchor='nw')

        if self.mode == 'password': self._password_ui(x0, y0, panel_w)
        elif self.mode == 'pin': self._pin_ui(x, y0)
        elif self.mode == 'pattern': self._pattern_ui(x, y0)
        elif self.mode == 'touch': self._touch_ui(x, y0)
        else: self._fingerprint_ui(x, y0, panel_w)

        self.message = self.canvas.create_text(x, y0 + panel_h - 42, text='Локальная защита интерфейса Vkus', fill=MUTED, font=('TkDefaultFont', 8))
        self.canvas.create_text(28, h - 28, anchor='w', text='Vkus  |  Kali Linux  |  Локальная защита', fill='#7188aa', font=('TkDefaultFont', 8))

    def set_mode(self, mode):
        self.mode = mode; self.pattern = []; self.touch_sequence = []
        self._redraw()

    def _password_ui(self, x0, y0, panel_w):
        self.canvas.create_text(x0 + panel_w/2, y0 + 205, text='Введите пароль', fill=TEXT, font=('TkDefaultFont', 11, 'bold'))
        self.entry = tk.Entry(self.canvas, show='•', bg='#071a37', fg=TEXT, insertbackground=TEXT, relief='flat', bd=0, font=('TkDefaultFont', 13))
        self.entry.bind('<Return>', lambda _e: self.try_password())
        self.canvas.create_window(x0 + 35, y0 + 230, width=panel_w - 70, height=45, window=self.entry, anchor='nw')
        self._action_button(x0 + 35, y0 + 290, panel_w - 70, '→  РАЗБЛОКИРОВАТЬ', self.try_password)
        entry_ref = self.entry
        self._schedule_focus(entry_ref)

    def _pin_ui(self, x, y0):
        self.canvas.create_text(x, y0 + 195, text='Введите PIN-код', fill=TEXT, font=('TkDefaultFont', 11, 'bold'))
        self.entry = tk.Entry(self.canvas, show='•', bg='#071a37', fg=TEXT, insertbackground=TEXT, relief='flat', bd=0, justify='center', font=('TkDefaultFont', 16))
        self.canvas.create_window(x-150, y0+220, width=300, height=42, window=self.entry, anchor='nw')
        self._action_button(x-150, y0+275, 300, 'РАЗБЛОКИРОВАТЬ', self.try_pin)
        entry_ref = self.entry
        self._schedule_focus(entry_ref)

    def _pin_button(self, x, y, label, command):
        b = tk.Button(self.canvas, text=label, command=command, bg='#0d2950', fg=TEXT, activebackground='#235ca5', activeforeground='white', relief='flat', bd=0, font=('TkDefaultFont', 12, 'bold'), cursor='hand2')
        self.canvas.create_window(x, y, width=62, height=42, window=b, anchor='center')
        return b

    def _pattern_ui(self, x, y0):
        self.canvas.create_text(x, y0 + 190, text='Соедините точки в заданном порядке', fill=TEXT, font=('TkDefaultFont', 10, 'bold'))
        self.canvas.create_text(x, y0 + 215, text='Нажатия мышью или сенсорным экраном', fill=MUTED, font=('TkDefaultFont', 8))
        coords = {}
        start_x, start_y, gap = x-105, y0+275, 105
        for n in range(1,10):
            col=(n-1)%3; row=(n-1)//3; px=start_x+col*gap; py=start_y+row*gap
            coords[n]=(px,py)
            c=tk.Canvas(self.canvas,width=54,height=54,bg='#0b2344',highlightthickness=2,highlightbackground='#6f35ff',cursor='hand2')
            c.create_oval(17,17,37,37,fill=CYAN,outline='')
            c.create_text(27,46,text=str(n),fill=MUTED,font=('TkDefaultFont',7))
            c.bind('<Button-1>',lambda e,k=n:self.pattern_press(k))
            self.canvas.create_window(px,py,width=54,height=54,window=c,anchor='center')
        self._action_button(x-150, y0+530, 300, 'СБРОСИТЬ / ПРОВЕРИТЬ', self.try_pattern)

    def pattern_press(self, n):
        if n not in self.pattern:
            self.pattern.append(n)
            self._set_message('Ключ: ' + ' • '.join(map(str,self.pattern)), MUTED)
            if len(self.pattern) >= 5: self.try_pattern()

    def _touch_ui(self, x, y0):
        self.canvas.create_text(x, y0 + 195, text='Тач-жест', fill=TEXT, font=('TkDefaultFont', 11, 'bold'))
        self.canvas.create_text(x, y0 + 218, text='Нажмите 5 зон в заданной последовательности', fill=MUTED, font=('TkDefaultFont', 8))
        labels=['1','2','3','4','5']; positions=[(-130,280),(0,250),(130,280),(-70,380),(70,380)]
        for label,(dx,dy) in zip(labels,positions):
            b=tk.Button(self.canvas,text=label,command=lambda k=label:self.touch_press(k),bg='#0d2950',fg=TEXT,activebackground='#2559a8',relief='flat',bd=0,font=('TkDefaultFont',14,'bold'),cursor='hand2')
            self.canvas.create_window(x+dx,y0+dy,width=70,height=55,window=b,anchor='center')
        self._action_button(x-150,y0+530,300,'СБРОСИТЬ / ПРОВЕРИТЬ',self.try_touch)

    def touch_press(self, n):
        self.touch_sequence.append(n); self._set_message('Тач: ' + ' • '.join(self.touch_sequence), MUTED)
        if len(self.touch_sequence)>=5: self.try_touch()

    def _fingerprint_ui(self, x, y0, panel_w):
        ok, status = fingerprint_available()
        self.canvas.create_text(x, y0+205, text='Биометрическая проверка', fill=TEXT, font=('TkDefaultFont',11,'bold'))
        self.canvas.create_text(x, y0+235, text='Linux fprintd', fill=MUTED, font=('TkDefaultFont',9))
        icon='◉' if ok else '○'
        self.canvas.create_text(x, y0+300, text=icon, fill=GREEN if ok else RED, font=('TkDefaultFont',52,'bold'))
        self.canvas.create_text(x, y0+350, text=status, fill=GREEN if ok else RED, font=('TkDefaultFont',9))
        self.fp_button = self._action_button(x-panel_w//2+35,y0+395,panel_w-70,'СКАНИРОВАТЬ ОТПЕЧАТОК',self.try_fingerprint,enabled=ok)
        if not ok:
            self.canvas.create_text(x,y0+465,text='Установите fprintd и зарегистрируйте палец\nдля использования этого способа.',fill=MUTED,font=('TkDefaultFont',8),justify='center')

    def _action_button(self,x,y,width,text,command,enabled=True):
        b=tk.Button(self.canvas,text=text,command=command,bg='#2458f5' if enabled else '#15243b',fg='white' if enabled else '#657995',activebackground='#7c2cff',activeforeground='white',relief='flat',bd=0,font=('TkDefaultFont',10,'bold'),cursor='hand2' if enabled else 'arrow',state='normal' if enabled else 'disabled')
        self.canvas.create_window(x,y,width=width,height=46,window=b,anchor='nw')
        return b

    def _schedule_focus(self, widget):
        if self._disposed:
            return
        def focus():
            self._after_jobs.discard(job)
            if self._disposed:
                return
            try:
                if widget is not None and widget.winfo_exists():
                    widget.focus_set()
            except tk.TclError:
                pass
        try:
            job = self.root.after(80, focus)
            self._after_jobs.add(job)
        except tk.TclError:
            pass

    def _set_message(self,text,color=MUTED):
        if self._disposed:
            return
        try:
            if self.canvas is not None and self.canvas.winfo_exists() and self.message:
                self.canvas.itemconfig(self.message,text=text,fill=color)
        except tk.TclError:
            pass

    def dispose(self):
        if self._disposed:
            return
        self._disposed = True
        for job in list(self._after_jobs):
            try:
                self.root.after_cancel(job)
            except tk.TclError:
                pass
        self._after_jobs.clear()
        for sequence, funcid in (('<Return>', self._return_binding), ('<Escape>', self._escape_binding)):
            if funcid:
                try:
                    self.root.unbind(sequence, funcid)
                except tk.TclError:
                    pass
        self._return_binding = None
        self._escape_binding = None
        try:
            if self.canvas is not None and self.canvas.winfo_exists():
                self.canvas.destroy()
        except tk.TclError:
            pass
        self.canvas = None
        self.message = None
        self.entry = None

    def fail(self,text):
        if self._disposed:
            return
        self._set_message(text,RED)
        try: self.root.bell()
        except tk.TclError: pass

    def try_password(self):
        if self._disposed:
            return
        value = ''
        if self.entry is not None:
            try:
                if self.entry.winfo_exists():
                    value = self.entry.get()
            except tk.TclError:
                self.entry = None
        if hash_value(value)==self.settings.get('password_hash'):
            self.on_unlock()
        else:
            if self.entry is not None:
                try:
                    if self.entry.winfo_exists(): self.entry.delete(0,'end')
                except tk.TclError:
                    self.entry = None
            self.fail('Неверный пароль')

    def try_pin(self):
        if self._disposed:
            return
        value = ''
        if self.entry is not None:
            try:
                if self.entry.winfo_exists():
                    value = self.entry.get()
            except tk.TclError:
                self.entry = None
        if value.isdigit() and hash_value(value)==self.settings.get('pin_hash'):
            self.on_unlock()
        else:
            if self.entry is not None:
                try:
                    if self.entry.winfo_exists(): self.entry.delete(0,'end')
                except tk.TclError:
                    self.entry = None
            self.fail('Неверный PIN-код')

    def try_pattern(self):
        if self._disposed:
            return
        expected=self.settings.get('pattern_hash')
        value='-'.join(map(str,self.pattern))
        if value and hash_value(value)==expected:
            self.on_unlock()
        else:
            self.pattern=[]; self.fail('Графический ключ неверен')

    def try_touch(self):
        if self._disposed:
            return
        expected=self.settings.get('touch_hash')
        value='-'.join(self.touch_sequence)
        if value and hash_value(value)==expected:
            self.on_unlock()
        else:
            self.touch_sequence=[]; self.fail('Тач-жест неверен')

    def try_fingerprint(self):
        if self._disposed:
            return
        if not self.fp_button: return
        self.fp_button.config(state='disabled', text='ПРИЛОЖИТЕ ПАЛЕЦ…')
        def work():
            user=__import__('getpass').getuser()
            try:
                p=subprocess.run(['fprintd-verify', user],capture_output=True,text=True,timeout=35)
                ok=p.returncode==0
                detail=(p.stdout+p.stderr).strip().splitlines()[-1] if (p.stdout+p.stderr).strip() else ('Отпечаток подтверждён' if ok else 'Отпечаток не подтверждён')
            except subprocess.TimeoutExpired:
                ok=False; detail='Время ожидания сканера истекло'
            except Exception as exc:
                ok=False; detail=str(exc)
            self.root.after(0,self._fingerprint_result,ok,detail)
        threading.Thread(target=work,daemon=True).start()

    def _fingerprint_result(self,ok,detail):
        if self._disposed:
            return
        if ok: self.on_unlock()
        else:
            self._set_message(detail[:90],RED); self.root.bell()
            if self.fp_button: self.fp_button.config(state='normal',text='СКАНИРОВАТЬ ОТПЕЧАТОК')
