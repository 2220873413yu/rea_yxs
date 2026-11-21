"""Manual battle-only chat, with a one-click temporary bridge and bounded existing-log confirmation."""
import json
import subprocess
import threading
import time
import uuid
from pathlib import Path
import frida
from account_lock import ensure_account_available
from connection import ADB
from instance_config import DEVICE
from game_log import GameResponseLog,tags
from game_protocol import JceReader

ROOT=Path(__file__).resolve().parent


def validate_message(value):
    """Accept one nonempty native-compatible short message without silently replacing unsupported characters."""
    if not isinstance(value,str)or not value.strip():raise ValueError('请输入聊天内容')
    if any(ord(c)<32 or ord(c)==127 for c in value):raise ValueError('请发送单条文字，不包含换行或控制字符')
    try:raw=value.encode('gbk')
    except UnicodeEncodeError as error:raise ValueError('内容含原生文字接口不支持的字符，请改用普通文字')from error
    if len(raw)>40:raise ValueError('内容过长：最多40字节，约20个汉字或40个英文字母')
    return value


def lua_text(value):
    """Pass validated UTF-8 text as decimal-escaped data, never executable Lua source."""
    return '"'+''.join('\\%03d'%byte for byte in value.encode('utf-8'))+'"'


def wire_text(body):
    """Read only tag-1 chat text in its original encoding, leaving other players' content undisplayed."""
    reader=JceReader(body)
    while reader.position<len(body):
        start=reader.position;field=reader.field()
        if field['tag']!=1 or field['wire_type']not in(6,7):continue
        header=2 if body[start]>>4==15 else 1
        width=1 if field['wire_type']==6 else 4
        begin=start+header+width;raw=body[begin:reader.position]
        # Native ChatController sends GBK bytes; prefer that exact transport encoding.
        try:return raw.decode('gbk')
        except UnicodeDecodeError:return raw.decode('utf-8',errors='replace')
    return None


def wait_chat_receipt(log,message,own_uin,cancelled,check,timeout=8):
    """Confirm one matching outgoing packet and own server broadcast; never send, retry, or infer success on timeout."""
    outgoing=0;deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        if cancelled():raise InterruptedError('等待已取消；消息可能已发出，未重试')
        check()
        for record in log.drain():
            sending=record['tag'].startswith('s_10006_')
            echo=record['tag'].startswith('r_10007_')
            if not(sending or echo):continue
            data=tags(JceReader(record['body']).fields())
            if sending:
                if wire_text(record['body'])!=message or outgoing:
                    raise RuntimeError('出现其他聊天发送，结果无法归属；未重试')
                outgoing+=1
            elif echo and outgoing and data.get(0)==own_uin and data.get(2)==0 and wire_text(record['body'])==message:
                return '服务器已回推本账号的消息（一次发送），未验证其他玩家是否显示'
        time.sleep(.15)
    raise TimeoutError('已观察到发送请求，未收到匹配的服务器回推；结果未确认，未重试'if outgoing else
                       '未观察到发送请求，结果未确认，未重试')


def send_battle_chat_once(message,cancelled):
    """Attach a private default-off bridge for this click only; never acquire or rebind the world helper's session."""
    message=validate_message(message)
    if cancelled():raise InterruptedError('发送已取消，未调用接口')
    ensure_account_available()
    flags=subprocess.CREATE_NO_WINDOW
    subprocess.run([ADB,'-s',DEVICE,'forward','tcp:27042','tcp:27042'],capture_output=True,check=True,timeout=5,creationflags=flags)
    pid=int(subprocess.check_output([ADB,'-s',DEVICE,'shell','pidof','com.qqgame.mic'],text=True,timeout=5,creationflags=flags).split()[0])
    session=frida.get_device_manager().add_remote_device('127.0.0.1:27042').attach(pid,realm='emulated')
    script=None;attempted=False;name='_REA_CHAT_CLICK_'+uuid.uuid4().hex
    try:
        script=session.create_script((ROOT/'bridge.js').read_text(encoding='utf-8'));script.load()
        if cancelled():raise InterruptedError('发送已取消，未调用接口')
        meta=json.loads(script.exports_sync.query((ROOT/'battle_chat_runtime.lua').read_text(encoding='utf-8').replace('__CHAT_API__',name)))
        log=GameResponseLog(ADB);log.drain()
        if cancelled():raise InterruptedError('发送已取消，未调用接口')
        attempted=True
        script.exports_sync.query(f'return {name}.send({lua_text(message)})')
        return wait_chat_receipt(log,message,meta['own_uin'],cancelled,
            lambda:script.exports_sync.query(f'return {name}.check()'))
    except Exception as error:
        # A dispatched RPC can fail after sending. Never describe such a failure as safely unsent.
        prefix='已调用一次发送，结果未确认，未重试：'if attempted else'未调用发送接口：'
        raise RuntimeError(prefix+str(error).splitlines()[0][:220])from error
    finally:
        if script is not None:
            try:script.exports_sync.query(f'{name}=nil;return "chat_scope_removed"')
            except Exception:pass
            try:script.exports_sync.close()
            except Exception:pass
            try:script.unload()
            except Exception:pass
        try:session.detach()
        except Exception:pass


class BattleChatSession:
    """Own a manual click independently of world readiness, and discard events after account changes."""

    def __init__(self,events,sender=send_battle_chat_once):
        """Stay completely idle until submit; sender injection keeps tests free of real communications."""
        self.events=events;self.sender=sender;self.guard=threading.Lock();self.generation=0
        self.cancel=threading.Event();self.job=None;self.closed=False

    def submit(self,message):
        """Queue a single validated message and reject double-clicks while its confirmation is pending."""
        message=validate_message(message)
        with self.guard:
            if self.closed:raise RuntimeError('助手正在关闭，未发送')
            if self.job is not None and self.job.is_alive():raise RuntimeError('已有消息等待确认，请勿重复点击')
            self.cancel=threading.Event();generation=self.generation;cancel=self.cancel
            self.job=threading.Thread(target=self._run,args=(message,generation,cancel),daemon=True)
            self.job.start()

    def _run(self,message,generation,cancel):
        """Invoke the sender exactly once and publish status only, without logging or persisting the message body."""
        try:status=self.sender(message,cancel.is_set);success=True
        except Exception as error:status=str(error).splitlines()[0][:320];success=False
        self.events.put(dict(chat_generation=generation,battle_chat_result=dict(success=success,status=status)))

    def cancel_pending(self):
        """Cancel queued/waiting work during account changes; accepted messages cannot be recalled."""
        with self.guard:self.cancel.set();self.generation+=1

    def close(self):
        """Revoke pending work and allow the short-lived bridge to clean itself up before application exit."""
        with self.guard:self.closed=True;self.cancel.set();self.generation+=1

    def pending_shutdown(self):
        """Report local thread lifetime only; never poll the game or server."""
        return self.job is not None and self.job.is_alive()
