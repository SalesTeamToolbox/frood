"""
Command filter — blocks dangerous shell patterns before execution.

Deny-list approach with optional allowlist for strict environments.
Patterns derived from common destructive commands that agents should never run.

Security layers:
0. Structural pre-checks (null bytes, newlines, hex escapes, ANSI-C quoting)
1. Deny-list of known-dangerous command patterns
2. Interpreter execution blocking (python -c, perl -e, etc.)
3. Shell metacharacter abuse detection (eval, backticks, $() in dangerous contexts)
4. Indirect execution blocking (sh -c, bash -c, here-documents)
5. Optional allowlist for strict lockdown

Note: This is one layer of defense. The shell tool also enforces workspace path
restrictions (blocking absolute paths outside the sandbox). Both layers must
pass for a command to execute.
"""

import logging
import re

logger = logging.getLogger("agent42.command_filter")

# Patterns that are always blocked
DENY_PATTERNS: list[re.Pattern] = [
    re.compile(p, re.IGNORECASE)
    for p in [
        # -- Destructive filesystem operations --
        r"\brm\s+(-[a-z]*f[a-z]*\s+)?/",  # rm -rf / (root deletion)
        r"\brm\s+-[a-z]*r[a-z]*\s+-[a-z]*f",  # rm -rf variants
        r"\bdd\s+.*of\s*=\s*/dev/",  # dd to device
        r"\bmkfs\b",  # format filesystem
        r"\bformat\b.*[A-Z]:",  # Windows format
        r":\(\)\s*\{\s*:\|:\s*&\s*\};:",  # fork bomb
        r">\s*/dev/sda",  # write to disk device
        r"\bchmod\s+-R\s+777\s+/\s*$",  # chmod -R 777 /
        r"\bchown\s+-R\s+.*\s+/\s*$",  # chown -R ... /
        # -- System control --
        r"\bshutdown\b",  # shutdown
        r"\breboot\b",  # reboot
        r"\bpoweroff\b",  # poweroff
        r"\bhalt\b",  # halt
        r"\binit\s+0\b",  # init 0
        r"\bsystemctl\s+(stop|disable|mask|restart)\b",  # service manipulation
        r"\bservice\s+\w+\s+(stop|restart)\b",  # sysvinit service control
        # -- Remote code execution / exfiltration --
        r"\bwget\b.*\|\s*\b(ba)?sh\b",  # wget pipe to shell
        r"\bcurl\b.*\|\s*\b(ba)?sh\b",  # curl pipe to shell
        r"\bcurl\b.*--upload-file\b",  # curl file upload
        r"\bcurl\b.*-T\s",  # curl file upload shorthand
        r"\bscp\b",  # scp file transfer
        r"\brsync\b.*[^/]:",  # rsync to remote host
        r"\bsftp\b",  # sftp transfer
        r"\bftp\b",  # ftp transfer
        # -- Network listeners / tunnels --
        r"\bnc\s+-[a-z]*l",  # netcat listener
        r"\bsocat\b.*LISTEN",  # socat listener
        r"\bssh\s+-[a-z]*R\b",  # ssh reverse tunnel
        r"\bssh\s+-[a-z]*D\b",  # ssh SOCKS proxy
        # -- Firewall / network --
        r"\biptables\s+-F",  # flush iptables
        r"\bufw\s+(disable|reset)\b",  # disable firewall
        # -- User / permission escalation --
        r"\buseradd\b",  # add user
        r"\buserdel\b",  # delete user
        r"\bpasswd\b",  # change password
        r"\bvisudo\b",  # edit sudoers
        r"\bchattr\b",  # change file attributes
        r"\bsudo\b",  # sudo privilege escalation
        r"\bsu\s+-?\s",  # su user switching
        r"\bpkexec\b",  # polkit escalation
        # -- Package management (prevent installing arbitrary software) --
        r"\bapt(-get)?\s+install\b",  # apt install
        r"\byum\s+install\b",  # yum install
        r"\bdnf\s+install\b",  # dnf install
        r"\bpacman\s+-S\b",  # pacman install
        r"\bsnap\s+install\b",  # snap install
        r"\bpip\s+install\b",  # pip install (in shell context)
        # -- Container / VM escape vectors --
        r"\bdocker\s+run\b",  # docker run
        r"\bdocker\s+exec\b",  # docker exec
        r"\bkubectl\s+exec\b",  # kubectl exec
        # -- Cron manipulation --
        r"\bcrontab\s+-[er]",  # edit/remove crontab
        # -- Shell metacharacter abuse / code injection --
        r"\beval\b",  # eval command execution
        r"\bexec\s",  # exec command replacement
        r"\bsource\s",  # source arbitrary scripts
        r"\b\.\s+/",  # . /path (source shorthand)
        r"`[^`]+`",  # backtick command substitution
        r"\$\([^)]*\b(rm|curl|wget|nc|ssh|dd|mkfs)\b",  # $() with dangerous commands
        r"\bxargs\b.*\b(rm|sh|bash)\b",  # xargs piping to dangerous commands
        # -- Indirect execution (bypass vectors) --
        r"\bsh\s+-c\b",  # sh -c (indirect execution)
        r"\bbash\s+-c\b",  # bash -c (indirect execution)
        r"\bdash\s+-c\b",  # dash -c (indirect execution)
        r"\bzsh\s+-c\b",  # zsh -c (indirect execution)
        r"\$\{[^}]*\b(rm|curl|wget|nc|ssh|dd|mkfs|sh|bash)\b",  # ${} with dangerous cmds
        r"<<-?\s*['\"]?\w+",  # here-document (<<EOF, <<'EOF', <<-EOF)
        r"\|\s*&",  # coprocess (|&)
        # -- Interpreter-based code execution --
        r"\bpython[23]?\s+-c\b",  # python -c arbitrary code
        r"\bperl\s+-e\b",  # perl -e arbitrary code
        r"\bruby\s+-e\b",  # ruby -e arbitrary code
        r"\bnode\s+-e\b",  # node -e arbitrary code
        r"\bphp\s+-r\b",  # php -r arbitrary code
        r"\blua\s+-e\b",  # lua -e arbitrary code
        r"\bawk\s+.*\bsystem\b",  # awk system() calls
        # -- Encoding-based bypass attempts --
        r"\bbase64\b.*\|\s*(ba)?sh\b",  # base64 decode piped to shell
        r"\bprintf\b.*\|\s*(ba)?sh\b",  # printf piped to shell
        r"\becho\b.*\|\s*(ba)?sh\b",  # echo piped to shell
        # -- Background processes / persistence --
        r"\bnohup\b",  # nohup for process persistence
        r"\bdisown\b",  # disown for detaching processes
        r"\bscreen\b",  # screen sessions
        r"\btmux\b",  # tmux sessions
        # -- Environment variable exfiltration --
        r"^\s*env\s*$",  # bare 'env' dumps all env vars
        r"\bprintenv\b",  # printenv dumps env vars
        r"\bset\s*$",  # bare 'set' dumps shell vars
        # -- Writing to sensitive system files --
        r"\btee\b.*(/etc/|/var/spool|\.ssh/|\.env|\.bashrc|\.profile)",
        # -- History manipulation --
        r"\bhistory\b",  # history access
    ]
]

