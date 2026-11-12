"""Saved-list collection controls with automatic resource identification and shared recovery."""
import tkinter as tk
from tkinter import ttk

from collection import CollectionOptions, RESOURCE_NAMES
from resource_preferences import PREFERENCES_PATH, load_coordinates
from resource_list_dialog import ResourceListDialog


class CollectionPanel(ttk.LabelFrame):
    """Collect only saved coordinates, without separate resource, level or radius filters."""

    def __init__(self, parent, enabled, on_switch, on_check=None, *, preferences=PREFERENCES_PATH):
        """Build collection controls with an optional role/map-specific resource list."""
        super().__init__(parent, text='自动采集', padding=10)
        self.enabled = enabled
        self.use_hero_recovery = tk.BooleanVar(master=self, value=False)
        self.ready = False
        self.queue_snapshot = None
        self.queue_text = tk.StringVar(value='已出征 / 上限：待读取')
        self.status = tk.StringVar(value='采集关闭；录入并保存资源清单后开启。')
        self.editor = None
        self.list_summary = tk.StringVar()
        self.set_preferences(preferences)
        self.recommendation = tk.StringVar(value='按实际目标选择采集最快的可用英雄。')
        self.balance_text = tk.StringVar(value='粮木铁按1:1:1补缺；存量及预计入库将在分配时读取。')
        switch_bar = ttk.Frame(self)
        switch_bar.pack(fill='x', pady=(0, 8))
        self.toggle = ttk.Checkbutton(switch_bar, text='自动采集', variable=enabled, command=on_switch, state='disabled')
        self.toggle.pack(side='left')
        self.recovery_toggle = ttk.Checkbutton(switch_bar, text='使用英雄恢复道具', variable=self.use_hero_recovery)
        self.recovery_toggle.pack(side='left', padx=(10, 0))
        ttk.Label(switch_bar, textvariable=self.queue_text).pack(side='right')
        row = ttk.Frame(self)
        row.pack(fill='x')
        ttk.Label(row, textvariable=self.list_summary).pack(side='left', padx=(0, 20))
        self.list_button = ttk.Button(row, text='编辑资源清单', command=self.edit_list)
        self.list_button.pack(side='right')
        self.check_button = ttk.Button(row, text='立即检查', command=on_check)
        self.check_button.pack(side='right', padx=6)
        ttk.Label(self, text='直接采集清单中的点，粮木铁按1:1:1补缺。\n按存量加预计入库优先补少的，同类再选近点。',
                  wraplength=520).pack(anchor='w', pady=(8, 4))
        ttk.Label(self, textvariable=self.balance_text, wraplength=520).pack(anchor='w', pady=(0, 4))
        ttk.Label(self, text='1级有余量即可，2级至少2万，3级至少3万，4级及以上至少4万。\n按服务器阶段时间检查，不按采集速度自行估算。\n每队带2个适配兵；无固定轮询，保留被动状态通知。\n清单未缓存坐标会自动加载区域，无需滑动地图。',
                  foreground='#666666', wraplength=520).pack(anchor='w', pady=(0, 4))
        ttk.Label(self, textvariable=self.recommendation, wraplength=520).pack(anchor='w')
        ttk.Label(self, textvariable=self.status, wraplength=520).pack(anchor='w', pady=(5, 0))
        self.update_controls(False)

    def edit_list(self):
        """Open the editor only while collection is off; existing saved coordinates remain unchanged."""
        if not self.enabled.get() and self.preferences is not None:
            self.editor = ResourceListDialog(self, self.coordinates, self.list_saved, preferences=self.preferences)

    def set_preferences(self, path):
        """Close an old role's editor before reading the new role's resource list."""
        if self.editor is not None and self.editor.winfo_exists():
            self.editor.destroy()
        self.preferences = path
        try:
            coordinates = load_coordinates(path) if path is not None else ()
        except (ValueError, OSError) as error:
            coordinates = ()
            self.status.set('资源清单读取失败，请编辑检查并保存：' + str(error))
        self.apply_resource_coordinates(coordinates)

    def list_saved(self, coordinates):
        """Apply an atomically saved list to the next run without enabling collection."""
        self.coordinates = coordinates
        self.list_summary.set(f'已保存{len(coordinates)}个坐标')
        self.status.set('清单已保存；开启后按预计存量补缺，同类优先选近点。')

    def apply_balance(self, balance):
        """Display advisory income separately from current stock and count manual trips in the same cap."""
        lines = ['最近一次分配快照（预计收益仅用于分配）：']
        for kind, name in RESOURCE_NAMES.items():
            lines.append(f"{name}：存量{balance['stock'][kind]:,.0f} + 预计入库{balance['incoming'][kind]:,.0f}"
                         f"；行军/采集{balance['counts'][kind]}/{balance['same_kind_limit']}队")
        if balance['unknown']:
            lines.append('部分队伍收益未确认，本次等待。')
        self.balance_text.set('\n'.join(lines))

    def apply_resource_coordinates(self, coordinates):
        """Reflect an already-persisted server-confirmed deletion without enabling collection."""
        self.coordinates = tuple(tuple(p) for p in coordinates)
        self.list_summary.set(f'已保存{len(self.coordinates)}个坐标')

    def options(self):
        """Freeze the saved list and optional hero item use when collection starts."""
        if not self.coordinates:
            raise ValueError('请先点击“编辑资源清单”录入并保存坐标')
        return CollectionOptions(mode='list', coordinates=self.coordinates,
                                 use_hero_recovery=self.use_hero_recovery.get())

    def update_controls(self, ready):
        """Allow immediate stop while connected and freeze run options while collecting."""
        self.ready = ready
        self.toggle.state(['!disabled'] if ready else ['disabled'])
        self.list_button.state(['disabled'] if self.enabled.get() or self.preferences is None else ['!disabled'])
        self.recovery_toggle.state(['disabled'] if self.enabled.get() else ['!disabled'])
        self.check_button.state(['!disabled'] if ready and self.enabled.get() else ['disabled'])
        self.render_queue()

    def apply_queue(self, state):
        """Display server capacity and native-rule occupancy from existing snapshots only."""
        self.queue_snapshot = state
        self.render_queue()

    def render_queue(self):
        """Keep unknown counts explicit and mark disconnected values as historical."""
        state = self.queue_snapshot
        if state is None:
            self.queue_text.set('已出征 / 上限：待读取')
            return
        prefix = '已出征' if self.ready else '已出征（上次）'
        limit = state.get('queue_limit', -1)
        used = state.get('queue_used', -1)
        self.queue_text.set(f"{prefix}：{used if state.get('queue_known') and used >= 0 else '—'} / {limit if limit >= 0 else '—'} 队")

    def apply_metrics(self, metrics):
        """Reflect the item setting in reference recommendations and recheck eligibility before departure."""
        kind = RESOURCE_NAMES.get(metrics['target']['kind'], '资源')
        eligible_actions = (0, 5) if self.use_hero_recovery.get() else (0,)
        rows = [hero for hero in metrics['heroes'] if hero.get('found') and hero.get('fresh') and
                hero.get('army_known') and not hero.get('busy') and hero.get('hero_state') == 0 and
                hero.get('action_state') in eligible_actions and hero.get('speed', 0) > 0]
        if rows:
            first = min(rows, key=lambda hero: (-hero['speed'], -hero['load'], hero['travel_seconds'], hero['hero_id']))
            self.recommendation.set(f"{kind}参考首选：{first['name']}，{first['speed']}/分。实际出征前重查。")
        else:
            self.recommendation.set(f'{kind}参考点暂无可用英雄，实际出征前会重新查询。')
