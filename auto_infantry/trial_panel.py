"""Default-off trial controls and public server-confirmed progress, roster and result display."""
import tkinter as tk
from tkinter import ttk
from collection_display import display_time

PHASES = {'off':'关闭', 'begin':'准备', 'profile':'读取试炼', 'roster':'读取可用英雄', 'selected':'确认三人名单',
          'challenge':'准备挑战', 'battle':'等待入场', 'skip':'等待原生跳过条件', 'result':'等待本场结算',
          'won':'本层胜利', 'returning':'返回试炼', 'next_profile':'确认下一层', 'handoff':'等待手动处理'}


class TrialPanel(ttk.Frame):
    """Keep the master switch separate from progress; displaying or opening this tab never starts a run."""

    def __init__(self, parent, enabled, on_switch):
        super().__init__(parent, padding=10)
        self.enabled = enabled
        self.snapshot = None
        self.toggle = ttk.Checkbutton(self, text='自动灵台试炼', variable=enabled, command=on_switch, state='disabled')
        self.toggle.pack(anchor='w')
        ttk.Label(self, text='无本轮名单时按试炼可用战力选前三人；每层用最强可用英雄，满足原生条件后跳过。\n'
                  '胜利继续；战败立即关闭，交给你手动操作。不复活、不重试、不自动翻牌或分享。\n'
                  '开启时关闭其他自动功能；试炼切场期间独占连接，其他开关不会自动恢复。',
                  wraplength=930, foreground='#666666').pack(anchor='w', pady=(8, 6))
        self.summary = tk.StringVar(value='试炼进度：尚未读取；开关默认关闭')
        self.timing = tk.StringVar(value='按原生跳过时间、回合变化和结算通知推进，无固定服务器轮询。')
        self.status = tk.StringVar(value='自动爬塔关闭。')
        ttk.Label(self, textvariable=self.summary).pack(anchor='w')
        ttk.Label(self, textvariable=self.timing, wraplength=930).pack(anchor='w', pady=4)
        self.tree = ttk.Treeview(self, columns=('hero','state','power'), show='headings', height=3)
        for key, title, width in [('hero','本轮三人名单',230),('state','试炼状态',160),('power','服务器总战力',200)]:
            self.tree.heading(key,text=title);self.tree.column(key,width=width,anchor='center')
        self.tree.pack(fill='x')
        ttk.Label(self,textvariable=self.status,wraplength=930).pack(anchor='w',pady=8)

    def update_controls(self, ready):
        """Always permit stopping an active run; disconnected sessions may not start another one."""
        self.toggle.state(['!disabled'] if ready or self.enabled.get() else ['disabled'])

    def clear(self):
        """Clear role-specific progress on account changes without persisting an enabled master."""
        self.snapshot=None;self.tree.delete(*self.tree.get_children())
        self.summary.set('试炼进度：等待当前账号数据')
        self.timing.set('按服务器允许时间和原生通知推进，无固定服务器轮询。')
        self.status.set('自动爬塔关闭。')

    def apply_snapshot(self, s):
        """Render only the trial's own confirmed roster, time and matched battle result."""
        self.snapshot=s
        phase=PHASES.get(s['phase'],s['phase'])
        self.summary.set(f"今日已过 {s['today_floor']} 层；历史最高 {s['max_floor']} 层；剩余 {s['remaining']} 次；阶段：{phase}")
        self.timing.set('本场跳过允许时间：'+(display_time(s['skip_at_ms']) if s['battle_ready'] and s['skip_at_ms']>0 else '等待入场')+
                        f"；当前回合 {s['round']}；服务器时间 {display_time(s['server_now_ms'])}")
        self.tree.delete(*self.tree.get_children())
        for h in s['heroes']:
            self.tree.insert('','end',values=(h['name'],'可出战' if h['state']==0 else f"不可出战（{h['state']}）",h['power']))