# Built-in allowlist for strict production environments.
# Only these command prefixes are permitted when allowlist mode is active.
DEFAULT_ALLOWLIST: list[str] = [
    r"^git\s",  # git commands
    r"^ls\b",  # directory listing
    r"^cat\s",  # file viewing
    r"^head\s",  # file head
    r"^tail\s",  # file tail
    r"^grep\s",  # search
    r"^find\s",  # file search
    r"^wc\b",  # word count
    r"^sort\b",  # sorting
    r"^diff\b",  # diff
    r"^echo\s",  # echo
    r"^pwd\s*$",  # current directory
    r"^mkdir\s",  # create directory
    r"^touch\s",  # create file
    r"^cp\s",  # copy
    r"^mv\s",  # move
    r"^python3?\s(?!-c)",  # python (but not -c)
    r"^node\s(?!-e)",  # node (but not -e)
    r"^npm\s",  # npm
    r"^pip\s(?!install)",  # pip (but not install in shell)
    r"^cargo\b",  # rust
    r"^make\b",  # make
    r"^cmake\b",  # cmake
    r"^test\s",  # test / [ ] conditionals
    r"^stat\s",  # file info
    r"^file\s",  # file type detection
    r"^realpath\s",  # resolve path
    r"^basename\s",  # path basename
    r"^dirname\s",  # path dirname
]


