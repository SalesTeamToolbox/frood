"""Tests for ExtensionLoader — agent execution lifecycle hooks."""



from agents.extension_loader import ExtensionLoader


class TestExtensionLoader:
    def test_no_extensions_dir_has_no_extensions(self):
        loader = ExtensionLoader(extensions_dir=None)
        assert not loader.has_extensions
        assert loader.list_extensions() == []

    def test_nonexistent_dir_has_no_extensions(self, tmp_path):
        loader = ExtensionLoader(extensions_dir=tmp_path / "nonexistent")
        assert not loader.has_extensions

    def test_empty_dir_has_no_extensions(self, tmp_path):
        loader = ExtensionLoader(extensions_dir=tmp_path)
        assert not loader.has_extensions

    def test_loads_extension_with_hooks(self, tmp_path):
        ext_file = tmp_path / "test_ext.py"
        ext_file.write_text(
            "def before_system_prompt(prompt, task_type):\n    return prompt + ' [modified]'\n"
        )
        loader = ExtensionLoader(extensions_dir=tmp_path)
        assert loader.has_extensions
        exts = loader.list_extensions()
        assert len(exts) == 1
        assert "before_system_prompt" in exts[0]["hooks"]

    def test_before_system_prompt_hook_called(self, tmp_path):
        ext_file = tmp_path / "before_prompt.py"
        ext_file.write_text(
            "def before_system_prompt(prompt, task_type):\n    return prompt + ' [before_hook]'\n"
        )
        loader = ExtensionLoader(extensions_dir=tmp_path)
        result = loader.call_before_system_prompt("Original prompt", "coding")
        assert result == "Original prompt [before_hook]"

    def test_after_system_prompt_hook_called(self, tmp_path):
        ext_file = tmp_path / "after_prompt.py"
        ext_file.write_text("def after_system_prompt(prompt):\n    return '[FINAL] ' + prompt\n")
        loader = ExtensionLoader(extensions_dir=tmp_path)
        result = loader.call_after_system_prompt("My prompt")
        assert result == "[FINAL] My prompt"

    def test_before_iteration_hook_called(self, tmp_path):
        ext_file = tmp_path / "iter_hook.py"
        ext_file.write_text(
            "def before_iteration(messages, iteration_num):\n"
            "    return messages + [{'role': 'system', 'content': f'Iteration {iteration_num}'}]\n"
        )
        loader = ExtensionLoader(extensions_dir=tmp_path)
        messages = [{"role": "user", "content": "test"}]
        result = loader.call_before_iteration(messages, 1)
        assert len(result) == 2
        assert result[-1]["content"] == "Iteration 1"

    def test_after_iteration_hook_called(self, tmp_path):
        ext_file = tmp_path / "after_iter.py"
        ext_file.write_text(
            "def after_iteration(output, iteration_num):\n"
            "    return output + f' [iter {iteration_num}]'\n"
        )
        loader = ExtensionLoader(extensions_dir=tmp_path)
        result = loader.call_after_iteration("Output text", 3)
        assert result == "Output text [iter 3]"

    def test_before_tool_call_hook_called(self, tmp_path):
        ext_file = tmp_path / "tool_hook.py"
        ext_file.write_text(
            "def before_tool_call(tool_name, kwargs):\n"
            "    kwargs['_audited'] = True\n"
            "    return kwargs\n"
        )
        loader = ExtensionLoader(extensions_dir=tmp_path)
        result = loader.call_before_tool_call("shell", {"command": "ls"})
        assert result.get("_audited") is True

    def test_after_tool_call_hook_called(self, tmp_path):
        ext_file = tmp_path / "after_tool.py"
        ext_file.write_text("def after_tool_call(tool_name, result):\n    return result\n")
        loader = ExtensionLoader(extensions_dir=tmp_path)
        mock_result = object()
        result = loader.call_after_tool_call("shell", mock_result)
        assert result is mock_result

    def test_alphabetical_ordering(self, tmp_path):
        """Extensions should be loaded and called in alphabetical filename order."""
        calls = []

        (tmp_path / "01_first.py").write_text(
            "def before_system_prompt(prompt, task_type):\n    return prompt + ' [FIRST]'\n"
        )
        (tmp_path / "02_second.py").write_text(
            "def before_system_prompt(prompt, task_type):\n    return prompt + ' [SECOND]'\n"
        )
        loader = ExtensionLoader(extensions_dir=tmp_path)
        result = loader.call_before_system_prompt("Base", "coding")
        assert result == "Base [FIRST] [SECOND]"

    def test_missing_hook_is_skipped(self, tmp_path):
        """Extension that doesn't define a hook should be skipped for that hook."""
        ext_file = tmp_path / "partial.py"
        ext_file.write_text("def after_iteration(output, iteration_num):\n    return output\n")
        loader = ExtensionLoader(extensions_dir=tmp_path)
        # before_system_prompt not defined — should return prompt unchanged
        result = loader.call_before_system_prompt("Original", "coding")
        assert result == "Original"

    def test_extension_error_does_not_crash(self, tmp_path):
        """An extension that raises should log a warning but not crash."""
        ext_file = tmp_path / "buggy.py"
        ext_file.write_text(
            "def before_system_prompt(prompt, task_type):\n    raise ValueError('Extension bug!')\n"
        )
        loader = ExtensionLoader(extensions_dir=tmp_path)
        # Should not raise, returns prompt unchanged
        result = loader.call_before_system_prompt("Safe prompt", "coding")
        assert result == "Safe prompt"

    def test_bad_return_type_ignored(self, tmp_path):
        """Extension returning wrong type should be ignored."""
        ext_file = tmp_path / "bad_return.py"
        ext_file.write_text(
            "def before_system_prompt(prompt, task_type):\n    return 42  # Not a string\n"
        )
        loader = ExtensionLoader(extensions_dir=tmp_path)
        result = loader.call_before_system_prompt("Original", "coding")
        # Should keep original since 42 is not a str
        assert result == "Original"

    def test_list_extensions_shows_hooks(self, tmp_path):
        ext_file = tmp_path / "multi_hook.py"
        ext_file.write_text(
            "def before_system_prompt(p, t): return p\ndef after_iteration(o, n): return o\n"
        )
        loader = ExtensionLoader(extensions_dir=tmp_path)
        exts = loader.list_extensions()
        assert len(exts) == 1
        hooks = exts[0]["hooks"]
        assert "before_system_prompt" in hooks
        assert "after_iteration" in hooks
