#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MURNET CLI v5.1 - INTERACTIVE SHELL
Полноценная командная оболочка для управления Murnet узлом
Запускает узел и предоставляет интерактивный доступ к нему
"""

import argparse
import sys
import os
import signal
import json
import time
import threading
import queue
import cmd
import shlex
from pathlib import Path
from typing import Optional, Dict, List, Any, Callable
from dataclasses import dataclass, field
from datetime import datetime

# Добавляем путь к модулям
sys.path.insert(0, str(Path(__file__).parent))

# Core imports
from core.node import MurnetNode
from core.config import MurnetConfig, get_config, set_config
from api.server import MurnetAPIServer
from core.crypto import Identity
from core.storage import Storage

# Optional UI libs
try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.tree import Tree
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from rich import box
    from rich.text import Text
    from rich.syntax import Syntax
    from rich.live import Live
    from rich.layout import Layout
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.completion import Completer, Completion
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.shortcuts import confirm
    HAS_PROMPT_TOOLKIT = True
    
    # Определяем Completer только если prompt_toolkit доступен
    class MurnetCompleter(Completer):
        """Автодополнение команд"""
        
        COMMANDS = [
            'help', 'quit', 'exit', 'status', 'peers', 'connect', 'disconnect',
            'send', 'chat', 'broadcast', 'dht', 'routes', 'storage', 'config',
            'identity', 'logs', 'clear', 'shell', 'restart', 'stop', 'start',
            'api', 'debug', 'export', 'import_key'
        ]
        
        def __init__(self, cli):
            self.cli = cli
        
        def get_completions(self, document, complete_event):
            text = document.text_before_cursor
            words = text.split()
            
            if not words or (len(words) == 1 and not text.endswith(' ')):
                # Дополняем команды
                for cmd in self.COMMANDS:
                    if cmd.startswith(text.lower()):
                        yield Completion(cmd, start_position=-len(text))
            else:
                cmd = words[0].lower()
                
                if cmd in ['connect', 'disconnect'] and len(words) <= 2:
                    # Дополняем адресами пиров
                    if self.cli.node and self.cli.node.transport:
                        for peer in self.cli.node.transport.get_peers():
                            addr = peer.get('address', '')
                            if addr and addr.startswith(words[-1] if len(words) > 1 else ''):
                                yield Completion(addr, start_position=-len(words[-1]) if len(words) > 1 else 0)
                
                elif cmd == 'send' and len(words) == 2:
                    # Дополняем контактами
                    contacts = self.cli._get_contacts()
                    for contact in contacts:
                        if contact.startswith(words[-1]):
                            yield Completion(contact, start_position=-len(words[-1]))
                
                elif cmd == 'chat' and len(words) == 2:
                    contacts = self.cli._get_contacts()
                    for contact in contacts:
                        if contact.startswith(words[-1]):
                            yield Completion(contact, start_position=-len(words[-1]))
    
except ImportError:
    HAS_PROMPT_TOOLKIT = False
    MurnetCompleter = None  # Заглушка


class MurnetInteractiveShell(cmd.Cmd):
    """
    Интерактивная оболочка для управления Murnet узлом
    """
    
    intro = None  # Устанавливается динамически
    prompt = "murnet> "
    
    def __init__(self, cli):
        super().__init__()
        self.cli = cli
        self.node = cli.node
        self.console = cli.console
        self._update_prompt()
        
        # История команд
        if HAS_PROMPT_TOOLKIT:
            history_path = Path.home() / '.murnet_history'
            self.session = PromptSession(
                history=FileHistory(str(history_path)),
                completer=MurnetCompleter(cli),
                auto_suggest=AutoSuggestFromHistory()
            )
    
    def _update_prompt(self):
        """Обновление приглашения с информацией о статусе"""
        if self.node and self.node.transport:
            peer_count = len(self.node.transport.get_peers())
            status = "🟢" if self.node.running else "🔴"
            self.prompt = f"{status} [{peer_count}] murnet> "
        else:
            self.prompt = "🔴 [?] murnet> "
    
    def preloop(self):
        """Перед запуском цикла"""
        self._show_banner()
        self._print_status()
    
    def precmd(self, line):
        """Перед выполнением команды"""
        self._update_prompt()
        return line.strip()
    
    def postcmd(self, stop, line):
        """После выполнения команды"""
        self._update_prompt()
        return stop
    
    def emptyline(self):
        """Пустая строка - обновляем статус"""
        self._print_status()
    
    def default(self, line):
        """Неизвестная команда"""
        if self.console:
            self.console.print(f"[red]Неизвестная команда: {line}[/red]")
            self.console.print("[dim]Введите 'help' для списка команд[/dim]")
        else:
            print(f"Неизвестная команда: {line}")
    
    def do_help(self, arg):
        """Показать справку: help [команда]"""
        if arg:
            # Справка по конкретной команде
            super().do_help(arg)
        else:
            self._show_help()
    
    def do_quit(self, arg):
        """Выйти из оболочки и остановить узел"""
        return self._do_exit()
    
    def do_exit(self, arg):
        """Выйти из оболочки и остановить узел"""
        return self._do_exit()
    
    def _do_exit(self):
        """Выход с подтверждением"""
        if HAS_PROMPT_TOOLKIT:
            try:
                if confirm("Остановить узел и выйти?"):
                    self.cli._shutdown()
                    return True
            except:
                self.cli._shutdown()
                return True
        else:
            self.cli._shutdown()
            return True
        return False
    
    def do_status(self, arg):
        """Показать полный статус узла"""
        if not self._check_node():
            return
        
        try:
            status = self.node.get_status()
            storage_stats = self.node.storage.get_stats() if self.node.storage else {}
            
            if self.console:
                # Создаем красивую таблицу
                grid = Table.grid(expand=True)
                grid.add_column(style="cyan")
                grid.add_column(style="white")
                grid.add_column(style="cyan")
                grid.add_column(style="white")
                
                uptime = status.get('stats', {}).get('uptime', 0)
                hours, rem = divmod(int(uptime), 3600)
                minutes, seconds = divmod(rem, 60)
                
                grid.add_row(
                    "📍 Адрес:", self.node.address[:40],
                    "⏱️  Аптайм:", f"{hours:02d}:{minutes:02d}:{seconds:02d}"
                )
                grid.add_row(
                    "🌐 Пиров:", str(len(self.node.transport.get_peers())),
                    "📨 Сообщений:", str(storage_stats.get('messages', 0))
                )
                grid.add_row(
                    "📬 Непрочитанных:", str(storage_stats.get('messages_unread', 0)),
                    "🗄️  DHT записей:", str(status.get('dht_entries', 0))
                )
                grid.add_row(
                    "💾 Размер БД:", f"{storage_stats.get('db_size_mb', 0):.2f} MB",
                    "🔐 E2E сессий:", str(status.get('security', {}).get('e2e_ready', 0))
                )
                
                self.console.print(Panel(grid, title="[bold green]Статус узла[/bold green]", border_style="green"))
            else:
                print(f"Адрес: {self.node.address}")
                print(f"Пиры: {len(self.node.transport.get_peers())}")
                print(f"Сообщений: {storage_stats.get('messages', 0)}")
                
        except Exception as e:
            self._error(f"Ошибка получения статуса: {e}")
    
    def do_peers(self, arg):
        """Управление пирами: peers [list|drop <addr>]"""
        if not self._check_node():
            return
        
        args = shlex.split(arg) if arg else ['list']
        cmd = args[0] if args else 'list'
        
        if cmd == 'list':
            self._show_peers()
        elif cmd == 'drop' and len(args) > 1:
            self._drop_peer(args[1])
        else:
            self._show_peers()
    
    def _show_peers(self):
        """Показать список пиров"""
        peers = self.node.transport.get_peers()
        
        if not peers:
            self._info("Нет подключенных пиров")
            return
        
        if self.console:
            table = Table(
                show_header=True, header_style="bold cyan",
                box=box.ROUNDED, expand=True
            )
            table.add_column("#", width=4, justify="right")
            table.add_column("Адрес", style="cyan")
            table.add_column("IP:Port", style="white")
            table.add_column("RTT", justify="right", style="green")
            table.add_column("Статус", justify="center")
            table.add_column("Рукопожатие", justify="center")
            
            for i, peer in enumerate(peers, 1):
                rtt = f"{peer.get('rtt', 0)*1000:.1f}ms" if peer.get('rtt') else "N/A"
                status = "🟢" if peer.get('is_active') else "🔴"
                auth = "🔒" if peer.get('handshake_complete') else "🔓"
                
                table.add_row(
                    str(i),
                    peer.get('address', 'Unknown')[:30],
                    f"{peer.get('ip')}:{peer.get('port')}",
                    rtt,
                    status,
                    auth
                )
            
            self.console.print(table)
            self.console.print(f"\n[dim]Всего пиров: {len(peers)}[/dim]")
        else:
            print(f"\nПиры ({len(peers)}):")
            for i, peer in enumerate(peers, 1):
                status = "🟢" if peer.get('is_active') else "🔴"
                print(f"  {i}. {status} {peer['address'][:30]}... @ {peer['ip']}:{peer['port']}")
    
    def _drop_peer(self, addr_or_idx):
        """Отключить пира"""
        peers = self.node.transport.get_peers()
        
        # Пробуем как индекс
        try:
            idx = int(addr_or_idx) - 1
            if 0 <= idx < len(peers):
                addr = peers[idx]['address']
            else:
                self._error(f"Неверный номер пира: {addr_or_idx}")
                return
        except ValueError:
            addr = addr_or_idx
        
        # Отключаем
        success = self.node.transport.disconnect_peer(addr)
        if success:
            self._success(f"Пир {addr[:20]}... отключен")
        else:
            self._error(f"Не удалось отключить пира {addr[:20]}...")
    
    def do_connect(self, arg):
        """Подключиться к пиру: connect <ip:port>"""
        if not self._check_node():
            return
        
        if not arg:
            self._error("Укажите адрес: connect <ip:port>")
            return
        
        try:
            if ':' in arg:
                ip, port_str = arg.rsplit(':', 1)
                port = int(port_str)
            else:
                ip = arg
                port = 8888
            
            self._info(f"Подключение к {ip}:{port}...")
            
            success = self.node.transport.connect_to(ip, port)
            
            if success:
                self._success(f"Подключено к {ip}:{port}")
            else:
                self._error(f"Не удалось подключиться к {ip}:{port}")
                
        except Exception as e:
            self._error(f"Ошибка подключения: {e}")
    
    def do_send(self, arg):
        """Отправить сообщение: send <адрес> <сообщение>"""
        if not self._check_node():
            return
        
        args = shlex.split(arg)
        if len(args) < 2:
            self._error("Использование: send <адрес> <сообщение>")
            return
        
        to_addr = args[0]
        message = ' '.join(args[1:])
        
        try:
            msg_id = self.node.send_message(to_addr, message)
            if msg_id:
                self._success(f"Отправлено! ID: {msg_id[:16]}...")
            else:
                self._error("Не удалось отправить сообщение")
        except Exception as e:
            self._error(f"Ошибка отправки: {e}")
    
    def do_chat(self, arg):
        """Интерактивный чат с контактом: chat <адрес>"""
        if not self._check_node():
            return
        
        if not arg:
            # Показываем список контактов
            contacts = self.cli._get_contacts()
            if not contacts:
                self._info("Нет контактов. Используйте: chat <адрес>")
                return
            
            if self.console:
                self.console.print("[cyan]Доступные контакты:[/cyan]")
                for i, contact in enumerate(contacts[:10], 1):
                    self.console.print(f"  {i}. {contact[:40]}...")
                self.console.print(f"\n[dim]Введите: chat <номер или адрес>[/dim]")
            else:
                print("Контакты:")
                for i, contact in enumerate(contacts[:10], 1):
                    print(f"  {i}. {contact[:40]}...")
            return
        
        # Определяем адрес (может быть номером из списка)
        try:
            idx = int(arg) - 1
            contacts = self.cli._get_contacts()
            if 0 <= idx < len(contacts):
                addr = contacts[idx]
            else:
                addr = arg
        except ValueError:
            addr = arg
        
        self._start_interactive_chat(addr)
    
    def _start_interactive_chat(self, addr):
        """Интерактивный режим чата"""
        if self.console:
            self.console.print(f"\n[bold cyan]💬 Чат с {addr[:40]}...[/bold cyan]")
            self.console.print("[dim]Введите сообщение (пустая строка для выхода)[/dim]\n")
        else:
            print(f"\n--- Чат с {addr[:40]}... ---")
        
        # Показываем историю
        self._show_chat_history(addr)
        
        while True:
            try:
                if HAS_PROMPT_TOOLKIT and hasattr(self, 'session'):
                    message = self.session.prompt("> ", multiline=False)
                else:
                    message = input("> ")
                
                if not message.strip():
                    break
                
                msg_id = self.node.send_message(addr, message.strip())
                if msg_id:
                    if self.console:
                        self.console.print(f"[dim]✓ Отправлено[/dim]")
                    else:
                        print("  ✓ Отправлено")
                else:
                    self._error("Ошибка отправки")
                    
            except (KeyboardInterrupt, EOFError):
                break
        
        if self.console:
            self.console.print(f"[dim]--- Чат завершен ---[/dim]\n")
        else:
            print("---\n")
    
    def _show_chat_history(self, addr, limit=10):
        """Показать историю переписки"""
        if not self.node or not self.node.storage:
            return
        
        messages = self.node.storage.get_messages(self.node.address, limit=100)
        chat_msgs = [m for m in messages 
                    if m.get('from') == addr or m.get('to') == addr]
        chat_msgs = sorted(chat_msgs, key=lambda x: x.get('timestamp', 0))[-limit:]
        
        if self.console and chat_msgs:
            self.console.print("[dim]История:[/dim]")
        
        for msg in chat_msgs:
            is_me = msg.get('from') == self.node.address
            ts = datetime.fromtimestamp(msg.get('timestamp', 0)).strftime('%H:%M')
            content = msg.get('content', '')
            
            if self.console:
                color = "green" if is_me else "blue"
                prefix = "Вы" if is_me else msg.get('from', 'Unknown')[:8]
                self.console.print(f"  [{color}]{ts} {prefix}:[/{color}] {content}")
            else:
                prefix = ">>" if is_me else "<<"
                print(f"  {prefix} [{ts}] {content}")
    
    def do_broadcast(self, arg):
        """Широковещательная рассылка: broadcast <сообщение>"""
        if not self._check_node():
            return
        
        if not arg:
            self._error("Введите сообщение: broadcast <текст>")
            return
        
        try:
            sent = self.node.transport.broadcast({
                'type': 'broadcast',
                'text': arg,
                'from': self.node.address,
                'timestamp': time.time()
            })
            self._success(f"Рассылка выполнена: {sent} пиров")
        except Exception as e:
            self._error(f"Ошибка рассылки: {e}")
    
    def do_dht(self, arg):
        """Управление DHT: dht [get <key>|put <key> <value>|stats]"""
        if not self._check_node():
            return
        
        args = shlex.split(arg) if arg else ['stats']
        cmd = args[0] if args else 'stats'
        
        try:
            if cmd == 'stats':
                stats = self.node.murnaked.get_stats() if hasattr(self.node, 'murnaked') else {}
                if self.console:
                    table = Table(show_header=False, box=box.SIMPLE)
                    table.add_column(style="cyan")
                    table.add_column(style="white")
                    
                    for key, value in stats.items():
                        table.add_row(key, str(value))
                    self.console.print(Panel(table, title="DHT Статистика"))
                else:
                    print("DHT Stats:", stats)
                    
            elif cmd == 'get' and len(args) > 1:
                key = args[1]
                value = self.node.murnaked.get(key) if hasattr(self.node, 'murnaked') else None
                if value:
                    self._success(f"{key} = {value}")
                else:
                    self._info(f"Ключ {key} не найден")
                    
            elif cmd == 'put' and len(args) > 2:
                key, value = args[1], args[2]
                success = self.node.murnaked.put(key, value) if hasattr(self.node, 'murnaked') else False
                if success:
                    self._success(f"Сохранено: {key}")
                else:
                    self._error("Не удалось сохранить")
            else:
                self._info("Использование: dht [stats|get <key>|put <key> <value>]")
                
        except Exception as e:
            self._error(f"Ошибка DHT: {e}")
    
    def do_routes(self, arg):
        """Показать таблицу маршрутизации"""
        if not self._check_node():
            return
        
        try:
            routes = self.node.routing.get_all_routes() if hasattr(self.node, 'routing') else {}
            
            if not routes:
                self._info("Таблица маршрутизации пуста")
                return
            
            if self.console:
                table = Table(
                    show_header=True, header_style="bold cyan",
                    box=box.ROUNDED, expand=True
                )
                table.add_column("Назначение", style="cyan")
                table.add_column("Следующий узел", style="white")
                table.add_column("Стоимость", justify="right", style="green")
                table.add_column("Хопов", justify="center")
                
                for dest, info in list(routes.items())[:20]:
                    table.add_row(
                        dest[:35],
                        info.get('next_hop', 'Unknown')[:30],
                        f"{info.get('cost', 0):.2f}",
                        str(info.get('hop_count', '?'))
                    )
                
                self.console.print(table)
                self.console.print(f"\n[dim]Всего маршрутов: {len(routes)}[/dim]")
            else:
                print(f"\nМаршруты ({len(routes)}):")
                for dest, info in routes.items():
                    print(f"  {dest[:30]}... -> {info.get('next_hop', 'Unknown')[:20]}... "
                          f"(cost: {info.get('cost', 0):.2f})")
                      
        except Exception as e:
            self._error(f"Ошибка: {e}")
    
    def do_storage(self, arg):
        """Управление хранилищем: storage [stats|clean|export]"""
        if not self._check_node() or not self.node.storage:
            return
        
        args = shlex.split(arg) if arg else ['stats']
        cmd = args[0] if args else 'stats'
        
        try:
            if cmd == 'stats':
                stats = self.node.storage.get_stats()
                if self.console:
                    table = Table(show_header=False, box=box.SIMPLE)
                    table.add_column(style="cyan")
                    table.add_column(style="white")
                    for k, v in stats.items():
                        table.add_row(k, str(v))
                    self.console.print(Panel(table, title="Storage Stats"))
                else:
                    print("Storage:", stats)
                    
            elif cmd == 'clean':
                # Очистка старых сообщений
                deleted = self.node.storage.clean_old_messages(days=30)
                self._success(f"Удалено старых сообщений: {deleted}")
                
            elif cmd == 'export':
                path = args[1] if len(args) > 1 else f"murnet_export_{int(time.time())}.json"
                data = self.node.storage.export_all()
                with open(path, 'w') as f:
                    json.dump(data, f, indent=2)
                self._success(f"Экспортировано в {path}")
            else:
                self._info("Использование: storage [stats|clean|export <path>]")
                
        except Exception as e:
            self._error(f"Ошибка: {e}")
    
    def do_identity(self, arg):
        """Управление идентификацией: identity [show|export|import]"""
        if not self._check_node():
            return
        
        args = shlex.split(arg) if arg else ['show']
        cmd = args[0] if args else 'show'
        
        try:
            if cmd == 'show':
                if self.console:
                    self.console.print(f"[cyan]Адрес:[/cyan] {self.node.address}")
                    self.console.print(f"[cyan]Публичный ключ:[/cyan] {self.node.identity.public_key.hex()[:64]}...")
                else:
                    print(f"Адрес: {self.node.address}")
                    
            elif cmd == 'export':
                path = args[1] if len(args) > 1 else "identity_backup.json"
                # Экспорт ключей (зашифрованный)
                self._info("Функция экспорта ключей...")
                
            elif cmd == 'import':
                self._error("Импорт возможен только при запуске узла")
            else:
                self._info("Использование: identity [show|export]")
                
        except Exception as e:
            self._error(f"Ошибка: {e}")
    
    def do_config(self, arg):
        """Показать/изменить конфигурацию: config [show|set <key> <value>]"""
        args = shlex.split(arg) if arg else ['show']
        cmd = args[0] if args else 'show'
        
        if cmd == 'show':
            config_dict = self.cli.config.to_dict() if hasattr(self.cli.config, 'to_dict') else {}
            if self.console:
                self.console.print(Syntax(json.dumps(config_dict, indent=2), "json"))
            else:
                print(json.dumps(config_dict, indent=2))
        else:
            self._info("Динамическое изменение конфига пока не поддерживается")
    
    def do_logs(self, arg):
        """Показать последние логи: logs [lines]"""
        lines = int(arg) if arg.isdigit() else 20
        
        # Здесь можно добавить чтение из файла логов
        self._info("Логи системы...")
        # TODO: implement log reading
    
    def do_clear(self, arg):
        """Очистить экран"""
        if self.console:
            self.console.clear()
        else:
            os.system('clear' if os.name != 'nt' else 'cls')
    
    def do_shell(self, arg):
        """Выполнить shell команду: shell <команда>"""
        if arg:
            os.system(arg)
        else:
            self._info("Использование: shell <команда>")
    
    def do_restart(self, arg):
        """Перезапустить узел"""
        self._info("Перезапуск узла...")
        self.cli._restart_node()
        self.node = self.cli.node
        self._success("Узел перезапущен")
    
    def do_stop(self, arg):
        """Остановить узел (без выхода)"""
        if self.node and self.node.running:
            self.node.stop()
            self._success("Узел остановлен")
        else:
            self._info("Узел уже остановлен")
    
    def do_start(self, arg):
        """Запустить узел (если остановлен)"""
        if not self.node or not self.node.running:
            self.cli._start_node()
            self.node = self.cli.node
            self._success("Узел запущен")
        else:
            self._info("Узел уже работает")
    
    def do_api(self, arg):
        """Управление API сервером: api [start|stop|status]"""
        args = shlex.split(arg) if arg else ['status']
        cmd = args[0] if args else 'status'
        
        if cmd == 'status':
            status = "🟢 Работает" if self.cli.api_server else "🔴 Остановлен"
            self._info(f"API сервер: {status}")
        elif cmd == 'start':
            self.cli._start_api()
            self._success("API сервер запущен")
        elif cmd == 'stop':
            self.cli._stop_api()
            self._success("API сервер остановлен")
    
    def do_debug(self, arg):
        """Отладочная информация"""
        if not self._check_node():
            return
        
        debug_info = {
            'node_running': self.node.running,
            'transport_peers': len(self.node.transport.get_peers()) if self.node.transport else 0,
            'storage_ready': self.node.storage is not None,
            'address': self.node.address,
            'threads': threading.active_count(),
        }
        
        if self.console:
            self.console.print(Syntax(json.dumps(debug_info, indent=2), "json"))
        else:
            print(json.dumps(debug_info, indent=2))
    
    def _check_node(self):
        """Проверка, что узел запущен"""
        if not self.node or not self.node.running:
            self._error("Узел не запущен. Используйте 'start'")
            return False
        return True
    
    def _show_banner(self):
        """Показать баннер"""
        if self.console:
            banner = """
