"""Legacy OpenAI wrapper kept only for older demos and migration fallback."""

import os
import json
import inspect
from typing import Dict, Any, List, Optional, Callable, Union, get_origin, get_args
from openai import AsyncOpenAI
from datetime import datetime


class OpenAIAgent:
    """
    OpenAI-compatible agent wrapper that mimics Strands SDK interface.

    This class provides a similar interface to the Strands Agent class
    but uses OpenAI's API instead.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gpt-5.4",
        system_prompt: str = "",
        tools: Optional[List[Callable]] = None,
        temperature: float = 0.7,
    ):
        """
        Initialize OpenAI Agent.

        Args:
            api_key: OpenAI API key (or uses env var OPENAI_API_KEY)
            model: Model to use (for example gpt-5.4)
            system_prompt: System prompt for the agent
            tools: List of tool functions (for function calling)
            temperature: Temperature for generation
        """
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OpenAI API key not provided or found in environment")

        self.client = AsyncOpenAI(api_key=self.api_key)
        self.model = model
        self.system_prompt = system_prompt
        self.tools = tools or []
        self.temperature = temperature

        # Convert tools to OpenAI function schema
        self.functions = self._convert_tools_to_functions()

    def _convert_tools_to_functions(self) -> List[Dict[str, Any]]:
        """
        Convert tool functions to OpenAI function calling schema.

        Returns:
            List of function schemas
        """
        functions = []
        for tool in self.tools:
            # Extract function metadata from docstring and annotations
            func_name = tool.__name__
            func_doc = tool.__doc__ or "No description"
            
            # Extract description from first line of docstring
            description_lines = func_doc.split("\n")
            description = description_lines[0].strip() if description_lines else "No description"
            
            # Parse Args section from docstring
            param_descriptions = {}
            in_args_section = False
            for line in description_lines:
                if line.strip().startswith("Args:"):
                    in_args_section = True
                    continue
                if in_args_section:
                    if line.strip() and not line.strip().startswith((":", " ", "\t")) and ":" not in line and not line.strip().startswith(("Args", "Returns", "Example")):
                        in_args_section = False
                    elif ":" in line:
                        parts = line.split(":", 1)
                        if len(parts) == 2:
                            param_name = parts[0].strip().rstrip(":")
                            param_desc = parts[1].strip()
                            param_descriptions[param_name] = param_desc

            # Basic function schema
            function_schema = {
                "name": func_name,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }

            # Get function signature
            try:
                sig = inspect.signature(tool)
                for param_name, param in sig.parameters.items():
                    if param_name == "self":
                        continue
                    
                    param_type = param.annotation if param.annotation != inspect.Parameter.empty else str
                    param_default = param.default if param.default != inspect.Parameter.empty else None
                    
                    # Determine type
                    param_type_str = "string"
                    param_schema = {}

                    if param_type == int:
                        param_type_str = "integer"
                    elif param_type == float:
                        param_type_str = "number"
                    elif param_type == bool:
                        param_type_str = "boolean"
                    elif param_type in [list, List] or (hasattr(param_type, "__origin__") and get_origin(param_type) is list):
                        param_type_str = "array"
                        # Get the inner type for List[X]
                        args = get_args(param_type) if hasattr(param_type, "__origin__") else []
                        if args:
                            inner_type = args[0]
                            # Check if it's List[Dict[...]]
                            if inner_type in [dict, Dict] or (hasattr(inner_type, "__origin__") and get_origin(inner_type) is dict):
                                param_schema["items"] = {"type": "object"}
                            elif inner_type == int:
                                param_schema["items"] = {"type": "integer"}
                            elif inner_type == float:
                                param_schema["items"] = {"type": "number"}
                            elif inner_type == bool:
                                param_schema["items"] = {"type": "boolean"}
                            elif inner_type == str:
                                param_schema["items"] = {"type": "string"}
                            else:
                                param_schema["items"] = {"type": "object"}
                        else:
                            # Default to string array if no inner type specified
                            param_schema["items"] = {"type": "string"}
                    elif param_type in [dict, Dict] or (hasattr(param_type, "__origin__") and get_origin(param_type) is dict):
                        param_type_str = "object"

                    # Handle Optional types
                    if hasattr(param_type, "__origin__"):
                        origin = get_origin(param_type)
                        if origin and hasattr(origin, "__name__") and "Optional" in str(origin):
                            args = get_args(param_type)
                            if args:
                                inner_type = args[0]
                                if inner_type == int:
                                    param_type_str = "integer"
                                elif inner_type == float:
                                    param_type_str = "number"
                                elif inner_type == bool:
                                    param_type_str = "boolean"

                    # Get description from docstring or use default
                    param_desc = param_descriptions.get(param_name, f"Parameter {param_name}")

                    param_schema["type"] = param_type_str
                    param_schema["description"] = param_desc

                    function_schema["parameters"]["properties"][param_name] = param_schema
                    
                    # Add to required if no default
                    if param_default is inspect.Parameter.empty:
                        function_schema["parameters"]["required"].append(param_name)
            except Exception as e:
                # Fallback: use annotations if signature parsing fails
                if hasattr(tool, "__annotations__"):
                    for param_name, param_type in tool.__annotations__.items():
                        if param_name != "return" and param_name != "self":
                            param_type_str = "string"
                            if param_type == int:
                                param_type_str = "integer"
                            elif param_type == float:
                                param_type_str = "number"
                            elif param_type == bool:
                                param_type_str = "boolean"
                            
                            function_schema["parameters"]["properties"][param_name] = {
                                "type": param_type_str,
                                "description": param_descriptions.get(param_name, f"Parameter {param_name}")
                            }
                            function_schema["parameters"]["required"].append(param_name)

            functions.append(function_schema)

        return functions

    async def run(self, user_input: str, **kwargs) -> str:
        """
        Run the agent with user input.

        Args:
            user_input: User's input/request
            **kwargs: Additional parameters

        Returns:
            Agent's response as string
        """
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_input}
        ]

        try:
            # Use function calling if tools are available
            if self.functions:
                max_iterations = kwargs.get("max_iterations", 10)
                iteration = 0
                
                while iteration < max_iterations:
                    response = await self.client.chat.completions.create(
                        model=self.model,
                        messages=messages,
                        temperature=self.temperature,
                        max_tokens=kwargs.get("max_tokens", 4096),
                        tools=[{"type": "function", "function": func} for func in self.functions] if self.functions else None,
                        tool_choice="auto"
                    )
                    
                    message = response.choices[0].message
                    
                    # Add assistant message to conversation
                    messages.append({
                        "role": "assistant",
                        "content": message.content,
                        "tool_calls": message.tool_calls
                    } if message.tool_calls else {
                        "role": "assistant",
                        "content": message.content
                    })
                    
                    # If no tool calls, we're done
                    if not message.tool_calls:
                        return message.content or ""
                    
                    # Execute tool calls
                    for tool_call in message.tool_calls:
                        tool_name = tool_call.function.name
                        tool_args = json.loads(tool_call.function.arguments)
                        
                        # Find the tool function
                        tool_func = None
                        for tool in self.tools:
                            if tool.__name__ == tool_name:
                                tool_func = tool
                                break
                        
                        if not tool_func:
                            tool_result = f"Error: Tool {tool_name} not found"
                        else:
                            try:
                                # Call the tool (handle both sync and async)
                                import inspect
                                
                                # Check if it's a coroutine function first
                                if inspect.iscoroutinefunction(tool_func):
                                    tool_result = await tool_func(**tool_args)
                                else:
                                    # Call sync function
                                    tool_result = tool_func(**tool_args)
                                    # Check if result is a coroutine (handles decorators that return coroutines)
                                    if inspect.iscoroutine(tool_result):
                                        tool_result = await tool_result
                                
                                # Convert result to string if needed
                                if isinstance(tool_result, (dict, list)):
                                    tool_result = json.dumps(tool_result, indent=2)
                                elif tool_result is None:
                                    tool_result = "No result returned"
                                else:
                                    tool_result = str(tool_result)
                            except Exception as e:
                                import traceback
                                error_trace = traceback.format_exc()
                                tool_result = f"Error executing {tool_name}: {str(e)}\n{traceback.format_exc()}"
                        
                        # Add tool result to messages
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": tool_name,
                            "content": tool_result
                        })
                    
                    iteration += 1
                
                # Return last assistant message if we hit max iterations
                return messages[-1].get("content", "Max iterations reached") if messages else "No response"
            else:
                # No tools, just regular chat
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=self.temperature,
                    max_tokens=kwargs.get("max_tokens", 4096),
                    response_format={"type": "json_object"} if kwargs.get("json_mode", False) else None
                )

                # Extract response
                message = response.choices[0].message

                # Return regular message
                return message.content or ""

        except Exception as e:
            return f"Error: {str(e)}"

    async def run_with_messages(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """
        Run the agent with a list of messages (for continuing conversations).

        Args:
            messages: List of message dictionaries with 'role' and 'content'
            **kwargs: Additional parameters

        Returns:
            Agent's response as string
        """
        # Ensure system prompt is included
        if not any(msg["role"] == "system" for msg in messages):
            messages.insert(0, {"role": "system", "content": self.system_prompt})

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=self.temperature,
                max_tokens=kwargs.get("max_tokens", 4096)
            )

            return response.choices[0].message.content

        except Exception as e:
            return f"Error: {str(e)}"


class Agent:
    """
    Compatibility wrapper to match Strands SDK Agent interface exactly.

    This allows existing code to work without modification.
    """

    def __init__(
        self,
        client: Any = None,  # Ignored, we create our own
        api_key: Optional[str] = None,
        model: str = "gpt-5.4",
        system_prompt: str = "",
        tools: Optional[List] = None
    ):
        """Initialize agent with Strands-like interface."""
        # Create OpenAI agent internally
        self._agent = OpenAIAgent(
            api_key=api_key,
            model=model,
            system_prompt=system_prompt,
            tools=tools
        )

    async def run(self, request: str) -> str:
        """Run agent with request."""
        return await self._agent.run(request)


# Helper function to create agent
def create_openai_agent(
    system_prompt: str,
    api_key: Optional[str] = None,
    tools: Optional[List] = None,
    model: Optional[str] = None
) -> Agent:
    """
    Create an OpenAI agent with the specified configuration.

    Args:
        system_prompt: System prompt for the agent
        tools: Optional list of tool functions
        model: Optional model override

    Returns:
        Configured Agent instance
    """
    model = model or os.getenv("ORCHESTRATOR_MODEL", "gpt-5.4")
    return Agent(
        api_key=api_key,
        model=model,
        system_prompt=system_prompt,
        tools=tools
    )