class CommandFilterError(PermissionError):
    """Raised when a command matches a blocked pattern."""

    def __init__(self, command: str, pattern: str):
        super().__init__(f"Blocked dangerous command: '{command}' matches pattern '{pattern}'")
        self.command = command
        self.pattern = pattern


# Pre-compiled patterns for structural bypass detection
_HEX_ESCAPE_RE = re.compile(r"\\x[0-9a-fA-F]{2}")
_ANSI_C_QUOTE_RE = re.compile(r"\$'[^']*\\[xnr0]")
_OCTAL_IP_RE = re.compile(r"0[0-7]{3,}")


class CommandFilter:
    """Validates shell commands against deny/allow patterns."""

    def __init__(
        self,
        extra_deny: list[str] | None = None,
        allowlist: list[str] | None = None,
    ):
        self._deny = list(DENY_PATTERNS)
        if extra_deny:
            self._deny.extend(re.compile(p, re.IGNORECASE) for p in extra_deny)

        self._allowlist: list[re.Pattern] | None = None
        if allowlist:
            self._allowlist = [re.compile(p) for p in allowlist]

    def _pre_check(self, command: str):
        """Structural pre-checks to catch bypass techniques before regex matching."""
        # Null bytes can bypass C-level path checks
        if "\x00" in command:
            raise CommandFilterError(command, "null byte in command")

        # Multi-line commands can hide dangerous operations after a safe first line
        if "\n" in command:
            raise CommandFilterError(command, "newline in command (multi-line injection)")

        # Hex escape sequences can encode blocked commands
        if _HEX_ESCAPE_RE.search(command):
            raise CommandFilterError(command, "hex escape sequence (potential encoding bypass)")

        # ANSI-C quoting ($'...') with escape sequences can bypass pattern matching
        if _ANSI_C_QUOTE_RE.search(command):
            raise CommandFilterError(
                command, "ANSI-C quoting with escape (potential encoding bypass)"
            )

        # Octal IP addresses can bypass SSRF protections (e.g., 0177.0.0.1 == 127.0.0.1)
        if _OCTAL_IP_RE.search(command):
            raise CommandFilterError(command, "octal IP address (potential SSRF bypass)")

    def check(self, command: str) -> str:
        """Validate a command. Returns the command if safe, raises if blocked.

        Evaluation order:
        1. Structural pre-checks (null bytes, newlines, encoding bypasses)
        2. Allowlist check (if configured — command must match at least one pattern)
        3. Deny-list check (command must not match any blocked pattern)
        """
        # Layer 0: Structural pre-checks
        self._pre_check(command)

        # Layer 1: Allowlist (strict mode — if set, only matching commands pass)
        if self._allowlist is not None:
            if not any(p.search(command) for p in self._allowlist):
                raise CommandFilterError(command, "not in allowlist")

        # Layer 2: Deny-list (default mode — blocked patterns are rejected)
        for pattern in self._deny:
            if pattern.search(command):
                raise CommandFilterError(command, pattern.pattern)

        return command
