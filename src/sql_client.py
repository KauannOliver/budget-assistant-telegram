import pyodbc
import os
from typing import List, Dict, Any

class SQLClient:
    def __init__(self):
        self.server = os.getenv("SQL_SERVER", "127.0.0.1")
        self.database = os.getenv("SQL_DATABASE", "demo_budget")
        self.user = os.getenv("SQL_USER")
        self.password = os.getenv("SQL_PASSWORD")
        self.trusted = os.getenv("SQL_TRUSTED_CONNECTION", "no").lower() == "yes"
        
    def _get_connection(self):
        # Using 'SQL Server' as the most common legacy driver present on Windows
        driver = os.getenv("SQL_DRIVER", "SQL Server")
        conn_str = (
            f"DRIVER={{{driver}}};"
            f"SERVER={self.server};"
            f"DATABASE={self.database};"
        )
        if self.trusted:
            conn_str += "Trusted_Connection=yes;"
        else:
            conn_str += f"UID={self.user};PWD={self.password};"
        return pyodbc.connect(conn_str)

    def execute_query(self, query: str, params: tuple = ()) -> List[Dict[str, Any]]:
        """Executes a SELECT query (read-only by agent definition) and returns the results."""
        if not self.trusted and (self.user is None or self.password is None):
            return [{"error": "Missing SQL Server credentials in environment variables."}]
            
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(query, params)
                    if cursor.description is None:
                        return [] # Fallback for queries without result sets
                    
                    columns = [column[0] for column in cursor.description]
                    results = []
                    from decimal import Decimal
                    for row in cursor.fetchall():
                        # Convert Decimal or special types into native Python types for JSON serialization
                        row_dict = {}
                        for i, value in enumerate(row):
                            if isinstance(value, Decimal):
                                value = float(value)
                            row_dict[columns[i]] = value
                        results.append(row_dict)
                    return results
        except Exception as e:
            print(f"SQL Error: {e}")
            return [{"error": str(e)}]
