"""Single-click guild invitation controls."""
import tkinter as tk
from tkinter import ttk


class GuildInvitePanel(ttk.Frame):
    """Accept one ID and show progress and the game's invitation receipt."""

    def __init__(self, parent, session, web_relay=None):
        super().__init__(parent, padding=10)
        self.session = session
        self.phase = 'idle'
        self.ready = False
        self.target = tk.StringVar()
        self.status = tk.StringVar()
        self.web_relay = web_relay
        self.web_target = None
        ttk.Label(self, text='请保持游戏在线，并使用有公会邀请权限的角色。').pack(anchor='w')
        row = ttk.Frame(self)
        row.pack(anchor='w', fill='x', pady=10)
        ttk.Label(row, text='玩家 ID').pack(side='left')
        self.entry = ttk.Entry(row, width=24, textvariable=self.target)
        self.entry.pack(side='left', padx=8)
        self.invite_button = ttk.Button(row, text='邀请', command=self.submit)
        self.invite_button.pack(side='left', padx=(0, 8))
        self.cancel_button = ttk.Button(row, text='取消', command=self.cancel)
        self.cancel_button.pack(side='left')
        ttk.Label(self, textvariable=self.status, wraplength=860).pack(anchor='w')
        ttk.Label(self, text='按游戏规则，邀请联盟盟主时会邀请整个联盟。').pack(anchor='w', pady=(8, 0))
        if web_relay is not None:
            ttk.Separator(self).pack(fill='x', pady=14)
            self.web_status = tk.StringVar(value='网页接单已关闭。')
            self.web_button = ttk.Button(self, text='开启网页接单', command=self.toggle_web)
            self.web_button.pack(anchor='w')
            ttk.Label(self, textvariable=self.web_status, wraplength=860).pack(anchor='w', pady=(6, 0))
        self.clear()

    def update_controls(self, ready):
        """Keep duplicate clicks and input changes disabled while an invitation is in progress."""
        self.ready = ready
        for widget, enabled in ((self.entry, self.phase == 'idle'),
                                (self.invite_button, self.phase == 'idle'),
                                (self.cancel_button, self.phase == 'preparing')):
            widget.state(['!disabled' if ready and enabled else 'disabled'])
        if self.web_relay is not None:
            self.web_button.state(['!disabled' if ready else 'disabled'])

    def toggle_web(self):
        """Enable or revoke public submissions for the currently visible game session."""
        if not self.ready:
            return
        if self.web_relay.active():
            self.web_relay.stop()
            self.apply_web_status('正在停止网页接单…')
            return
        try:
            self.web_relay.start()
            self.apply_web_status('正在检查游戏连接和公会邀请权限…')
        except RuntimeError as error:
            self.apply_web_status(str(error))

    def apply_web_status(self, message):
        """Show connector availability independently of the game's individual invite receipt."""
        self.web_status.set(message)
        self.web_button.configure(text='停止网页接单' if self.web_relay.active() else '开启网页接单')

    def mark_web_received(self, target):
        """Notify the owner when a webpage visitor's invitation is accepted."""
        self.web_target = target
        if self.phase == 'idle':
            self.phase = 'preparing'
        self.status.set(f'收到网页邀请请求（{target}），正在等待游戏回执…')
        self.update_controls(self.ready)

    def submit(self):
        """Let this explicit click authorize one lookup and one invitation."""
        if not self.ready or self.phase != 'idle':
            return
        try:
            self.session.submit(self.target.get())
        except (ValueError, RuntimeError) as error:
            self.status.set(str(error))
            return
        self.phase = 'preparing'
        self.status.set('正在等待游戏查询回执…')
        self.update_controls(self.ready)

    def mark_sending(self):
        """Display the transition from the cancellable lookup to the invite receipt wait."""
        if self.phase == 'preparing':
            self.phase = 'sending'
            self.status.set('正在发送邀请，等待游戏回执…')
            self.update_controls(self.ready)

    def cancel(self):
        """Cancel the lookup if submission has not started."""
        if self.phase != 'preparing' or not self.session.cancel_current():
            return
        self.phase = 'cancelling'
        self.status.set('正在取消…')
        self.update_controls(self.ready)

    def apply_result(self, status):
        """Translate known failures for display and keep the ID available for review."""
        self.phase = 'idle'
        if status == '游戏回执：邀请失败（6852）':
            status = '游戏回执：该玩家已加入公会'
        if self.web_target is not None:
            status = f'网页邀请（{self.web_target}）{status}'
            self.web_target = None
        elif status == '游戏回执：邀请成功':
            self.target.set('')
        self.status.set(status)
        self.update_controls(self.ready)

    def clear(self):
        """Remove the previous account's pending UI state."""
        self.phase = 'idle'
        self.web_target = None
        self.target.set('')
        self.status.set('输入 12 位玩家 ID 后，点击「邀请」。')
        self.update_controls(False)
