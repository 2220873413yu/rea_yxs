"""Scrollable roster with explicit persisted choices and a default-off recovery master."""
import tkinter as tk
from tkinter import ttk

from hero_preferences import PREFERENCES_PATH, load_heroes, save_heroes, checked_heroes
from collection import RESOURCE_NAMES
from collection_display import display_time


def hero_display(state):
    """Show the last confirmed descriptive state even after cache age expires; unknown data never means idle."""
    seconds = max(0, (state.get('remaining_ms', 0) + 999) // 1000)
    label = ('数据不明' if not state.get('found') or not state.get('army_known') else
             state['activity_label'] if state.get('activity_label') and state.get('confirmed_ms', 0) > 0 else
             '数据不明' if not state.get('fresh') else
             '活动占用' if state.get('hero_state') != 0 else
             '行动中（待确认）' if state.get('busy') else
             '恢复中' if seconds else '空闲')
    return label, f'{seconds // 3600:02}:{seconds // 60 % 60:02}:{seconds % 60:02}'


class HeroPanel(ttk.LabelFrame):
    """Keep roster refreshes separate from the user's saved selection and spending switch."""

    def __init__(self, parent, enabled, on_switch, on_refresh, on_attributes=None, *, preferences=PREFERENCES_PATH):
        """Bind saved hero selections to the current page's preference file."""
        super().__init__(parent, text='英雄属性与恢复', padding=10)
        self.enabled = enabled
        self.ready = False
        self.collection_active = False
        self.roster = {}
        self.speeds = {}
        self.loads = {}
        self.references = {}
        self.sort_column = None
        self.sort_reverse = True
        self.reference_text = tk.StringVar(value='采集速度：正在读取二级参考点；实际派出前会按目标重新查询。')
        self.status = tk.StringVar(value='自动恢复关闭，正在读取名单…')
        self.stock = tk.StringVar(value='五分钟英雄恢复加速：正在读取…')
        self.note = tk.StringVar()
        self.set_preferences(preferences)
        bar = ttk.Frame(self)
        bar.pack(fill='x')
        self.toggle = ttk.Checkbutton(bar, text='自动恢复英雄', variable=enabled, command=on_switch, state='disabled')
        self.toggle.pack(side='left')
        self.mode=tk.StringVar(value='普通')
        ttk.Label(bar,text='恢复模式').pack(side='left',padx=(12,4))
        self.mode_box=ttk.Combobox(bar,textvariable=self.mode,values=('普通','快速'),state='disabled',width=7)
        self.mode_box.pack(side='left')
        self.refresh_button = ttk.Button(bar, text='刷新英雄名单', command=on_refresh, state='disabled')
        self.refresh_button.pack(side='right')
        self.attributes_button = ttk.Button(bar, text='刷新采集属性', command=on_attributes or (lambda: None), state='disabled')
        self.attributes_button.pack(side='right', padx=(0, 6))
        listing = ttk.Frame(self)
        listing.pack(fill='both', expand=True, pady=(7, 5))
        self.tree = ttk.Treeview(listing, columns=('selected', 'name', 'state', 'confirmed', 'time', 'power', 'iron', 'wood', 'grain', 'load'),
                                 show='headings', height=8, selectmode='browse')
        self.titles = {}
        for key, title, width in (('selected', '恢复勾选', 65), ('name', '英雄', 100), ('state', '状态', 160),
                                   ('confirmed', '最后确认（北京时间）', 160), ('time', '恢复剩余', 85), ('power', '战力', 85), ('iron', '铁/分', 70),
                                   ('wood', '木/分', 70), ('grain', '粮/分', 70), ('load', '负重', 85)):
            self.titles[key] = title
            self.tree.heading(key, text=title, command=lambda column=key: self.sort_by(column))
            self.tree.column(key, width=width, minwidth=width, anchor='center', stretch=key == 'name')
        scrollbar = ttk.Scrollbar(listing, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        horizontal = ttk.Scrollbar(listing, orient='horizontal', command=self.tree.xview)
        self.tree.configure(xscrollcommand=horizontal.set)
        self.tree.grid(row=0, column=0, sticky='nsew')
        scrollbar.grid(row=0, column=1, sticky='ns')
        horizontal.grid(row=1, column=0, sticky='ew')
        listing.columnconfigure(0, weight=1)
        listing.rowconfigure(0, weight=1)
        self.tree.bind('<Button-1>', self.click)
        self.tree.bind('<space>', self.space)
        ttk.Label(self, textvariable=self.reference_text, wraplength=950, foreground='#666666').pack(anchor='w')
        ttk.Label(self, textvariable=self.note, wraplength=590, foreground='#666666').pack(anchor='w')
        ttk.Label(self, textvariable=self.stock).pack(anchor='w', pady=(5, 0))
        ttk.Label(self, textvariable=self.status, wraplength=590).pack(anchor='w')
        ttk.Label(self,text='普通：逐个确认；快速：每秒最多3次、最多3个/批，核对成功后继续。采集恢复共用；切换前关闭恢复和采集。',
                  foreground='#666666',wraplength=950).pack(anchor='w')

    def recovery_mode(self):
        """Map explicit UI choices to validated worker modes; do not persist a fast default across restart."""
        value=self.mode.get()
        if value not in ('普通','快速'):raise ValueError('请选择普通或快速恢复模式')
        return 'fast' if value=='快速' else 'normal'

    def selected(self):
        """Return a validated stable ID list, independent of card position and roster sort order."""
        return checked_heroes(self.selection)

    def update_controls(self, ready, collection_active=None):
        """Freeze the shared mode during recovery/collection and keep the master stop available."""
        self.ready = ready
        if collection_active is not None:
            self.collection_active = collection_active
        self.toggle.state(['!disabled'] if ready and (self.enabled.get() or (self.roster and self.selection)) else ['disabled'])
        self.refresh_button.state(['!disabled'] if ready and not self.enabled.get() else ['disabled'])
        self.attributes_button.state(['!disabled'] if ready and not self.collection_active else ['disabled'])
        self.mode_box.configure(state='readonly' if ready and not self.enabled.get() and not self.collection_active else 'disabled')

    def render(self):
        """Preserve scroll position and user choices; missing selected heroes remain visibly unavailable."""
        ids = list(self.roster) + sorted(self.selection - self.roster.keys())
        if self.sort_column is not None:
            ids.sort(key=self.sort_value, reverse=self.sort_reverse)
        for item in self.tree.get_children():
            if int(item) not in ids:
                self.tree.delete(item)
        for index, hero_id in enumerate(ids):
            state = self.roster.get(hero_id)
            label, remaining = hero_display(state) if state else ('未在当前名单中', '—')
            values = ('☑' if hero_id in self.selection else '☐',
                      state.get('name', str(hero_id)) if state else str(hero_id), label,
                      display_time(state.get('confirmed_ms')) if state else '未知',
                      remaining, state.get('power', 0) if state else '—',
                      self.speeds.get(hero_id, {}).get(3, '—'), self.speeds.get(hero_id, {}).get(2, '—'),
                      self.speeds.get(hero_id, {}).get(1, '—'), self.loads.get(hero_id, '—'))
            iid = str(hero_id)
            if self.tree.exists(iid):
                self.tree.item(iid, values=values)
                self.tree.move(iid, '', index)
            else:
                self.tree.insert('', 'end', iid=iid, values=values)

    def sort_value(self, hero_id):
        """Sort numerical properties numerically while keeping selected IDs independent of row order."""
        state = self.roster.get(hero_id, {})
        key = self.sort_column
        if key in {'iron', 'wood', 'grain'}:
            return self.speeds.get(hero_id, {}).get({'iron': 3, 'wood': 2, 'grain': 1}[key], -1)
        if key == 'load':
            return self.loads.get(hero_id, -1)
        if key == 'selected':
            return hero_id in self.selection
        if key == 'power':
            return state.get('power', -1)
        if key == 'time':
            return state.get('remaining_ms', -1)
        if key == 'confirmed':
            return state.get('confirmed_ms', 0)
        return str(state.get('name', hero_id)) if key == 'name' else hero_display(state)[0]

    def sort_by(self, key):
        """Toggle one heading's order without changing recovery selections or the collection policy."""
        self.sort_reverse = not self.sort_reverse if self.sort_column == key else key not in {'name', 'state'}
        self.sort_column = key
        for column, title in self.titles.items():
            self.tree.heading(column, text=title + ((' ↓' if self.sort_reverse else ' ↑') if column == key else ''))
        self.render()

    def apply_metrics(self, metrics):
        """Keep target-specific server rates apart from live recovery snapshots so refreshes cannot erase them."""
        target = metrics['target']
        kind = target['kind']
        for hero in metrics['heroes']:
            self.speeds.setdefault(hero['hero_id'], {})[kind] = hero['speed']
            self.loads[hero['hero_id']] = hero['load']
        self.references[kind] = f"{RESOURCE_NAMES[kind]}：{target['level']}级({target['x']},{target['y']})"
        self.reference_text.set('速度参考点：' + '；'.join(self.references[k] for k in (3, 2, 1) if k in self.references) +
                                '。实际出征前重新查询；负重为最近查询值。')
        self.render()

    def clear_metrics(self, kind):
        """Display unknown rather than a stale speed when the requested reference resource is unavailable."""
        for rates in self.speeds.values():
            rates.pop(kind, None)
        self.references[kind] = f'{RESOURCE_NAMES[kind]}：未找到参考点'
        self.reference_text.set('速度参考点：' + '；'.join(self.references[k] for k in (3, 2, 1) if k in self.references))
        self.render()

    def apply_roster(self, roster):
        """Update available heroes and shared inventory without adding or removing saved choices."""
        self.roster = {hero['hero_id']: hero for hero in roster['heroes']}
        self.stock.set(f"五分钟英雄恢复加速：{roster['items']} 个")
        self.render()

    def apply_state(self, state):
        """Reflect a confirmed individual response while leaving other hero rows and choices intact."""
        self.roster[state['hero_id']] = state
        self.stock.set(f"五分钟英雄恢复加速：{state['items']} 个")
        self.render()

    def set_preferences(self, path):
        """Replace selected heroes with the choices saved for the confirmed role."""
        self.preferences = path
        try:
            self.selection = set(load_heroes(path)) if path is not None else set()
            self.note.set('点击勾选列选择英雄；修改名单前先关闭自动恢复。')
        except (ValueError, OSError) as error:
            self.selection = set()
            self.note.set('原选择文件读取失败，请重新勾选：' + str(error).splitlines()[0])

    def toggle_hero(self, hero_id):
        """Save a user choice atomically; a failed save never silently changes the enabled set."""
        if self.enabled.get() or self.preferences is None:
            return
        updated = self.selection ^ {hero_id}
        try:
            save_heroes(updated, self.preferences)
        except (ValueError, OSError) as error:
            self.status.set('保存勾选失败：' + str(error).splitlines()[0])
            return
        self.selection = updated
        self.render()
        self.note.set(f'已保存 {len(updated)} 位英雄；修改名单前先关闭自动恢复。')
        self.update_controls(self.ready)

    def click(self, event):
        """Toggle only clicks in the checkbox column, leaving other cells usable for row selection."""
        if self.tree.identify_region(event.x, event.y) == 'cell' and self.tree.identify_column(event.x) == '#1':
            row = self.tree.identify_row(event.y)
            if row:
                self.toggle_hero(int(row))

    def space(self, event):
        """Allow keyboard selection changes using Space on the focused hero row."""
        row = self.tree.focus()
        if row:
            self.toggle_hero(int(row))
        return 'break'
