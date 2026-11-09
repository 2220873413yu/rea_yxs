"""Manual platform and role selection UI, with explicit private consent and a separate binding confirmation."""
import queue
import threading
import tkinter as tk
from tkinter import ttk,messagebox
from .roles import RoleClient,LoginChoice,PLATFORMS,PROVIDERS,RoleConsentRequired
from .transport import ServiceError
from .secure_store import StoreError
from .protocol import ProtocolError
from .binding_session import LoginExpiredError
from .labels import account_name


def choose_login(parent,callback):
    """Require both game platform and provider before the callback may request any QR code."""
    dialog=tk.Toplevel(parent);dialog.title('添加账号 · 选择登录平台');dialog.geometry('420x260')
    dialog.transient(parent);dialog.grab_set()
    device=tk.StringVar(value='');provider=tk.StringVar(value='')
    ttk.Label(dialog,text='先选择英雄杀角色的平台和登录方式',font=('Microsoft YaHei UI',12,'bold')).pack(pady=18)
    platforms=ttk.Combobox(dialog,values=list(PLATFORMS.values()),textvariable=device,state='readonly');platforms.pack(pady=6)
    providers=ttk.Combobox(dialog,values=list(PROVIDERS.values()),textvariable=provider,state='readonly');providers.pack(pady=6)
    hint=tk.StringVar(value='两项均需选择；不会根据账号昵称推测。')
    ttk.Label(dialog,textvariable=hint).pack(pady=10)
    def confirm():
        """Freeze explicit choices for this QR session; no default platform or provider is supplied."""
        if not device.get() or not provider.get():hint.set('请先完成两项选择。');return
        choice=LoginChoice(next(k for k,v in PLATFORMS.items() if v==device.get()),
                           next(k for k,v in PROVIDERS.items() if v==provider.get()))
        dialog.destroy();callback(choice)
    ttk.Button(dialog,text='继续扫码',command=confirm).pack(pady=8)


