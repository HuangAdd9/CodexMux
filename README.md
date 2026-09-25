# CodexMux

A lightweight multiplexer for isolated Codex CLI accounts, sessions, history synchronization, and safe resume workflows.

CodexMux provides experimental Linux wrappers for account-isolated Codex CLI sessions and conservative cross-account history synchronization. This is an independent community tool, not an official OpenAI product.

## Status

Open-source under the Apache License 2.0. No accounts, credentials, production conversations, or operational databases are included.

The snapshot has 53 regression tests. The current compatibility check uses Codex CLI 0.156.1; earlier daemon reattachment checks also covered an app server at 0.153.0. These observations are not a compatibility guarantee for other releases. The wrappers depend on internal history and app-server details that can change.

## Features

- Create separate account homes without logging in; authentication remains handled by Codex.
- Show the live ChatGPT Codex limit windows for every logged-in account.
- Run different sessions concurrently, including sessions using the same account.
- Find an explicit session UUID across local account homes and import compatible history.
- Recognize compatible legacy and paginated copies by stable history IDs when their byte layouts differ.
- Import required `history_base` ancestors without replacing divergent branches.
- Coordinate explicit session access across cooperating wrappers on the same machine.
- Reattach an eligible detached interactive session to its verified local app server.
- Verify an explicitly requested provider during supported daemon reattachment, refusing an ignored change.

## Layout

```text
bin/codex-account       Account selection and isolated CODEX_HOME
bin/codex-account-limits Concurrent ChatGPT Codex limit queries
bin/codex-session-sync  History synchronization, locks, daemon reattachment
bin/codex               Optional transparent routing of plain codex commands
tests/                  Synthetic regression fixtures and mocked app servers
```

## Requirements

- Linux with `/proc/locks`, Unix sockets and `SO_PEERCRED`.
- Bash, Python 3.10+, GNU coreutils/findutils and util-linux `flock`.
- A separately installed Codex CLI.
- The account's normal Codex authentication and network access.

Python code uses only the standard library. macOS and native Windows are not supported by this snapshot. WSL has not been validated. The tool does not configure proxies or provide model access.

## Try without installing

Keep the native Codex executable on PATH. From this repository, use a subshell so the environment overrides do not persist:

```bash
(
  export CODEX_SESSION_SYNC_BIN="$PWD/bin/codex-session-sync"
  export CODEX_ACCOUNT_LIMITS_BIN="$PWD/bin/codex-account-limits"
  ./bin/codex-account --add personal
  ./bin/codex-account personal login --device-auth
  ./bin/codex-account personal login status
)
```

Creating `personal` only creates its directory. Login is a separate, explicit step. Existing accounts are not overwritten. `--list` lists accounts with an `auth.json`, not every empty account directory and not a live authentication check.

```bash
(
  export CODEX_SESSION_SYNC_BIN="$PWD/bin/codex-session-sync"
  export CODEX_ACCOUNT_LIMITS_BIN="$PWD/bin/codex-account-limits"
  ./bin/codex-account --list
  ./bin/codex-account --lslimit
  ./bin/codex-account personal resume SESSION_ID
)
```

`--lslimit` queries the official Codex app-server `account/rateLimits/read`
method for every account that has an `auth.json`. It prints each primary and
secondary quota window with used percentage, remaining percentage and reset
time in `Asia/Shanghai`. Accounts are queried concurrently (four at a time by default); a failed
or expired account is reported without hiding successful results from other
accounts. Set `CODEX_ACCOUNT_LIMIT_WORKERS` or
`CODEX_ACCOUNT_LIMIT_TIMEOUT_SEC` to positive integers when the defaults are
not suitable. The command is read-only with respect to quotas and does not
consume a reset credit.

Replace `SESSION_ID` with your own UUID. The default account home is `~/.codex-accounts/personal`; the shared history search home is `~/.codex`. The wrapper requests the `openai` provider and file-based authentication by default. An explicit later `-c model_provider=...` argument is preserved; it does not create the provider configuration or validate access to that provider.

