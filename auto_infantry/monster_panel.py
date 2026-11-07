"""Default-off hunting controls, native combat capacity and per-army stage display."""
import tkinter as tk
from tkinter import ttk

from collection_display import display_time
from monster import HuntOptions, MAX_HUNT_RADIUS


class MonsterPanel(ttk.LabelFrame):
    """Show bounded scope, native default followers and independent quick-combat progress."""

    def __init__(self, parent, enabled, on_switch, on_check):
        super().__init__(parent, text='自动打野（按服务器额度补队）', padding=8)
        self.enabled = enabled
        self.radius = tk.IntVar(value=20)
        self.status = tk.StringVar(value='当前打野关闭；到地图刷新时刻会自动开启，不为打野使用恢复道具。')
        self.auto_hint = tk.StringVar(value='手动取消勾选只暂停到下一刷新时刻；关闭助手可停止定时开启。')
        self.team = tk.StringVar(value='队伍：未派出')
        self.capacity = tk.StringVar(value='出征额度：待读取；本轮忽略：0个坐标')
        row = ttk.Frame(self)
        row.pack(fill='x')
        self.toggle = ttk.Checkbutton(row, text='自动打野', variable=enabled, command=on_switch, state='disabled')
        self.toggle.pack(side='left')
        ttk.Label(row, text='距主城最大范围（格）').pack(side='left', padx=(20, 6))
        self.range_box = ttk.Spinbox(row, from_=1, to=MAX_HUNT_RADIUS, width=5, textvariable=self.radius)
        self.range_box.pack(side='left')
        self.check = ttk.Button(row, text='立即检查', command=on_check, state='disabled')
        self.check.pack(side='right')
        ttk.Label(self, text='从近到远查询区域并独立记录；满队暂停查询，仅有视野、空闲且胜券在握才按默认编队出征，到达后自动跳过战斗。',
                  wraplength=960, foreground='#666666').pack(anchor='w', pady=(4, 0))
        ttk.Label(self, textvariable=self.status, wraplength=960).pack(anchor='w')
        ttk.Label(self, textvariable=self.auto_hint, wraplength=960, foreground='#666666').pack(anchor='w')
        ttk.Label(self, textvariable=self.capacity, wraplength=960).pack(anchor='w', pady=(4, 3))
        listing=ttk.Frame(self)
        listing.pack(fill='both',expand=True)
        self.tree=ttk.Treeview(listing,columns=('hero','target','state','soldiers','end'),show='headings',height=4)
        for key,title,width in (('hero','英雄 / 队伍ID',185),('target','野怪坐标',125),('state','当前阶段',125),
                                ('soldiers','小兵数',75),('end','服务器阶段结束（北京时间）',220)):
            self.tree.heading(key,text=title)
            self.tree.column(key,width=width,minwidth=65,anchor='center')
        bar=ttk.Scrollbar(listing,orient='vertical',command=self.tree.yview)
        self.tree.configure(yscrollcommand=bar.set)
        self.tree.pack(side='left',fill='both',expand=True)
        bar.pack(side='right',fill='y')

    def options(self):
        """Validate the visible radius for this run; an invalid entry never enables departures."""
        return HuntOptions(self.radius.get())

    def update_controls(self, ready):
        """Freeze the active scope while leaving the master stop immediately accessible."""
        self.toggle.state(['!disabled'] if ready else ['disabled'])
        self.range_box.state(['disabled'] if self.enabled.get() else ['!disabled'])
        self.check.state(['!disabled'] if ready and self.enabled.get() else ['disabled'])

    def apply_team(self, row):
        """Render only worker-confirmed stage times; no UI callback queries game state."""
        self.team.set(f"{row['name']} / {row['army_id']} →（{row['x']},{row['y']}），"
                      f"小兵{row['followers']}名；服务器阶段结束：{display_time(row['end_ms'])}")

    def apply_snapshot(self, snapshot):
        """Render all confirmed helper teams and native capacity without adding any server query."""
        count=f"{snapshot['queue_used']} / {snapshot['queue_limit']}" if snapshot['queue_known'] else '未知'
        self.capacity.set(f"出征额度：已占用 {count}；助手管理 {snapshot['managed']} 队；本轮忽略 {snapshot['ignored']} 个坐标")
        if 'scanned' in snapshot:
            self.capacity.set(self.capacity.get() + f"；区域 {snapshot['scanned']}/{snapshot['regions']}，记录 {snapshot['discovered']} 个目标")
        self.tree.delete(*self.tree.get_children())
        states={2:'行军中',3:'到达待战',5:'战斗中',7:'已返回待确认',9:'返城中',11:'等待战斗'}
        for row in snapshot['rows']:
            label='已跳过，待状态确认' if row['state']==3 and row['skipped'] else states.get(row['state'],f"状态{row['state']}")
            self.tree.insert('', 'end',iid=str(row['army_id']),values=(f"{row['name']} / {row['army_id']}",
                             f"{row['x']},{row['y']}",label,row['followers'],display_time(row['end_ms'])))
