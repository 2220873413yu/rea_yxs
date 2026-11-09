"""Local receipt history with durable pre-dispatch rows and no authentication material."""
from datetime import datetime,timezone,timedelta
from contextlib import contextmanager
import os,sqlite3
from pathlib import Path
from .transport import ServiceError
from .labels import account_name

STATUSES={'running':'处理中','success':'成功','skipped':'跳过','failed':'失败','uncertain':'待确认'}


class HistoryStore:
    """Persist allowlisted public receipt fields in SQLite, independently from encrypted credentials."""
    def __init__(self,path=None):
        """Create the local journal without contacting the service or modifying attempt guards."""
        self.path=Path(path) if path else Path(os.environ['LOCALAPPDATA'])/'REA_YXS/xinyue_helper/history.sqlite3'
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS receipts (
                id INTEGER PRIMARY KEY, created TEXT NOT NULL, updated TEXT NOT NULL,
                account_key TEXT NOT NULL, account TEXT NOT NULL, role TEXT NOT NULL,
                action TEXT NOT NULL, status TEXT NOT NULL, rewards TEXT NOT NULL, detail TEXT NOT NULL)''')
            db.execute("UPDATE receipts SET status='uncertain',detail='上次进程中断，需核对；不会据此重发。 ' || detail WHERE status='running'")

    @contextmanager
    def connect(self):
        """Open a short-lived, fully synchronized local transaction safe across the UI and worker threads."""
        db=sqlite3.connect(self.path,timeout=5);db.row_factory=sqlite3.Row
        db.execute('PRAGMA synchronous=FULL')
        try:
            with db:yield db
        finally:db.close()

    @staticmethod
    def now():
        """Use explicit Beijing timestamps for both submission time and final confirmation time."""
        return datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S')

    def begin(self,account_key,account,role,action):
        """Commit a pending row before allowing a mutating request; a storage failure blocks dispatch."""
        now=self.now()
        with self.connect() as db:
            cur=db.execute('INSERT INTO receipts(created,updated,account_key,account,role,action,status,rewards,detail) VALUES(?,?,?,?,?,?,?,?,?)',
                (now,now,account_key,account,role,action,'running','','请求前记录；中断后需核对'))
            return cur.lastrowid

    def finish(self,key,status,rewards='',detail=''):
        """Update the original row rather than creating a second receipt for the same attempt."""
        if status not in STATUSES:raise ValueError('Unknown history state')
        with self.connect() as db:
            db.execute('UPDATE receipts SET updated=?,status=?,rewards=?,detail=? WHERE id=?',
                (self.now(),status,rewards,detail,key))

    def list(self,status='',limit=1000):
        """Read newest local entries and current in-flight status without issuing any service queries."""
        with self.connect() as db:
            rows=[dict(r) for r in db.execute('SELECT * FROM receipts ORDER BY id DESC LIMIT ?', (limit,))]
        return [r for r in rows if not status or r['status']==status]


class ClaimRecorder:
    """Record existing client actions without replacing their preflight and persistent duplicate guards."""
    def __init__(self,history):
        """Inject local storage so tests never touch the real receipt database."""
        self.history=history

    def execute(self,account,role,action,client,operation):
        """Persist before dispatch, classify structured client results, and never retry ambiguous outcomes."""
        row=self.history.begin(account['profile_id'],account_name(account),role,action)
        try:
            message=operation()
            status=getattr(client,'result_status','uncertain')
            rewards=tuple((name,count) for name,count in getattr(client,'actual_rewards',()) if name and isinstance(count,int) and count>0)
            reward_text='、'.join(f'{name} ×{count}' for name,count in rewards) if rewards else (
                (getattr(client,'reward_description','') or ('G分余额变化见详情' if action=='G分签到' else '实际奖品待核对')) if status=='success' else '')
        except Exception as error:
            status='uncertain' if getattr(client,'dispatched',False) else 'failed'
            # Only documented, credential-free errors may reach this public journal.
            message=str(error) if isinstance(error,ServiceError) else '操作未完成；未保存原始异常或登录凭据。'
            reward_text=''
        try:self.history.finish(row,status,reward_text,message)
        except Exception:
            # A pending row was already committed. Never resend to repair a local journal failure.
            raise ServiceError('本地记录更新失败；操作可能已提交，请只读核对，不要重发。') from None
        return status,message
