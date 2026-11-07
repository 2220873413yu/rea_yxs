"""Default-off two-hour military report timer and the last authoritative list summary."""
import tkinter as tk
from tkinter import ttk
from collection_display import display_time


class ReportPanel(ttk.Frame):
    """Show the next timer deadline separately from report counts; opening the tab never queries or claims."""

    def __init__(self,parent,enabled,on_switch):
        super().__init__(parent,padding=10)
        self.toggle=ttk.Checkbutton(self,text='每两小时自动领取军报',variable=enabled,command=on_switch,state='disabled')
        self.toggle.pack(anchor='w')
        ttk.Label(self,text='开启两小时后首次检查，以后每两小时检查一次；有可领奖励才一键领取。\n'
            '不按红点或数量阈值触发，不删除军报；等待期间不查询服务器。\n'
            '关闭、换号、重启或开启灵台试炼后停止计时；领取结果不明时关闭，不自动重发。',
            foreground='#666666',wraplength=930).pack(anchor='w',pady=8)
        self.next_time=tk.StringVar(value='下次检查（北京时间）：未安排')
        self.summary=tk.StringVar(value='军报数量：尚未查询')
        self.confirmed=tk.StringVar(value='最近确认：尚未查询')
        self.status=tk.StringVar(value='自动领取军报关闭。')
        for value in (self.next_time,self.summary,self.confirmed,self.status):
            ttk.Label(self,textvariable=value,wraplength=930).pack(anchor='w',pady=5)

    def update_controls(self,ready):
        """Only a connected world can start its report timer."""
        self.toggle.state(['!disabled']if ready else['disabled'])

    def clear(self):
        """Discard old-role counts and timer display when the account/session changes."""
        self.apply_next(None)
        self.summary.set('军报数量：尚未查询')
        self.confirmed.set('最近确认：尚未查询')
        self.status.set('自动领取军报关闭。')

    def apply_next(self,value):
        """Display the existing deadline without running a UI-side query or timer action."""
        self.next_time.set('下次检查（北京时间）：'+(display_time(value)if value is not None else'未安排'))

    def apply_snapshot(self,s):
        """Keep total retained records distinct from actionable unclaimed rewards."""
        self.summary.set(f"军报 {s['total']} 条，可领奖励 {s['claimable']} 条；"
            f"军事 {s['military']} / 待领 {s['military_pending']}，内政 {s['internal']} / 待领 {s['internal_pending']}，事件 {s['event']} / 待领 {s['event_pending']}")
        self.confirmed.set('最近确认（北京时间）：'+display_time(s['confirmed_ms']))
