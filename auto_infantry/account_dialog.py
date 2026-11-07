"""Public account metadata controls; credentials are never returned to Tk variables or widgets."""
import tkinter as tk
from tkinter import ttk, messagebox
from account_store import AccountError

from collection_display import display_time

PLATFORMS = {'安卓 QQ': (0, 1), '安卓微信': (0, 0), 'iOS QQ': (1, 1), 'iOS 微信': (1, 0)}


class AccountDialog(tk.Toplevel):
    """Save the authenticated role or select a stored SDK profile for a default-off restart switch."""

    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.title('账号保存与切换')
        self.geometry('760x410')
        self.minsize(680, 370)
        self.records = {}
        panel = ttk.Frame(self, padding=12)
        panel.pack(fill='both', expand=True)
        ttk.Label(panel, text='切换会关闭全部自动功能并重启游戏；登录协议需本人勾选，成功后重新读取账号数据。',
                  wraplength=710).pack(anchor='w', pady=(0, 8))
        self.tree = ttk.Treeview(panel, columns=('name', 'level', 'mobile', 'platform', 'status', 'updated'),
                                 show='headings', selectmode='browse', height=8)
        for key, title, width in (('name', '角色', 120), ('level', '等级', 55), ('mobile', '系统', 65),
                                   ('platform', '登录方式', 75), ('status', '票据状态', 190), ('updated', '保存时间（北京）', 140)):
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, minwidth=45, anchor='center', stretch=key in ('name', 'status'))
        self.tree.pack(fill='both', expand=True)
        self.tree.bind('<<TreeviewSelect>>', self.select)
        bar = ttk.Frame(panel)
        bar.pack(fill='x', pady=(9, 6))
        self.save_button = ttk.Button(bar, text='保存当前账号', command=lambda: app.request_session('account_save'))
        self.save_button.pack(side='left')
        self.switch_button = ttk.Button(bar, text='切换选中账号', command=self.switch)
        self.switch_button.pack(side='left', padx=8)
        self.delete_button = ttk.Button(bar, text='删除选中账号', command=self.delete)
        self.delete_button.pack(side='left')
        ttk.Button(bar, text='取消等待 / 重新读取', command=lambda: app.request_session('connect')).pack(side='right')
        scan = ttk.Frame(panel)
        scan.pack(fill='x')
        self.platform = tk.StringVar(value='安卓 QQ')
        self.platform_box = ttk.Combobox(scan, textvariable=self.platform, values=tuple(PLATFORMS), state='readonly', width=13)
        self.platform_box.pack(side='left')
        self.scan_button = ttk.Button(scan, text='扫码登录 / 更新票据', command=self.scan)
        self.scan_button.pack(side='left', padx=8)
        ttk.Label(panel, textvariable=app.status, wraplength=710).pack(anchor='w', pady=(8, 3))
        ttk.Label(panel, text='票据仅以当前Windows用户加密保存；失效时重新扫码。不会保存密码或将票据写入Git/操作日志。',
                  foreground='#666666', wraplength=710).pack(anchor='w')
        self.refresh(app.sessions.store.list())

    def refresh(self, records):
        """Replace only public rows and preserve the selected stable profile across metadata updates."""
        selected = self.tree.selection()
        self.records = {record['profile_id']: record for record in records}
        self.tree.delete(*self.tree.get_children())
        for record in records:
            self.tree.insert('', 'end', iid=record['profile_id'], values=(record['name'], record['level'], record['mobile'],
                record['platform'], record['status'], display_time(int(record['updated'] * 1000)) if record['updated'] else '未知'))
        if selected and selected[0] in self.records:
            self.tree.selection_set(selected[0])
        self.update_controls()

    def update_controls(self):
        """Never allow simultaneous switch/scan/save requests; cancellation remains available during local waits."""
        enabled = not self.app.login_busy and not self.app.closing
        for control in (self.save_button, self.scan_button):
            control.state(['!disabled'] if enabled else ['disabled'])
        self.platform_box.state(['!disabled', 'readonly'] if enabled else ['disabled'])
        selected = self.tree.selection()
        valid = bool(selected and not self.records.get(selected[0], {}).get('unreadable') and
                     self.records.get(selected[0], {}).get('status') != '需要重新扫码')
        self.switch_button.state(['!disabled'] if enabled and valid else ['disabled'])
        self.delete_button.state(['!disabled'] if enabled and bool(selected) else ['disabled'])

    def select(self, event=None):
        """Choose the matching native QR platform for a profile that needs a renewed authorization."""
        selection = self.tree.selection()
        if selection:
            record = self.records.get(selection[0], {})
            for label, context in PLATFORMS.items():
                if context == (record.get('mobile_platform'), record.get('open_platform')):
                    self.platform.set(label)
        self.update_controls()

    def switch(self):
        """Pass only the stable digest key to the session owner; no credential data reaches the callback."""
        selected = self.tree.selection()
        if selected:
            self.app.request_session('account_switch', selected[0])

    def scan(self):
        """Request one native QR authorization for the selected bounded platform enums."""
        self.app.request_session('account_qr', PLATFORMS[self.platform.get()])

    def delete(self):
        """Confirm the displayed local identity, then forget only its saved profile without logging out of the game."""
        if self.app.login_busy or self.app.closing:
            return
        selected = self.tree.selection()
        if not selected or selected[0] not in self.records:
            return
        key = selected[0]
        row = self.records[key]
        label = f"{row['name']} · {row['mobile']} {row['platform']}"
        if not messagebox.askyesno('删除本地账号', f'删除本机保存的“{label}”及加密票据？\n'
                                  '不会删除服务器角色或退出游戏。之后可重新扫码添加。',
                                  parent=self, default=messagebox.NO):
            return
        if self.app.login_busy or self.app.closing:
            return
        try:
            self.app.sessions.store.delete(key)
            self.app.status.set('已删除本地账号：' + label + '；可选择对应平台重新扫码添加')
        except (AccountError, RuntimeError) as error:
            messagebox.showerror('删除未完成', str(error), parent=self)
        self.refresh(self.app.sessions.store.list())
