"""Second emulator tab with its own world-mode controls and background process."""
from dataclasses import asdict
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import ttk

from beacon_panel import BeaconPanel
from bootstrap import ADB
from collection_display import display_time
from collection_panel import CollectionPanel
from collection_teams_panel import CollectionTeamsPanel
from controller import owned_soldiers
from hero_panel import HeroPanel
from instance_config import PRIMARY_DEVICE, instance_directory, role_preferences
from league_panel import LeaguePanel
from login_session import account_label
from monster_panel import MonsterPanel
from report_panel import ReportPanel
from units import UNIT_NAMES


def discover_devices():
    """List online emulator serials without touching the primary instance or forwarding ports."""
    result = subprocess.run([ADB, 'devices'], capture_output=True, check=True, text=True, encoding='utf-8',
                            timeout=5, creationflags=subprocess.CREATE_NO_WINDOW)
    devices = []
    for line in result.stdout.splitlines():
        fields = line.split()
        if (len(fields) >= 2 and fields[1] == 'device' and fields[0] != PRIMARY_DEVICE
                and re.fullmatch(r'emulator-[0-9]{4,5}', fields[0])):
            devices.append(fields[0])
    return sorted(set(devices))


class InstanceProcess:
    """Transport one tab's commands and server-confirmed display events over inherited pipes."""

    def __init__(self, device, events, expected_identity=None):
        """Identify the selected emulator and start its worker without blocking Tk."""
        self.device = device
        self.expected_identity = expected_identity
        self.events = events
        self.process = None
        self.closing = threading.Event()
        self.guard = threading.Lock()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        """Wait for child output and keep a visible error if identification or startup fails."""
        try:
            identity = subprocess.run([ADB, '-s', self.device, 'shell', 'settings', 'get', 'secure', 'android_id'],
                                      capture_output=True, check=True, text=True, encoding='utf-8', timeout=5,
                                      creationflags=subprocess.CREATE_NO_WINDOW).stdout.strip().lower()
            if self.expected_identity is not None and identity != self.expected_identity:
                raise ValueError('设备身份已变化，请关闭标签页后重新选择实例')
            directory = instance_directory(self.device, identity)
            directory.mkdir(parents=True, exist_ok=True)
            env = dict(os.environ, REA_HELPER_DEVICE=self.device, REA_HELPER_DEVICE_ID=identity)
            executable = Path(sys.executable).with_name('python.exe') if Path(sys.executable).name.lower() == 'pythonw.exe' else sys.executable
            with (directory / 'worker-errors.log').open('a', encoding='utf-8') as diagnostics:
                with self.guard:
                    if self.closing.is_set():
                        return
                    self.process = subprocess.Popen([str(executable), '-u', str(Path(__file__).with_name('instance_worker.py'))],
                                                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=diagnostics,
                                                    text=True, encoding='utf-8', env=env,
                                                    creationflags=subprocess.CREATE_NO_WINDOW)
                self.events.put({'device_directory': directory})
                for line in self.process.stdout:
                    self.events.put(json.loads(line))
                self.process.wait()
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            self.events.put({'process_error': '雷电连接未建立：' + str(error).splitlines()[0][:180]})
        finally:
            self.close()
            if self.process is not None:
                self.process.wait()
                self.process.stdout.close()
            self.events.put({'process_stopped': True})

    def send(self, **command):
        """Submit one command to the running instance or fail without changing its task state."""
        with self.guard:
            if self.closing.is_set() or self.process is None or self.process.poll() is not None:
                raise RuntimeError('第二台雷电后台尚未连接，请先重新读取')
            try:
                self.process.stdin.write(json.dumps(command, ensure_ascii=True) + '\n')
                self.process.stdin.flush()
            except OSError as error:
                raise RuntimeError('第二台雷电后台连接已断开') from error

    def close(self):
        """Signal EOF so the worker can release its bridge and finish any in-flight login transaction."""
        with self.guard:
            if not self.closing.is_set():
                self.closing.set()
                if self.process is not None:
                    try:
                        self.process.stdin.close()
                    except OSError:
                        pass


