#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MURNET CLI v5.1 - PRODUCTION READY
Полноценное приложение для управления Murnet узлом
"""

import argparse
import sys
import os
import signal
import json
import time
import threading
import queue
from pathlib import Path
from typing import Optional, Dict, List, Any
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
    from rich.layout import Layout
    from rich.live import Live
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from rich.prompt import Prompt, Confirm
    from rich import box
    from rich.text import Text
    from rich.align import Align
    from rich.tree import Tree
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

try:
    from prompt_toolkit import prompt as pt_prompt
    from prompt_toolkit.completion import WordCompleter
    HAS_PROMPT_TOOLKIT = True
except ImportError:
    HAS_PROMPT_TOOLKIT = False


@dataclass
class AppState:
    """Состояние приложения"""
    running: bool = True
    current_view: str = "dashboard"  # dashboard, chat, peers, network, dht, logs
    messages: List[Dict] = field(default_factory=list)
    peers: List[Dict] = field(default_factory=list)
    logs: queue.Queue = field(default_factory=queue.Queue)
    selected_contact: Optional[str] = None
    last_update: float = 0
    show_help: bool = False
    input_buffer: str = ""
    notification: Optional[str] = None
    notification_time: float = 0


class MurnetCLI:
    """
    Полноценное CLI приложение для Murnet
    - Запускает узел
    - Предоставляет интерактивный интерфейс
    - Работает в одном процессе
    """
    
    VIEWS = ["dashboard", "chat", "peers", "network", "dht", "logs"]
    
    def __init__(self):
        self.node: Optional[MurnetNode] = None
        self.api_server: Optional[MurnetAPIServer] = None
        self.config: Optional[MurnetConfig] = None
        self.state = AppState()
        
        self.console = Console() if HAS_RICH else None
        self.use_tui = HAS_RICH and os.environ.get('TERM') not in ['dumb', '']
        
        self._lock = threading.Lock()
        self._input_event = threading.Event()
        self._last_command = ""
        
        # Graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """Обработчик сигналов"""
        self.state.running = False
        if self.console:
            self.console.print("\n[yellow]Получен сигнал завершения...[/yellow]")
    
    def run(self):
        """Главная точка входа"""
        parser = self._create_parser()
        args = parser.parse_args()
        
        # Загрузка конфигурации
        self._load_config(args)
        
        # Обработка команд
        if args.command is None:
            if args.daemon:
                self._run_daemon(args)
            else:
                self._run_interactive(args)
        else:
            handler = getattr(self, f'_cmd_{args.command}', None)
            if handler:
                handler(args)
            else:
                parser.print_help()
    
    def _create_parser(self) -> argparse.ArgumentParser:
        """Создание парсера аргументов"""
        parser = argparse.ArgumentParser(
            description="🌐 Murnet v5.0 - Децентрализованная P2P сеть",
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog="""
Примеры:
  %(prog)s                           # Интерактивный режим
  %(prog)s --daemon                  # Фоновый режим
  %(prog)s send <addr> "привет"      # Быстрая отправка
  %(prog)s status                    # Показать статус
            """
        )
        
        parser.add_argument("--config", "-c", help="Путь к конфигу")
        parser.add_argument("--data-dir", "-d", default="./data", help="Директория данных")
        parser.add_argument("--profile", choices=["mobile", "vds", "desktop"],
                           help="Профиль конфигурации")
        parser.add_argument("--port", "-p", type=int, default=8888, help="P2P порт")
        parser.add_argument("--api-port", type=int, default=8080, help="API порт")
        parser.add_argument("--no-api", action="store_true", help="Без API сервера")
        parser.add_argument("--no-tui", action="store_true", help="Без TUI (простой режим)")
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
    
    def _load_config(self, args):
        """Загрузка конфигурации"""
        if args.config:
            self.config = MurnetConfig.from_file(args.config)
        else:
            self.config = get_config()
        
        if args.profile:
            self.config.apply_profile(args.profile)
        
        set_config(self.config)
    
    def _run_daemon(self, args):
        """Фоновый режим"""
        self._print("👻 Запуск в фоновом режиме...")
        
        try:
            import daemon
            with daemon.DaemonContext():
                self._run_simple_mode(args, silent=True)
        except ImportError:
            self._print("⚠️ python-daemon не установлен, запуск в foreground")
            self._run_simple_mode(args)
    
    def _run_interactive(self, args):
        """Интерактивный режим с TUI"""
        if not self.use_tui or args.no_tui:
            self._run_simple_mode(args)
            return
        
        self._show_banner()
        
        if not self._init_node(args):
            return
        
        self._start_background_tasks()
        
        try:
            self._main_loop()
        except Exception as e:
            self._log(f"[red]Ошибка: {e}[/red]")
        finally:
            self._shutdown()
    
    def _run_simple_mode(self, args, silent=False):
        """Простой режим без TUI"""
        if not silent:
            self._print("🚀 Murnet Simple Mode")
            self._print(f"Запуск узла на порту {args.port}...")
        
        try:
            self.node = MurnetNode(data_dir=args.data_dir, port=args.port)
            self.node.start()
            
            if not silent:
                self._print(f"✓ Узел запущен: {self.node.address}")
                self._print(f"P2P порт: {args.port}")
                self._print("\nКоманды: status, peers, send, chat, broadcast, exit")
            
            while self.state.running:
                try:
                    cmd = input("\nmurnet> ").strip()
                    self._handle_simple_command(cmd)
                except (KeyboardInterrupt, EOFError):
                    break
                except Exception as e:
                    self._print(f"Ошибка: {e}")
        
        finally:
            if not silent:
                self._print("\n🛑 Остановка узла...")
            if self.node:
                self.node.stop()
            if not silent:
                self._print("✓ Узел остановлен")
    
    def _handle_simple_command(self, cmd: str):
        """Обработка команд в простом режиме"""
        if not cmd:
            return
        
        parts = cmd.split(None, 1)
        command = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""
        
        if command in ["exit", "quit", "q"]:
            self.state.running = False
        elif command == "status":
            self._show_status_simple()
        elif command == "peers":
            self._show_peers_simple()
        elif command == "send":
            subparts = args.split(None, 1)
            if len(subparts) == 2:
                msg_id = self.node.send_message(subparts[0], subparts[1])
                self._print(f"✓ {msg_id[:16]}..." if msg_id else "✗ Ошибка")
        elif command == "chat":
            self._simple_chat()
        elif command == "broadcast":
            if args:
                sent = self.node.transport.broadcast({
                    'type': 'broadcast',
                    'text': args,
                    'from': self.node.address
                })
                self._print(f"✓ Рассылка: {sent} пиров")
        elif command == "connect":
            if ":" in args:
                ip, port = args.rsplit(":", 1)
                try:
                    port = int(port)
                    success = self.node.transport.connect_to(ip, port)
                    self._print(f"{'✓' if success else '✗'} Подключение к {args}")
                except ValueError:
                    self._print("Неверный порт")
        elif command == "help":
            self._print("""
