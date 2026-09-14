# Robot Framework tooling for Helix

A `flake-parts` flake that provides the editor toolchain Helix needs for
Robot Framework: the [RobotCode](https://robotcode.io) language server,
[Robocop](https://robocop.readthedocs.io) (linter **and** formatter), and
Robot Framework itself.

## Use it

```console
$ nix develop          # robot, rebot, libdoc, testdoc, robocop, robotcode, hx
$ hx tests/demo.robot
```

`.helix/languages.toml` in this repo wires the editor up, so the LSP is live as
soon as you open a `.robot` file. What you get:

| Feature | Provided by |
| --- | --- |
| Completion (keywords, variables, libraries, imports) | RobotCode |
| Hover docs, goto-definition, references, rename | RobotCode |
| Diagnostics — unknown keywords, bad imports, arg counts | RobotCode analyser |
| Diagnostics — style/lint | Robocop, in-process |
| `:format` and format-on-save | Robocop's formatter, via the LSP |
| Syntax highlighting, folding, semantic tokens | Helix's bundled grammar + RobotCode |

To get the same setup outside this project, copy `.helix/languages.toml` into
`~/.config/helix/languages.toml` and install the toolchain:

```console
$ nix profile install github:<you>/robotfw    # or: nix profile install .
```

## Something to test

[`src/vendomatic/`](src/vendomatic) is a self-contained toy vending machine --
a Python API, a JSON state file, a `vendomatic` command line program and a
JSON-over-HTTP server, all on the standard library. `nix develop` puts it on
`PYTHONPATH`, so `Library  vendomatic.machine` resolves and the language server
completes its keywords. [`VENDOMATIC.md`](VENDOMATIC.md) documents it.

## Why one Python environment

The language server imports Robot Framework, Robocop and your test libraries
**in-process** to resolve keywords, lint and format. They therefore have to
share a single interpreter, which is what `packages.robot-toolchain` is.

That is also why adding your project's libraries to the environment is what
makes completion and goto-definition work for *their* keywords, not just the
built-ins. Edit the `mkToolchain` call in [`nix/toolchain.nix`](nix/toolchain.nix):

```nix
toolchain = mkToolchain {
  extraPackages = ps: [
    ps.robotframework-seleniumlibrary
    ps.robotframework-requests
  ];
};
```

## Outputs

| Output | What it is |
| --- | --- |
| `packages.default` / `packages.robot-toolchain` | the combined environment; everything on one `PATH` |
| `packages.robotcode` | RobotCode CLI alone |
| `packages.robocop` | Robocop alone |
| `packages.robotframework` | Robot Framework alone |
| `apps.{robotcode,robocop,robot}` | `nix run .#robocop -- check tests/` |
| `devShells.default` | toolchain + Helix |
| `checks.toolchain-smoke` | asserts the three CLIs start and the LSP/DAP plugins are registered |
| `overlays.default` | adds the Python packages below to any nixpkgs |

## Packaging notes

Only Robot Framework itself is in nixpkgs; [`nix/python-packages.nix`](nix/python-packages.nix)
adds the rest:

- **RobotCode 2.7.0**, which upstream ships as one distribution per component
  (`robotcode`, `-core`, `-plugin`, `-robot`, `-jsonrpc2`, `-modifiers`,
  `-analyze`, `-runner`, `-language-server`, `-debugger`). They are PEP 420
  namespace packages under `robotcode.`, and the CLI discovers
  `language-server`/`debug`/`analyze` as pluggy entry points — so they must be
  installed together, not wrapped separately.
- **Robocop 9.0.0**.
- **typer 0.27.2**, overriding nixpkgs' 0.25.1. Robocop 9 imports typer's
  vendored click (`typer._click`), which only exists from typer 0.26 on.

`robotcode-plugin` is missing a `robotcode-core` dependency in its upstream
metadata; the overlay adds it.

The `repl` / `repl-server` components are deliberately left out: they pin
`prompt-toolkit != 3.0.52`, which is exactly the version in nixpkgs, and Helix
does not use them.

## Debugging

Configured and working. `:debug-start` offers four templates:

| Template | What it does |
| --- | --- |
| `suite` | prompts for a file or directory (with path completion) |
| `whole project` | debugs `.` without prompting |
| `suite (stop on entry)` | breaks as soon as the run starts |
| `suite (by tag)` | prompts for a target, then a tag to `--include` |

Set breakpoints with `:debug-breakpoint`, then `:debug-start`. Robot Framework
keywords appear as stack frames, and suite/test variables show up in the
variables view. Suite output is streamed into Helix's debug output; results land
in `results/` (RobotCode's default output directory).

Two things matter in `.helix/languages.toml`, both easy to get wrong:

- **The adapter is `robotcode debug-launch`, not `robotcode debug`.** These are
  different programs. `debug` speaks DAP over TCP or a named pipe only,
  implements `attach` rather than `launch`, and takes the suite to run as
  *command-line* arguments — so the target could never be chosen from the
  editor, since Helix only substitutes template params into the DAP request.
  `debug-launch` speaks stdio, implements `launch` with a `target` argument, and
  spawns `debug` itself. It is the adapter VS Code drives, and it is hidden from
  `robotcode --help`.

  stdio also avoids a race in Helix's TCP transport: `tcp_process` sleeps 500 ms
  after spawning and then connects exactly once, with no retry — a margin a
  Python adapter that imports Robot Framework can easily miss.

- **`request` and `console` have to be set explicitly in each template's
  `args`.** Helix sends the template args as the DAP launch arguments but does
  not add a `request` field, and the launcher declares it as a required
  parameter. And the launcher's default `console` is `"integratedTerminal"`,
  which makes it send a `runInTerminal` reverse request; Helix only answers that
  if `[editor.terminal]` is configured, and otherwise fails the session with
  "No external terminal defined". `console = "internalConsole"` has the launcher
  run the suite itself and forward output as DAP events instead.

The launcher accepts far more than these templates use — `outputDir`,
`variables`, `variableFiles`, `robotPythonPath`, `profiles`, `exclude`,
`dryRun`, `mode`, `attachPython` — all settable as template `args`.
