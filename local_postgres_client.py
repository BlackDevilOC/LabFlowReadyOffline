"""
LabFlow Local PostgreSQL Query Builder & Client Adapter
========================================================
Provides a Supabase-compatible API wrapper over local PostgreSQL (psycopg2).
Translates .table('x').select().eq().insert().update().execute() directly
into optimized local PostgreSQL queries.
"""

import os
import sys
import json
import logging
from typing import Dict, List, Any, Optional, Union
from datetime import datetime, timezone
import psycopg2
from psycopg2.extras import RealDictCursor

# Ensure local DB config is loaded
root_dir = os.path.dirname(os.path.abspath(__file__))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from local_postgres_engine import get_connection

logger = logging.getLogger("LabFlow.LocalPostgresClient")


class QueryResult:
    """Emulates Supabase API response object holding .data and .count."""
    def __init__(self, data: Any = None, count: Optional[int] = None):
        self.data = data
        self.count = count


class QueryBuilder:
    """Supabase/PostgREST compatible query builder targeting local PostgreSQL."""
    def __init__(self, table_name: str):
        # Handle table aliases if any
        table_map = {
            "patient_test_results": "test_results_all",
            "fitness_patients": "patients"
        }
        self.table_name = table_map.get(table_name, table_name)
        self.action = "SELECT"
        self.select_columns = "*"
        self.where_clauses: List[str] = []
        self.params: List[Any] = []
        self.payload: Any = None
        self.order_clause: Optional[str] = None
        self.limit_val: Optional[int] = None
        self.offset_val: Optional[int] = None
        self.is_single = False
        self.join_patients = False
        self.inner_join = False

    def select(self, *columns, count: Optional[str] = None):
        self.action = "SELECT"
        if columns:
            if len(columns) == 1 and isinstance(columns[0], str):
                self.select_columns = columns[0]
            else:
                self.select_columns = ", ".join(str(c) for c in columns)
        else:
            self.select_columns = "*"

        if "patients(" in self.select_columns or "patients!" in self.select_columns:
            self.join_patients = True
            if "patients!inner" in self.select_columns:
                self.inner_join = True
        return self

    def insert(self, data: Union[Dict, List[Dict]], upsert: bool = False):
        self.action = "INSERT"
        self.payload = data if isinstance(data, list) else [data]
        if upsert:
            self.is_upsert = True
        return self

    def upsert(self, data: Union[Dict, List[Dict]], on_conflict: Optional[str] = None):
        self.action = "INSERT"
        self.is_upsert = True
        self.on_conflict = on_conflict
        self.payload = data if isinstance(data, list) else [data]
        return self

    def update(self, data: Dict):
        self.action = "UPDATE"
        self.payload = data
        return self

    def delete(self):
        self.action = "DELETE"
        return self

    def eq(self, column: str, value: Any):
        col_ref = self._format_col(column)
        self.where_clauses.append(f"{col_ref} = %s")
        self.params.append(value)
        return self

    def neq(self, column: str, value: Any):
        col_ref = self._format_col(column)
        self.where_clauses.append(f"{col_ref} != %s")
        self.params.append(value)
        return self

    def gte(self, column: str, value: Any):
        col_ref = self._format_col(column)
        self.where_clauses.append(f"{col_ref} >= %s")
        self.params.append(value)
        return self

    def lte(self, column: str, value: Any):
        col_ref = self._format_col(column)
        self.where_clauses.append(f"{col_ref} <= %s")
        self.params.append(value)
        return self

    def gt(self, column: str, value: Any):
        col_ref = self._format_col(column)
        self.where_clauses.append(f"{col_ref} > %s")
        self.params.append(value)
        return self

    def lt(self, column: str, value: Any):
        col_ref = self._format_col(column)
        self.where_clauses.append(f"{col_ref} < %s")
        self.params.append(value)
        return self

    def ilike(self, column: str, pattern: str):
        col_ref = self._format_col(column)
        self.where_clauses.append(f"{col_ref} ILIKE %s")
        self.params.append(pattern)
        return self

    def in_(self, column: str, values: List[Any]):
        col_ref = self._format_col(column)
        self.where_clauses.append(f"{col_ref} = ANY(%s)")
        self.params.append(values)
        return self

    def order(self, column: str, desc: bool = False):
        col_ref = self._format_col(column)
        direction = "DESC" if desc else "ASC"
        self.order_clause = f"ORDER BY {col_ref} {direction}"
        return self

    def limit(self, n: int):
        self.limit_val = n
        return self

    def range(self, start: int, end: int):
        self.limit_val = max(0, end - start + 1)
        self.offset_val = start
        return self

    def single(self):
        self.is_single = True
        return self

    def _format_col(self, col: str) -> str:
        if self.join_patients:
            if col.startswith("patients."):
                sub_col = col.split(".", 1)[1]
                return f'p."{sub_col}"' if sub_col == "user" else f'p.{sub_col}'
            elif col.startswith("test_results_all."):
                sub_col = col.split(".", 1)[1]
                return f't."{sub_col}"' if sub_col == "user" else f't.{sub_col}'
            
            patient_cols = ["relation", "relation_name", "age", "gender", "shift", "mobile", "patient_token", "user", "user_id"]
            if col in patient_cols:
                return f'p."{col}"' if col == "user" else f"p.{col}"
            return f't."{col}"'

        if "." in col:
            t_name, sub_col = col.split(".", 1)
            return f'"{t_name}"."{sub_col}"' if sub_col == "user" else f'"{t_name}".{sub_col}'

        if col == "user":
            return '"user"'
        return f'"{col}"'

    def execute(self) -> QueryResult:
        conn = get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        try:
            if self.action == "SELECT":
                data = self._execute_select(cursor)
            elif self.action == "INSERT":
                data = self._execute_insert(cursor)
            elif self.action == "UPDATE":
                data = self._execute_update(cursor)
            elif self.action == "DELETE":
                data = self._execute_delete(cursor)
            else:
                data = []

            conn.commit()
            cursor.close()
            conn.close()

            if self.is_single:
                single_item = data[0] if (isinstance(data, list) and len(data) > 0) else None
                return QueryResult(data=single_item)

            return QueryResult(data=data, count=len(data) if isinstance(data, list) else 0)

        except Exception as e:
            conn.rollback()
            cursor.close()
            conn.close()
            logger.error(f"Execution error on table '{self.table_name}': {e}")
            raise

    def _execute_select(self, cursor) -> List[Dict]:
        where_sql = ("WHERE " + " AND ".join(self.where_clauses)) if self.where_clauses else ""
        order_sql = self.order_clause or ""
        limit_sql = f"LIMIT {self.limit_val}" if self.limit_val else ""
        offset_sql = f"OFFSET {self.offset_val}" if self.offset_val is not None else ""

        if self.join_patients and self.table_name == "test_results_all":
            # Joined query between test_results_all and patients
            join_type = "INNER JOIN" if self.inner_join else "LEFT JOIN"
            sql = f"""
                SELECT t.id, t.mr_no, t.patient_name, t.test_name, t.category, t.test_values, t.status, t.created_at, t.remarks,
                       p.relation, p.relation_name, p.age, p.gender, p.shift, p.mobile, p.patient_token, p."user", p.user_id
                FROM public.test_results_all t
                {join_type} public.patients p ON t.mr_no = p.mr_no
                {where_sql}
                {order_sql}
                {limit_sql} {offset_sql};
            """
            cursor.execute(sql, self.params)
            rows = cursor.fetchall()
            
            # Format joined rows matching Supabase nested patient object structure
            results = []
            for r in rows:
                r_dict = dict(r)
                patient_info = {
                    "relation": r_dict.pop("relation", None),
                    "relation_name": r_dict.pop("relation_name", None),
                    "age": r_dict.pop("age", None),
                    "gender": r_dict.pop("gender", None),
                    "shift": r_dict.pop("shift", None),
                    "mobile": r_dict.pop("mobile", None),
                    "patient_token": r_dict.pop("patient_token", None),
                    "user": r_dict.pop("user", None),
                    "user_id": r_dict.pop("user_id", None)
                }
                r_dict["patients"] = patient_info
                results.append(r_dict)
            return results

        # Standard SELECT query
        sql = f'SELECT * FROM public."{self.table_name}" {where_sql} {order_sql} {limit_sql} {offset_sql};'
        cursor.execute(sql, self.params)
        return [dict(r) for r in cursor.fetchall()]

    def _execute_insert(self, cursor) -> List[Dict]:
        if not self.payload:
            return []

        inserted = []
        for item in self.payload:
            clean_item = dict(item)

            # Auto-handle NULL or missing mr_no for patients
            if self.table_name == "patients":
                if "mr_no" in clean_item and (clean_item["mr_no"] is None or str(clean_item["mr_no"]).strip() in ["", "None", "null"]):
                    clean_item.pop("mr_no", None)
                if "mr_no" not in clean_item:
                    cursor.execute("SELECT COALESCE(MAX(mr_no), 0) + 1 AS next_mr FROM public.patients;")
                    row = cursor.fetchone()
                    clean_item["mr_no"] = row["next_mr"] if isinstance(row, dict) else row[0]

            # Remove None id if auto-generated by DB
            if "id" in clean_item and clean_item["id"] is None:
                clean_item.pop("id", None)

            cols = [f'"{k}"' for k in clean_item.keys()]
            vals = list(clean_item.values())
            
            # Format JSON dicts for JSONB columns
            clean_vals = []
            for v in vals:
                if isinstance(v, (dict, list)):
                    clean_vals.append(json.dumps(v))
                else:
                    clean_vals.append(v)

            cols_sql = ", ".join(cols)
            placeholders = ", ".join(["%s"] * len(clean_vals))
            
            if getattr(self, "is_upsert", False):
                raw_conflict = getattr(self, "on_conflict", None) or ("snapshot_type,date_from,date_to" if self.table_name == "analytics_snapshots" else "id")
                conflict_cols = [f'"{c.strip()}"' for c in raw_conflict.split(",")]
                conflict_target = ", ".join(conflict_cols)
                
                raw_cols = [c.strip() for c in raw_conflict.split(",")]
                update_cols = [f'"{k}" = EXCLUDED."{k}"' for k in clean_item.keys() if k not in raw_cols and k != "id"]
                if update_cols:
                    conflict_sql = f' ON CONFLICT ({conflict_target}) DO UPDATE SET ' + ", ".join(update_cols)
                else:
                    conflict_sql = f' ON CONFLICT ({conflict_target}) DO NOTHING'
                sql = f'INSERT INTO public."{self.table_name}" ({cols_sql}) VALUES ({placeholders}){conflict_sql} RETURNING *;'
            else:
                sql = f'INSERT INTO public."{self.table_name}" ({cols_sql}) VALUES ({placeholders}) RETURNING *;'

            cursor.execute(sql, clean_vals)
            row = cursor.fetchone()
            if row:
                inserted.append(dict(row))

        return inserted

    def _execute_update(self, cursor) -> List[Dict]:
        if not self.payload:
            return []

        set_clauses = []
        set_params = []

        for k, v in self.payload.items():
            set_clauses.append(f'"{k}" = %s')
            if isinstance(v, (dict, list)):
                set_params.append(json.dumps(v))
            else:
                set_params.append(v)

        set_sql = ", ".join(set_clauses)
        where_sql = ("WHERE " + " AND ".join(self.where_clauses)) if self.where_clauses else ""
        all_params = set_params + self.params

        sql = f'UPDATE public."{self.table_name}" SET {set_sql} {where_sql} RETURNING *;'
        cursor.execute(sql, all_params)
        return [dict(r) for r in cursor.fetchall()]

    def _execute_delete(self, cursor) -> List[Dict]:
        where_sql = ("WHERE " + " AND ".join(self.where_clauses)) if self.where_clauses else ""
        sql = f'DELETE FROM public."{self.table_name}" {where_sql} RETURNING *;'
        cursor.execute(sql, self.params)
        return [dict(r) for r in cursor.fetchall()]


class LocalPostgresClient:
    """Client class mimicking Supabase Client interface."""
    def table(self, table_name: str) -> QueryBuilder:
        return QueryBuilder(table_name)


def get_local_postgres_client() -> LocalPostgresClient:
    """Factory function returning a LocalPostgresClient instance."""
    return LocalPostgresClient()
