from kivy.config import Config
Config.set('input', 'mouse', 'mouse,multitouch_on_demand')

import os
import socket
import re
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


class Terminal(TextInput):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
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
        lines[-1] = self.prompt + text
        self.text = "\n".join(lines)
        self.cursor = self.get_cursor_from_index(len(self.prompt + text))

    def execute_command(self, command_line: str) -> str:
        if not command_line.strip():
            return ""
        parts = command_line.strip().split()
        cmd = parts[0] if parts else ""
        if cmd == "exit":
            App.get_running_app().stop()
            return ""
        if cmd == "ls" or cmd == "cd":
            return command_line
        expanded = expand_env_vars_system(command_line)
        if expanded != command_line:
            return expanded
        return f"Команда не найдена: {cmd}"


class TerminalApp(App):
    def build(self):
        return Terminal()

    def on_start(self):
        username = os.getenv("USERNAME") or os.getenv("USER") or "user"
        hostname = socket.gethostname()
        Window.set_title(f"Эмулятор - [{username}@{hostname}]")


if __name__ == "__main__":
    TerminalApp().run()