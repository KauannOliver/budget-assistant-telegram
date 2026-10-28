import json
from .sql_client import SQLClient

class AgentTools:
    """Provides tools for the LLM to call and fetch FP&A data from SQL.
    Uses the OFFICIAL query provided by the user for CloseClawdio.
    """
    
    def __init__(self, sql_client: SQLClient):
        self.sql_client = sql_client

    def _get_base_query(self, cost_center_code: str = None, period_yyyy_mm: str = None) -> str:
        """Returns the base analytical query provided by the user as a CTE.
        Injects filters into the base query for performance where possible.
        """
        # Default filters
        year_filter = "SUBSTRING(AKD.AKD_DATA, 1, 4) BETWEEN '2026' AND '2026'"
        month_filter = "SUBSTRING(AKD.AKD_DATA, 5, 2) BETWEEN '01' AND '12'"
        
        if period_yyyy_mm and len(period_yyyy_mm) == 7:
            y, m = period_yyyy_mm.split('-')
            year_filter = f"SUBSTRING(AKD.AKD_DATA, 1, 4) = '{y}'"
            month_filter = f"SUBSTRING(AKD.AKD_DATA, 5, 2) = '{m}'"

        cc_filter = ""
        if cost_center_code:
            # RTRIM added for robust matching of padded cost center codes/names
            cc_filter = f"AND (RTRIM(AKD.AKD_CC) = '{cost_center_code}' OR CTT.CTT_DESC01 LIKE '%{cost_center_code}%')"

        def get_company_sql(suffix):
            return f"""
                SELECT  
                    RTRIM(AKD.AKD_CC) AS [COD. C.CUSTO], 
                    RTRIM(CTT.CTT_DESC01) AS [DESC. C.CUSTO], 
                    RTRIM(AKD.AKD_CO) AS [COD. C.CONTA], 
                    RTRIM(AK5.AK5_DESCRI) AS [DESC. C.CONTA], 
                    RTRIM(AKD.AKD_ITCTB) AS [COD. ITEM CTB.], 
                    RTRIM(ISNULL(CTD.CTD_DESC01, '')) AS [DESC. ITEM CTB.], 
                    AKD.AKD_DATA AS [DATA], 
                    RTRIM(CASE WHEN AKD.AKD_TPSALD = 'ES' THEN 'RE' ELSE AKD.AKD_TPSALD END) AS [TIPO SALDO], 
                    AKD.AKD_ZORIG,
                    CASE 
                        WHEN AKD.AKD_ZORIG = 'SC1' THEN 'SOL. COMPRA'
                        WHEN AKD.AKD_ZORIG = 'SC7' THEN 'PED. COMPRA'
                        WHEN AKD.AKD_ZORIG = 'SD1' THEN 'DOC. ENTRADA'
                        WHEN AKD.AKD_ZORIG = 'SE2' THEN 'TIT. A PAGAR'
                        WHEN AKD.AKD_ZORIG = 'SE1' THEN 'TIT. A RECEBER'
                        WHEN AKD.AKD_ZORIG = 'CNF' THEN 'CONTRATO'
                        WHEN AKD.AKD_ZORIG = 'CNE' THEN 'MEDIÇÃO'
                        WHEN AKD.AKD_ZORIG = 'SD3' THEN 'MOV. INTERNA'
                        WHEN AKD.AKD_ZORIG = 'SD2' THEN 'DEVOLUÇÃO'
                    END AS TIPO_DOC,
                    RTRIM(CASE WHEN AKD.AKD_ZORIG = 'SE1' THEN ISNULL(SA1.A1_NREDUZ, '') ELSE ISNULL(SA2.A2_NREDUZ, '') END) AS NOME_FORN,
                    RTRIM(AKD.AKD_ZPROD) AS PRODUTO,
                    RTRIM(ISNULL(SB1.B1_DESC, '')) AS DESC_PROD,
                    CASE WHEN AKD.AKD_LCTBLQ <> '' THEN 'Sim' ELSE 'Não' END AS [LANC. BLOQ],
                    ROUND(SUM(CASE 
                        WHEN AKD.AKD_TIPO = '1' AND AKD.AKD_TPSALD ='ES' THEN ROUND(AKD.AKD_VALOR1, 2) * -1 
                        WHEN AKD.AKD_TIPO = '1' AND AKD.AKD_TPSALD <>'ES' THEN ROUND(AKD.AKD_VALOR1, 2) 
                        WHEN AKD.AKD_TIPO = '2' AND AKD.AKD_TPSALD ='ES' THEN ROUND(AKD.AKD_VALOR1, 2)  
                        WHEN AKD.AKD_TIPO = '2' AND AKD.AKD_TPSALD <>'ES' THEN ROUND(AKD.AKD_VALOR1, 2) * -1
                    END), 2) AS [VALOR]
                FROM AKD{suffix} AKD WITH (NOLOCK)
                INNER JOIN AK5{suffix} AK5 WITH (NOLOCK) ON AK5.AK5_CODIGO = AKD.AKD_CO AND AK5.D_E_L_E_T_ = ''  
                INNER JOIN CTT{suffix} CTT WITH (NOLOCK) ON CTT.CTT_CUSTO = AKD.AKD_CC AND CTT.D_E_L_E_T_ = ''
                LEFT JOIN CTD{suffix} CTD WITH (NOLOCK) ON CTD.CTD_ITEM = AKD.AKD_ITCTB AND CTD.D_E_L_E_T_ = ''
                LEFT JOIN SA2{suffix} SA2 WITH (NOLOCK) ON SA2.A2_FILIAL = '' AND SA2.A2_COD = AKD.AKD_ZCLIFO AND SA2.A2_LOJA = AKD.AKD_ZLOJA AND SA2.D_E_L_E_T_ = ''
                LEFT JOIN SA1{suffix} SA1 WITH (NOLOCK) ON SA1.A1_FILIAL = '' AND SA1.A1_COD = AKD.AKD_ZCLIFO AND SA1.A1_LOJA = AKD.AKD_ZLOJA AND SA1.D_E_L_E_T_ = ''
                LEFT JOIN SB1{suffix} SB1 WITH (NOLOCK) ON SB1.B1_FILIAL = '' AND SB1.B1_COD = AKD.AKD_ZPROD AND SB1.D_E_L_E_T_ = ''
                WHERE AKD.D_E_L_E_T_ = '' AND AKD.AKD_STATUS = '1' AND AKD.AKD_PROCES <> '000356'
                AND {year_filter} AND {month_filter}
                {cc_filter}
                GROUP BY 
                    AKD.AKD_CC, CTT.CTT_DESC01, AKD.AKD_CO, AK5.AK5_DESCRI, AKD.AKD_ITCTB, ISNULL(CTD.CTD_DESC01, ''), 
                    AKD.AKD_DATA, AKD.AKD_TPSALD,
                    AKD.AKD_ZORIG, AKD.AKD_ZCLIFO, AKD.AKD_ZLOJA, AKD.AKD_ZPROD,
                    CASE WHEN AKD.AKD_ZORIG = 'SE1' THEN ISNULL(SA1.A1_NREDUZ, '') ELSE ISNULL(SA2.A2_NREDUZ, '') END,
                    ISNULL(SB1.B1_DESC, ''), AKD.AKD_LCTBLQ
            """

        union_sql = f"{get_company_sql('010')} UNION ALL {get_company_sql('090')}"
        return f"WITH BaseData AS ({union_sql})"

    # ─────────────────────────────────────────────────────────────────────────
    # Public Tools
    # ─────────────────────────────────────────────────────────────────────────

    def search_cost_center(self, name_query: str) -> str:
        """Finds cost center codes (COD. C.CUSTO) from partial name lookups."""
        query = f"""
            SELECT DISTINCT RTRIM(CTT_CUSTO) as code, RTRIM(CTT_DESC01) as name
            FROM CTT010
            WHERE (CTT_CUSTO LIKE '%{name_query}%' OR CTT_DESC01 LIKE '%{name_query}%') AND D_E_L_E_T_ = ''
            UNION ALL
            SELECT DISTINCT RTRIM(CTT_CUSTO) as code, RTRIM(CTT_DESC01) as name
            FROM CTT090
            WHERE (CTT_CUSTO LIKE '%{name_query}%' OR CTT_DESC01 LIKE '%{name_query}%') AND D_E_L_E_T_ = ''
        """
        return json.dumps(self.sql_client.execute_query(query))

    def get_budget_vs_actual_summary(self, cost_center_code: str = None, period_yyyy_mm: str = None) -> str:
        base = self._get_base_query(cost_center_code, period_yyyy_mm)
        query = f"{base} SELECT SUM(CASE WHEN [TIPO SALDO] = 'OR' THEN [VALOR] ELSE 0 END) as Budget_OR, SUM(CASE WHEN [TIPO SALDO] = 'RE' THEN [VALOR] ELSE 0 END) as Actual_RE, SUM(CASE WHEN [TIPO SALDO] = 'EX' THEN [VALOR] ELSE 0 END) as Extra_EX, SUM(CASE WHEN [TIPO SALDO] = 'EM' THEN [VALOR] ELSE 0 END) as Commitment_EM FROM BaseData"
        return json.dumps(self.sql_client.execute_query(query))

    def get_budget_vs_actual_by_cost_center(self, period_yyyy_mm: str = None, limit: int = 10) -> str:
        base = self._get_base_query(None, period_yyyy_mm)
        query = f"{base} SELECT TOP {limit} [COD. C.CUSTO] as CostCenterCode, MAX([DESC. C.CUSTO]) as CostCenterName, SUM(CASE WHEN [TIPO SALDO] = 'OR' THEN [VALOR] ELSE 0 END) as Budget_OR, SUM(CASE WHEN [TIPO SALDO] = 'RE' THEN [VALOR] ELSE 0 END) as Actual_RE FROM BaseData GROUP BY [COD. C.CUSTO] ORDER BY Actual_RE DESC"
        return json.dumps(self.sql_client.execute_query(query))

    def get_budget_vs_actual_by_account(self, cost_center_code: str = None, period_yyyy_mm: str = None, limit: int = 10) -> str:
        base = self._get_base_query(cost_center_code, period_yyyy_mm)
        query = f"{base} SELECT TOP {limit} [COD. C.CONTA] as AccountCode, MAX([DESC. C.CONTA]) as AccountName, SUM(CASE WHEN [TIPO SALDO] = 'OR' THEN [VALOR] ELSE 0 END) as Budget_OR, SUM(CASE WHEN [TIPO SALDO] = 'RE' THEN [VALOR] ELSE 0 END) as Actual_RE FROM BaseData GROUP BY [COD. C.CONTA] ORDER BY Actual_RE DESC"
        return json.dumps(self.sql_client.execute_query(query))

    def get_supplier_breakdown(self, cost_center_code: str = None, period_yyyy_mm: str = None, limit: int = 5) -> str:
        base = self._get_base_query(cost_center_code, period_yyyy_mm)
        query = f"{base} SELECT TOP {limit} NOME_FORN as Supplier, SUM([VALOR]) as Total_Spent FROM BaseData WHERE [TIPO SALDO] = 'RE' AND NOME_FORN <> '' GROUP BY NOME_FORN ORDER BY Total_Spent DESC"
        return json.dumps(self.sql_client.execute_query(query))

    def get_product_breakdown(self, cost_center_code: str = None, period_yyyy_mm: str = None, limit: int = 5) -> str:
        base = self._get_base_query(cost_center_code, period_yyyy_mm)
        query = f"{base} SELECT TOP {limit} DESC_PROD as Product, SUM([VALOR]) as Total_Spent FROM BaseData WHERE [TIPO SALDO] = 'RE' AND DESC_PROD <> '' GROUP BY DESC_PROD ORDER BY Total_Spent DESC"
        return json.dumps(self.sql_client.execute_query(query))

    def get_available_balance_view(self, cost_center_code: str = None, period_yyyy_mm: str = None) -> str:
        base = self._get_base_query(cost_center_code, period_yyyy_mm)
        query = f"{base} SELECT SUM(CASE WHEN [TIPO SALDO] = 'OR' THEN [VALOR] ELSE 0 END) as Budget, SUM(CASE WHEN [TIPO SALDO] = 'EX' THEN [VALOR] ELSE 0 END) as Extra, SUM(CASE WHEN [TIPO SALDO] = 'RE' THEN [VALOR] ELSE 0 END) as Actual, SUM(CASE WHEN [TIPO SALDO] = 'EM' THEN [VALOR] ELSE 0 END) as Commitment, SUM(CASE WHEN [TIPO SALDO] IN ('OR','EX') THEN [VALOR] ELSE -[VALOR] END) as Net_Balance FROM BaseData"
        return json.dumps(self.sql_client.execute_query(query))

    def get_openai_tools_definition(self):
        definitions = [
            ("search_cost_center", "Finds cost center codes by name (e.g., 'TIC'). Use this if you only have a name."),
            ("get_budget_vs_actual_summary", "Totals for Budget (OR), Actual (RE), Extra Budget (EX), and Commitment (EM)."),
            ("get_budget_vs_actual_by_cost_center", "Rank cost centers by spending."),
            ("get_budget_vs_actual_by_account", "Rank accounts (COD. C.CONTA) by spending."),
            ("get_supplier_breakdown", "Top suppliers driving actual spend."),
            ("get_product_breakdown", "Top products driving actual spend."),
            ("get_available_balance_view", "Calculates OR + EX - RE - EM.")
        ]
        tools = []
        for name, desc in definitions:
            props = {"period_yyyy_mm": {"type": "string", "description": "Format YYYY-MM"}}
            if name == "search_cost_center":
                props = {"name_query": {"type": "string", "description": "Name or part of code (e.g. 'TIC')"}}
            else:
                props["cost_center_code"] = {"type": "string", "description": "Specific COD. C.CUSTO or name"}
            
            tools.append({
                "type": "function",
                "function": {
                    "name": name,
                    "description": desc,
                    "parameters": {
                        "type": "object",
                        "properties": props
                    }
                }
            })
        return tools

    def execute_tool(self, name: str, arguments: dict) -> str:
        func = getattr(self, name, None)
        if func and callable(func):
            try:
                result = func(**arguments)
                if result == "[]" or result == '[{"Budget_OR": null, "Actual_RE": null, "Extra_EX": null, "Commitment_EM": null}]':
                    return json.dumps({"status": "no_data_found", "message": "The query returned no results for the given filters. Check if the period or cost center code is correct."})
                return result
            except Exception as e:
                return json.dumps({"status": "error", "message": str(e)})
        return json.dumps({"status": "error", "message": f"Tool {name} not found."})
