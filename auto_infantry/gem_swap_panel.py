"""Manual 宝具 substitution controls: name a hero, pick two 主印 positions, apply inside a battle."""
import tkinter as tk
from tkinter import ttk

from gem_swap import GEMS, OFF


class GemSwapPanel(ttk.Frame):
    """Keep the rule set explicit; opening this tab or resolving a name never touches a battle."""

    def __init__(self, parent, enabled, on_switch, on_revert, on_probe, on_resolve):
        super().__init__(parent, padding=10)
        self.enabled = enabled
        self.hero_base = 0
        self.hero_label = ''
        self.names = []

        row = ttk.Frame(self)
        row.pack(anchor='w')
        self.toggle = ttk.Checkbutton(row, text='进入对局后自动替换宝具', variable=enabled,
                                      command=lambda: on_switch(False), state='disabled')
        self.toggle.pack(side='left')
        self.revert_button = ttk.Button(row, text='还原本次替换', command=lambda: on_revert(True), state='disabled')
        self.revert_button.pack(side='left', padx=(12, 0))
        self.probe_button = ttk.Button(row, text='读取当前对局英雄', command=lambda: on_probe(True), state='disabled')
        self.probe_button.pack(side='left', padx=(12, 0))
        self.resolve_button = ttk.Button(row, text='解析英雄名', command=lambda: on_resolve(False), state='disabled')
        self.resolve_button.pack(side='left', padx=(12, 0))

        ttk.Label(self, text='只在本机客户端内改当前对局的英雄卡：不发请求、不改存档，退出或重连后自动恢复。\n'
                             '只填「空着的槽位」，不动已装备的宝具；槽位不够会直接报错，不会覆盖。\n'
                             '设置可以在游戏大厅完成，不需要先进西游幻境；进入对局后自动按这里生效。',
                  wraplength=930, foreground='#666666').pack(anchor='w', pady=(8, 8))

        grid = ttk.Frame(self)
        grid.pack(anchor='w')
        ttk.Label(grid, text='英雄名').grid(row=0, column=0, sticky='w', padx=(0, 6))
        self.hero = ttk.Combobox(grid, values=[], width=18)
        self.hero.grid(row=0, column=1, sticky='w', padx=(0, 18))
        ttk.Label(grid, text='第一个主印').grid(row=0, column=2, sticky='w', padx=(0, 6))
        self.first = ttk.Combobox(grid, values=list(GEMS), width=12, state='readonly')
        self.first.set('天狼')
        self.first.grid(row=0, column=3, sticky='w', padx=(0, 18))
        ttk.Label(grid, text='第二个主印').grid(row=0, column=4, sticky='w', padx=(0, 6))
        self.second = ttk.Combobox(grid, values=list(GEMS), width=12, state='readonly')
        self.second.set('傲剑')
        self.second.grid(row=0, column=5, sticky='w')

        self.summary = tk.StringVar(value='宝具替换：先输入英雄名并点「解析英雄名」')
        self.status = tk.StringVar(value='宝具替换关闭。')
        ttk.Label(self, textvariable=self.summary).pack(anchor='w', pady=(10, 2))
        self.tree = ttk.Treeview(self, columns=('slot', 'gem', 'skill'), show='headings', height=4)
        for key, title, width in (('slot', '槽位', 80), ('gem', '宝具 id', 140), ('skill', '技能 id', 140)):
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, anchor='center')
        self.tree.pack(fill='x', pady=(6, 0))
        ttk.Label(self, textvariable=self.status, wraplength=930).pack(anchor='w', pady=(8, 0))

    def selection(self):
        """Return the frozen rule tuple exactly as the session validates it."""
        return self.hero_base, self.first.get(), self.second.get()

    def set_roster(self, rows):
        """Offer the helper's confirmed hero names as suggestions; the id always comes from 解析."""
        self.names = [row['name'] for row in rows or [] if row.get('hero_id')]
        self.hero.configure(values=self.names)
        if not self.hero.get() and '朱元璋' in self.names:
            self.hero.set('朱元璋')

    def update_controls(self, available):
        """Allow stopping at any time; naming and resolving need only a running game process."""
        self.toggle.state(['!disabled'] if available or self.enabled.get() else ['disabled'])
        self.revert_button.state(['!disabled'] if self.enabled.get() else ['disabled'])
        self.probe_button.state(['!disabled'] if available else ['disabled'])
        self.resolve_button.state(['!disabled'] if available else ['disabled'])
        self.first.configure(state='readonly' if available else 'disabled')
        self.second.configure(state='readonly' if available else 'disabled')

    def apply_resolved(self, snapshot):
        """Show the resolved identity so the user can confirm the right hero before arming."""
        if snapshot.get('state') != 'found':
            return
        self.hero_base = snapshot['hero_base']
        self.hero_label = self.hero.get()
        ids = snapshot.get('ids') or []
        self.summary.set(f'已解析：{self.hero_label} → 英雄 {self.hero_base}（含 {len(ids)} 个星级变体：{ids}）')

    def apply_current_hero(self, snapshot):
        """Adopt the hero this battle actually assigned, so a mid-battle target needs no name."""
        hero = snapshot.get('hero') if isinstance(snapshot, dict) else None
        if snapshot.get('state') != 'found' or not hero:
            return
        self.hero_base = hero
        self.hero_label = f'对局内英雄 {hero}'
        self.summary.set(f'当前对局英雄：{hero}；选好宝具后勾选开关即可生效')
        self.apply_slots(snapshot.get('slots'))

    def clear(self):
        """Drop the previous role's choices without persisting an armed rule set."""
        self.hero_base = 0
        self.hero_label = ''
        self.names = []
        self.hero.configure(values=[])
        self.hero.set('')
        self.tree.delete(*self.tree.get_children())
        self.summary.set('宝具替换：先输入英雄名并点「解析英雄名」')
        self.status.set('宝具替换关闭。')

    def apply_slots(self, slots):
        """Show the client-side gem list that the last replacement left behind."""
        self.tree.delete(*self.tree.get_children())
        for row in slots or ():
            self.tree.insert('', 'end', values=(row.get('slot'), row.get('gem'), row.get('skill')))