class RoleDialog:
    """Own an immutable account snapshot; network workers never read current selection or touch Tk."""
    def __init__(self,parent,store,key,on_bound,choice=None,on_expired=None):
        """Open a modal picker; after a QR choice, query only that explicitly chosen platform."""
        self.store=store;self.account=store.load(key);self.on_bound=on_bound;self.on_expired=on_expired
        self.client=RoleClient();self.events=queue.Queue();self.busy=False;self.closed=False;self.roles=();self.partitions=()
        self.window=tk.Toplevel(parent);self.window.title('英雄杀 · 区服与角色绑定');self.window.geometry('760x590')
        self.window.transient(parent);self.window.grab_set();self.window.protocol('WM_DELETE_WINDOW',self.close)
        frame=ttk.Frame(self.window,padding=15);frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='账号：'+account_name(self.account)+' / '+PROVIDERS[self.account['provider']],font=('Microsoft YaHei UI',12,'bold')).pack(anchor='w')
        self.current_detail=tk.StringVar(value='服务器当前绑定：尚未检查。受限处理只针对当前绑定，不使用下方选中的其他平台或角色。')
        ttk.Label(frame,textvariable=self.current_detail,wraplength=710,justify='left').pack(fill='x',pady=(10,4))
        self.repair_button=ttk.Button(frame,text='检查当前绑定状态',command=self.check_repair);self.repair_button.pack(anchor='w')
        bar=ttk.Frame(frame);bar.pack(fill='x',pady=12)
        ttk.Label(bar,text='英雄杀平台：').pack(side='left')
        self.platform=tk.StringVar(value=PLATFORMS[choice.device] if choice else '')
        self.platform_box=ttk.Combobox(bar,textvariable=self.platform,values=list(PLATFORMS.values()),state='readonly',width=12);self.platform_box.pack(side='left')
        self.platform_box.bind('<<ComboboxSelected>>',self.platform_changed)
        self.query_button=ttk.Button(bar,text='获取区服',command=self.query_partitions);self.query_button.pack(side='left',padx=8)
        ttk.Label(frame,text='游戏区服（不是QQ / 微信登录方式）：').pack(anchor='w')
        self.partition_value=tk.StringVar(value='')
        self.partition_box=ttk.Combobox(frame,textvariable=self.partition_value,state='readonly');self.partition_box.pack(fill='x')
        self.partition_box.bind('<<ComboboxSelected>>',self.query_roles)
        self.table=ttk.Treeview(frame,columns=('name','partition','platform'),show='headings',selectmode='browse',height=7)
        for key_,title,width in [('name','角色昵称',220),('partition','角色所属区服',220),('platform','所选平台',160)]:
            self.table.heading(key_,text=title);self.table.column(key_,width=width)
        self.table.pack(fill='both',expand=True,pady=12)
        self.status=tk.StringVar(value='请选择平台，再获取服务器区服。角色不会默认选中。')
        ttk.Label(frame,textvariable=self.status,wraplength=710,justify='left').pack(fill='x')
        self.bind_button=ttk.Button(frame,text='确认所选角色并绑定',command=self.bind);self.bind_button.pack(pady=12)
        ttk.Label(frame,text='普通绑定不自动解绑；受限处理需单独确认。均不签到、不领奖，失败不自动重试。',foreground='#666666').pack(anchor='w')
        self.window.after(100,self.consume)
        if choice:self.window.after_idle(self.query_partitions)

    def choice(self):
        """Read a deliberate platform selection, keeping OAuth provider fixed to the saved account."""
        return LoginChoice(next((k for k,v in PLATFORMS.items() if v==self.platform.get()),''),self.account['provider'])

    def platform_changed(self,event=None):
        """Invalidate all rows on platform changes so an old platform's selection cannot be bound."""
        self.partitions=();self.roles=();self.partition_value.set('');self.partition_box.configure(values=())
        self.table.delete(*self.table.get_children());self.status.set('平台已更改，请重新获取区服。')

    def run(self,job,success):
        """Serialize short UI-triggered operations; no business polling, background retries, or claims."""
        if self.busy or self.closed:return
        self.busy=True;self.controls(False)
        def worker():
            """Return only domain-safe errors, preserving a pending privacy gate for an explicit UI decision."""
            try:self.events.put(('ok',success,job()))
            except LoginExpiredError as error:self.events.put(('expired',None,str(error)))
            except RoleConsentRequired as error:self.events.put(('consent',(job,success),str(error)))
            except (ServiceError,StoreError,ProtocolError) as error:self.events.put(('error',None,str(error)))
            except Exception:self.events.put(('error',None,'操作未完成；未输出凭据，不自动重试。'))
        threading.Thread(target=worker,daemon=True).start()

    def controls(self,enabled):
        """Prevent platform changes and repeated binding clicks while a request is in flight."""
        for button in (self.query_button,self.bind_button,self.repair_button):button.configure(state='normal' if enabled else 'disabled')
        for combo in (self.platform_box,self.partition_box):combo.configure(state='readonly' if enabled else 'disabled')

    def query_partitions(self):
        """Fetch server partitions for the explicit platform, with no automatic server or role selection."""
        try:choice=self.choice()
        except ServiceError as error:self.status.set(str(error));return
        self.platform_changed();self.status.set('正在查询所选平台的区服…')
        self.run(lambda:self.client.partitions(self.account,choice),self.render_partitions)

    def render_partitions(self,partitions):
        """Use returned IDs; load a sole partition automatically while leaving every role unselected."""
        self.partitions=partitions
        self.partition_box.configure(values=[p.name+'（'+str(p.id)+'）' for p in partitions])
        self.status.set('请选择区服以查询角色；列表标签以服务器返回为准，角色所属区服将在下表单独显示。' if partitions else '服务器未返回区服。')
        if len(partitions)==1:
            self.partition_box.current(0);self.query_roles()

    def query_roles(self,event=None):
        """Query roles only when the person explicitly selects a server-returned partition."""
        index=self.partition_box.current()
        if index<0 or index>=len(self.partitions):return
        choice=self.choice();partition=self.partitions[index]
        self.roles=();self.table.delete(*self.table.get_children());self.status.set('正在读取所选区服的角色…')
        self.run(lambda:self.client.roles(self.account,choice,partition),self.render_roles)

    def render_roles(self,roles):
        """Display the role endpoint's actual area label, correcting misleading picker labels without guessing IDs."""
        self.roles=roles
        for i,role in enumerate(roles):self.table.insert('','end',iid=str(i),values=(role.name,role.partition_name,role.choice.label))
        index=self.partition_box.current();areas={role.partition_name for role in roles}
        if len(areas)==1 and 0<=index<len(self.partitions):
            area=next(iter(areas));part=self.partitions[index]
            labels=list(self.partition_box.cget('values'));labels[index]=area+'（'+str(part.id)+'）'
            self.partition_box.configure(values=labels);self.partition_box.current(index)
        self.status.set(f'找到 {len(roles)} 个角色。区服按角色实际返回显示；请选择角色后再确认绑定，不会自动绑定。')

    def bind(self):
        """Ask for a separate role-specific confirmation immediately before any server binding write."""
        if self.busy:return
        selected=self.table.selection()
        if not selected:self.status.set('请先点击一个角色，不会自动选第一个。');return
        role=self.roles[int(selected[0])]
        if role.choice!=self.choice():self.status.set('平台已变化，请重新查询。');return
        if not messagebox.askokcancel('确认绑定英雄杀角色',
                '账号：'+account_name(self.account)+'\n角色：'+role.label+
                '\n\n仅绑定此角色，不签到、不领奖；不自动解绑已有角色。',parent=self.window):return
        self.status.set('正在重新核对角色并绑定一次；结果不明不重复提交…')
        self.run(lambda:self.client.bind(self.account,role),lambda message:self.bound(role,message))

    def check_repair(self):
        """Read the real current binding first; the button itself never immediately unbinds a role."""
        if self.busy:return
        self.status.set('只读检查服务器当前绑定及受限状态…')
        self.run(lambda:self.client.prepare_repair(self.account),self.confirm_repair)

    def confirm_repair(self,snapshot):
        """Show the actual bound platform/role and require separate consent for both one-shot writes."""
        role=snapshot.role
        self.current_detail.set('服务器当前绑定：'+role.label+'；'+('绑定受限' if snapshot.restricted else '未受限'))
        if not snapshot.restricted:
            try:self.store.remember_role(self.account['profile_id'],role.name)
            except (StoreError,OSError):pass
            self.status.set('同一角色已绑定且未受限，可直接使用；本次仅查询，未解绑或重绑。');return
        confirmed=messagebox.askokcancel('处理当前礼包绑定受限',
            '账号：'+account_name(self.account)+'\n服务器当前绑定：'+role.label+
            '\n\n将先解除英雄杀礼包绑定，再绑定回上述同一个角色。'
            '\n不会改成下方选中的其他平台或角色，不签到、不领奖。'
            '\n若中途失败，可能暂时没有礼包绑定；停止且不自动重试。'
            '\n\n确认处理？',parent=self.window)
        if not confirmed:self.status.set('已取消处理，本次仅查询，未解绑。');return
        self.status.set('已确认处理当前绑定：'+role.label+'；每步只提交一次…')
        self.run(lambda:self.client.repair(self.account,snapshot),lambda message:self.bound(role,message))

    def bound(self,role,message):
        """Persist explicit verified selection, clear old claim consent, and invalidate parent role caches."""
        self.store.set_game_device(self.account['profile_id'],role.choice.device,clear_confirmation=True)
        self.store.remember_role(self.account['profile_id'],role.name)
        self.current_detail.set('服务器当前绑定：'+role.label+'；已核对，未受限')
        self.status.set(message);self.on_bound(self.account['profile_id'])

    def consume(self):
        """Deliver worker results on Tk's thread; request private-data consent only on the native gate."""
        if self.closed:return
        try:
            while True:
                kind,callback,value=self.events.get_nowait();self.busy=False;self.controls(True)
                if kind=='ok':
                    try:callback(value)
                    except (ServiceError,StoreError,ProtocolError) as error:
                        self.status.set('服务器操作已完成，但本地更新未完成：'+str(error)+'；请只读核对，不要重复提交。')
                elif kind=='expired':
                    self.status.set(value)
                    self.current_detail.set('当前登录票据未通过校验，请关闭本窗口并“添加 / 更新账号”重新扫码；未修改绑定。')
                    if self.on_expired:self.on_expired(self.account['profile_id'])
                elif kind=='consent':
                    job,success=callback
                    if messagebox.askokcancel('授权获取英雄杀角色资料',value+'\n\n资料设置为“仅自己可见”。这不是绑定或领奖。是否同意？',parent=self.window):
                        choice=self.choice()
                        def authorize_then_read():
                            """Consent once after the person's click, then repeat only the previously gated read."""
                            self.client.consent_private(self.account,choice);return job()
                        self.run(authorize_then_read,success)
                    else:self.status.set('未授权读取角色；登录票据已保留，未绑定。')
                else:self.status.set(value)
        except queue.Empty:pass
        if not self.closed:self.window.after(100,self.consume)

    def close(self):
        """Close safely; an already submitted binding is never cancelled or resubmitted implicitly."""
        if self.busy:
            messagebox.showinfo('操作进行中','请等待当前请求返回；不会自动重试。',parent=self.window);return
        self.closed=True;self.window.destroy()
