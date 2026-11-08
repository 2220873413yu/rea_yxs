"""Manual battle-chat composer; only the send button can initiate a message."""
import tkinter as tk
from tkinter import ttk
from battle_chat import validate_message


class BattleChatPanel(ttk.Frame):
    """Show explicit one-shot sending and preserve uncertain text for the user to decide what to do next."""

    def __init__(self,parent,on_send):
        """Build an idle input and button; never bind Enter, timers, focus events or tab selection to sending."""
        super().__init__(parent,padding=10)
        self.busy=False;self.ready=False;self.on_send=on_send
        ttk.Label(self,text='仅发送到当前正在参与的战斗房间；选将、观战、结算或大厅不发送。',wraplength=920).pack(anchor='w')
        self.message=tk.StringVar()
        line=ttk.Frame(self);line.pack(fill='x',pady=10)
        self.entry=ttk.Entry(line,textvariable=self.message,width=58);self.entry.pack(side='left',fill='x',expand=True,padx=(0,8))
        self.send_button=ttk.Button(line,text='发送一次',command=self.submit);self.send_button.pack(side='left')
        self.status=tk.StringVar(value='输入内容后点击发送；不会自动发送或自动重试。')
        ttk.Label(self,textvariable=self.status,wraplength=920).pack(anchor='w',pady=5)
        ttk.Label(self,text='最多40字节（约20个汉字）。不修改游戏输入限制，助手不保存正文。\n超时或结果不明时不会补发；再次点击前，请先在游戏中核对消息。',foreground='#666666',wraplength=920).pack(anchor='w',pady=5)
        self.update_controls(False)

    def update_controls(self,ready):
        """Gate only on account-operation availability and this click, independently of world-map automation."""
        self.ready=ready;enabled=ready and not self.busy
        self.entry.state(['!disabled']if enabled else['disabled'])
        self.send_button.state(['!disabled']if enabled else['disabled'])

    def submit(self):
        """Validate locally before delegating one explicit click; keep empty/invalid text away from the transport."""
        if not self.ready or self.busy:return
        try:
            text=validate_message(self.message.get());self.on_send(text)
        except Exception as error:self.status.set(str(error).splitlines()[0]);return
        self.busy=True;self.update_controls(self.ready)
        self.status.set('正在核对战斗房间并发送一次，等待服务器确认…')

    def apply_result(self,result):
        """Clear text only after confirmed success; an uncertain result never triggers another send."""
        self.busy=False
        if result['success']:self.message.set('')
        self.status.set(result['status']);self.update_controls(self.ready)

    def clear(self):
        """Remove the preceding account's text and confirmation status without sending anything."""
        self.busy=False;self.message.set('');self.status.set('输入内容后点击发送；不会自动发送或自动重试。')
        self.update_controls(False)
