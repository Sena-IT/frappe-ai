import frappe
import requests
import json
from frappe_ai.api.mcp_client import list_mcp_tools, call_mcp_tool

def get_openrouter_api_key():
    settings = frappe.get_single("AI Setting")
    if not settings.key_provisioned:
        raise frappe.PermissionError("OpenRouter API key has not been provisioned for this site.")
    return settings.get_password("site_api_key")

def llm_call(model_id: str, messages: list, temperature: float = 0.7):
    api_key = get_openrouter_api_key()
    headers = {"Authorization": f"Bearer {api_key}"}
    body = {
        "model": model_id,
        "messages": messages,
        "temperature": temperature,
    }
    
    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json=body
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
    except requests.exceptions.RequestException as e:
        frappe.log_error(f"LLM call failed: {e.response.text if e.response else e}")
        raise

def build_tool_decision_prompt(user_query, tools):
    return f"""
You are an expert AI assistant that can use tools.
Your task is to determine the most appropriate tool to use to answer the user's query.

Here is the user's query:
<user_query>
{user_query}
</user_query>

Here is the list of available tools:
<tools>
{json.dumps(tools, indent=2)}
</tools>

You must respond in the following JSON format, and nothing else:
{{
  "tool_name": "<the name of the tool you have chosen>",
  "tool_params": {{
    "param1": "value1",
    "param2": "value2"
  }}
}}

If no tool is appropriate, respond with:
{{
  "tool_name": "no_tool_needed",
  "tool_params": {{}}
}}
"""

def build_final_response_prompt(user_query, tool_name, tool_result):
    return f"""
You are a helpful AI assistant.
A user asked the following question:
<user_query>
{user_query}
</user_query>

To answer this question, the system executed the tool `{tool_name}` and got the following result:
<tool_result>
{json.dumps(tool_result, indent=2)}
</tool_result>

Based on this information, please provide a clear and helpful response to the user.
"""

def decide_tool(user_query, tools):
    prompt = build_tool_decision_prompt(user_query, tools)
    messages = [{"role": "user", "content": prompt}]
    # Using Gemini 1.5 Flash as requested
    response_text = llm_call("google/gemini-2.5-flash", messages)
    
    try:
        return json.loads(response_text)
    except json.JSONDecodeError:
        frappe.log_error(f"Failed to decode tool decision from LLM response: {response_text}")
        # Fallback or error handling
        return {"tool_name": "error_parsing_json", "tool_params": {}}

def generate_final_response(user_query, tool_name, tool_result):
    prompt = build_final_response_prompt(user_query, tool_name, tool_result)
    messages = [{"role": "user", "content": prompt}]
    # Using a more capable model for final response generation
    return llm_call("google/gemini-2.5-flash", messages)

@frappe.whitelist()
def run_tool_orchestration(user_query: str):
    log = []

    def add_log_step(step_name, status, data):
        log.append({"step": step_name, "status": status, "data": data})

    try:
        # Step 1: List available tools
        add_log_step("List Available Tools", "running", {})
        mcp_tools_response = list_mcp_tools()
        available_tools = mcp_tools_response.get("result", {}).get("tools", [])
        if not available_tools or mcp_tools_response.get("error"):
            raise Exception(f"Failed to list MCP tools: {mcp_tools_response.get('error', 'No tools found')}")
        add_log_step("List Available Tools", "success", {"request": "tools/list", "response": available_tools})

        # Step 2: Decide which tool to use
        add_log_step("Decide Tool", "running", {})
        tool_decision_prompt = build_tool_decision_prompt(user_query, available_tools)
        decision_llm_response = llm_call("google/gemini-2.5-flash", [{"role": "user", "content": tool_decision_prompt}])
        
        try:
            # The LLM often wraps the JSON in ```json ... ```. We need to strip that.
            if "```json" in decision_llm_response:
                cleaned_response = decision_llm_response.split("```json")[1].split("```")[0].strip()
            else:
                # Find the first '{' and the last '}' to extract the JSON object
                start = decision_llm_response.find('{')
                end = decision_llm_response.rfind('}')
                if start != -1 and end != -1:
                    cleaned_response = decision_llm_response[start:end+1]
                else:
                    cleaned_response = decision_llm_response # fallback to original if no JSON object is found

            tool_decision = json.loads(cleaned_response)
        except (json.JSONDecodeError, IndexError):
            add_log_step("Decide Tool", "error", {"prompt": tool_decision_prompt, "llm_response": decision_llm_response, "error": "LLM returned invalid JSON"})
            raise Exception("The tool decision model returned an invalid response.")
        
        add_log_step("Decide Tool", "success", {"prompt": tool_decision_prompt, "llm_response": decision_llm_response, "parsed": tool_decision})

        tool_name = tool_decision.get("tool_name")
        tool_params = tool_decision.get("tool_params", {})

        # 3. Call the chosen tool (or handle no tool)
        if not tool_name or tool_name == "no_tool_needed":
             final_response = "I determined that no specific tool was needed to answer your query. How can I assist you further?"
             add_log_step("Generate Final Response", "success", {"reason": "No tool needed", "response": final_response})
             return {"log": log, "final_response": final_response}

        add_log_step("Execute Tool", "running", {})
        tool_result_response = call_mcp_tool(tool_name, tool_params)
        tool_result = tool_result_response.get("result")
        
        if not tool_result:
            add_log_step("Execute Tool", "error", {"tool": tool_name, "params": tool_params, "response": tool_result_response})
            raise Exception(f"Error executing tool '{tool_name}': {tool_result_response.get('error', {}).get('message', 'Unknown error')}")
        
        add_log_step("Execute Tool", "success", {"tool": tool_name, "params": tool_params, "result": tool_result})

        # 4. Generate final response
        add_log_step("Generate Final Response", "running", {})
        final_response = generate_final_response(user_query, tool_name, tool_result)
        add_log_step("Generate Final Response", "success", {"response": final_response})
        
        return {"log": log, "final_response": final_response}

    except Exception as e:
        error_message = str(e)
        frappe.log_error(f"Tool Orchestration Failed: {error_message}", "Tool Orchestration")
        
        # Mark the last running step as failed
        if log and log[-1]["status"] == "running":
            log[-1]["status"] = "error"
            log[-1]["data"]["error"] = error_message
        
        final_response = f"**Orchestration Failed**\n\nAn error occurred: {error_message}"
        
        return {"log": log, "final_response": final_response, "error": True} 