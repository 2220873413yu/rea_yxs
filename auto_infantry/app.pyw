"""Default-off controls for troops, shared recovery and resource-specific collection."""
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from bootstrap import ensure_server
from controller import Worker, owned_soldiers
from units import UNIT_NAMES
from hero_panel import HeroPanel
from collection_panel import CollectionPanel
from collection_teams_panel import CollectionTeamsPanel
from monster_panel import MonsterPanel
from league_panel import LeaguePanel
from beacon_panel import BeaconPanel
from collection_display import display_time
from login_session import LoginSession, account_label


class App:
    """Keep troop selections separate from the master spending switch."""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title('英雄杀 · 造兵、恢复、采集与打野')
        self.root.geometry('1050x1000')
        self.root.minsize(900, 940)
        self.events = queue.Queue()
        self.sessions = LoginSession(self.events)
        self.login_busy = False
        self.worker = None
        self.closing = False
        self.ready = False
        self.enabled = tk.BooleanVar(value=False)
        self.training_speed = tk.BooleanVar(value=False)
        self.hero_enabled = tk.BooleanVar(value=False)
        self.collect_enabled = tk.BooleanVar(value=False)
        self.hunt_enabled = tk.BooleanVar(value=False)
        self.league_enabled = tk.BooleanVar(value=False)
        self.beacon_enabled = tk.BooleanVar(value=False)
        self.selections = {unit: tk.BooleanVar(value=unit == 411) for unit in UNIT_NAMES}
        self.counts = {unit: tk.StringVar(value='正在读取…') for unit in UNIT_NAMES}
        self.stock = tk.StringVar(value='五分钟训练加速：正在读取…')
        self.status = tk.StringVar(value='请保持游戏在西游幻境中，正在连接…')
        style = ttk.Style()
        style.configure('Title.TLabel', font=('Microsoft YaHei UI', 15, 'bold'))
        style.configure('TLabel', font=('Microsoft YaHei UI', 10))
        style.configure('Switch.TCheckbutton', font=('Microsoft YaHei UI', 13))
        panel = ttk.Frame(self.root, padding=16)
        panel.pack(fill='both', expand=True)
        header = ttk.Frame(panel)
        header.pack(fill='x')
        ttk.Label(header, text='世界模式助手', style='Title.TLabel').pack(side='left')
        self.login_button = ttk.Button(header, text='iOS 微信扫码登录', command=lambda: self.request_session('ios_wechat'))
        self.login_button.pack(side='right')
        self.reload_button = ttk.Button(header, text='重新读取当前账号', command=lambda: self.request_session('connect'))
        self.reload_button.pack(side='right', padx=6)
        self.account_status = tk.StringVar(value='当前账号：正在读取；自动功能关闭')
        ttk.Label(header, textvariable=self.account_status, wraplength=360).pack(side='left', padx=(14, 0))
        top = ttk.Frame(panel)
        top.pack(fill='x', pady=(10, 0))
        troop_panel = ttk.LabelFrame(top, text='士兵训练', padding=10)
        troop_panel.pack(side='left', fill='both', expand=True, padx=(0, 10))
        self.collection_panel = CollectionPanel(top, self.collect_enabled, self.switch_collection, self.check_collection)
        self.collection_panel.pack(side='right', fill='both', expand=True)
        self.toggle = ttk.Checkbutton(troop_panel, text='自动造兵', variable=self.enabled,
                                     command=self.switch, style='Switch.TCheckbutton', state='disabled')
        self.toggle.pack(anchor='w', pady=(0, 8))
        choices = ttk.LabelFrame(troop_panel, text='造哪些兵', padding=10)
        choices.pack(fill='x')
        self.choice_widgets = {}
        for row, unit in enumerate((412, 413, 411, 803)):
            name = UNIT_NAMES[unit]
            box = ttk.Checkbutton(choices, text=name, variable=self.selections[unit])
            box.grid(row=row, column=0, sticky='w', padx=(0, 25), pady=2)
            self.choice_widgets[unit] = box
            ttk.Label(choices, textvariable=self.counts[unit]).grid(row=row, column=1, sticky='w', pady=2)
        ttk.Label(troop_panel, textvariable=self.stock).pack(anchor='w', pady=(8, 3))
        self.speed_toggle = ttk.Checkbutton(troop_panel, text='自动使用五分钟训练加速', variable=self.training_speed)
        self.speed_toggle.pack(anchor='w', pady=(3, 5))
        ttk.Label(troop_panel, text='不勾选则正常训练，到期后检查；修改选项前先关闭自动造兵。',
                  foreground='#666666', wraplength=390, font=('Microsoft YaHei UI', 9)).pack(anchor='w')
        self.collection_teams_panel = CollectionTeamsPanel(panel)
        self.collection_teams_panel.pack(fill='x', pady=(4, 0))
        self.feature_tabs = ttk.Notebook(panel)
        self.feature_tabs.pack(fill='both', expand=True, pady=(8, 0))
        self.hero_panel = HeroPanel(self.feature_tabs, self.hero_enabled, self.switch_hero, self.refresh_heroes, self.refresh_attributes)
        self.hero_panel.tree.configure(height=4)
        self.feature_tabs.add(self.hero_panel, text='英雄属性与恢复')
        self.monster_panel = MonsterPanel(self.feature_tabs, self.hunt_enabled, self.switch_hunt, self.check_hunt)
        self.feature_tabs.add(self.monster_panel, text='自动打野')
        self.league_panel = LeaguePanel(self.feature_tabs, self.league_enabled, self.switch_league, self.check_league)
        self.feature_tabs.add(self.league_panel, text='联盟采集')
        self.beacon_panel = BeaconPanel(self.feature_tabs, self.beacon_enabled, self.switch_beacon, self.check_beacon)
        self.feature_tabs.add(self.beacon_panel, text='烽火台')
        self.hero_status = self.hero_panel.status
        ttk.Separator(panel).pack(fill='x', pady=9)
        ttk.Label(panel, textvariable=self.status, wraplength=960).pack(anchor='w')
        ttk.Label(panel, text='造兵只处理所选兵种，补满后自动关闭；恢复只用五分钟专用道具，不足五分钟也可用一个。\n采集恢复与自动恢复共用同一队列，不重复用道具；关闭后不发新请求，已接受的行动不会撤销。',
                  foreground='#666666', font=('Microsoft YaHei UI', 9)).pack(anchor='w', pady=(10, 0))
        ttk.Label(panel, text='选择会记住，换号后自动功能关闭；本次手动开启打野后，才恢复刷新时刻自动开启规则。',
                  foreground='#666666', font=('Microsoft YaHei UI', 9)).pack(anchor='w', pady=(5, 0))
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        self.connect()
        self.root.after(100, self.poll)

    def connect(self):
        """Start a fresh default-off session without blocking Tk on game readiness."""
        self.request_session('connect')

    def clear_account_views(self):
        """Remove all old account snapshots and switches while retaining explicit saved selection settings."""
        self.ready = False
        for variable in (self.enabled, self.hero_enabled, self.collect_enabled, self.hunt_enabled,
                         self.league_enabled, self.beacon_enabled, self.training_speed):
            variable.set(False)
        for count in self.counts.values():
            count.set('正在读取…')
        self.stock.set('五分钟训练加速：正在读取…')
        hero = self.hero_panel
        hero.roster.clear(); hero.speeds.clear(); hero.loads.clear(); hero.references.clear()
        hero.tree.delete(*hero.tree.get_children())
        hero.stock.set('五分钟英雄恢复加速：正在读取…')
        hero.reference_text.set('采集速度：等待当前账号数据…')
        hero.status.set('自动恢复关闭，等待当前账号名单…')
        collection = self.collection_panel
        collection.queue_snapshot = None
        collection.queue_text.set('已出征 / 上限：待读取')
        collection.recommendation.set('等待当前账号的采集属性…')
        collection.balance_text.set('粮木铁按1:1:1补缺；等待当前账号存量。')
        collection.status.set('自动采集关闭；等待当前账号数据。')
        for view in (self.collection_teams_panel, self.league_panel, self.beacon_panel):
            view.snapshot = None
            view.tree.delete(*view.tree.get_children())
        self.collection_teams_panel.awaiting = False
        self.collection_teams_panel.note.set('等待当前账号数据；自动采集关闭。')
        self.league_panel.mine.set('等待当前账号联盟矿…')
        self.league_panel.confirmed.set('尚未确认当前账号服务器状态')
        self.league_panel.status.set('自动联盟采集关闭。')
        self.beacon_panel.scout_info = ''
        self.beacon_panel.summary.set('烽火台额度：待读取')
        self.beacon_panel.timing.set('刷新与下次检查：待读取')
        self.beacon_panel.status.set('自动烽火台关闭。')
        self.monster_panel.tree.delete(*self.monster_panel.tree.get_children())
        self.monster_panel.team.set('队伍：未派出')
        self.monster_panel.capacity.set('出征额度：待读取；本轮忽略：0个坐标')
        self.monster_panel.status.set('自动打野关闭。')
        self.monster_panel.auto_hint.set('本账号尚未手动开启打野，刷新时刻自动开启暂不启用。')

    def request_session(self, mode):
        """Stop old automation, clear its display, then request native login or current-account reconstruction."""
        if self.closing:
            return
        self.clear_account_views()
        self.login_busy = True
        self.account_status.set('当前账号：正在重新读取，自动功能关闭')
        self.status.set('正在停止旧连接并准备扫码登录…' if mode == 'ios_wechat' else '正在重新连接当前账号…')
        self.sessions.request(mode)
        self.worker = None
        self.update_controls()

    def update_controls(self):
        """Enable each independent master while connected and freeze the settings owned by an active run."""
        self.toggle.state(['!disabled'] if self.ready else ['disabled'])
        self.hero_panel.update_controls(self.ready, self.collect_enabled.get())
        self.collection_panel.update_controls(self.ready)
        self.monster_panel.update_controls(self.ready)
        self.league_panel.update_controls(self.ready)
        self.beacon_panel.update_controls(self.ready)
        self.collection_teams_panel.set_active(self.collect_enabled.get(), self.ready)
        for box in self.choice_widgets.values():
            box.state(['disabled'] if self.enabled.get() else ['!disabled'])
        self.speed_toggle.state(['disabled'] if self.enabled.get() else ['!disabled'])
        self.login_button.state(['disabled'] if self.login_busy else ['!disabled'])

    def switch_hero(self):
        """Freeze the user's persisted hero choices without changing the troop master."""
        if self.worker is None:
            self.hero_enabled.set(False)
            return
        try:
            self.worker.switch_hero(self.hero_enabled.get(), self.hero_panel.selected())
            self.hero_status.set('正在刷新所选英雄与部队状态…' if self.hero_enabled.get() else '已关闭，不再发送恢复请求')
        except Exception as error:
            self.hero_enabled.set(False)
            self.ready = False
            self.hero_status.set('自动恢复已停止：' + str(error).splitlines()[0])
        self.update_controls()

    def refresh_heroes(self):
        """Request a read-only roster update through the existing serial worker."""
        if self.worker is not None and not self.hero_enabled.get():
            self.hero_status.set('正在刷新英雄名单…')
            self.worker.request_hero_refresh()

    def refresh_attributes(self):
        """Queue read-only resource-specific metrics without enabling collection or changing selections."""
        if self.worker is not None and not self.collect_enabled.get():
            self.collection_panel.status.set('正在查询采集属性（不会派出）…')
            self.worker.request_collection_attributes()

    def switch_collection(self):
        """Freeze the visible resource scope and control departures plus their shared recovery demand."""
        if self.worker is None:
            self.collect_enabled.set(False)
            return
        try:
            options = self.collection_panel.options() if self.collect_enabled.get() else None
            self.worker.switch_collection(self.collect_enabled.get(), options)
            self.collection_panel.status.set('正在核对采集目标与英雄…' if self.collect_enabled.get() else '采集关闭，不再派出；已有行动不会取消')
        except Exception as error:
            self.collect_enabled.set(False)
            try:
                self.worker.switch_collection(False)
            except Exception:
                pass
            self.collection_panel.status.set('采集未开启：' + str(error).splitlines()[0])
        self.update_controls()

    def check_collection(self):
        """Queue one explicit recheck of an already enabled collection run without enabling consumption."""
        if self.worker is not None and self.collect_enabled.get():
            self.worker.collection.request_check()
            self.collection_panel.status.set('已请求立即检查，等待当前操作完成后确认服务器状态…')

    def switch_hunt(self):
        """Freeze the hunting scope and separately gate both departures and native battle skipping."""
        if self.worker is None:
            self.hunt_enabled.set(False)
            return
        try:
            options = self.monster_panel.options() if self.hunt_enabled.get() else None
            self.worker.switch_hunt(self.hunt_enabled.get(), options)
            self.monster_panel.status.set('正在确认主城附近野怪与可用阵容…' if self.hunt_enabled.get()
                                          else '打野已暂停；下个地图刷新时刻会自动开启，已有队伍不会撤回。')
        except Exception as error:
            self.hunt_enabled.set(False)
            try:
                self.worker.switch_hunt(False)
            except Exception:
                pass
            self.monster_panel.status.set('打野未开启：' + str(error).splitlines()[0])
        self.update_controls()

    def check_hunt(self):
        """Request one manual hunting recheck without enabling any switch."""
        if self.worker is not None and self.hunt_enabled.get():
            self.worker.hunt.request_check()
            self.monster_panel.status.set('已请求检查，等待当前操作完成…')

    def start_hunt_on_refresh(self, epoch):
        """Validate the current visible radius on the UI thread before accepting a scheduled gate opening."""
        if not self.ready or self.closing or self.worker is None or self.hunt_enabled.get():
            return
        try:
            if self.worker.hunt.start_on_refresh(epoch, self.monster_panel.options()):
                self.hunt_enabled.set(True)
        except Exception as error:
            self.hunt_enabled.set(False)
            try:
                self.worker.switch_hunt(False)
            except Exception:
                pass
            self.monster_panel.status.set('定时开启打野失败：' + str(error).splitlines()[0])
            self.worker.publish(action='hunt_auto_start_failed', error=str(error))
        self.update_controls()

    def switch_league(self):
        """Control only alliance departures, keeping the one-time startup reconciliation read-only."""
        if self.worker is None:
            self.league_enabled.set(False)
            return
        try:
            self.worker.league.switch(self.league_enabled.get())
            self.league_panel.status.set('正在确认联盟矿和本方队伍…' if self.league_enabled.get() else
                                         '联盟采集关闭，不再派出；已有行动不会撤回。')
        except Exception as error:
            self.league_enabled.set(False)
            self.league_panel.status.set('联盟采集未开启：' + str(error).splitlines()[0])
        self.update_controls()

    def check_league(self):
        """Request one server check without changing the alliance mining switch."""
        if self.worker is not None:
            self.worker.league.request_check()
            self.league_panel.status.set('已请求检查服务器状态，等待当前操作完成…')

    def switch(self):
        """Enable only checked troop types; a master-off event cancels all queued spending."""
        selected = tuple(unit for unit, value in self.selections.items() if value.get())
        if self.worker is None or (self.enabled.get() and not selected):
            self.enabled.set(False)
            self.status.set('请至少勾选一个兵种')
            self.update_controls()
            return
        try:
            self.worker.switch(self.enabled.get(), selected, use_training_speed=self.training_speed.get())
            self.status.set('正在核对所选兵种并开始补兵…' if self.enabled.get() else '已关闭，不再发送新请求')
        except Exception as error:
            self.enabled.set(False)
            self.ready = False
            self.status.set('已停止：' + str(error).splitlines()[0])
        self.update_controls()

    def switch_beacon(self):
        """Authorize selected beacon types only, preserving every other feature's spending gate."""
        if self.worker is None:
            self.beacon_enabled.set(False)
            return
        try:
            self.worker.beacon.switch(self.beacon_enabled.get(),self.beacon_panel.selected_types())
            self.beacon_panel.status.set('正在核对所选事件、英雄、斥候和烽火台额度…' if self.beacon_enabled.get() else
                                         '自动烽火台关闭，不再发送出征、侦察、撤回、跳过或领奖请求。')
        except Exception as error:
            self.beacon_enabled.set(False)
            self.beacon_panel.status.set('自动烽火台未开启：' + str(error).splitlines()[0])
        self.update_controls()

    def check_beacon(self):
        """Request one server reconciliation without opening the rescue spending gate."""
        if self.worker is not None:
            self.worker.beacon.request_check()
            self.beacon_panel.status.set('已请求核对服务器事件和队伍…')

    def poll(self):
        """Render confirmed switches and accept only the authorized, scoped scheduled-hunting start requests."""
        try:
            while True:
                event = self.events.get_nowait()
                if event.get('session_epoch', self.sessions.epoch) != self.sessions.epoch:
                    continue
                self.worker = self.sessions.worker
                if event.get('account_changed'):
                    self.request_session('connect')
                    continue
                if 'login_busy' in event:
                    self.login_busy = event['login_busy']
                if 'account' in event:
                    self.account_status.set(account_label(event['account']))
                if 'account_status' in event:
                    self.account_status.set(event['account_status'])
                if 'ready' in event:
                    self.ready = event['ready']
                if 'beacon_enabled' in event:
                    self.beacon_enabled.set(event['beacon_enabled'])
                if 'beacon_status' in event:
                    self.beacon_panel.status.set(event['beacon_status'].splitlines()[0][:240])
                if 'beacon_snapshot' in event:
                    self.beacon_panel.apply_snapshot(event['beacon_snapshot'])
                if 'beacon_scout' in event:
                    self.beacon_panel.apply_scout(event['beacon_scout'])
                if 'hunt_auto_start_epoch' in event:
                    self.start_hunt_on_refresh(event['hunt_auto_start_epoch'])
                if 'hunt_auto_next_ms' in event:
                    next_ms = event['hunt_auto_next_ms']
                    self.monster_panel.auto_hint.set('刷新时刻自动开启；下次参考：' + display_time(next_ms)
                                                    if next_ms is not None else '当前地图没有配置刷新时刻，未安排自动开启')
                if 'hunt_auto_status' in event:
                    self.monster_panel.auto_hint.set(event['hunt_auto_status'])
                if event.get('enabled') is False:
                    self.enabled.set(False)
                if event.get('hero_enabled') is False:
                    self.hero_enabled.set(False)
                if event.get('collect_enabled') is False:
                    self.collect_enabled.set(False)
                if 'hunt_enabled' in event:
                    self.hunt_enabled.set(bool(event['hunt_enabled']))
                if event.get('league_enabled') is False:
                    self.league_enabled.set(False)
                if 'league_status' in event:
                    self.league_panel.status.set(event['league_status'].splitlines()[0][:240])
                if 'league_snapshot' in event:
                    self.league_panel.apply_snapshot(event['league_snapshot'])
                if 'hunt_status' in event:
                    self.monster_panel.status.set(event['hunt_status'].splitlines()[0][:240])
                if 'hunt_team' in event:
                    self.monster_panel.apply_team(event['hunt_team'])
                if 'hunt_snapshot' in event:
                    self.monster_panel.apply_snapshot(event['hunt_snapshot'])
                if 'collection_metrics' in event:
                    self.hero_panel.apply_metrics(event['collection_metrics'])
                    self.collection_panel.apply_metrics(event['collection_metrics'])
                if 'collection_attributes_missing' in event:
                    self.hero_panel.clear_metrics(event['collection_attributes_missing'])
                if 'collection_status' in event:
                    self.collection_panel.status.set(event['collection_status'].splitlines()[0][:220])
                if 'resource_coordinates' in event:
                    self.collection_panel.apply_resource_coordinates(event['resource_coordinates'])
                if 'collection_teams' in event and (self.worker is None or
                        event.get('collection_teams_epoch') == self.worker.collection.epoch):
                    self.collection_teams_panel.apply_snapshot(event['collection_teams'])
                if 'hero_roster' in event:
                    self.hero_panel.apply_roster(event['hero_roster'])
                    if 'queue_used' in event['hero_roster']:
                        self.collection_panel.apply_queue(event['hero_roster'])
                if 'collection_queue' in event:
                    self.collection_panel.apply_queue(event['collection_queue'])
                if 'collection_balance' in event:
                    self.collection_panel.apply_balance(event['collection_balance'])
                if 'hero_list_status' in event:
                    self.hero_status.set(event['hero_list_status'].splitlines()[0][:200])
                if 'hero_state' in event:
                    self.hero_panel.apply_state(event['hero_state'])
                if 'hero_status' in event:
                    if self.hero_enabled.get() or event.get('hero_enabled') is False or event.get('recovery_for_collection'):
                        self.hero_status.set(event['hero_status'].splitlines()[0][:200])
                if 'state' in event:
                    state = event['state']
                    unit = state['soldier_id']
                    self.counts[unit].set(f"{owned_soldiers(state)} / {state['limit']}　训练中：{state['pending']}　编队：{state.get('deployed', 0)}")
                    self.stock.set(f"五分钟训练加速：{state['items']} 个")
                if 'status' in event:
                    text = event['status'].splitlines()[0]
                    if not self.enabled.get() and text == '运行中':
                        text = '已关闭，不再发送新请求'
                    self.status.set(text[:240])
                self.update_controls()
        except queue.Empty:
            pass
        if not self.closing:
            self.root.after(100, self.poll)

    def close(self):
        """Disable every independent action gate before closing the visible control window."""
        self.closing = True
        self.sessions.close()
        self.enabled.set(False)
        self.hero_enabled.set(False)
        self.collect_enabled.set(False)
        self.hunt_enabled.set(False)
        self.league_enabled.set(False)
        self.beacon_enabled.set(False)
        if self.worker is not None:
            try:
                self.worker.stop()
            except Exception:
                pass
        self.root.destroy()

    def run(self):
        """Keep the control window responsive until the user closes it."""
        self.root.mainloop()


if __name__ == '__main__':
    try:
        App().run()
    except Exception:
        import traceback
        Path(__file__).with_name('startup-error.txt').write_text(traceback.format_exc(), encoding='utf-8')
        raise