Команды:
  status      - Статус узла
  peers       - Список пиров
  send        - Отправить сообщение (send <addr> <msg>)
  chat        - Интерактивный чат
  broadcast   - Широковещательная рассылка
  connect     - Подключиться к пиру (connect <IP:PORT>)
  exit        - Выход
            """)
    
    def _show_banner(self):
        """Показать баннер"""
        banner = """
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║   🌐  M U R N E T   v 5 . 1                                 ║
║                                                              ║
║   Децентрализованная P2P сеть                               ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
        """
        if self.console:
            self.console.print(Panel(banner.strip(), style="cyan", box=box.DOUBLE))
        else:
            print(banner)
    
    def _init_node(self, args) -> bool:
        """Инициализация узла"""
        try:
            if self.console:
                with Progress(
                    SpinnerColumn(),
                    TextColumn("[progress.description]{task.description}"),
                    console=self.console,
                    transient=True
                ) as progress:
                    
                    task = progress.add_task("[cyan]Инициализация...", total=None)
                    
                    progress.update(task, description="[cyan]Создание узла...")
                    self.node = MurnetNode(data_dir=args.data_dir, port=args.port)
                    
                    progress.update(task, description="[cyan]Запуск P2P...")
                    self.node.start()
                    
                    if not args.no_api:
                        progress.update(task, description="[cyan]Запуск API...")
                        self.api_server = MurnetAPIServer(
                            self.node,
                            host=self.config.api.host,
                            port=args.api_port
                        )
                        threading.Thread(target=self.api_server.run, daemon=True).start()
                    
                    progress.update(task, description="[green]✓ Готово!")
                    time.sleep(0.3)
            else:
                self.node = MurnetNode(data_dir=args.data_dir, port=args.port)
                self.node.start()
                
                if not args.no_api:
                    self.api_server = MurnetAPIServer(
                        self.node,
                        host=self.config.api.host,
                        port=args.api_port
                    )
                    threading.Thread(target=self.api_server.run, daemon=True).start()
            
            info_lines = [
                f"Адрес: {self.node.address}",
                f"P2P порт: {args.port}",
            ]
            if self.api_server:
                info_lines.append(f"API: http://{self.config.api.host}:{args.api_port}")
            
            if self.console:
                self.console.print(Panel(
                    "\n".join(info_lines), 
                    title="[green]✓ Узел запущен[/green]", 
                    border_style="green"
                ))
            
            time.sleep(0.5)
            return True
            
        except Exception as e:
            self._print(f"[red]✗ Ошибка: {e}[/red]")
            return False
    
    def _start_background_tasks(self):
        """Запуск фоновых задач"""
        tasks = [
            ("messages", self._update_messages, 2),
            ("peers", self._update_peers, 3),
        ]
        
        for name, target, interval in tasks:
            t = threading.Thread(
                target=self._worker_loop,
                args=(target, interval),
                name=f"BG-{name}",
                daemon=True
            )
            t.start()
    
    def _worker_loop(self, target, interval):
        """Цикл фоновой задачи"""
        while self.state.running:
            try:
                target()
            except Exception as e:
                pass
            time.sleep(interval)
    
    def _update_messages(self):
        """Обновление сообщений"""
        if self.node and self.node.storage:
            msgs = self.node.storage.get_messages(self.node.address, limit=100)
            
            old_ids = {m['id'] for m in self.state.messages}
            for msg in msgs:
                if msg['id'] not in old_ids:
                    if msg.get('to') == self.node.address and not msg.get('read'):
                        from_addr = msg.get('from', 'Unknown')[:16]
                        preview = msg.get('content', '')[:30]
                        self._show_notification(f"📨 {from_addr}...: {preview}")
            
            with self._lock:
                self.state.messages = msgs
    
    def _update_peers(self):
        """Обновление пиров"""
        if self.node and self.node.transport:
            peers = self.node.transport.get_peers()
            with self._lock:
                self.state.peers = peers
    
    def _show_notification(self, message: str, duration: float = 3.0):
        """Показать уведомление"""
        with self._lock:
            self.state.notification = message
            self.state.notification_time = time.time()
        
        def clear():
            time.sleep(duration)
            with self._lock:
                if time.time() - self.state.notification_time >= duration:
                    self.state.notification = None
        
        threading.Thread(target=clear, daemon=True).start()
    
    def _main_loop(self):
        """Главный цикл TUI"""
        input_thread = threading.Thread(target=self._input_thread, daemon=True)
        input_thread.start()
        
        while self.state.running:
            try:
                if self.console:
                    self.console.clear()
                    self._render_current_view()
                time.sleep(0.2)
            except Exception as e:
                time.sleep(1)
    
    def _input_thread(self):
        """Поток ввода"""
        while self.state.running:
            try:
                import select
                import sys
                
                if select.select([sys.stdin], [], [], 0.5)[0]:
                    line = sys.stdin.readline().strip()
                    if line:
                        self._handle_input(line)
            except:
                time.sleep(0.5)
    
    def _handle_input(self, line: str):
        """Обработка ввода"""
        if not line:
            return
        
        # Односимвольные команды
        if len(line) == 1:
            cmd = line.lower()
            
            if cmd == "1":
                self.state.current_view = "dashboard"
            elif cmd == "2":
                self.state.current_view = "chat"
            elif cmd == "3":
                self.state.current_view = "peers"
            elif cmd == "4":
                self.state.current_view = "network"
            elif cmd == "5":
                self.state.current_view = "dht"
            elif cmd == "6":
                self.state.current_view = "logs"
            elif cmd == "s":
                self._action_send_message()
            elif cmd == "c":
                self._action_connect_peer()
            elif cmd == "d":
                self._action_disconnect_peer()
            elif cmd == "b":
                self._action_broadcast()
            elif cmd == "r":
                self._force_refresh()
            elif cmd == "q":
                self.state.running = False
            elif cmd == "?":
                self.state.show_help = not self.state.show_help
            elif cmd == "n" and self.state.current_view == "chat":
                self._action_new_chat()
            return
        
        # Многосимвольные команды
        parts = line.split(None, 1)
        cmd = parts[0].lower()
        
        if cmd == "send" and len(parts) > 1:
            subparts = parts[1].split(None, 1)
            if len(subparts) == 2:
                self.node.send_message(subparts[0], subparts[1])
                self._show_notification("✓ Сообщение отправлено")
        elif cmd == "connect" and len(parts) > 1 and ":" in parts[1]:
            ip, port_str = parts[1].rsplit(":", 1)
            try:
                port = int(port_str)
                self.node.transport.connect_to(ip, port)
                self._show_notification(f"✓ Подключение к {ip}:{port}")
            except:
                self._show_notification("✗ Неверный порт")
        elif cmd == "view" and len(parts) > 1 and parts[1] in self.VIEWS:
            self.state.current_view = parts[1]
        elif cmd == "help":
            self.state.show_help = True
    
    def _render_current_view(self):
        """Отрисовка текущего вида"""
        self._render_header()
        
        if self.state.show_help:
            self._render_help()
        else:
            renderers = {
                "dashboard": self._render_dashboard,
                "chat": self._render_chat,
                "peers": self._render_peers,
                "network": self._render_network,
                "dht": self._render_dht,
                "logs": self._render_logs,
            }
            renderer = renderers.get(self.state.current_view, self._render_dashboard)
            renderer()
        
        self._render_footer()
        
        with self._lock:
            if self.state.notification and time.time() - self.state.notification_time < 3:
                self.console.print(f"\n[cyan]{self.state.notification}[/cyan]")
    
    def _render_header(self):
        """Отрисовка заголовка"""
        with self._lock:
            peer_count = len(self.state.peers)
            unread = len([m for m in self.state.messages 
                        if not m.get('read') and m.get('to') == getattr(self.node, 'address', '')])
        
        view_colors = {
            "dashboard": "green", "chat": "magenta", "peers": "cyan",
            "network": "blue", "dht": "yellow", "logs": "white"
        }
        
        color = view_colors.get(self.state.current_view, "white")
        mode_str = f"[{color}]● {self.state.current_view.upper()}[/{color}]"
        
        header = (
            f"[bold cyan]🌐 MURNET[/bold cyan] | "
            f"{mode_str} | "
            f"[cyan]📡 {peer_count} пиров[/cyan] | "
            f"[magenta]✉️ {unread} непрочитанных[/magenta]"
        )
        
        self.console.print(Panel(header, box=box.ROUNDED, style="blue"))
    
    def _render_dashboard(self):
        """Дашборд"""
        self.console.print("\n[bold cyan]📊 Статистика[/bold cyan]")
        self.console.print(self._create_stats_table())
        
        self.console.print("\n[bold cyan]📨 Последние сообщения[/bold cyan]")
        self.console.print(self._create_messages_table(limit=8))
        
        self.console.print("\n[bold cyan]🌐 Сеть[/bold cyan]")
        self.console.print(self._create_peers_tree(limit=6))
    
    def _create_stats_table(self) -> Table:
        """Статистика"""
        table = Table(show_header=False, box=box.SIMPLE, expand=True)
        table.add_column(style="cyan", width=20)
        table.add_column(style="white")
        table.add_column(style="cyan", width=20)
        table.add_column(style="white")
        
        try:
            status = self.node.get_status() if self.node else {}
            storage = self.node.storage.get_stats() if self.node and self.node.storage else {}
            
            uptime = status.get('stats', {}).get('uptime', 0)
            hours, rem = divmod(int(uptime), 3600)
            minutes, seconds = divmod(rem, 60)
            
            table.add_row(
                "⏱️  Аптайм:", f"{hours:02d}:{minutes:02d}:{seconds:02d}",
                "📨 Сообщений:", str(storage.get('messages', 0))
            )
            table.add_row(
                "📬 Непрочитанных:", str(storage.get('messages_unread', 0)),
                "🗄️  DHT записей:", str(status.get('dht_entries', 0))
            )
            table.add_row(
                "💾 Размер БД:", f"{storage.get('db_size_mb', 0):.1f} MB",
                "🔐 E2E сессий:", str(status.get('security', {}).get('e2e_ready', 0))
            )
        except:
            table.add_row("[dim]Загрузка...", "", "", "")
        
        return table
    
    def _create_messages_table(self, limit: int = 10) -> Table:
        """Таблица сообщений"""
        table = Table(
            show_header=True, header_style="bold cyan",
            box=box.SIMPLE, expand=True, row_styles=["", "dim"]
        )
        table.add_column("Время", width=8, style="dim")
        table.add_column("От/Кому", width=15, style="cyan")
        table.add_column("Сообщение", style="white")
        table.add_column("✓", width=3, justify="center")
        
        with self._lock:
            messages = sorted(
                self.state.messages,
                key=lambda x: x.get('timestamp', 0),
                reverse=True
            )[:limit]
        
        for msg in messages:
            ts = datetime.fromtimestamp(msg.get('timestamp', 0)).strftime('%H:%M')
            is_me = msg.get('from') == getattr(self.node, 'address', None)
            other = msg.get('to') if is_me else msg.get('from')
            other_short = (other or 'Unknown')[:14]
            
            content = msg.get('content', '')[:40]
            if len(content) > 40:
                content = content[:37] + "..."
            
            delivered = "✓" if msg.get('delivered') else "○"
            is_unread = not msg.get('read') and not is_me
            style = "bold" if is_unread else ""
            
            table.add_row(ts, other_short, content, delivered, style=style)
        
        if not messages:
            table.add_row("-", "-", "[dim]Нет сообщений[/dim]", "")
        
        return table
    
    def _create_peers_tree(self, limit: int = 6) -> Tree:
        """Дерево пиров"""
        tree = Tree("📡 Подключенные пиры")
        
        with self._lock:
            peers = self.state.peers[:limit]
        
        for peer in peers:
            status = "🟢" if peer.get('is_active') else "🔴"
            auth = "🔒" if peer.get('handshake_complete') else "🔓"
            rtt = f" {peer.get('rtt', 0)*1000:.0f}ms" if peer.get('rtt') else ""
            addr = peer.get('address', 'Unknown')[:20]
            
            tree.add(f"{status} {auth} {addr}...{rtt}")
        
        with self._lock:
            remaining = len(self.state.peers) - limit
        
        if remaining > 0:
            tree.add(f"[dim]... и ещё {remaining}[/dim]")
        
        if not peers:
            tree.add("[dim]Нет подключенных пиров[/dim]")
        
        return tree
    
    def _render_chat(self):
        """Чат"""
        self.console.print("\n[bold cyan]👥 Контакты[/bold cyan]")
        
        contacts = {}
        with self._lock:
            for msg in self.state.messages:
                addr = msg.get('from') if msg.get('from') != getattr(self.node, 'address', None) else msg.get('to')
                if addr:
                    if addr not in contacts:
                        contacts[addr] = {'unread': 0, 'last': 0}
                    if not msg.get('read') and msg.get('to') == getattr(self.node, 'address', None):
                        contacts[addr]['unread'] += 1
                    contacts[addr]['last'] = max(contacts[addr]['last'], msg.get('timestamp', 0))
        
        sorted_contacts = sorted(contacts.items(), key=lambda x: x[1]['last'], reverse=True)
        
        for i, (addr, info) in enumerate(sorted_contacts[:10], 1):
            unread = f" [red]({info['unread']})[/red]" if info['unread'] else ""
            marker = "▶ " if addr == self.state.selected_contact else "  "
            self.console.print(f"  {i}. {marker}{addr[:25]}...{unread}")
        
        self.console.print("\n[bold cyan]💬 Диалог[/bold cyan]")
        
        if self.state.selected_contact:
            with self._lock:
                msgs = [m for m in self.state.messages 
                       if m.get('from') == self.state.selected_contact 
                       or m.get('to') == self.state.selected_contact]
                msgs = sorted(msgs, key=lambda x: x.get('timestamp', 0))
            
            for msg in msgs[-20:]:  # Последние 20 сообщений
                is_me = msg.get('from') == getattr(self.node, 'address', None)
                color = "green" if is_me else "blue"
                prefix = "Вы" if is_me else msg.get('from', 'Unknown')[:8]
                ts = datetime.fromtimestamp(msg.get('timestamp', 0)).strftime('%H:%M')
                content = msg.get('content', '')
                
                self.console.print(f"  [{color}]{ts} {prefix}:[/{color}] {content}")
            
            if not msgs:
                self.console.print("  [dim]Нет сообщений...[/dim]")
        else:
            self.console.print("  [dim]Выберите контакт (1-9) или нажмите 'n' для нового[/dim]")
    
    def _render_peers(self):
        """Пиры"""
        table = Table(
            show_header=True, header_style="bold cyan",
            box=box.ROUNDED, expand=True
        )
        table.add_column("#", width=4, justify="right")
        table.add_column("Адрес", style="cyan")
        table.add_column("IP:Port", style="white")
        table.add_column("RTT", justify="right", style="green")
        table.add_column("Статус")
        
        with self._lock:
            peers = self.state.peers
        
        for i, peer in enumerate(peers, 1):
            rtt = f"{peer.get('rtt', 0)*1000:.1f}ms" if peer.get('rtt') else "N/A"
            status = "[green]● Активен[/green]" if peer.get('is_active') else "[red]● Нет[/red]"
            
            table.add_row(
                str(i),
                peer.get('address', 'Unknown')[:25],
                f"{peer.get('ip')}:{peer.get('port')}",
                rtt,
                status
            )
        
        if not peers:
            table.add_row("", "[dim]Нет подключенных пиров[/dim]", "", "", "")
        
        self.console.print("\n[bold cyan]🌐 Управление пирами[/bold cyan]")
        self.console.print(table)
        self.console.print("\n[dim]Команды: c - подключиться, d - отключить[/dim]")
    
    def _render_network(self):
        """Сеть"""
        self.console.print("\n[bold cyan]🛤️  Маршрутизация[/bold cyan]")
        
        try:
            routes = self.node.routing.get_all_routes() if self.node else {}
            
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
                    dest[:30],
                    info.get('next_hop', 'Unknown')[:25],
                    f"{info.get('cost', 0):.2f}",
                    str(info.get('hop_count', '?'))
                )
            
            if not routes:
                table.add_row("[dim]Нет маршрутов[/dim]", "", "", "")
            
            self.console.print(table)
        except Exception as e:
            self.console.print(f"[red]Ошибка: {e}[/red]")
    
    def _render_dht(self):
        """DHT"""
        self.console.print("\n[bold cyan]🗄️  DHT Статистика[/bold cyan]")
        
        try:
            stats = self.node.murnaked.get_stats() if self.node else {}
            ring = stats.get('ring_stats', {})
            
            table = Table(show_header=False, box=box.SIMPLE, expand=True)
            table.add_column(style="cyan", width=25)
            table.add_column(style="white")
            table.add_column(style="cyan", width=25)
            table.add_column(style="white")
            
            table.add_row(
                "Локальных ключей:", str(stats.get('local_keys', 0)),
                "Виртуальных нод:", str(ring.get('total_vnodes', 0))
            )
            table.add_row(
                "Сохранено записей:", str(stats.get('stored_keys', 0)),
                "Реальных нод:", str(ring.get('real_nodes', 0))
            )
            table.add_row(
                "Получено записей:", str(stats.get('retrieved_keys', 0)),
                "Покрытие кольца:", f"{ring.get('ring_coverage', 0):.2f}%"
            )
            
            self.console.print(table)
        except Exception as e:
            self.console.print(f"[red]Ошибка: {e}[/red]")
    
    def _render_logs(self):
        """Логи"""
        self.console.print("\n[bold cyan]📋 Системные логи[/bold cyan]")
        self.console.print("[dim]Логи системы...[/dim]")
    
    def _render_help(self):
        """Помощь"""
        help_text = """
