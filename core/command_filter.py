"""
Command filter — blocks dangerous shell patterns before execution.

Deny-list approach with optional allowlist for strict environments.
Patterns derived from common destructive commands that agents should never run.

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
        r"\brm\s+(-[a-z]*f[a-z]*\s+)?/",       # rm -rf / (root deletion)
        r"\brm\s+-[a-z]*r[a-z]*\s+-[a-z]*f",    # rm -rf variants
        r"\bdd\s+.*of\s*=\s*/dev/",              # dd to device
        r"\bmkfs\b",                              # format filesystem
        r"\bformat\b.*[A-Z]:",                    # Windows format
        r":\(\)\s*\{\s*:\|:\s*&\s*\};:",          # fork bomb
        r">\s*/dev/sda",                          # write to disk device
        r"\bchmod\s+-R\s+777\s+/\s*$",           # chmod -R 777 /
        r"\bchown\s+-R\s+.*\s+/\s*$",            # chown -R ... /

        # -- System control --
        r"\bshutdown\b",                          # shutdown
        r"\breboot\b",                            # reboot
        r"\bpoweroff\b",                          # poweroff
        r"\bhalt\b",                              # halt
        r"\binit\s+0\b",                          # init 0
        r"\bsystemctl\s+(stop|disable|mask|restart)\b",  # service manipulation
        r"\bservice\s+\w+\s+(stop|restart)\b",   # sysvinit service control

        # -- Remote code execution / exfiltration --
        r"\bwget\b.*\|\s*\b(ba)?sh\b",           # wget pipe to shell
        r"\bcurl\b.*\|\s*\b(ba)?sh\b",           # curl pipe to shell
        r"\bcurl\b.*--upload-file\b",             # curl file upload
        r"\bcurl\b.*-T\s",                        # curl file upload shorthand
        r"\bscp\b",                               # scp file transfer
        r"\brsync\b.*[^/]:",                      # rsync to remote host
        r"\bsftp\b",                              # sftp transfer
        r"\bftp\b",                               # ftp transfer

        # -- Network listeners / tunnels --
        r"\bnc\s+-[a-z]*l",                       # netcat listener
        r"\bsocat\b.*LISTEN",                     # socat listener
        r"\bssh\s+-[a-z]*R\b",                    # ssh reverse tunnel
        r"\bssh\s+-[a-z]*D\b",                    # ssh SOCKS proxy

        # -- Firewall / network --
        r"\biptables\s+-F",                       # flush iptables
        r"\bufw\s+(disable|reset)\b",             # disable firewall

        # -- User / permission escalation --
        r"\buseradd\b",                           # add user
        r"\buserdel\b",                           # delete user
        r"\bpasswd\b",                            # change password
        r"\bvisudo\b",                            # edit sudoers
        r"\bchattr\b",                            # change file attributes

        # -- Package management (prevent installing arbitrary software) --
        r"\bapt(-get)?\s+install\b",              # apt install
        r"\byum\s+install\b",                     # yum install
        r"\bdnf\s+install\b",                     # dnf install
        r"\bpacman\s+-S\b",                       # pacman install
        r"\bsnap\s+install\b",                    # snap install

        # -- Container / VM escape vectors --
        r"\bdocker\s+run\b",                      # docker run
        r"\bdocker\s+exec\b",                     # docker exec
        r"\bkubectl\s+exec\b",                    # kubectl exec

        # -- Cron manipulation --
        r"\bcrontab\s+-[er]",                     # edit/remove crontab
    ]
]


class CommandFilterError(PermissionError):
    """Raised when a command matches a blocked pattern."""

    def __init__(self, command: str, pattern: str):
        super().__init__(f"Blocked dangerous command: '{command}' matches pattern '{pattern}'")
        self.command = command
        self.pattern = pattern


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

    def check(self, command: str) -> str:
        """Validate a command. Returns the command if safe, raises if blocked."""
        # If allowlist is set, command must match at least one allowlist pattern
        if self._allowlist is not None:
            if not any(p.search(command) for p in self._allowlist):
                raise CommandFilterError(command, "not in allowlist")

        # Check deny patterns
        for pattern in self._deny:
            if pattern.search(command):
                raise CommandFilterError(command, pattern.pattern)

        return command
