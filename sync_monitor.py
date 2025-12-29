#!/usr/bin/env python3
"""
JIRA-Lark 多團隊同步監控系統
提供全畫面 TUI 介面監控多個團隊表格的同步狀態
"""

import asyncio
import curses
import logging
import os
import signal
import subprocess
import sys
import time
import traceback
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml


class SyncStatus(Enum):
    """同步狀態枚舉"""

    IDLE = "idle"
    SYNCING = "syncing"
    SUCCESS = "success"
    FAILED = "failed"
    PAUSED = "paused"

    def get_color(self) -> int:
        """獲取對應的顏色對"""
        return {
            SyncStatus.IDLE: 8,  # 白色
            SyncStatus.SYNCING: 4,  # 黃色
            SyncStatus.SUCCESS: 2,  # 綠色
            SyncStatus.FAILED: 1,  # 紅色
            SyncStatus.PAUSED: 7,  # 灰色
        }.get(self, 8)

    def get_symbol(self) -> str:
        """獲取對應的符號"""
        return {
            SyncStatus.IDLE: "⏸",
            SyncStatus.SYNCING: "⟳",
            SyncStatus.SUCCESS: "✓",
            SyncStatus.FAILED: "✗",
            SyncStatus.PAUSED: "⏸",
        }.get(self, "?")


