"""Standalone QQ/WeChat accounts, explicit game platforms, role binding and manual gift actions."""
from io import BytesIO
from dataclasses import replace
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk,messagebox
from PIL import Image,ImageTk
from .auth import QQAuth,WeChatAuth
from .roles import PLATFORMS,PROVIDERS
from .role_dialog import choose_login,RoleDialog
from .gifts import GiftClient
from .bounty import BountyClient
from .weekly import WeeklyClient
from .gscore import GScoreClient
from .exchange import ExchangeClient,ALLOWED
from .history import HistoryStore,ClaimRecorder,STATUSES
from .batch import BatchRunner
from .secure_store import AccountStore,StoreError
from .transport import ServiceError
from .protocol import ProtocolError
from .binding_session import LoginExpiredError


class App:
    """Keep all network work in one worker and expose only safe account/state projections to Tk."""
    def __init__(self):
        """Build manual account-specific gift and G-score controls; startup performs no business requests."""
        self.root=tk.Tk();self.root.title('心悦助手 · 账号与英雄杀礼包');self.root.geometry('1000x980')
        self.store=AccountStore();self.events=queue.Queue();self.busy=False;self.stop=threading.Event()
        self.history=HistoryStore();self.batch_stop=threading.Event();self.history_window=None
        self.states={};self.bounty_states={};self.weekly_states={};self.gscore_states={};self.exchange_states={};self.active='';self.photo=None;self.qr=None;self.pending_roles=None
        self.status=tk.StringVar(value='仅加载本地账号；选择账号后手动查询或签到。')
        box=ttk.Frame(self.root,padding=18);box.pack(fill='both',expand=True)
        ttk.Label(box,text='心悦俱乐部 · 英雄杀礼包',font=('Microsoft YaHei UI',18,'bold')).pack(anchor='w')
        ttk.Label(box,text='QQ / 微信独立扫码；先选安卓或iOS，角色确认后才绑定。账号本机加密保存，启动不查询、不签到。').pack(anchor='w',pady=(5,14))
        bar=ttk.Frame(box);bar.pack(fill='x')
        self.actions=[]
        for label,command in [('添加 / 更新账号',self.login),('选择角色 / 绑定',self.open_roles),('查询签到状态',self.query),('签到一次',self.signin)]:
            button=ttk.Button(bar,text=label,command=command);button.pack(side='left',padx=(0,8));self.actions.append(button)
        batch_button=ttk.Button(bar,text='一键签到（全部账号）',command=self.start_batch);batch_button.pack(side='left',padx=(0,8));self.actions.append(batch_button)
        self.batch_stop_button=ttk.Button(bar,text='停止批量',command=self.stop_batch,state='disabled');self.batch_stop_button.pack(side='left',padx=(0,8))
        ttk.Button(bar,text='领取记录',command=self.show_history).pack(side='left')
        self.accounts=ttk.Treeview(box,columns=('name','provider','saved'),show='headings',height=4,selectmode='browse')
        for key,title,width in [('name','账号昵称',210),('provider','选定平台 / 登录方式',200),('saved','票据保存时间（UTC）',300)]:
            self.accounts.heading(key,text=title);self.accounts.column(key,width=width)
        self.accounts.pack(fill='x',pady=14);self.accounts.bind('<<TreeviewSelect>>',self.select)
        self.detail=tk.StringVar(value='尚未查询服务器状态。')
        ttk.Label(box,textvariable=self.detail,wraplength=790,justify='left').pack(anchor='w',pady=8)
        point_tabs=ttk.Notebook(box);point_tabs.pack(fill='x',pady=8)
        points=ttk.Frame(point_tabs,padding=10);point_tabs.add(points,text='G分签到')
        pointbar=ttk.Frame(points);pointbar.pack(fill='x')
        for label,command in [('查询G分签到',self.query_gscore),('普通签到一次',self.signin_gscore)]:
            button=ttk.Button(pointbar,text=label,command=command);button.pack(side='left',padx=(0,8));self.actions.append(button)
            if label=='普通签到一次':self.gscore_sign_button=button
        self.gscore_detail=tk.StringVar(value='尚未查询。本功能仅领取基础签到奖励，不看广告、不抽奖、不兑换。')
        ttk.Label(points,textvariable=self.gscore_detail,wraplength=810,justify='left').pack(anchor='w',pady=(10,2))
        exchange=ttk.Frame(point_tabs,padding=10);point_tabs.add(exchange,text='G分手动兑换')
        exchange_bar=ttk.Frame(exchange);exchange_bar.pack(fill='x');self.exchange_buttons={}
        for label,command in [('查询兑换状态',self.query_exchange),('兑换粮木矿礼盒',lambda:self.receive_exchange('粮木矿礼盒')),
                              ('兑换元神宝盒',lambda:self.receive_exchange('元神宝盒'))]:
            button=ttk.Button(exchange_bar,text=label,command=command);button.pack(side='left',padx=(0,8));self.actions.append(button)
            if label!='查询兑换状态':self.exchange_buttons[label[2:]]=button
        self.exchange_table=ttk.Treeview(exchange,columns=('title','quantity','cost','cycle','count','status'),show='headings',height=2)
        for key,title,width in [('title','礼包',150),('quantity','每次数量',90),('cost','消耗G分',90),('cycle','周期',90),('count','已兑/上限',100),('status','服务器状态',240)]:
            self.exchange_table.heading(key,text=title);self.exchange_table.column(key,width=width)
        self.exchange_table.pack(fill='x',pady=8)
        self.exchange_detail=tk.StringVar(value='尚未查询。点击兑换后确认角色及消耗；不自动兑换，结果不明不重发。')
        ttk.Label(exchange,textvariable=self.exchange_detail,wraplength=900,justify='left').pack(anchor='w')
        weekly=ttk.LabelFrame(box,text='超级周礼包 · 以服务器当前资格为准',padding=10);weekly.pack(fill='x',pady=8)
        weekbar=ttk.Frame(weekly);weekbar.pack(fill='x')
        for label,command in [('查询周礼包',self.query_weekly),('领取周礼包一次',self.receive_weekly)]:
            button=ttk.Button(weekbar,text=label,command=command);button.pack(side='left',padx=(0,8));self.actions.append(button)
            if label=='领取周礼包一次':self.weekly_receive_button=button
        self.weekly_detail=tk.StringVar(value='尚未查询。仅服务器明确可领、有剩余次数且零消耗时允许领取。')
        ttk.Label(weekly,textvariable=self.weekly_detail,wraplength=810,justify='left').pack(anchor='w',pady=(10,2))
        tasks=ttk.LabelFrame(box,text='赏金任务 · 英雄杀',padding=10);tasks.pack(fill='x',pady=10)
        taskbar=ttk.Frame(tasks);taskbar.pack(fill='x')
        self.bounty_buttons={}
        for label,command in [('查询赏金任务',self.query_bounty),('领取每日礼包',lambda:self.receive_bounty('每日礼包')),
                              ('抽奖一次',lambda:self.receive_bounty('抽奖礼包'))]:
            button=ttk.Button(taskbar,text=label,command=command);button.pack(side='left',padx=(0,8));self.actions.append(button)
            self.bounty_buttons[label]=button
        self.task_table=ttk.Treeview(tasks,columns=('title','state','count','cost','reward'),show='headings',height=2,selectmode='browse')
        for key,title,width in [('title','任务',105),('state','服务器状态',130),('count','已用/上限',80),('cost','消耗分值',80),('reward','奖励/候选奖池',380)]:
            self.task_table.heading(key,text=title);self.task_table.column(key,width=width)
        self.task_table.pack(fill='x',pady=10);self.task_table.bind('<<TreeviewSelect>>',self.show_task)
        self.bounty_detail=tk.StringVar(value='尚未查询赏金任务。只开放零消耗的每日礼包和抽奖礼包。')
        ttk.Label(tasks,textvariable=self.bounty_detail,wraplength=810,justify='left').pack(anchor='w')
        ttk.Separator(box).pack(fill='x',pady=12)
        ttk.Label(box,textvariable=self.status,wraplength=790,justify='left').pack(anchor='w')
        ttk.Label(box,text='支持QQ / 微信独立扫码；角色绑定须单独选择确认，不自动解绑。添加账号不签到、不领奖。\n签到、礼包和手动兑换保持点击触发，按账号、周期防重复；结果不明不自动重发，无固定业务轮询。',
                  foreground='#666666',wraplength=790).pack(anchor='w',pady=16)
        self.reload();self.root.after(100,self.consume);self.root.protocol('WM_DELETE_WINDOW',self.close)

    def record_action(self,account,role,action,client,operation,kind):
        """Share the durable local history path between every manual entry point and batch execution."""
        status,message=ClaimRecorder(self.history).execute(account,role,action,client,operation)
        self.events.put(('status',message))
        if hasattr(client,'last_state'):self.events.put((kind,(account['profile_id'],client.last_state)))
        return status

    def start_batch(self):
        """Freeze the local account list, perform read-only preflight, then await one explicit plan confirmation."""
        if self.busy:return
        rows=tuple(self.store.list())
        if not rows:self.status.set('请先添加账号。');return
        self.batch_stop=threading.Event();stop=self.batch_stop
        self.batch_stop_button.configure(state='normal')
        def job():
            """Keep all requests sequential and wait for the UI approval without blocking Tk's event loop."""
            runner=BatchRunner(self.store,self.history)
            progress=lambda message:self.events.put(('status',message))
            on_state=lambda kind,key,state:self.events.put((kind,(key,state)))
            plan=runner.prepare(rows,stop,on_state,progress)
            if stop.is_set():self.events.put(('status','批量预查已停止，未领取。'));return
            gate=threading.Event();decision={'approved':False}
            self.events.put(('batch_plan',(plan,gate,decision)))
            while not gate.wait(.2):
                if stop.is_set():return
            if not decision['approved'] or stop.is_set():
                self.events.put(('status','已取消批量领取，未提交领取请求。'));return
            result=runner.execute(plan,stop,on_state,progress)
            self.events.put(('status',f"批量{'已停止' if result.get('cancelled') else '完成'}：成功 {result.get('success',0)}，跳过 {result.get('skipped',0)}，失败 {result.get('failed',0)}，待确认 {result.get('uncertain',0)}。详见领取记录。"))
        self.run(job)

    def stop_batch(self):
        """Stop only future steps; an already dispatched request still gets its verification and history update."""
        self.batch_stop.set();self.status.set('已请求停止；正在处理的请求完成核对后停止，不再派发后续任务。')

    def confirm_batch(self,plan,gate,decision):
        """Present the full scrollable account/role plan; consent applies only to this one batch."""
        dialog=tk.Toplevel(self.root);dialog.title('确认本次一键签到');dialog.geometry('780x560');dialog.transient(self.root);dialog.grab_set()
        ready=sum(s.status=='ready' for s in plan)
        ttk.Label(dialog,text=f'本轮 {len({s.account_key for s in plan})} 个账号，预查可领取 {ready} 项',font=('Microsoft YaHei UI',13,'bold')).pack(pady=12)
        ttk.Label(dialog,text='只处理G分签到、普通周礼包、每日礼包和免费抽奖。不会兑换、看广告或改绑定。').pack(pady=4)
        frame=ttk.Frame(dialog);frame.pack(fill='both',expand=True,padx=15,pady=10)
        text=tk.Text(frame,wrap='word');scroll=ttk.Scrollbar(frame,command=text.yview);text.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right',fill='y');text.pack(fill='both',expand=True);text.insert('1.0',BatchRunner.summary(plan));text.configure(state='disabled')
        def finish(approved):
            """Signal the worker exactly once after closing the confirmation, including window-close cancellation."""
            decision['approved']=approved;dialog.destroy();gate.set()
        buttons=ttk.Frame(dialog);buttons.pack(pady=12)
        ttk.Button(buttons,text='取消',command=lambda:finish(False)).pack(side='left',padx=10)
        ttk.Button(buttons,text='确认并开始本轮',command=lambda:finish(True)).pack(side='left',padx=10)
        dialog.protocol('WM_DELETE_WINDOW',lambda:finish(False))

    def show_history(self):
        """Display only local receipt rows; opening or refreshing this window never calls the service."""
        if self.history_window and self.history_window.winfo_exists():self.history_window.lift();return
        window=tk.Toplevel(self.root);window.title('本地领取记录');window.geometry('1120x560');self.history_window=window
        bar=ttk.Frame(window,padding=10);bar.pack(fill='x');filter_value=tk.StringVar(value='全部')
        labels={'全部':'',**{label:key for key,label in STATUSES.items() if key!='running'}}
        ttk.Label(bar,text='状态：').pack(side='left')
        choices=ttk.Combobox(bar,textvariable=filter_value,values=list(labels),state='readonly',width=12);choices.pack(side='left')
        ttk.Label(bar,text='仅本机保存；最近1000条；历史操作不会补造领取时间。').pack(side='left',padx=15)
        frame=ttk.Frame(window,padding=10);frame.pack(fill='both',expand=True)
        table=ttk.Treeview(frame,columns=('time','account','role','action','status','rewards'),show='headings')
        for key,title,width in [('time','时间（北京时间）',165),('account','账号',110),('role','角色',210),('action','项目',125),('status','结果',70),('rewards','实际奖品',340)]:
            table.heading(key,text=title);table.column(key,width=width)
        scroll=ttk.Scrollbar(frame,orient='vertical',command=table.yview);table.configure(yscrollcommand=scroll.set);scroll.pack(side='right',fill='y');table.pack(fill='both',expand=True)
        detail=tk.StringVar(value='点击一条记录查看详情；候选奖池不会作为实际奖品保存。')
        ttk.Label(window,textvariable=detail,wraplength=1080,justify='left',padding=10).pack(fill='x');rows={}
        def refresh(event=None):
            """Filter the local database and render unknown/interrupted results without retrying any operation."""
            table.delete(*table.get_children());rows.clear()
            try:values=self.history.list(labels.get(filter_value.get(),''))
            except Exception:detail.set('本地记录读取失败；不会发起网络请求。');return
            for row in values:
                key=str(row['id']);rows[key]=row
                table.insert('', 'end',iid=key,values=(row['updated'],row['account'],row['role'],row['action'],STATUSES[row['status']],row['rewards']))
        def select(event=None):
            """Show both submission and update times with the stored safe business explanation."""
            selected=table.selection()
            if selected:
                row=rows[selected[0]];detail.set('开始：'+row['created']+'；最后确认：'+row['updated']+'；'+row['detail'])
        ttk.Button(bar,text='刷新本地记录',command=refresh).pack(side='right');choices.bind('<<ComboboxSelected>>',refresh);table.bind('<<TreeviewSelect>>',select);refresh()

    def reload(self,selected=''):
        """Load encrypted local records only; retain account selection without requesting any endpoint."""
        self.accounts.delete(*self.accounts.get_children())
        rows=self.store.list()
        for row in rows:
            platform=PLATFORMS.get(row.get('game_device'),'平台未选择')
            key=row['profile_id'];self.accounts.insert('', 'end',iid=key,values=(row.get('nickname') or '已保存账号',platform+' / '+PROVIDERS[row['provider']],row['saved_at'][:19].replace('T',' ')))
        selected=selected or (max(rows,key=lambda row:row['saved_at'])['profile_id'] if rows else '')
        if selected and self.accounts.exists(selected):self.accounts.selection_set(selected);self.active=selected

    def select(self,event=None):
        """Show only the selected account's cached state, without automatic queries on selection."""
        if self.busy:return
        selected=self.accounts.selection()
        self.active=selected[0] if selected else ''
        state=self.states.get(self.active)
        self.detail.set((state.role_label+'\n'+state.describe()) if state else '尚未查询本账号的服务器状态。')
        self.render_bounty()
        self.render_weekly()
        self.render_gscore()
        self.render_exchange()

    def render_exchange(self):
        """Render only selected-account exchange data, disabling spent quotas and insufficient balances."""
        self.exchange_table.delete(*self.exchange_table.get_children())
        state=self.exchange_states.get(self.active)
        if state:
            for gift in sorted(state.gifts,key=lambda g:list(ALLOWED).index(g.title)):
                label=gift.describe()
                if gift.available and state.balance<gift.cost:label='G分不足'
                if state.restricted or not state.role_key:label='绑定未确认或受限'
                self.exchange_table.insert('', 'end',values=(gift.title,gift.quantity,gift.cost,'每日' if gift.cycle==1 else '每周' if gift.cycle==2 else '未知',f'{gift.used}/{gift.total}',label))
            self.exchange_detail.set(state.role_label+f'；当前G分 {state.balance}。每次确认后仅兑换一次，不自动兑换。')
        else:self.exchange_detail.set('尚未查询本账号兑换状态。点击才查询或兑换，不自动消耗G分。')
        for title,button in self.exchange_buttons.items():
            gift=next((g for g in state.gifts if g.title==title),None) if state else None
            button.configure(state='normal' if state and gift and state.eligible(gift) and not self.busy else 'disabled')

    def query_exchange(self):
        """Read live account balance, recipient and the two exchange quotas without spending G-score."""
        key=self.active
        if not key:self.status.set('请先选择账号。');return
        self.status.set('正在只读查询G分兑换状态、价格和剩余次数…')
        def job():
            """Keep the exchange snapshot associated with the account selected when query was clicked."""
            state=ExchangeClient().query(self.store.load(key));self.events.put(('exchange',(key,state)))
            self.events.put(('status',f'兑换查询完成：余额 {state.balance} G分；本次仅查询，未兑换。'))
        self.run(job)

    def receive_exchange(self,title):
        """Always confirm account, current recipient, exact reward and G-score cost before dispatching once."""
        key=self.active;state=self.exchange_states.get(key)
        if self.busy:return
        gift=next((g for g in state.gifts if g.title==title),None) if state else None
        if not state or not gift or not state.eligible(gift):self.status.set('请先查询；余额不足或本周期不可兑换。');return
        account=self.store.load(key)
        # Unlike free-gift role consent, remembered consent never skips a G-score spending confirmation.
        confirmed=messagebox.askokcancel('确认消耗G分兑换',
            f"账号：{account.get('nickname') or 'QQ账号'}\n角色：{state.role_label}\n\n"
            f'兑换：{gift.title} ×{gift.quantity}\n消耗：{gift.cost} G分\n当前余额：{state.balance} G分\n\n仅提交一次，超时不重发。',parent=self.root)
        if not confirmed:return
        self.status.set('正在重新核对角色、价格和次数；符合确认内容才兑换一次…')
        def job():
            """Recheck the immutable confirmed gift and render fresh post-state even after uncertain results."""
            client=ExchangeClient();account=self.store.load(key)
            self.record_action(account,state.role_label,'手动兑换：'+gift.title,client,
                lambda:client.receive(account,state.role_key,gift),'exchange')
        self.run(job)

    def render_gscore(self):
        """Render only the selected account snapshot and disable signing when signed, unknown or busy."""
        state=self.gscore_states.get(self.active)
        self.gscore_detail.set(state.describe() if state else '尚未查询本账号G分；只领取基础奖励，不看广告、不兑换。')
        self.gscore_sign_button.configure(state='normal' if state and state.available and not self.busy else 'disabled')

    def query_gscore(self):
        """Read account-level G-score status on demand without querying or changing game-role binding."""
        key=self.active
        if not key:self.status.set('请先选择账号。');return
        self.status.set('正在只读查询G分、连续签到天数和今日状态…')
        def job():
            """Keep this status response attached to the account selected at dispatch."""
            state=GScoreClient().query(self.store.load(key));self.events.put(('gscore',(key,state)))
            self.events.put(('status','G分查询完成：'+state.describe()+'。本次操作仅查询。'))
        self.run(job)

    def signin_gscore(self):
        """Fresh-check one ordinary signup and render its result without role changes or automatic replay."""
        key=self.active;state=self.gscore_states.get(key)
        if self.busy:return
        if not state or not state.available:self.status.set(state.describe() if state else '请先查询G分签到。');return
        self.status.set('正在重新查询G分签到状态；未签到才提交一次普通签到，不看广告…')
        def job():
            """Publish the latest state even after uncertain submission so stale eligibility is not reused."""
            client=GScoreClient();account=self.store.load(key)
            self.record_action(account,'心悦账号G分','G分签到',client,lambda:client.signin(account),'gscore')
        self.run(job)

    def render_weekly(self):
        """Show the selected account's cached eligibility and disable claiming for all unknown/restricted states."""
        state=self.weekly_states.get(self.active)
        if state:
            reward='、'.join(f'{name} ×{count}' for name,count in state.rewards) or '服务器未返回奖励说明'
            self.weekly_detail.set(state.role_label+'\n'+state.describe()+f'；次数 {state.used}/{state.total}；消耗 {state.cost} 分\n奖励：'+reward)
        else:self.weekly_detail.set('尚未查询本账号周礼包。资格不足、未激活、次数用尽或状态未知时不领取。')
        self.weekly_receive_button.configure(state='normal' if state and state.available and not self.busy else 'disabled')

    def query_weekly(self):
        """Read weekly qualification once after a user click, without activating, upgrading or claiming."""
        key=self.active
        if not key:self.status.set('请先选择账号。');return
        self.status.set('正在只读查询周礼包资格、角色、次数和消耗…')
        def job():
            """Keep the weekly response tied to the account selected at dispatch."""
            state=WeeklyClient().query(self.store.load(key));self.events.put(('weekly',(key,state)))
            self.events.put(('status','周礼包查询完成：'+state.describe()+'。本次操作仅查询。'))
        self.run(job)

    def receive_weekly(self):
        """Require account-specific role consent and revalidate live eligibility before one weekly claim."""
        key=self.active;state=self.weekly_states.get(key)
        if self.busy:return
        if not state or not state.available:self.status.set(state.describe() if state else '请先查询周礼包。');return
        def submit():
            """Use the confirmed role and gift snapshot while the worker rejects any later server changes."""
            self.status.set('正在重新检查周礼包资格；仅零消耗时提交一次，不会自动重试…')
            def job():
                """Verify business success and refreshed server usage without repeating the mutation."""
                client=WeeklyClient();account=self.store.load(key)
                self.record_action(account,state.role_label,'周礼包',client,
                    lambda:client.receive(account,state.role_key,state.gift_id),'weekly')
            self.run(job)
        self.authorize_role(key,state,'领取超级周礼包一次',submit)

    def render_bounty(self):
        """Show only this account's cached task rows and gate action buttons without requesting the network."""
        self.task_table.delete(*self.task_table.get_children())
        state=self.bounty_states.get(self.active)
        if state:
            for task in sorted(state.tasks,key=lambda t:t.title!='每日礼包'):
                reward='、'.join(f'{name} ×{count}' for name,count in task.rewards)
                self.task_table.insert('', 'end',iid=task.title,values=(task.title,task.describe(),f'{task.used}/{task.total}',task.cost,reward))
            self.bounty_detail.set(state.role_label+('；服务器提示绑定受限。' if state.binding_restricted else '；点击任务行可查看奖励。'))
        else:self.bounty_detail.set('尚未查询本账号的赏金任务；启动和切换账号不会自动查询。')
        for title,button in [('每日礼包','领取每日礼包'),('抽奖礼包','抽奖一次')]:
            eligible=state and state.role_key and not state.binding_restricted and any(t.title==title and t.available for t in state.tasks)
            self.bounty_buttons[button].configure(state='normal' if eligible and not self.busy else 'disabled')

    def show_task(self,event=None):
        """Display cached candidate rewards as candidates, never as an actual lottery result."""
        selected=self.task_table.selection();state=self.bounty_states.get(self.active)
        if not selected or not state:return
        task=next((t for t in state.tasks if t.title==selected[0]),None)
        if task:
            label='候选奖池（随机一项）：' if task.kind==1 else '奖励：'
            self.bounty_detail.set(label+'、'.join(f'{name} ×{count}' for name,count in task.rewards))

    def query_bounty(self):
        """Read role and both supported task states once for the account selected when the user clicked."""
        key=self.active
        if not key:self.status.set('请先选择账号。');return
        self.status.set('正在只读查询赏金任务、次数和消耗…')
        def job():
            """Return an account-keyed snapshot and summarize actual task states without claiming or drawing."""
            state=BountyClient().query(self.store.load(key));self.events.put(('bounty',(key,state)))
            summary='；'.join(task.title+'：'+task.describe()+f'（{task.used}/{task.total}）' for task in state.tasks)
            self.events.put(('status','赏金任务查询完成：'+(summary or '服务器未返回这两项任务')+'。本次操作仅查询。'))
        self.run(job)

    def receive_bounty(self,title):
        """Require current role consent and dispatch only the named free task, once, with fresh server checks."""
        key=self.active;state=self.bounty_states.get(key)
        if self.busy:return
        if not state:self.status.set('请先查询赏金任务。');return
        task=next((t for t in state.tasks if t.title==title),None)
        if not task or not task.available or state.binding_restricted or not state.role_key:
            self.status.set('此任务当前不可执行；请查询服务器状态。');return
        def submit():
            """Use the confirmed account and exact gift ID even if list selection later changes."""
            self.status.set('正在重新核对角色、免费条件和次数；只提交一次…')
            def job():
                """Read actual server rewards and verified task state without automatic replay."""
                client=BountyClient();account=self.store.load(key)
                self.record_action(account,state.role_label,'赏金'+title,client,
                    lambda:client.receive(account,title,state.role_key,task.gift_id),'bounty')
            self.run(job)
        self.authorize_role(key,state,'免费抽奖一次' if task.kind==1 else '领取每日礼包一次',submit)

    def run(self,job):
        """Serialize work and disable entry points so repeated clicks cannot dispatch overlapping claims."""
        if self.busy:return
        self.busy=True;account_key=self.active
        for button in self.actions:button.configure(state='disabled')
        def worker():
            """Report safe errors to both the main status and any active QR dialog; never echo raw exceptions."""
            try:job()
            except LoginExpiredError as error:
                self.events.put(('session_expired',account_key))
                self.events.put(('status',str(error)));self.events.put(('qr_status',str(error)))
            except (ServiceError,StoreError,ProtocolError) as error:
                self.events.put(('status',str(error)));self.events.put(('qr_status',str(error)))
            except Exception:
                message='操作未完成，未输出凭据；请求不会自动重试。'
                self.events.put(('status',message));self.events.put(('qr_status',message))
            finally:self.events.put(('finished',None))
        threading.Thread(target=worker,daemon=True).start()

    def login(self):
        """Require a deliberate platform and provider selection before requesting a fresh official QR."""
        if self.busy:return
        choose_login(self.root,self.start_login)

    def start_login(self,choice):
        """Freeze QR provider and game platform; save approved credentials before opening the role picker."""
        if self.busy:return
        self.stop=threading.Event();stop=self.stop
        label=PROVIDERS[choice.provider]
        self.qr=tk.Toplevel(self.root);self.qr.title(choice.label+' · 扫码登录心悦');self.qr.geometry('500x590')
        self.qr.transient(self.root);self.qr.grab_set()
        self.qr.protocol('WM_DELETE_WINDOW',self.cancel_login)
        ttk.Label(self.qr,text=choice.label+'：用本人手机'+label+'扫码',font=('Microsoft YaHei UI',14,'bold')).pack(pady=15)
        self.qr_label=ttk.Label(self.qr,anchor='center');self.qr_label.pack(fill='both',expand=True)
        self.qr_status=tk.StringVar(value='正在申请新的'+label+'二维码…')
        ttk.Label(self.qr,textvariable=self.qr_status,wraplength=450).pack(pady=10)
        ttk.Button(self.qr,text='取消 / 关闭',command=self.cancel_login).pack(pady=10)
        self.status.set(choice.label+'授权期间仅处理登录；之后选择区服和角色，不签到、不领奖。')
        def job():
            """Bound QR waiting to its expiry and ignore any result arriving after user cancellation."""
            provider=QQAuth() if choice.provider=='qq' else WeChatAuth()
            challenge=provider.begin()
            if stop.is_set():return
            self.events.put(('qr_image',challenge.image))
            while not stop.is_set() and time.monotonic()<challenge.expires_at:
                state,credentials=provider.poll(challenge)
                if stop.is_set():return
                if credentials:
                    row=self.store.save(credentials,credentials.headers())
                    self.store.set_game_device(row['profile_id'],choice.device)
                    self.events.put(('saved',row))
                    if choice.provider=='wx':
                        try:
                            credentials.nickname=provider.user_info(credentials)
                            row=self.store.save(credentials,credentials.headers())
                            self.events.put(('saved',row))
                        except ServiceError:
                            self.events.put(('status','微信票据已保存；昵称暂未取得，继续只读查询角色，不自动重试登录。'))
                    if stop.is_set():return
                    self.events.put(('status',choice.label+'登录成功，Token已本机加密保存；请选择角色，未执行签到领奖。'))
                    self.events.put(('roles_after_login',(row['profile_id'],choice)))
                    self.events.put(('qr_done',None));return
                if state=='expired':break
                self.events.put(('qr_status','已扫码，请在手机确认。' if state=='scanned' else '等待'+label+'扫码…'))
                stop.wait(3)
            if not stop.is_set():self.events.put(('qr_status','二维码已过期。关闭后点击“添加 / 更新账号”重新生成。'))
        self.run(job)

    def open_roles(self,key=None,choice=None):
        """Open manual account-scoped role discovery; existing accounts must explicitly choose a platform."""
        if self.busy:return
        key=key or self.active
        if not key:self.status.set('请先选择账号。');return
        RoleDialog(self.root,self.store,key,self.binding_changed,choice,on_expired=self.login_expired)

    def login_expired(self,key):
        """Discard cached recipients for a stale ticket, retaining its encrypted file until explicit re-login."""
        for cache in (self.states,self.bounty_states,self.weekly_states,self.gscore_states,self.exchange_states):cache.pop(key,None)
        if key==self.active:
            self.detail.set('登录票据已失效或不是最新，请添加 / 更新账号重新扫码；不要因此解绑。')
            self.render_bounty();self.render_weekly();self.render_gscore();self.render_exchange()

    def binding_changed(self,key):
        """Invalidate cached gift recipients and display verified binding changes without claiming anything."""
        for cache in (self.states,self.bounty_states,self.weekly_states,self.gscore_states,self.exchange_states):cache.pop(key,None)
        self.reload(key);self.select();self.status.set('角色绑定已核对；已清除旧礼包状态，请按需手动查询，未签到领奖。')

    def cancel_login(self):
        """Cancel only this helper's pending authorization; never log out or invalidate saved accounts."""
        self.stop.set();self.pending_roles=None
        if self.qr and self.qr.winfo_exists():self.qr.destroy()
        self.qr=None

    def query(self):
        """Request current binding and sign-in state once for the explicitly selected account."""
        key=self.active
        if not key:self.status.set('请先选择账号。');return
        self.status.set('正在只读查询绑定角色和签到状态…')
        def job():
            """Bind the query result to the account captured when its button was pressed."""
            value=GiftClient().query(self.store.load(key));self.events.put(('state',(key,value)))
            self.events.put(('status','签到查询完成：'+value.describe()+'。本次操作仅查询。'))
        self.run(job)

    def signin(self):
        """Require explicit role consent unless the same binding has an unexpired 30-day local confirmation."""
        key=self.active;state=self.states.get(key)
        if self.busy:return
        if not state:self.status.set('请先查询本账号的签到状态。');return
        if not state.available:self.status.set(state.describe());return
        self.authorize_role(key,state,'签到一次',lambda:self.submit(key,state.role_key))

    def authorize_role(self,key,state,prompt,callback):
        """Share explicit same-role 30-day consent across sign-in and the two bounty actions; never rebind."""
        account=self.store.load(key);confirmation=account.get('role_confirmation',{})
        if confirmation.get('role_key')==state.role_key and confirmation.get('expires_at',0)>time.time():
            callback();return
        dialog=tk.Toplevel(self.root);dialog.title('确认礼包领取角色');dialog.geometry('480x250');dialog.transient(self.root);dialog.grab_set()
        ttk.Label(dialog,text='确认使用当前绑定角色'+prompt,font=('Microsoft YaHei UI',14,'bold')).pack(pady=18)
        ttk.Label(dialog,text=state.role_label,wraplength=440).pack(pady=8)
        remember=tk.BooleanVar(value=True)
        ttk.Checkbutton(dialog,text='30天内不需要再确认（角色变更后重新确认）',variable=remember).pack(pady=10)
        bar=ttk.Frame(dialog);bar.pack(pady=12)
        def confirm():
            """Persist user consent before submitting; this changes no server-side role binding."""
            self.store.confirm_role(key,state.role_key,state.role_label,remember.get())
            dialog.destroy();callback()
        ttk.Button(bar,text='取消',command=dialog.destroy).pack(side='left',padx=8)
        ttk.Button(bar,text='确认并执行一次',command=confirm).pack(side='left',padx=8)

    def submit(self,key,role_key):
        """Dispatch one guarded claim after a fresh preflight; no automatic resubmission on any exception."""
        self.status.set('正在核对服务器最新状态；符合条件时只提交一次签到…')
        def job():
            """Use the immutable selected account identity throughout preflight, claim and verification."""
            account=self.store.load(key);client=GiftClient()
            self.record_action(account,self.states[key].role_label,'英雄杀七天签到',client,
                lambda:client.signin(account,role_key),'state')
        self.run(job)

    def consume(self):
        """Apply worker events on Tk's thread and discard QR events after that dialog is cancelled."""
        try:
            while True:
                kind,value=self.events.get_nowait()
                if kind=='status':self.status.set(value)
                elif kind=='session_expired':
                    self.login_expired(value)
                elif kind=='state':
                    key,state=value;self.states[key]=state
                    if key==self.active:self.detail.set(state.role_label+'\n'+state.describe())
                elif kind=='bounty':
                    key,state=value;self.bounty_states[key]=state
                    if key==self.active:self.render_bounty()
                elif kind=='weekly':
                    key,state=value;self.weekly_states[key]=state
                    if key==self.active:self.render_weekly()
                elif kind=='gscore':
                    key,state=value;self.gscore_states[key]=state
                    if key in self.exchange_states:self.exchange_states[key]=replace(self.exchange_states[key],balance=state.balance)
                    if key==self.active:self.render_gscore()
                elif kind=='exchange':
                    key,state=value;self.exchange_states[key]=state
                    if key in self.gscore_states:self.gscore_states[key]=replace(self.gscore_states[key],balance=state.balance)
                    if key==self.active:self.render_exchange();self.render_gscore()
                elif kind=='batch_plan':self.confirm_batch(*value)
                elif kind=='saved':self.reload(value['profile_id'])
                elif kind=='roles_after_login' and not self.stop.is_set():self.pending_roles=value
                elif kind=='qr_image' and self.qr and not self.stop.is_set():
                    picture=Image.open(BytesIO(value));picture=picture.resize((410,410),Image.Resampling.NEAREST)
                    self.photo=ImageTk.PhotoImage(picture);self.qr_label.configure(image=self.photo)
                elif kind=='qr_status' and self.qr and not self.stop.is_set():self.qr_status.set(value)
                elif kind=='qr_done':
                    pending=self.pending_roles;self.cancel_login();self.pending_roles=pending
                elif kind=='finished':
                    self.busy=False
                    self.batch_stop_button.configure(state='disabled')
                    for button in self.actions:button.configure(state='normal')
                    if self.active:self.accounts.selection_set(self.active)
                    self.render_bounty()
                    self.render_weekly()
                    self.render_gscore()
                    self.render_exchange()
                    if self.pending_roles:
                        key,choice=self.pending_roles;self.pending_roles=None
                        self.root.after_idle(lambda key=key,choice=choice:self.open_roles(key,choice))
        except queue.Empty:pass
        self.root.after(100,self.consume)

    def close(self):
        """Cancel pending QR waiting and close without changing any saved account's login state."""
        self.stop.set();self.batch_stop.set();self.root.destroy()


if __name__=='__main__':App().root.mainloop()
