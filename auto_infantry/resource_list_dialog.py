"""Edit a saved coordinate list in a separate window without growing the main control panel."""
import tkinter as tk
from tkinter import ttk

from resource_preferences import PREFERENCES_PATH, parse_coordinates, save_coordinates


class ResourceListDialog(tk.Toplevel):
    """Save a validated coordinate-only list; no game queries or spending operations exist here."""

    def __init__(self, parent, coordinates, on_saved, *, preferences=PREFERENCES_PATH):
        """Bind this editor to the resource list that was active when it opened."""
        super().__init__(parent)
        self.title('资源清单')
        self.geometry('500x420')
        self.minsize(430, 340)
        self.transient(parent.winfo_toplevel())
        self.on_saved = on_saved
        self.preferences = preferences
        body = ttk.Frame(self, padding=16)
        body.pack(fill='both', expand=True)
        ttk.Label(body, text='每行一个坐标，例如97,192。最多100点，重复坐标自动合并。', wraplength=450).pack(anchor='w')
        ttk.Label(body, text='只保存坐标；资源类型、等级和余量采集前实时查询。\n1级有余量即可，2级至少2万，3级至少3万，4级及以上至少4万。',
                  foreground='#666666', wraplength=450).pack(anchor='w', pady=(5, 10))
        editor = ttk.Frame(body)
        editor.pack(fill='both', expand=True)
        self.text = tk.Text(editor, height=10, width=30, undo=True, wrap='none')
        scroll = ttk.Scrollbar(editor, orient='vertical', command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set)
        self.text.pack(side='left', fill='both', expand=True)
        scroll.pack(side='right', fill='y')
        self.text.insert('1.0', '\n'.join(f'{x},{y}' for x, y in coordinates))
        self.message = tk.StringVar(value='未加载的坐标需要先在游戏中查看附近地图。')
        ttk.Label(body, textvariable=self.message, wraplength=450).pack(anchor='w', pady=10)
        buttons = ttk.Frame(body)
        buttons.pack(fill='x')
        ttk.Button(buttons, text='保存清单', command=self.save).pack(side='right')
        ttk.Button(buttons, text='取消', command=self.destroy).pack(side='right', padx=8)
        self.grab_set()
        self.text.focus_set()

    def save(self):
        """Keep the editor open on invalid input/write failure, and publish changes only after atomic save."""
        try:
            coordinates = save_coordinates(parse_coordinates(self.text.get('1.0', 'end-1c')), self.preferences)
        except (ValueError, OSError) as error:
            self.message.set('未保存：' + str(error))
            return
        self.on_saved(coordinates)
        self.destroy()
