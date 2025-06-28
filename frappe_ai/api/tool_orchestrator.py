import frappe
import requests
import json
import os
import openai
from frappe_ai.api.mcp_client import list_mcp_tools, call_mcp_tool

def get_openrouter_api_key():
    """Retrieves the provisioned OpenRouter API key from AI Settings."""
    settings = frappe.get_single("AI Setting")
    if not settings.key_provisioned:
        raise frappe.PermissionError("OpenRouter API key has not been provisioned for this site.")
    return settings.get_password("site_api_key")

def get_openai_api_key():
    """Retrieves the OpenAI API key from AI Settings."""
    settings = frappe.get_single("AI Setting")
    # This assumes a field 'openai_api_key' of type 'Password' exists in 'AI Setting' DocType.
    openai_key = settings.get_password("openai_api_key")
    if not openai_key:
        raise frappe.PermissionError("OpenAI API key is not set in AI Settings.")
    return openai_key

def openrouter_call(model_id: str, messages: list, tools: list = None, tool_choice: str = "auto", temperature: float = 0.2):
    """
    Makes a call to the OpenRouter LLM API, supporting tool use.
    Returns the entire assistant message object from the response.
    """
    api_key = get_openrouter_api_key()
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    body = {
        "model": model_id,
        "messages": messages,
        "temperature": temperature,
    }
    if tools:
        body["tools"] = tools
        body["tool_choice"] = tool_choice
    
    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json=body,
            timeout=180 # Increased timeout for potentially long tool-use chains
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]
    except requests.exceptions.RequestException as e:
        frappe.log_error(f"LLM call failed: {e.response.text if e.response else e}", "LLM Call Error")
        raise

def openai_responses_call(model_id: str, messages: list, log_container: list = None):
    """
    Makes a call to the OpenAI Responses API, supporting tool use and conversation state.
    Returns the entire response object.
    """
    client = openai.OpenAI(api_key=get_openai_api_key())
    
    tools_payload = [
            {
                "type": "mcp",
                "server_label": "sentrafrappe",
                "server_url": "https://5332-115-96-84-178.ngrok-free.app/mcp",
                "require_approval": "never",
            },
        ]
    # The 'input' parameter expects the full message structure, not just the content string.
    input_payload = messages 
    instructions_payload = """ 
**Key Instructions:**
- **Follow Tool Schemas**: When calling a tool, you **must** use the exact parameter names defined in its function signature. Refer to the tool's definition to understand the required arguments and their format. Do not guess parameter names.
- **CRITICAL - Parameter Names**: For `create_document` and `update_document`, the parameter for the document's data is called `values`. The parameter `fields` is used for reading tools like `get_document`. **DO NOT** use `fields` when you mean to use `values`.
- **Pay Attention to Nested Objects**: Carefully examine every tool's schema for parameters that are of type 'object'. You **must** construct a nested JSON object for these parameters as specified in their schema. Do not flatten the structure. For example: `create_document(doctype='Contact', values={'first_name': 'John'})`.
- **Never Ask for Information**: You have tools to find information. Use them. Do not ask the user for names, IDs, or other details you can discover yourself.
- **Self-Correct on Errors**: If a tool returns an error, do not give up. This often means your initial assumption was wrong. Look at the error and try again to solve it with the tools that are available to you.
- **Do not ask for permission**: Do not ask the user for permission to use a tool. Recursively use the tools to find the answer and complete the task.
You can call multiple tools in the same run. Do not stop until the task is done. Keep iterating on what to do next given the situation and recursively call tools to solve tasks.
        """

    if log_container is not None:
        log_container.append({
            "step": "LLM Request Payload",
            "status": "info",
            "data": {
                "model": model_id,
                "input": input_payload,
                "tools": tools_payload,
                "instructions": instructions_payload
            }
        })

    response = client.responses.create(
        model=model_id,
        tools=tools_payload,
        input=input_payload,
        instructions=instructions_payload
    )
    return response

def llm_call(provider: str, model_id: str, messages: list, tools: list = None, tool_choice: str = "auto", temperature: float = 0.2, previous_response_id: str = None):
    if provider == "openrouter":
        return openrouter_call(model_id, messages, tools, tool_choice, temperature)
    else: # Default to openai
        return openai_responses_call(model_id, messages)

def format_openai_output_to_log(response_obj):
    """Formats the OpenAI response object into a structured log for the frontend."""
    log = []
    final_response_text = ""
    
    if not hasattr(response_obj, 'output') or not response_obj.output:
        return log, final_response_text

    for item in response_obj.output:
        item_dict = item.model_dump(exclude_unset=True)
        step_name = item_dict.get('type', 'Unknown Step').replace('_', ' ').title()
        status = 'success'
        data = {}

        if item_dict.get('error'):
            status = 'error'
            data['error'] = item_dict['error']
        
        if item_dict.get('type') == 'mcp_list_tools':
            step_name = f"List Tools ({item_dict.get('server_label', '')})"
            tools_list = item_dict.get('tools', [])
            data['tools_found'] = len(tools_list)
            data['tools_schemas'] = tools_list # Log the full schemas

        elif item_dict.get('type') == 'mcp_call':
            tool_name = item_dict.get('name', 'unknown_tool')
            step_name = f"Execute Tool: {tool_name}"
            data['arguments'] = item_dict.get('arguments')
            # Only show output if it exists
            if item_dict.get('output'):
                data['output'] = item_dict.get('output')

        elif item_dict.get('type') == 'message':
            step_name = "Assistant Message"
            if item_dict.get('role') == 'assistant' and item_dict.get('content'):
                text_content = ""
                for content_part in item_dict['content']:
                    if content_part.get('type') == 'output_text':
                        text_content += content_part.get('text', '')
                # Don't add empty messages to the final response
                if text_content.strip():
                    final_response_text += text_content + "\\n\\n"
                # Skip adding empty assistant messages to the log
                if not text_content.strip():
                    continue
                data['message'] = text_content
            else:
                # Don't log non-assistant messages
                continue
        
        log.append({"step": step_name, "status": status, "data": data})

    return log, final_response_text.strip()

@frappe.whitelist()
def run_tool_orchestration(user_query: str):
    """
    Runs a multi-step tool-use loop, allowing the LLM to recursively use tools
    from the MCP server to answer a user's query.
    """
    try:
        messages = [{"role": "user", "content": user_query}]
        initial_log = []
        response_obj = openai_responses_call("gpt-4.1", messages, log_container=initial_log)
        
        parsed_log, final_response = format_openai_output_to_log(response_obj)

        log = initial_log + parsed_log
        
        has_error = any(step['status'] == 'error' for step in log)

        # If the final response is empty but there's no error, use a default message
        if not final_response and not has_error:
            final_response = "The process completed, but no final answer was generated."

        return {"log": log, "final_response": final_response, "error": has_error}
    except Exception as e:
        frappe.log_error(f"Tool Orchestration Failed: {str(e)}", "Tool Orchestration")
        return {
            "log": [{
                "step": "Orchestration Failed",
                "status": "error",
                "data": {"error": str(e)}
            }],
            "final_response": f"**Orchestration Failed**\n\nAn unhandled error occurred: {str(e)}",
            "error": True
        }