[bold cyan]
╔══════════════════════════════════════════════════════════════╗
║                    🌐  M U R N E T   v 5 . 1                 ║
║                                                              ║
║              Интерактивная командная оболочка                ║
╚══════════════════════════════════════════════════════════════╝
[/bold cyan]
            """
            self.console.print(banner)
        else:
            print("\n=== MURNET v5.1 ===\n")
    
    def _show_help(self):
        """Показать справку"""
        help_text = """
[bold cyan]Основные команды:[/bold cyan]
  [green]status[/green]              - Статус узла
  [green]peers[/green] [list|drop]     - Список пиров или отключение
  [green]connect[/green] <ip:port>   - Подключиться к пиру
  [green]send[/green] <addr> <msg>  - Отправить сообщение
  [green]chat[/green] [addr]         - Интерактивный чат
  [green]broadcast[/green] <msg>    - Широковещательная рассылка

[bold cyan]Сеть и хранилище:[/bold cyan]
  [green]routes[/green]              - Таблица маршрутизации
  [green]dht[/green] [stats|get|put] - Управление DHT
  [green]storage[/green] [stats|...] - Управление хранилищем

[bold cyan]Управление:[/bold cyan]
  [green]identity[/green] [show]     - Информация об идентификации
  [green]config[/green] [show]       - Конфигурация
  [green]start[/green], [green]stop[/green], [green]restart[/green] - Управление узлом
  [green]api[/green] [start|stop]    - Управление API
  [green]clear[/green]               - Очистить экран
  [green]quit[/green], [green]exit[/green]          - Выйти и остановить узел