@dataclass
class TableInfo:
    """表格資訊"""

    team: str
    table: str
    table_id: str
    wiki_token: str
    sync_interval: int
    enabled: bool = True
    paused: bool = False

    # 同步狀態
    status: SyncStatus = SyncStatus.IDLE
    last_sync_time: Optional[float] = None
    next_sync_time: Optional[float] = None
    sync_count: int = 0
    error_count: int = 0
    last_error: Optional[str] = None

    # 日誌
    logs: deque = field(default_factory=lambda: deque(maxlen=1000))

    @property
    def key(self) -> str:
        """表格唯一鍵"""
        return f"{self.team}.{self.table}"

    def add_log(self, message: str, level: str = "INFO"):
        """添加日誌"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.logs.append(f"[{timestamp}] [{level}] {message}")


class ConfigWatcher:
    """配置檔案監控器"""

    def __init__(self, config_path: str):
        self.config_path = config_path
        self.last_mtime = 0
        self._update_mtime()

    def _update_mtime(self):
        """更新最後修改時間"""
        try:
            self.last_mtime = os.path.getmtime(self.config_path)
        except Exception:
            self.last_mtime = 0

    def has_changed(self) -> bool:
        """檢查配置是否已變更"""
        try:
            current_mtime = os.path.getmtime(self.config_path)
            if current_mtime > self.last_mtime:
                self.last_mtime = current_mtime
                return True
        except Exception:
            pass
        return False


class SyncMonitor:
    """同步監控主類"""

    def __init__(self, config_path: str):
        self.config_path = config_path
        self.config_watcher = ConfigWatcher(config_path)
        self.tables: Dict[str, TableInfo] = {}
        self.current_table_index = 0
        self.should_exit = False
        self.sync_tasks: Dict[str, asyncio.Task] = {}
        self.global_pause = False
        self.cleanup_in_progress = False
        self.last_cleanup_date = None

        # 畫面配置
        self.status_height_ratio = 0.33
        self.log_offset = 0

        # 全局日誌
        self.global_logs = deque(maxlen=500)

        # 加載配置
        self._load_config()

    def _load_config(self) -> bool:
        """加載配置檔案"""
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)

            # 獲取預設同步間隔
            default_interval = config.get("global", {}).get(
                "default_sync_interval", 300
            )

            # 解析團隊配置
            teams = config.get("teams", {})
            new_tables = {}

            for team_name, team_config in teams.items():
                if not team_config.get("enabled", True):
                    continue

                team_interval = team_config.get("sync_interval", default_interval)
                wiki_token = team_config.get("wiki_token", "")

                tables = team_config.get("tables", {})
                for table_name, table_config in tables.items():
                    if not table_config.get("enabled", True):
                        continue

                    table_interval = table_config.get("sync_interval", team_interval)
                    table_id = table_config.get("table_id", "")

                    key = f"{team_name}.{table_name}"

                    # 保留現有狀態
                    if key in self.tables:
                        existing = self.tables[key]
                        new_tables[key] = TableInfo(
                            team=team_name,
                            table=table_name,
                            table_id=table_id,
                            wiki_token=wiki_token,
                            sync_interval=table_interval,
                            enabled=True,
                            paused=existing.paused,
                            status=existing.status,
                            last_sync_time=existing.last_sync_time,
                            next_sync_time=existing.next_sync_time,
                            sync_count=existing.sync_count,
                            error_count=existing.error_count,
                            last_error=existing.last_error,
                            logs=existing.logs,
                        )
                    else:
                        # 新表格，設定為立即同步（使用較早的時間確保立即觸發）
                        new_tables[key] = TableInfo(
                            team=team_name,
                            table=table_name,
                            table_id=table_id,
                            wiki_token=wiki_token,
                            sync_interval=table_interval,
                            next_sync_time=0,  # 設為 0 確保立即開始第一次同步
                        )

            self.tables = new_tables
            self._add_global_log("配置加載成功", "INFO")
            return True

        except Exception as e:
            self._add_global_log(f"配置加載失敗: {e}", "ERROR")
            return False

    def _add_global_log(self, message: str, level: str = "INFO"):
        """添加全局日誌"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.global_logs.append(f"[{timestamp}] [{level}] {message}")

    def _get_taiwan_now(self) -> datetime:
        """取得台灣時間"""
        return datetime.now(timezone(timedelta(hours=8)))

    def _set_global_pause(self, paused: bool):
        """設置全局暫停狀態"""
        self.global_pause = paused
        if not paused:
            for table in self.tables.values():
                if table.status == SyncStatus.PAUSED and not table.paused:
                    table.status = SyncStatus.IDLE

    async def _wait_for_running_syncs(self):
        """等待所有同步完成"""
        while not self.should_exit:
            running = [
                t for t in self.tables.values() if t.status == SyncStatus.SYNCING
            ]
            if not running:
                return
            await asyncio.sleep(1)

    async def _run_table_scan_cleaner(self) -> bool:
        """執行 table_scan_cleaner.py"""
        try:
            cmd = [sys.executable, "table_scan_cleaner.py", "--no-confirm"]
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=os.path.dirname(os.path.abspath(__file__)),
            )

            async def read_stream(stream, log_level):
                while True:
                    line = await stream.readline()
                    if not line:
                        break
                    line_text = line.decode("utf-8").strip()
                    if line_text:
                        self._add_global_log(line_text, log_level)

            await asyncio.gather(
                read_stream(process.stdout, "INFO"),
                read_stream(process.stderr, "ERROR"),
                process.wait(),
            )

            return process.returncode == 0

        except Exception as e:
            self._add_global_log(f"執行清理命令失敗: {e}", "ERROR")
            return False

    async def _run_daily_cleanup(self, cleanup_date):
        """執行每日清理流程"""
        try:
            self.cleanup_in_progress = True
            self.last_cleanup_date = cleanup_date
            self._add_global_log("到達每日清理時間，暫停同步中...", "INFO")
            self._set_global_pause(True)

            await self._wait_for_running_syncs()
            self._add_global_log("同步已完成，開始執行清理...", "INFO")

            success = await self._run_table_scan_cleaner()
            if success:
                self._add_global_log("清理完成，恢復同步", "INFO")
            else:
                self._add_global_log("清理失敗，恢復同步", "ERROR")

        finally:
            self._set_global_pause(False)
            self.cleanup_in_progress = False

    async def _watch_daily_cleanup(self):
        """監控每日清理時間（台灣時間 00:00）"""
        while not self.should_exit:
            now = self._get_taiwan_now()
            if now.hour == 0 and now.minute == 0:
                today = now.date()
                if self.last_cleanup_date != today and not self.cleanup_in_progress:
                    await self._run_daily_cleanup(today)
            await asyncio.sleep(1)

    async def _sync_table(self, table_info: TableInfo):
        """同步單一表格"""
        key = table_info.key

        while not self.should_exit:
            # 全局暫停（清理中）
            if self.global_pause and not table_info.paused:
                table_info.status = SyncStatus.PAUSED
                await asyncio.sleep(1)
                continue

            # 檢查是否暫停
            if table_info.paused:
                table_info.status = SyncStatus.PAUSED
                await asyncio.sleep(1)
                continue

            # 檢查是否到達同步時間
            current_time = time.time()
            if (
                table_info.next_sync_time is None
                or current_time < table_info.next_sync_time
            ):
                await asyncio.sleep(0.1)  # 減少檢查間隔到 0.1 秒，提高並行響應速度
                continue

            # 開始同步
            table_info.status = SyncStatus.SYNCING
            table_info.add_log(f"開始同步 {key}", "INFO")
            self._add_global_log(f"開始同步 {key}", "INFO")

            try:
                # 執行主同步
                success = await self._run_main_sync(table_info)

                if success:
                    # 如果表格名稱是 tcg_table，執行父子關係和 Sprints 更新
                    if table_info.table == "tcg_table":
                        table_info.add_log("執行父子關係和 Sprints 更新", "INFO")
                        await self._run_parent_child_update(table_info)

                    table_info.status = SyncStatus.SUCCESS
                    table_info.sync_count += 1
                    table_info.add_log(
                        f"同步成功 (第 {table_info.sync_count} 次)", "INFO"
                    )
                    self._add_global_log(f"{key} 同步成功", "INFO")
                else:
                    raise Exception("同步失敗")

            except Exception as e:
                table_info.status = SyncStatus.FAILED
                table_info.error_count += 1
                table_info.last_error = str(e)
                table_info.add_log(f"同步失敗: {e}", "ERROR")
                self._add_global_log(f"{key} 同步失敗: {e}", "ERROR")

            # 更新同步時間
            table_info.last_sync_time = time.time()
            table_info.next_sync_time = (
                table_info.last_sync_time + table_info.sync_interval
            )

            next_time_str = datetime.fromtimestamp(table_info.next_sync_time).strftime(
                "%H:%M:%S"
            )
            table_info.add_log(f"下次同步: {next_time_str}", "INFO")

    async def _run_main_sync(self, table_info: TableInfo) -> bool:
        """執行主同步程序"""
        try:
            cmd = [
                sys.executable,
                "main.py",
                "sync",
                "--team",
                table_info.team,
                "--table",
                table_info.table,
            ]

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=os.path.dirname(os.path.abspath(__file__)),
            )

            # 即時讀取輸出 - 創建兩個任務分別讀取 stdout 和 stderr
            async def read_stream(stream, log_level):
                """即時讀取輸出流"""
                while True:
                    line = await stream.readline()
                    if not line:
                        break
                    line_text = line.decode("utf-8").strip()
                    if line_text:
                        table_info.add_log(line_text, log_level)

            # 並行讀取 stdout 和 stderr
            await asyncio.gather(
                read_stream(process.stdout, "INFO"),
                read_stream(process.stderr, "ERROR"),
                process.wait(),
            )

            return process.returncode == 0

        except Exception as e:
            table_info.add_log(f"執行同步命令失敗: {e}", "ERROR")
            return False

    async def _run_parent_child_update(self, table_info: TableInfo) -> bool:
        """執行父子關係和 Sprints 更新"""
        try:
            lark_url = f"https://igxy0zaeo1r.sg.larksuite.com/wiki/{table_info.wiki_token}?table={table_info.table_id}"

            cmd = [
                sys.executable,
                "parent_child_relationship_updater.py",
                "--url",
                lark_url,
                "--parent-field",
                "Parent Tickets",
                "--sprints-field",
                "Sprints",
                "--execute",
            ]

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=os.path.dirname(os.path.abspath(__file__)),
            )

            # 即時讀取輸出
            async def read_stream(stream, log_level):
                """即時讀取輸出流"""
                while True:
                    line = await stream.readline()
                    if not line:
                        break
                    line_text = line.decode("utf-8").strip()
                    if line_text:
                        table_info.add_log(line_text, log_level)

            # 並行讀取 stdout 和 stderr
            await asyncio.gather(
                read_stream(process.stdout, "INFO"),
                read_stream(process.stderr, "ERROR"),
                process.wait(),
            )

            return process.returncode == 0

        except Exception as e:
            table_info.add_log(f"父子關係更新失敗: {e}", "ERROR")
            return False

    async def _watch_config(self):
        """監控配置檔案變更"""
        while not self.should_exit:
            if self.config_watcher.has_changed():
                self._add_global_log("檢測到配置變更，重新加載...", "INFO")
                if self._load_config():
                    # 重啟同步任務
                    await self._restart_sync_tasks()

            await asyncio.sleep(2)

    async def _restart_sync_tasks(self):
        """重啟同步任務"""
        # 取消舊任務
        for task in self.sync_tasks.values():
            task.cancel()

        self.sync_tasks.clear()

        # 啟動新任務
        for key, table_info in self.tables.items():
            task = asyncio.create_task(self._sync_table(table_info))
            self.sync_tasks[key] = task

        self._add_global_log("同步任務已重啟", "INFO")

    def _get_current_table(self) -> Optional[TableInfo]:
        """獲取當前選中的表格"""
        if not self.tables:
            return None

        keys = list(self.tables.keys())
        if 0 <= self.current_table_index < len(keys):
            return self.tables[keys[self.current_table_index]]
        return None

    def _draw_ui(self, stdscr):
        """繪製 UI"""
        height, width = stdscr.getmaxyx()

        # 清空螢幕
        stdscr.erase()

        # 計算分割線位置
        status_height = int(height * self.status_height_ratio)
        log_height = height - status_height - 1

        # 繪製標題
        title = "JIRA-Lark 多團隊同步監控系統"
        try:
            stdscr.addstr(
                0,
                (width - len(title)) // 2,
                title,
                curses.A_BOLD | curses.color_pair(6),
            )
        except:
            pass

        # 繪製狀態區域
        self._draw_status_panel(stdscr, 1, status_height - 1, width)

        # 繪製分割線
        try:
            stdscr.addstr(status_height, 0, "─" * width, curses.color_pair(7))
        except:
            pass

        # 繪製日誌區域
        self._draw_log_panel(stdscr, status_height + 1, log_height, width)

        # 繪製幫助信息
        help_text = "Q:退出 | ←→:切換表格 | P:暫停/恢復 | R:重新加載配置"
        try:
            stdscr.addstr(height - 1, 0, help_text[: width - 1], curses.color_pair(7))
        except:
            pass

        # 刷新螢幕
        stdscr.noutrefresh()
        curses.doupdate()

    def _draw_status_panel(self, stdscr, start_y: int, height: int, width: int):
        """繪製狀態面板（橫向排版）"""
        if not self.tables:
            try:
                stdscr.addstr(start_y + 1, 2, "沒有啟用的表格", curses.color_pair(7))
            except:
                pass
            return

        # 第一行：團隊狀態概覽（橫向排列）
        y = start_y
        x = 0
        col_width = 20  # 每個團隊佔用的寬度

        for idx, (key, table_info) in enumerate(self.tables.items()):
            if x + col_width > width:
                # 換到下一行
                y += 1
                x = 0

            if y >= start_y + height:
                break

            # 高亮當前選中的表格
            is_selected = idx == self.current_table_index

            # 狀態符號和顏色
            status_symbol = table_info.status.get_symbol()
            status_color = table_info.status.get_color()

            # 暫停標記
            pause_mark = "[P]" if table_info.paused else "   "

            # 縮短顯示格式：符號 team.table [P] 狀態
            display_text = f"{status_symbol} {key} {pause_mark}"
            display_text = display_text[: col_width - 1].ljust(col_width - 1)

            # 繪製
            try:
                attr = curses.A_REVERSE if is_selected else curses.A_NORMAL
                stdscr.addstr(
                    y, x, display_text, curses.color_pair(status_color) | attr
                )
                x += col_width
            except:
                pass

        # 詳細信息行：顯示當前選中表格的詳細信息
        y += 1
        if y < start_y + height:
            current_table = self._get_current_table()
            if current_table:
                # 時間資訊
                if current_table.last_sync_time:
                    last_sync = datetime.fromtimestamp(
                        current_table.last_sync_time
                    ).strftime("%H:%M:%S")
                else:
                    last_sync = "---"

                if current_table.next_sync_time:
                    next_sync = datetime.fromtimestamp(
                        current_table.next_sync_time
                    ).strftime("%H:%M:%S")
                    remaining = int(current_table.next_sync_time - time.time())
                    if remaining < 0:
                        remaining = 0
                    time_info = f"上次:{last_sync} 下次:{next_sync} (剩餘:{remaining}s)"
                else:
                    time_info = f"上次:{last_sync}"

                # 統計資訊
                stats = (
                    f"成功:{current_table.sync_count} 失敗:{current_table.error_count}"
                )

                # 詳細信息
                detail_text = f"[{current_table.key}] {time_info} | {stats}"

                try:
                    stdscr.addstr(
                        y,
                        0,
                        detail_text[: width - 1].ljust(width - 1),
                        curses.color_pair(7),
                    )
                except:
                    pass

                # 錯誤信息
                y += 1
                if current_table.last_error and y < start_y + height:
                    error_text = f"錯誤: {current_table.last_error}"
                    try:
                        stdscr.addstr(
                            y, 2, error_text[: width - 3], curses.color_pair(1)
                        )
                    except:
                        pass

    def _draw_log_panel(self, stdscr, start_y: int, height: int, width: int):
        """繪製日誌面板"""
        current_table = self._get_current_table()

        # 標題
        if current_table:
            log_title = f"日誌: {current_table.key} (使用 ↑↓ 捲動)"
            logs = list(current_table.logs)
        else:
            log_title = "全局日誌 (使用 ↑↓ 捲動)"
            logs = list(self.global_logs)

        try:
            stdscr.addstr(
                start_y, 2, log_title[: width - 3], curses.A_BOLD | curses.color_pair(6)
            )
        except:
            pass

        # 繪製日誌
        display_height = height - 1
        total_logs = len(logs)

        # 調整捲動偏移
        max_offset = max(0, total_logs - display_height)
        self.log_offset = max(0, min(self.log_offset, max_offset))

        # 顯示日誌
        for i in range(display_height):
            log_idx = total_logs - display_height + i - self.log_offset
            if 0 <= log_idx < total_logs:
                log_line = logs[log_idx]

                # 根據日誌級別設定顏色
                if "[ERROR]" in log_line:
                    color = curses.color_pair(1)
                elif "[WARNING]" in log_line:
                    color = curses.color_pair(4)
                else:
                    color = curses.color_pair(8)

                try:
                    stdscr.addstr(
                        start_y + 1 + i,
                        0,
                        log_line[: width - 1].ljust(width - 1),
                        color,
                    )
                except:
                    pass

    async def _handle_input(self, stdscr):
        """處理用戶輸入"""
        # 設置非阻塞模式
        stdscr.nodelay(True)

        while not self.should_exit:
            try:
                key = stdscr.getch()

                if key == -1:
                    # 沒有輸入
                    await asyncio.sleep(0.05)
                    continue

                # Q: 退出
                if key in (ord("q"), ord("Q")):
                    self.should_exit = True
                    break

                # 左右鍵: 切換表格
                elif key == curses.KEY_LEFT:
                    if self.tables:
                        self.current_table_index = (self.current_table_index - 1) % len(
                            self.tables
                        )
                        self.log_offset = 0

                elif key == curses.KEY_RIGHT:
                    if self.tables:
                        self.current_table_index = (self.current_table_index + 1) % len(
                            self.tables
                        )
                        self.log_offset = 0

                # 上下鍵: 捲動日誌
                elif key == curses.KEY_UP:
                    self.log_offset = max(0, self.log_offset + 1)

                elif key == curses.KEY_DOWN:
                    self.log_offset = max(0, self.log_offset - 1)

                # P: 暫停/恢復當前表格
                elif key in (ord("p"), ord("P")):
                    current_table = self._get_current_table()
                    if current_table:
                        current_table.paused = not current_table.paused
                        status = "暫停" if current_table.paused else "恢復"
                        self._add_global_log(f"{current_table.key} 已{status}", "INFO")

                # R: 重新加載配置
                elif key in (ord("r"), ord("R")):
                    self._add_global_log("手動重新加載配置...", "INFO")
                    if self._load_config():
                        await self._restart_sync_tasks()

            except Exception as e:
                self._add_global_log(f"處理輸入時發生錯誤: {e}", "ERROR")

            await asyncio.sleep(0.05)

    async def run_async(self, stdscr):
        """異步運行主循環"""
        # 初始化 curses 顏色
        curses.start_color()
        curses.use_default_colors()

        # 定義顏色對
        curses.init_pair(1, curses.COLOR_RED, -1)  # 錯誤/失敗
        curses.init_pair(2, curses.COLOR_GREEN, -1)  # 成功
        curses.init_pair(3, curses.COLOR_BLUE, -1)  # 藍色
        curses.init_pair(4, curses.COLOR_YELLOW, -1)  # 警告/同步中
        curses.init_pair(5, curses.COLOR_MAGENTA, -1)  # 品紅
        curses.init_pair(6, curses.COLOR_CYAN, -1)  # 青色/標題
        curses.init_pair(7, curses.COLOR_WHITE, -1)  # 白色/灰色
        curses.init_pair(8, -1, -1)  # 預設

        # 隱藏游標
        curses.curs_set(0)

        # 啟動同步任務
        for key, table_info in self.tables.items():
            task = asyncio.create_task(self._sync_table(table_info))
            self.sync_tasks[key] = task

        # 啟動配置監控
        config_task = asyncio.create_task(self._watch_config())

        # 啟動每日清理監控
        cleanup_task = asyncio.create_task(self._watch_daily_cleanup())

        # 啟動輸入處理
        input_task = asyncio.create_task(self._handle_input(stdscr))

        # UI 更新循環
        while not self.should_exit:
            try:
                self._draw_ui(stdscr)
                await asyncio.sleep(0.1)
            except KeyboardInterrupt:
                self.should_exit = True
                break
            except Exception as e:
                self._add_global_log(f"UI 更新錯誤: {e}", "ERROR")

        # 清理
        config_task.cancel()
        cleanup_task.cancel()
        input_task.cancel()
        for task in self.sync_tasks.values():
            task.cancel()

        # 等待所有任務結束
        await asyncio.gather(
            config_task,
            cleanup_task,
            input_task,
            *self.sync_tasks.values(),
            return_exceptions=True,
        )

    def run(self, stdscr):
        """運行主循環 (curses 入口)"""
        try:
            asyncio.run(self.run_async(stdscr))
        except KeyboardInterrupt:
            pass


def main():
    """主函數"""
    # 獲取配置檔案路徑
    script_dir = Path(__file__).parent
    config_path = script_dir / "config.yaml"

    if not config_path.exists():
        print(f"錯誤: 找不到配置檔案 {config_path}")
        sys.exit(1)

    # 創建監控器
    monitor = SyncMonitor(str(config_path))

    if not monitor.tables:
        print("警告: 沒有啟用的表格")
        print("請檢查 config.yaml 配置")
        sys.exit(1)

    # 啟動 TUI
    try:
        curses.wrapper(monitor.run)
    except KeyboardInterrupt:
        print("\n收到中斷信號，正在退出...")
    except Exception as e:
        print(f"\n發生錯誤: {e}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
