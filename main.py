from kivy.config import Config
Config.set('input', 'mouse', 'mouse,multitouch_on_demand')

import os
import socket
import re
import argparse
import zipfile
from kivy.app import App
from kivy.uix.textinput import TextInput
from kivy.core.window import Window

DEFAULT_FONT_SIZE = 16
MIN_FONT_SIZE = 8
MAX_FONT_SIZE = 40


def expand_env_vars_system(token: str) -> str:
    """Раскрытие переменных окружения реальной системы"""
    def replacer(match):
        var = match.group(1)
        return os.environ.get(var, match.group(0))
    return re.sub(r'\$([A-Za-z_][A-Za-z0-9_]*)', replacer, token)


def load_vfs_from_zip(zip_path):
    vfs = {}
    if not zip_path or not os.path.exists(zip_path):
        print(f"VFS не найден: {zip_path}")
        return vfs
    with zipfile.ZipFile(zip_path, 'r') as z:
        for info in z.infolist():
            parts = info.filename.strip('/').split('/')
            ref = vfs
            for p in parts[:-1]:
                ref = ref.setdefault(p, {})
            if info.is_dir():
                ref[parts[-1]] = {}
            else:
                ref[parts[-1]] = z.read(info.filename)
    return vfs


class Terminal(TextInput):
    def __init__(self, vfs=None, start_script=None, debug=False, **kwargs):
        super().__init__(**kwargs)
        self.debug = debug
        self.vfs = vfs or {}
        self.vfs_loaded = bool(vfs)
        self.current_dir = []

        self.username = os.getenv("USERNAME") or os.getenv("USER") or "user"
        self.hostname = socket.gethostname()
        self.prompt = f"{self.username}@{self.hostname}:~$ "
        self.text = self.prompt
        self.multiline = True

        # история команд
        self.history = []
        self.history_index = None
        self.current_input = ""

        # оформление
        self.background_color = (0, 0, 0, 1)
        self.foreground_color = (0, 1, 0, 1)
        self.font_size = DEFAULT_FONT_SIZE

        # предупреждение если VFS не загружена
        if not self.vfs_loaded:
            warning = "Внимание! VFS не загружена. Введите команду:\nloadvfs <путь к ZIP> или exit"
            self.text += "\n" + warning
            self.cursor = self.get_cursor_from_index(len(self.text))

        # если стартовый скрипт есть и VFS загружена
        if start_script and self.vfs_loaded:
            self.run_start_script(start_script)

    # ---------------------- вставка текста и backspace ----------------------
    def insert_text(self, substring, from_undo=False):
        if self.cursor_index() < self._get_prompt_index():
            self.cursor = self.get_cursor_from_index(len(self.text))
        return super().insert_text(substring, from_undo=from_undo)

    def do_backspace(self, from_undo=False, mode='bkspc'):
        if self.cursor_index() <= self._get_prompt_index():
            return
        super().do_backspace(from_undo, mode)

    def _get_prompt_index(self):
        """Возвращает индекс в self.text, с которого начинается ввод после приглашения"""
        lines = self.text.splitlines()
        if not lines:
            return 0
        last_line = lines[-1]
        return len(self.text) - len(last_line) + len(self.prompt)

    # ---------------------- клавиши ----------------------
    def keyboard_on_key_down(self, window, keycode, text, modifiers):
        # управление шрифтом
        if 'ctrl' in modifiers:
            if text == '+' or keycode[1] in ('plus', 'kp_plus', 'equal', '='):
                self.font_size = min(self.font_size + 1, MAX_FONT_SIZE)
                return True
            if text == '-' or keycode[1] in ('minus', 'kp_minus', '_'):
                self.font_size = max(self.font_size - 1, MIN_FONT_SIZE)
                return True
            if text == '0' or keycode[1] in ('0', 'numpad0'):
                self.font_size = DEFAULT_FONT_SIZE
                return True

        # Enter
        if keycode[1] == "enter":
            last_line = self.text.splitlines()[-1]
            command_line = last_line[len(self.prompt):].strip()
            if command_line:
                self.history.append(command_line)
            self.history_index = None
            self.current_input = ""

            output = self.execute_command(command_line)
            if output:
                self.text += "\n" + output
            self.text += "\n" + self.prompt
            self.cursor = self.get_cursor_from_index(len(self.text))
            return True

        # стрелки для истории
        if keycode[1] in ("up", "down"):
            if self.history:
                if self.history_index is None:
                    self.current_input = self.text.splitlines()[-1][len(self.prompt):]
                    self.history_index = len(self.history)
                if keycode[1] == "up":
                    self.history_index = max(0, self.history_index - 1)
                else:
                    self.history_index = min(len(self.history) - 1, self.history_index + 1)
                if 0 <= self.history_index < len(self.history):
                    line = self.history[self.history_index]
                else:
                    line = self.current_input
                self._replace_current_line(line)
            return True

        return super().keyboard_on_key_down(window, keycode, text, modifiers)

    # ---------------------- история ----------------------
    def _replace_current_line(self, text):
        lines = self.text.splitlines()
        lines[-1] = self.prompt + text
        self.text = "\n".join(lines)
        self.cursor = self.get_cursor_from_index(len(self.text))

    # ---------------------- стартовый скрипт ----------------------
    def run_start_script(self, script_path):
        if not os.path.exists(script_path):
            self.text += f"\nОшибка: стартовый скрипт не найден: {script_path}"
            self.cursor = self.get_cursor_from_index(len(self.text))
            return

        with open(script_path, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue

                # показываем команду
                self.text += "\n" + self.prompt + line
                self.cursor = self.get_cursor_from_index(len(self.text))

                try:
                    output = self.execute_command(line)
                except Exception as e:
                    output = f"Ошибка при выполнении команды: {e}"

                # показываем результат
                if output:
                    self.text += "\n" + output

            # в конце вернуть приглашение
            self.text += "\n" + self.prompt
            self.cursor = self.get_cursor_from_index(len(self.text))

    # ---------------------- VFS ----------------------
    def _get_vfs_ref(self, path=None):
        if path is None:
            path = self.current_dir
        ref = self.vfs
        for d in path:
            ref = ref[d]
        return ref

    def _resolve_path(self, target):
        if target.startswith('/'):
            path = []
            parts = target.strip('/').split('/')
        else:
            path = self.current_dir.copy()
            parts = target.split('/')
        for p in parts:
            if p == '' or p == '.':
                continue
            elif p == '..':
                if path:
                    path.pop()
            else:
                ref = self._get_vfs_ref(path)
                if p not in ref or not isinstance(ref[p], dict):
                    raise ValueError(f"cd: {p}: нет такого каталога")
                path.append(p)
        return path

    # ---------------------- команды ----------------------
    def cmd_cd(self, args):
        if not self.vfs_loaded:
            return "Ошибка: VFS не загружена. Используйте loadvfs <zip> или exit"
        if not args:
            self.current_dir = []
        else:
            try:
                self.current_dir = self._resolve_path(args[0])
            except ValueError as e:
                return str(e)
        self.update_prompt()
        return ""

    def cmd_ls(self, args):
        if not self.vfs_loaded:
            return "Ошибка: VFS не загружена. Используйте loadvfs <zip> или exit"

        use_system_env = False
        if args and args[0] == "-s":
            use_system_env = True
            args = args[1:]

        if not args:
            ref = self._get_vfs_ref()
            return "  ".join(ref.keys())

        outputs = []
        for tok in args:
            if use_system_env:
                tok = expand_env_vars_system(tok)

            try:
                if tok.startswith('/'):
                    parts = [p for p in tok.strip('/').split('/') if p]
                    ref = self.vfs
                    for p in parts:
                        if isinstance(ref, dict) and p in ref:
                            ref = ref[p]
                        else:
                            raise FileNotFoundError
                    if isinstance(ref, dict):
                        outputs.append(f"{tok}:\n" + ("  ".join(ref.keys()) if ref else ""))
                    else:
                        outputs.append(tok)
                else:
                    ref = self._get_vfs_ref()
                    if tok in ref:
                        if isinstance(ref[tok], dict):
                            outputs.append(f"{tok}:\n" + ("  ".join(ref[tok].keys()) if ref[tok] else ""))
                        else:
                            outputs.append(tok)
                    else:
                        raise FileNotFoundError

            except FileNotFoundError:
                outputs.append(f"ls: {tok}: нет такого файла или каталога")

        return "\n".join(outputs)

    def update_prompt(self):
        path_str = '/' + '/'.join(self.current_dir) if self.current_dir else '~'
        self.prompt = f"{self.username}@{self.hostname}:{path_str}$ "
        self.cursor = self.get_cursor_from_index(len(self.text))

    def execute_command(self, command_line: str) -> str:
        if not command_line.strip():
            return ""

        parts = command_line.strip().split()
        cmd, *args = parts

        if cmd == "exit":
            App.get_running_app().stop()
            return ""
        if cmd == "loadvfs":
            if not args:
                return "Укажите путь к VFS ZIP"
            zip_path = args[0]
            if not os.path.exists(zip_path):
                return f"VFS не найден: {zip_path}"
            self.vfs = load_vfs_from_zip(zip_path)
            self.vfs_loaded = True
            self.current_dir = []
            self.update_prompt()
            return f"VFS загружена из {zip_path}"

        if not self.vfs_loaded:
            return "Ошибка: VFS не загружена. Введите loadvfs <путь> или exit"

        if cmd == "ls":
            return self.cmd_ls(args)
        elif cmd == "cd":
            return self.cmd_cd(args)
        else:
            return f"Команда не найдена: {cmd}"


class TerminalApp(App):
    def __init__(self, vfs=None, start_script=None, **kwargs):
        self.vfs = vfs
        self.start_script = start_script
        super().__init__(**kwargs)

    def build(self):
        return Terminal(vfs=self.vfs, start_script=self.start_script)

    def on_start(self):
        username = os.getenv("USERNAME") or os.getenv("USER") or "user"
        hostname = socket.gethostname()
        Window.set_title(f"Эмулятор - [{username}@{hostname}]")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--vfs-path', type=str, default=None, help='Путь к ZIP VFS')
    parser.add_argument('--start-script', type=str, default=None, help='Путь к стартовому скрипту')
    args = parser.parse_args()

    print("DEBUG: параметры запуска:", args)

    vfs = load_vfs_from_zip(args.vfs_path) if args.vfs_path else None
    TerminalApp(vfs=vfs, start_script=args.start_script).run()
