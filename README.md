# Automated testing for Vendomatic

The goal of this repository is to show my work in learning to use Robot Framework for automated testing of Vendomatic, a small toy vending machine Python library I had Claude Opus write for me.

`tests/vendomatic.robot` and `resources/vendomatic.resource` are the main files to show my work.

## Project structure

| Path | What it is |
| --- | --- |
| `README.md` | This file: what the repository is for, and how it is laid out. |
| `VENDOMATIC.md` | The Vendomatic library's own documentation — the domain, its modules, the Python/CLI/HTTP entry points and the errors each one raises. The system under test, so the reference when writing tests. |
| `src/vendomatic/` | The Vendomatic library itself: pure Python, standard library only. `machine.py`, `inventory.py` and `money.py` are the domain; `cli.py` and `server.py` wrap it as a program and an HTTP API; `storage.py`, `maintenance.py` and `errors.py` cover state files, background jobs and failures. |
| `tests/` | The Robot Framework suites. `vendomatic.robot` tests the library; `demo.robot` is a smoke test that only proves the tooling runs. Run them with `robot tests/`. |
| `resources/` | The Robot resource directory. `vendomatic.resource` provides keywords for the tests. |
| `pyproject.toml` | Packaging for `vendomatic` (setuptools, `src/` layout) and the `vendomatic` console script. |
| `flake.nix` | Entry point of the Nix flake: the dev shell (`nix develop`) and the packages that make up the toolchain. |
| `flake.lock` | Pinned versions of the flake's inputs. |
| `nix/` | What `flake.nix` imports. `toolchain.nix` builds the single Python environment holding Robot Framework, Robocop and RobotCode; `python-packages.nix` packages the RobotCode distributions that nixpkgs does not have yet. |
