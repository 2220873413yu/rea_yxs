"""Select and save the local ADB executable and primary emulator."""

from pathlib import Path
import subprocess
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from bootstrap import ADB, online_devices
from instance_config import PRIMARY_DEVICE, save_emulator_settings


class EmulatorSettingsDialog(simpledialog.Dialog):
    def body(self, parent):
        """Show the current ADB path and its online emulator instances."""
        self.adb_path = tk.StringVar(value=ADB)
        self.device = tk.StringVar(value=PRIMARY_DEVICE)
        self.status = tk.StringVar()
        self.scanned_path = None
        ttk.Label(parent, text='雷电 adb.exe').grid(row=0, column=0, sticky='w')
        ttk.Entry(parent, textvariable=self.adb_path, width=60, state='readonly').grid(row=1, column=0, sticky='ew')
        ttk.Button(parent, text='浏览…', command=self.browse).grid(row=1, column=1, padx=6)
        ttk.Label(parent, text='主雷电实例').grid(row=2, column=0, sticky='w', pady=(10, 0))
        self.devices = ttk.Combobox(parent, textvariable=self.device, state='readonly')
        self.devices.grid(row=3, column=0, sticky='w')
        ttk.Button(parent, text='刷新实例', command=self.refresh).grid(row=3, column=1, padx=6)
        ttk.Label(parent, textvariable=self.status, wraplength=430).grid(row=4, column=0, columnspan=2, sticky='w', pady=8)
        self.after_idle(self.refresh)
        return self.devices

    def browse(self):
        """Pick the ADB executable in the user's LDPlayer installation."""
        current = Path(self.adb_path.get())
        selected = filedialog.askopenfilename(parent=self, title='选择雷电安装目录中的 adb.exe',
                                              initialdir=str(current.parent) if current.parent.is_dir() else None,
                                              filetypes=[('ADB', 'adb.exe')])
        if selected:
            self.adb_path.set(selected)
            self.refresh()

    def refresh(self):
        """Refresh the device list and retain an earlier selection only if it is online."""
        path = Path(self.adb_path.get())
        devices = []
        self.scanned_path = None
        if path.name.lower() != 'adb.exe' or not path.is_absolute() or not path.is_file():
            self.status.set('请选择雷电安装目录中的 adb.exe。')
        else:
            try:
                devices = online_devices(str(path))
            except (OSError, subprocess.SubprocessError):
                self.status.set('ADB 无法列出实例。请确认选的是雷电自带的 adb.exe。')
            else:
                self.scanned_path = str(path)
                self.status.set('请选择主实例。保存后重新打开助手生效。' if devices else
                                '没有在线实例。请先启动雷电，再点击「刷新实例」。')
        self.devices.configure(values=devices)
        if self.device.get() not in devices:
            self.device.set(devices[0] if len(devices) == 1 else '')

    def validate(self):
        """Keep the dialog open if the selection or write fails."""
        if not self.scanned_path or self.device.get() not in self.devices['values']:
            self.status.set('请先选择一个在线的雷电实例。')
            return False
        try:
            save_emulator_settings(self.scanned_path, self.device.get())
        except OSError as error:
            messagebox.showerror('无法保存雷电设置', str(error), parent=self)
            return False
        self.result = True
        return True
