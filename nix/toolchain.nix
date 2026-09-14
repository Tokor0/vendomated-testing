# flake-parts module: builds the Robot Framework toolchain that Helix drives.
#
# Everything lands in a *single* Python environment on purpose.  The RobotCode
# language server imports Robot Framework, Robocop and your test libraries
# in-process to resolve keywords, lint and format, so they all have to share
# one interpreter -- that is also why extending the environment with your
# project's libraries (SeleniumLibrary, RequestsLibrary, ...) is what makes
# completion and go-to-definition work for them.
{ lib, ... }:
{
  flake.overlays.default = final: prev: {
    pythonPackagesExtensions = (prev.pythonPackagesExtensions or [ ]) ++ [
      (import ./python-packages.nix { inherit lib; pkgs = final; })
    ];
  };

  perSystem =
    { pkgs, ... }:
    let
      python = pkgs.python3.override {
        self = python;
        packageOverrides = import ./python-packages.nix { inherit lib pkgs; };
      };

      # Programs the editor calls: robotcode (LSP + DAP + runner), robocop
      # (lint/format), robot/rebot/libdoc/testdoc (Robot Framework itself).
      mkToolchain =
        {
          extraPackages ? _ps: [ ],
        }:
        python.withPackages (
          ps:
          [
            ps.robotcode
            ps.robotcode-analyze
            ps.robotcode-debugger
            ps.robotcode-language-server
            ps.robotcode-runner
            ps.robotframework
            ps.robotframework-robocop
          ]
          ++ extraPackages ps
        );

      toolchain = mkToolchain { };
    in
    {
      _module.args.robotPython = python;

      packages = {
        default = toolchain;
        robot-toolchain = toolchain;

        # Individually usable, e.g. `nix run .#robocop -- check tests/`.
        robotcode = python.pkgs.robotcode;
        robocop = python.pkgs.robotframework-robocop;
        robotframework = python.pkgs.robotframework;
      };

      apps = {
        robotcode.program = "${toolchain}/bin/robotcode";
        robocop.program = "${toolchain}/bin/robocop";
        robot.program = "${toolchain}/bin/robot";
      };

      devShells.default = pkgs.mkShell {
        packages = [
          toolchain
          pkgs.helix
        ];

        shellHook = ''
          export HELIX_RUNTIME=${pkgs.helix}/lib/runtime

          # Put the Vendomatic sample library on the interpreter's path, so
          # both `robot` and the in-process language server can import it.
          export PYTHONPATH="$PWD/src''${PYTHONPATH:+:$PYTHONPATH}"

          # Only greet an interactive shell, so `nix develop -c ...` stays clean.
          if [[ $- == *i* ]]; then
            echo "Robot Framework toolchain:"
            echo "  robot     $(robot --version 2>&1 | head -1)"
            echo "  robocop   $(robocop --version)"
            echo "  robotcode $(robotcode --version)"
            echo "  vendomatic $(python -c 'import vendomatic; print(vendomatic.__version__)') (sample library on PYTHONPATH)"
            echo
            echo "Open a .robot file with 'hx' -- .helix/languages.toml wires up the LSP."
          fi
        '';
      };

      # `nix flake check` proves the pieces actually start up together.
      checks.toolchain-smoke =
        pkgs.runCommand "robot-toolchain-smoke"
          {
            nativeBuildInputs = [ toolchain ];
          }
          ''
            export HOME=$TMPDIR
            robot --version || true          # robot exits 251 on --version
            robocop --version
            robotcode --version
            # The language server and debug adapter are CLI plugins; if the
            # pluggy entry points were not visible these would not be listed.
            robotcode --help | grep -q language-server
            robotcode --help | grep -q debug
            # `debug-launch` is the DAP adapter Helix talks to. It is hidden
            # from --help, so probe it directly.
            robotcode debug-launch --help | grep -q -- --stdio
            touch $out
          '';
    };
}
