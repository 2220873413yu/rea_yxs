"""Read-only collection team status and scheduling view, backed only by worker snapshot events."""
import tkinter as tk
from tkinter import ttk

from collection_display import display_time


class CollectionTeamsPanel(ttk.LabelFrame):
    """Show each team's last confirmed stage/deadline and the scheduler's planned trigger."""

    def __init__(self, parent):
        super().__init__(parent, text='采集队伍与检查计划（北京时间）', padding=6)
        self.active = False
        self.connected = False
        self.snapshot = None
        self.awaiting = False
        self.note = tk.StringVar(value='开启自动采集后显示服务器数据；此表不会新增查询。')
        listing = ttk.Frame(self)
        listing.pack(fill='x')
        self.tree = ttk.Treeview(listing, columns=('hero', 'state', 'end', 'check'), show='headings', height=2)
        for key, title, width in (('hero', '英雄 / 队伍ID', 160), ('state', '当前阶段', 115),
                                  ('end', '服务器阶段结束时间', 185), ('check', '该队计划检查时间', 185)):
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, minwidth=width, anchor='center', stretch=True)
        scrollbar = ttk.Scrollbar(listing, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side='left', fill='x', expand=True)
        scrollbar.pack(side='right', fill='y')
        ttk.Label(self, textvariable=self.note, foreground='#666666', wraplength=950).pack(anchor='w', pady=(3, 0))

    def set_active(self, active, connected):
        """Retain historical data while stopped, but never present a cancelled timer as an active plan."""
        if (active, connected) == (self.active, self.connected):
            return
        if active and not self.active:
            self.awaiting = True
        self.active, self.connected = active, connected
        self.render()

    def apply_snapshot(self, snapshot):
        """Replace all rows from one server-confirmed worker event, including removal of returned armies."""
        self.snapshot = snapshot
        self.awaiting = False
        self.render()

    def render(self):
        """Format stored values only; status updates and table rendering never read server or game state."""
        self.tree.delete(*self.tree.get_children())
        snapshot = self.snapshot
        if snapshot is None:
            self.note.set('等待服务器数据…' if self.active else '开启自动采集后显示服务器数据；此表不会新增查询。')
            return
        live = self.active and self.connected and not self.awaiting
        for row in snapshot['rows']:
            check = display_time(row['check_ms']) if row['check_ms'] is not None else '等待推送或手动检查'
            if not live:
                check = '等待刷新' if self.active and self.connected else '已取消（采集未运行）'
            self.tree.insert('', 'end', iid=str(row['army_id']), values=(f"{row['hero']} / {row['army_id']}",
                             row['state'], display_time(row['end_ms']), check))
        updated = display_time(snapshot['server_now_ms'])
        if not live:
            state = '等待本轮刷新' if self.active and self.connected else '采集已关闭或断线，保留上次数据'
            self.note.set(f'{state}；数据时间 {updated}。')
        else:
            next_check = display_time(snapshot['next_check_ms']) if snapshot['next_check_ms'] is not None else '等待推送或手动检查'
            self.note.set(f'数据时间 {updated}；下次整体检查：{next_check}。推送可提前，全量查询同时更新各队。')
