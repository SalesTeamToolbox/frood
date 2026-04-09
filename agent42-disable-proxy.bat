@echo off
echo Disabling Agent42 LLM Proxy...
setx ANTHROPIC_BASE_URL ""
setx ANTHROPIC_API_KEY ""
setx ANTHROPIC_MODEL ""
echo.
echo Done! Claude Code will use default settings.
echo Restart your terminal or VS Code for changes to take effect.