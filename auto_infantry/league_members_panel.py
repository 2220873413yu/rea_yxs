"""Alliance-first browsing of saved sightings, public server rosters and manually queried hero details."""
import tkinter as tk
from tkinter import ttk
from player_panel import hero_details
from collection_display import display_time
from league_comparison import compare_leagues


class LeagueMembersPanel(ttk.Frame):
    """Keep league selection local; only explicit search/list/profile controls send requests."""

    def __init__(self,parent,on_query,on_stop=None,on_export_stop=None):
        """Build passive league browsing and explicit search/query/export/cancel controls."""
        super().__init__(parent,padding=10)
        self.ready=False;self.busy=False;self.on_query=on_query;self.search_running=False
        self.local_records=[];self.local_scope=None;self.league_snapshot=None
        self.remote_leagues={};self.own_league_id=None;self.selected_league=None;self.comparison_rows=[]
        self.view_source='local'
        self.export_running=False
        bar=ttk.Frame(self);bar.pack(fill='x')
        self.search=ttk.Button(bar,text='搜索本图用户',command=lambda:self.on_query('map_scan',0))
        self.stop_search=ttk.Button(bar,text='停止搜索',command=on_stop)
        self.local_button=ttk.Button(bar,text='查看本地记录',command=self.show_local)
        self.refresh=ttk.Button(bar,text='更新联盟人数',command=lambda:self.on_query('leagues',0))
        self.load=ttk.Button(bar,text='加载服务器成员',command=self.load_members)
        self.query=ttk.Button(bar,text='查询选中玩家',command=self.query_member)
        self.stop_export=ttk.Button(bar,text='停止导出',command=on_export_stop)
        self.clear_cache=ttk.Button(bar,text='清空资料缓存',command=lambda:self.on_query('clear_profile_cache',0))
        for button in (self.search,self.stop_search,self.local_button,self.refresh,self.load,self.query,self.stop_export,self.clear_cache):button.pack(side='left',padx=(0,6))
        self.status=tk.StringVar(value='先选择左侧联盟，再选择玩家查询武将；切换联盟只读取本地记录。')
        ttk.Label(self,textvariable=self.status,wraplength=930).pack(anchor='w',pady=6)
        area=ttk.Panedwindow(self,orient='horizontal');area.pack(fill='both',expand=True)
        league_area=ttk.LabelFrame(area,text='① 联盟',padding=4)
        member_area=ttk.LabelFrame(area,text='② 联盟玩家',padding=4)
        detail_area=ttk.LabelFrame(area,text='③ 武将资料',padding=4)
        area.add(league_area,weight=3);area.add(member_area,weight=2);area.add(detail_area,weight=4)
        self.comparison_time=tk.StringVar(value='人数更新：未查询\n本地记录：暂无')
        ttk.Label(league_area,textvariable=self.comparison_time).pack(anchor='w',pady=(0,3))
        table=ttk.Frame(league_area);table.pack(fill='both',expand=True)
        self.comparison=ttk.Treeview(table,columns=('name','total','discovered','difference'),show='headings',height=5,selectmode='browse')
        for key,label,width in (('name','联盟',100),('total','接口',48),('discovered','已发现',55),('difference','差额',50)):
            self.comparison.heading(key,text=label);self.comparison.column(key,width=width,anchor='w'if key=='name'else'center')
        scroll=ttk.Scrollbar(table,orient='vertical',command=self.comparison.yview)
        self.comparison.configure(yscrollcommand=scroll.set);scroll.pack(side='right',fill='y');self.comparison.pack(fill='both',expand=True)
        self.comparison_note=tk.StringVar(value='差额仅供参考，不保证完整名单。')
        ttk.Label(league_area,textvariable=self.comparison_note,wraplength=285,foreground='#666666').pack(anchor='w',pady=(3,0))
        self.comparison.bind('<<TreeviewSelect>>',lambda e:self.select_league())
        self.league_menu=tk.Menu(self,tearoff=False)
        self.league_menu.add_command(label='导出Excel（已记录成员）',command=self.export_league)
        self.comparison.bind('<Button-3>',self.open_league_menu)
        self.member_title=tk.StringVar(value='选择联盟后显示本地玩家')
        ttk.Label(member_area,textvariable=self.member_title,wraplength=205).pack(anchor='w',pady=(0,3))
        name_bar=ttk.Frame(member_area);name_bar.pack(fill='x',pady=(0,4))
        ttk.Label(name_bar,text='全图名字搜索').pack(side='left')
        self.name_filter=tk.StringVar()
        self.name_entry=ttk.Entry(name_bar,textvariable=self.name_filter,width=12)
        self.name_entry.pack(side='left',fill='x',expand=True,padx=4)
        self.clear_name=ttk.Button(name_bar,text='清空',width=4,command=lambda:self.name_filter.set(''))
        self.clear_name.pack(side='left')
        members=ttk.Frame(member_area);members.pack(fill='both',expand=True)
        self.tree=ttk.Treeview(members,columns=('name','league','coords'),displaycolumns=('name','coords'),show='headings',height=5,selectmode='browse')
        for key,label,width in (('name','玩家',115),('league','联盟',100),('coords','坐标',70)):
            self.tree.heading(key,text=label);self.tree.column(key,width=width)
        scroll=ttk.Scrollbar(members,orient='vertical',command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set);scroll.pack(side='right',fill='y');self.tree.pack(fill='both',expand=True)
        self.tree.bind('<Double-1>',lambda e:self.query_member())
        for tree in (self.comparison,self.tree):
            tree.bind('<Button-1>',lambda e:'break'if self.busy else None,add='+')
            tree.bind('<KeyPress>',lambda e:'break'if self.busy else None,add='+')
        self.details=tk.Text(detail_area,height=8,width=36,wrap='word',font=('Microsoft YaHei UI',10),state='disabled')
        scroll=ttk.Scrollbar(detail_area,orient='vertical',command=self.details.yview)
        self.details.configure(yscrollcommand=scroll.set);scroll.pack(side='right',fill='y');self.details.pack(fill='both',expand=True)
        self.name_filter.trace_add('write',self.filter_names)
        self.update_controls(False)

    def update_controls(self,ready):
        """Freeze query selection in flight, retaining cancellation for active search or export work."""
        self.ready=ready;enabled=ready and not self.busy
        for button in (self.refresh,self.search,self.local_button,self.clear_cache):button.state(['!disabled']if enabled else['disabled'])
        self.load.state(['!disabled']if enabled and self.selected_league is not None else['disabled'])
        self.query.state(['!disabled']if enabled and self.tree.get_children() else['disabled'])
        self.stop_search.state(['!disabled']if ready and self.search_running else['disabled'])
        self.stop_export.state(['!disabled']if ready and self.export_running else['disabled'])
        for widget in (self.name_entry,self.clear_name):widget.state(['disabled']if self.busy else['!disabled'])

    def open_league_menu(self,event):
        """Right-click the actual alliance row; merely opening its menu sends no request."""
        if self.busy or not self.ready:return
        row=self.comparison.identify_row(event.y)
        if not row:return
        self.comparison.selection_set(row);self.select_league()
        has_members=any(r['league_id']==self.selected_league for r in self.local_records)
        self.league_menu.entryconfigure(0,state='normal'if has_members else'disabled')
        try:self.league_menu.tk_popup(event.x_root,event.y_root)
        finally:self.league_menu.grab_release()

    def export_league(self):
        """Export only the chosen league's saved users, irrespective of the currently visible roster source."""
        if self.busy or not self.ready or self.selected_league is None:return
        if not any(r['league_id']==self.selected_league for r in self.local_records):
            self.status.set('该联盟没有已记录成员，请先搜索本图用户');return
        self.on_query('export',self.selected_league)

    def apply_export_progress(self,snapshot):
        """Show click-owned progress and enable cancellation without driving any network work."""
        self.export_running=snapshot['active']
        if self.export_running:self.status.set(f"正在导出：已处理 {snapshot['done']} / {snapshot['total']} 人；逐人查询，不自动重试。")
        self.update_controls(self.ready)

    def set_busy(self,busy):
        """Share one click gate with individual-player queries without triggering any background reads."""
        self.busy=busy;self.update_controls(self.ready)

    def replace_details(self,value):
        """Clear a previous player's profile before changing the selected league or starting another query."""
        self.details.configure(state='normal');self.details.delete('1.0','end');self.details.insert('1.0',value);self.details.configure(state='disabled')

    def clear_roster(self):
        """Remove visible player handles without deleting their persisted map observations."""
        self.tree.delete(*self.tree.get_children());self.replace_details('');self.update_controls(self.ready)

    def clear(self):
        """Drop all previous-account league choices, sightings and profile results."""
        self.local_records=[];self.local_scope=None;self.league_snapshot=None;self.remote_leagues={};self.own_league_id=None
        self.selected_league=None;self.comparison_rows=[];self.search_running=False;self.export_running=False;self.busy=False;self.view_source='local'
        self.name_filter.set('')
        self.comparison.delete(*self.comparison.get_children());self.clear_roster()
        self.comparison_time.set('人数更新：未查询\n本地记录：暂无')
        self.comparison_note.set('差额仅供参考，不保证完整名单。');self.member_title.set('选择联盟后显示本地玩家')
        self.status.set('先选择左侧联盟，再选择玩家查询武将；切换联盟只读取本地记录。')

    def load_members(self):
        """Only this button requests the chosen league's native full/partial server roster."""
        if not self.busy and self.ready and self.selected_league is not None:self.on_query('roster',self.selected_league)

    def query_member(self):
        """Query only a deliberately chosen local or current server-roster player."""
        if self.busy or not self.ready:return
        selected=self.tree.selection()
        if not selected:self.status.set('请先选择一名玩家');return
        if selected[0].startswith('local:'):self.on_query('saved_member',selected[0][6:])
        else:self.on_query('member',int(selected[0]))

    def apply_index(self,snapshot):
        """Restore local sightings/totals and keep the same selected league when it still exists."""
        self.local_scope=snapshot['scope'];self.local_records=snapshot['players'];self.league_snapshot=snapshot.get('league_snapshot')
        self.refresh_comparison()

    def refresh_comparison(self):
        """Build league navigation from saved sightings, saved counts and explicitly loaded public leagues."""
        rows={r['league_id']:r for r in compare_leagues(self.local_records,self.league_snapshot)}
        for league_id,league in self.remote_leagues.items():
            if league_id not in rows:rows[league_id]=dict(league_id=league_id,name=league['name'],total=league.get('member_count'),
                discovered=0,difference=league.get('member_count'),observed_ms=0,confirmed_ms=0,note='差额仅供参考'if'member_count'in league else'接口人数未查询')
        self.comparison_rows=sorted(rows.values(),key=lambda r:(r['name'],r['league_id']))
        if self.selected_league not in rows:
            self.selected_league=(self.own_league_id if self.own_league_id in rows else
                max(self.comparison_rows,key=lambda r:r['discovered'])['league_id']if rows else None)
        self.comparison.delete(*self.comparison.get_children())
        for row in self.comparison_rows:
            gap=row['difference'];difference='—'if gap is None else f'超出{-gap}'if gap<0 else str(gap)
            self.comparison.insert('','end',iid=str(row['league_id']),values=(row['name'],
                '未查询'if row['total']is None else row['total'],row['discovered'],difference))
        if self.selected_league is not None:self.comparison.selection_set(str(self.selected_league))
        self.update_comparison_time();self.show_local()

    def select_league(self):
        """A league click filters local sightings only; queued Tk selection events cannot erase fresh server rows."""
        selected=self.comparison.selection()
        if not selected:return
        league_id=int(selected[0])
        if self.busy:
            if self.selected_league is not None and league_id!=self.selected_league:self.comparison.selection_set(str(self.selected_league))
            return
        if league_id==self.selected_league:
            self.update_comparison_time();return
        self.selected_league=league_id;self.update_comparison_time();self.show_local()

    def update_comparison_time(self):
        """Show the selected league's independent count/observation times and explain gaps without marking errors."""
        row=next((r for r in self.comparison_rows if r['league_id']==self.selected_league),None)
        confirmed=row['confirmed_ms']if row else 0;observed=row['observed_ms']if row else 0
        self.comparison_time.set('人数更新：'+(display_time(confirmed)if confirmed else'未查询')+
            '\n本地记录：'+(display_time(observed)if observed else'暂无'))
        self.comparison_note.set(row['note']if row else'差额仅供参考，不保证完整名单。')

    def show_local(self):
        """Browse one league normally; a nickname fragment searches all saved map players without requests."""
        self.clear_roster();self.view_source='local'
        keyword=self.name_filter.get().strip().casefold()
        rows=([r for r in self.local_records if keyword in r['name'].casefold()]if keyword else
              [r for r in self.local_records if r['league_id']==self.selected_league])
        self.tree.configure(displaycolumns=('name','league','coords')if keyword else('name','coords'))
        name=next((r['name']for r in self.comparison_rows if r['league_id']==self.selected_league),'未选择联盟')
        for row in rows:self.tree.insert('','end',iid='local:'+row['record_key'],values=(row['name'],row['league_name']or'未入盟',f"{row['x']},{row['y']}"))
        self.member_title.set(f'全图匹配 {len(rows)} / {len(self.local_records)}人'if keyword else f'{name} · 本地 {len(rows)}人')
        self.status.set(f'名字搜索：全图本地记录匹配{len(rows)}人，不区分联盟；点击玩家后可查询武将。'if keyword else
                        f'{name}：本地已发现{len(rows)}人；点击玩家后可查询武将。'+
                        ('该联盟尚无本地记录，可搜索本图用户或手动加载服务器成员。'if not rows else'差额仅供参考。'))
        self.update_controls(self.ready)

    def filter_names(self,*_):
        """Filter cached map names on typing; never send searches or disturb an in-flight player query."""
        if not self.busy:self.show_local()

    def apply_search_progress(self,snapshot):
        """Display the clicked search's finite progress, without generating additional requests."""
        self.search_running=snapshot['active']
        if snapshot['active']:self.status.set(f"搜索区域 {snapshot['done']} / {snapshot['total']}；已保存{snapshot['found']}名玩家。停止后保留已发现记录。")
        self.update_controls(self.ready)

    def apply_leagues(self,snapshot):
        """Add manually fetched league choices; selection still shows saved users rather than requesting members."""
        self.remote_leagues={r['league_id']:r for r in snapshot['leagues']};self.own_league_id=snapshot['own_league_id']
        self.refresh_comparison()

    def apply_roster(self,snapshot):
        """Display the explicitly requested server roster and label its scope instead of merging it into map sightings."""
        league_id=snapshot['league_id'];self.selected_league=league_id
        self.remote_leagues.setdefault(league_id,dict(league_id=league_id,name=snapshot['name']))
        self.refresh_comparison();self.clear_roster();self.view_source='server'
        for row in snapshot['members']:self.tree.insert('','end',iid=str(row['member_key']),values=(row['name'],snapshot['name'],'—'))
        scope='公开成员资料，不保证完整名单'if snapshot['public']else'本盟成员名单'
        self.member_title.set(f"{snapshot['name']} · 服务器 {len(snapshot['members'])}人")
        self.status.set(f"{snapshot['name']}：{scope}；确认 {display_time(snapshot['confirmed_ms'])}。查看本地记录可切回地图已发现玩家。")
        if self.name_filter.get().strip():self.show_local()
        else:self.tree.configure(displaycolumns=('name','coords'))
        self.update_controls(self.ready)

    def apply_member(self,snapshot):
        """Keep identity-confirmed hero data in the right pane, with the server-returned nickname/time."""
        self.replace_details(hero_details(snapshot))
        source='本地缓存'if snapshot.get('from_cache')else'服务器查询'
        self.status.set(f"{snapshot['nickname']}（{snapshot.get('display_id')or'ID未返回'}）　{source}，确认 {display_time(snapshot['confirmed_ms'])}"+
                        ('；'+snapshot['cache_warning']if snapshot.get('cache_warning')else''))