[dim]Для подробной справки: help <команда>[/dim]
        """
        if self.console:
            self.console.print(help_text)
        else:
            print(help_text)
    
    def _print_status(self):
        """Печать краткого статуса"""
        if self.node and self.node.running:
            peers = len(self.node.transport.get_peers()) if self.node.transport else 0
            self._info(f"Узел активен | Пиры: {peers} | Адрес: {self.node.address[:20]}...")
    
    def _success(self, msg):
        if self.console:
            self.console.print(f"[green]✓ {msg}[/green]")
        else:
            print(f"✓ {msg}")
    
    def _error(self, msg):
        if self.console:
            self.console.print(f"[red]✗ {msg}[/red]")
        else:
            print(f"✗ {msg}")
    
    def _info(self, msg):
        if self.console:
            self.console.print(f"[cyan]ℹ {msg}[/cyan]")
        else:
            print(f"ℹ {msg}")


class MurnetCLI:
    """
    Главный класс CLI приложения
    """
    
    def __init__(self):
        self.node: Optional[MurnetNode] = None
        self.api_server: Optional[MurnetAPIServer] = None
        self.config: Optional[MurnetConfig] = None
        self.console = Console() if HAS_RICH else None
        self.args = None
        
        # Graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """Обработчик сигналов"""
        if self.console:
            self.console.print("\n[yellow]Получен сигнал завершения...[/yellow]")
        self._shutdown()
        sys.exit(0)
    
    def run(self):
        """Главная точка входа"""
        parser = self._create_parser()
        self.args = parser.parse_args()
        
        # Загрузка конфигурации
        self._load_config()
        
        # Обработка команд
        if self.args.command is None:
            self._run_interactive()
        else:
            self._run_single_command()
    
    def _create_parser(self) -> argparse.ArgumentParser:
        """Создание парсера аргументов"""
        parser = argparse.ArgumentParser(
            description="🌐 Murnet v6.0 - Децентрализованная P2P сеть",
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog="""
Примеры:
  %(prog)s                           # Интерактивная оболочка
  %(prog)s --daemon                  # Фоновый режим
  %(prog)s send <addr> "привет"      # Однократная команда
            """
        )
        
        parser.add_argument("--config", "-c", help="Путь к конфигу")
        parser.add_argument("--data-dir", "-d", default="./data", help="Директория данных")
        parser.add_argument("--profile", choices=["mobile", "vds", "desktop"],
                           help="Профиль конфигурации")
        parser.add_argument("--port", "-p", type=int, default=8888, help="P2P порт")
        parser.add_argument("--api-port", type=int, default=8080, help="API порт")
        parser.add_argument("--no-api", action="store_true", help="Без API сервера")
        parser.add_argument("--daemon", action="store_true", help="Фоновый режим")
        
        subparsers = parser.add_subparsers(dest="command", help="Команды")
        
        # Send
        send_parser = subparsers.add_parser("send", help="Отправить сообщение")
        send_parser.add_argument("to", help="Адрес получателя")
        send_parser.add_argument("message", nargs="+", help="Текст сообщения")
        
        # Status
        subparsers.add_parser("status", help="Статус узла")
        
        # Peers
        peers_parser = subparsers.add_parser("peers", help="Управление пирами")
        peers_parser.add_argument("--connect", metavar="IP:PORT", help="Подключиться к пиру")
        peers_parser.add_argument("--list", "-l", action="store_true", help="Список пиров")
        
        return parser
    
    def _load_config(self):
        """Загрузка конфигурации"""
        if self.args.config:
            self.config = MurnetConfig.from_file(self.args.config)
        else:
            self.config = get_config()
        
        if self.args.profile:
            self.config.apply_profile(self.args.profile)
        
        set_config(self.config)
    
    def _run_interactive(self):
        """Запуск интерактивной оболочки"""
        # Запускаем узел
        if not self._start_node():
            return
        
        # Запускаем API если нужно
        if not self.args.no_api:
            self._start_api()
        
        # Запускаем оболочку
        try:
            shell = MurnetInteractiveShell(self)
            if HAS_PROMPT_TOOLKIT:
                # Используем prompt_toolkit для улучшенного ввода
                while True:
                    try:
                        shell._update_prompt()
                        text = shell.session.prompt(shell.prompt)
                        if text.strip():
                            shell.onecmd(text)
                    except KeyboardInterrupt:
                        continue
                    except EOFError:
                        break
            else:
                shell.cmdloop()
        except Exception as e:
            if self.console:
                self.console.print(f"[red]Ошибка: {e}[/red]")
        finally:
            self._shutdown()
    
    def _run_single_command(self):
        """Выполнение одиночной команды"""
        # Запускаем узел временно
        if not self._start_node():
            return
        
        try:
            handler = getattr(self, f'_cmd_{self.args.command}', None)
            if handler:
                handler(self.args)
            else:
                print(f"Неизвестная команда: {self.args.command}")
        finally:
            self._shutdown()
    
    def _start_node(self) -> bool:
        """Запуск узла"""
        try:
            if self.console:
                with Progress(
                    SpinnerColumn(),
                    TextColumn("[progress.description]{task.description}"),
                    console=self.console,
                    transient=True
                ) as progress:
                    
                    task = progress.add_task("[cyan]Запуск узла...", total=None)
                    
                    self.node = MurnetNode(
                        data_dir=self.args.data_dir,
                        port=self.args.port
                    )
                    self.node.start()
                    
                    progress.update(task, description="[green]✓ Узел запущен")
                    time.sleep(0.5)
            else:
                print("Запуск узла...")
                self.node = MurnetNode(
                    data_dir=self.args.data_dir,
                    port=self.args.port
                )
                self.node.start()
                print(f"✓ Узел запущен: {self.node.address}")
            
            return True
            
        except Exception as e:
            if self.console:
                self.console.print(f"[red]✗ Ошибка запуска: {e}[/red]")
            else:
                print(f"✗ Ошибка запуска: {e}")
            return False
    
    def _restart_node(self):
        """Перезапуск узла"""
        self._shutdown_node()
        time.sleep(1)
        self._start_node()
    
    def _start_api(self):
        """Запуск API сервера"""
        if not self.node or not self.node.running:
            return False
        
        try:
            self.api_server = MurnetAPIServer(
                self.node,
                host=self.config.api.host if hasattr(self.config, 'api') else '127.0.0.1',
                port=self.args.api_port
            )
            self.api_thread = threading.Thread(target=self.api_server.run, daemon=True)
            self.api_thread.start()
            return True
        except Exception as e:
            if self.console:
                self.console.print(f"[yellow]⚠ Не удалось запустить API: {e}[/yellow]")
            return False
    
    def _stop_api(self):
        """Остановка API сервера"""
        if self.api_server:
            # TODO: implement proper shutdown
            self.api_server = None
    
    def _shutdown(self):
        """Полное завершение работы"""
        if self.console:
            self.console.print("\n[yellow]🛑 Завершение работы...[/yellow]")
        
        self._shutdown_node()
        
        if self.console:
            self.console.print("[green]✓ Узел остановлен[/green]")
    
    def _shutdown_node(self):
        """Остановка узла"""
        if self.node:
            try:
                self.node.stop()
            except:
                pass
            self.node = None
    
    def _get_contacts(self) -> List[str]:
        """Получить список контактов из сообщений"""
        if not self.node or not self.node.storage:
            return []
        
        messages = self.node.storage.get_messages(self.node.address, limit=1000)
        contacts = set()
        
        for msg in messages:
            if msg.get('from') and msg['from'] != self.node.address:
                contacts.add(msg['from'])
            if msg.get('to') and msg['to'] != self.node.address:
                contacts.add(msg['to'])
        
        return sorted(list(contacts))
    
    # Команды для одиночного режима
    def _cmd_send(self, args):
        """Отправка сообщения в одиночном режиме"""
        message = ' '.join(args.message) if isinstance(args.message, list) else args.message
        msg_id = self.node.send_message(args.to, message)
        print(f"✓ Отправлено: {msg_id[:16]}..." if msg_id else "✗ Ошибка")
    
    def _cmd_status(self, args):
        """Статус в одиночном режиме"""
        status = self.node.get_status()
        print(f"Адрес: {self.node.address}")
        print(f"Пиры: {len(self.node.transport.get_peers())}")
        print(f"Статус: {'Работает' if self.node.running else 'Остановлен'}")
    
    def _cmd_peers(self, args):
        """Управление пирами в одиночном режиме"""
        if args.connect:
            ip, port = args.connect.rsplit(":", 1)
            success = self.node.transport.connect_to(ip, int(port))
            print(f"{'✓' if success else '✗'} Подключение к {args.connect}")
        elif args.list:
            peers = self.node.transport.get_peers()
            for p in peers:
                print(f"  {p['address'][:30]}... @ {p['ip']}:{p['port']}")


def main():
    """Точка входа"""
    app = MurnetCLI()
    app.run()


if __name__ == "__main__":
    main()
