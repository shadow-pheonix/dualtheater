"""Native library navigation and scrollable pages; operations use DesktopService."""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk


class ScrollablePage(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, highlightthickness=0, background='#101827')
        bar = ttk.Scrollbar(self, orient='vertical', command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=bar.set)
        bar.pack(side='right', fill='y'); self.canvas.pack(side='left', fill='both', expand=True)
        self.body = ttk.Frame(self.canvas, padding=18)
        self.window = self.canvas.create_window((0, 0), window=self.body, anchor='nw')
        self.body.bind('<Configure>', lambda event: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>', self._resize)
        self.canvas.bind_all('<MouseWheel>', self._wheel, add='+')

    def _resize(self, event):
        self.canvas.itemconfigure(self.window, width=event.width)
        def labels(parent):
            for child in parent.winfo_children():
                if isinstance(child, ttk.Label) and child.cget('wraplength'):
                    child.configure(wraplength=max(240, event.width - 48))
                labels(child)
        labels(self.body)

    def _wheel(self, event):
        # Scroll only this page when the pointer is over it, preserving native
        # list/combobox/scale handling and other windows' event bindings.
        target = self.winfo_containing(event.x_root, event.y_root)
        if isinstance(target, (ttk.Treeview, ttk.Combobox, tk.Text, ttk.Scale)):
            return
        while target:
            if target == self:
                self.canvas.yview_scroll(-int(event.delta / 120), 'units'); return
            target = target.master


class LibraryPane(ttk.Frame):
    def __init__(self, parent, queue, note, select_player):
        super().__init__(parent)
        self.queue, self.note, self.select_player = queue, note, select_player
        self.provider = 'windows'; self.entry = self.parent_entry = ''
        self.cursor = 0; self.providers = []; self.rows = {}; self.running = False; self.busy = False
        self.provider_value = tk.StringVar(value='Windows folders')
        self.message = tk.StringVar(value='Start the TV connection to manage and browse shared movie folders.')
        ttk.Label(self, text='Your movie library', style='Heading.TLabel').pack(anchor='w')
        note(self, 'Share a Windows folder once, then browse its folders and movies from the TV, Windows or phone. Android storage appears while its sharing app is connected and open.')
        row = ttk.Frame(self); row.pack(fill='x', pady=6)
        self.add_button = ttk.Button(row, text='Share Windows folder…', command=self.add)
        self.add_button.pack(side='left')
        self.remove_button = ttk.Button(row, text='Stop sharing selected folder', command=self.remove)
        self.remove_button.pack(side='left', padx=8)
        row = ttk.Frame(self); row.pack(fill='x', pady=6)
        ttk.Label(row, text='Source').pack(side='left')
        self.source = ttk.Combobox(row, textvariable=self.provider_value, state='readonly')
        self.source.pack(side='left', fill='x', expand=True, padx=8)
        self.source.bind('<<ComboboxSelected>>', self.change_provider)
        self.up_button = ttk.Button(row, text='Parent folder', command=lambda: self.browse(self.parent_entry))
        self.up_button.pack(side='left')
        self.refresh_button = ttk.Button(row, text='Refresh', command=lambda: self.browse(self.entry, self.cursor))
        self.refresh_button.pack(side='left', padx=(8, 0))
        ttk.Label(self, textvariable=self.message, wraplength=790).pack(anchor='w', pady=6)
        self.tree = ttk.Treeview(self, columns=('kind', 'size'), show='tree headings', height=13, selectmode='browse')
        self.tree.heading('#0', text='Folder / movie'); self.tree.heading('kind', text='Type'); self.tree.heading('size', text='Size')
        self.tree.column('#0', width=490); self.tree.column('kind', width=80, stretch=False); self.tree.column('size', width=90, stretch=False)
        self.tree.pack(fill='both', expand=True, pady=6)
        self.tree.bind('<Double-1>', self.open); self.tree.bind('<Return>', self.open)
        self.tree.bind('<<TreeviewSelect>>', lambda event: self.enabled(self.running, self.busy))
        row = ttk.Frame(self); row.pack(fill='x', pady=6)
        self.open_button = ttk.Button(row, text='Open folder / play movie', command=self.open)
        self.open_button.pack(side='left')
        self.previous = ttk.Button(row, text='Previous page', command=lambda: self.browse(self.entry, max(0, self.cursor - 100)))
        self.previous.pack(side='right', padx=(8, 0))
        self.next_cursor = None
        self.next = ttk.Button(row, text='Next page', command=lambda: self.browse(self.entry, self.next_cursor or 0))
        self.next.pack(side='right')
        note(self, 'Android sharing uses a folder chosen in that device’s system picker. Keep that app open during playback. Only original, seekable movie files can be streamed. A missing phone does not affect Windows or TV track controls.')
        self.enabled(False, False)

    def status(self, value):
        choices = value.get('client_state', {}).get('providers', [])
        self.providers = [row for row in choices if row.get('available')]
        self.source['values'] = [row.get('label', row['id']) for row in self.providers]
        selected = next((i for i, row in enumerate(self.providers) if row['id'] == self.provider), -1)
        if selected >= 0: self.source.current(selected)
        elif self.provider != 'windows': self.message.set('Source disconnected. Choose Windows folders or reconnect the sharing app.')

    def enabled(self, running, busy):
        self.running, self.busy = running, busy
        ready = running and not busy
        for button in (self.add_button, self.refresh_button, self.open_button):
            button.configure(state='normal' if ready else 'disabled')
        self.source.configure(state='readonly' if ready else 'disabled')
        self.up_button.configure(state='normal' if ready and self.entry else 'disabled')
        self.previous.configure(state='normal' if ready and self.cursor else 'disabled')
        self.next.configure(state='normal' if ready and self.next_cursor is not None else 'disabled')
        self.remove_button.configure(state='normal' if ready and self.provider == 'windows' and not self.entry and self.tree.selection() else 'disabled')

    def change_provider(self, event=None):
        index = self.source.current()
        if 0 <= index < len(self.providers):
            self.provider = self.providers[index]['id']; self.browse('')

    def browse(self, entry='', cursor=0):
        if not self.running: return
        self.entry, self.cursor = entry, cursor
        self.message.set('Opening shared folder…')
        self.queue('library', action='browse', provider=self.provider, entry=entry, cursor=cursor)

    def result(self, action, result):
        if action in ('library_add', 'library_remove'):
            self.provider = 'windows'; self.browse(''); return
        if action == 'load_entry': self.select_player(); return
        if action != 'browse' or not isinstance(result, dict): return
        self.provider = result.get('provider', self.provider)
        self.entry = result.get('entry', ''); self.parent_entry = result.get('parent', '')
        self.next_cursor = result.get('next_cursor')
        self.message.set(result.get('label', 'Shared movie folders'))
        self.tree.delete(*self.tree.get_children()); self.rows = {}
        for row in result.get('entries', []):
            available = row.get('available', True) and row.get('seekable', True)
            key = self.tree.insert('', 'end', text=row['name'], values=(
                ('Folder' if row['directory'] else 'Movie') if available else 'Unavailable',
                '' if row['directory'] else self.size(row.get('size', 0))))
            self.rows[key] = row
        if not self.rows: self.message.set('No movie files here. Open a subfolder or share a Windows movie folder.')

    def add(self):
        chosen = filedialog.askdirectory(parent=self.winfo_toplevel(), title='Share this movie folder and its subfolders')
        if chosen: self.queue('library', action='library_add', path=chosen)

    def remove(self):
        rows = self.tree.selection()
        if rows and self.provider == 'windows' and not self.entry:
            row = self.rows.get(rows[0])
            if row and messagebox.askyesno('Stop sharing folder', 'Remove this folder from remote browsing? Original files stay on disk.', parent=self.winfo_toplevel()):
                self.queue('library', action='library_remove', root_id=row['id'])

    def open(self, event=None):
        selected = self.tree.selection(); row = self.rows.get(selected[0]) if selected else None
        if not row or not self.running or self.busy: return
        if not row.get('available', True) or not row.get('seekable', True):
            self.message.set('This source is unavailable or cannot seek. Reconnect it or choose a local storage folder.'); return
        if row['directory']: self.browse(row['id'])
        else:
            self.message.set('Preparing original video and HDMI audio…')
            self.queue('library', action='load_entry', provider=self.provider, entry=row['id'], autoplay=True)

    @staticmethod
    def size(count):
        if count >= 1024**3: return f'{count / 1024**3:.1f} GiB'
        return f'{count / 1024**2:.1f} MiB' if count else 'Unknown'
