#!/usr/bin/env python3
"""
JIRA-Lark 表格掃描清理工具

功能:
1. 去除重複項目（以單號為判斷依據）
2. 去除空白單號項目
3. 檢查單號是否存在於 JIRA，若不存在則刪除
4. 清理完成後重建快取
"""

import argparse
import logging
import sys
import time
from typing import Dict, List, Optional, Set, Tuple

from data_cleaner import DataCleaner
from logger import setup_logging
from sync_coordinator import SyncCoordinator


class TableScanCleaner:
    """表格掃描清理器 - 基於現有 DataCleaner 與 SyncCoordinator"""

    def __init__(self, config_file: str = "config.yaml"):
        self.logger = logging.getLogger(f"{__name__}.TableScanCleaner")
        self.cleaner = DataCleaner(config_file)
        self.config_manager = self.cleaner.config_manager
        self.jira_client = self.cleaner.jira_client
        self.lark_client = self.cleaner.lark_client
        self._sync_coordinator = None
        self._sync_logger = None

    def _get_target_tables(self, team: Optional[str], table: Optional[str]) -> List[Dict]:
        if table and not team:
            raise ValueError("指定 --table 時必須同時指定 --team")

        targets = []
        if team:
            team_config = self.config_manager.get_team_config(team)
            if not team_config:
                raise ValueError(f"找不到團隊或未啟用: {team}")

            tables = team_config.get("tables", {})
            if table:
                table_config = tables.get(table)
                if not table_config or not table_config.get("enabled", True):
                    raise ValueError(f"找不到表格或未啟用: {team}.{table}")
                targets.append(
                    {
                        "team": team,
                        "table": table,
                        "team_config": team_config,
                        "table_config": table_config,
                    }
                )
                return targets

            for table_name, table_config in tables.items():
                if table_config.get("enabled", True):
                    targets.append(
                        {
                            "team": team,
                            "table": table_name,
                            "team_config": team_config,
                            "table_config": table_config,
                        }
                    )
            return targets

        for team_name in self.config_manager.get_enabled_teams():
            team_config = self.config_manager.get_team_config(team_name)
            if not team_config:
                continue
            for table_name, table_config in team_config.get("tables", {}).items():
                if table_config.get("enabled", True):
                    targets.append(
                        {
                            "team": team_name,
                            "table": table_name,
                            "team_config": team_config,
                            "table_config": table_config,
                        }
                    )
        return targets

    def _collect_records(self, records: List[Dict], ticket_field: str) -> Tuple[List[Dict], Dict[str, List[Dict]]]:
        blank_records = []
        records_by_key: Dict[str, List[Dict]] = {}

        for record in records:
            issue_key = self.cleaner._extract_issue_key_from_record(record, ticket_field)
            issue_key = str(issue_key).strip() if issue_key else ""

            if not issue_key:
                blank_records.append(record)
                continue

            record["_extracted_issue_key"] = issue_key
            record["_created_time"] = record.get("created_time", 0)
            record["_modified_time"] = record.get("modified_time", 0)
            records_by_key.setdefault(issue_key, []).append(record)

        return blank_records, records_by_key

    def _dedupe_records(self, records: List[Dict]) -> List[Dict]:
        unique_records = []
        seen_ids: Set[str] = set()

        for record in records:
            record_id = record.get("record_id")
            if not record_id:
                unique_records.append(record)
                continue
            if record_id in seen_ids:
                continue
            seen_ids.add(record_id)
            unique_records.append(record)

        return unique_records

    def _fetch_existing_issue_keys(
        self, issue_keys: List[str], batch_size: int = 50
    ) -> Tuple[Set[str], Set[str]]:
        existing_keys: Set[str] = set()
        failed_keys: Set[str] = set()

        if not issue_keys:
            return existing_keys, failed_keys

        total_batches = (len(issue_keys) + batch_size - 1) // batch_size
        self.logger.info(f"分批檢查 JIRA Issue Keys: {len(issue_keys)} 個，批次 {batch_size}，共 {total_batches} 批")

        for i in range(0, len(issue_keys), batch_size):
            batch_keys = issue_keys[i : i + batch_size]
            batch_num = i // batch_size + 1

            try:
                keys_str = ", ".join([f'"{key}"' for key in batch_keys])
                jql = f"key IN ({keys_str})"
                issues_dict = self.jira_client.search_issues(jql, fields=["key"])
                existing_keys.update(issues_dict.keys())
                self.logger.debug(f"批次 {batch_num}/{total_batches} 成功，找到 {len(issues_dict)} 筆")
            except Exception as e:
                self.logger.error(f"批次 {batch_num}/{total_batches} JIRA 檢查失敗: {e}")
                failed_keys.update(batch_keys)
            time.sleep(0.2)

        return existing_keys, failed_keys

    def scan_and_clean_table(
        self,
        team: str,
        table: str,
        duplicate_strategy: str = "keep-latest",
        dry_run: bool = True,
        confirm: bool = True,
    ) -> Dict:
        result = {
            "team": team,
            "table": table,
            "total_records": 0,
            "blank_records": 0,
            "duplicate_groups": 0,
            "duplicate_records": 0,
            "duplicate_records_to_delete": 0,
            "missing_issue_keys": 0,
            "missing_records": 0,
            "jira_check_failed_keys": 0,
            "records_to_delete": 0,
            "deleted_records": 0,
            "success": True,
            "error": None,
        }

        try:
            team_config = self.config_manager.get_team_config(team)
            if not team_config:
                raise ValueError(f"找不到團隊或未啟用: {team}")

            table_config = team_config.get("tables", {}).get(table)
            if not table_config or not table_config.get("enabled", True):
                raise ValueError(f"找不到表格或未啟用: {team}.{table}")

            wiki_token = team_config["wiki_token"]
            table_id = table_config["table_id"]
            ticket_field = table_config.get("ticket_field", "Issue Key")

            if not self.lark_client.set_wiki_token(wiki_token):
                raise RuntimeError(f"無法設定 wiki_token: {team}.{table}")

            all_records = self.lark_client.get_all_records(table_id)
            result["total_records"] = len(all_records)

            blank_records, records_by_key = self._collect_records(all_records, ticket_field)
            result["blank_records"] = len(blank_records)

            duplicates = {k: v for k, v in records_by_key.items() if len(v) > 1}
            result["duplicate_groups"] = len(duplicates)
            result["duplicate_records"] = sum(len(records) for records in duplicates.values())

            duplicate_records_to_delete = self.cleaner.choose_records_to_keep(
                duplicates, duplicate_strategy
            )
            result["duplicate_records_to_delete"] = len(duplicate_records_to_delete)

            issue_keys = list(records_by_key.keys())
            existing_keys, failed_keys = self._fetch_existing_issue_keys(issue_keys)
            missing_keys = set(issue_keys) - existing_keys - failed_keys

            missing_records = []
            for issue_key in missing_keys:
                missing_records.extend(records_by_key.get(issue_key, []))

            result["missing_issue_keys"] = len(missing_keys)
            result["missing_records"] = len(missing_records)
            result["jira_check_failed_keys"] = len(failed_keys)

            records_to_delete = self._dedupe_records(
                blank_records + duplicate_records_to_delete + missing_records
            )
            result["records_to_delete"] = len(records_to_delete)

            if records_to_delete and confirm and not dry_run:
                print("\n⚠️  即將刪除以下記錄")
                print(f"團隊: {team}")
                print(f"表格: {table}")
                print(f"空白單號: {result['blank_records']}")
                print(
                    f"重複組數: {result['duplicate_groups']}，重複記錄: {result['duplicate_records']}，將刪除: {result['duplicate_records_to_delete']}"
                )
                print(
                    f"JIRA 不存在單號: {result['missing_issue_keys']}，記錄數: {result['missing_records']}"
                )
                if result["jira_check_failed_keys"] > 0:
                    print(f"JIRA 檢查失敗單號: {result['jira_check_failed_keys']}（本次不刪除）")
                print(f"總刪除數: {result['records_to_delete']}")

                response = input("\n確定要繼續嗎？ (yes/no): ").strip().lower()
                if response not in ("yes", "y"):
                    self.logger.info("使用者取消操作")
                    return result

            deleted_count = self.cleaner.delete_lark_records(team, table, records_to_delete, dry_run)
            result["deleted_records"] = deleted_count

            self._print_table_summary(result, dry_run)
            return result

        except Exception as e:
            self.logger.error(f"掃描清理失敗: {team}.{table}, {e}")
            result["success"] = False
            result["error"] = str(e)
            return result

    def rebuild_cache(self, team: Optional[str] = None, table: Optional[str] = None) -> Dict:
        if not self._sync_coordinator:
            global_config = self.config_manager.get_global_config()
            if not self._sync_logger:
                log_config = {
                    "log_level": global_config.get("log_level", "INFO"),
                    "log_file": global_config.get("log_file", "jira_lark_sync.log"),
                    "max_size": global_config.get("log_max_size", "10MB"),
                    "backup_count": global_config.get("log_backup_count", 5),
                }
                self._sync_logger = setup_logging(log_config)
            self._sync_coordinator = SyncCoordinator(
                config_manager=self.config_manager,
                schema_path=global_config.get("schema_file", "schema.yaml"),
                base_data_dir=global_config.get("data_directory", "data"),
                logger=self._sync_logger,
            )
        return self._sync_coordinator.rebuild_cache_from_lark(team, table)

    def _print_table_summary(self, result: Dict, dry_run: bool) -> None:
        print(f"\n📊 掃描結果: {result['team']}.{result['table']}")
        print(f"總記錄: {result['total_records']}")
        print(f"空白單號: {result['blank_records']}")
        print(
            f"重複組數: {result['duplicate_groups']}，重複記錄: {result['duplicate_records']}，將刪除: {result['duplicate_records_to_delete']}"
        )
        print(
            f"JIRA 不存在單號: {result['missing_issue_keys']}，記錄數: {result['missing_records']}"
        )
        if result["jira_check_failed_keys"] > 0:
            print(f"JIRA 檢查失敗單號: {result['jira_check_failed_keys']}（本次不刪除）")
        if dry_run:
            print(f"【乾跑】預計刪除: {result['records_to_delete']}")
        else:
            print(f"實際刪除: {result['deleted_records']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="JIRA-Lark 表格掃描清理工具")
    parser.add_argument("--team", help="指定團隊名稱")
    parser.add_argument("--table", help="指定表格名稱")
    parser.add_argument("--dry-run", action="store_true", help="乾跑模式，不實際刪除")
    parser.add_argument("--no-confirm", action="store_true", help="跳過確認提示")
    parser.add_argument(
        "--duplicate-strategy",
        choices=["keep-latest", "keep-oldest"],
        default="keep-latest",
        help="重複記錄保留策略",
    )
    parser.add_argument("--config", default="config.yaml", help="配置檔案路徑")
    parser.add_argument("--verbose", "-v", action="store_true", help="詳細輸出")
    args = parser.parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    try:
        cleaner = TableScanCleaner(args.config)
        targets = cleaner._get_target_tables(args.team, args.table)
        if not targets:
            print("❌ 沒有找到任何可處理的表格")
            sys.exit(1)

        total_stats = {
            "tables_scanned": 0,
            "records_scanned": 0,
            "blank_records": 0,
            "duplicate_groups": 0,
            "duplicate_records": 0,
            "duplicate_records_to_delete": 0,
            "missing_issue_keys": 0,
            "missing_records": 0,
            "jira_check_failed_keys": 0,
            "records_to_delete": 0,
            "deleted_records": 0,
            "errors": 0,
        }

        for target in targets:
            result = cleaner.scan_and_clean_table(
                team=target["team"],
                table=target["table"],
                duplicate_strategy=args.duplicate_strategy,
                dry_run=args.dry_run,
                confirm=not args.no_confirm,
            )

            total_stats["tables_scanned"] += 1
            total_stats["records_scanned"] += result["total_records"]
            total_stats["blank_records"] += result["blank_records"]
            total_stats["duplicate_groups"] += result["duplicate_groups"]
            total_stats["duplicate_records"] += result["duplicate_records"]
            total_stats["duplicate_records_to_delete"] += result["duplicate_records_to_delete"]
            total_stats["missing_issue_keys"] += result["missing_issue_keys"]
            total_stats["missing_records"] += result["missing_records"]
            total_stats["jira_check_failed_keys"] += result["jira_check_failed_keys"]
            total_stats["records_to_delete"] += result["records_to_delete"]
            total_stats["deleted_records"] += result["deleted_records"]
            if not result["success"]:
                total_stats["errors"] += 1

        print("\n✅ 全部表格掃描完成")
        print(f"表格數量: {total_stats['tables_scanned']}")
        print(f"總記錄數: {total_stats['records_scanned']}")
        print(f"空白單號: {total_stats['blank_records']}")
        print(
            f"重複組數: {total_stats['duplicate_groups']}，重複記錄: {total_stats['duplicate_records']}，將刪除: {total_stats['duplicate_records_to_delete']}"
        )
        print(
            f"JIRA 不存在單號: {total_stats['missing_issue_keys']}，記錄數: {total_stats['missing_records']}"
        )
        if total_stats["jira_check_failed_keys"] > 0:
            print(f"JIRA 檢查失敗單號: {total_stats['jira_check_failed_keys']}（本次不刪除）")
        if args.dry_run:
            print(f"【乾跑】預計刪除: {total_stats['records_to_delete']}")
        else:
            print(f"實際刪除: {total_stats['deleted_records']}")

        if total_stats["errors"] > 0:
            print(f"❌ 發生 {total_stats['errors']} 個錯誤，略過快取重建")
            sys.exit(1)

        if args.dry_run:
            print("【乾跑】略過快取重建")
            return

        rebuild_result = cleaner.rebuild_cache(args.team, args.table)
        if not rebuild_result.get("success", False):
            print(f"❌ 快取重建失敗: {rebuild_result.get('error', '未知錯誤')}")
            sys.exit(1)

        print("✅ 快取重建完成")

    except KeyboardInterrupt:
        print("\n⚠️ 操作被用戶中止")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 執行失敗: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