class SecondaryPage(ttk.Frame):
    """Render the second emulator's controls without borrowing the first tab's worker or settings."""

    def __init__(self, notebook, device, on_close, primary_role):
        """Create the default-off controls and start a dedicated emulator process."""
        super().__init__(notebook, padding=(12, 8))
        self.notebook = notebook
        self.device = device
        self.primary_role = primary_role
        self.on_close = on_close
        self.events = queue.Queue()
        self.epoch = 0
        self.ready = False
        self.busy = True
        self.closing = False
        self.directory = None
        self.scope = None
        self.collection_review_pending = False
        self.profiles = []
        self.account_window = None
        self.switches = {name: tk.BooleanVar(self) for name in ('enabled', 'collect_enabled', 'hero_enabled',
                                                                'hunt_enabled', 'league_enabled', 'beacon_enabled', 'report_enabled')}
        self.account = tk.StringVar(self, value='正在读取角色…')
        self.status = tk.StringVar(self, value='正在连接 ' + device)
        header = ttk.Frame(self)
        header.pack(fill='x', pady=(0, 6))
        ttk.Label(header, textvariable=self.account, style='Title.TLabel').pack(side='left')
        ttk.Label(header, text=self.device).pack(side='left', padx=(8, 0))
        ttk.Button(header, text='关闭标签页', command=on_close).pack(side='right')
        self.reload_button = ttk.Button(header, text='重新读取', command=lambda: self.session('connect'))
        self.reload_button.pack(side='right', padx=5)
        self.account_button = ttk.Button(header, text='切换账号', command=self.choose_account)
        self.account_button.pack(side='right')
        top = ttk.Frame(self)
        top.pack(fill='x')
        training = ttk.LabelFrame(top, text='士兵训练', padding=9)
        training.pack(side='left', fill='both', expand=True, padx=(0, 8))
        self.training_switch = ttk.Checkbutton(training, text='自动造兵', variable=self.switches['enabled'],
                                                command=lambda: self.switch('enabled'))
        self.training_switch.pack(anchor='w')
        self.units = {unit: tk.BooleanVar(self, value=unit == 411) for unit in (412, 413, 411, 803)}
        self.counts = {unit: tk.StringVar(self, value='正在读取…') for unit in self.units}
        self.unit_buttons = []
        for unit, selected in self.units.items():
            row = ttk.Frame(training)
            row.pack(fill='x', pady=2)
            button = ttk.Checkbutton(row, text=UNIT_NAMES[unit], variable=selected)
            button.pack(side='left', padx=(0, 10))
            self.unit_buttons.append(button)
            ttk.Label(row, textvariable=self.counts[unit]).pack(side='left')
        self.stock = tk.StringVar(self, value='五分钟训练加速：待读取')
        ttk.Label(training, textvariable=self.stock).pack(anchor='w', pady=(6, 2))
        self.training_speed = tk.BooleanVar(self)
        self.speed_button = ttk.Checkbutton(training, text='自动使用五分钟训练加速', variable=self.training_speed)
        self.speed_button.pack(anchor='w')
        self.collection = CollectionPanel(top, self.switches['collect_enabled'], lambda: self.switch('collect_enabled'),
                                          lambda: self.action('collect_check'), preferences=None)
        self.collection.pack(side='right', fill='both', expand=True)
        self.collection_review = ttk.Button(self, text='已核对游戏中的采集队伍，解除暂停',
                                            command=lambda: self.action('collect_reviewed'))
        self.teams = CollectionTeamsPanel(self)
        self.teams.pack(fill='x', pady=4)
        tabs = ttk.Notebook(self)
        tabs.pack(fill='both', expand=True)
        self.heroes = HeroPanel(tabs, self.switches['hero_enabled'], lambda: self.switch('hero_enabled'),
                                lambda: self.action('hero_refresh'), lambda: self.action('attributes_refresh'), preferences=None)
        self.heroes.tree.configure(height=4)
        self.hunt = MonsterPanel(tabs, self.switches['hunt_enabled'], lambda: self.switch('hunt_enabled'), lambda: self.action('hunt_check'))
        self.league = LeaguePanel(tabs, self.switches['league_enabled'], lambda: self.switch('league_enabled'),
                                  lambda: self.action('league_check'))
        self.beacon = BeaconPanel(tabs, self.switches['beacon_enabled'], lambda: self.switch('beacon_enabled'),
                                  lambda: self.action('beacon_check'), preferences=None)
        self.report = ReportPanel(tabs, self.switches['report_enabled'], lambda: self.switch('report_enabled'))
        for panel, title in ((self.heroes, '英雄属性与恢复'), (self.hunt, '自动打野'), (self.league, '联盟采集'),
                             (self.beacon, '烽火台'), (self.report, '军报')):
            tabs.add(panel, text=title)
        ttk.Label(self, textvariable=self.status, wraplength=960).pack(anchor='w', pady=(6, 0))
        self.process = InstanceProcess(device, self.events)
        self.update_controls()
        self.poll_job = self.after(100, self.poll)

    def update_controls(self):
        """Keep each spending switch disabled until the current role and world are confirmed."""
        ready = self.ready and not self.closing and self.scope is not None
        self.training_switch.state(['!disabled'] if ready else ['disabled'])
        for button in (*self.unit_buttons, self.speed_button):
            button.state(['!disabled'] if ready and not self.switches['enabled'].get() else ['disabled'])
        self.heroes.update_controls(ready, self.switches['collect_enabled'].get())
        self.collection.update_controls(ready and not self.collection_review_pending)
        if ready and self.collection_review_pending:
            self.collection_review.pack(anchor='e', before=self.teams)
        else:
            self.collection_review.pack_forget()
        self.hunt.update_controls(ready)
        self.league.update_controls(ready)
        self.beacon.update_controls(ready)
        self.report.update_controls(ready)
        self.teams.set_active(self.switches['collect_enabled'].get(), ready)
        self.reload_button.state(['disabled'] if self.busy or self.closing else ['!disabled'])
        self.account_button.state(['disabled'] if self.busy or self.closing or not self.process.thread.is_alive() else ['!disabled'])

    def reset_role(self):
        """Clear previous-role choices, confirmed data, and any open resource editor."""
        self.ready = False
        self.scope = None
        self.collection_review_pending = False
        self.account.set('正在读取角色…')
        for value in self.switches.values():
            value.set(False)
        for unit, value in self.units.items():
            value.set(unit == 411)
        for value in self.counts.values():
            value.set('正在读取…')
        self.training_speed.set(False)
        self.stock.set('五分钟训练加速：待读取')
        self.collection.use_hero_recovery.set(False)
        self.collection.queue_snapshot = None
        self.collection.set_preferences(None)
        self.collection.status.set('等待当前角色的采集资料。')
        self.collection.balance_text.set('粮木铁按1:1:1补缺；等待当前角色存量。')
        self.collection.recommendation.set('等待当前角色的采集属性…')
        self.heroes.mode.set('普通')
        self.heroes.roster.clear()
        self.heroes.speeds.clear()
        self.heroes.loads.clear()
        self.heroes.references.clear()
        self.heroes.set_preferences(None)
        self.heroes.status.set('自动恢复关闭，等待当前角色名单…')
        self.heroes.reference_text.set('等待当前角色的采集属性…')
        self.heroes.stock.set('五分钟英雄恢复加速：待读取')
        self.hunt.radius.set(20)
        self.hunt.team.set('队伍：未派出')
        self.hunt.capacity.set('出征额度：待读取')
        self.hunt.status.set('自动打野关闭。')
        self.hunt.auto_hint.set('本账号尚未手动开启打野。')
        self.league.snapshot = None
        self.league.mine.set('等待当前角色的联盟资源矿…')
        self.league.confirmed.set('尚未确认服务器状态')
        self.league.status.set('自动联盟采集关闭。')
        self.beacon.set_preferences(None)
        self.beacon.scout_info = ''
        self.beacon.summary.set('烽火台额度：待读取')
        self.beacon.timing.set('刷新与下次检查：待读取')
        self.beacon.status.set('自动烽火台关闭。')
        self.beacon.snapshot = self.teams.snapshot = None
        self.teams.awaiting = False
        for panel in (self.heroes, self.hunt, self.league, self.beacon, self.teams):
            panel.tree.delete(*panel.tree.get_children())
        self.report.clear()
        self.notebook.tab(self, text='雷电 1')

    def session(self, mode, selection=None):
        """Apply a login or reconnect request to this tab only, disabling old-role controls immediately."""
        if self.busy or self.closing:
            return
        try:
            if mode == 'connect' and not self.process.thread.is_alive():
                self.epoch = 0
                self.events = queue.Queue()
                self.process = InstanceProcess(self.device, self.events, self.directory.name if self.directory is not None else None)
            else:
                self.process.send(operation='session', mode=mode, selection=selection)
                self.epoch += 1
        except RuntimeError as error:
            self.status.set(str(error))
            return
        self.reset_role()
        self.busy = True
        self.status.set('正在处理雷电 1 的账号与连接…')
        self.update_controls()

    def choose_account(self):
        """List only this emulator's locally saved accounts and offer explicit native QR login."""
        if self.account_window is not None and self.account_window.winfo_exists():
            self.account_window.lift()
            return
        dialog = self.account_window = tk.Toplevel(self)
        dialog.title('雷电 1 · 切换账号')
        dialog.transient(self.winfo_toplevel())
        body = ttk.Frame(dialog, padding=14)
        body.pack(fill='both', expand=True)
        ttk.Label(body, text='切号会暂停本页任务并重启雷电 1 中的游戏。保存当前账号也会暂停本页任务。').pack(anchor='w')
        listing = ttk.Treeview(body, columns=('name','platform','status'), show='headings', height=5, selectmode='browse')
        for key, title, width in (('name','角色',120),('platform','平台',110),('status','状态',200)):
            listing.heading(key, text=title)
            listing.column(key, width=width)
        listing.pack(fill='x', pady=6)
        for record in self.profiles:
            status = '雷电 0 正在使用' if record['profile_id'] == self.primary_role() else record['status']
            listing.insert('', 'end', iid=record['profile_id'], values=(record['name'], f"{record['mobile']} {record['platform']}", status))
        message = tk.StringVar(dialog, value='首次使用请扫码登录，或保存雷电 1 中已登录的角色。')
        ttk.Label(body, textvariable=message).pack(anchor='w', pady=3)

        def submit(mode, selection=None):
            """Close the chooser only after the owner explicitly requests an account operation."""
            dialog.destroy()
            self.session(mode, selection)

        def use_saved():
            """Reject an occupied or known-expired profile before pausing any task."""
            selected = listing.selection()
            if not selected:
                message.set('请先选择一个账号。')
                return
            profile = next(record for record in self.profiles if record['profile_id'] == selected[0])
            if selected[0] == self.primary_role():
                message.set('该账号正在雷电 0 使用，请选择其他账号。')
            elif self.scope is not None and selected[0] == self.scope['role']:
                message.set('雷电 1 已在使用该账号。')
            elif profile['status'] == '需要重新扫码':
                message.set('该账号需要重新扫码，请选择下方对应的平台。')
            else:
                submit('account_switch', selected[0])

        actions = ttk.Frame(body)
        actions.pack(fill='x', pady=4)
        ttk.Button(actions, text='切换到选中账号', command=use_saved).pack(side='left')
        ttk.Button(actions, text='保存当前账号', command=lambda: submit('account_save')).pack(side='left', padx=5)
        platforms = {'iOS 微信': (1, 0), '安卓微信': (0, 0), '安卓QQ': (0, 1), 'iOS QQ': (1, 1)}
        login_type = ttk.Combobox(actions, values=tuple(platforms), state='readonly', width=9)
        login_type.current(0)
        login_type.pack(side='left', padx=5)
        ttk.Button(actions, text='扫码登录', command=lambda: submit('account_qr', platforms[login_type.get()])).pack(side='left')

    def action(self, action, **options):
        """Send a command tagged with the exact session visible on this page."""
        if not self.ready or self.closing:
            return
        try:
            self.process.send(operation='action', action=action, epoch=self.epoch, **options)
        except RuntimeError as error:
            self.status.set(str(error))
            if action in self.switches:
                self.switches[action].set(False)

    def switch(self, name):
        """Read settings from this page and submit one of its allowed feature switches."""
        enabled = self.switches[name].get()
        options = {}
        try:
            if name == 'enabled':
                units = [unit for unit, selected in self.units.items() if selected.get()]
                if enabled and not units:
                    raise ValueError('请至少勾选一个兵种')
                options.update(units=units, training_speed=self.training_speed.get())
            elif name == 'collect_enabled' and enabled:
                options.update(options=asdict(self.collection.options()), mode=self.heroes.recovery_mode())
            elif name == 'hero_enabled':
                options.update(heroes=self.heroes.selected(), mode=self.heroes.recovery_mode())
            elif name == 'hunt_enabled' and enabled:
                options['radius'] = self.hunt.options().radius
            elif name == 'beacon_enabled':
                options['kinds'] = self.beacon.selected_types()
            self.action(name, enabled=enabled, **options)
        except (ValueError, tk.TclError) as error:
            self.switches[name].set(False)
            self.status.set(str(error))
        self.update_controls()

    def apply_event(self, event):
        """Apply current-epoch state without updating any Tk variables on the first tab."""
        if 'device_directory' in event:
            self.directory = event['device_directory']
            return
        if event.get('process_stopped'):
            self.reset_role()
            self.busy = False
            if not self.status.get().startswith('雷电连接未建立'):
                self.status.set('雷电 1 后台已退出，点「重新读取」再次连接。')
            return
        if 'process_error' in event:
            self.status.set(event['process_error'])
            return
        epoch = event['session_epoch']
        if epoch < self.epoch:
            return
        if event.get('session_reset'):
            self.epoch = epoch
            self.reset_role()
        if epoch != self.epoch:
            return
        for name in self.switches.keys() & event.keys():
            self.switches[name].set(event[name])
        if 'login_busy' in event:
            self.busy = event['login_busy']
        if 'ready' in event:
            self.ready = event['ready']
            if not self.ready and 'error' in event:
                if self.account_window is not None and self.account_window.winfo_exists():
                    self.account_window.destroy()
                self.notebook.tab(self, text='雷电 1 · 已断开')
        if 'profiles' in event:
            self.profiles = event['profiles']
        if 'account' in event:
            label = account_label(event['account'])
            self.account.set(label)
            nickname = label.removeprefix('当前角色：').split(' · ', 1)[0]
            self.notebook.tab(self, text='雷电 1 · ' + nickname if event['account'].get('logged_in') else '雷电 1 · 未登录')
        if 'account_status' in event:
            self.account.set(event['account_status'])
        if 'instance_scope' in event:
            self.scope = event['instance_scope']
            paths = role_preferences(self.directory, **self.scope)
            self.heroes.set_preferences(paths['heroes'])
            self.beacon.set_preferences(paths['beacon'])
            self.collection.set_preferences(paths['resources'])
        if 'status' in event:
            self.status.set(event['status'].splitlines()[0][:240])
        if 'collection_review_pending' in event:
            self.collection_review_pending = event['collection_review_pending']
        self.apply_task_event(event)

    def apply_task_event(self, event):
        """Render this tab's task snapshots and pass through scheduled hunt requests."""
        if 'state' in event:
            row = event['state']
            self.counts[row['soldier_id']].set(f"{owned_soldiers(row)} / {row['limit']}　训练中：{row['pending']}　编队：{row.get('deployed',0)}")
            self.stock.set(f"五分钟训练加速：{row['items']} 个")
        for key, callback in (
            ('hero_roster', self.heroes.apply_roster), ('hero_state', self.heroes.apply_state),
            ('collection_attributes_missing', self.heroes.clear_metrics), ('collection_teams', self.teams.apply_snapshot),
            ('collection_queue', self.collection.apply_queue), ('resource_coordinates', self.collection.apply_resource_coordinates),
            ('collect_use_hero_recovery', self.collection.use_hero_recovery.set), ('hunt_team', self.hunt.apply_team),
            ('hunt_snapshot', self.hunt.apply_snapshot), ('league_snapshot', self.league.apply_snapshot),
            ('beacon_snapshot', self.beacon.apply_snapshot),
            ('beacon_scout', self.beacon.apply_scout), ('report_next_ms', self.report.apply_next), ('report_snapshot', self.report.apply_snapshot),
        ):
            if key in event:
                callback(event[key])
        if 'hero_roster' in event and 'queue_used' in event['hero_roster']:
            self.collection.apply_queue(event['hero_roster'])
        if 'collection_metrics' in event:
            self.heroes.apply_metrics(event['collection_metrics'])
            self.collection.apply_metrics(event['collection_metrics'])
        if 'collection_balance' in event:
            balance = event['collection_balance']
            for key in ('stock', 'incoming', 'counts'):
                balance[key] = {int(kind): amount for kind, amount in balance[key].items()}
            self.collection.apply_balance(balance)
        if 'hunt_auto_start_epoch' in event and not self.switches['hunt_enabled'].get():
            try:
                self.action('hunt_auto_start', hunt_epoch=event['hunt_auto_start_epoch'], radius=self.hunt.options().radius)
            except (ValueError, tk.TclError) as error:
                self.hunt.status.set(str(error))
        if 'hunt_auto_next_ms' in event:
            value = event['hunt_auto_next_ms']
            self.hunt.auto_hint.set('刷新时刻自动开启；下次参考：' + display_time(value) if value is not None else '当前地图未配置刷新时刻')
        for key, label in (('hero_list_status', self.heroes.status), ('hero_status', self.heroes.status),
                           ('collection_status', self.collection.status), ('hunt_status', self.hunt.status), ('league_status', self.league.status),
                           ('hunt_auto_status', self.hunt.auto_hint), ('beacon_status', self.beacon.status), ('report_status', self.report.status)):
            if key in event:
                label.set(event[key].splitlines()[0][:240])

    def poll(self):
        """Drain a bounded batch even when the other tab is selected, keeping Tk responsive."""
        if self.closing:
            return
        try:
            for _ in range(80):
                self.apply_event(self.events.get_nowait())
        except queue.Empty:
            pass
        finally:
            self.update_controls()
            self.poll_job = self.after(100, self.poll)

    def close(self):
        """Stop this tab's worker and close role-specific editors before it is removed."""
        self.closing = True
        self.after_cancel(self.poll_job)
        self.collection.set_preferences(None)
        if self.account_window is not None and self.account_window.winfo_exists():
            self.account_window.destroy()
        self.process.close()
