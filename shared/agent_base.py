"""
Legacy Anthropic-compatible base agent kept for older demos.
"""

import os
import asyncio
from typing import Any, Dict, List, Optional, Callable
from anthropic import Anthropic
import json


class Tool:
    """Tool wrapper for agent functions"""

    def __init__(self, func: Callable, name: str = None, description: str = None):
        self.func = func
        self.name = name or func.__name__
        self.description = description or func.__doc__ or "No description"

    async def run(self, *args, **kwargs):
        """Execute the tool"""
        if asyncio.iscoroutinefunction(self.func):
            return await self.func(*args, **kwargs)
        else:
            return self.func(*args, **kwargs)


class Agent:
    """Base Agent class compatible with Anthropic Claude"""

    def __init__(
        self,
        client: Anthropic,
        model: str = "claude-3-sonnet-20241022",
        system_prompt: str = "",
        tools: List[Tool] = None,
        max_tokens: int = 4096
    ):
        self.client = client
        self.model = model
        self.system_prompt = system_prompt
        self.tools = tools or []
        self.max_tokens = max_tokens
        self.conversation_history = []

    def _format_tools_for_prompt(self) -> str:
        """Format available tools for inclusion in prompt"""
        if not self.tools:
            return ""

        tools_desc = "\n\nAvailable tools:\n"
        for tool in self.tools:
            tools_desc += f"- {tool.name}: {tool.description}\n"

        tools_desc += "\nTo use a tool, respond with: TOOL:{tool_name} ARGS:{json_args}"
        return tools_desc

    async def run(self, query: str) -> str:
        """Run the agent with a query"""
        # Add tools description to system prompt if tools are available
        full_system_prompt = self.system_prompt
        if self.tools:
            full_system_prompt += self._format_tools_for_prompt()

        # Create message
        messages = [
            {"role": "user", "content": query}
        ]

        # Add conversation history
        messages = self.conversation_history + messages

        try:
            # Call Anthropic API
            response = self.client.messages.create(
                model=self.model,
                system=full_system_prompt,
                messages=messages,
                max_tokens=self.max_tokens
            )

            # Extract response
            assistant_message = response.content[0].text

            # Check if tool use is requested
            if self.tools and "TOOL:" in assistant_message:
                tool_response = await self._handle_tool_use(assistant_message)
                if tool_response:
                    # Add tool response to conversation
                    self.conversation_history.append({"role": "user", "content": query})
                    self.conversation_history.append({"role": "assistant", "content": assistant_message})

                    # Get final response after tool use
                    tool_result_message = f"Tool result: {tool_response}"
                    messages.append({"role": "assistant", "content": assistant_message})
                    messages.append({"role": "user", "content": tool_result_message})

                    final_response = self.client.messages.create(
                        model=self.model,
                        system=full_system_prompt,
                        messages=messages,
                        max_tokens=self.max_tokens
                    )

                    return final_response.content[0].text

            # Update conversation history
            self.conversation_history.append({"role": "user", "content": query})
            self.conversation_history.append({"role": "assistant", "content": assistant_message})

            return assistant_message

        except Exception as e:
            return f"Error running agent: {str(e)}"

    async def _handle_tool_use(self, response: str) -> Optional[str]:
        """Parse and execute tool use from response"""
        try:
            # Parse tool use
            if "TOOL:" in response and "ARGS:" in response:
                tool_part = response.split("TOOL:")[1].split("ARGS:")[0].strip()
                args_part = response.split("ARGS:")[1].strip()

                # Find the tool
                tool = None
                for t in self.tools:
                    if t.name == tool_part:
                        tool = t
                        break

                if not tool:
                    return f"Tool '{tool_part}' not found"

                # Parse arguments
                try:
                    args = json.loads(args_part) if args_part else {}
                except:
                    args = {"input": args_part}  # Fallback to simple string input

                # Execute tool
                result = await tool.run(**args)
                return str(result)

        except Exception as e:
            return f"Error executing tool: {str(e)}"

        return None

    def reset(self):
        """Reset conversation history"""
        self.conversation_history = []


def create_agent(
    model: str = None,
    system_prompt: str = "",
    tools: List[Callable] = None
) -> Agent:
    """Factory function to create an agent"""
    # Get API key from environment
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY environment variable not set")

    # Create Anthropic client
    client = Anthropic(api_key=api_key)

    # Default model
    if not model:
        model = os.getenv("CLAUDE_MODEL", "claude-3-sonnet-20241022")

    # Convert functions to tools
    tool_objects = []
    if tools:
        for func in tools:
            tool_objects.append(Tool(func))

    return Agent(
        client=client,
        model=model,
        system_prompt=system_prompt,
        tools=tool_objects
    )
