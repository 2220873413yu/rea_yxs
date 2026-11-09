"""Visible independent QQ authorization proof, preceding the complete multi-account interface."""
from datetime import datetime
from io import BytesIO
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk
from .auth import QQAuth, BGW
from .transport import ServiceError
from .secure_store import AccountStore, StoreError
from . import protocol


class VerifyWindow:
    """Show official QR refresh/cancel controls and only validate/save a phone-approved login."""
    def __init__(self):
        self.root=tk.Tk()
        self.root.title('心悦助手 · QQ独立扫码验证')
        self.root.geometry('540x640')
        self.root.resizable(False,False)
        self.root.protocol('WM_DELETE_WINDOW',self.close)
        self.events=queue.Queue();self.stop=threading.Event();self.generation=0
        self.status=tk.StringVar(value='正在申请QQ二维码…')
        panel=ttk.Frame(self.root,padding=20);panel.pack(fill='both',expand=True)
        ttk.Label(panel,text='QQ扫码登录心悦俱乐部',font=('Microsoft YaHei UI',17,'bold')).pack(pady=(0,8))
        ttk.Label(panel,text='请用本人手机QQ扫码，并在手机上确认授权。').pack()
        ttk.Label(panel,text='不依赖模拟器或心悦APP；本次不签到、不领奖。').pack(pady=(2,12))
        self.image_label=ttk.Label(panel,anchor='center');self.image_label.pack(fill='both',expand=True)
        ttk.Label(panel,textvariable=self.status,wraplength=480,anchor='center',justify='center').pack(pady=14)
        bar=ttk.Frame(panel);bar.pack()
        self.refresh_button=ttk.Button(bar,text='刷新QQ二维码',command=self.refresh);self.refresh_button.pack(side='left',padx=6)
        ttk.Button(bar,text='取消 / 关闭',command=self.close).pack(side='left',padx=6)
        self.root.after(100,self.refresh)
        self.root.after(100,self.consume)

    def refresh(self):
        """Cancel the old local session and ignore all late results before starting a fresh QR challenge."""
        self.stop.set();self.stop=threading.Event();self.generation+=1
        generation=self.generation;stop=self.stop
        self.status.set('正在申请QQ二维码…');self.image_label.configure(image='')
        self.refresh_button.configure(state='disabled')
        threading.Thread(target=self.authorize,args=(generation,stop),daemon=True).start()

    def authorize(self,generation,stop):
        """Run only official QR authorization, one read validation, and local DPAPI saving in a worker."""
        emit=lambda kind,value:self.events.put((generation,kind,value))
        try:
            provider=QQAuth();challenge=provider.begin()
            if stop.is_set():return
            emit('image',challenge.image);emit('status','等待QQ扫码；扫描后请在手机确认授权。')
            while not stop.is_set() and time.monotonic()<challenge.expires_at:
                state,credentials=provider.poll(challenge)
                if stop.is_set():return
                if state=='expired':emit('status','QQ二维码已过期，请点击“刷新QQ二维码”。');return
                if state=='scanned':emit('status','已扫描，请在手机QQ上确认授权。')
                if credentials is not None:
                    emit('status','已收到授权，正在独立查询验证…')
                    headers=credentials.headers()
                    response=provider.session.request(BGW+'xyapp.GiftSrv/GetGamesGifts',bytes.fromhex('0a067369676e696e10a309'),headers)
                    fields=protocol.parse(response.body);ret=protocol.get(fields,1,0)
                    if response.status!=200 or ret!=0 or protocol.get(fields,3) is None:
                        raise ServiceError('授权已返回，但心悦查询未验证通过：'+str(ret))
                    if stop.is_set():return
                    public=AccountStore().save(credentials,headers)
                    emit('saved',public)
                    return
                stop.wait(3)
            if not stop.is_set():emit('status','QQ二维码已过期，请刷新。')
        except (ServiceError,StoreError,protocol.ProtocolError) as error:
            if not stop.is_set():emit('status',str(error))
        except Exception:
            if not stop.is_set():emit('status','登录验证未完成，请刷新二维码；未记录明文凭据。')
        finally:emit('finished',None)

    def consume(self):
        """Apply only current-session public/image events on the Tk thread, never raw account credentials."""
        try:
            while True:
                generation,kind,value=self.events.get_nowait()
                if generation!=self.generation:continue
                if kind=='image':
                    image=Image.open(BytesIO(value));image=image.resize((420,420),Image.Resampling.NEAREST)
                    self.photo=ImageTk.PhotoImage(image);self.image_label.configure(image=self.photo)
                elif kind=='status':self.status.set(value)
                elif kind=='saved':
                    self.status.set('QQ登录及独立查询验证成功。账号已在本机加密保存；没有签到或领取礼包。')
                    self.image_label.configure(image='')
                elif kind=='finished':self.refresh_button.configure(state='normal')
        except queue.Empty:pass
        self.root.after(100,self.consume)

    def close(self):
        """Cancel future work and destroy this proof window without logging out any account."""
        self.stop.set();self.root.destroy()


if __name__=='__main__':
    VerifyWindow().root.mainloop()
