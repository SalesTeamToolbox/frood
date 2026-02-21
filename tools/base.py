"""
Abstract base for all agent tools.

Tools follow a schema-based pattern: each tool declares its name, description,
and parameters (JSON Schema) so the LLM can call them via function calling.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ToolResult:
    """Result of a tool execution."""
    output: str = ""
    error: str = ""
    success: bool = True

    @property
    def content(self) -> str:
        return self.output if self.success else f"Error: {self.error}"


class Tool(ABC):
    """Abstract base class for all agent tools."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique tool identifier."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description for the LLM."""
        ...

    @property
    @abstractmethod
    def parameters(self) -> dict:
        """JSON Schema for tool parameters."""
        ...

    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        """Execute the tool with the given parameters."""
        ...

    def to_schema(self) -> dict:
        """Serialize to OpenAI function-calling format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }
