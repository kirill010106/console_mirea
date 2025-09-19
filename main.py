from kivy.config import Config
Config.set('input', 'mouse', 'mouse,multitouch_on_demand')

import os
import socket
import re
import argparse
import zipfile
import calendar
import datetime
from kivy.app import App
from kivy.uix.textinput import TextInput
from kivy.core.window import Window

DEFAULT_FONT_SIZE = 16
MIN_FONT_SIZE = 8
MAX_FONT_SIZE = 40


def expand_env_vars_system(token: str) -> str:
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
                if p not in ref:
                    ref[p] = {'owner': 'user'}
                ref = ref[p]
                if not isinstance(ref, dict):
                    raise ValueError(f"Конфликт: {p} уже существует как файл")
            last = parts[-1]

            if info.is_dir():
                if last not in ref:
                    ref[last] = {'owner': 'user'}
                else:
                    if isinstance(ref[last], dict) and 'owner' not in ref[last]:
                        ref[last]['owner'] = 'user'
            else:
                content = z.read(info.filename)
                ref[last] = {'content': content, 'owner': 'user'}
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

        self.history = []
        self.history_index = None
        self.current_input = ""

        self.background_color = (0, 0, 0, 1)
        self.foreground_color = (0, 1, 0, 1)
        self.font_size = DEFAULT_FONT_SIZE
        self.font_name = 'DejaVuSansMono'

        if not self.vfs_loaded:
            warning = "Внимание! VFS не загружена. Введите команду:\nloadvfs <путь к ZIP> или exit"
            self.text += "\n" + warning
            self.cursor = self.get_cursor_from_index(len(self.text))

        if start_script and self.vfs_loaded:
            self.run_start_script(start_script)

    def _get_prompt_index(self):
        lines = self.text.splitlines()
        last_line = lines[-1] if lines else ''
        return len(self.text) - len(last_line) + len(self.prompt)

    def insert_text(self, substring, from_undo=False):
        prompt_index = self._get_prompt_index()
        if self.cursor_index() < prompt_index:
            self.cursor = self.get_cursor_from_index(prompt_index)
        return super().insert_text(substring, from_undo=from_undo)

    def do_backspace(self, from_undo=False, mode='bkspc'):
        prompt_index = self._get_prompt_index()
        if self.cursor_index() <= prompt_index:
            return
        super().do_backspace(from_undo, mode)

    def keyboard_on_key_down(self, window, keycode, text, modifiers):
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

        if keycode[1] == "left":
            prompt_index = self._get_prompt_index()
            if self.cursor_index() <= prompt_index:
                return True
        if keycode[1] == "home":
            self.cursor = self.get_cursor_from_index(self._get_prompt_index())
            return True

        return super().keyboard_on_key_down(window, keycode, text, modifiers)

    def _replace_current_line(self, text):
        lines = self.text.splitlines()
        if lines and not lines[-1]:
            lines.pop()
        lines[-1] = self.prompt + text
        self.text = "\n".join(lines) + "\n"
        self.cursor = self.get_cursor_from_index(len(self.text) - 1)

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

                self.text += "\n" + self.prompt + line
                self.cursor = self.get_cursor_from_index(len(self.text))

                try:
                    output = self.execute_command(line)
                except Exception as e:
                    output = f"Ошибка при выполнении команды: {e}"

                if output:
                    self.text += "\n" + output

            self.text += "\n" + self.prompt
            self.cursor = self.get_cursor_from_index(len(self.text))

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

    def _resolve_path_and_parent(self, target):
        if target.startswith('/'):
            path = []
            parts = target.strip('/').split('/')
        else:
            path = self.current_dir.copy()
            parts = target.split('/')

        for p in parts[:-1]:
            if p == '' or p == '.':
                continue
            elif p == '..':
                if path:
                    path.pop()
            else:
                ref = self._get_vfs_ref(path)
                if p not in ref or not isinstance(ref[p], dict):
                    raise FileNotFoundError(f"{target}: нет такого файла или каталога")
                path.append(p)

        parent_ref = self._get_vfs_ref(path)
        name = parts[-1] if parts else ''

        if not name:
            raise FileNotFoundError("Пустое имя")

        if name not in parent_ref:
            raise FileNotFoundError(f"{target}: нет такого файла или каталога")

        obj = parent_ref[name]
        return parent_ref, name, obj

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
        long_format = False
        if args and args[0] == "-s":
            use_system_env = True
            args = args[1:]
        elif args and args[0] == "-l":
            long_format = True
            args = args[1:]

        if not args:
            ref = self._get_vfs_ref()
            items = [k for k in ref.keys() if k != 'owner']
            if long_format:
                lines = []
                for item in items:
                    obj = ref[item]
                    owner = obj.get('owner', 'unknown')
                    size = len(obj.get('content', b'')) if 'content' in obj else 0
                    mode = 'd' if 'content' not in obj else '-'
                    lines.append(f"{mode}rw-r--r-- 1 {owner} {size} {item}")
                return "\n".join(lines)
            return "  ".join(items)

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
                        items = [k for k in ref.keys() if k != 'owner']
                        if long_format:
                            lines = []
                            for item in items:
                                obj = ref[item]
                                owner = obj.get('owner', 'unknown')
                                size = len(obj.get('content', b'')) if 'content' in obj else 0
                                mode = 'd' if 'content' not in obj else '-'
                                lines.append(f"{mode}rw-r--r-- 1 {owner} {size} {item}")
                            outputs.append(f"{tok}:\n" + "\n".join(lines))
                        else:
                            outputs.append(f"{tok}:\n" + ("  ".join(items) if items else ""))
                    else:
                        outputs.append(tok)
                else:
                    ref = self._get_vfs_ref()
                    if tok in ref:
                        item = ref[tok]
                        if isinstance(item, dict):
                            items = [k for k in item.keys() if k != 'owner']
                            if long_format:
                                lines = []
                                for item_name in items:
                                    obj = item[item_name]
                                    owner = obj.get('owner', 'unknown')
                                    size = len(obj.get('content', b'')) if 'content' in obj else 0
                                    mode = 'd' if 'content' not in obj else '-'
                                    lines.append(f"{mode}rw-r--r-- 1 {owner} {size} {item_name}")
                                outputs.append(f"{tok}:\n" + "\n".join(lines))
                            else:
                                outputs.append(f"{tok}:\n" + ("  ".join(items) if items else ""))
                        else:
                            if long_format:
                                owner = item.get('owner', 'unknown')
                                size = len(item.get('content', b''))
                                outputs.append(f"-rw-r--r-- 1 {owner} {size} {tok}")
                            else:
                                outputs.append(tok)
                    else:
                        raise FileNotFoundError

            except FileNotFoundError:
                outputs.append(f"ls: {tok}: нет такого файла или каталога")

        return "\n".join(outputs)
    
    def cmd_mv(self, args):
        if len(args) != 2:
            return "mv: требуется два аргумента: <источник> <назначение>"

        src, dst = args

        try:
            src_parent, src_name, src_obj = self._resolve_path_and_parent(src)
        except FileNotFoundError as e:
            return f"mv: {e}"

        # Проверим, является ли dst директорией
        dst_is_dir = False
        dst_parent = None
        dst_name = None

        if dst.startswith('/'):
            dst_path = []
            dst_parts = dst.strip('/').split('/')
        else:
            dst_path = self.current_dir.copy()
            dst_parts = dst.split('/')

        # Проходим по всем частям пути, кроме последней
        for p in dst_parts[:-1]:
            if p == '' or p == '.':
                continue
            elif p == '..':
                if dst_path:
                    dst_path.pop()
            else:
                try:
                    dst_ref = self._get_vfs_ref(dst_path)
                    if p not in dst_ref or not isinstance(dst_ref[p], dict):
                        return f"mv: невозможно создать '{dst}': нет такого каталога"
                    dst_path.append(p)
                except Exception:
                    return f"mv: невозможно создать '{dst}': нет такого каталога"

        # Теперь dst_path — путь к родительской директории
        dst_parent = self._get_vfs_ref(dst_path)
        dst_name = dst_parts[-1] if dst_parts else ''

        # Проверяем, существует ли dst_name в dst_parent
        if dst_name in dst_parent:
            dst_target = dst_parent[dst_name]
            if isinstance(dst_target, dict):
                dst_is_dir = True
            else:
                dst_is_dir = False
        else:
            dst_is_dir = False

        # Если dst — директория, и dst_name пустое или равно точке — используем имя src
        if dst_is_dir and (not dst_name or dst_name == '.'):
            dst_name = src_name

        # Если dst_name уже существует — ошибка
        if dst_name in dst_parent:
            return f"mv: '{dst}' существует"

        # Перемещаем
        dst_parent[dst_name] = src_obj
        del src_parent[src_name]

        return ""
    def cmd_chown(self, args):
        if len(args) != 2:
            return "chown: требуется два аргумента: <пользователь> <файл>"

        new_owner, target = args

        try:
            parent, name, obj = self._resolve_path_and_parent(target)
        except FileNotFoundError as e:
            return f"chown: {e}"

        if isinstance(obj, dict):
            obj['owner'] = new_owner
            return ""
        else:
            return f"chown: {target}: неверный тип объекта"

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
        elif cmd == "rev":
            if not args:
                return "rev: не указаны аргументы"
            return " ".join(arg[::-1] for arg in args)
        elif cmd == "cal":
            try:
                today = datetime.date.today()
                if not args:
                    return calendar.month(today.year, today.month)
                elif len(args) == 1:
                    year = int(args[0])
                    return calendar.calendar(year)
                elif len(args) == 2:
                    month = int(args[0])
                    year = int(args[1])
                    return calendar.month(year, month)
                else:
                    return "cal: слишком много аргументов"
            except ValueError:
                return f"cal: неверный аргумент: {args[0] if args else ''}"
            except Exception:
                return "cal: ошибка при выводе календаря"
        elif cmd == "mv":
            return self.cmd_mv(args)
        elif cmd == "chown":
            return self.cmd_chown(args)
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

    vfs = load_vfs_from_zip(args.vfs_path) if args.vfs_path else None
    TerminalApp(vfs=vfs, start_script=args.start_script).run()