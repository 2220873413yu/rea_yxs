"""Default-off alliance mining controls and server-confirmed status, with no I/O in the view."""
import tkinter as tk
from tkinter import ttk

from collection_display import display_time

PHASES = {2: '行军中', 3: '行军中', 6: '采集中', 7: '已返回（待确认）', 9: '返城中'}


class LeaguePanel(ttk.Frame):
    """Display the independent one-team workflow and distinguish server deadlines from check times."""

    def __init__(self, parent, enabled, on_switch, on_check):
        super().__init__(parent, padding=10)
        self.enabled = enabled
        self.snapshot = None
        self.connected = False
        self.toggle = ttk.Checkbutton(self, text='自动联盟采集', variable=enabled, command=on_switch, state='disabled')
        self.toggle.pack(anchor='w')
        self.check = ttk.Button(self, text='检查服务器状态', command=on_check, state='disabled')
        self.check.pack(anchor='e')
        self.mine = tk.StringVar(value='启动后核对本联盟资源矿…')
        self.status = tk.StringVar(value='联盟采集默认关闭，不会自动派出。')
        self.confirmed = tk.StringVar(value='尚未确认服务器状态')
        ttk.Label(self, textvariable=self.mine, wraplength=950).pack(anchor='w', pady=6)
        self.tree = ttk.Treeview(self, columns=('hero', 'state', 'end', 'check'), show='headings', height=3)
        for key, title, width in (('hero', '英雄 / 队伍ID', 180), ('state', '当前阶段', 130),
                                  ('end', '服务器阶段结束（北京时间）', 230), ('check', '计划检查（北京时间）', 230)):
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, minwidth=100, anchor='center')
        self.tree.pack(fill='x', pady=6)
        ttk.Label(self, textvariable=self.confirmed, foreground='#666666').pack(anchor='w')
        ttk.Label(self, textvariable=self.status, wraplength=950).pack(anchor='w', pady=8)
        ttk.Label(self, text='维护一支本方联盟采集队伍；手动撤回后，只要开关勾选，确认回城就继续。\n'
                  '按服务器阶段时间和被动变化检查，无固定网络轮询；原生默认带兵，不主动消耗恢复道具。\n'
                  '联盟矿采空或位置满时等待；不会自动建矿。关闭开关不会撤回已有队伍。',
                  foreground='#666666', wraplength=950).pack(anchor='w')

    def update_controls(self, connected):
        """Keep a manual read available while connected, even when automatic departures are disabled."""
        self.connected = connected
        for widget in (self.toggle, self.check):
            widget.state(['!disabled'] if connected else ['disabled'])
        self.render()

    def apply_snapshot(self, snapshot):
        """Replace the displayed snapshot only after the worker confirms server state."""
        self.snapshot = snapshot
        self.render()

    def render(self):
        """Render cached times only; a closed or disconnected switch cancels displayed check plans."""
        if self.snapshot is None:
            return
        snapshot = self.snapshot
        mine = snapshot['mine']
        self.mine.set((f"{mine['name']}（{mine['x']},{mine['y']}）　余量 {mine['stock']}　"
                       f"共享位置 {mine['occupied']} / {mine['capacity']}") if mine else '本联盟暂无资源矿')
        self.tree.delete(*self.tree.get_children())
        for row in snapshot['rows']:
            active = self.enabled.get() and self.connected
            check = (display_time(row['check_ms']) if row.get('check_ms') else '等待推送或手动检查') if active else '已取消（自动关闭）'
            self.tree.insert('', 'end', values=(f"{row['name']} / {row['army_id']}",
                             PHASES.get(row['state'], f"行动中（{row['state']}）"), display_time(row['end_ms']), check))
        self.confirmed.set('最后服务器确认：' + display_time(snapshot['server_now_ms']))
