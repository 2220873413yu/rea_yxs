"""Manual public-player hero query; opening this tab never sends requests."""
import tkinter as tk
from tkinter import ttk
from collection_display import display_time


def hero_details(snapshot):
    """Format only returned heroes and equipment, marking missing fields rather than inferring ownership."""
    lines=[]
    for hero in snapshot['heroes']:
        lines.append(f"{hero['role']}：{hero['name']}　战力 {hero.get('power') if hero.get('power') is not None else '未知'}　{hero['level']}级　{hero['star']}星")
        gems=['槽%d %s%s'%(g['slot'],g['name'],f"（{g['level']}级）" if 'level'in g else '') for g in hero['gems']]
        equips=['槽%d %s'%(e['slot'],e['name'])for e in hero['equipment']]
        lines.extend(['宝具：'+('；'.join(gems)or'未返回'),'装备：'+('；'.join(equips)or'未返回'),''])
    return '\n'.join(lines) if lines else '服务器未返回可展示的武将资料。'


class PlayerPanel(ttk.Frame):
    """Keep query state separate from automation switches and clear results across account changes."""

    def __init__(self,parent,on_query):
        super().__init__(parent,padding=10)
        self.busy=False;self.ready=False;self.player_id=tk.StringVar()
        bar=ttk.Frame(self);bar.pack(fill='x')
        ttk.Label(bar,text='用户ID').pack(side='left')
        self.entry=ttk.Entry(bar,textvariable=self.player_id,width=24);self.entry.pack(side='left',padx=8)
        self.button=ttk.Button(bar,text='查询武将',command=on_query,state='disabled');self.button.pack(side='left')
        self.status=tk.StringVar(value='输入用户ID后点击查询；不会自动刷新。')
        ttk.Label(self,textvariable=self.status,wraplength=930).pack(anchor='w',pady=8)
        area=ttk.Frame(self);area.pack(fill='both',expand=True)
        self.details=tk.Text(area,wrap='word',height=10,font=('Microsoft YaHei UI',10),state='disabled')
        scroll=ttk.Scrollbar(area,orient='vertical',command=self.details.yview)
        self.details.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right',fill='y');self.details.pack(fill='both',expand=True)
        ttk.Label(self,text='仅显示服务器返回的最强武将和展示武将，不代表完整武将名单。',foreground='#666666').pack(anchor='w',pady=(6,0))

    def update_controls(self,ready):
        """Permit one manual query only when the world is connected and no query is in flight."""
        self.ready=ready
        self.button.state(['!disabled']if ready and not self.busy else['disabled'])
        self.entry.state(['disabled']if self.busy else['!disabled'])

    def set_busy(self,busy):
        """Prevent repeated clicks while this single request chain runs."""
        self.busy=busy;self.update_controls(self.ready)

    def replace_details(self,text):
        """Replace the read-only text without retaining stale rows from a different target."""
        self.details.configure(state='normal');self.details.delete('1.0','end')
        self.details.insert('1.0',text);self.details.configure(state='disabled')

    def clear(self):
        """Discard results when reconnecting or switching the logged-in account."""
        self.set_busy(False);self.replace_details('');self.status.set('输入用户ID后点击查询；不会自动刷新。')

    def apply_snapshot(self,snapshot):
        """Show cache provenance and retain the original confirmation time instead of claiming a fresh reply."""
        self.replace_details(hero_details(snapshot))
        source='本地缓存'if snapshot.get('from_cache')else'服务器查询'
        self.status.set(f"{snapshot['nickname']}（{snapshot['display_id']}）　{source}，确认时间：{display_time(snapshot['confirmed_ms'])}"+
                        ('；'+snapshot['cache_warning']if snapshot.get('cache_warning')else''))