[bold cyan]Управление Murnet CLI:[/bold cyan]

[green]Вкладки (1-6):[/green]
  1 / dashboard - Главный экран со статистикой
  2 / chat      - Чат с контактами
  3 / peers     - Управление пирами
  4 / network   - Маршрутизация
  5 / dht       - DHT статистика
  6 / logs      - Системные логи

[green]Действия:[/green]
  s / send    - Отправить сообщение
  c / connect - Подключиться к пиру
  d / disconnect - Отключить пира
  b / broadcast  - Широковещательно
  r / refresh    - Обновить данные
  q / quit       - Выход

[green]В чате:[/green]
  1-9       - Выбрать контакт
  n         - Новый диалог

[dim]Нажмите Enter для возврата...[/dim]
        """
        self.console.print(Panel(help_text.strip(), title="❓ Помощь", box=box.ROUNDED))
    
    def _render_footer(self):
        """Футер"""
        if self.state.show_help:
            self.console.print("\n[dim center]Нажмите Enter для возврата[/dim]")
        else:
            footer = (
                "1:Дашборд 2:Чат 3:Пиры 4:Сеть 5:DHT 6:Логи | "
                "s:Отправить c:Подключить d:Отключить b:Широковещание r:Обновить q:Выход | ?:Помощь"
            )
            self.console.print(f"\n[dim]{footer}[/dim]")
    
    def _action_send_message(self):
        """Отправка сообщения"""
        self.console.clear()
        self.console.print("[bold cyan]📤 Отправка сообщения[/bold cyan]\n")
        
        to = self._prompt("Кому (адрес): ")
        if not to:
            return
        
        self.console.print("[dim]Сообщение (Enter для завершения):[/dim]")
        lines = []
        while True:
            line = self._prompt("> ")
            if not line and lines:
                break
            if line:
                lines.append(line)
        
        content = "\n".join(lines)
        if content:
            with self.console.status("[cyan]Отправка...[/cyan]"):
                msg_id = self.node.send_message(to, content)
            
            if msg_id:
                self._show_notification(f"✓ Отправлено: {msg_id[:16]}...")
        
        self._prompt("\nНажмите Enter...")
    
    def _action_connect_peer(self):
        """Подключение к пиру"""
        self.console.clear()
        self.console.print("[bold cyan]🔗 Подключение к пиру[/bold cyan]\n")
        
        ip = self._prompt("IP: ")
        if not ip:
            return
        
        port_str = self._prompt("Порт [8888]: ") or "8888"
        try:
            port = int(port_str)
        except:
            port = 8888
        
        with self.console.status(f"[cyan]Подключение к {ip}:{port}...[/cyan]"):
            success = self.node.transport.connect_to(ip, port)
        
        if success:
            self._show_notification(f"✓ Подключено к {ip}:{port}")
        else:
            self._show_notification("✗ Не удалось подключиться")
        
        self._prompt("\nНажмите Enter...")
    
    def _action_disconnect_peer(self):
        """Отключение пира"""
        self.console.clear()
        self.console.print("[bold cyan]🔌 Отключение пира[/bold cyan]\n")
        
        with self._lock:
            peers = self.state.peers
        
        if not peers:
            self.console.print("[yellow]Нет подключенных пиров[/yellow]")
            self._prompt("\nНажмите Enter...")
            return
        
        for i, peer in enumerate(peers[:10], 1):
            print(f"  {i}. {peer['address'][:30]}...")
        
        choice = self._prompt("\nНомер пира: ")
        
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(peers):
                addr = peers[idx]['address']
                self._show_notification(f"Отключение {addr[:20]}...")
        
        self._prompt("\nНажмите Enter...")
    
    def _action_broadcast(self):
        """Широковещательная рассылка"""
        self.console.clear()
        self.console.print("[bold cyan]📢 Широковещательная рассылка[/bold cyan]\n")
        
        message = self._prompt("Сообщение: ")
        if message:
            with self.console.status("[cyan]Рассылка...[/cyan]"):
                sent = self.node.transport.broadcast({
                    'type': 'broadcast',
                    'text': message,
                    'from': self.node.address
                })
            
            self._show_notification(f"✓ Рассылка: {sent} пиров")
        
        self._prompt("\nНажмите Enter...")
    
    def _action_new_chat(self):
        """Новый чат"""
        self.console.clear()
        self.console.print("[bold cyan]💬 Новый диалог[/bold cyan]\n")
        
        addr = self._prompt("Адрес контакта: ")
        if addr:
            self.state.selected_contact = addr
            self._show_notification(f"Выбран контакт: {addr[:20]}...")
    
    def _force_refresh(self):
        """Обновление"""
        self._update_messages()
        self._update_peers()
        self._show_notification("✓ Данные обновлены")
    
    def _simple_chat(self):
        """Простой чат"""
        to = input("\nКому (адрес): ").strip()
        if not to:
            return
        
        print(f"\n--- Чат с {to[:20]}... ---")
        try:
            while True:
                msg = input("> ").strip()
                if not msg:
                    break
                msg_id = self.node.send_message(to, msg)
                print(f"  ✓ {msg_id[:16]}..." if msg_id else "  ✗ Ошибка")
        except KeyboardInterrupt:
            pass
        print("---")
    
    def _prompt(self, text: str) -> str:
        """Prompt"""
        if HAS_PROMPT_TOOLKIT and self.console:
            try:
                return pt_prompt(text)
            except:
                pass
        return input(text)
    
    def _print(self, *args, **kwargs):
        """Print"""
        if self.console:
            self.console.print(*args, **kwargs)
        else:
            print(*args)
    
    def _log(self, message: str):
        """Лог"""
        self.state.logs.put(message)
    
    def _shutdown(self):
        """Shutdown"""
        self.state.running = False
        
        if self.console:
            self.console.clear()
            self.console.print("[yellow]🛑 Завершение работы...[/yellow]")
        
        if self.node:
            try:
                self.node.stop()
                if self.console:
                    self.console.print("[green]✓ Узел остановлен[/green]")
            except Exception as e:
                if self.console:
                    self.console.print(f"[red]Ошибка: {e}[/red]")
    
    @staticmethod
    def _human_size(size_bytes: int) -> str:
        """Human readable size"""
        if size_bytes == 0:
            return "0B"
        size_names = ["B", "KB", "MB", "GB"]
        i = 0
        while size_bytes >= 1024 and i < len(size_names) - 1:
            size_bytes /= 1024
            i += 1
        return f"{size_bytes:.1f}{size_names[i]}"
    
    def _cmd_send(self, args):
        """Команда send"""
        message = ' '.join(args.message) if isinstance(args.message, list) else args.message
        
        if not self.node:
            self.node = MurnetNode(data_dir=args.data_dir, port=args.port)
            self.node.start()
        
        msg_id = self.node.send_message(args.to, message)
        print(f"✅ Отправлено! ID: {msg_id}" if msg_id else "❌ Ошибка")
        self.node.stop()
    
    def _cmd_status(self, args):
        """Команда status"""
        if not self.node:
            self.node = MurnetNode(data_dir=args.data_dir, port=args.port)
            self.node.start()
        
        try:
            status = self.node.get_status()
            storage = self.node.storage.get_stats()
            
            print(f"Адрес: {self.node.address}")
            print(f"Пиры: {len(self.node.transport.get_peers())}")
            print(f"Сообщений: {storage.get('messages', 0)}")
            print(f"Непрочитанных: {storage.get('messages_unread', 0)}")
            print(f"БД: {storage.get('db_size_mb', 0):.1f} MB")
        except Exception as e:
            print(f"Ошибка: {e}")
        
        self.node.stop()
    
    def _cmd_peers(self, args):
        """Команда peers"""
        if not self.node:
            self.node = MurnetNode(data_dir=args.data_dir, port=args.port)
            self.node.start()
        
        if args.connect:
            try:
                ip, port = args.connect.rsplit(":", 1)
                port = int(port)
                success = self.node.transport.connect_to(ip, port)
                print(f"{'✅' if success else '❌'} Подключение к {args.connect}")
            except Exception as e:
                print(f"❌ Ошибка: {e}")
        elif args.list:
            peers = self.node.transport.get_peers()
            print(f"Пиры ({len(peers)}):")
            for p in peers:
                status = "🟢" if p.get('is_active') else "🔴"
                print(f"  {status} {p['address'][:20]}... @ {p['ip']}:{p['port']}")
        
        self.node.stop()


def main():
    """Точка входа"""
    app = MurnetCLI()
    app.run()


if __name__ == "__main__":
    main()