"""Default-off controls for troops, shared recovery and resource-specific collection."""
import queue
import threading
import time
from datetime import datetime, timedelta
from math import ceil
import tkinter as tk
from pathlib import Path
from tkinter import ttk, filedialog, messagebox

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
from account_dialog import AccountDialog
from trial_panel import TrialPanel
from report_panel import ReportPanel
from player_panel import PlayerPanel
from league_members_panel import LeagueMembersPanel
from battle_chat import BattleChatSession
from battle_chat_panel import BattleChatPanel
from hall_profile import HallProfileSession
from guild_invite import GuildInviteSession
from guild_invite_panel import GuildInvitePanel
from guild_web_relay import GuildWebRelay
from gem_swap import GemSwapSession
from gem_swap_panel import GemSwapPanel
from hunt_reconnect import log_reconnect
from secondary_page import SecondaryPage, discover_devices


class App:
    """Keep troop selections separate from the master spending switch."""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title('英雄杀 · 造兵、恢复、采集与打野')
        self.root.geometry('1050x1000')
        self.root.minsize(900, 940)
        self.events = queue.Queue()
        self.battle_chat = BattleChatSession(self.events)
        self.hall_profile = HallProfileSession(self.events)
        self.guild_invite = GuildInviteSession(self.events)
        self.guild_web_relay = GuildWebRelay(self.guild_invite, self.events)
        self.gem_swap = GemSwapSession(self.events)
        self.sessions = LoginSession(self.events)
        self.login_busy = False
        self.accounts_dialog = None
        self.worker = None
        self.closing = False
        self.secondary = None
        self.device_picker_open = False
        self.primary_profile_id = None
        self.reconnect_timer = None
        self.ready = False
        self.trial_exclusive = False
        self.enabled = tk.BooleanVar(value=False)
        self.training_speed = tk.BooleanVar(value=False)
        self.hero_enabled = tk.BooleanVar(value=False)
        self.collect_enabled = tk.BooleanVar(value=False)
        self.hunt_enabled = tk.BooleanVar(value=False)
        self.league_enabled = tk.BooleanVar(value=False)
        self.beacon_enabled = tk.BooleanVar(value=False)
        self.trial_enabled = tk.BooleanVar(value=False)
        self.report_enabled = tk.BooleanVar(value=False)
        self.gem_swap_enabled = tk.BooleanVar(value=False)
        self.selections = {unit: tk.BooleanVar(value=unit == 411) for unit in UNIT_NAMES}
        self.counts = {unit: tk.StringVar(value='正在读取…') for unit in UNIT_NAMES}
        self.stock = tk.StringVar(value='五分钟训练加速：正在读取…')
        self.status = tk.StringVar(value='请保持游戏在西游幻境中，正在连接…')
        style = ttk.Style()
        style.configure('Title.TLabel', font=('Microsoft YaHei UI', 15, 'bold'))
        style.configure('TLabel', font=('Microsoft YaHei UI', 10))
        style.configure('Switch.TCheckbutton', font=('Microsoft YaHei UI', 13))
        self.workspace = ttk.Notebook(self.root)
        self.workspace.pack(fill='both', expand=True)
        panel = self.primary_page = ttk.Frame(self.workspace, padding=(16, 3))
        self.workspace.add(panel, text='雷电 0')
        self.add_device_page = ttk.Frame(self.workspace)
        self.workspace.add(self.add_device_page, text='＋ 添加雷电')
        self.workspace.bind('<<NotebookTabChanged>>', self.workspace_changed)
        header = ttk.Frame(panel)
        header.pack(fill='x')
        ttk.Label(header, text='世界模式助手', style='Title.TLabel').pack(side='left')
        self.login_button = ttk.Button(header, text='iOS 微信扫码登录', command=lambda: self.request_session('account_qr', (1, 0)))
        self.login_button.pack(side='right')
        self.reload_button = ttk.Button(header, text='重新读取当前账号', command=lambda: self.request_session('connect'))
        self.reload_button.pack(side='right', padx=6)
        ttk.Button(header, text='账号管理', command=self.open_accounts).pack(side='right')
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
        self.trial_panel = TrialPanel(self.feature_tabs, self.trial_enabled, self.switch_trial)
        self.feature_tabs.add(self.trial_panel, text='灵台试炼')
        self.report_panel = ReportPanel(self.feature_tabs,self.report_enabled,self.switch_report)
        self.feature_tabs.add(self.report_panel,text='军报')
        self.player_panel = PlayerPanel(self.feature_tabs, self.query_player,self.clear_player_cache)
        self.feature_tabs.add(self.player_panel, text='玩家武将查询')
        self.league_members_panel = LeagueMembersPanel(self.feature_tabs,self.query_league,self.stop_map_search,self.stop_league_export)
        self.feature_tabs.add(self.league_members_panel,text='联盟成员')
        self.battle_chat_panel = BattleChatPanel(self.feature_tabs,self.send_battle_chat)
        self.feature_tabs.add(self.battle_chat_panel,text='战斗聊天')
        self.guild_invite_panel = GuildInvitePanel(self.feature_tabs, self.guild_invite, self.guild_web_relay)
        self.feature_tabs.add(self.guild_invite_panel, text='公会邀请')
        self.gem_swap_panel = GemSwapPanel(self.feature_tabs, self.gem_swap_enabled, self.switch_gem_swap,
                                           self.revert_gem_swap, self.probe_gem_swap, self.resolve_gem_swap)
        self.feature_tabs.add(self.gem_swap_panel, text='宝具替换')
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

    def workspace_changed(self, _event):
        """Open the instance selector from the add tab without disturbing the primary task view."""
        if self.closing or self.device_picker_open or self.secondary is not None:
            return
        if self.workspace.select() != str(self.add_device_page):
            return
        self.workspace.select(self.primary_page)
        self.device_picker_open = True
        result = queue.Queue()

        def find():
            """Query ADB off the Tk thread so the first tab stays responsive."""
            try:
                result.put(discover_devices())
            except Exception:
                result.put(None)

        def show():
            """Display one explicit selection of an online emulator other than the first."""
            if self.closing:
                return
            try:
                devices = result.get_nowait()
            except queue.Empty:
                self.root.after(80, show)
                return
            if not devices:
                self.device_picker_open = False
                messagebox.showinfo('添加雷电', '未读取到第二台在线雷电，请启动第二台模拟器并确认 ADB 已连接。', parent=self.root)
                return
            dialog = tk.Toplevel(self.root)
            dialog.title('添加雷电实例')
            dialog.transient(self.root)
            body = ttk.Frame(dialog, padding=14)
            body.pack(fill='both', expand=True)
            ttk.Label(body, text='选择要添加到第二个标签页的雷电设备。').pack(anchor='w')
            devices_box = ttk.Combobox(body, values=devices, state='readonly', width=24)
            devices_box.current(0)
            devices_box.pack(fill='x', pady=8)

            def finish():
                """Release the picker so it can be opened again after cancel or close."""
                self.device_picker_open = False
                dialog.destroy()

            def add():
                """Bind the new tab only to the explicitly selected serial."""
                device = devices_box.get()
                finish()
                self.workspace.forget(self.add_device_page)
                self.secondary = SecondaryPage(self.workspace, device, self.close_secondary, lambda: self.primary_profile_id)
                self.workspace.add(self.secondary, text='雷电 1')
                self.workspace.select(self.secondary)

            ttk.Button(body, text='连接所选设备', command=add).pack(side='right')
            ttk.Button(body, text='取消', command=finish).pack(side='right', padx=6)
            dialog.protocol('WM_DELETE_WINDOW', finish)

        threading.Thread(target=find, daemon=True).start()
        self.root.after(80, show)

    def close_secondary(self):
        """Close the second tab while its process releases resources without blocking the first tab."""
        page = self.secondary
        if page is None or page.closing:
            return
        page.close()
        self.workspace.select(self.primary_page)
        self.workspace.forget(page)

        def release():
            """Expose the add tab again only after the old emulator owner has exited."""
            if page.process.thread.is_alive():
                self.root.after(100, release)
                return
            page.destroy()
            self.secondary = None
            if not self.closing:
                self.workspace.add(self.add_device_page, text='＋ 添加雷电')

        self.root.after(100, release)

    def connect(self):
        """Start a fresh default-off session without blocking Tk on game readiness."""
        self.request_session('connect')

    def clear_account_views(self):
        """Remove all old account snapshots and switches while retaining explicit saved selection settings."""
        self.ready = False
        self.trial_exclusive = False
        self.player_panel.clear()
        self.league_members_panel.clear()
        self.battle_chat.cancel_pending();self.battle_chat_panel.clear()
        self.hall_profile.cancel_pending()
        self.guild_web_relay.stop()
        self.guild_invite.cancel_pending()
        self.guild_invite_panel.clear()
        for variable in (self.enabled, self.hero_enabled, self.collect_enabled, self.hunt_enabled,
                         self.league_enabled, self.beacon_enabled, self.training_speed, self.trial_enabled,self.report_enabled):
            variable.set(False)
        for count in self.counts.values():
            count.set('正在读取…')
        self.stock.set('五分钟训练加速：正在读取…')
        hero = self.hero_panel
        hero.mode.set('普通')
        hero.roster.clear(); hero.speeds.clear(); hero.loads.clear(); hero.references.clear()
        hero.tree.delete(*hero.tree.get_children())
        hero.stock.set('五分钟英雄恢复加速：正在读取…')
        hero.reference_text.set('采集速度：等待当前账号数据…')
        hero.status.set('自动恢复关闭，等待当前账号名单…')
        collection = self.collection_panel
        collection.use_hero_recovery.set(False)
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
        self.trial_panel.clear()
        self.report_panel.clear()
        self.gem_swap_panel.clear()

    def open_accounts(self):
        """Display public saved-role metadata in a separate window without interrupting active game work."""
        if self.accounts_dialog is None or not self.accounts_dialog.winfo_exists():
            self.accounts_dialog = AccountDialog(self)
        else:
            self.accounts_dialog.refresh(self.sessions.store.list())
            self.accounts_dialog.lift()

    def request_session(self, mode, selection=None):
        """Stop old automation before login, local migration or reconstruction; credentials never reach status text."""
        if self.closing:
            return
        self.cancel_reconnect('手动操作或会话替换')
        self.clear_account_views()
        self.login_busy = True
        migrating = mode in {'account_export', 'account_import'}
        self.account_status.set('正在处理本地账号迁移，自动功能全部关闭' if migrating else '当前账号：正在重新读取，自动功能关闭')
        self.status.set('正在停止旧连接并加密处理迁移文件…' if migrating else
                        '正在停止旧连接并处理账号操作…' if mode != 'connect' else '正在重新连接当前账号…')
        self.sessions.request(mode, selection)
        self.worker = None
        self.update_controls()

    def cancel_reconnect(self, reason):
        """Cancel the window-owned attempt before a manual action or shutdown takes ownership."""
        if self.reconnect_timer is not None:
            self.root.after_cancel(self.reconnect_timer)
            self.reconnect_timer = None
            log_reconnect('helper_reconnect_cancelled', reason)

    def schedule_reconnect(self, plan):
        """Hand off one monotonic deadline after the disconnected worker releases the bridge."""
        if self.closing or self.reconnect_timer is not None:
            return
        epoch = self.sessions.epoch
        delay = max(0, plan['deadline'] - time.monotonic())
        due = datetime.now() + timedelta(seconds=delay)

        def attempt():
            """Consume the timer once, ignoring callbacks from a replaced or closed window session."""
            if self.closing or self.sessions.epoch != epoch or self.reconnect_timer != timer:
                return
            self.reconnect_timer = None
            log_reconnect('helper_reconnect_attempt', '等待时间已到，检查原游戏进程与会话')
            self.request_session('hunt_reconnect', plan)

        timer = self.root.after(ceil(delay * 1000), attempt)
        self.reconnect_timer = timer
        self.status.set(f'连接异常，预计 {due:%H:%M:%S} 自动重连一次')
        log_reconnect('helper_reconnect_scheduled', '连接异常，保留采集与打野计划',
                      due=due.isoformat(timespec='seconds'), disconnect_reason=plan['reason'])

    def update_controls(self):
        """Enable each independent master while connected and freeze the settings owned by an active run."""
        world_ready = self.ready and not self.trial_exclusive
        self.toggle.state(['!disabled'] if world_ready else ['disabled'])
        self.hero_panel.update_controls(world_ready, self.collect_enabled.get())
        self.collection_panel.update_controls(world_ready)
        self.monster_panel.update_controls(world_ready)
        self.league_panel.update_controls(world_ready)
        self.player_panel.update_controls(not self.login_busy and not self.closing)
        self.league_members_panel.update_controls(world_ready)
        self.battle_chat_panel.update_controls(not self.login_busy and not self.closing)
        self.guild_invite_panel.update_controls(not self.login_busy and not self.closing)
        self.beacon_panel.update_controls(world_ready)
        self.trial_panel.update_controls(self.ready)
        self.report_panel.update_controls(world_ready)
        self.gem_swap_panel.update_controls(True)
        self.collection_teams_panel.set_active(self.collect_enabled.get(), world_ready)
        for box in self.choice_widgets.values():
            box.state(['disabled'] if self.enabled.get() or self.trial_exclusive else ['!disabled'])
        self.speed_toggle.state(['disabled'] if self.enabled.get() or self.trial_exclusive else ['!disabled'])
        self.login_button.state(['disabled'] if self.login_busy else ['!disabled'])
        if self.accounts_dialog is not None and self.accounts_dialog.winfo_exists():
            self.accounts_dialog.update_controls()

    def send_battle_chat(self,message):
        """Delegate only an explicit composer click; battle chat does not depend on a loaded world map."""
        if self.login_busy or self.closing:raise RuntimeError('账号操作或关闭进行中，未发送')
        self.battle_chat.submit(message)

    def switch_hero(self):
        """Freeze hero choices and the explicit shared recovery mode without changing troop automation."""
        if self.worker is None:
            self.hero_enabled.set(False)
            return
        try:
            if self.hero_enabled.get():self.worker.set_recovery_mode(self.hero_panel.recovery_mode())
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
        """Freeze collection scope and the same recovery mode used by the ordinary hero master."""
        if self.worker is None:
            self.collect_enabled.set(False)
            return
        try:
            if self.collect_enabled.get():self.worker.set_recovery_mode(self.hero_panel.recovery_mode())
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
        if not self.ready or self.closing or self.trial_exclusive or self.worker is None or self.hunt_enabled.get():
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

    def query_player(self):
        """Query public profiles through a login-bound temporary hall connection, independently of map readiness."""
        if self.login_busy or self.closing:return
        try:
            self.hall_profile.submit(self.player_panel.player_id.get(),self.worker)
            self.player_panel.replace_details('')
            self.player_panel.set_busy(True)
            self.league_members_panel.set_busy(True)
            self.player_panel.status.set('已提交玩家查询，等待处理…')
        except Exception as error:
            self.player_panel.status.set(str(error).splitlines()[0])

    def clear_player_cache(self):
        """Clear the current login's local profile cache without requiring world entry or sending a request."""
        if self.login_busy or self.closing:return
        try:
            self.hall_profile.submit(None,self.worker,clear_cache=True)
            self.player_panel.set_busy(True);self.league_members_panel.set_busy(True)
            self.player_panel.status.set('正在清空当前资料缓存…')
        except Exception as error:self.player_panel.status.set(str(error).splitlines()[0])

    def query_league(self, operation, value):
        """Choose an export destination before querying, then serialize the clicked league action."""
        if self.worker is None:return
        try:
            if operation=='export':
                import re
                from datetime import datetime
                league=next((r for r in self.league_members_panel.comparison_rows if r['league_id']==value),{})
                name=re.sub(r'[<>:"/\\|?*\x00-\x1f]','_',league.get('name','联盟')).strip(' .')or'联盟'
                path=filedialog.asksaveasfilename(parent=self.root,title='导出联盟已记录成员',defaultextension='.xlsx',
                    initialfile=f"{name}_{datetime.now():%Y%m%d_%H%M%S}.xlsx",filetypes=[('Excel 工作簿','*.xlsx')])
                if not path:return
                self.worker.request_league_export(value,path)
                self.league_members_panel.export_running=True
            else:self.worker.request_league_query(operation,value)
            if operation in {'leagues','roster'}:self.league_members_panel.clear_roster()
            else:self.league_members_panel.replace_details('')
            self.league_members_panel.set_busy(True);self.player_panel.set_busy(True)
            self.league_members_panel.status.set('已提交导出，正在逐人查询资料…'if operation=='export'else'已提交查询，等待服务器响应…')
        except Exception as error:self.league_members_panel.status.set(str(error).splitlines()[0])

    def stop_map_search(self):
        """Cancel remaining planned areas locally, allowing the current scoped read to restore the original view."""
        if self.worker is not None:
            self.worker.map_index.stop()
            self.league_members_panel.status.set('正在停止搜索，等待当前区域返回并保存已发现记录…')

    def stop_league_export(self):
        """Stop unsent export requests and save a workbook marking the remaining members unqueried."""
        if self.worker is not None:
            self.worker.league_export.stop()
            self.league_members_panel.status.set('正在停止导出，将保留已取得资料并标注未查询成员…')

    def switch_report(self):
        """Authorize only the current account's two-hour timer; enabling never immediately claims anything."""
        if self.worker is None:
            self.report_enabled.set(False)
            return
        try:
            self.worker.report.switch(self.report_enabled.get())
        except Exception as error:
            self.report_enabled.set(False)
            self.report_panel.status.set('自动领取未开启：'+str(error).splitlines()[0])
        self.update_controls()

    def switch_trial(self):
        """Start the exclusive default-off trial run or immediately revoke its queued requests for manual handoff."""
        if self.worker is None:
            self.trial_enabled.set(False)
            return
        try:
            self.worker.switch_trial(self.trial_enabled.get())
            self.trial_exclusive = self.worker.trial.holding
            if self.trial_enabled.get():
                for v in (self.enabled,self.hero_enabled,self.collect_enabled,self.hunt_enabled,self.league_enabled,self.beacon_enabled,self.training_speed,self.report_enabled):
                    v.set(False)
                self.trial_panel.status.set('正在读取本轮试炼；已有名单沿用，无名单时选择最强可用三人')
        except Exception as error:
            self.trial_enabled.set(False)
            self.trial_panel.status.set('自动爬塔未开启：'+str(error).splitlines()[0])
        self.update_controls()

    def switch_gem_swap(self, revert=False):
        """Arm or disarm the 宝具 rules through this feature's own bridge; never sends a game request."""
        try:
            if revert:
                self.gem_swap.revert()
            elif self.gem_swap_enabled.get():
                hero_base, first, second = self.gem_swap_panel.selection()
                self.gem_swap.arm(hero_base, first, second, self.gem_swap_panel.hero.get())
            else:
                self.gem_swap.disarm()
        except Exception as error:
            self.gem_swap_enabled.set(False)
            self.gem_swap_panel.status.set('宝具替换未开启：' + str(error).splitlines()[0][:200])
        self.update_controls()

    def revert_gem_swap(self, revert=True):
        """Restore the client slots this session changed; the rules stay disarmed afterwards."""
        self.switch_gem_swap(True)

    def probe_gem_swap(self, probe=True):
        """Read the hero this battle assigned to my seat, so it can be named without the world roster."""
        self.gem_swap.probe()

    def resolve_gem_swap(self, resolve=True):
        """Resolve the typed hero name through the game's own config rows."""
        try:
            self.gem_swap.resolve(self.gem_swap_panel.hero.get())
        except Exception as error:
            self.gem_swap_panel.status.set('英雄名未解析：' + str(error).splitlines()[0][:200])

    def poll(self):
        """Render confirmed switches and accept only the authorized, scoped scheduled-hunting start requests."""
        try:
            while True:
                event = self.events.get_nowait()
                if event.get('session_epoch', self.sessions.epoch) != self.sessions.epoch:
                    continue
                if event.get('chat_generation',self.battle_chat.generation)!=self.battle_chat.generation:
                    continue
                if event.get('hall_profile_generation',self.hall_profile.generation)!=self.hall_profile.generation:
                    continue
                if ('guild_invite_generation' in event and
                        event['guild_invite_generation'] != self.guild_invite.generation):
                    continue
                if 'guild_web_status' in event:
                    self.guild_invite_panel.apply_web_status(event['guild_web_status'])
                if 'guild_web_received' in event:
                    self.guild_invite_panel.mark_web_received(event['guild_web_received'])
                if event.get('guild_invite_sending'):
                    self.guild_invite_panel.mark_sending()
                if 'guild_invite_result' in event:
                    self.guild_invite_panel.apply_result(event['guild_invite_result'])
                if 'battle_chat_result'in event:
                    self.battle_chat_panel.apply_result(event['battle_chat_result'])
                if 'hall_profile_snapshot'in event or 'hall_profile_error'in event:
                    self.player_panel.set_busy(False);self.league_members_panel.set_busy(False)
                    if 'hall_profile_error'in event:self.player_panel.status.set(event['hall_profile_error'])
                    else:
                        snapshot=event['hall_profile_snapshot']
                        if snapshot.get('cleared'):
                            self.player_panel.replace_details('');self.league_members_panel.replace_details('')
                            self.player_panel.status.set(snapshot['status'])
                        else:self.player_panel.apply_snapshot(snapshot)
                self.worker = self.sessions.worker
                if event.get('trial_reconnect'):
                    snapshot=self.trial_panel.snapshot
                    message=self.trial_panel.status.get()
                    self.request_session('connect')
                    if snapshot is not None:
                        self.trial_panel.apply_snapshot({**snapshot,'enabled':False,'phase':'off'})
                    self.trial_panel.status.set(message+'；已返回地图，重新读取账号，所有开关保持关闭')
                    continue
                if event.get('delayed_reconnect'):
                    self.schedule_reconnect(event['delayed_reconnect'])
                    continue
                if 'login_busy' in event:
                    self.login_busy = event['login_busy']
                if 'account' in event:
                    label = account_label(event['account'])
                    self.account_status.set(label)
                    self.primary_profile_id = event['account'].get('profile_id')
                    name = label.removeprefix('当前角色：').split(' · ', 1)[0]
                    self.workspace.tab(self.primary_page, text='雷电 0 · ' + name if event['account'].get('logged_in') else '雷电 0')
                if 'account_status' in event:
                    self.account_status.set(event['account_status'])
                if 'profiles' in event and self.accounts_dialog is not None and self.accounts_dialog.winfo_exists():
                    self.accounts_dialog.refresh(event['profiles'])
                if 'ready' in event:
                    self.ready = event['ready']
                if 'player_busy' in event:
                    self.player_panel.set_busy(event['player_busy'])
                    self.league_members_panel.set_busy(event['player_busy'])
                if 'league_query_status' in event:
                    self.league_members_panel.status.set(event['league_query_status'])
                if event.get('player_cache_cleared'):
                    self.league_members_panel.replace_details('');self.player_panel.replace_details('')
                    self.player_panel.status.set('当前图玩家资料缓存已清空，下次查询将重新请求服务器。')
                if 'map_index_snapshot' in event:
                    self.league_members_panel.apply_index(event['map_index_snapshot'])
                if 'map_index_progress' in event:
                    self.league_members_panel.apply_search_progress(event['map_index_progress'])
                if 'league_export_progress' in event:
                    self.league_members_panel.apply_export_progress(event['league_export_progress'])
                if 'league_query_list' in event:
                    self.league_members_panel.apply_leagues(event['league_query_list'])
                if 'league_query_roster' in event:
                    self.league_members_panel.apply_roster(event['league_query_roster'])
                if 'league_query_member' in event:
                    self.league_members_panel.apply_member(event['league_query_member'])
                if 'player_status' in event:
                    self.player_panel.status.set(event['player_status'])
                if 'player_snapshot' in event:
                    self.player_panel.apply_snapshot(event['player_snapshot'])
                if 'trial_enabled' in event:
                    self.trial_enabled.set(bool(event['trial_enabled']))
                if 'report_enabled' in event:
                    self.report_enabled.set(bool(event['report_enabled']))
                if 'report_next_ms' in event:
                    self.report_panel.apply_next(event['report_next_ms'])
                if 'report_snapshot' in event:
                    self.report_panel.apply_snapshot(event['report_snapshot'])
                if 'report_status' in event:
                    self.report_panel.status.set(event['report_status'].splitlines()[0][:240])
                if 'trial_exclusive' in event:
                    self.trial_exclusive = bool(event['trial_exclusive'])
                if 'trial_status' in event:
                    self.trial_panel.status.set(event['trial_status'].splitlines()[0][:240])
                if 'trial_snapshot' in event:
                    self.trial_panel.apply_snapshot(event['trial_snapshot'])
                if 'gem_swap_enabled' in event:
                    self.gem_swap_enabled.set(bool(event['gem_swap_enabled']))
                if 'gem_swap_status' in event:
                    self.gem_swap_panel.status.set(event['gem_swap_status'].splitlines()[0][:240])
                if 'gem_swap_slots' in event:
                    self.gem_swap_panel.apply_slots(event['gem_swap_slots'])
                if 'gem_swap_current_hero' in event:
                    self.gem_swap_panel.apply_current_hero(event['gem_swap_current_hero'])
                if 'gem_swap_resolved' in event:
                    self.gem_swap_panel.apply_resolved(event['gem_swap_resolved'])
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
                if 'collect_use_hero_recovery' in event:
                    self.collection_panel.use_hero_recovery.set(event['collect_use_hero_recovery'])
                if 'collect_enabled' in event:
                    self.collect_enabled.set(event['collect_enabled'])
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
                    self.gem_swap_panel.set_roster(event['hero_roster'].get('heroes'))
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
        if self.closing:
            return
        self.closing = True
        self.close_secondary()
        self.cancel_reconnect('助手已退出')
        self.battle_chat.close()
        self.hall_profile.close()
        self.guild_web_relay.stop()
        self.guild_invite.close()
        self.sessions.close()
        self.enabled.set(False)
        self.hero_enabled.set(False)
        self.collect_enabled.set(False)
        self.hunt_enabled.set(False)
        self.league_enabled.set(False)
        self.beacon_enabled.set(False)
        self.trial_enabled.set(False)
        self.report_enabled.set(False)
        self.gem_swap_enabled.set(False)
        self.gem_swap.close()
        if self.worker is not None:
            try:
                self.worker.stop()
            except Exception:
                pass
        self.finish_close()

    def finish_close(self):
        """Wait without blocking Tk so daemon shutdown cannot interrupt a two-file SDK restore transaction."""
        secondary = getattr(self, 'secondary', None)
        if ((secondary is not None and secondary.process.thread.is_alive()) or
                self.sessions.pending_shutdown() or self.battle_chat.pending_shutdown() or
                self.hall_profile.pending_shutdown() or self.guild_invite.pending_shutdown() or
                self.guild_web_relay.pending_shutdown()):
            self.status.set('正在安全退出账号操作，请稍候；自动功能全部关闭…')
            self.root.after(100, self.finish_close)
        else:
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
