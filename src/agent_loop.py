import os
import json
from openai import OpenAI
from .tools import AgentTools
from .skill_loader import SkillLoader
from .memory import MemoryManager

class AgentLoop:
    """Manages the reasoning cycle between user messages, the LLM, and the tools.
    Spec-compliant FP&A reasoning engine.
    """
    
    def __init__(self, tools: AgentTools, memory: MemoryManager, skill_loader: SkillLoader):
        self.tools = tools
        self.memory = memory
        self.skill_loader = skill_loader
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        self.system_prompt = self.skill_loader.get_system_prompt()
        # Inject current date context (Spec-FR-01/06)
        self.system_prompt = f"Today is 2026-03-20. Current financial period is 2026-03.\n\n{self.system_prompt}"

    def process_message(self, user_id: str, user_message: str) -> str:
        # 1. Load context window (spec FR-03, FR-06)
        history = self.memory.get_history(user_id, limit=30)
        
        # 2. Build message payload
        messages = [{"role": "system", "content": self.system_prompt}]
        for msg in history:
            # Flatten history into OpenAI format
            m = {"role": msg["role"], "content": msg["content"]}
            if "tool_calls" in msg: m["tool_calls"] = msg["tool_calls"]
            messages.append(m)
            
        messages.append({"role": "user", "content": user_message})
        
        # Persist user message
        self.memory.add_message(user_id, "user", user_message)

        tools_def = self.tools.get_openai_tools_definition()
        max_iterations = 10 # Spec §15: increased for complex FP&A drill-downs
        
        for i in range(max_iterations):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=tools_def,
                    tool_choice="auto"
                )
            except Exception as e:
                error_msg = f"Erro na API da OpenAI: {str(e)}"
                return "Desculpe, ocorreu um erro técnico ao processar sua análise financeira."

            response_message = response.choices[0].message
            
            # Step-by-step reasoning storage
            msg_to_append = {"role": "assistant", "content": response_message.content}
            if response_message.tool_calls:
                msg_to_append["tool_calls"] = [
                    {
                        "id": t.id,
                        "type": "function",
                        "function": {
                            "name": t.function.name,
                            "arguments": t.function.arguments
                        }
                    } for t in response_message.tool_calls
                ]
            
            messages.append(msg_to_append)
            
            # 3. Handle Tool Execution
            if response_message.tool_calls:
                for tool_call in response_message.tool_calls:
                    function_name = tool_call.function.name
                    try:
                        arguments = json.loads(tool_call.function.arguments)
                        # Execute against SQL
                        tool_result = self.tools.execute_tool(function_name, arguments)
                    except Exception as e:
                        tool_result = json.dumps({"error": f"Invalid arguments: {str(e)}"})
                    
                    # Feed result back to LLM
                    messages.append({
                        "tool_call_id": tool_call.id,
                        "role": "tool",
                        "name": function_name,
                        "content": tool_result
                    })
            else:
                # 4. Final Answer Conclusion
                final_answer = response_message.content
                
                # Metadata Extraction (Spec Memory §6) — Heuristic to persist focus
                metadata = self._extract_metadata_from_context(messages)
                
                self.memory.add_message(user_id, "assistant", final_answer, metadata=metadata)
                return final_answer

        # Fail gracefully if max iterations reached (Spec §15)
        fallback_msg = "Cheguei ao limite de análise para esta pergunta. Por favor, tente ser mais específico ou use o comando /reset para limpar o contexto."
        self.memory.add_message(user_id, "assistant", fallback_msg)
        return fallback_msg

    def _extract_metadata_from_context(self, messages: list) -> dict:
        """Heuristic to track analytical focus (period, cost center) from tool calls."""
        meta = {}
        for msg in reversed(messages):
            if "tool_calls" in msg:
                for tc in msg["tool_calls"]:
                    args = json.loads(tc["function"]["arguments"])
                    if "cost_center_code" in args: meta["focus_entity_value"] = args["cost_center_code"]
                    if "period_yyyy_mm" in args: meta["time_scope"] = args["period_yyyy_mm"]
                if meta: break
        return meta
