"""Default-off beacon controls with separately selected event policies and server stage display."""
import tkinter as tk
from tkinter import ttk

from collection_display import display_time
from beacon_preferences import PREFERENCES_PATH, load_types,save_types

KINDS = {1:'救援', 2:'宝藏', 3:'资源', 4:'怪物'}
STATES = {0:'未开始', 1:'行军/处理中', 2:'执行中', 3:'可领奖'}


class BeaconPanel(ttk.Frame):
    """Show type choices, current events, scout/return stages and authoritative deadline checks."""

    def __init__(self, parent, enabled, on_switch, on_check, *, preferences=PREFERENCES_PATH):
        """Build the default-off rescue controls and the read-only event/army display."""
        super().__init__(parent, padding=10)
        self.enabled = enabled
        self.connected = False
        self.snapshot = None
        self.scout_info=''
        self.status = tk.StringVar(value='自动烽火台关闭；启动只读取当前状态。')
        self.summary = tk.StringVar(value='烽火台额度：待读取')
        self.timing = tk.StringVar(value='刷新与下次检查：待读取')
        bar = ttk.Frame(self)
        bar.pack(fill='x')
        self.toggle = ttk.Checkbutton(bar, text='自动烽火台', variable=enabled, command=on_switch, state='disabled')
        self.toggle.pack(side='left')
        self.choices={k:tk.BooleanVar() for k in KINDS}
        self.set_preferences(preferences)
        self.choice_boxes=[]
        for k in (1,4,3,2):
            box=ttk.Checkbutton(bar,text=KINDS[k],variable=self.choices[k],command=self.save_choices)
            box.pack(side='left',padx=(8,0));self.choice_boxes.append(box)
        self.check = ttk.Button(bar, text='立即检查', command=on_check, state='disabled')
        self.check.pack(side='right')
        ttk.Label(self, text='救援到达撤回；怪物胜券在握才出征、到达后跳过；资源正常采完；完成后自动领奖。\n'
                  '宝藏正常消耗现有斥候、不购买；不主动用恢复/加速道具。修改类型前先关闭总开关。',
                  foreground='#666666', wraplength=950).pack(anchor='w', pady=(8,4))
        ttk.Label(self, textvariable=self.summary).pack(anchor='w')
        ttk.Label(self, textvariable=self.timing, wraplength=950).pack(anchor='w', pady=(3,4))
        columns = ('kind','target','state','army','end')
        self.tree = ttk.Treeview(self, columns=columns, show='headings', height=4)
        for key,label,width in zip(columns, ('类型','事件 / 坐标','当前状态','英雄 / 队伍','服务器阶段结束（北京时间）'),
                                   (110,190,140,200,210)):
            self.tree.heading(key,text=label)
            self.tree.column(key,width=width,anchor='center',stretch=True)
        scroll = ttk.Scrollbar(self, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right',fill='y')
        self.tree.pack(fill='both',expand=True)
        ttk.Label(self,textvariable=self.status,wraplength=950).pack(anchor='w',pady=(6,0))
        ttk.Label(self,text='关闭后停止新的出征、侦察、撤回、跳过和领奖；已接受的行动继续。按服务器时间和推送检查，无固定网络轮询。',
                  foreground='#666666',wraplength=950).pack(anchor='w',pady=(4,0))

    def update_controls(self, ready):
        """Permit immediate stop while connected and mark disabled/disconnected check plans cancelled."""
        self.connected = ready
        self.toggle.state(['!disabled'] if ready else ['disabled'])
        self.check.state(['!disabled'] if ready else ['disabled'])
        for box in self.choice_boxes:box.state(['disabled'] if self.enabled.get() else ['!disabled'])
        self.render()

    def selected_types(self):
        """Return only explicit type choices; the master switch remains separate and default-off."""
        return tuple(k for k,v in self.choices.items() if v.get())

    def set_preferences(self, path):
        """Reload the beacon choices after confirming the current role."""
        self.preferences = path
        try:
            choices = load_types(path) if path is not None else (1,)
        except (ValueError, OSError) as error:
            choices = (1,)
            self.status.set('类型选择未加载，保留救援：' + str(error))
        for kind, choice in self.choices.items():
            choice.set(kind in choices)

    def save_choices(self):
        """Persist type choices while stopped; saving never starts any game action."""
        if self.enabled.get():return
        if self.preferences is None:
            return
        try:save_types(self.selected_types(), self.preferences)
        except (ValueError,OSError) as error:self.status.set('类型选择保存失败：'+str(error))

    def apply_scout(self, state):
        """Display fresh native stock/cost independently of scout arrival or event completion."""
        self.scout_info=f"；斥候 {state['stock']}，本次需要 {state['cost']}"
        self.render()

    def apply_snapshot(self, snapshot):
        """Render only worker-confirmed data; refreshing the view never sends a game request."""
        self.snapshot = snapshot
        self.render()

    def render(self):
        """Keep completed event timestamps out of active-stage timers and show returning armies separately."""
        if self.snapshot is None:
            return
        snapshot = self.snapshot
        prefix = '' if self.connected else '上次确认：'
        self.summary.set(f"{prefix}烽火台占用 {snapshot['queue_used']} / {snapshot['queue_limit']} 队（返城 {snapshot.get('returning_count',0)}）；"
                         f"事件 {len(snapshot['events'])} 个"+self.scout_info)
        check = (display_time(snapshot['check_ms']) if snapshot.get('check_ms') else '等待推送或手动检查')
        if not (self.enabled.get() and self.connected):
            check = '已取消（自动关闭或断线）'
        refresh = display_time(snapshot['refresh_end_ms']) if snapshot['refresh_end_ms'] else '服务器未提供有效刷新时间'
        self.timing.set(f"刷新参考：{refresh}；下次检查：{check}；数据时间：{display_time(snapshot['server_now_ms'])}")
        self.tree.delete(*self.tree.get_children())
        armies = {a['army_id']:a for a in snapshot['armies']}
        displayed = set()
        for event in snapshot['events']:
            army = armies.get(event['army_id'])
            if army:
                displayed.add(army['army_id'])
            end = army['end_ms'] if army else event['end_ms'] if event['state']==2 else 0
            state=STATES.get(event['state'],f"状态{event['state']}")
            if army and army['state']==9:state+=' / 返城中'
            self.tree.insert('', 'end', values=(KINDS.get(event['kind'],'其他（只读）'),
                f"{event['event_id']} / ({event['x']},{event['y']})",state,
                f"{army['name']} / {army['army_id']}" if army else '—',display_time(end) if end else '—'))
        for army in snapshot['armies']:
            if army['army_id'] not in displayed:
                self.tree.insert('', 'end', values=('烽火台队伍',str(army['target_id']),
                    '返城中' if army['state']==9 else f"行动中（{army['state']}）",
                    f"{army['name']} / {army['army_id']}",display_time(army['end_ms']) if army['end_ms'] else '—'))
        for scout in snapshot.get('scouts',[]):
            self.tree.insert('','end',values=('斥候',f"({scout['x']},{scout['y']})",'已侦察，等待事件更新','—','—'))