The wrapper also links the shared `AGENTS.md`, `skills`, and `rules` into an account home when absent. Account homes isolate Codex state, not operating-system permissions or instructions. Review `SECURITY.md` before importing sensitive sessions between accounts.

## Optional plain `codex resume` routing

`bin/codex` shadows the native command; enabling it is optional. Test it in a subshell instead of replacing an existing executable:

```bash
(
  export CODEX_REAL_BIN="$(command -v codex)"
  export CODEX_SESSION_SYNC_BIN="$PWD/bin/codex-session-sync"
  export PATH="$PWD/bin:$PATH"
  codex resume SESSION_ID
)
```

`CODEX_REAL_BIN` must point to the native Codex executable or its official launcher, NOT an existing routing wrapper. If your shell already uses a wrapper, set the native path explicitly. Exiting the subshell removes these routing overrides; no shell startup file or installed executable is changed. Sessions created during use remain in their account homes.

Plain `codex` always uses the main home (`~/.codex` or `CODEX_SHARED_HOME`), unless an explicit `CODEX_HOME` overrides it. Only `codex-account NAME` selects a named account. Explicit-ID commands still search all account homes for compatible history, but never select credentials by history source, file size or provider. Provider arguments are passed through; the main home's default provider is not changed. A session picker without a UUID only sees the main home's available sessions, not every unimported account history.

## Configuration

| Variable | Default / purpose |
| --- | --- |
| `CODEX_SHARED_HOME` | `~/.codex`; shared history search home |
| `CODEX_ACCOUNTS_HOME` | `~/.codex-accounts`; account homes |
| `CODEX_ACCOUNT_LOCK_HOME` | `~/.cache/codex-account/locks`; shared local coordination locks |
| `CODEX_SESSION_SYNC_BIN` | `~/bin/codex-session-sync`; synchronization helper |
| `CODEX_ACCOUNT_LIMITS_BIN` | `~/bin/codex-account-limits`; account limit helper |
| `CODEX_ACCOUNT_LIMIT_WORKERS` | `4`; concurrent account status requests |
| `CODEX_ACCOUNT_LIMIT_TIMEOUT_SEC` | `20`; timeout per account in seconds |
| `CODEX_REAL_BIN` | Explicit native executable for the optional router |

Use explicit Codex arguments and configure the provider in the appropriate account home. Selecting a provider does not select a different account home.

## Safety boundaries and troubleshooting

- **Divergent copies:** the tool refuses to merge independent histories. A larger file or newer modification time is not proof that it contains all messages. Known legacy and paginated layouts can be reconciled only when one logical history contains the other with matching shared records. Sequential use of stale copies can create a real branch even without simultaneous writers.
- **Not continuous synchronization:** imports happen during supported explicit-ID operations, not after every message. Old copies can remain in other account homes.
- **Active writer:** do not delete locks blindly. A detached native task may still run. Only verified supported local daemon reattachment is allowed; other conflicts fail closed.
- **Provider switching:** idle daemon resume may be verified; active turns are not forcibly switched. Existing subagents and future in-session forks are not covered by this guarantee. Other remote settings such as working directory remain subject to native Codex behavior.
- **Lock scope:** coordination is local, not a distributed lock across SSH hosts. Plain native clients can bypass wrapper coordination. Unqualified session pickers and in-session switches are not a guarantee of global UUID exclusion.
- **Parent history:** a complete, fixed local ancestor prefix can be read without taking an exclusive parent lock. Missing or incompatible lineage falls back to conservative checks.
- **Legacy migration:** a sessions symlink pointing exactly to the shared sessions directory is replaced with a real account-local directory. Explicit-ID imports provide the needed history; other symlink targets are rejected.
- **No automatic conflict repair:** this snapshot does not choose a divergent branch, merge databases, delete live writer locks, kill user tasks, or reset quotas.

## Tests

```bash
bash -n bin/codex bin/codex-account
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_*.py' -q
```

Tests use temporary homes, fabricated UUIDs and local mock services. They do not call a model or require authentication. `CODEX_TEST_BIN` can explicitly point tests to a different copy; by default tests target this repository, not `~/bin`.

## License

Licensed under the Apache License, Version 2.0. See [`LICENSE`](LICENSE).
